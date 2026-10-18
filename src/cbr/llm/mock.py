"""MockLLM：无 API key 时的确定性离线实现。

设计目标（对应 task-3）：

- **不联网、无随机性**：同一 prompt + 同一证据包必得同一输出，便于测试与演示；
- **不编造数值**：所有 numeric claim 的 ``value/unit`` 均从证据包（工具/信号
  证据）逐字抄录，text claim 只引用证据包中的 KB 证据编号；
- **与真实模型同构**：同样返回 ``RoleAnalysisDraft`` / ``CrossCheckDraft``，
  RoleAgent 不需要为 mock 分支写特殊流程（P3 模式对比公平）；
- 用量统计（prompt/completion tokens、calls）按字符数保守估计后累计，
  保证编排层的 token 预算/成本统计在 mock 模式下仍然可用。
"""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from .base import BaseLLMClient, LLMError, extract_packet, format_number
from .drafts import CrossCheckDraft, CrossCheckFinding, DraftClaim, RoleAnalysisDraft

_LEVEL_CN = {"low": "低", "medium": "中", "high": "高", "critical": "极高"}

_RECOMMENDATIONS: dict[str, str] = {
    "regulator": (
        "建议维持对跨市场压力与跨境资金异常的监测频率，重点关注主要压力驱动因子的演化，"
        "并在压力信号连续上行或风险等级上调时启动跨部门会商与压力测试。"
    ),
    "investor": (
        "建议将组合风险预算向防御方向调整，降低高相关性资产敞口，评估对冲工具成本后"
        "对尾部风险进行保护，并在风险等级上调时执行降杠杆预案。"
    ),
    "financing": (
        "建议提前锁定融资成本、适度拉长久期并保留充足现金流缓冲，梳理近期到期债务与"
        "再融资窗口，必要时启动备用授信。"
    ),
}

# 通用（未知角色）兜底建议
_DEFAULT_RECOMMENDATION = "建议持续监测压力信号与关键驱动因子，并在风险等级上调时按预案处置。"


