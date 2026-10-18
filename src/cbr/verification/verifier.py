"""横切 A：验证与审计层 —— 六类核验器。

``verify(decision, evidence_index, settings) -> VerificationReport`` 对应架构 3.6：

===================  =====================================================  ===========================
核验项              规则                                                    计入字段
===================  =====================================================  ===========================
numeric              claim.value / claim.text 中的数字 vs 引用证据数值        numeric_checks_total/passed
citation             claim.evidence_ids 必须存在；KB 证据必须有 chunk_id 且  citation_checks_total/passed
                     publish_time <= as_of
unsupported          claim 未绑定任何 evidence_ids                            unsupported_claims
leakage              evidence.as_of / release_time > as_of                   leakage_events
permission           trace 中 tool_denied / tool_call allowed=false           permission_violations
schema               RiskCard/Claim 重新校验失败、claim_id 重复/缺失、角色错位   schema_errors
===================  =====================================================  ===========================

说明：

- 数值核验只拿 claim 自己绑定的证据做比对；跨角色证据一致性由冲突仲裁（R3/R4）负责，
  两者互补（仲裁发现“各引各证”的分歧，核验发现“自证不自洽”的数值错误与幻觉）。
- 偏好差异（``Claim.status == PREFERENCE``）不产生任何错误计数：它只是阈值/权重不同。
- 所有“无法比对”的情形（证据里没有可复算数值）按 0 次检查处理，不虚增分母。
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from ..schemas import (
    Claim,
    ClaimType,
    DecisionCard,
    Evidence,
    EvidenceKind,
    RiskCard,
    TraceEvent,
    VerificationIssue,
    VerificationReport,
)
from .numeric import DEFAULT_ABS_TOL, DEFAULT_REL_TOL, extract_numbers, flatten_numbers, numbers_match
from .trace import read_trace

_VIOLATION_ACTIONS = {"tool_denied", "permission_violation", "permission_denied"}
_TOOL_ACTIONS = {"tool_call", "tool"}
_EXCLUDED_FROM_PERMISSION = {"cross_check", "cross_validation", "tool_recompute_skipped"}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def resolve_tolerances(settings: Any = None) -> tuple[float, float]:
    """从 AppSettings / OrchestrationSettings / dict 中解析 (abs_tol, rel_tol)。"""
    if settings is None:
        return DEFAULT_ABS_TOL, DEFAULT_REL_TOL
    candidate = getattr(settings, "orchestration", settings)
    if candidate is None:
        return DEFAULT_ABS_TOL, DEFAULT_REL_TOL
    if isinstance(candidate, Mapping):
        abs_tol = candidate.get("numeric_tolerance_abs", DEFAULT_ABS_TOL)
        rel_tol = candidate.get("numeric_tolerance_rel", DEFAULT_REL_TOL)
    else:
        abs_tol = getattr(candidate, "numeric_tolerance_abs", DEFAULT_ABS_TOL)
        rel_tol = getattr(candidate, "numeric_tolerance_rel", DEFAULT_REL_TOL)
    try:
        return float(abs_tol), float(rel_tol)
    except (TypeError, ValueError):  # pragma: no cover - 配置异常兜底
        return DEFAULT_ABS_TOL, DEFAULT_REL_TOL


def _role_str(card: RiskCard | None) -> str | None:
    if card is None:
        return None
    role = card.role
    return role.value if hasattr(role, "value") else str(role)


def _to_date(value: Any) -> date | None:
    """兼容 date / datetime / ISO 字符串 → date。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value[:10]
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def _fmt(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _add_issue(
    report: VerificationReport,
    issue_type: str,
    detail: str,
    *,
    role: str | None = None,
    claim_id: str | None = None,
    severity: str = "warning",
) -> None:
    report.issues.append(
        VerificationIssue(
            issue_type=issue_type,  # type: ignore[arg-type]
            role=role,
            claim_id=claim_id,
            detail=detail,
            severity=severity,  # type: ignore[arg-type]
        )
    )


# --------------------------------------------------------------------------- #
# 证据索引归一化
# --------------------------------------------------------------------------- #
def _coerce_evidence(item: Any) -> Evidence | None:
    if isinstance(item, Evidence):
        return item
    if isinstance(item, Mapping):
        try:
            return Evidence.model_validate(item)
        except ValidationError:
            return None
    if hasattr(item, "evidence_id") and hasattr(item, "model_dump"):
        try:
            return Evidence.model_validate(item.model_dump())
        except ValidationError:
            return None
    return None


def _normalize_evidence_index(evidence_index: Any, report: VerificationReport) -> dict[str, Evidence]:
    """把 Mapping / list[Evidence] / 黑板对象统一成 ``{evidence_id: Evidence}``。"""
    index: dict[str, Evidence] = {}
    if evidence_index is None:
        return index

    # 支持直接传黑板（黑板的 index() 是 dict）
    candidate = evidence_index
    index_attr = getattr(candidate, "index", None)
    if callable(index_attr) and not isinstance(candidate, Mapping):
        try:
            candidate = index_attr()
        except TypeError:  # pragma: no cover - 非常规签名
            candidate = None
    if candidate is None:
        return index

    items: Iterable[Any]
    if isinstance(candidate, Mapping):
        items = list(candidate.items())
    else:
        items = [(None, item) for item in candidate]

    for key, raw in items:
        evidence = _coerce_evidence(raw)
        if evidence is None:
            report.schema_errors += 1
            _add_issue(
                report,
                "schema",
                f"证据索引项 {key!r} 无法通过 Evidence schema 校验: {raw!r:.120}",
                severity="error",
            )
            continue
        eid = evidence.evidence_id or (str(key) if key is not None else "")
        if not eid:
            report.schema_errors += 1
            _add_issue(report, "schema", "证据缺少 evidence_id", severity="error")
            continue
        index[eid] = evidence
    return index


# --------------------------------------------------------------------------- #
# 证据数值 / 引文
# --------------------------------------------------------------------------- #
def _evidence_numbers(evidence: Evidence) -> list[float]:
    numbers = flatten_numbers(evidence.payload)
    if evidence.value is not None:
        try:
            numbers.insert(0, float(evidence.value))
        except (TypeError, ValueError):  # pragma: no cover
            pass
    # KB 证据的数值通常写在 summary 文本里
    if evidence.kind in (EvidenceKind.KB, EvidenceKind.POLICY):
        for number in extract_numbers(evidence.summary):
            if number not in numbers:
                numbers.append(number)
    return numbers


def _claim_evidence_numbers(claim: Claim, index: dict[str, Evidence]) -> list[float]:
    """claim 所绑定证据中的全部数值。"""
    numbers: list[float] = []
    for evidence_id in claim.evidence_ids:
        evidence = index.get(evidence_id)
        if evidence is None:
            continue
        for number in _evidence_numbers(evidence):
            if number not in numbers:
                numbers.append(number)
    return numbers


def _claim_reference_numbers(claim: Claim, index: dict[str, Evidence]) -> list[float]:
    """证据数值 + claim.value（用于文本数字比对与 recommendation 依据集合）。"""
    numbers = _claim_evidence_numbers(claim, index)
    if claim.value is not None:
        try:
            value = float(claim.value)
            if value not in numbers:
                numbers.append(value)
        except (TypeError, ValueError):  # pragma: no cover
            pass
    return numbers


def _evidence_grade(evidence: Evidence | None) -> int:
    if evidence is None:
        return 0
    if evidence.kind == EvidenceKind.TOOL:
        return 3
    if evidence.kind in (EvidenceKind.KB, EvidenceKind.POLICY):
        return 2
    return 1


# --------------------------------------------------------------------------- #
# 六类核验
# --------------------------------------------------------------------------- #
def _check_schema(report: VerificationReport, decision: DecisionCard) -> None:
    """RiskCard / Claim 级 schema 与一致性校验。"""
    for role_key, card in decision.cards.items():
        if card is None:
            report.schema_errors += 1
            _add_issue(report, "schema", f"角色 {role_key} 的子卡片缺失", role=str(role_key), severity="error")
            continue
        if not isinstance(card, RiskCard):
            report.schema_errors += 1
            _add_issue(
                report, "schema", f"角色 {role_key} 的子卡片类型非法: {type(card)!r}", role=str(role_key), severity="error"
            )
            continue
        try:
            RiskCard.model_validate(card.model_dump(mode="python"))
        except ValidationError as exc:
            report.schema_errors += 1
            _add_issue(
                report,
                "schema",
                f"RiskCard[{role_key}] 重新校验失败: {exc.errors()[:2]}",
                role=str(role_key),
                severity="error",
            )
        card_role = card.role.value if hasattr(card.role, "value") else str(card.role)
        seen_claim_ids: set[str] = set()
        for claim in card.claims:
            if not claim.claim_id:
                report.schema_errors += 1
                _add_issue(
                    report, "schema", f"RiskCard[{role_key}] 存在缺少 claim_id 的主张", role=str(role_key), severity="error"
                )
            elif claim.claim_id in seen_claim_ids:
                report.schema_errors += 1
                _add_issue(
                    report,
                    "schema",
                    f"RiskCard[{role_key}] claim_id 重复: {claim.claim_id}",
                    role=str(role_key),
                    claim_id=claim.claim_id,
                    severity="error",
                )
            else:
                seen_claim_ids.add(claim.claim_id)
            claim_role = str(claim.role or "")
            if claim_role and claim_role not in {card_role, str(role_key)}:
                report.schema_errors += 1
                _add_issue(
                    report,
                    "schema",
                    f"主张 {claim.claim_id} 的 role={claim_role!r} 与卡片角色 {card_role!r} 不一致",
                    role=str(role_key),
                    claim_id=claim.claim_id,
                    severity="error",
                )


def _check_leakage(report: VerificationReport, decision: DecisionCard, index: dict[str, Evidence]) -> None:
    as_of = decision.as_of
    flagged: set[str] = set()

    def _flag(evidence: Evidence, detail: str) -> None:
        key = evidence.evidence_id or detail
        if key in flagged:
            return
        flagged.add(key)
        report.leakage_events += 1
        _add_issue(report, "leakage", detail, severity="error")

    for evidence in index.values():
        ev_date = _to_date(evidence.as_of)
        if ev_date is not None and ev_date > as_of:
            _flag(evidence, f"证据 {evidence.evidence_id} 的 as_of={ev_date} 晚于决策 as_of={as_of}")
        for source in [evidence.source, *evidence.citations]:
            publish = _to_date(getattr(source, "release_time", None))
            if publish is not None and publish > as_of:
                _flag(
                    evidence,
                    f"证据 {evidence.evidence_id} 的来源 {source.name!r} release_time={_fmt(source.release_time)} 晚于 as_of={as_of}",
                )

    signal_date = _to_date(decision.signal.as_of)
    if signal_date is not None and signal_date > as_of:
        report.leakage_events += 1
        _add_issue(report, "leakage", f"共享风险信号 as_of={signal_date} 晚于决策 as_of={as_of}", severity="error")


def _check_claim_citation(
    report: VerificationReport,
    card: RiskCard,
    claim: Claim,
    index: dict[str, Evidence],
    as_of: date,
) -> None:
    role = _role_str(card)
    if not claim.evidence_ids:
        report.unsupported_claims += 1
        _add_issue(
            report,
            "unsupported",
            f"主张 {claim.claim_id}（{claim.claim_type.value}）未绑定任何 evidence_id，属于无依据断言",
            role=role,
            claim_id=claim.claim_id,
            severity="warning",
        )
        return

    report.citation_checks_total += 1
    problems: list[str] = []
    for evidence_id in claim.evidence_ids:
        evidence = index.get(evidence_id)
        if evidence is None:
            problems.append(f"引用的证据不存在: {evidence_id}")
            continue
        if evidence.kind == EvidenceKind.KB:
            chunk_id = evidence.source.chunk_id or next(
                (c.chunk_id for c in evidence.citations if c.chunk_id), None
            )
            publish = evidence.source.release_time or next(
                (c.release_time for c in evidence.citations if c.release_time), None
            )
            if not chunk_id:
                problems.append(f"KB 证据 {evidence_id} 缺少 chunk_id")
            if publish is None:
                problems.append(f"KB 证据 {evidence_id} 缺少 publish_time")
            elif _to_date(publish) is not None and _to_date(publish) > as_of:  # type: ignore[operator]
                problems.append(
                    f"KB 证据 {evidence_id} 的 publish_time={_fmt(publish)} 晚于 as_of={as_of}"
                )
    if problems:
        _add_issue(
            report,
            "citation",
            f"主张 {claim.claim_id} 引文核验失败: {'; '.join(problems)}",
            role=role,
            claim_id=claim.claim_id,
            severity="error",
        )
    else:
        report.citation_checks_passed += 1


def _check_claim_numeric(
    report: VerificationReport,
    card: RiskCard,
    claim: Claim,
    index: dict[str, Evidence],
    abs_tol: float,
    rel_tol: float,
) -> None:
    role = _role_str(card)
    text_numbers = extract_numbers(claim.text)
    evidence_numbers = _claim_evidence_numbers(claim, index)
    value = claim.value

    if claim.claim_type == ClaimType.NUMERIC or (
        claim.claim_type == ClaimType.DIRECTIONAL and value is not None
    ):
        report.numeric_checks_total += 1
        problems: list[str] = []
        if value is None:
            problems.append("数值型主张缺少 value 字段")
        else:
            if evidence_numbers:
                if not any(numbers_match(value, ref, abs_tol, rel_tol) for ref in evidence_numbers):
                    problems.append(
                        f"claim.value={value} 与引用证据数值 {evidence_numbers[:6]} 不匹配"
                    )
            elif not text_numbers:
                problems.append("数值型主张缺少可复算的工具/知识库证据数值")
            if text_numbers:
                text_candidates = list(evidence_numbers)
                text_candidates.append(float(value))
                unmatched = [
                    number
                    for number in text_numbers
                    if not any(numbers_match(number, ref, abs_tol, rel_tol) for ref in text_candidates)
                ]
                if unmatched:
                    problems.append(f"claim.text 中数字 {unmatched} 无法在引用证据/claim.value 中找到依据")
        if problems:
            _add_issue(
                report,
                "numeric",
                f"主张 {claim.claim_id} 数值核验失败: {'; '.join(problems)}",
                role=role,
                claim_id=claim.claim_id,
                severity="error",
            )
        else:
            report.numeric_checks_passed += 1
        return

    if claim.claim_type == ClaimType.TEXT and text_numbers:
        if not evidence_numbers:
            # 没有可复算数值：交给 citation/unsupported 处理，不虚增数值分母
            return
        report.numeric_checks_total += 1
        unmatched = [
            number
            for number in text_numbers
            if not any(numbers_match(number, ref, abs_tol, rel_tol) for ref in evidence_numbers)
        ]
        if unmatched:
            _add_issue(
                report,
                "numeric",
                f"文本主张 {claim.claim_id} 中数字 {unmatched} 与引用证据数值 {evidence_numbers[:6]} 不一致",
                role=role,
                claim_id=claim.claim_id,
                severity="error",
            )
        else:
            report.numeric_checks_passed += 1


def _check_key_metrics(
    report: VerificationReport,
    card: RiskCard,
    index: dict[str, Evidence],
    abs_tol: float,
    rel_tol: float,
) -> None:
    role = _role_str(card)
    for metric in card.key_metrics:
        if not isinstance(metric.value, (int, float)) or isinstance(metric.value, bool):
            continue
        if not metric.evidence_id:
            continue
        evidence = index.get(metric.evidence_id)
        if evidence is None:
            continue
        reference_numbers = _evidence_numbers(evidence)
        if not reference_numbers:
            continue
        report.numeric_checks_total += 1
        if any(numbers_match(metric.value, ref, abs_tol, rel_tol) for ref in reference_numbers):
            report.numeric_checks_passed += 1
        else:
            _add_issue(
                report,
                "numeric",
                f"关键指标 {metric.name}={metric.value} 与其证据 {metric.evidence_id} 的数值不一致",
                role=role,
                severity="error",
            )


def _check_recommendation(
    report: VerificationReport,
    card: RiskCard,
    index: dict[str, Evidence],
    abs_tol: float,
    rel_tol: float,
) -> None:
    """建议文本中的数字必须能在卡片绑定的证据集中找到依据。"""
    numbers = extract_numbers(card.recommendation)
    if not numbers:
        return
    allowed: list[float] = []
    for evidence_id in card.evidence_ids:
        evidence = index.get(evidence_id)
        if evidence is not None:
            allowed.extend(_evidence_numbers(evidence))
    for claim in card.claims:
        allowed.extend(_claim_reference_numbers(claim, index))
    if not allowed:
        return
    report.numeric_checks_total += 1
    unmatched = [
        number for number in numbers if not any(numbers_match(number, ref, abs_tol, rel_tol) for ref in allowed)
    ]
    if unmatched:
        _add_issue(
            report,
            "numeric",
            f"recommendation 中出现没有证据支撑的数字: {unmatched}",
            role=_role_str(card),
            severity="error",
        )
    else:
        report.numeric_checks_passed += 1


def _check_permission(
    report: VerificationReport,
    decision: DecisionCard,
    trace_events: list[TraceEvent] | None,
) -> None:
    events = trace_events
    if events is None:
        events = read_trace(decision.trace_ref) if decision.trace_ref else []
    seen: set[tuple[Any, ...]] = set()
    for event in events:
        if event.action in _EXCLUDED_FROM_PERMISSION:
            continue
        detail = event.detail or {}
        denied = False
        if event.action in _VIOLATION_ACTIONS:
            denied = True
        elif event.action in _TOOL_ACTIONS:
            if detail.get("allowed") is False or detail.get("violation") is True:
                denied = True
            elif str(detail.get("permission", "")).lower() in {"denied", "deny", "disallowed"}:
                denied = True
        if not denied:
            continue
        key = (
            event.step,
            event.role,
            event.tool,
            event.args_hash,
            detail.get("claim_id"),
            detail.get("reason"),
        )
        if key in seen:
            continue
        seen.add(key)
        report.permission_violations += 1
        tool_name = event.tool or detail.get("tool")
        _add_issue(
            report,
            "permission",
            f"越权工具调用被拦截：role={event.role} tool={tool_name} reason={detail.get('reason', '')}",
            role=event.role,
            claim_id=detail.get("claim_id"),
            severity="error",
        )


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def verify(
    decision: DecisionCard,
    evidence_index: Any = None,
    settings: Any = None,
    *,
    trace_events: list[TraceEvent] | None = None,
) -> VerificationReport:
    """对一次决策卡执行六类核验，返回已 ``finalize()`` 的 VerificationReport。

    Args:
        decision: 编排层产出的决策卡。
        evidence_index: 证据索引；支持 ``{evidence_id: Evidence}``、``list[Evidence]`` 或黑板对象。
        settings: AppSettings / OrchestrationSettings / dict（读取数值容差）。
        trace_events: 可选 trace 事件列表；缺省时从 ``decision.trace_ref`` 读回。
    """
    abs_tol, rel_tol = resolve_tolerances(settings)
    report = VerificationReport(run_id=decision.run_id)
    index = _normalize_evidence_index(evidence_index, report)

    # 1) schema
    _check_schema(report, decision)

    # 2) 时点泄漏
    _check_leakage(report, decision, index)

    # 3) 逐卡片：引文 / 数值 / 关键指标 / 建议文本
    for card in decision.cards.values():
        if not isinstance(card, RiskCard):
            continue
        for claim in card.claims:
            _check_claim_citation(report, card, claim, index, decision.as_of)
            _check_claim_numeric(report, card, claim, index, abs_tol, rel_tol)
        _check_key_metrics(report, card, index, abs_tol, rel_tol)
        _check_recommendation(report, card, index, abs_tol, rel_tol)

    # 4) 越权
    _check_permission(report, decision, trace_events)

    return report.finalize()


__all__ = ["verify", "resolve_tolerances"]
