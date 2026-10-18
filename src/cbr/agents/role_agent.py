"""角色智能体（RoleAgent）：论文 4.3「三角色预警智能体」的工程实现。

每个角色使用**同一套 Agent Loop 代码**、不同的 :class:`RoleSpec` 配置：

1. 读取共享 ``RiskSignal``（唯一共同风险锚）与 ``MarketSnapshot``；
2. 按 ``RoleSpec.tool_permissions`` 选择工具 → 权限校验（越权只记 trace、不执行）
   → 调用确定性工具 → 收集 ``Evidence``；
3. 时点过滤知识库检索 → KB 证据（text claim 的引文来源）；
4. 把证据整理成机器可读"证据包"，交给底层 LLM（MockLLM 或 DeepSeek）生成
   结构化草稿 :class:`RoleAnalysisDraft`；
5. **自检回填**：numeric claim 的 value/unit 一律以工具证据为准（LLM 文本被替换
   为规范化表述），text claim 必须绑定 KB 证据，directional 必须绑定信号证据；
   无证据的主张直接丢弃并记 trace；
6. 按角色阈值确定性判定 ``risk_level``（LLM 的等级判断仅作参考，不生效），
   估算 ``decision_loss``，组装 ``RiskCard``；
7. 记录 ``llm_call`` / ``tool_call`` / ``tool_denied`` / ``kb_search`` / ``claim`` /
   ``cross_check`` / ``finalize`` 审计轨迹，返回 ``AgentOutput``。

Mock 模式与真实 DeepSeek 模式共用以上全部流程，只有 ``LLMClient`` 实现不同
（P3 对照实验的资源可比性依赖这一点）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..config import AppSettings
from ..contracts import DataProvider, KnowledgeBase, LLMClient, ToolRegistry
from ..llm.base import (
    LLMError,
    dumps,
    encode_packet,
    format_number,
)
from ..llm.drafts import (
    CrossCheckDraft,
    CrossCheckFinding,
    DraftClaim,
    RoleAnalysisDraft,
)
from ..llm.mock import MockLLM
from ..schemas import (
    AgentContext,
    AgentOutput,
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceKind,
    MetricItem,
    RiskCard,
    RiskLevel,
    Role,
    RoleSpec,
    SourceRef,
    ToolRef,
    ToolResult,
    TraceEvent,
)
from .prompts import (
    cross_check_system_prompt,
    cross_check_user_prompt,
    evidence_summary_text,
    horizon_word,
    peer_evidence_summary_text,
    role_system_prompt,
    role_user_prompt,
    signal_summary_text,
)

logger = logging.getLogger("cbr.agents.role_agent")

# 角色判定窗口：监管关注中期系统性压力，投资关注近端尾部风险，融资关注再融资窗口。
ROLE_HORIZONS: dict[Role, int] = {
    Role.REGULATOR: 10,
    Role.INVESTOR: 5,
    Role.FINANCING: 20,
}

LEVEL_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
LEVEL_CN: dict[RiskLevel, str] = {
    RiskLevel.LOW: "低",
    RiskLevel.MEDIUM: "中",
    RiskLevel.HIGH: "高",
    RiskLevel.CRITICAL: "极高",
}


@dataclass(frozen=True)
class ToolPlanItem:
    """一次计划中的工具调用。"""

    name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    purpose: str = ""


# 各角色的默认工具计划：工具名严格来自 configs/roles.yaml 的 tool_permissions；
# 参数名与 tools-knowledge 冻结的工具签名一致（全部有默认值，失败会防御式回退）。
_ROLE_TOOL_PLANS: dict[Role, tuple[ToolPlanItem, ...]] = {
    Role.REGULATOR: (
        ToolPlanItem(
            "systemic_risk",
            {"lookback": 252, "tail_q": 0.05, "dy_window": 120, "dy_horizon": 10},
            "跨市场溢出与系统性风险（ΔCoVaR / MES / DY 溢出）",
        ),
        ToolPlanItem(
            "risk_measure",
            {"lookback": 252, "confidence": 0.95, "horizon_days": 10},
            "市场压力测度（波动、VaR/CVaR、回撤、压力分位）",
        ),
        ToolPlanItem(
            "capital_flow",
            {"lookback": 60, "z_window": 60, "anomaly_z": 1.5},
            "跨境资金异常流动与同步撤离",
        ),
        ToolPlanItem(
            "scenario",
            {
                "us_equity_drop_pct": 10.0,
                "fx_depreciation_pct": 5.0,
                "spread_widening_bp": 100.0,
                "method": "both",
            },
            "外部冲击情景下的跨市场压力传导",
        ),
        ToolPlanItem(
            "forecast",
            {"horizon": 10, "include_drivers": True},
            "读取融合预测器的共享压力预测",
        ),
    ),
    Role.INVESTOR: (
        ToolPlanItem(
            "risk_measure",
            {"lookback": 252, "confidence": 0.99, "horizon_days": 5},
            "组合尾部风险测度（VaR/CVaR、回撤）",
        ),
        ToolPlanItem(
            "capital_flow",
            {"lookback": 60, "z_window": 60, "anomaly_z": 1.5},
            "跨境资金异常流动对风险偏好的冲击",
        ),
        ToolPlanItem(
            "systemic_risk",
            {"lookback": 252, "tail_q": 0.05, "dy_window": 120, "dy_horizon": 5},
            "跨市场相关性与风险传染",
        ),
        ToolPlanItem(
            "scenario",
            {
                "us_equity_drop_pct": 15.0,
                "fx_depreciation_pct": 5.0,
                "spread_widening_bp": 80.0,
                "method": "both",
            },
            "组合尾部损失情景分析",
        ),
        ToolPlanItem(
            "forecast",
            {"horizon": 5, "include_drivers": True},
            "读取近端压力预测",
        ),
    ),
    Role.FINANCING: (
        ToolPlanItem(
            "funding_cost",
            {"lookback": 252, "cost_jump_bp": 50.0, "refinancing_horizon_days": 90},
            "融资成本、信用利差与再融资窗口",
        ),
        ToolPlanItem(
            "scenario",
            {
                "fx_depreciation_pct": 7.0,
                "spread_widening_bp": 120.0,
                "method": "both",
            },
            "汇率与利差冲击下的融资成本情景",
        ),
        ToolPlanItem(
            "risk_measure",
            {"lookback": 252, "confidence": 0.95, "horizon_days": 20},
            "市场压力对融资环境的传导测度",
        ),
        ToolPlanItem(
            "forecast",
            {"horizon": 20, "include_drivers": True},
            "读取远端压力预测（再融资窗口）",
        ),
    ),
}

# 决策损失权重 → 损失侧映射（silent=不预警/不行动的期望损失；warn=预警/行动的期望成本）
_LOSS_SIDE: dict[str, str] = {
    "miss": "silent",
    "missed_exit": "silent",
    "tail_loss": "silent",
    "cost_overrun": "silent",
    "liquidity_shortfall": "silent",
    "delay": "silent",
    "false_alarm": "warn",
    "transaction_cost": "warn",
    "over_hedging": "warn",
}

_TOOL_LABELS: dict[str, str] = {
    "risk_measure": "风险测度指标",
    "systemic_risk": "系统性风险指标",
    "capital_flow": "跨境资金流指标",
    "funding_cost": "融资成本指标",
    "scenario": "情景压力指标",
    "forecast": "压力预测概率",
    "knowledge_search": "知识检索结果",
}

_METRIC_KEY_LABELS: dict[str, str] = {
    "volatility": "年化波动率",
    "vol": "年化波动率",
    "var_hist": "历史模拟 VaR",
    "var": "组合 VaR",
    "cvar": "组合 CVaR",
    "max_drawdown": "最大回撤",
    "dy_spillover": "跨市场溢出指数",
    "dy_spillover_index": "跨市场溢出指数",
    "delta_covar": "ΔCoVaR",
    "covar": "CoVaR",
    "mes": "边际期望损失",
    "northbound_outflow_z": "北向资金流出 z 值",
    "net_inflow_z": "跨境净流入 z 值",
    "synchronized_exit": "同步撤离指标",
    "concentration": "资金集中度",
    "ah_premium": "AH 溢价",
    "funding_cost_change_bp": "融资成本变化",
    "credit_spread": "信用利差",
    "refinancing_window_days": "再融资窗口",
    "scenario_loss": "情景组合损失",
    "expected_return": "情景预期收益",
    "prob_high_stress": "高压力概率",
}

_ROLE_FALLBACK_RECOMMENDATION: dict[Role, str] = {
    Role.REGULATOR: (
        "建议维持对跨市场压力与跨境资金异常的监测频率，重点关注主要压力驱动因子的演化，"
        "并在压力信号连续上行时启动跨部门会商与压力测试。"
    ),
    Role.INVESTOR: (
        "建议将组合风险预算向防御方向调整，降低高相关性资产敞口，评估对冲成本后对"
        "尾部风险进行保护，并在风险等级上调时执行降杠杆预案。"
    ),
    Role.FINANCING: (
        "建议提前锁定融资成本、适度拉长久期并保留充足现金流缓冲，梳理近期到期债务与"
        "再融资窗口，必要时启动备用授信。"
    ),
}

_BRACKET_DIGIT_RE = re.compile(r"[（(][^（）()]*[0-9０-９][^（）()]*[）)]")
_DIGIT_RE = re.compile(r"[0-9０-９]+")
_WS_RE = re.compile(r"\s+")

# 等级升级规则：角色阈值之外，若关键工具证据越过角色阈值则上调一级（审计可查）
_ESCALATION_RULES: dict[Role, tuple[tuple[str, tuple[str, ...]], ...]] = {
    Role.REGULATOR: (("dy_spillover", ("spillover", "溢出", "dy_", "systemic", "传染")),),
    Role.INVESTOR: (("max_drawdown", ("drawdown", "回撤", "cvar", "var", "尾部")),),
    Role.FINANCING: (("funding_cost_jump_bp", ("funding", "spread", "利差", "融资")),),
}


def _hash_payload(payload: Any, *, size: int = 16) -> str:
    """确定性短哈希（用于 trace 的 args_hash / result_hash）。"""

    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:size]


def _jsonable(value: Any) -> Any:
    """把任意对象转成可 JSON 序列化的纯 Python 值（trace detail 安全）。"""

    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _safe_label(text: Any, fallback: str = "工具指标") -> str:
    """生成不含数字的中文标签（保证 numeric claim 文本里只出现被核验的数值）。"""

    if text is None:
        return fallback
    cleaned = _BRACKET_DIGIT_RE.sub("", str(text))
    cleaned = _DIGIT_RE.sub("", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip(" ，。；：、（）()【】[]")
    return cleaned or fallback


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # 过滤 NaN


def _iter_numeric_leaves(payload: Any, *, depth: int = 0) -> Iterable[tuple[str, float]]:
    """递归遍历 payload 中的数值叶子（最多 3 层，跳过明显元数据键）。"""

    if depth > 2:
        return
    skip_keys = {
        "as_of",
        "version",
        "tool_version",
        "lookback",
        "n_obs",
        "n_observations",
        "elapsed_ms",
        "seed",
        "window",
        "horizon",
        "horizons",
        "confidence",
        "tail_q",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in skip_keys:
                continue
            number = _as_float(value)
            if number is not None:
                yield str(key), number
            elif isinstance(value, (dict, list)):
                yield from _iter_numeric_leaves(value, depth=depth + 1)
    elif isinstance(payload, list):
        for index, value in enumerate(payload[:5]):
            number = _as_float(value)
            if number is not None:
                yield f"value_{index}", number
            elif isinstance(value, (dict, list)):
                yield from _iter_numeric_leaves(value, depth=depth + 1)


def _primary_metric(evidence: Evidence) -> tuple[str, float] | None:
    """取证据的主指标：优先 evidence.value，否则取 payload 首个数值叶子。"""

    if evidence.value is not None:
        value = _as_float(evidence.value)
        if value is None:
            return None
        payload = evidence.payload or {}
        primary_name = payload.get("primary_metric")
        if isinstance(primary_name, str) and primary_name.strip():
            return primary_name.strip(), value
        for key, leaf in _iter_numeric_leaves(payload):
            if abs(leaf - value) <= max(1e-9, abs(value) * 1e-9):
                return key, value
        return "value", value
    for key, leaf in _iter_numeric_leaves(evidence.payload or {}):
        return key, leaf
    return None


class RoleAgent:
    """单角色智能体：同一循环代码 + 不同 RoleSpec。"""

    def __init__(
        self,
        role_spec: RoleSpec,
        registry: ToolRegistry,
        provider: DataProvider,
        kb: KnowledgeBase,
        llm: LLMClient,
        settings: AppSettings,
        *,
        system_prompt: str | None = None,
        tool_plan: Sequence[str] | None = None,
        enforce_registry_permissions: bool = True,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.role_spec = role_spec
        self.role = role_spec.role
        self.registry = registry
        self.provider = provider
        self.kb = kb
        self.llm = llm
        self.settings = settings
        self._logger = logger_ or logger
        self.system_prompt = system_prompt or role_system_prompt(role_spec)
        self._tool_plan_override = tuple(tool_plan) if tool_plan is not None else None
        # 单智能体基线（P3 对照）使用合成 generalist RoleSpec + 三主体工具并集，
        # 此时权限以合成 RoleSpec 白名单为准（注册表的 role→tool 矩阵仍按原角色配置，
        # 不应否决基线的并集权限）；真实三角色模式保持双重校验（默认 True）。
        self.enforce_registry_permissions = enforce_registry_permissions
        self._fallback_llm: MockLLM | None = None
        self.role_horizon = self._resolve_role_horizon()

    # ------------------------------------------------------------------ #
    # 公共入口
    # ------------------------------------------------------------------ #
    def analyze(self, context: AgentContext) -> AgentOutput:
        """对一次 ``AgentContext`` 完成角色分析，返回可审计的 ``AgentOutput``。"""

        started = time.perf_counter()
        run_id = self._run_id(context)
        step = self._step(context)
        trace: list[TraceEvent] = []
        tool_calls = 0
        tokens = 0

        signal = context.signal
        role_prob = self._role_probability(signal)
        risk_level = self._risk_level_from_signal(role_prob)
        signal_evidence = self._build_signal_evidence(context)
        trace.append(
            self._event(
                run_id,
                step,
                "signal",
                detail={
                    "evidence_id": signal_evidence.evidence_id,
                    "model_version": signal.model_version,
                    "role_horizon": self.role_horizon,
                    "role_probability": round(role_prob, 6),
                    "risk_level": risk_level.value,
                },
            )
        )

        tool_evidence, tool_trace, tool_calls, tool_errors = self._run_tool_plan(
            context, run_id, step
        )
        trace.extend(tool_trace)

        kb_evidence, kb_trace = self._search_knowledge(context, run_id, step)
        trace.extend(kb_trace)

        published: list[Evidence] = self._dedupe_evidence(
            [signal_evidence, *tool_evidence, *kb_evidence]
        )
        available = {item.evidence_id: item for item in published}
        base_level = risk_level
        risk_level, escalation = self._escalate_risk_level(risk_level, published)
        if risk_level != base_level:
            trace.append(
                self._event(
                    run_id,
                    step,
                    "risk_level",
                    detail={
                        "base_level": base_level.value,
                        "final_level": risk_level.value,
                        "escalated_by": escalation,
                    },
                )
            )
        facts = self._build_facts(published)
        key_metrics = self._build_key_metrics(published, signal, signal_evidence.evidence_id)

        packet = self._build_packet(
            context=context,
            run_id=run_id,
            step=step,
            risk_level=risk_level,
            role_prob=role_prob,
            facts=facts,
            signal=signal,
            signal_evidence=signal_evidence,
            tool_errors=tool_errors,
        )
        draft, llm_tokens, draft_trace = self._run_role_analysis(
            context=context,
            packet=packet,
            published=published,
            run_id=run_id,
            step=step,
        )
        tokens += llm_tokens
        trace.extend(draft_trace)

        claims = self._materialize_claims(
            draft.claims,
            available=available,
            signal_ref=signal_evidence.evidence_id,
            context=context,
            run_id=run_id,
            step=step,
            trace=trace,
        )

        cross_findings: list[CrossCheckFinding] = []
        cross_note = ""
        if context.round > 0 and context.peer_evidence:
            cross_findings, cross_tokens, cross_trace, cross_note = self._cross_validate(
                context=context,
                run_id=run_id,
                step=step,
                published=published,
                tokens_so_far=tokens,
            )
            tokens += cross_tokens
            trace.extend(cross_trace)

        decision_loss = self._decision_loss(role_prob, risk_level)
        limitations = self._build_limitations(
            context=context,
            draft=draft,
            kb_evidence=kb_evidence,
            tool_errors=tool_errors,
            cross_note=cross_note,
        )
        headline = self._headline(draft, risk_level)
        recommendation = (
            draft.recommendation.strip()
            if draft.recommendation and draft.recommendation.strip()
            else _ROLE_FALLBACK_RECOMMENDATION[self.role]
        )

        card_evidence_ids = list(
            dict.fromkeys(
                [
                    signal_evidence.evidence_id,
                    *[item.evidence_id for item in published],
                    *[metric.evidence_id for metric in key_metrics if metric.evidence_id],
                    *[eid for claim in claims for eid in claim.evidence_ids],
                ]
            )
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        card = RiskCard(
            role=self.role,
            as_of=context.as_of,
            risk_level=risk_level,
            headline=headline,
            base_signal_ref=signal_evidence.evidence_id,
            key_metrics=key_metrics,
            claims=claims,
            recommendation=recommendation,
            decision_loss=decision_loss,
            limitations=limitations,
            evidence_ids=card_evidence_ids,
            tool_calls=tool_calls,
            tokens=tokens,
            latency_ms=latency_ms,
            round=context.round,
        )
        card = RiskCard.model_validate(card.model_dump())  # schema 兜底校验
        trace.append(
            self._event(
                run_id,
                step,
                "finalize",
                detail={
                    "role": self.role.value,
                    "risk_level": risk_level.value,
                    "claims": len(claims),
                    "tool_calls": tool_calls,
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                    "llm_mode": getattr(self.llm, "mode", "unknown"),
                    "escalated_by": escalation,
                    "cross_check_findings": len(cross_findings),
                },
                latency_ms=latency_ms,
                tokens=tokens,
            )
        )
        return AgentOutput(
            role=self.role,
            card=card,
            evidence=published,
            tool_calls=tool_calls,
            tokens=tokens,
            latency_ms=latency_ms,
            trace=trace,
        )

    # ------------------------------------------------------------------ #
    # 工具调用 / 权限
    # ------------------------------------------------------------------ #
    def tool_plan(self) -> list[ToolPlanItem]:
        """当前角色的工具计划（单智能体基线会传入三主体工具并集覆盖）。"""

        if self._tool_plan_override is None:
            return list(_ROLE_TOOL_PLANS.get(self.role, ()))
        default_map: dict[str, ToolPlanItem] = {}
        for plans in _ROLE_TOOL_PLANS.values():
            for item in plans:
                default_map.setdefault(item.name, item)
        return [
            default_map.get(
                name,
                ToolPlanItem(name, {}, f"通用分析工具 {name}"),
            )
            for name in self._tool_plan_override
        ]

    def _check_permission(self, tool_name: str) -> tuple[bool, str]:
        """角色白名单 + 注册表权限矩阵双重校验；返回 (allowed, reason)。"""

        if tool_name not in self.role_spec.tool_permissions:
            return False, "not_in_role_permissions"
        if not self.enforce_registry_permissions:
            return True, "role_spec_only"
        try:
            allowed = bool(self.registry.allow(self.role, tool_name))
        except Exception as exc:  # noqa: BLE001 - 权限检查失败按拒绝处理（保守）
            return False, f"registry_error:{exc}"
        return (True, "allowed") if allowed else (False, "registry_denied")

    def _check_kb_permission(self) -> tuple[bool, str]:
        """知识库检索权限：角色白名单为主；仅当注册表确实登记了
        ``knowledge_search`` 工具时才再叠加注册表权限矩阵（避免注册表未包装
        KB 时误拦截）。"""

        if "knowledge_search" not in self.role_spec.tool_permissions:
            return False, "not_in_role_permissions"
        if not self.enforce_registry_permissions:
            return True, "role_spec_only"
        try:
            registry_names = set(self.registry.names())
        except Exception:  # noqa: BLE001 - 注册表异常时仅用角色白名单
            registry_names = set()
        if "knowledge_search" in registry_names:
            try:
                if not bool(self.registry.allow(self.role, "knowledge_search")):
                    return False, "registry_denied"
            except Exception as exc:  # noqa: BLE001
                return False, f"registry_error:{exc}"
        return True, "allowed"

    def _run_tool_plan(
        self, context: AgentContext, run_id: str, step: str
    ) -> tuple[list[Evidence], list[TraceEvent], int, list[str]]:
        """执行工具计划：越权只记 trace、不执行；失败工具记录后跳过。"""

        trace: list[TraceEvent] = []
        tool_evidence: list[Evidence] = []
        tool_errors: list[str] = []
        tool_calls = 0
        max_calls = self._max_tool_calls(context)

        for plan in self.tool_plan():
            if tool_calls >= max_calls:
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "tool_skip",
                        detail={"reason": "tool_budget_exhausted", "max_tool_calls": max_calls},
                    )
                )
                break

            allowed, reason = self._check_permission(plan.name)
            if not allowed:
                # 越权：记录审计事件，绝不执行（verifier 用 tool_denied 统计越权阻断）
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "tool_denied",
                        tool=plan.name,
                        detail={
                            "reason": reason,
                            "violation": True,
                            "allowed": False,
                            "purpose": plan.purpose,
                        },
                    )
                )
                continue

            tool = self._resolve_tool(plan.name)
            if tool is None:
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "tool_call",
                        tool=plan.name,
                        detail={
                            "ok": False,
                            "error": "tool_not_found",
                            "allowed": True,
                            "purpose": plan.purpose,
                        },
                    )
                )
                tool_errors.append(plan.name)
                continue

            tool_calls += 1
            started = time.perf_counter()
            result, used_kwargs, fallback = self._invoke_tool(tool, context, plan.kwargs)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            args_hash = _hash_payload({"as_of": context.as_of.isoformat(), "kwargs": used_kwargs})
            result_hash = _hash_payload(result.model_dump()) if result is not None else None

            if result is None:
                tool_errors.append(plan.name)
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "tool_call",
                        tool=plan.name,
                        args_hash=args_hash,
                        detail={
                            "ok": False,
                            "allowed": True,
                            "fallback_no_kwargs": fallback,
                            "purpose": plan.purpose,
                            "error": "tool_run_failed",
                        },
                        latency_ms=elapsed_ms,
                    )
                )
                continue

            if not result.ok:
                tool_errors.append(plan.name)
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "tool_call",
                        tool=plan.name,
                        args_hash=args_hash,
                        result_hash=result_hash,
                        detail={
                            "ok": False,
                            "allowed": True,
                            "purpose": plan.purpose,
                            "error": result.error or "tool_returned_not_ok",
                            "data_disallowed": bool(result.data.get("disallowed")),
                            "fallback_no_kwargs": fallback,
                        },
                        latency_ms=max(elapsed_ms, result.elapsed_ms),
                    )
                )
                continue

            evidence = self._evidence_from_tool_result(context, result, plan.name)
            if evidence is None:
                continue
            if evidence.as_of > context.as_of:
                # 时点泄漏防御：不使用 as_of 之后发布的工具证据
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "leakage_reject",
                        tool=plan.name,
                        detail={
                            "evidence_id": evidence.evidence_id,
                            "evidence_as_of": evidence.as_of.isoformat(),
                            "context_as_of": context.as_of.isoformat(),
                        },
                    )
                )
                continue

            tool_evidence.append(evidence)
            trace.append(
                self._event(
                    run_id,
                    step,
                    "tool_call",
                    tool=plan.name,
                    args_hash=args_hash,
                    result_hash=result_hash,
                    detail={
                        "ok": True,
                        "allowed": True,
                        "purpose": plan.purpose,
                        "evidence_id": evidence.evidence_id,
                        "tool_version": result.version,
                        "fallback_no_kwargs": fallback,
                        "value": evidence.value,
                        "unit": evidence.unit,
                    },
                    latency_ms=max(elapsed_ms, result.elapsed_ms),
                )
            )

        return tool_evidence, trace, tool_calls, tool_errors

    def _resolve_tool(self, name: str) -> Any | None:
        try:
            tool = self.registry.get(name)
        except Exception:  # noqa: BLE001 - KeyError/未注册工具统一视为不可用
            return None
        return tool if hasattr(tool, "run") else None

    def _invoke_tool(
        self, tool: Any, context: AgentContext, kwargs: dict[str, Any]
    ) -> tuple[ToolResult | None, dict[str, Any], bool]:
        """防御式调用工具：参数不兼容时回退到零参数签名（fallback=True）。"""

        tried_kwargs = dict(kwargs)
        try:
            raw = tool.run(context.as_of, **tried_kwargs)
        except TypeError:
            if not tried_kwargs:
                return None, tried_kwargs, False
            tried_kwargs = {}
            try:
                raw = tool.run(context.as_of)
                return self._coerce_tool_result(raw), {}, True
            except Exception:  # noqa: BLE001
                return None, {}, True
        except Exception:  # noqa: BLE001 - 工具失败不允许拖垮智能体
            return None, tried_kwargs, False
        return self._coerce_tool_result(raw), tried_kwargs, False

    @staticmethod
    def _coerce_tool_result(raw: Any) -> ToolResult | None:
        if isinstance(raw, ToolResult):
            return raw
        if isinstance(raw, dict):
            try:
                return ToolResult.model_validate(raw)
            except Exception:  # noqa: BLE001
                return None
        return None

    # ------------------------------------------------------------------ #
    # 证据构造
    # ------------------------------------------------------------------ #
    def _build_signal_evidence(self, context: AgentContext) -> Evidence:
        signal = context.signal
        evidence_id = signal.evidence_id or (
            f"ev_sig_{context.as_of.strftime('%Y%m%d')}_"
            f"{_safe_label(signal.model_version, 'signal')}"
        )
        payload = {
            "model_version": signal.model_version,
            "horizons": {str(h): float(p) for h, p in (signal.horizons or {}).items()},
            "percentile": signal.percentile,
            "level": signal.level.value,
            "drivers": [
                {
                    "factor": driver.factor,
                    "contribution": float(driver.contribution),
                    "direction": driver.direction,
                    "description": driver.description,
                }
                for driver in signal.drivers
            ],
            "modality_contrib": dict(signal.modality_contrib or {}),
            "label_version": signal.label_version,
        }
        return Evidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.SIGNAL,
            as_of=signal.as_of or context.as_of,
            title="共享多模态风险信号",
            summary=(
                f"融合预测器 {signal.model_version} 输出的多窗口高压力概率与驱动因子归因"
                f"（风险等级：{signal.level.value}）"
            ),
            payload=payload,
            unit="probability",
            value=None,
            source=SourceRef(name="risk_signal", doc_id=signal.model_version),
            tool=ToolRef(name="risk_signal", version=signal.model_version or "unknown"),
            produced_by=self.role.value,
            hash=_hash_payload(payload),
        )

    def _evidence_from_tool_result(
        self, context: AgentContext, result: ToolResult, plan_name: str
    ) -> Evidence | None:
        tool_name = result.tool_name or plan_name
        evidence = result.evidence
        if evidence is None:
            if not result.data:
                return None
            primary_value = _primary_metric_from_payload(result.data)
            evidence_id = (
                f"ev_tool_{tool_name}_{context.as_of.strftime('%Y%m%d')}_"
                f"{_hash_payload({'tool': tool_name, 'version': result.version, 'data': result.data}, size=12)}"
            )
            return Evidence(
                evidence_id=evidence_id,
                kind=EvidenceKind.TOOL,
                as_of=result.as_of,
                title=f"{tool_name} 工具输出",
                summary=f"{tool_name} v{result.version} 在 {result.as_of.isoformat()} 的计算结果",
                payload=dict(result.data),
                unit=result.unit,
                value=primary_value,
                source=SourceRef(name=f"tool:{tool_name}"),
                tool=ToolRef(
                    name=tool_name,
                    version=result.version,
                    elapsed_ms=result.elapsed_ms,
                ),
                produced_by=self.role.value,
                citations=list(result.citations),
                hash=_hash_payload(result.data),
            )

        updates: dict[str, Any] = {}
        if not evidence.produced_by or evidence.produced_by == "system":
            updates["produced_by"] = self.role.value
        if evidence.tool is None:
            updates["tool"] = ToolRef(
                name=tool_name, version=result.version, elapsed_ms=result.elapsed_ms
            )
        if evidence.source is None or evidence.source.name == "unknown":
            updates["source"] = SourceRef(name=f"tool:{tool_name}")
        if not evidence.citations:
            updates["citations"] = list(result.citations)
        if evidence.hash is None:
            updates["hash"] = _hash_payload(evidence.payload)
        return evidence.model_copy(update=updates) if updates else evidence

    def _search_knowledge(
        self, context: AgentContext, run_id: str, step: str
    ) -> tuple[list[Evidence], list[TraceEvent]]:
        """时点过滤知识库检索（text claim 的引文来源）。"""

        trace: list[TraceEvent] = []
        if self.kb is None:
            return [], trace
        allowed, reason = self._check_kb_permission()
        if not allowed:
            trace.append(
                self._event(
                    run_id,
                    step,
                    "tool_denied",
                    tool="knowledge_search",
                    detail={"reason": reason, "violation": True, "allowed": False},
                )
            )
            return [], trace

        query = self._knowledge_query(context)
        started = time.perf_counter()
        try:
            items = self.kb.search(query, context.as_of, top_k=3)
        except Exception as exc:  # noqa: BLE001 - KB 不可用不阻塞分析
            trace.append(
                self._event(
                    run_id,
                    step,
                    "kb_search",
                    tool="knowledge_search",
                    detail={"ok": False, "error": str(exc)[:300], "query": query},
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            return [], trace

        evidence_items: list[Evidence] = []
        for item in items or []:
            if not isinstance(item, Evidence):
                continue
            if item.as_of > context.as_of:
                continue  # 时点过滤双保险
            evidence_items.append(item)
        evidence_items = self._dedupe_evidence(evidence_items)
        trace.append(
            self._event(
                run_id,
                step,
                "kb_search",
                tool="knowledge_search",
                detail={
                    "ok": True,
                    "query": query,
                    "as_of": context.as_of.isoformat(),
                    "hits": len(evidence_items),
                    "evidence_ids": [item.evidence_id for item in evidence_items],
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        return evidence_items, trace

    def _knowledge_query(self, context: AgentContext) -> str:
        focus = " ".join(self.role_spec.focus[:2]) or self.role_spec.display_name
        drivers = " ".join(driver.factor for driver in context.signal.drivers[:2])
        task = (context.task or "").strip()
        parts = [focus, "跨境 金融 风险 政策 方法学", drivers, task]
        return " ".join(part for part in parts if part)[:200]

    @staticmethod
    def _dedupe_evidence(items: Iterable[Evidence]) -> list[Evidence]:
        seen: set[str] = set()
        result: list[Evidence] = []
        for item in items:
            if item.evidence_id in seen:
                continue
            seen.add(item.evidence_id)
            result.append(item)
        return result

    # ------------------------------------------------------------------ #
    # 证据包 / prompt
    # ------------------------------------------------------------------ #
    def _build_facts(self, published: Sequence[Evidence]) -> list[dict[str, Any]]:
        """把证据整理成 LLM 可引用的"事实卡"。

        只有 kind=tool 的数值证据可成为 numeric fact（LLM 数值唯一来源）；
        KB 证据成为 text fact；信号证据不直接给数值（避免同一 evidence_id
        在不同角色下出现不同主指标，破坏共享风险锚）。
        """

        facts: list[dict[str, Any]] = []
        for evidence in published:
            if evidence.kind == EvidenceKind.TOOL:
                primary = _primary_metric(evidence)
                if primary is None:
                    continue
                key, value = primary
                label = _METRIC_KEY_LABELS.get(key) or _TOOL_LABELS.get(
                    getattr(evidence.tool, "name", ""), "工具指标"
                )
                label = _safe_label(label, "工具指标")
                facts.append(
                    {
                        "evidence_id": evidence.evidence_id,
                        "kind": evidence.kind.value,
                        "title": evidence.title,
                        "label": label,
                        "subject": label,
                        "summary": evidence.summary,
                        "value": value,
                        "unit": evidence.unit,
                        "claim_type": "numeric",
                    }
                )
            elif evidence.kind == EvidenceKind.KB:
                facts.append(
                    {
                        "evidence_id": evidence.evidence_id,
                        "kind": evidence.kind.value,
                        "title": evidence.title,
                        "label": _safe_label(evidence.title, "知识库片段"),
                        "subject": evidence.title,
                        "summary": evidence.summary,
                        "value": None,
                        "unit": None,
                        "claim_type": "text",
                    }
                )
        return facts

    def _build_key_metrics(
        self,
        published: Sequence[Evidence],
        signal: Any,
        signal_ref: str,
    ) -> list[MetricItem]:
        metrics: list[MetricItem] = []
        horizons = {int(h): float(p) for h, p in (signal.horizons or {}).items()}
        for horizon in sorted(horizons):
            metrics.append(
                MetricItem(
                    name=f"prob_high_stress_h{horizon}",
                    label=f"{horizon_word(horizon)}高压力概率",
                    value=horizons[horizon],
                    unit="probability",
                    evidence_id=signal_ref,
                    description="共享多模态风险信号（P1 融合预测器）",
                )
            )
        for evidence in published:
            if evidence.kind != EvidenceKind.TOOL:
                continue
            primary = _primary_metric(evidence)
            if primary is None:
                continue
            key, value = primary
            metrics.append(
                MetricItem(
                    name=_safe_metric_name(key or "value"),
                    label=_METRIC_KEY_LABELS.get(key) or _TOOL_LABELS.get(
                        getattr(evidence.tool, "name", ""), "工具指标"
                    ),
                    value=value,
                    unit=evidence.unit,
                    evidence_id=evidence.evidence_id,
                    description=(
                        f"工具 {getattr(evidence.tool, 'name', 'tool')} "
                        f"v{getattr(evidence.tool, 'version', '?')}"
                    ),
                )
            )
            if len(metrics) >= 8:
                break
        return metrics[:8]

    def _build_packet(
        self,
        *,
        context: AgentContext,
        run_id: str,
        step: str,
        risk_level: RiskLevel,
        role_prob: float,
        facts: list[dict[str, Any]],
        signal: Any,
        signal_evidence: Evidence,
        tool_errors: list[str],
    ) -> dict[str, Any]:
        peer_facts = [
            {
                "evidence_id": evidence.evidence_id,
                "kind": getattr(evidence.kind, "value", str(evidence.kind)),
                "title": evidence.title,
                "value": evidence.value,
                "unit": evidence.unit,
                "produced_by": evidence.produced_by,
            }
            for evidence in context.peer_evidence
            if evidence.as_of <= context.as_of
        ]
        return {
            "run_id": run_id,
            "step": step,
            "as_of": context.as_of.isoformat(),
            "mode": context.mode.value,
            "round": context.round,
            "task": context.task,
            "role_key": self.role.value,
            "role": {
                "key": self.role.value,
                "display_name": self.role_spec.display_name,
                "objective": self.role_spec.objective,
                "focus": list(self.role_spec.focus),
                "info_permissions": list(self.role_spec.info_permissions),
                "tool_permissions": list(self.role_spec.tool_permissions),
                "thresholds": dict(self.role_spec.thresholds),
                "decision_loss_weights": dict(self.role_spec.decision_loss_weights),
                "output_style": self.role_spec.output_style,
                "forbidden_actions": list(self.role_spec.forbidden_actions),
            },
            "signal": {
                "as_of": signal.as_of.isoformat(),
                "model_version": signal.model_version,
                "horizons": {str(h): float(p) for h, p in (signal.horizons or {}).items()},
                "percentile": signal.percentile,
                "level": signal.level.value,
                "label_version": signal.label_version,
                "evidence_id": signal_evidence.evidence_id,
                "drivers": [
                    {
                        "factor": driver.factor,
                        "contribution": float(driver.contribution),
                        "direction": driver.direction,
                        "description": driver.description,
                    }
                    for driver in signal.drivers
                ],
                "modality_contrib": dict(signal.modality_contrib or {}),
            },
            "risk_level": risk_level.value,
            "role_horizon": self.role_horizon,
            "role_probability": round(role_prob, 6),
            "facts": facts,
            "limitations_hints": self._limitation_hints(tool_errors),
            "peer_facts": peer_facts,
        }

    def _limitation_hints(self, tool_errors: Sequence[str]) -> list[str]:
        hints = [
            "仅使用 as_of 当日及之前已发布的证据与知识库片段。",
            "工具结果受数据覆盖期与参数设定影响，跨市场口径可能不完全一致。",
        ]
        if tool_errors:
            hints.append("部分工具调用失败，相应维度未纳入本次分析。")
        if not self.role_spec.tool_permissions:
            hints.append("角色未配置工具权限，数值证据可能不足。")
        return hints

    def _run_role_analysis(
        self,
        *,
        context: AgentContext,
        packet: dict[str, Any],
        published: Sequence[Evidence],
        run_id: str,
        step: str,
    ) -> tuple[RoleAnalysisDraft, int, list[TraceEvent]]:
        trace: list[TraceEvent] = []
        signal_text = signal_summary_text(context.signal, role_horizon=self.role_horizon)
        evidence_text = evidence_summary_text(
            [item for item in published if item.kind != EvidenceKind.SIGNAL]
        )
        user_prompt = role_user_prompt(
            self.role_spec,
            as_of=context.as_of.isoformat(),
            mode=context.mode.value,
            round_no=context.round,
            task=context.task,
            signal_text=signal_text,
            evidence_text=evidence_text,
            peer_text=peer_evidence_summary_text(list(context.peer_evidence)),
            packet_text=encode_packet(packet),
        )
        draft, tokens, llm_trace = self._call_llm(
            system=self.system_prompt,
            user=user_prompt,
            schema=RoleAnalysisDraft,
            purpose="role_analysis",
            run_id=run_id,
            step=step,
            trace=trace,
        )
        trace.extend(llm_trace)
        if draft is None:
            # 真实模型不可用时降级为本地确定性规则模板，保证卡片仍可产出且可溯源
            fallback = self._get_fallback_llm()
            fallback_before = fallback.usage
            try:
                draft = fallback.structured(self.system_prompt, user_prompt, RoleAnalysisDraft)
                fallback_delta = self._usage_delta(fallback_before, fallback.usage)
                draft = draft.model_copy(
                    update={
                        "limitations": [
                            *draft.limitations,
                            "LLM 调用失败，已降级为本地规则模板输出（证据链仍完整可溯源）。",
                        ]
                    }
                )
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "llm_fallback",
                        detail={"mode": "mock_rule_template", "schema": "RoleAnalysisDraft"},
                        tokens=fallback_delta["total_tokens"],
                    )
                )
                tokens += fallback_delta["total_tokens"]
            except Exception as exc:  # noqa: BLE001 - 最后兜底
                self._logger.exception("规则模板降级也失败：%s", exc)
                draft = RoleAnalysisDraft(
                    headline="",
                    claims=[],
                    recommendation="",
                    limitations=["LLM 与规则模板均不可用，本次仅提供证据摘要。"],
                )
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "llm_error",
                        detail={"error": str(exc)[:300], "stage": "fallback"},
                    )
                )
        return draft, tokens, trace

    def _call_llm(
        self,
        *,
        system: str,
        user: str,
        schema: type,
        purpose: str,
        run_id: str,
        step: str,
        trace: list[TraceEvent],
    ) -> tuple[Any | None, int, list[TraceEvent]]:
        """调用 LLM 并记录 llm_call / llm_error 审计事件；异常不向上抛出。"""

        events: list[TraceEvent] = []
        before = self.llm.usage
        started = time.perf_counter()
        try:
            result = self.llm.structured(system, user, schema)
        except LLMError as exc:
            after = self.llm.usage
            delta = self._usage_delta(before, after)
            events.append(
                self._event(
                    run_id,
                    step,
                    "llm_call",
                    detail={
                        "ok": False,
                        "purpose": purpose,
                        "schema": getattr(schema, "__name__", str(schema)),
                        "llm_mode": getattr(self.llm, "mode", "unknown"),
                        "prompt_tokens": delta["prompt_tokens"],
                        "completion_tokens": delta["completion_tokens"],
                        "calls": delta["calls"],
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    tokens=delta["total_tokens"],
                )
            )
            events.append(
                self._event(
                    run_id,
                    step,
                    "llm_error",
                    detail={"purpose": purpose, "error_type": type(exc).__name__},
                    tokens=delta["total_tokens"],
                )
            )
            return None, delta["total_tokens"], events

        after = self.llm.usage
        delta = self._usage_delta(before, after)
        last_call = dict(getattr(self.llm, "last_call", {}) or {})
        events.append(
            self._event(
                run_id,
                step,
                "llm_call",
                detail={
                    "ok": True,
                    "purpose": purpose,
                    "schema": getattr(schema, "__name__", str(schema)),
                    "llm_mode": last_call.get("mode") or getattr(self.llm, "mode", "unknown"),
                    "prompt_tokens": delta["prompt_tokens"],
                    "completion_tokens": delta["completion_tokens"],
                    "calls": delta["calls"],
                    "attempts": last_call.get("attempts"),
                    **{
                        key: last_call[key]
                        for key in ("transport_attempts", "prompt_chars", "completion_chars")
                        if key in last_call
                    },
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
                tokens=delta["total_tokens"],
            )
        )
        return result, delta["total_tokens"], events

    @staticmethod
    def _usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {
            key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "calls")
        }

    def _get_fallback_llm(self) -> MockLLM:
        if self._fallback_llm is None:
            self._fallback_llm = MockLLM()
        return self._fallback_llm

    # ------------------------------------------------------------------ #
    # Claim 自检与回填
    # ------------------------------------------------------------------ #
    def _materialize_claims(
        self,
        draft_claims: Sequence[DraftClaim],
        *,
        available: dict[str, Evidence],
        signal_ref: str,
        context: AgentContext,
        run_id: str,
        step: str,
        trace: list[TraceEvent],
    ) -> list[Claim]:
        claims: list[Claim] = []
        for index, draft_claim in enumerate(draft_claims[:8]):
            claim = self._materialize_claim(
                draft_claim, available=available, signal_ref=signal_ref, index=index + 1
            )
            if claim is None:
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "claim_rejected",
                        detail={
                            "index": index + 1,
                            "claim_type": str(getattr(draft_claim, "claim_type", "unknown")),
                            "reason": "unsupported_by_evidence",
                            "evidence_ids": list(draft_claim.evidence_ids),
                        },
                    )
                )
                continue
            claims.append(claim)
            trace.append(
                self._event(
                    run_id,
                    step,
                    "claim",
                    detail={
                        "claim_id": claim.claim_id,
                        "claim_type": claim.claim_type.value,
                        "value": claim.value,
                        "unit": claim.unit,
                        "direction": claim.direction,
                        "evidence_ids": claim.evidence_ids,
                        "status": claim.status.value,
                    },
                )
            )
        if not claims:
            # 极端情况（证据不足/LLM 输出全部不可溯源）：用规则模板从证据生成
            for fallback_claim in self._template_claims(available, signal_ref, context.signal):
                claims.append(fallback_claim)
                trace.append(
                    self._event(
                        run_id,
                        step,
                        "claim",
                        detail={
                            "claim_id": fallback_claim.claim_id,
                            "claim_type": fallback_claim.claim_type.value,
                            "evidence_ids": fallback_claim.evidence_ids,
                            "source": "deterministic_template",
                        },
                    )
                )
        return claims

    def _materialize_claim(
        self,
        draft_claim: DraftClaim,
        *,
        available: dict[str, Evidence],
        signal_ref: str,
        index: int,
    ) -> Claim | None:
        evidence_ids = [eid for eid in draft_claim.evidence_ids if eid in available]
        if not evidence_ids:
            return None
        try:
            claim_type = ClaimType(draft_claim.claim_type)
        except ValueError:
            claim_type = ClaimType.TEXT

        if claim_type == ClaimType.NUMERIC:
            # 数值唯一来源：kind=tool 且带 value 的证据；LLM 给的 value/unit 一律被覆盖
            numeric_evidence = next(
                (
                    available[eid]
                    for eid in evidence_ids
                    if available[eid].kind == EvidenceKind.TOOL
                    and available[eid].value is not None
                ),
                None,
            )
            if numeric_evidence is None or numeric_evidence.value is None:
                return None
            value = float(numeric_evidence.value)
            unit = numeric_evidence.unit or draft_claim.unit
            label = _safe_label(
                draft_claim.subject
                or (numeric_evidence.title if numeric_evidence.title else "工具指标")
            )
            text = f"{label}为 {format_number(value)}" + (f" {unit}" if unit else "") + "。"
            return Claim(
                claim_id=self._claim_id(index),
                role=self.role.value,
                claim_type=ClaimType.NUMERIC,
                subject=label,
                text=text,
                value=value,
                unit=unit,
                direction=None,
                evidence_ids=_ordered_ids(evidence_ids, numeric_evidence.evidence_id),
                confidence=_clamp_confidence(draft_claim.confidence, default=0.9),
                status=ClaimStatus.UNVERIFIED,
            )

        if claim_type == ClaimType.TEXT:
            kb_ids = [
                eid for eid in evidence_ids if available[eid].kind == EvidenceKind.KB
            ]
            if not kb_ids:
                return None
            text = (draft_claim.text or "").strip() or "知识库证据支持该判断。"
            return Claim(
                claim_id=self._claim_id(index),
                role=self.role.value,
                claim_type=ClaimType.TEXT,
                subject=(draft_claim.subject or available[kb_ids[0]].title).strip(),
                text=text,
                value=None,
                unit=None,
                direction=None,
                evidence_ids=kb_ids,
                confidence=_clamp_confidence(draft_claim.confidence, default=0.8),
                status=ClaimStatus.UNVERIFIED,
            )

        # DIRECTIONAL：必须绑定信号证据（优先）或其他可用证据
        direction = draft_claim.direction if draft_claim.direction in {"up", "down", "flat", "none"} else "none"
        ordered_ids = _ordered_ids(evidence_ids, signal_ref) if signal_ref in evidence_ids else evidence_ids
        text = (draft_claim.text or "").strip() or "基于现有证据的方向性判断。"
        return Claim(
            claim_id=self._claim_id(index),
            role=self.role.value,
            claim_type=ClaimType.DIRECTIONAL,
            subject=(draft_claim.subject or "方向性判断").strip(),
            text=text,
            value=None,
            unit=None,
            direction=direction,
            evidence_ids=ordered_ids,
            confidence=_clamp_confidence(draft_claim.confidence, default=0.75),
            status=ClaimStatus.UNVERIFIED,
        )

    def _claim_id(self, index: int) -> str:
        return f"{self.role.value}-c{index}"

    def _template_claims(
        self, available: dict[str, Evidence], signal_ref: str, signal: Any
    ) -> list[Claim]:
        """确定性兜底 claims（无 LLM 或 LLM 输出全部不可溯源时使用）。"""

        claims: list[Claim] = []
        numeric_evidence = [
            evidence
            for evidence in available.values()
            if evidence.kind == EvidenceKind.TOOL and evidence.value is not None
        ]
        for evidence in numeric_evidence[:2]:
            primary = _primary_metric(evidence)
            if primary is None:
                continue
            key, value = primary
            label = _safe_label(
                _METRIC_KEY_LABELS.get(key)
                or _TOOL_LABELS.get(getattr(evidence.tool, "name", ""), "工具指标")
            )
            unit = evidence.unit
            claims.append(
                Claim(
                    claim_id=self._claim_id(len(claims) + 1),
                    role=self.role.value,
                    claim_type=ClaimType.NUMERIC,
                    subject=label,
                    text=f"{label}为 {format_number(value)}" + (f" {unit}" if unit else "") + "。",
                    value=value,
                    unit=unit,
                    evidence_ids=[evidence.evidence_id],
                    confidence=0.85,
                    status=ClaimStatus.UNVERIFIED,
                )
            )
        for evidence in [
            item for item in available.values() if item.kind == EvidenceKind.KB
        ][:2]:
            claims.append(
                Claim(
                    claim_id=self._claim_id(len(claims) + 1),
                    role=self.role.value,
                    claim_type=ClaimType.TEXT,
                    subject=evidence.title,
                    text="知识库中的政策与方法学证据为当前判断提供依据。",
                    evidence_ids=[evidence.evidence_id],
                    confidence=0.75,
                    status=ClaimStatus.UNVERIFIED,
                )
            )
        drivers = list(getattr(signal, "drivers", []) or [])
        signal_item = available.get(signal_ref)
        if signal_item is not None:
            factor = str(drivers[0].factor) if drivers else "共享风险信号"
            direction = str(drivers[0].direction) if drivers else "up"
            claims.append(
                Claim(
                    claim_id=self._claim_id(len(claims) + 1),
                    role=self.role.value,
                    claim_type=ClaimType.DIRECTIONAL,
                    subject=f"主要风险驱动：{factor}" if drivers else "共享风险信号方向",
                    text=(
                        f"{factor} 是当前共享压力信号的主要驱动因子，方向"
                        f"{'上行' if direction != 'down' else '下行'}。"
                        if drivers
                        else "当前共享风险信号指向压力方向。"
                    ),
                    direction=direction if direction in {"up", "down", "flat", "none"} else "up",  # type: ignore[arg-type]
                    evidence_ids=[signal_ref],
                    confidence=0.7,
                    status=ClaimStatus.UNVERIFIED,
                )
            )
        return claims

    # ------------------------------------------------------------------ #
    # 风险等级 / 决策损失 / 局限
    # ------------------------------------------------------------------ #
    def _resolve_role_horizon(self) -> int:
        default = ROLE_HORIZONS.get(self.role, 10)
        configured = self.role_spec.thresholds.get("horizon_days")
        return int(configured) if configured else default

    def _role_probability(self, signal: Any) -> float:
        horizons = {int(h): float(p) for h, p in (signal.horizons or {}).items()}
        if not horizons:
            percentile = _as_float(getattr(signal, "percentile", None))
            return max(0.0, min(1.0, percentile or 0.0))
        if self.role_horizon in horizons:
            return max(0.0, min(1.0, horizons[self.role_horizon]))
        nearest = min(horizons, key=lambda horizon: abs(horizon - self.role_horizon))
        return max(0.0, min(1.0, horizons[nearest]))

    def _risk_level_from_signal(self, probability: float) -> RiskLevel:
        thresholds = self.role_spec.thresholds or {}
        high = _as_float(thresholds.get("high_stress_prob"))
        critical = _as_float(thresholds.get("critical_stress_prob"))
        high = 0.5 if high is None else high
        critical = min(0.95, high + 0.2) if critical is None else critical
        if probability >= critical:
            return RiskLevel.CRITICAL
        if probability >= high:
            return RiskLevel.HIGH
        if probability >= high * 0.5:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _escalate_risk_level(
        self, level: RiskLevel, published: Sequence[Evidence]
    ) -> tuple[RiskLevel, str | None]:
        """关键工具证据越过角色阈值时上调一级（记录触发证据，便于审计/核验）。"""

        thresholds = self.role_spec.thresholds or {}
        for threshold_key, keywords in _ESCALATION_RULES.get(self.role, ()):
            threshold = _as_float(thresholds.get(threshold_key))
            if threshold is None:
                continue
            for evidence in published:
                if evidence.value is None or evidence.kind != EvidenceKind.TOOL:
                    continue
                haystack = " ".join(
                    [
                        str(evidence.title or ""),
                        str(getattr(evidence.tool, "name", "") or ""),
                        " ".join(str(key) for key in (evidence.payload or {}).keys()),
                    ]
                ).lower()
                if not any(keyword.lower() in haystack for keyword in keywords):
                    continue
                if abs(float(evidence.value)) < threshold:
                    continue
                if LEVEL_ORDER[level] < LEVEL_ORDER[RiskLevel.CRITICAL]:
                    return _next_level(level), evidence.evidence_id
        return level, None

    def _decision_loss(self, probability: float, level: RiskLevel) -> dict[str, float]:
        """基于信号概率与角色损失权重的归一化期望损失估计（非货币金额）。"""

        weights = self.role_spec.decision_loss_weights or {
            "miss": 1.0,
            "false_alarm": 1.0,
        }
        components: dict[str, float] = {}
        warn_total = 0.0
        silent_total = 0.0
        for name, weight in weights.items():
            side = _LOSS_SIDE.get(name, "silent")
            factor = probability if side == "silent" else (1.0 - probability)
            contribution = float(weight) * factor
            components[f"expected_{name}"] = round(contribution, 6)
            if side == "warn":
                warn_total += contribution
            else:
                silent_total += contribution
        components["if_warn_total"] = round(warn_total, 6)
        components["if_silent_total"] = round(silent_total, 6)
        recommended = (
            warn_total if LEVEL_ORDER[level] >= LEVEL_ORDER[RiskLevel.HIGH] else silent_total
        )
        components["recommended_total"] = round(recommended, 6)
        components["signal_probability"] = round(probability, 6)
        return components

    def _build_limitations(
        self,
        *,
        context: AgentContext,
        draft: RoleAnalysisDraft,
        kb_evidence: Sequence[Evidence],
        tool_errors: Sequence[str],
        cross_note: str,
    ) -> list[str]:
        limitations: list[str] = []
        for item in draft.limitations:
            text = str(item).strip()
            if text and text not in limitations:
                limitations.append(text)
        system_notes = [
            "风险等级由共享信号概率与角色阈值确定性判定，LLM 不直接决定等级。",
            "关键数值均来自版本化确定性工具证据，claim 数值已按证据回填。",
            "决策损失为基于信号概率与角色损失权重的归一化期望估计，非真实货币金额。",
        ]
        if not kb_evidence:
            system_notes.append("知识库检索不可用或为空：本次分析未包含政策/方法学文本证据。")
        if tool_errors:
            system_notes.append("部分工具调用失败，相应维度未纳入本次分析。")
        already_mentions_mock = any(
            "MockLLM" in item or "规则模板" in item for item in limitations
        )
        if getattr(self.llm, "is_mock", False) and not already_mentions_mock:
            system_notes.append(
                "当前为 MockLLM 确定性离线模式：文本结论由规则模板生成，仅用于流程验证。"
            )
        if cross_note:
            system_notes.append(cross_note)
        for note in system_notes:
            if note not in limitations:
                limitations.append(note)
        return limitations[:8]

    def _headline(self, draft: RoleAnalysisDraft, level: RiskLevel) -> str:
        headline = (draft.headline or "").strip()
        if headline:
            return headline[:160]
        return f"{self.role_spec.display_name}风险等级：{LEVEL_CN[level]}"

    # ------------------------------------------------------------------ #
    # 交叉验证（R2）
    # ------------------------------------------------------------------ #
    def _cross_validate(
        self,
        *,
        context: AgentContext,
        run_id: str,
        step: str,
        published: Sequence[Evidence],
        tokens_so_far: int,
    ) -> tuple[list[CrossCheckFinding], int, list[TraceEvent], str]:
        trace: list[TraceEvent] = []
        peer = [
            evidence
            for evidence in context.peer_evidence
            if isinstance(evidence, Evidence) and evidence.as_of <= context.as_of
        ]
        if not peer:
            return [], 0, trace, ""
        max_tokens = self._max_tokens(context)
        if tokens_so_far >= max_tokens:
            trace.append(
                self._event(
                    run_id,
                    step,
                    "cross_check_skip",
                    detail={"reason": "token_budget_exhausted", "max_tokens": max_tokens},
                )
            )
            return [], 0, trace, ""

        peer_facts = [
            {
                "evidence_id": evidence.evidence_id,
                "kind": getattr(evidence.kind, "value", str(evidence.kind)),
                "title": evidence.title,
                "value": evidence.value,
                "unit": evidence.unit,
                "produced_by": evidence.produced_by,
                "as_of": evidence.as_of.isoformat(),
            }
            for evidence in peer
        ]
        cross_packet = {
            "run_id": run_id,
            "step": step,
            "as_of": context.as_of.isoformat(),
            "round": context.round,
            "role_key": self.role.value,
            "role": {"key": self.role.value, "display_name": self.role_spec.display_name},
            "peer_facts": peer_facts,
            "own_evidence_ids": [evidence.evidence_id for evidence in published],
        }
        user_prompt = cross_check_user_prompt(
            self.role_spec,
            as_of=context.as_of.isoformat(),
            round_no=context.round,
            peer_text=peer_evidence_summary_text(peer),
            own_evidence_text=evidence_summary_text(
                [item for item in published if item.kind != EvidenceKind.SIGNAL]
            ),
            packet_text=encode_packet(cross_packet),
        )
        draft, tokens, llm_trace = self._call_llm(
            system=cross_check_system_prompt(self.role_spec),
            user=user_prompt,
            schema=CrossCheckDraft,
            purpose="cross_check",
            run_id=run_id,
            step=step,
            trace=trace,
        )
        trace.extend(llm_trace)
        if draft is None:
            return [], tokens, trace, ""

        peer_ids = {evidence.evidence_id for evidence in peer}
        findings = [finding for finding in draft.findings if finding.evidence_id in peer_ids][:2]
        for finding in findings:
            trace.append(
                self._event(
                    run_id,
                    step,
                    "cross_check",
                    detail={
                        "evidence_id": finding.evidence_id,
                        "verdict": finding.verdict,
                        "note": finding.note,
                        "recomputed_value": finding.recomputed_value,
                    },
                )
            )
        if findings:
            note = "已对共享黑板上的 peer 证据完成交叉复核。"
        else:
            note = "peer 证据无法定位到本角色可用证据编号，未形成有效交叉复核结论。"
        if draft.summary:
            trace.append(
                self._event(
                    run_id,
                    step,
                    "cross_check",
                    detail={"summary": draft.summary},
                )
            )
        return findings, tokens, trace, note

    # ------------------------------------------------------------------ #
    # 预算 / 运行标识 / trace
    # ------------------------------------------------------------------ #
    def _max_tool_calls(self, context: AgentContext) -> int:
        budget_value = _as_float(context.budget.get("max_tool_calls"))
        if budget_value is not None and budget_value > 0:
            return int(budget_value)
        orchestration = getattr(self.settings, "orchestration", None)
        return int(getattr(orchestration, "max_tool_calls_per_agent", 6) or 6)

    def _max_tokens(self, context: AgentContext) -> int:
        budget_value = _as_float(context.budget.get("max_tokens"))
        if budget_value is not None and budget_value > 0:
            return int(budget_value)
        orchestration = getattr(self.settings, "orchestration", None)
        return int(getattr(orchestration, "max_tokens_per_agent", 4000) or 4000)

    def _run_id(self, context: AgentContext) -> str:
        run_id = str(context.budget.get("run_id") or "").strip()
        if run_id:
            return run_id
        return f"{self.role.value}-{context.as_of.strftime('%Y%m%d')}"

    def _step(self, context: AgentContext) -> str:
        step = str(context.budget.get("step") or "").strip()
        return step or f"R{context.round}"

    def _event(
        self,
        run_id: str,
        step: str,
        action: str,
        *,
        tool: str | None = None,
        args_hash: str | None = None,
        result_hash: str | None = None,
        detail: dict[str, Any] | None = None,
        latency_ms: int = 0,
        tokens: int = 0,
    ) -> TraceEvent:
        return TraceEvent(
            run_id=run_id,
            step=step,
            role=self.role.value,
            action=action,
            tool=tool,
            args_hash=args_hash,
            result_hash=result_hash,
            detail=_jsonable(detail or {}),
            latency_ms=max(0, int(latency_ms)),
            tokens=max(0, int(tokens)),
        )


# --------------------------------------------------------------------------- #
# 模块级工具函数
# --------------------------------------------------------------------------- #
def _primary_metric_from_payload(payload: dict[str, Any]) -> float | None:
    for _, value in _iter_numeric_leaves(payload):
        return value
    return None


def _safe_metric_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_.-]", "_", str(name or "value")).strip("_")
    return cleaned or "value"


def _ordered_ids(evidence_ids: Sequence[str], preferred: str) -> list[str]:
    ordered = [eid for eid in evidence_ids if eid == preferred]
    ordered.extend(eid for eid in evidence_ids if eid != preferred)
    return ordered


def _clamp_confidence(value: float | None, *, default: float) -> float:
    number = _as_float(value)
    if number is None:
        return default
    return max(0.0, min(1.0, number))


def _next_level(level: RiskLevel) -> RiskLevel:
    order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    return order[min(len(order) - 1, order.index(level) + 1)]


def build_role_agent(
    role_spec: RoleSpec,
    registry: ToolRegistry,
    provider: DataProvider,
    kb: KnowledgeBase,
    llm: LLMClient,
    settings: AppSettings,
    *,
    system_prompt: str | None = None,
    tool_plan: Sequence[str] | None = None,
    enforce_registry_permissions: bool = True,
) -> RoleAgent:
    """构建单角色智能体（settings 位于最后，与类签名一致）。"""

    return RoleAgent(
        role_spec=role_spec,
        registry=registry,
        provider=provider,
        kb=kb,
        llm=llm,
        settings=settings,
        system_prompt=system_prompt,
        tool_plan=tool_plan,
        enforce_registry_permissions=enforce_registry_permissions,
    )


def build_role_agents(
    registry: ToolRegistry,
    provider: DataProvider,
    kb: KnowledgeBase,
    llm: LLMClient,
    settings: AppSettings,
    *,
    role_specs: dict[Role, RoleSpec] | None = None,
) -> dict[Role, RoleAgent]:
    """一次构建三角色智能体（编排层最常用入口）。"""

    if role_specs is None:
        from ..config import load_role_specs

        role_specs = load_role_specs()
    return {
        role: build_role_agent(spec, registry, provider, kb, llm, settings)
        for role, spec in role_specs.items()
    }


__all__ = [
    "LEVEL_CN",
    "LEVEL_ORDER",
    "ROLE_HORIZONS",
    "RoleAgent",
    "ToolPlanItem",
    "build_role_agent",
    "build_role_agents",
]