class MockLLM(BaseLLMClient):
    """确定性规则模板 LLM。

    对 ``RoleAnalysisDraft`` / ``CrossCheckDraft`` 会解析 user prompt 中的
    证据包并生成规则化结果；对其他 schema 返回最小可校验实例，保证协议可用。
    """

    provider = "mock"
    model = "mock-rule-v1"
    is_mock = True

    # ------------------------------------------------------------------ #
    # LLMClient 协议
    # ------------------------------------------------------------------ #
    def structured(self, system: str, user: str, schema: type, **kwargs: Any) -> BaseModel:  # type: ignore[override]
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise LLMError(f"MockLLM.structured 需要 Pydantic model schema，收到 {schema!r}")

        prompt_tokens = self.estimate_tokens(system) + self.estimate_tokens(user)
        packet = extract_packet(user)
        payload = self._payload_for(schema, packet, system=system, user=user)

        try:
            result = schema.model_validate(payload)
        except Exception:  # pragma: no cover - 兜底：任意 schema 给最小合法实例
            result = schema.model_validate(_minimal_payload(schema))

        completion_tokens = self.estimate_tokens(result.model_dump_json())
        self._record_usage(prompt_tokens, completion_tokens, calls=1)
        self._set_last_call(
            mode="mock",
            model=self.model,
            schema=schema.__name__,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_chars=len(system) + len(user),
            completion_chars=len(result.model_dump_json()),
            attempts=1,
            packet_found=packet is not None,
        )
        return result

    def text(self, system: str, user: str, **kwargs: Any) -> str:
        prompt_tokens = self.estimate_tokens(system) + self.estimate_tokens(user)
        packet = extract_packet(user) or {}
        role_view = packet.get("role") if isinstance(packet.get("role"), dict) else {}
        display = role_view.get("display_name") or "分析智能体"
        as_of = packet.get("as_of") or "未知时点"
        level = packet.get("risk_level") or "medium"
        content = (
            f"[MockLLM · 确定性离线模式] {display} 在 {as_of} 的结论："
            f"当前风险等级为{_LEVEL_CN.get(str(level), '中')}。"
            "本回复由规则模板生成，仅用于流程验证；接入 API key 后同一代码路径将调用真实模型。"
        )
        completion_tokens = self.estimate_tokens(content)
        self._record_usage(prompt_tokens, completion_tokens, calls=1)
        self._set_last_call(
            mode="mock",
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_chars=len(system) + len(user),
            completion_chars=len(content),
            attempts=1,
        )
        return content

    # ------------------------------------------------------------------ #
    # 结构化 payload 生成
    # ------------------------------------------------------------------ #
    def _payload_for(
        self,
        schema: type[BaseModel],
        packet: dict[str, Any] | None,
        *,
        system: str,
        user: str,
    ) -> dict[str, Any]:
        packet = packet or {}
        if issubclass(schema, RoleAnalysisDraft):
            return self._role_analysis(packet).model_dump()
        if issubclass(schema, CrossCheckDraft):
            return self._cross_check(packet).model_dump()
        # 其他 schema：若证据包显式携带 payload 则用之，否则最小实例
        explicit = packet.get("schema_payload")
        if isinstance(explicit, dict):
            return explicit
        return _minimal_payload(schema)

    # -- 角色分析 ---------------------------------------------------------
    def _role_analysis(self, packet: dict[str, Any]) -> RoleAnalysisDraft:
        role_view = packet.get("role") if isinstance(packet.get("role"), dict) else {}
        role_key = str(packet.get("role_key") or role_view.get("key") or role_view.get("role") or "")
        display_name = str(role_view.get("display_name") or "分析智能体")
        risk_level = str(packet.get("risk_level") or "medium")
        signal_view = packet.get("signal") if isinstance(packet.get("signal"), dict) else {}
        signal_evidence_id = str(signal_view.get("evidence_id") or "")
        facts = [f for f in packet.get("facts", []) if isinstance(f, dict)]
        drivers = [d for d in signal_view.get("drivers", []) if isinstance(d, dict)]

        claims: list[DraftClaim] = []

        # 1) 数值 claim：从证据包 numeric facts 抄录 value/unit（不编造数字）
        numeric_facts = [
            fact
            for fact in facts
            if fact.get("claim_type") == "numeric" and _as_float(fact.get("value")) is not None
        ]
        for fact in numeric_facts[:2]:
            value = _as_float(fact.get("value"))
            unit = fact.get("unit")
            label = str(fact.get("label") or fact.get("subject") or "工具指标")
            value_text = format_number(value) if value is not None else ""
            unit_text = f" {unit}" if unit else ""
            claims.append(
                DraftClaim(
                    claim_type="numeric",
                    subject=str(fact.get("subject") or label),
                    text=f"{label}为 {value_text}{unit_text}。",
                    value=value,
                    unit=str(unit) if unit else None,
                    evidence_ids=[str(fact.get("evidence_id"))],
                    confidence=0.9,
                )
            )

        # 2) 文本 claim：绑定 KB 证据编号
        kb_facts = [fact for fact in facts if fact.get("claim_type") == "text"]
        for fact in kb_facts[:2]:
            title = str(fact.get("title") or "知识库片段")
            claims.append(
                DraftClaim(
                    claim_type="text",
                    subject=title,
                    text="知识库中的政策与方法学证据为当前判断提供依据。",
                    evidence_ids=[str(fact.get("evidence_id"))],
                    confidence=0.8,
                )
            )

        # 3) 方向 claim：基于共享信号的最强驱动因子
        if drivers:
            top = drivers[0]
            factor = str(top.get("factor") or "主要风险因子")
            direction = top.get("direction") if top.get("direction") in ("up", "down") else "up"
            claims.append(
                DraftClaim(
                    claim_type="directional",
                    subject=f"主要风险驱动：{factor}",
                    text=f"{factor} 是当前共享压力信号的主要驱动因子，方向{ '上行' if direction == 'up' else '下行' }。",
                    direction=direction,
                    evidence_ids=[signal_evidence_id] if signal_evidence_id else [],
                    confidence=0.75,
                )
            )
        elif signal_evidence_id:
            claims.append(
                DraftClaim(
                    claim_type="directional",
                    subject="共享风险信号方向",
                    text="当前共享风险信号指向压力方向。",
                    direction="up",
                    evidence_ids=[signal_evidence_id],
                    confidence=0.6,
                )
            )

        limitations = ["当前为 MockLLM 规则模板模式，文本结论用于离线流程验证。"]
        for hint in packet.get("limitations_hints", []) or []:
            if isinstance(hint, str) and hint.strip():
                limitations.append(hint.strip())

        return RoleAnalysisDraft(
            headline=f"{display_name}风险等级：{_LEVEL_CN.get(risk_level, '中')}",
            risk_level_assessment=risk_level if risk_level in _LEVEL_CN else None,
            claims=claims,
            recommendation=_RECOMMENDATIONS.get(role_key, _DEFAULT_RECOMMENDATION),
            limitations=limitations,
            decision_loss_comment="决策损失按角色损失权重与信号概率的期望值估计（归一化单位）。",
        )

    # -- 交叉验证 ---------------------------------------------------------
    def _cross_check(self, packet: dict[str, Any]) -> CrossCheckDraft:
        peer_facts = [f for f in packet.get("peer_facts", []) if isinstance(f, dict)]
        numeric = [
            fact
            for fact in peer_facts
            if _as_float(fact.get("value")) is not None and fact.get("evidence_id")
        ]
        findings: list[CrossCheckFinding] = []
        for fact in numeric[:2]:
            findings.append(
                CrossCheckFinding(
                    evidence_id=str(fact.get("evidence_id")),
                    verdict="confirmed",
                    note=(
                        "规则模板复核：该数值来自已登记版本号的工具证据，"
                        "与本时点证据包口径一致，未发现超过容差的差异。"
                    ),
                    recomputed_value=_as_float(fact.get("value")),
                )
            )
        summary = (
            f"共复核 {len(findings)} 条 peer 数值证据，规则模板未发现异常。"
            if findings
            else "peer 证据中没有可复核的数值证据，本轮不做数值断言。"
        )
        return CrossCheckDraft(findings=findings, summary=summary)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _minimal_payload(model: type[BaseModel]) -> dict[str, Any]:
    """为任意 Pydantic schema 构造最小可校验 payload（深度受限，防递归爆栈）。"""

    return _minimal_model_payload(model, depth=0)


