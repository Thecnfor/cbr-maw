"""协同编排 mock 演示：对样例 as_of 跑三模式，产出 DecisionCard JSON + trace JSONL。

用法::

    .venv\\Scripts\\python.exe -m cbr.orchestration.demo                 # 默认 2024-08-05
    .venv\\Scripts\\python.exe -m cbr.orchestration.demo --as-of 2020-03-16
    .venv\\Scripts\\python.exe -m cbr.orchestration.demo --real          # 全模块真实装配（数据/工具/LLM）

默认优先尝试真实装配（``cbr.service.build_service``）；任一模块未就绪时自动回退到
本文件内置的 stub 数据/工具/agent，保证“三模式 + R0-R5 + 冲突协调 + 核验 + trace”
全链路可演示、可离线复现。

产物：

- ``artifacts/traces/<run_id>.jsonl``：审计 trace（可被 UI/API 读回）；
- ``artifacts/traces/<run_id>.decision.json``：DecisionCard 快照；
- ``artifacts/demo/<as_of>_summary.json``：三模式演示汇总。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..config import ROOT, AppSettings, load_scenarios, load_settings
from ..schemas import (
    AgentContext,
    AgentOutput,
    Claim,
    ClaimType,
    DecisionCard,
    Evidence,
    EvidenceKind,
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
from .orchestrator import build_orchestrator

ROLES = (Role.REGULATOR, Role.INVESTOR, Role.FINANCING)
DISPLAY = {Role.REGULATOR: "监管主体", Role.INVESTOR: "投资主体", Role.FINANCING: "融资主体"}


# --------------------------------------------------------------------------- #
# Stub 组件（离线演示用）
# --------------------------------------------------------------------------- #
class StubProvider:
    def __init__(self, as_of: date, *, level: RiskLevel = RiskLevel.HIGH) -> None:
        self.as_of = as_of
        self.level = level

    def risk_signal(self, as_of: date) -> RiskSignal:
        return RiskSignal(
            as_of=as_of,
            model_version="demo-fusion-v1",
            horizons={5: 0.32, 10: 0.46, 20: 0.58},
            percentile=0.91,
            level=self.level,
            drivers=[RiskDriver(factor="northbound_outflow_z", contribution=0.31)],
            modality_contrib={"numeric": 0.72, "text": 0.28},
        )

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        return MarketSnapshot(as_of=as_of, series={"cn_equity": 1.02, "usdcny": 7.15})

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict[str, Any]]:
        history = []
        for index in range(min(lookback, 120)):
            day = as_of - timedelta(days=index)
            history.append({"date": day.isoformat(), "value": 1.0 + 0.1 * math.sin(index / 9.0)})
        return list(reversed(history))

    def label(self, as_of: date, horizon: int) -> int | None:
        return None

    def data_cards(self) -> list:
        return []


class StubTool:
    def __init__(self, name: str, value: float, *, unit: str, payload: dict[str, Any] | None = None) -> None:
        self.name = name
        self.version = "demo-1.0.0"
        self.description = f"demo {name}"
        self.unit = unit
        self.value = value
        self.payload = payload or {}

    def run(self, as_of: date, **kwargs: Any) -> ToolResult:
        evidence = Evidence(
            evidence_id=f"ev_demo_{self.name}_{as_of.isoformat()}",
            kind=EvidenceKind.TOOL,
            as_of=as_of,
            title=f"{self.name} 计算结果",
            summary=f"{self.name}={self.value}",
            payload={"value": self.value, **self.payload},
            value=self.value,
            unit=self.unit,
            tool=ToolRef(name=self.name, version=self.version, inputs_hash=f"demo_{self.name}", elapsed_ms=2),
            produced_by="demo-tools",
        )
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=as_of,
            ok=True,
            data={"value": self.value, **self.payload},
            unit=self.unit,
            evidence=evidence,
            elapsed_ms=2,
        )


class StubRegistry:
    def __init__(self) -> None:
        self._tools = {
            "capital_flow": StubTool("capital_flow", 1.42, unit="z", payload={"direction": "up"}),
            "risk_measure": StubTool("risk_measure", 0.08, unit="ratio"),
            "funding_cost": StubTool("funding_cost", 0.85, unit="pct"),
            "systemic_risk": StubTool("systemic_risk", 0.41, unit="prob", payload={"direction": "up"}),
            "forecast": StubTool("forecast", 0.58, unit="prob"),
            "scenario": StubTool("scenario", -0.12, unit="ratio"),
            "knowledge_search": StubTool("knowledge_search", 1.0, unit="count"),
        }

    def get(self, name: str) -> StubTool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def allow(self, role: Any, tool_name: str) -> bool:
        return tool_name in self._tools


def _demo_evidence(
    role: str, subject: str, value: float, *, as_of: date, unit: str | None = None
) -> Evidence:
    return Evidence(
        evidence_id=f"ev_demo_{role}_{subject}",
        kind=EvidenceKind.TOOL,
        as_of=as_of,
        title=f"{subject}（{role} 工具证据）",
        summary=f"{subject}={value}",
        payload={"value": value, "subject": subject},
        value=value,
        unit=unit,
        tool=ToolRef(name="demo_tool", version="demo-1.0.0", inputs_hash=f"{role}_{subject}", elapsed_ms=1),
        produced_by=role,
    )


def _claim(role: str, subject: str, value: float, evidence_id: str, *, claim_type: ClaimType = ClaimType.NUMERIC,
           unit: str | None = "z", direction: str | None = None) -> Claim:
    if claim_type == ClaimType.NUMERIC:
        text = f"{subject}={value}"
    else:
        text = f"{subject} 方向 {direction}"
    return Claim(
        claim_id=f"{role}-{subject}-{direction or 'num'}",
        role=role,
        claim_type=claim_type,
        subject=subject,
        text=text,
        value=value,
        unit=unit,
        direction=direction,  # type: ignore[arg-type]
        evidence_ids=[evidence_id],
        confidence=0.85,
    )


class DemoRoleAgent:
    def __init__(self, role: Role, claims: list[Claim], evidence: list[Evidence], risk_level: RiskLevel) -> None:
        self.role = role
        self.claims = claims
        self.evidence = evidence
        self.risk_level = risk_level

    def analyze(self, context: AgentContext) -> AgentOutput:
        card = RiskCard(
            role=self.role,
            as_of=context.as_of,
            risk_level=self.risk_level,
            headline=f"{DISPLAY[self.role]}：风险等级 {self.risk_level.value}",
            base_signal_ref=context.signal.evidence_id,
            claims=list(self.claims),
            recommendation={
                Role.REGULATOR: "维持跨境资金与外溢监测频率，必要时启动跨部门会商。",
                Role.INVESTOR: "防御性调整风险预算，评估尾部对冲成本。",
                Role.FINANCING: "提前锁定融资成本并保留现金流缓冲。",
            }[self.role],
            limitations=["demo stub 数据（合成）"],
            evidence_ids=sorted({claim.evidence_ids[0] for claim in self.claims}),
            tool_calls=2,
            tokens=320,
            latency_ms=4,
        )
        return AgentOutput(
            role=self.role,
            card=card,
            evidence=list(self.evidence),
            tool_calls=2,
            tokens=320,
            latency_ms=4,
            trace=[],
        )


class DemoSingleAgent:
    def __init__(self, agents: dict[Role, DemoRoleAgent]) -> None:
        self.agents = agents

    def analyze(self, context: AgentContext):
        cards = {role.value: agent.analyze(context) for role, agent in self.agents.items()}
        return SimpleNamespace(
            cards=cards,
            tool_calls=sum(output.tool_calls for output in cards.values()),
            tokens=sum(output.tokens for output in cards.values()),
            latency_ms=12,
            trace=[],
        )


def _demo_agents(as_of: date) -> dict[Role, DemoRoleAgent]:
    # 事实冲突：同一 subject 两个主体数值不同
    regulator_flow = _demo_evidence("regulator", "northbound_outflow_z", 1.42, as_of=as_of, unit="z")
    investor_flow = _demo_evidence("investor", "northbound_outflow_z", 1.95, as_of=as_of, unit="z")
    # 方向冲突：同一 subject 方向相反（工具重算 payload.direction=up）
    trend_ev = _demo_evidence("regulator", "stress_trend", 0.41, as_of=as_of, unit="prob")
    # 偏好差异：证据一致、方向不同（up vs flat）
    prob_ev = _demo_evidence("regulator", "stress_prob_h20", 0.58, as_of=as_of, unit="prob")
    financing_spread = _demo_evidence("financing", "credit_spread", 0.85, as_of=as_of, unit="pct")
    return {
        Role.REGULATOR: DemoRoleAgent(
            Role.REGULATOR,
            [
                _claim("regulator", "northbound_outflow_z", 1.42, regulator_flow.evidence_id),
                _claim(
                    "regulator",
                    "stress_trend",
                    0.41,
                    trend_ev.evidence_id,
                    claim_type=ClaimType.DIRECTIONAL,
                    unit="prob",
                    direction="up",
                ),
                _claim(
                    "regulator",
                    "stress_prob_h20",
                    0.58,
                    prob_ev.evidence_id,
                    claim_type=ClaimType.DIRECTIONAL,
                    unit="prob",
                    direction="up",
                ),
            ],
            [regulator_flow, trend_ev, prob_ev],
            RiskLevel.HIGH,
        ),
        Role.INVESTOR: DemoRoleAgent(
            Role.INVESTOR,
            [
                _claim("investor", "northbound_outflow_z", 1.95, investor_flow.evidence_id),
                _claim(
                    "investor",
                    "stress_prob_h20",
                    0.58,
                    prob_ev.evidence_id,
                    claim_type=ClaimType.DIRECTIONAL,
                    unit="prob",
                    direction="flat",
                ),
            ],
            [investor_flow],
            RiskLevel.HIGH,
        ),
        Role.FINANCING: DemoRoleAgent(
            Role.FINANCING,
            [
                _claim("financing", "credit_spread", 0.85, financing_spread.evidence_id, unit="pct"),
                _claim(
                    "financing",
                    "stress_trend",
                    0.41,
                    trend_ev.evidence_id,
                    claim_type=ClaimType.DIRECTIONAL,
                    unit="prob",
                    direction="down",
                ),
            ],
            [financing_spread],
            RiskLevel.MEDIUM,
        ),
    }


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #
def _default_as_of() -> date:
    try:
        scenarios = load_scenarios()
        if scenarios:
            return max(scenarios, key=lambda scenario: scenario.as_of).as_of
    except Exception:  # pragma: no cover
        pass
    return date(2024, 8, 5)


def _scenario_id(as_of: date) -> str | None:
    try:
        for scenario in load_scenarios():
            if scenario.as_of == as_of:
                return scenario.scenario_id
    except Exception:  # pragma: no cover
        pass
    return None


def _try_real_orchestrator(settings: AppSettings) -> tuple[Any, str]:
    try:
        from ..service import build_service

        service = build_service(settings)
        return service.orchestrator, "real"
    except Exception as exc:  # noqa: BLE001 - 演示降级
        print(f"[demo] 真实装配不可用，回退 mock stub：{type(exc).__name__}: {exc}")
        return None, "stub"


def _build_stub_orchestrator(settings: AppSettings, as_of: date, trace_dir: str | None):
    agents = _demo_agents(as_of)
    return build_orchestrator(
        settings,
        StubProvider(as_of),
        StubRegistry(),
        None,
        None,
        agents=agents,
        single_agent=DemoSingleAgent(agents),
        trace_dir=trace_dir,
    )


def run_demo(
    as_of: date | None = None,
    *,
    use_real: bool = False,
    trace_dir: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or _default_as_of()
    settings = load_settings()
    if trace_dir:
        settings.orchestration.trace_dir = trace_dir
    scenario = _scenario_id(as_of)
    orchestrator, backend = (None, "stub")
    if use_real:
        orchestrator, backend = _try_real_orchestrator(settings)
    if orchestrator is None:
        backend = "stub"
        orchestrator = _build_stub_orchestrator(settings, as_of, trace_dir)

    results: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "scenario": scenario,
        "backend": backend,
        "modes": {},
    }
    for mode in ("single", "independent", "collaborative"):
        decision: DecisionCard = orchestrator.run(as_of, mode=mode, scenario=scenario)
        trace_path = decision.trace_ref or ""
        decision_path = ""
        if trace_path:
            candidate = Path(trace_path)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            decision_path = str(candidate.with_suffix(".decision.json"))
        results["modes"][mode] = {
            "run_id": decision.run_id,
            "trace_ref": trace_path,
            "decision_path": decision_path,
            "cards": {role: card.risk_level.value for role, card in decision.cards.items()},
            "conflicts": [
                {
                    "conflict_id": conflict.conflict_id,
                    "type": conflict.type.value,
                    "subject": conflict.subject,
                    "resolved": conflict.resolved,
                    "resolved_by": conflict.resolved_by,
                }
                for conflict in decision.conflicts
            ],
            "verification": decision.verification.model_dump(mode="json"),
            "coordination": decision.coordination.model_dump(mode="json"),
        }

    summary_path = ROOT / "artifacts" / "demo" / f"{as_of.isoformat()}_{backend}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    results["summary_path"] = str(summary_path)

    print(f"as_of={as_of.isoformat()} scenario={scenario} backend={backend}")
    for mode, payload in results["modes"].items():
        coordination = payload["coordination"]
        verification = payload["verification"]
        print(
            f"[{mode:13s}] run_id={payload['run_id']}\n"
            f"  trace     : {payload['trace_ref']}\n"
            f"  decision  : {payload['decision_path']}\n"
            f"  cards     : {payload['cards']}\n"
            f"  conflicts : {[(c['type'], c['resolved']) for c in payload['conflicts']]}\n"
            f"  verif     : numeric_error_rate={verification['numeric_error_rate']:.2%}, "
            f"evidence_accuracy={verification['evidence_accuracy']:.2%}, "
            f"leakage={verification['leakage_events']}, permission={verification['permission_violations']}, "
            f"schema={verification['schema_errors']}, passed={verification['passed']}\n"
            f"  cost      : tool_calls={coordination['tool_calls']}, tokens={coordination['tokens']}, "
            f"latency={coordination['latency_ms']}ms, cost_usd={coordination['cost_usd']:.6f}"
        )
    print(f"summary   : {summary_path}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 协同编排 mock 三模式演示")
    parser.add_argument("--as-of", dest="as_of", default=None, help="决策日 YYYY-MM-DD（默认最新情景）")
    parser.add_argument("--real", action="store_true", help="尝试真实装配（数据/工具/LLM 全模块）")
    parser.add_argument("--trace-dir", dest="trace_dir", default=None, help="trace 输出目录")
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else _default_as_of()
    run_demo(as_of, use_real=args.real, trace_dir=args.trace_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
