"""L5 协同编排层：三模式统一代码路径 + R0-R5 协同流程 + 审计 trace（架构 3.5）。

对外契约::

    from cbr.orchestration import build_orchestrator
    orchestrator = build_orchestrator(settings, provider, registry, kb, llm)
    decision = orchestrator.run(as_of=date(2024, 8, 5), mode="collaborative")
    response = orchestrator.chat(ChatRequest(message="当前跨境风险如何？"))

三模式（同一代码路径，仅配置开关不同）：

====================  ==========  ==============  ==========  ==============
模式                   参与者      证据共享        交叉验证    分歧协调/黑板
====================  ==========  ==============  ==========  ==============
single                1 个通用     否              否          否
                      agent 依次
                      完成三主体
independent           3 个独立     否              否          否
                      RoleAgent
collaborative         3 个独立     是（去重）      是（工具重算） 是（R3/R4/HITL）
                      RoleAgent
====================  ==========  ==============  ==========  ==============

资源预算：每次 AgentContext 的 ``budget.max_tool_calls/max_tokens`` 在三种模式下
完全一致（每角色上限）；一次 run 的工具总预算 = ``角色数 × 每角色上限``，协同模式
的交叉验证/权威重算调用从执行者在角色预算中扣减，因此三种模式可比。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ..config import (
    AppSettings,
    OrchestrationSettings,
    load_role_specs,
    load_scenarios,
)
from ..schemas import (
    AgentContext,
    AgentOutput,
    ChatRequest,
    ChatResponse,
    Claim,
    ClaimStatus,
    ClaimType,
    Conflict,
    CoordinationStats,
    DecisionCard,
    Evidence,
    EvidenceKind,
    ExperimentMode,
    MarketSnapshot,
    RiskCard,
    RiskLevel,
    RiskSignal,
    Role,
    RoleSpec,
    SourceRef,
    TraceEvent,
)
from ..verification.numeric import closest_number, flatten_numbers, numbers_match
from ..verification.trace import TraceWriter, hash_obj, make_run_id, read_trace, resolve_trace_path
from ..verification.verifier import verify
from .blackboard import EvidenceBlackboard, detect_conflicts
from .conflict import ConflictArbitrator, tool_for_subject
from .hitl import HITLItem, HITLQueue

#: 三角色顺序固定（与 configs/roles.yaml / 论文 4.3 一致）
DEFAULT_ROLES: tuple[Role, ...] = (Role.REGULATOR, Role.INVESTOR, Role.FINANCING)


# --------------------------------------------------------------------------- #
# 协议 / 模式开关
# --------------------------------------------------------------------------- #
@runtime_checkable
class RoleAgentLike(Protocol):
    """编排层对 RoleAgent 的最小鸭子类型要求。"""

    def analyze(self, context: AgentContext) -> AgentOutput: ...


@dataclass(frozen=True)
class ModeFlags:
    """实验模式开关：三模式共用同一管线，仅这些开关不同。"""

    mode: ExperimentMode
    use_single_agent: bool
    share_evidence: bool
    cross_validate: bool
    coordinate: bool


MODE_FLAGS: dict[ExperimentMode, ModeFlags] = {
    ExperimentMode.SINGLE: ModeFlags(
        mode=ExperimentMode.SINGLE,
        use_single_agent=True,
        share_evidence=False,
        cross_validate=False,
        coordinate=False,
    ),
    ExperimentMode.INDEPENDENT: ModeFlags(
        mode=ExperimentMode.INDEPENDENT,
        use_single_agent=False,
        share_evidence=False,
        cross_validate=False,
        coordinate=False,
    ),
    ExperimentMode.COLLABORATIVE: ModeFlags(
        mode=ExperimentMode.COLLABORATIVE,
        use_single_agent=False,
        share_evidence=True,
        cross_validate=True,
        coordinate=True,
    ),
}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _coerce_mode(mode: ExperimentMode | str) -> ExperimentMode:
    if isinstance(mode, ExperimentMode):
        return mode
    try:
        return ExperimentMode(str(mode).strip().lower())
    except ValueError as exc:
        options = ", ".join(item.value for item in ExperimentMode)
        raise ValueError(f"未知实验模式 {mode!r}；可选: {options}") from exc


def _coerce_as_of(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"无法解析 as_of={value!r}，应为 YYYY-MM-DD") from exc


def _as_role(value: Any) -> Role | None:
    if isinstance(value, Role):
        return value
    try:
        return Role(str(value).strip().lower())
    except (ValueError, TypeError):
        return None


def _role_value(value: Any) -> str:
    return value.value if isinstance(value, Role) else str(value)


def _level_value(level: Any) -> str:
    return level.value if isinstance(level, RiskLevel) else str(level)


def _resolve_orchestration_settings(settings: Any) -> OrchestrationSettings:
    if settings is None:
        return OrchestrationSettings()
    candidate = getattr(settings, "orchestration", None)
    if isinstance(candidate, OrchestrationSettings):
        return candidate
    if isinstance(settings, OrchestrationSettings):
        return settings
    if isinstance(settings, Mapping):
        return OrchestrationSettings(**settings)
    if candidate is not None:
        return OrchestrationSettings.model_validate(
            candidate.model_dump() if hasattr(candidate, "model_dump") else dict(candidate)
        )
    return OrchestrationSettings()


def _default_role_specs() -> dict[Role, RoleSpec]:
    """读取 configs/roles.yaml；不可用时回退到最小 RoleSpec。"""
    try:
        specs = load_role_specs()
        if specs:
            return specs
    except Exception:  # pragma: no cover - 配置缺失时保底
        pass
    fallback: dict[Role, RoleSpec] = {}
    for role in DEFAULT_ROLES:
        fallback[role] = RoleSpec(
            role=role,
            display_name={Role.REGULATOR: "监管主体智能体", Role.INVESTOR: "投资主体智能体", Role.FINANCING: "融资主体智能体"}[role],
            objective="跨境金融压力预警",
            thresholds={},
        )
    return fallback


def _await_sync(value: Any) -> Any:
    """兼容同步/异步智能体实现。"""
    if not inspect.isawaitable(value):
        return value
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():  # pragma: no cover - 事件循环内不可同步等待
        raise RuntimeError("智能体返回 awaitable，但当前已存在运行中的事件循环")
    return asyncio.run(value)


# --------------------------------------------------------------------------- #
# Agent 工厂懒加载（依赖 task-3 agent-core，不硬编码其内部实现）
# --------------------------------------------------------------------------- #
def _load_agents_module() -> Any:
    try:
        from .. import agents as agents_module  # type: ignore
    except Exception as exc:  # pragma: no cover - 未就绪时给明确提示
        raise RuntimeError(
            "cbr.agents 尚未就绪（由 agent-core / task-3 提供）。"
            "可通过 build_orchestrator(..., agents=..., single_agent=...) 注入测试用 Agent。"
        ) from exc
    return agents_module


def _call_with_signature(func: Callable[..., Any], values: Mapping[str, Any]) -> Any:
    """按参数名绑定调用，兼容位置参数约定。"""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover
        return func(**{key: value for key, value in values.items() if key != "role_specs"})
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in values:
            kwargs[name] = values[name]
        elif parameter.default is inspect.Parameter.empty:
            raise TypeError(f"无法为 {func!r} 的参数 {name!r} 绑定值")
    return func(**kwargs)


def _call_first(func: Callable[..., Any], attempts: Sequence[tuple[Any, ...]]) -> Any:
    last_error: Exception | None = None
    for args in attempts:
        try:
            return func(*args)
        except TypeError as exc:  # 参数顺序/个数不匹配 → 试下一种约定
            last_error = exc
    if last_error is not None:
        raise last_error
    raise TypeError("没有可用的调用方式")


def build_role_agent_from_module(
    module: Any,
    role_spec: RoleSpec,
    registry: Any,
    provider: Any,
    kb: Any,
    llm: Any,
    settings: Any,
) -> Any:
    """构建单个角色智能体（优先模块工厂，其次 RoleAgent 类）。"""
    values = {
        "role_spec": role_spec,
        "registry": registry,
        "provider": provider,
        "kb": kb,
        "llm": llm,
        "settings": settings,
    }
    for attribute in ("build_role_agent", "RoleAgent"):
        builder = getattr(module, attribute, None)
        if builder is None:
            continue
        try:
            return _call_with_signature(builder, values)
        except TypeError:
            return _call_first(
                builder,
                (
                    (role_spec, registry, provider, kb, llm, settings),
                    (role_spec, provider, registry, kb, llm, settings),
                ),
            )
    raise RuntimeError("cbr.agents 既没有 build_role_agent，也没有 RoleAgent 类")


def build_role_agents_from_module(
    module: Any,
    registry: Any,
    provider: Any,
    kb: Any,
    llm: Any,
    settings: Any,
    role_specs: Mapping[Role, RoleSpec],
) -> dict[Role, Any]:
    builder = getattr(module, "build_role_agents", None)
    if callable(builder):
        values = {
            "registry": registry,
            "provider": provider,
            "kb": kb,
            "llm": llm,
            "settings": settings,
            "role_specs": dict(role_specs),
        }
        try:
            result = _call_with_signature(builder, values)
        except TypeError:
            result = _call_first(
                builder,
                (
                    (registry, provider, kb, llm, settings),
                    (provider, registry, kb, llm, settings),
                ),
            )
        if isinstance(result, Mapping):
            normalized: dict[Role, Any] = {}
            for key, agent in result.items():
                role = _as_role(key)
                if role is not None and agent is not None:
                    normalized[role] = agent
            return normalized
    return {
        role: build_role_agent_from_module(module, spec, registry, provider, kb, llm, settings)
        for role, spec in role_specs.items()
        if role in DEFAULT_ROLES
    }


def build_single_agent_from_module(
    module: Any,
    registry: Any,
    provider: Any,
    kb: Any,
    llm: Any,
    settings: Any,
    role_specs: Mapping[Role, RoleSpec],
) -> Any:
    values = {
        "registry": registry,
        "provider": provider,
        "kb": kb,
        "llm": llm,
        "settings": settings,
        "role_specs": dict(role_specs),
    }
    for attribute in ("build_single_agent", "SingleAgent"):
        builder = getattr(module, attribute, None)
        if builder is None:
            continue
        try:
            return _call_with_signature(builder, values)
        except TypeError:
            return _call_first(
                builder,
                (
                    (registry, provider, kb, llm, settings),
                    (provider, registry, kb, llm, settings),
                ),
            )
    raise RuntimeError("cbr.agents 既没有 build_single_agent，也没有 SingleAgent 类")


# --------------------------------------------------------------------------- #
# 编排器
# --------------------------------------------------------------------------- #
class OrchestratorImpl:
    """协同编排器实现（三模式统一管线）。"""

    def __init__(
        self,
        settings: Any,
        provider: Any,
        registry: Any,
        kb: Any = None,
        llm: Any = None,
        *,
        role_specs: Mapping[Any, RoleSpec] | None = None,
        agents: Mapping[Any, Any] | None = None,
        single_agent: Any = None,
        trace_dir: str | None = None,
        clock: Callable[[], datetime] | None = None,
        hitl: HITLQueue | None = None,
    ) -> None:
        self.settings = settings if settings is not None else AppSettings()
        self.provider = provider
        self.registry = registry
        self.kb = kb
        self.llm = llm
        self.orchestration = _resolve_orchestration_settings(settings)
        self.role_specs: dict[Role, RoleSpec] = {
            _as_role(key): spec
            for key, spec in (role_specs or _default_role_specs()).items()
            if _as_role(key) is not None
        }
        for role in DEFAULT_ROLES:  # 兜底，保证三主体齐全
            self.role_specs.setdefault(role, _default_role_specs().get(role) or RoleSpec(role=role, display_name=role.value, objective=""))
        self.roles: list[Role] = list(DEFAULT_ROLES)
        self._agents: dict[Role, Any] = {}
        for key, agent in (agents or {}).items():
            role = _as_role(key)
            if role is not None and agent is not None:
                self._agents[role] = agent
        self._single_agent = single_agent
        self._agents_built = all(role in self._agents for role in self.roles)
        self._agent_build_errors: dict[Role, Exception] = {}
        self._single_agent_error: Exception | None = None
        self._trace_dir = trace_dir or getattr(self.orchestration, "trace_dir", "artifacts/traces")
        self._clock = clock
        self._last_index: dict[str, Evidence] = {}
        self._last_board: EvidenceBlackboard = EvidenceBlackboard(
            self.abs_tol, self.rel_tol, self.role_specs
        )
        self.hitl = hitl or HITLQueue(
            enabled=bool(getattr(self.orchestration, "human_in_the_loop", True)),
            trace_factory=self._trace_writer_for_run,
            clock=clock,
        )

    # ------------------------------------------------------------------ #
    # 配置 / 预算
    # ------------------------------------------------------------------ #
    @property
    def abs_tol(self) -> float:
        return float(getattr(self.orchestration, "numeric_tolerance_abs", 1e-6))

    @property
    def rel_tol(self) -> float:
        return float(getattr(self.orchestration, "numeric_tolerance_rel", 1e-3))

    @property
    def per_agent_tool_calls(self) -> int:
        return max(int(getattr(self.orchestration, "max_tool_calls_per_agent", 6)), 0)

    @property
    def per_agent_tokens(self) -> int:
        return max(int(getattr(self.orchestration, "max_tokens_per_agent", 4000)), 0)

    @property
    def coordination_weight_mu(self) -> float:
        """J = L + μ·C 中的协同成本权重 μ。"""
        return float(getattr(self.orchestration, "coordination_weight_mu", 0.1))

    def _estimate_cost(self, coordination: CoordinationStats) -> float:
        """按配置把协同开销折算为统一成本单位 C（tool_calls / tokens / latency）。"""
        cost = (
            coordination.tool_calls * float(getattr(self.orchestration, "cost_per_tool_call", 0.0))
            + (coordination.tokens / 1000.0)
            * float(getattr(self.orchestration, "cost_per_1k_tokens", 0.0))
            + coordination.latency_ms * float(getattr(self.orchestration, "cost_per_latency_ms", 0.0))
        )
        return round(cost, 8)

    @property
    def display_names(self) -> dict[str, str]:
        return {
            role.value: (spec.display_name or role.value)
            for role, spec in self.role_specs.items()
        }

    def budget_plan(self, mode: ExperimentMode | str = ExperimentMode.COLLABORATIVE) -> dict[str, int]:
        """一次 run 的总预算（三种模式一致，保证 P3 可比）。"""
        actors = len(self.roles)
        return {
            "max_tool_calls": self.per_agent_tool_calls * actors,
            "max_tokens": self.per_agent_tokens * actors,
            "per_agent_tool_calls": self.per_agent_tool_calls,
            "per_agent_tokens": self.per_agent_tokens,
        }

    def _context_budget(self, run_id: str, mode: ExperimentMode, role: Role | None, step: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "step": step,
            "max_tool_calls": self.per_agent_tool_calls,
            "max_tokens": self.per_agent_tokens,
            "max_rounds": max(int(getattr(self.orchestration, "rounds", 1)), 1),
            "mode": mode.value,
            "role": role.value if role is not None else "single",
        }

    def _check_mode_enabled(self, mode: ExperimentMode) -> None:
        enabled = [str(item) for item in getattr(self.orchestration, "modes", [])]
        if enabled and mode.value not in enabled:
            raise ValueError(f"实验模式 {mode.value} 未启用；orchestration.modes={enabled}")

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #
    def run(
        self,
        as_of: date | str,
        mode: ExperimentMode | str = ExperimentMode.COLLABORATIVE,
        scenario: str | None = None,
    ) -> DecisionCard:
        """执行一次预警决策（三模式同一代码路径）。"""
        started = time.perf_counter()
        as_of_date = _coerce_as_of(as_of)
        mode_enum = _coerce_mode(mode)
        self._check_mode_enabled(mode_enum)
        flags = MODE_FLAGS[mode_enum]
        run_id = make_run_id(mode_enum.value, as_of_date)
        trace = TraceWriter(run_id, self._trace_dir, clock=self._clock)
        trace.emit(
            step="R0",
            action="run_start",
            detail={
                "run_id": run_id,
                "mode": mode_enum.value,
                "scenario": scenario,
                "as_of": as_of_date.isoformat(),
                "roles": [role.value for role in self.roles],
                "budget": self.budget_plan(mode_enum),
                "tolerances": {"abs": self.abs_tol, "rel": self.rel_tol},
            },
        )

        board = EvidenceBlackboard(self.abs_tol, self.rel_tol, self.role_specs)
        signal = self._load_signal(as_of_date, trace)
        snapshot = self._load_snapshot(as_of_date, trace)
        signal_evidence = self._signal_evidence(signal, as_of_date)
        board.add(signal_evidence, role=Role.COORDINATOR, count_shared=flags.share_evidence)

        coordination = CoordinationStats()
        remaining = self._new_budget_table(flags)
        degraded_roles: list[str] = []
        budget_truncated = [False]

        # ---- R0 独立分析 -------------------------------------------------
        outputs, raw_usage = self._round0(
            as_of_date, mode_enum, flags, signal, snapshot, trace, run_id, remaining, degraded_roles
        )
        self._account_usage(outputs, raw_usage, flags, remaining, coordination, trace, budget_truncated)

        # ---- R1 证据共享（黑板去重） -------------------------------------
        self._round1(outputs, board, trace, flags)
        coordination.evidence_shared = board.evidence_shared
        coordination.duplicate_evidence = board.duplicate_evidence

        # ---- R2 交叉验证（工具重算关键数值主张） -------------------------
        if flags.cross_validate:
            self._round2(as_of_date, outputs, board, trace, run_id, flags, remaining, coordination)

        # ---- R3 分歧识别 + R4 协调仲裁 -----------------------------------
        conflicts: list[Conflict] = []
        if flags.coordinate:
            conflicts = self._round3_4(
                as_of_date, run_id, board, trace, flags, remaining, coordination, degraded_roles
            )

        # ---- R5 汇总决策卡 + 核验 + HITL ---------------------------------
        coordination.evidence_shared = board.evidence_shared
        coordination.duplicate_evidence = board.duplicate_evidence
        cards: dict[str, RiskCard] = {role.value: output.card for role, output in outputs.items()}
        coordination.latency_ms = int((time.perf_counter() - started) * 1000)
        decision = DecisionCard(
            run_id=run_id,
            as_of=as_of_date,
            scenario=scenario,
            mode=mode_enum,
            signal=signal,
            cards=cards,
            evidence=sorted(board.all(), key=lambda ev: ev.evidence_id),
            conflicts=conflicts,
            coordination=coordination,
            final_advice="",
            trace_ref=trace.trace_ref,
        )
        report = verify(decision, board.index(), self.settings, trace_events=trace.events)
        decision.verification = report

        self._queue_verification_hitl(decision, report, run_id)
        if budget_truncated[0]:
            self.hitl.enqueue(
                kind="budget_exceeded",
                summary="智能体用量超过单角色预算，统计按上限截断（不改变已产出卡片）",
                run_id=run_id,
                payload={"budget": self.budget_plan(mode_enum)},
            )
        self.hitl.auto_process(run_id=run_id)
        escalated_items = [item for item in self.hitl.for_run(run_id) if item.auto_policy == "escalate"]

        coordination.latency_ms = int((time.perf_counter() - started) * 1000)
        coordination.cost_usd = self._estimate_cost(coordination)
        decision.coordination = coordination
        decision.final_advice = self._compose_final_advice(
            decision, board, degraded_roles, escalated_items, flags
        )
        decision_path = self._write_decision_artifact(trace, decision)
        trace.emit(
            step="R5",
            action="finalize",
            detail={
                "decision_path": str(decision_path),
                "cards": {role: _level_value(card.risk_level) for role, card in cards.items()},
                "degraded_roles": degraded_roles,
                "conflicts_total": coordination.conflicts_total,
                "conflicts_resolved": coordination.conflicts_resolved,
                "conflicts_escalated": coordination.conflicts_escalated,
                "verification": {
                    "numeric_error_rate": report.numeric_error_rate,
                    "evidence_accuracy": report.evidence_accuracy,
                    "unsupported_claims": report.unsupported_claims,
                    "leakage_events": report.leakage_events,
                    "permission_violations": report.permission_violations,
                    "schema_errors": report.schema_errors,
                    "passed": report.passed,
                },
                "escalated_items": [item.item_id for item in escalated_items],
                "tool_calls": coordination.tool_calls,
                "tokens": coordination.tokens,
                "latency_ms": coordination.latency_ms,
                "cost_usd": coordination.cost_usd,
                "coordination_weight_mu": self.coordination_weight_mu,
            },
        )

        self._last_board = board
        self._last_index = board.index()
        return decision

    def run_all_modes(
        self, as_of: date | str, scenario: str | None = None
    ) -> dict[str, DecisionCard]:
        """对同一 as_of 依次跑三模式（演示 / P3 对照用）。"""
        result: dict[str, DecisionCard] = {}
        enabled = [str(item) for item in getattr(self.orchestration, "modes", [])] or [
            mode.value for mode in ExperimentMode
        ]
        for mode_name in enabled:
            result[mode_name] = self.run(as_of, mode=mode_name, scenario=scenario)
        return result

    def chat(self, request: ChatRequest) -> ChatResponse:
        mode = request.mode if request.mode in {"single", "independent", "collaborative"} else "collaborative"
        if request.as_of is not None:
            as_of = _coerce_as_of(request.as_of)
            scenario = self._scenario_for(as_of)
        else:
            scenario_obj = self._latest_scenario()
            as_of = scenario_obj.as_of if scenario_obj is not None else date.today()
            scenario = scenario_obj.scenario_id if scenario_obj is not None else None
        decision = self.run(as_of, mode=mode, scenario=scenario)
        return ChatResponse(
            reply=self._compose_chat_reply(request.message, decision),
            as_of=as_of,
            decision=decision,
            citations=self._collect_citations(),
            trace_id=decision.run_id,
        )

    # ------------------------------------------------------------------ #
    # 只读接口（UI / API duck-typing）
    # ------------------------------------------------------------------ #
    @property
    def blackboard(self) -> EvidenceBlackboard:
        """最近一次 run 的证据黑板（UI/API 可经它查询证据；未运行时为空板）。"""
        return self._last_board

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        if not evidence_id:
            return None
        evidence = self._last_board.get(evidence_id)
        if evidence is not None:
            return evidence
        return self._last_index.get(evidence_id)

    def get_trace(self, run_id: str) -> list[TraceEvent]:
        """按 run_id 或 trace_ref 读回审计轨迹（jsonl）。"""
        if not run_id:
            return []
        candidate = resolve_trace_path(run_id)
        if candidate is None:
            from pathlib import Path

            candidate = Path(self._trace_dir)
            if not candidate.is_absolute():
                from ..config import ROOT

                candidate = ROOT / candidate
            candidate = candidate / f"{run_id}.jsonl"
        if candidate.is_file():
            return read_trace(candidate)
        return read_trace(run_id)

    def pending_hitl(self, run_id: str | None = None) -> list[HITLItem]:
        return self.hitl.needs_review(run_id=run_id)

    def record_hitl_decision(
        self,
        item_id: str,
        action: str,
        note: str = "",
        replacement: dict[str, Any] | None = None,
    ) -> HITLItem:
        """记录人工 approve/reject/override（追加到对应 run 的 trace）。"""
        if action == "approve":
            return self.hitl.approve(item_id, note=note)
        if action == "reject":
            return self.hitl.reject(item_id, note=note)
        if action == "override":
            return self.hitl.override(item_id, replacement or {}, note=note)
        raise ValueError(f"未知 HITL 动作 {action!r}；可选 approve/reject/override")

    # ------------------------------------------------------------------ #
    # Agent 懒加载 / 调用
    # ------------------------------------------------------------------ #
    def _trace_writer_for_run(self, run_id: str) -> TraceWriter:
        return TraceWriter(run_id, self._trace_dir, clock=self._clock)

    def _ensure_agents(self) -> None:
        if self._agents_built:
            return
        missing = [role for role in self.roles if role not in self._agents]
        if not missing:
            self._agents_built = True
            return
        try:
            module = _load_agents_module()
        except Exception as exc:
            for role in missing:
                self._agent_build_errors[role] = exc
            self._agents_built = True
            return
        builder = getattr(module, "build_role_agents", None)
        if callable(builder):
            try:
                built = build_role_agents_from_module(
                    module, self.registry, self.provider, self.kb, self.llm, self.settings, self.role_specs
                )
                for role, agent in built.items():
                    if role in missing and agent is not None:
                        self._agents[role] = agent
            except Exception:  # 批量构建失败 → 回退逐个构建
                pass
        for role in missing:
            if role in self._agents:
                continue
            try:
                self._agents[role] = build_role_agent_from_module(
                    module,
                    self.role_specs.get(role) or RoleSpec(role=role, display_name=role.value, objective=""),
                    self.registry,
                    self.provider,
                    self.kb,
                    self.llm,
                    self.settings,
                )
            except Exception as exc:
                self._agent_build_errors[role] = exc
        self._agents_built = True

    def _get_role_agent(self, role: Role) -> Any:
        if role in self._agents:
            return self._agents[role]
        self._ensure_agents()
        if role in self._agents:
            return self._agents[role]
        error = self._agent_build_errors.get(role)
        raise RuntimeError(f"角色智能体 {role.value} 不可用：{type(error).__name__}: {error}")

    def _get_single_agent(self) -> Any:
        if self._single_agent is not None:
            return self._single_agent
        if self._single_agent_error is not None:
            raise RuntimeError(f"单智能体模式不可用：{self._single_agent_error}")
        try:
            module = _load_agents_module()
            self._single_agent = build_single_agent_from_module(
                module, self.registry, self.provider, self.kb, self.llm, self.settings, self.role_specs
            )
        except Exception as exc:
            self._single_agent_error = exc
            raise RuntimeError(f"单智能体模式不可用：{type(exc).__name__}: {exc}") from exc
        return self._single_agent

    @staticmethod
    def _call_agent(agent: Any, context: AgentContext) -> Any:
        for attribute in ("analyze", "run", "analyze_role"):
            method = getattr(agent, attribute, None)
            if callable(method):
                return _await_sync(method(context))
        if callable(agent):
            return _await_sync(agent(context))
        raise TypeError(f"Agent 对象不支持 analyze(context) 调用：{type(agent)!r}")

    def _normalize_agent_output(
        self, result: Any, role: Role, context: AgentContext
    ) -> AgentOutput:
        if isinstance(result, AgentOutput):
            output = result
        elif isinstance(result, RiskCard):
            output = AgentOutput(role=role, card=result)
        elif isinstance(result, Mapping):
            output = (
                AgentOutput.model_validate(result)
                if "card" in result
                else AgentOutput(role=role, card=RiskCard.model_validate(result))
            )
        elif hasattr(result, "card"):
            card = result.card
            output = AgentOutput(
                role=getattr(result, "role", role) or role,
                card=card if isinstance(card, RiskCard) else RiskCard.model_validate(card),
                evidence=list(getattr(result, "evidence", []) or []),
                tool_calls=int(getattr(result, "tool_calls", 0) or 0),
                tokens=int(getattr(result, "tokens", 0) or 0),
                latency_ms=int(getattr(result, "latency_ms", 0) or 0),
                trace=list(getattr(result, "trace", []) or []),
            )
        else:
            raise TypeError(f"无法解析智能体输出类型：{type(result)!r}")

        card = output.card
        updates: dict[str, Any] = {}
        if card.role != role:
            updates["role"] = role
        if card.as_of != context.as_of:
            updates["as_of"] = context.as_of
        if card.round != context.round:
            updates["round"] = context.round
        if card.base_signal_ref is None and context.signal.evidence_id:
            updates["base_signal_ref"] = context.signal.evidence_id
        claim_evidence_ids = list(
            dict.fromkeys(
                [*card.evidence_ids, *(eid for claim in card.claims for eid in claim.evidence_ids)]
            )
        )
        if claim_evidence_ids != card.evidence_ids:
            updates["evidence_ids"] = claim_evidence_ids
        if updates:
            card = card.model_copy(update=updates)
        output = output.model_copy(
            update={
                "role": role,
                "card": card,
                "tool_calls": output.tool_calls or card.tool_calls,
                "tokens": output.tokens or card.tokens,
                "latency_ms": output.latency_ms or card.latency_ms,
            }
        )
        return output

    def _degraded_output(
        self, role: Role, as_of: date, signal: RiskSignal, error: Exception, round_index: int
    ) -> AgentOutput:
        display = self.display_names.get(role.value, role.value)
        level = signal.level if isinstance(signal.level, RiskLevel) else RiskLevel.MEDIUM
        degraded_level = RiskLevel.MEDIUM if level in (RiskLevel.LOW, RiskLevel.MEDIUM) else level
        card = RiskCard(
            role=role,
            as_of=as_of,
            risk_level=degraded_level,
            headline=f"{display}本轮分析失败，已降级为占位卡片",
            base_signal_ref=signal.evidence_id,
            key_metrics=[],
            claims=[],
            recommendation="该角色本轮分析异常，不输出未经核验的数值或建议；建议由其他角色结论覆盖并人工复核。",
            decision_loss={},
            limitations=[f"{type(error).__name__}: {error}"],
            evidence_ids=[signal.evidence_id] if signal.evidence_id else [],
            tool_calls=0,
            tokens=0,
            latency_ms=0,
            round=round_index,
        )
        return AgentOutput(role=role, card=card, evidence=[], tool_calls=0, tokens=0, latency_ms=0, trace=[])

    # ------------------------------------------------------------------ #
    # 预算 / 用量
    # ------------------------------------------------------------------ #
    def _new_budget_table(self, flags: ModeFlags) -> dict[str, dict[str, int]]:
        if flags.use_single_agent:
            total_tc = self.per_agent_tool_calls * len(self.roles)
            total_tokens = self.per_agent_tokens * len(self.roles)
            return {"single": {"tool_calls": total_tc, "tokens": total_tokens}}
        return {
            role.value: {"tool_calls": self.per_agent_tool_calls, "tokens": self.per_agent_tokens}
            for role in self.roles
        }

    def _record_agent_trace(self, trace: TraceWriter, run_id: str, role: Role, output: AgentOutput) -> None:
        for event in output.trace:
            if not isinstance(event, TraceEvent):
                continue
            updates: dict[str, Any] = {}
            if not event.run_id:
                updates["run_id"] = run_id
            if not event.step:
                updates["step"] = "R0"
            if event.role is None:
                updates["role"] = role.value
            trace.write(event.model_copy(update=updates) if updates else event)

    def _account_usage(
        self,
        outputs: Mapping[Role, AgentOutput],
        raw_usage: Mapping[str, int],
        flags: ModeFlags,
        remaining: dict[str, dict[str, int]],
        coordination: CoordinationStats,
        trace: TraceWriter,
        truncated_flag: list[bool],
    ) -> None:
        if flags.use_single_agent:
            budget = remaining.get("single", {"tool_calls": 0, "tokens": 0})
            raw_tc = max(int(raw_usage.get("tool_calls", 0) or 0), 0)
            raw_tokens = max(int(raw_usage.get("tokens", 0) or 0), 0)
            allowed_tc = min(raw_tc, budget.get("tool_calls", 0))
            allowed_tokens = min(raw_tokens, budget.get("tokens", 0))
            budget["tool_calls"] -= allowed_tc
            budget["tokens"] -= allowed_tokens
            coordination.tool_calls += allowed_tc
            coordination.tokens += allowed_tokens
            if allowed_tc < raw_tc or allowed_tokens < raw_tokens:
                truncated_flag[0] = True
                trace.emit(
                    step="R0",
                    action="budget_exceeded",
                    role="single",
                    detail={
                        "raw": {"tool_calls": raw_tc, "tokens": raw_tokens},
                        "allowed": {"tool_calls": allowed_tc, "tokens": allowed_tokens},
                    },
                )
            return
        for role, output in outputs.items():
            budget = remaining.setdefault(
                role.value, {"tool_calls": self.per_agent_tool_calls, "tokens": self.per_agent_tokens}
            )
            raw_tc = max(int(output.tool_calls or 0), 0)
            raw_tokens = max(int(output.tokens or 0), 0)
            allowed_tc = min(raw_tc, budget["tool_calls"])
            allowed_tokens = min(raw_tokens, budget["tokens"])
            budget["tool_calls"] -= allowed_tc
            budget["tokens"] -= allowed_tokens
            coordination.tool_calls += allowed_tc
            coordination.tokens += allowed_tokens
            if allowed_tc < raw_tc or allowed_tokens < raw_tokens:
                truncated_flag[0] = True
                trace.emit(
                    step="R0",
                    action="budget_exceeded",
                    role=role.value,
                    detail={
                        "raw": {"tool_calls": raw_tc, "tokens": raw_tokens},
                        "allowed": {"tool_calls": allowed_tc, "tokens": allowed_tokens},
                    },
                )

    def _registry_allows(self, role: Role, tool_name: str) -> bool:
        allow = getattr(self.registry, "allow", None)
        if not callable(allow):
            return True
        try:
            return bool(allow(role, tool_name))
        except Exception:  # pragma: no cover
            return False

    def _available_tool_names(self) -> list[str] | None:
        names = getattr(self.registry, "names", None)
        if callable(names):
            try:
                return list(names())
            except Exception:  # pragma: no cover
                return None
        return None

    # ------------------------------------------------------------------ #
    # R0 独立分析
    # ------------------------------------------------------------------ #
    def _round0(
        self,
        as_of: date,
        mode: ExperimentMode,
        flags: ModeFlags,
        signal: RiskSignal,
        snapshot: MarketSnapshot,
        trace: TraceWriter,
        run_id: str,
        remaining: dict[str, dict[str, int]],
        degraded_roles: list[str],
    ) -> tuple[dict[Role, AgentOutput], dict[str, int]]:
        if flags.use_single_agent:
            return self._round0_single(as_of, mode, signal, snapshot, trace, run_id, remaining, degraded_roles)
        outputs: dict[Role, AgentOutput] = {}
        for role in self.roles:
            outputs[role] = self._analyze_role(
                role, as_of, mode, signal, snapshot, trace, run_id, round_index=0, peer_evidence=[], degraded_roles=degraded_roles
            )
        usage = {
            "tool_calls": sum(int(output.tool_calls or 0) for output in outputs.values()),
            "tokens": sum(int(output.tokens or 0) for output in outputs.values()),
        }
        return outputs, usage

    def _analyze_role(
        self,
        role: Role,
        as_of: date,
        mode: ExperimentMode,
        signal: RiskSignal,
        snapshot: MarketSnapshot,
        trace: TraceWriter,
        run_id: str,
        *,
        round_index: int,
        peer_evidence: list[Evidence],
        degraded_roles: list[str],
    ) -> AgentOutput:
        context = AgentContext(
            as_of=as_of,
            mode=mode,
            signal=signal,
            snapshot=snapshot,
            round=round_index,
            peer_evidence=list(peer_evidence),
            budget=self._context_budget(run_id, mode, role, step=f"R0:{role.value}"),
            task=self._task_prompt(role, as_of, mode, round_index),
        )
        trace.emit(
            step="R0",
            action="analysis_start",
            role=role.value,
            detail={"round": round_index, "peer_evidence": len(peer_evidence), "budget": context.budget},
        )
        started = time.perf_counter()
        try:
            agent = self._get_role_agent(role)
            raw = self._call_agent(agent, context)
            output = self._normalize_agent_output(raw, role, context)
        except Exception as exc:  # 单角色失败降级，不拖垮整体
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            output = self._degraded_output(role, as_of, signal, exc, round_index)
            if role.value not in degraded_roles:
                degraded_roles.append(role.value)
            trace.emit(
                step="R0",
                action="agent_error",
                role=role.value,
                detail={"error": f"{type(exc).__name__}: {exc}", "degraded": True},
                latency_ms=elapsed_ms,
            )
            trace.emit(
                step="R0",
                action="analysis_done",
                role=role.value,
                detail={"degraded": True, "claims": 0, "tool_calls": 0, "tokens": 0},
                latency_ms=elapsed_ms,
            )
            return output
        elapsed_ms = output.latency_ms or int((time.perf_counter() - started) * 1000)
        if not output.latency_ms:
            output = output.model_copy(update={"latency_ms": elapsed_ms})
        self._record_agent_trace(trace, run_id, role, output)
        trace.emit(
            step="R0",
            action="analysis_done",
            role=role.value,
            detail={
                "degraded": False,
                "risk_level": _level_value(output.card.risk_level),
                "claims": len(output.card.claims),
                "tool_calls": int(output.tool_calls or 0),
                "tokens": int(output.tokens or 0),
                "evidence": len(output.evidence),
            },
            latency_ms=int(output.latency_ms or elapsed_ms),
            tokens=int(output.tokens or 0),
        )
        return output

    def _round0_single(
        self,
        as_of: date,
        mode: ExperimentMode,
        signal: RiskSignal,
        snapshot: MarketSnapshot,
        trace: TraceWriter,
        run_id: str,
        remaining: dict[str, dict[str, int]],
        degraded_roles: list[str],
    ) -> tuple[dict[Role, AgentOutput], dict[str, int]]:
        pool = remaining.setdefault(
            "single",
            {
                "tool_calls": self.per_agent_tool_calls * len(self.roles),
                "tokens": self.per_agent_tokens * len(self.roles),
            },
        )
        context = AgentContext(
            as_of=as_of,
            mode=mode,
            signal=signal,
            snapshot=snapshot,
            round=0,
            peer_evidence=[],
            budget={**self._context_budget(run_id, mode, None, step="R0:single"), **pool},
            task=self._single_task_prompt(as_of, mode),
        )
        trace.emit(
            step="R0",
            action="analysis_start",
            role="single",
            detail={"round": 0, "budget": {key: pool[key] for key in ("tool_calls", "tokens")}},
        )
        started = time.perf_counter()
        try:
            agent = self._get_single_agent()
            raw = self._call_agent(agent, context)
            outputs, usage, agent_trace = self._normalize_single_result(raw, context)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            degraded_roles.extend([role.value for role in self.roles if role.value not in degraded_roles])
            outputs = {
                role: self._degraded_output(role, as_of, signal, exc, 0) for role in self.roles
            }
            trace.emit(
                step="R0",
                action="agent_error",
                role="single",
                detail={"error": f"{type(exc).__name__}: {exc}", "degraded": True},
                latency_ms=elapsed_ms,
            )
            for role in self.roles:
                trace.emit(
                    step="R0",
                    action="analysis_done",
                    role=role.value,
                    detail={"degraded": True, "claims": 0, "tool_calls": 0, "tokens": 0},
                    latency_ms=0,
                )
            return outputs, {"tool_calls": 0, "tokens": 0}
        elapsed_ms = usage.get("latency_ms") or int((time.perf_counter() - started) * 1000)
        for event in agent_trace:
            if isinstance(event, TraceEvent):
                updates = {}
                if not event.run_id:
                    updates["run_id"] = run_id
                if not event.step:
                    updates["step"] = "R0"
                trace.write(event.model_copy(update=updates) if updates else event)
        for role, output in outputs.items():
            trace.emit(
                step="R0",
                action="analysis_done",
                role=role.value,
                detail={
                    "degraded": False,
                    "risk_level": _level_value(output.card.risk_level),
                    "claims": len(output.card.claims),
                    "tool_calls": int(output.tool_calls or 0),
                    "tokens": int(output.tokens or 0),
                    "evidence": len(output.evidence),
                    "actor": "single",
                },
                latency_ms=int(elapsed_ms if role is self.roles[0] else 0),
                tokens=int(output.tokens or 0),
            )
        return outputs, dict(usage)

    def _normalize_single_result(
        self, result: Any, context: AgentContext
    ) -> tuple[dict[Role, AgentOutput], dict[str, int], list[TraceEvent]]:
        cards_obj: Any = getattr(result, "cards", None)
        usage: dict[str, int] = {
            "tool_calls": int(getattr(result, "tool_calls", 0) or 0),
            "tokens": int(getattr(result, "tokens", 0) or 0),
            "latency_ms": int(getattr(result, "latency_ms", 0) or 0),
        }
        agent_trace = list(getattr(result, "trace", []) or [])
        if cards_obj is None and isinstance(result, Mapping):
            cards_obj = result.get("cards")
            usage = {
                "tool_calls": int(result.get("tool_calls", usage["tool_calls"]) or 0),
                "tokens": int(result.get("tokens", usage["tokens"]) or 0),
                "latency_ms": int(result.get("latency_ms", usage["latency_ms"]) or 0),
            }
            agent_trace = list(result.get("trace", agent_trace) or [])
        if cards_obj is None:
            raise TypeError("单智能体输出缺少 cards（应为 SingleAgentResult.cards 或 dict）")
        outputs: dict[Role, AgentOutput] = {}
        for key, value in dict(cards_obj).items():
            role = _as_role(key)
            if role is None:
                continue
            try:
                outputs[role] = self._normalize_agent_output(value, role, context)
            except Exception:  # 单个角色卡片解析失败 → 降级
                outputs[role] = self._degraded_output(
                    role, context.as_of, context.signal, ValueError(f"单智能体返回的 {key} 卡片无法解析"), context.round
                )
        for role in self.roles:
            if role not in outputs:
                outputs[role] = self._degraded_output(
                    role,
                    context.as_of,
                    context.signal,
                    ValueError("单智能体未返回该角色卡片"),
                    context.round,
                )
        # 单智能体总用量为空时，按各卡片用量求和
        if not usage["tool_calls"]:
            usage["tool_calls"] = sum(int(output.tool_calls or 0) for output in outputs.values())
        if not usage["tokens"]:
            usage["tokens"] = sum(int(output.tokens or 0) for output in outputs.values())
        return outputs, usage, agent_trace

    def _task_prompt(self, role: Role, as_of: date, mode: ExperimentMode, round_index: int) -> str:
        spec = self.role_specs.get(role)
        display = spec.display_name if spec else role.value
        objective = (spec.objective if spec else "") or ""
        return (
            f"以「{display}」身份完成 {as_of.isoformat()} 的跨境金融压力分析并输出结构化 RiskCard。"
            f"目标：{objective[:160]}。"
            "约束：数值主张必须绑定确定性工具证据且 value/unit 与工具输出逐字一致；"
            "文本主张必须绑定知识库 chunk 证据；禁止输出证据中不存在的数字。"
            f"实验模式={mode.value}，轮次={round_index}。"
        )

    def _single_task_prompt(self, as_of: date, mode: ExperimentMode) -> str:
        return (
            f"作为通用风险分析智能体，依次以监管/投资/融资三主体视角完成 {as_of.isoformat()} "
            "的跨境金融压力分析，输出三张差异化 RiskCard（同一共享风险信号，角色目标/阈值/建议不同）。"
            "约束：数值主张必须绑定确定性工具证据且逐字一致；文本主张必须绑定知识库证据。"
            f"实验模式={mode.value}（single）。"
        )

    # ------------------------------------------------------------------ #
    # R1 证据共享
    # ------------------------------------------------------------------ #
    def _round1(
        self,
        outputs: Mapping[Role, AgentOutput],
        board: EvidenceBlackboard,
        trace: TraceWriter,
        flags: ModeFlags,
    ) -> None:
        shared_before = board.evidence_shared
        duplicate_before = board.duplicate_evidence
        for role, output in outputs.items():
            for evidence in output.evidence:
                is_duplicate = board.contains_equivalent(evidence)
                evidence_id = board.add(evidence, role=role, count_shared=flags.share_evidence)
                if flags.share_evidence:
                    trace.emit(
                        step="R1",
                        action="evidence_dedup" if is_duplicate else "evidence_share",
                        role=role.value,
                        detail={
                            "evidence_id": evidence_id,
                            "source_id": evidence.evidence_id,
                            "kind": evidence.kind.value if hasattr(evidence.kind, "value") else str(evidence.kind),
                            "title": evidence.title[:80],
                            "value": evidence.value,
                            "tool": evidence.tool.name if evidence.tool else None,
                        },
                    )
            board.register_card(role, output.card)
        if flags.share_evidence:
            trace.emit(
                step="R1",
                action="evidence_share_summary",
                detail={
                    "evidence_total": len(board),
                    "new_shared": board.evidence_shared - shared_before,
                    "duplicates": board.duplicate_evidence - duplicate_before,
                    "claims": len(board.claims),
                },
            )

    # ------------------------------------------------------------------ #
    # R2 交叉验证
    # ------------------------------------------------------------------ #
    def _round2(
        self,
        as_of: date,
        outputs: Mapping[Role, AgentOutput],
        board: EvidenceBlackboard,
        trace: TraceWriter,
        run_id: str,
        flags: ModeFlags,
        remaining: dict[str, dict[str, int]],
        coordination: CoordinationStats,
    ) -> None:
        cards = {role: output.card for role, output in outputs.items()}
        plan = self._plan_cross_checks(cards)
        tool_calls = 0
        matched = 0
        mismatched = 0
        available = self._available_tool_names()
        for verifier_role, owner_role, claim in plan:
            budget = remaining.setdefault(
                verifier_role.value,
                {"tool_calls": self.per_agent_tool_calls, "tokens": self.per_agent_tokens},
            )
            if budget["tool_calls"] <= 0:
                trace.emit(
                    step="R2",
                    action="cross_check",
                    role=verifier_role.value,
                    detail={"claim_id": claim.claim_id, "skipped": True, "reason": "budget_exhausted"},
                )
                continue
            tool_name = tool_for_subject(claim.subject, available)
            if tool_name is None:
                trace.emit(
                    step="R2",
                    action="cross_check",
                    role=verifier_role.value,
                    detail={"claim_id": claim.claim_id, "skipped": True, "reason": "no_tool_mapping"},
                )
                continue
            if not self._registry_allows(verifier_role, tool_name):
                trace.emit(
                    step="R2",
                    action="cross_check",
                    role=verifier_role.value,
                    detail={
                        "claim_id": claim.claim_id,
                        "skipped": True,
                        "reason": "permission_matrix_denied",
                        "tool": tool_name,
                    },
                )
                continue
            started = time.perf_counter()
            try:
                result = self.registry.get(tool_name).run(as_of)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
            except Exception as exc:
                trace.emit(
                    step="R2",
                    action="cross_check",
                    role=verifier_role.value,
                    tool=tool_name,
                    detail={"claim_id": claim.claim_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"},
                )
                continue
            if getattr(result, "ok", False) is not True:
                trace.emit(
                    step="R2",
                    action="cross_check",
                    role=verifier_role.value,
                    tool=tool_name,
                    detail={"claim_id": claim.claim_id, "ok": False, "error": getattr(result, "error", None)},
                    latency_ms=elapsed_ms,
                )
                continue
            evidence = getattr(result, "evidence", None)
            if evidence is None:
                continue
            evidence_id = board.add(evidence, role=verifier_role, count_shared=flags.share_evidence)
            budget["tool_calls"] -= 1
            tool_calls += 1
            coordination.tool_calls += 1
            scalar = self._result_scalar(result, evidence, claim.value)
            is_match = scalar is not None and numbers_match(scalar, claim.value, self.abs_tol, self.rel_tol)
            if is_match:
                matched += 1
                claim.status = ClaimStatus.VERIFIED
            else:
                mismatched += 1
                claim.status = ClaimStatus.CONFLICTED
                synthetic = Claim(
                    claim_id=f"recheck_{claim.claim_id}",
                    role=verifier_role.value,
                    claim_type=ClaimType.NUMERIC,
                    subject=claim.subject,
                    text=f"交叉验证：工具 {tool_name} 对 {claim.subject} 的重算值为 {scalar}",
                    value=scalar,
                    unit=claim.unit or evidence.unit,
                    direction=claim.direction,
                    evidence_ids=[evidence_id],
                    confidence=1.0,
                    status=ClaimStatus.VERIFIED,
                )
                board.add_claims([synthetic])
            trace.emit(
                step="R2",
                action="cross_check",
                role=verifier_role.value,
                tool=tool_name,
                args_hash=hash_obj({"tool": tool_name, "as_of": as_of.isoformat(), "subject": claim.subject}),
                result_hash=hash_obj(evidence.model_dump(mode="json")),
                detail={
                    "owner_role": owner_role.value,
                    "claim_id": claim.claim_id,
                    "subject": claim.subject,
                    "claim_value": claim.value,
                    "tool_value": scalar,
                    "match": is_match,
                    "evidence_id": evidence_id,
                },
                latency_ms=elapsed_ms,
            )
        trace.emit(
            step="R2",
            action="cross_check_summary",
            detail={"checks_planned": len(plan), "tool_calls": tool_calls, "matched": matched, "mismatched": mismatched},
        )

    def _plan_cross_checks(self, cards: Mapping[Role, RiskCard]) -> list[tuple[Role, Role, Claim]]:
        plan: list[tuple[Role, Role, Claim]] = []
        count = len(self.roles)
        for index, owner in enumerate(self.roles):
            card = cards.get(owner)
            if card is None:
                continue
            numeric_claims = [
                claim
                for claim in card.claims
                if claim.claim_type == ClaimType.NUMERIC and claim.value is not None
            ]
            numeric_claims.sort(key=lambda claim: float(claim.confidence or 0.0), reverse=True)
            verifier = self.roles[(index + 1) % count]
            if verifier == owner:
                continue
            for claim in numeric_claims[:1]:  # 每人复核他人 1 条关键数值主张
                plan.append((verifier, owner, claim))
        return plan

    def _result_scalar(self, result: Any, evidence: Evidence, target: float | None) -> float | None:
        candidates: list[float] = []
        if evidence.value is not None:
            try:
                candidates.append(float(evidence.value))
            except (TypeError, ValueError):  # pragma: no cover
                pass
        data = getattr(result, "data", {}) or {}
        for key in ("value", "z", "prob", "metric", "estimate", "spillover"):
            candidate = data.get(key) if isinstance(data, Mapping) else None
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                if float(candidate) not in candidates:
                    candidates.append(float(candidate))
        for number in flatten_numbers(data):
            if number not in candidates:
                candidates.append(number)
        if evidence.payload:
            for number in flatten_numbers(evidence.payload):
                if number not in candidates:
                    candidates.append(number)
        if not candidates:
            return None
        if target is not None:
            return closest_number(float(target), candidates)
        return candidates[0]

    # ------------------------------------------------------------------ #
    # R3/R4 分歧识别与协调
    # ------------------------------------------------------------------ #
    def _round3_4(
        self,
        as_of: date,
        run_id: str,
        board: EvidenceBlackboard,
        trace: TraceWriter,
        flags: ModeFlags,
        remaining: dict[str, dict[str, int]],
        coordination: CoordinationStats,
        degraded_roles: list[str],
    ) -> list[Conflict]:
        all_claims = board.claims
        conflicts = detect_conflicts(
            all_claims,
            cards=board.cards,
            role_specs=self.role_specs,
            abs_tol=self.abs_tol,
            rel_tol=self.rel_tol,
        )
        coordination.conflicts_total = len(conflicts)
        trace.emit(
            step="R3",
            action="conflict_detection",
            detail={
                "total": len(conflicts),
                "claims_checked": len(all_claims),
                "conflicts": [
                    {
                        "conflict_id": conflict.conflict_id,
                        "subject": conflict.subject,
                        "type": conflict.type.value,
                        "severity": conflict.severity,
                        "roles": conflict.roles,
                    }
                    for conflict in conflicts
                ],
            },
        )
        if not conflicts:
            trace.emit(step="R4", action="conflict_resolution", detail={"total": 0, "note": "未发现跨角色分歧"})
            return conflicts

        arbitrator = ConflictArbitrator(
            board=board,
            as_of=as_of,
            run_id=run_id,
            registry=self.registry,
            hitl=self.hitl,
            trace=trace,
            role_specs=self.role_specs,
            display_names=self.display_names,
            abs_tol=self.abs_tol,
            rel_tol=self.rel_tol,
            budget=remaining,
        )
        max_rounds = max(1, int(getattr(self.orchestration, "rounds", 1)))
        attempts = 0
        for attempt in range(1, max_rounds + 1):
            pending = [conflict for conflict in conflicts if not conflict.resolved]
            if not pending:
                break
            attempts = attempt
            trace.emit(
                step="R4",
                action="coordination_round",
                detail={"round": attempt, "max_rounds": max_rounds, "pending": len(pending)},
            )
            outcome = arbitrator.resolve(
                conflicts,
                board.claim_index,
                board.cards,
                final_round=(attempt == max_rounds),
            )
            coordination.conflicts_resolved += outcome.resolved
            coordination.tool_calls += outcome.tool_calls
            if all(conflict.resolved for conflict in conflicts):
                break
        coordination.rounds = attempts if conflicts else 0
        coordination.conflicts_escalated = sum(1 for conflict in conflicts if not conflict.resolved)
        trace.emit(
            step="R4",
            action="conflict_resolution",
            detail={
                "total": len(conflicts),
                "resolved": coordination.conflicts_resolved,
                "escalated": coordination.conflicts_escalated,
                "rounds": coordination.rounds,
                "items": [
                    {
                        "conflict_id": conflict.conflict_id,
                        "subject": conflict.subject,
                        "type": conflict.type.value,
                        "resolved": conflict.resolved,
                        "resolved_by": conflict.resolved_by,
                        "resolution": conflict.resolution,
                    }
                    for conflict in conflicts
                ],
            },
        )
        return conflicts

    # ------------------------------------------------------------------ #
    # R5 汇总 / 核验 / HITL
    # ------------------------------------------------------------------ #
    def _queue_verification_hitl(
        self, decision: DecisionCard, report: Any, run_id: str
    ) -> None:
        critical_roles = [
            role for role, card in decision.cards.items() if _level_value(card.risk_level) == RiskLevel.CRITICAL.value
        ]
        if critical_roles or _level_value(decision.signal.level) == RiskLevel.CRITICAL.value:
            self.hitl.enqueue(
                kind="high_risk",
                summary=f"高风险/极高风险预警触发人工复核：roles={critical_roles or ['signal']}",
                run_id=run_id,
                payload={"roles": critical_roles, "signal_level": _level_value(decision.signal.level)},
            )
        if report.permission_violations:
            self.hitl.enqueue(
                kind="permission_violation",
                summary=f"审计 trace 中发现 {report.permission_violations} 次越权工具调用，需人工确认处理",
                run_id=run_id,
                payload={"count": report.permission_violations},
            )
        if not report.passed or report.numeric_error_rate > 0 or report.leakage_events or report.schema_errors:
            self.hitl.enqueue(
                kind="verification_failure",
                summary=(
                    f"核验未通过：numeric_error_rate={report.numeric_error_rate:.2%}, "
                    f"leakage={report.leakage_events}, permission={report.permission_violations}, "
                    f"schema={report.schema_errors}"
                ),
                run_id=run_id,
                payload={
                    "numeric_error_rate": report.numeric_error_rate,
                    "leakage_events": report.leakage_events,
                    "permission_violations": report.permission_violations,
                    "schema_errors": report.schema_errors,
                },
            )

    def _compose_final_advice(
        self,
        decision: DecisionCard,
        board: EvidenceBlackboard,
        degraded_roles: list[str],
        escalated_items: list[HITLItem],
        flags: ModeFlags,
    ) -> str:
        lines: list[str] = []
        if escalated_items:
            kinds = sorted({item.kind for item in escalated_items})
            lines.append(
                f"⚠️ 需人工复核（escalated）：{len(escalated_items)} 项待人工处理（{', '.join(kinds)}），"
                f"详见 HITL 队列与 trace。"
            )
        lines.append(
            f"【CBR-MAW 综合决策卡｜as_of {decision.as_of.isoformat()}｜mode {decision.mode.value}"
            f"｜run_id {decision.run_id}】"
        )
        mode_notes = {
            ExperimentMode.SINGLE: "单智能体模式：同一通用智能体依次完成三主体任务，无证据共享与交叉验证。",
            ExperimentMode.INDEPENDENT: "三独立智能体模式：三主体各自分析，无共享黑板、无交叉验证、无协调。",
            ExperimentMode.COLLABORATIVE: "完整协同模式：R0 独立分析 → R1 证据共享 → R2 交叉验证 → R3 分歧识别 → R4 协调仲裁。",
        }
        lines.append(mode_notes.get(decision.mode, ""))
        horizons = decision.signal.horizons or {}
        horizon_text = "，".join(
            f"{horizon}日={probability:.2%}" for horizon, probability in sorted(horizons.items())
        )
        lines.append(
            f"共享风险信号：风险等级 {_level_value(decision.signal.level)}；{horizon_text or '无期限概率'}"
            + (
                f"；历史分位 {decision.signal.percentile:.2%}"
                if decision.signal.percentile is not None
                else ""
            )
            + f"；模型 {decision.signal.model_version}"
        )
        lines.append("【三主体差异化建议】")
        for role in self.roles:
            card = decision.cards.get(role.value)
            if card is None:
                continue
            display = self.display_names.get(role.value, role.value)
            degraded = "（降级）" if role.value in degraded_roles else ""
            recommendation = (card.recommendation or "—").strip().replace("\n", " ")
            lines.append(
                f"- {display}{degraded}｜风险等级 {_level_value(card.risk_level)}｜"
                f"{card.headline.strip()}｜建议：{recommendation[:180]}"
            )
        if flags.coordinate:
            type_counts: dict[str, int] = {}
            for conflict in decision.conflicts:
                type_counts[conflict.type.value] = type_counts.get(conflict.type.value, 0) + 1
            if decision.conflicts:
                lines.append(
                    f"分歧说明：共 {len(decision.conflicts)} 项"
                    f"（事实 {type_counts.get('fact', 0)} / 方向 {type_counts.get('directional', 0)} / "
                    f"偏好 {type_counts.get('preference', 0)}），"
                    f"已解决 {decision.coordination.conflicts_resolved}，"
                    f"升级 {decision.coordination.conflicts_escalated}。"
                )
                for conflict in decision.conflicts[:6]:
                    lines.append(
                        f"  · {conflict.conflict_id}｜{conflict.type.value}｜{conflict.subject}｜"
                        f"{'已解决' if conflict.resolved else '未解决'}｜{conflict.resolution[:140]}"
                    )
            else:
                lines.append("分歧说明：未发现跨角色事实/方向/偏好冲突。")
        report = decision.verification
        lines.append(
            f"核验状态：数值错误率 {report.numeric_error_rate:.2%}"
            f"（{report.numeric_checks_passed}/{report.numeric_checks_total} 通过），"
            f"证据准确率 {report.evidence_accuracy:.2%}"
            f"（{report.citation_checks_passed}/{report.citation_checks_total}），"
            f"无依据断言 {report.unsupported_claims}，时点泄漏 {report.leakage_events}，"
            f"越权拦截 {report.permission_violations}，schema 错误 {report.schema_errors}。"
        )
        lines.append(
            f"协同成本：工具调用 {decision.coordination.tool_calls}"
            f"（预算上限 {self.budget_plan(decision.mode)['max_tool_calls']}），"
            f"tokens {decision.coordination.tokens}，时延 {decision.coordination.latency_ms}ms，"
            f"协调轮次 {decision.coordination.rounds}，"
            f"证据 {len(board)} 条（去重 {board.duplicate_evidence}）；"
            f"折算成本 C={decision.coordination.cost_usd:.6f}"
            f"（tool_calls×{float(getattr(self.orchestration, 'cost_per_tool_call', 0.0))}"
            f" + tokens/1k×{float(getattr(self.orchestration, 'cost_per_1k_tokens', 0.0))}"
            f" + latency_ms×{float(getattr(self.orchestration, 'cost_per_latency_ms', 0.0))}），"
            f"J = L + μ·C 口径 μ={self.coordination_weight_mu}"
            f"（L 由各主体 decision_loss 权重单独评估）。"
        )
        if degraded_roles:
            lines.append(f"降级说明：以下角色本轮分析异常，已使用降级卡片：{', '.join(degraded_roles)}。")
        lines.append(f"审计轨迹：{decision.trace_ref}（run_id={decision.run_id}）")
        return "\n".join(line for line in lines if line)

    def _write_decision_artifact(self, trace: TraceWriter, decision: DecisionCard) -> Any:
        try:
            return trace.write_decision(decision.model_dump(mode="json"))
        except Exception:  # pragma: no cover - 落盘失败不影响返回
            return trace.decision_path

    # ------------------------------------------------------------------ #
    # 数据加载 / 证据构造
    # ------------------------------------------------------------------ #
    def _load_signal(self, as_of: date, trace: TraceWriter) -> RiskSignal:
        try:
            signal = self.provider.risk_signal(as_of)
            if not isinstance(signal, RiskSignal):
                raise TypeError(f"provider.risk_signal 返回类型非法: {type(signal)!r}")
        except Exception as exc:
            trace.emit(
                step="R0",
                action="provider_error",
                detail={"stage": "risk_signal", "error": f"{type(exc).__name__}: {exc}", "fallback": True},
            )
            signal = RiskSignal(
                as_of=as_of,
                model_version="fallback-v0",
                horizons={5: 0.5, 10: 0.5, 20: 0.5},
                percentile=None,
                level=RiskLevel.MEDIUM,
            )
        if not signal.evidence_id:
            signal = signal.model_copy(
                update={"evidence_id": f"ev_sig_{as_of.isoformat()}_{signal.model_version}"}
            )
        return signal

    def _load_snapshot(self, as_of: date, trace: TraceWriter) -> MarketSnapshot:
        try:
            snapshot = self.provider.market_snapshot(as_of)
            if not isinstance(snapshot, MarketSnapshot):
                raise TypeError(f"provider.market_snapshot 返回类型非法: {type(snapshot)!r}")
            return snapshot
        except Exception as exc:
            trace.emit(
                step="R0",
                action="provider_error",
                detail={"stage": "market_snapshot", "error": f"{type(exc).__name__}: {exc}", "fallback": True},
            )
            return MarketSnapshot(as_of=as_of)

    def _signal_evidence(self, signal: RiskSignal, as_of: date) -> Evidence:
        evidence_id = signal.evidence_id or f"ev_sig_{as_of.isoformat()}_{signal.model_version}"
        horizon_text = "，".join(
            f"{horizon}日={probability:.2%}" for horizon, probability in sorted((signal.horizons or {}).items())
        )
        payload = {
            "model_version": signal.model_version,
            "horizons": {str(horizon): probability for horizon, probability in (signal.horizons or {}).items()},
            "percentile": signal.percentile,
            "level": _level_value(signal.level),
            "drivers": [
                driver.model_dump(mode="json") if hasattr(driver, "model_dump") else dict(driver)
                for driver in signal.drivers
            ],
            "modality_contrib": dict(signal.modality_contrib or {}),
            "label_version": signal.label_version,
        }
        return Evidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.SIGNAL,
            as_of=as_of,
            title=f"共享多模态风险信号（{signal.model_version}）",
            summary=f"风险等级 {_level_value(signal.level)}；{horizon_text or '无期限概率'}",
            payload=payload,
            value=None,
            unit=None,
            source=SourceRef(
                name="P1 多模态融合模型",
                url=None,
                doc_id=f"signal_{signal.model_version}",
                release_time=datetime.combine(as_of, dt_time.max, tzinfo=timezone.utc),
            ),
            produced_by="system:p1-fusion",
        )

    # ------------------------------------------------------------------ #
    # chat / 场景辅助
    # ------------------------------------------------------------------ #
    def _latest_scenario(self) -> Any:
        try:
            scenarios = load_scenarios()
        except Exception:  # pragma: no cover
            return None
        if not scenarios:
            return None
        return max(scenarios, key=lambda scenario: scenario.as_of)

    def _scenario_for(self, as_of: date) -> str | None:
        try:
            scenarios = load_scenarios()
        except Exception:  # pragma: no cover
            return None
        for scenario in scenarios:
            if scenario.as_of == as_of:
                return scenario.scenario_id
        return None

    def _collect_citations(self) -> list[SourceRef]:
        citations: list[SourceRef] = []
        seen: set[tuple[Any, ...]] = set()
        for evidence in self._last_index.values():
            for source in [evidence.source, *evidence.citations]:
                if source is None:
                    continue
                key = (source.name, source.url, source.doc_id, source.chunk_id)
                if key in seen:
                    continue
                if not (source.url or source.doc_id or source.chunk_id):
                    continue
                seen.add(key)
                citations.append(source)
                if len(citations) >= 10:
                    return citations
        return citations

    def _compose_chat_reply(self, message: str, decision: DecisionCard) -> str:
        lines = [
            f"已按「{decision.mode.value}」模式完成 {decision.as_of.isoformat()} 的协同预警分析。",
            f"你的问题：{message.strip()}",
            "",
            decision.final_advice,
        ]
        return "\n".join(line for line in lines if line)


# --------------------------------------------------------------------------- #
# 工厂函数（cbr.service 装配约定）
# --------------------------------------------------------------------------- #
def build_orchestrator(
    settings: Any,
    provider: Any,
    registry: Any,
    kb: Any = None,
    llm: Any = None,
    *,
    role_specs: Mapping[Any, RoleSpec] | None = None,
    agents: Mapping[Any, Any] | None = None,
    single_agent: Any = None,
    trace_dir: str | None = None,
    clock: Callable[[], datetime] | None = None,
    hitl: HITLQueue | None = None,
) -> OrchestratorImpl:
    """装配协同编排器。

    契约签名（``cbr.service`` 使用）::

        build_orchestrator(settings, provider, registry, kb, llm) -> Orchestrator

    额外关键字参数仅用于测试注入 / 演示：

    - ``agents``: ``{Role: AgentLike}`` 注入角色智能体（避免依赖 cbr.agents 就绪）；
    - ``single_agent``: 注入单智能体；
    - ``trace_dir`` / ``clock`` / ``hitl``：测试与演示用。
    """
    return OrchestratorImpl(
        settings,
        provider,
        registry,
        kb,
        llm,
        role_specs=role_specs,
        agents=agents,
        single_agent=single_agent,
        trace_dir=trace_dir,
        clock=clock,
        hitl=hitl,
    )


__all__ = [
    "OrchestratorImpl",
    "build_orchestrator",
    "build_role_agent_from_module",
    "build_role_agents_from_module",
    "build_single_agent_from_module",
    "MODE_FLAGS",
    "ModeFlags",
    "RoleAgentLike",
    "DEFAULT_ROLES",
]
