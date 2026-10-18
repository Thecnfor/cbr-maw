"""协同编排层测试：三模式同管线、R0-R5、冲突分类/仲裁、预算、HITL、trace。

全部使用 mock agent / stub provider / stub tool，不依赖 agent-core（task-3）落地，
也不访问真实网络与真实数据。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from cbr.config import AppSettings
from cbr.contracts import Orchestrator
from cbr.orchestration import (
    EvidenceBlackboard,
    HITLQueue,
    build_orchestrator,
    detect_conflicts,
)
from cbr.schemas import (
    AgentContext,
    AgentOutput,
    ChatRequest,
    Claim,
    ClaimStatus,
    ClaimType,
    ConflictType,
    DecisionCard,
    Evidence,
    EvidenceKind,
    ExperimentMode,
    MarketSnapshot,
    RiskCard,
    RiskDriver,
    RiskLevel,
    RiskSignal,
    Role,
    SourceRef,
    ToolRef,
    ToolResult,
)
from cbr.verification.trace import read_trace

AS_OF = date(2024, 8, 5)
ROLES = ("regulator", "investor", "financing")


# --------------------------------------------------------------------------- #
# Stub 数据层 / 工具层
# --------------------------------------------------------------------------- #
class StubProvider:
    """满足 contracts.DataProvider 的最小实现。"""

    def __init__(self, as_of: date = AS_OF, level: RiskLevel = RiskLevel.HIGH) -> None:
        self.as_of = as_of
        self.level = level

    def risk_signal(self, as_of: date) -> RiskSignal:
        return RiskSignal(
            as_of=as_of,
            model_version="stub-fusion-v1",
            horizons={5: 0.12, 10: 0.28, 20: 0.41},
            percentile=0.86,
            level=self.level,
            drivers=[RiskDriver(factor="northbound_outflow_z", contribution=0.31)],
            modality_contrib={"numeric": 0.72, "text": 0.28},
        )

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        return MarketSnapshot(as_of=as_of, series={"cn_equity": 1.0, "usdcny": 7.1})

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict]:
        return []

    def label(self, as_of: date, horizon: int) -> int | None:
        return None

    def data_cards(self) -> list:
        return []


class StubTool:
    """满足 contracts.Tool 的确定性工具；数值用于交叉验证。"""

    def __init__(
        self,
        name: str,
        value: float,
        *,
        unit: str = "index",
        payload: dict | None = None,
        fail: bool = False,
    ) -> None:
        self.name = name
        self.version = "1.0.0"
        self.description = f"stub {name}"
        self.unit = unit
        self.value = value
        self.payload = payload or {}
        self.fail = fail

    def run(self, as_of: date, **kwargs) -> ToolResult:
        if self.fail:
            raise RuntimeError(f"stub tool {self.name} failed")
        evidence_id = f"ev_tool_{self.name}_{as_of.isoformat()}"
        evidence = Evidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.TOOL,
            as_of=as_of,
            title=f"{self.name} 计算结果",
            summary=f"{self.name}={self.value}",
            payload={"value": self.value, **self.payload},
            value=self.value,
            unit=self.unit,
            tool=ToolRef(name=self.name, version=self.version, inputs_hash=f"in_{self.name}", elapsed_ms=3),
            produced_by="tools",
        )
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=as_of,
            ok=True,
            data={"value": self.value, **self.payload},
            unit=self.unit,
            evidence=evidence,
            elapsed_ms=3,
        )


class StubRegistry:
    """满足 contracts.ToolRegistry：默认三角色全部放行。"""

    def __init__(self, tools: list[StubTool], *, allow_all: bool = True) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.allow_all = allow_all
        self.denied: list[tuple[str, str]] = []

    def get(self, name: str):
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def allow(self, role, tool_name: str) -> bool:
        if tool_name not in self._tools:
            return False
        if self.allow_all:
            return True
        allowed = {
            Role.REGULATOR: {"capital_flow", "systemic_risk", "risk_measure", "funding_cost"},
            Role.INVESTOR: {"capital_flow", "risk_measure"},
            Role.FINANCING: {"funding_cost", "risk_measure", "systemic_risk"},
        }
        role_enum = role if isinstance(role, Role) else Role(str(role))
        if tool_name not in allowed.get(role_enum, set()):
            self.denied.append((role_enum.value, tool_name))
            return False
        return True


def make_tools(*, capital_flow_fail: bool = False) -> StubRegistry:
    return StubRegistry(
        [
            StubTool(
                "capital_flow",
                1.42,
                unit="z",
                payload={"label": "northbound_outflow_z"},
                fail=capital_flow_fail,
            ),
            StubTool("risk_measure", 0.03, unit="ratio"),
            StubTool("funding_cost", 0.85, unit="pct"),
            StubTool(
                "systemic_risk",
                0.41,
                unit="prob",
                payload={"direction": "up"},
            ),
            StubTool("forecast", 0.41, unit="prob"),
        ]
    )


# --------------------------------------------------------------------------- #
# Mock 智能体
# --------------------------------------------------------------------------- #
def make_evidence(role: str, subject: str, value: float, *, unit: str | None = None) -> Evidence:
    return Evidence(
        evidence_id=f"ev_{role}_{subject}",
        kind=EvidenceKind.TOOL,
        as_of=AS_OF,
        title=f"{subject}（{role} 工具证据）",
        summary=f"{subject}={value}",
        payload={"value": value, "subject": subject},
        value=value,
        unit=unit,
        tool=ToolRef(name="stub_tool", version="1.0.0", inputs_hash=f"{role}_{subject}", elapsed_ms=2),
        produced_by=role,
    )


def make_card(
    role: Role,
    claims: list[Claim],
    *,
    as_of: date = AS_OF,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    evidence_ids: list[str] | None = None,
    recommendation: str = "维持防御仓位，关注跨境资金与利差变化。",
    headline: str | None = None,
) -> RiskCard:
    return RiskCard(
        role=role,
        as_of=as_of,
        risk_level=risk_level,
        headline=headline or f"{role.value} 风险提示",
        base_signal_ref=None,
        key_metrics=[],
        claims=claims,
        recommendation=recommendation,
        decision_loss={"miss": 1.0},
        limitations=["stub 卡片"],
        evidence_ids=evidence_ids or sorted({eid for claim in claims for eid in claim.evidence_ids}),
        tool_calls=1,
        tokens=100,
        latency_ms=3,
        round=0,
    )


def numeric_claim(
    role: str,
    subject: str,
    value: float,
    evidence_id: str,
    *,
    unit: str | None = "z",
    text: str | None = None,
    confidence: float = 0.9,
) -> Claim:
    return Claim(
        claim_id=f"c_{role}_{subject}",
        role=role,
        claim_type=ClaimType.NUMERIC,
        subject=subject,
        text=text or f"{subject}={value}",
        value=value,
        unit=unit,
        evidence_ids=[evidence_id],
        confidence=confidence,
    )


def directional_claim(
    role: str,
    subject: str,
    direction: str,
    value: float,
    evidence_id: str,
    *,
    text: str | None = None,
) -> Claim:
    return Claim(
        claim_id=f"c_{role}_{subject}_{direction}",
        role=role,
        claim_type=ClaimType.DIRECTIONAL,
        subject=subject,
        text=text or f"{subject} 方向 {direction}",
        value=value,
        direction=direction,  # type: ignore[arg-type]
        evidence_ids=[evidence_id],
        confidence=0.8,
    )


class FakeRoleAgent:
    """可配置的 RoleAgent 替身，`.analyze(context) -> AgentOutput`。"""

    def __init__(
        self,
        role: Role,
        claims: list[Claim],
        evidence: list[Evidence] | None = None,
        *,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        fail: bool = False,
        tool_calls: int = 1,
        tokens: int = 100,
    ) -> None:
        self.role = role
        self.claims = claims
        self.evidence = evidence or []
        self.risk_level = risk_level
        self.fail = fail
        self.tool_calls = tool_calls
        self.tokens = tokens
        self.contexts: list[AgentContext] = []
        self.calls = 0

    def analyze(self, context: AgentContext) -> AgentOutput:
        self.calls += 1
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError(f"{self.role.value} agent 模拟失败")
        card = make_card(
            self.role,
            list(self.claims),
            as_of=context.as_of,
            risk_level=self.risk_level,
            recommendation="维持防御仓位，关注跨境资金与利差变化。",
        )
        return AgentOutput(
            role=self.role,
            card=card,
            evidence=list(self.evidence),
            tool_calls=self.tool_calls,
            tokens=self.tokens,
            latency_ms=5,
            trace=[],
        )


class FakeSingleAgent:
    """单智能体替身：一次 analyze 返回三张卡（SingleAgentResult 结构）。"""

    def __init__(self, agents: dict[Role, FakeRoleAgent]) -> None:
        self.agents = agents
        self.contexts: list[AgentContext] = []

    def analyze(self, context: AgentContext):
        self.contexts.append(context)
        cards = {}
        tool_calls = 0
        tokens = 0
        for role, agent in self.agents.items():
            output = agent.analyze(context)
            cards[role.value] = AgentOutput(
                role=role,
                card=output.card,
                evidence=list(output.evidence),
                tool_calls=output.tool_calls,
                tokens=output.tokens,
                latency_ms=output.latency_ms,
                trace=[],
            )
            tool_calls += output.tool_calls
            tokens += output.tokens
        return SimpleNamespace(cards=cards, tool_calls=tool_calls, tokens=tokens, latency_ms=12, trace=[])


# --------------------------------------------------------------------------- #
# 场景构造
# --------------------------------------------------------------------------- #
def happy_agents() -> dict[Role, FakeRoleAgent]:
    """三角色各 1 条数值 claim + 匹配的工具证据；无冲突。"""
    regulator_ev = make_evidence("regulator", "northbound_outflow_z", 1.42, unit="z")
    investor_ev = make_evidence("investor", "var_95", 0.03, unit="ratio")
    financing_ev = make_evidence("financing", "credit_spread", 0.85, unit="pct")
    return {
        Role.REGULATOR: FakeRoleAgent(
            Role.REGULATOR,
            [numeric_claim("regulator", "northbound_outflow_z", 1.42, regulator_ev.evidence_id)],
            [regulator_ev],
        ),
        Role.INVESTOR: FakeRoleAgent(
            Role.INVESTOR,
            [numeric_claim("investor", "var_95", 0.03, investor_ev.evidence_id, unit="ratio")],
            [investor_ev],
        ),
        Role.FINANCING: FakeRoleAgent(
            Role.FINANCING,
            [numeric_claim("financing", "credit_spread", 0.85, financing_ev.evidence_id, unit="pct")],
            [financing_ev],
        ),
    }


def fact_conflict_agents() -> dict[Role, FakeRoleAgent]:
    """regulator 与 investor 对同一 subject 报出不同数值 → fact conflict。"""
    reg_ev = make_evidence("regulator", "northbound_outflow_z", 1.42, unit="z")
    inv_ev = make_evidence("investor", "northbound_outflow_z", 2.50, unit="z")
    fin_ev = make_evidence("financing", "credit_spread", 0.85, unit="pct")
    return {
        Role.REGULATOR: FakeRoleAgent(
            Role.REGULATOR,
            [numeric_claim("regulator", "northbound_outflow_z", 1.42, reg_ev.evidence_id)],
            [reg_ev],
        ),
        Role.INVESTOR: FakeRoleAgent(
            Role.INVESTOR,
            [numeric_claim("investor", "northbound_outflow_z", 2.50, inv_ev.evidence_id)],
            [inv_ev],
        ),
        Role.FINANCING: FakeRoleAgent(
            Role.FINANCING,
            [numeric_claim("financing", "credit_spread", 0.85, fin_ev.evidence_id, unit="pct")],
            [fin_ev],
        ),
    }


def directional_conflict_agents() -> dict[Role, FakeRoleAgent]:
    """regulator 看涨、financing 看跌同一 subject → directional conflict。"""
    shared_ev = make_evidence("regulator", "stress_trend", 0.41, unit="prob")
    inv_ev = make_evidence("investor", "var_95", 0.03, unit="ratio")
    return {
        Role.REGULATOR: FakeRoleAgent(
            Role.REGULATOR,
            [directional_claim("regulator", "stress_trend", "up", 0.41, shared_ev.evidence_id)],
            [shared_ev],
        ),
        Role.INVESTOR: FakeRoleAgent(
            Role.INVESTOR,
            [numeric_claim("investor", "var_95", 0.03, inv_ev.evidence_id, unit="ratio")],
            [inv_ev],
        ),
        Role.FINANCING: FakeRoleAgent(
            Role.FINANCING,
            [directional_claim("financing", "stress_trend", "down", 0.41, shared_ev.evidence_id)],
            [],
        ),
    }


def preference_agents() -> dict[Role, FakeRoleAgent]:
    """三主体证据一致，但 regulator 判 up、investor 判 flat → preference divergence。"""
    shared_ev = make_evidence("regulator", "stress_prob_h20", 0.41, unit="prob")
    fin_ev = make_evidence("financing", "credit_spread", 0.85, unit="pct")
    return {
        Role.REGULATOR: FakeRoleAgent(
            Role.REGULATOR,
            [directional_claim("regulator", "stress_prob_h20", "up", 0.41, shared_ev.evidence_id)],
            [shared_ev],
        ),
        Role.INVESTOR: FakeRoleAgent(
            Role.INVESTOR,
            [directional_claim("investor", "stress_prob_h20", "flat", 0.41, shared_ev.evidence_id)],
            [],
        ),
        Role.FINANCING: FakeRoleAgent(
            Role.FINANCING,
            [numeric_claim("financing", "credit_spread", 0.85, fin_ev.evidence_id, unit="pct")],
            [fin_ev],
        ),
    }


def build(settings: AppSettings, agents: dict[Role, FakeRoleAgent], registry: StubRegistry | None = None):
    single = FakeSingleAgent(agents)
    orchestrator = build_orchestrator(
        settings,
        StubProvider(),
        registry or make_tools(),
        None,
        None,
        agents=agents,
        single_agent=single,
    )
    return orchestrator, single


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    app = AppSettings()
    app.orchestration.rounds = 1
    app.orchestration.max_tool_calls_per_agent = 4
    app.orchestration.max_tokens_per_agent = 1000
    app.orchestration.numeric_tolerance_abs = 1e-6
    app.orchestration.numeric_tolerance_rel = 1e-3
    app.orchestration.trace_dir = str(tmp_path / "traces")
    app.orchestration.human_in_the_loop = True
    return app


# --------------------------------------------------------------------------- #
# 1) 三模式均可产出 DecisionCard（同一代码路径 / 同一预算）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["single", "independent", "collaborative"])
def test_three_modes_produce_decision_card(settings: AppSettings, tmp_path: Path, mode: str) -> None:
    agents = happy_agents()
    orchestrator, single = build(settings, agents)
    assert isinstance(orchestrator, Orchestrator)  # 满足 contracts.Orchestrator

    decision = orchestrator.run(AS_OF, mode=mode)

    assert isinstance(decision, DecisionCard)
    assert decision.mode == ExperimentMode(mode)
    assert decision.run_id.startswith(f"{mode}_{AS_OF.isoformat()}_")
    assert set(decision.cards) == set(ROLES)
    for role, card in decision.cards.items():
        assert card.role.value == role
        assert card.as_of == AS_OF
        assert card.claims, f"{role} 卡片应有 claim"

    # trace / 决策卡产物可读回
    trace_path = Path(decision.trace_ref)
    assert trace_path.is_file(), f"trace 文件不存在: {trace_path}"
    events = read_trace(trace_path)
    assert events and all(event.run_id == decision.run_id for event in events)
    assert trace_path.with_suffix(".decision.json").is_file()
    assert orchestrator.get_trace(decision.run_id)

    # 证据快照 / 只读查询
    assert decision.evidence
    evidence_id = decision.evidence[0].evidence_id
    assert orchestrator.get_evidence(evidence_id) is not None
    assert orchestrator.get_evidence("ev_not_exists") is None

    # 预算对齐：三种模式总预算一致，实际用量不超上限
    plan = orchestrator.budget_plan(mode)
    assert plan["max_tool_calls"] == settings.orchestration.max_tool_calls_per_agent * 3
    assert decision.coordination.tool_calls <= plan["max_tool_calls"]
    assert decision.coordination.tokens <= plan["max_tokens"]

    # 协同成本折算：C = tool_calls*cost_per_tool_call + tokens/1k*cost_per_1k_tokens + latency_ms*cost_per_latency_ms
    coordination = decision.coordination
    expected_cost = round(
        coordination.tool_calls * settings.orchestration.cost_per_tool_call
        + coordination.tokens / 1000.0 * settings.orchestration.cost_per_1k_tokens
        + coordination.latency_ms * settings.orchestration.cost_per_latency_ms,
        8,
    )
    assert coordination.cost_usd == pytest.approx(expected_cost)
    assert coordination.cost_usd > 0
    assert "J = L + μ·C" in decision.final_advice
    assert f"μ={settings.orchestration.coordination_weight_mu}" in decision.final_advice

    # 证据快照去重
    evidence_ids = [evidence.evidence_id for evidence in decision.evidence]
    assert len(evidence_ids) == len(set(evidence_ids))

    # 核验器在干净场景下通过
    report = decision.verification
    assert report.numeric_error_rate == 0.0, report.issues
    assert report.evidence_accuracy == 1.0
    assert report.leakage_events == 0
    assert report.permission_violations == 0
    assert report.schema_errors == 0
    assert report.passed is True

    # 三模式预算上下文一致（每角色上限相同）
    contexts = [ctx for agent in agents.values() for ctx in agent.contexts]
    if mode == "single":
        contexts += single.contexts
    assert contexts
    for context in contexts:
        assert context.budget["max_tool_calls"] == settings.orchestration.max_tool_calls_per_agent
        assert context.budget["max_tokens"] == settings.orchestration.max_tokens_per_agent
        assert context.budget["run_id"] == decision.run_id


def test_single_mode_calls_single_agent_once(settings: AppSettings) -> None:
    agents = happy_agents()
    orchestrator, single = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode="single")
    # 编排器只调用一次 SingleAgent.analyze；三张卡由它一次产出
    assert len(single.contexts) == 1
    assert decision.coordination.rounds == 0
    assert decision.coordination.evidence_shared == 0


def test_independent_mode_has_no_coordination(settings: AppSettings) -> None:
    agents = happy_agents()
    orchestrator, _ = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode="independent")
    assert decision.conflicts == []
    assert decision.coordination.evidence_shared == 0
    assert decision.coordination.rounds == 0
    steps = {event.step for event in read_trace(decision.trace_ref)}
    assert steps == {"R0", "R5"}
    # 无共享 → 每个 agent 的 evidence 只在本角色卡片引用中解析
    assert len(decision.evidence) == 4  # signal + 3 工具证据


def test_collaborative_trace_covers_r0_to_r5(settings: AppSettings) -> None:
    orchestrator, _ = build(settings, happy_agents())
    decision = orchestrator.run(AS_OF, mode="collaborative")
    events = read_trace(decision.trace_ref)
    steps = {event.step for event in events}
    assert {"R0", "R1", "R2", "R3", "R4", "R5"} <= steps
    actions = {event.action for event in events}
    assert {"run_start", "analysis_start", "analysis_done", "cross_check", "conflict_detection", "conflict_resolution", "finalize"} <= actions
    # R0 三角色齐全
    r0_roles = {event.role for event in events if event.step == "R0" and event.action == "analysis_done"}
    assert set(ROLES) <= r0_roles


# --------------------------------------------------------------------------- #
# 2) 冲突分类：fact / directional / preference + 解决
# --------------------------------------------------------------------------- #
def test_fact_conflict_detected_and_resolved_by_tool(settings: AppSettings) -> None:
    agents = fact_conflict_agents()
    orchestrator, _ = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode="collaborative")

    assert decision.coordination.conflicts_total >= 1
    fact = next(conflict for conflict in decision.conflicts if conflict.type == ConflictType.FACT)
    assert "northbound_outflow_z" in fact.subject
    assert fact.resolved is True
    assert fact.resolved_by == "tool"
    assert set(fact.roles) >= {"regulator", "investor"}

    regulator_claim = decision.cards["regulator"].claims[0]
    investor_claim = decision.cards["investor"].claims[0]
    assert regulator_claim.status == ClaimStatus.VERIFIED
    assert investor_claim.status == ClaimStatus.REJECTED

    # trace 中 R3/R4 有完整记录
    actions = [(event.step, event.action) for event in read_trace(decision.trace_ref)]
    assert ("R3", "conflict_detection") in actions
    assert any(step == "R4" and action == "conflict_resolved" for step, action in actions)


def test_directional_conflict_resolved_by_supplementary_tool_evidence(settings: AppSettings) -> None:
    agents = directional_conflict_agents()
    orchestrator, _ = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode="collaborative")

    directional = [
        conflict for conflict in decision.conflicts if conflict.type == ConflictType.DIRECTIONAL
    ]
    assert directional, decision.conflicts
    conflict = directional[0]
    assert "stress_trend" in conflict.subject
    assert conflict.resolved is True
    assert conflict.resolved_by == "tool"

    regulator_claim = decision.cards["regulator"].claims[0]
    financing_claim = next(
        claim
        for claim in decision.cards["financing"].claims
        if claim.subject == "stress_trend"
    )
    # 工具 payload 方向为 up → regulator 被采纳、financing 被驳回
    assert regulator_claim.status == ClaimStatus.VERIFIED
    assert financing_claim.status == ClaimStatus.REJECTED
    # 方向冲突通过 R4 补充工具证据解决，工具调用计入协同成本
    actions = [(event.step, event.action) for event in read_trace(decision.trace_ref)]
    assert ("R4", "tool_call") in actions
    assert decision.coordination.tool_calls >= 4


def test_preference_divergence_kept_and_not_error(settings: AppSettings) -> None:
    agents = preference_agents()
    orchestrator, _ = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode="collaborative")

    preferences = [
        conflict for conflict in decision.conflicts if conflict.type == ConflictType.PREFERENCE
    ]
    assert preferences, [(c.type, c.subject, c.description) for c in decision.conflicts]
    conflict = preferences[0]
    assert conflict.resolved is True
    assert conflict.resolved_by == "consensus"
    assert conflict.resolution
    assert decision.coordination.conflicts_escalated == 0

    regulator_claim = decision.cards["regulator"].claims[0]
    investor_claim = decision.cards["investor"].claims[0]
    assert regulator_claim.status == ClaimStatus.PREFERENCE
    assert investor_claim.status == ClaimStatus.PREFERENCE
    # 偏好差异不得被误判为错误
    assert decision.verification.numeric_error_rate == 0.0
    assert decision.verification.passed is True
    assert not [issue for issue in decision.verification.issues if issue.issue_type == "numeric"]
    assert "偏好" in decision.final_advice


def test_unresolved_conflict_escalates_to_hitl(settings: AppSettings) -> None:
    agents = fact_conflict_agents()
    orchestrator, _ = build(settings, agents, make_tools(capital_flow_fail=True))
    decision = orchestrator.run(AS_OF, mode="collaborative")

    unresolved = [conflict for conflict in decision.conflicts if not conflict.resolved]
    assert unresolved, decision.conflicts
    assert unresolved[0].resolved_by == "unresolved"
    assert decision.coordination.conflicts_escalated >= 1
    assert "需人工复核" in decision.final_advice

    items = orchestrator.pending_hitl(decision.run_id)
    assert items and any(item.kind == "unresolved_conflict" for item in items)
    assert all(item.status == "auto_processed" for item in items)
    actions = [(event.step, event.action) for event in read_trace(decision.trace_ref)]
    assert ("R4", "hitl_escalate") in actions
    assert any(step == "HITL" for step, _ in actions)

    # 人工 approve/reject/override 均写回 trace
    item = items[0]
    before = len(read_trace(decision.trace_ref))
    updated = orchestrator.record_hitl_decision(item.item_id, "approve", note="人工确认")
    after = read_trace(decision.trace_ref)
    assert updated.status == "approved"
    assert len(after) == before + 1
    assert after[-1].action == "hitl"
    assert after[-1].detail.get("event") == "approve"
    with pytest.raises(ValueError):
        orchestrator.record_hitl_decision(item.item_id, "unknown")
    with pytest.raises(KeyError):
        orchestrator.record_hitl_decision("hitl_not_exists", "approve")


# --------------------------------------------------------------------------- #
# 3) 失败降级：单角色异常不拖垮整体
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["independent", "collaborative"])
def test_single_role_failure_degrades_gracefully(settings: AppSettings, mode: str) -> None:
    agents = happy_agents()
    agents[Role.INVESTOR].fail = True
    orchestrator, _ = build(settings, agents)
    decision = orchestrator.run(AS_OF, mode=mode)

    assert set(decision.cards) == set(ROLES)
    investor_card = decision.cards["investor"]
    assert investor_card.claims == []
    assert any("模拟失败" in limitation for limitation in investor_card.limitations)
    assert "降级" in investor_card.headline
    # 其他角色不受影响
    assert decision.cards["regulator"].claims
    assert decision.cards["financing"].claims
    actions = [(event.step, event.action) for event in read_trace(decision.trace_ref)]
    assert ("R0", "agent_error") in actions
    assert "降级说明" in decision.final_advice
    # 决策卡依然产出且核验器可跑
    assert decision.verification.schema_errors == 0


def test_single_agent_failure_degrades_all_roles(settings: AppSettings) -> None:
    agents = happy_agents()

    class BrokenSingle:
        def analyze(self, context):  # noqa: ANN001
            raise RuntimeError("single agent 崩了")

    orchestrator = build_orchestrator(
        settings,
        StubProvider(),
        make_tools(),
        None,
        None,
        agents=agents,
        single_agent=BrokenSingle(),
    )
    decision = orchestrator.run(AS_OF, mode="single")
    assert set(decision.cards) == set(ROLES)
    assert all(card.claims == [] for card in decision.cards.values())
    assert "降级说明" in decision.final_advice


def test_hitl_queue_actions_write_trace(tmp_path: Path) -> None:
    from cbr.verification.trace import TraceWriter

    def trace_factory(run_id: str) -> TraceWriter:
        return TraceWriter(run_id, tmp_path / "traces")

    queue = HITLQueue(trace_factory=trace_factory)
    approve_item = queue.enqueue("verification_failure", "数值核验未通过", run_id="hitl_run")
    reject_item = queue.enqueue("unresolved_conflict", "未解决冲突", run_id="hitl_run", payload={"conflict_id": "cf_x"})
    override_item = queue.enqueue("high_risk", "极高风险", run_id="hitl_run")
    assert len(queue.pending()) == 3
    processed = queue.auto_process(run_id="hitl_run")
    assert len(processed) == 3
    assert all(item.status == "auto_processed" for item in processed)
    assert all(item.auto_policy == "escalate" for item in processed)

    queue.approve(approve_item.item_id, note="确认")
    queue.reject(reject_item.item_id, note="驳回冲突结论")
    queue.override(override_item.item_id, {"final_advice": "人工覆盖建议"}, note="覆盖")
    assert queue.get(approve_item.item_id).status == "approved"
    assert queue.get(reject_item.item_id).status == "rejected"
    assert queue.get(override_item.item_id).status == "overridden"
    assert queue.get(override_item.item_id).payload["replacement"]["final_advice"] == "人工覆盖建议"
    assert queue.needs_review()  # auto_policy=escalate 的事项仍需人工复核

    events = read_trace(TraceWriter("hitl_run", tmp_path / "traces").path)
    actions = [event.detail.get("event") for event in events]
    assert "enqueue" in actions
    assert "auto_process" in actions
    assert {"approve", "reject", "override"} <= set(actions)
    queue.clear()
    assert queue.items == []


# --------------------------------------------------------------------------- #
# 4) 黑板 / 冲突分类纯函数
# --------------------------------------------------------------------------- #
def test_blackboard_dedup_by_tool_inputs_hash() -> None:
    board = EvidenceBlackboard()
    first = make_evidence("regulator", "northbound_outflow_z", 1.42, unit="z")
    duplicate = first.model_copy(update={"evidence_id": "ev_duplicate_alias"})
    first_id = board.add(first, role=Role.REGULATOR)
    second_id = board.add(duplicate, role=Role.INVESTOR)
    assert first_id == second_id == first.evidence_id
    assert board.evidence_shared == 1
    assert board.duplicate_evidence == 1
    assert board.resolve_id("ev_duplicate_alias") == first.evidence_id
    assert board.get("ev_duplicate_alias") is not None
    assert board.contains_equivalent(duplicate) is True
    assert len(board) == 1
    assert set(board.index()) == {"ev_regulator_northbound_outflow_z", "ev_duplicate_alias"}


def test_detect_conflicts_classification_rules(settings: AppSettings) -> None:
    reg_ev = make_evidence("regulator", "northbound_outflow_z", 1.42, unit="z")
    inv_ev = make_evidence("investor", "northbound_outflow_z", 2.50, unit="z")
    fact_claims = [
        numeric_claim("regulator", "northbound_outflow_z", 1.42, reg_ev.evidence_id),
        numeric_claim("investor", "northbound_outflow_z", 2.50, inv_ev.evidence_id),
    ]
    conflicts = detect_conflicts(fact_claims)
    assert [conflict.type for conflict in conflicts] == [ConflictType.FACT]

    up = directional_claim("regulator", "stress_trend", "up", 0.41, "ev_shared")
    down = directional_claim("financing", "stress_trend", "down", 0.41, "ev_shared")
    directional = detect_conflicts([up, down])
    assert [conflict.type for conflict in directional] == [ConflictType.DIRECTIONAL]

    up2 = directional_claim("regulator", "stress_prob_h20", "up", 0.41, "ev_shared")
    flat = directional_claim("investor", "stress_prob_h20", "flat", 0.41, "ev_shared")
    preference = detect_conflicts([up2, flat])
    assert [conflict.type for conflict in preference] == [ConflictType.PREFERENCE]


# --------------------------------------------------------------------------- #
# 5) chat / run_all_modes / 参数校验
# --------------------------------------------------------------------------- #
def test_chat_returns_reply_and_trace(settings: AppSettings) -> None:
    orchestrator, _ = build(settings, happy_agents())
    response = orchestrator.chat(ChatRequest(message="当前跨境风险如何？", as_of=AS_OF, mode="collaborative"))
    assert response.reply and "协同预警分析" in response.reply
    assert response.as_of == AS_OF
    assert response.decision is not None
    assert response.trace_id == response.decision.run_id
    assert orchestrator.get_trace(response.trace_id)
    assert isinstance(response.citations, list)


def test_run_all_modes_returns_three_cards(settings: AppSettings) -> None:
    orchestrator, _ = build(settings, happy_agents())
    decisions = orchestrator.run_all_modes(AS_OF)
    assert set(decisions) == {"single", "independent", "collaborative"}
    for mode, decision in decisions.items():
        assert decision.mode.value == mode
        assert set(decision.cards) == set(ROLES)


def test_invalid_mode_raises(settings: AppSettings) -> None:
    orchestrator, _ = build(settings, happy_agents())
    with pytest.raises(ValueError):
        orchestrator.run(AS_OF, mode="unknown-mode")


def test_disabled_mode_raises(settings: AppSettings) -> None:
    settings.orchestration.modes = ["single"]
    orchestrator, _ = build(settings, happy_agents())
    with pytest.raises(ValueError):
        orchestrator.run(AS_OF, mode="collaborative")


def test_agents_lazy_import_error_is_clear(settings: AppSettings) -> None:
    """未注入 agent 且 cbr.agents 未就绪时，run 应降级而不是崩溃。"""
    orchestrator = build_orchestrator(settings, StubProvider(), make_tools(), None, None)
    decision = orchestrator.run(AS_OF, mode="collaborative")
    assert set(decision.cards) == set(ROLES)
    assert all(card.claims == [] for card in decision.cards.values())