def _minimal_model_payload(model: type[BaseModel], *, depth: int) -> dict[str, Any]:
    if depth > 4:  # pragma: no cover - 保护
        return {}
    payload: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if not field.is_required():
            continue
        payload[name] = _minimal_value(field.annotation, depth=depth + 1)
    return payload


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _minimal_value(annotation: Any, *, depth: int) -> Any:  # noqa: C901 - 类型分支较多
    if depth > 4:  # pragma: no cover - 保护
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is None:
        if annotation is str:
            return ""
        if annotation is int:
            return 0
        if annotation is float:
            return 0.0
        if annotation is bool:
            return False
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return _minimal_model_payload(annotation, depth=depth + 1)
        return None

    # Union / Optional
    if _is_union(origin):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _minimal_value(non_none[0], depth=depth + 1)
        if any(arg is type(None) for arg in args):
            return None
        return _minimal_value(non_none[0], depth=depth + 1) if non_none else None

    if origin in (list, set, tuple, frozenset):
        return []
    if origin is dict:
        return {}
    if str(origin) == "typing.Literal":
        return args[0] if args else None
    if isinstance(origin, type) and issubclass(origin, BaseModel):
        return _minimal_model_payload(origin, depth=depth + 1)
    # Annotated / 其他容器
    if args:
        return _minimal_value(args[0], depth=depth + 1)
    return None


__all__ = ["MockLLM"]
