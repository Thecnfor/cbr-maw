"""冲突分类与仲裁规则（架构 3.5 的 R3/R4，论文 4.4）。

仲裁优先级（与架构文档一致）：

1. **工具重算**：同一 subject 有对应确定性工具时重算，以可复现证据为准；
2. **权威数据源 / 证据质量**：工具证据 > 知识库/政策原文 > 共享信号/行情 > 无证据；
3. **人工接管（HITL）**：补充证据后仍不一致 → 升级人工，保留冲突并在决策卡标记。

按冲突类型：

- ``fact``：数值不一致 → 工具重算/证据质量裁决，胜者 VERIFIED、败者 REJECTED；
- ``directional``：方向相反 → 追加工具证据（payload.direction）或证据质量裁决；
  仍无法判定则升级 HITL；
- ``preference``：证据一致、阈值/权重不同 → 保留差异（``ClaimStatus.PREFERENCE``），
  **不算错误**，分主体呈现。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..schemas import (
    Claim,
    ClaimStatus,
    Conflict,
    ConflictType,
    Evidence,
    EvidenceKind,
    Role,
    RoleSpec,
    ToolRef,
)
from ..verification.numeric import DEFAULT_ABS_TOL, DEFAULT_REL_TOL, flatten_numbers, numbers_match
from ..verification.trace import hash_obj
from .blackboard import EvidenceBlackboard, evidence_grade

#: subject 关键词 → 权威工具。顺序敏感：越具体的规则放前面。
SUBJECT_TOOL_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("northbound", "southbound", "capital_flow", "ah_premium", "资金", "北向", "南向", "跨境"), "capital_flow"),
    (("funding", "credit_spread", "refinanc", "利差", "融资", "信用"), "funding_cost"),
    (("spillover", "covar", "correlation", "systemic", "外溢", "传染", "相关性"), "systemic_risk"),
    (("var", "cvar", "drawdown", "volatility", "最大回撤", "波动", "回撤"), "risk_measure"),
    (("stress_prob", "probability", "prob_high", "预测概率", "高压力概率"), "forecast"),
    (("scenario", "情景", "冲击"), "scenario"),
    (("policy", "regulation", "政策", "监管", "资本管制"), "knowledge_search"),
    (("trend", "direction", "方向", "趋势"), "systemic_risk"),
)

#: 兜底工具（subject 无法映射时用于“重算同一口径”的最终尝试）
DEFAULT_TOOL = "risk_measure"


def _as_role(value: Any) -> Role | None:
    if isinstance(value, Role):
        return value
    try:
        return Role(str(value))
    except (ValueError, TypeError):
        return None


def tool_for_subject(subject: str | None, available: Iterable[str] | None = None) -> str | None:
    """按 subject 关键词选择权威工具；提供 ``available`` 时仅返回已注册工具。"""
    text = str(subject or "").lower()
    available_set = set(available) if available is not None else None
    for keys, tool_name in SUBJECT_TOOL_RULES:
        if not any(key in text for key in keys):
            continue
        if available_set is not None and tool_name not in available_set:
            continue
        return tool_name
    if available_set is not None and DEFAULT_TOOL in available_set:
        return DEFAULT_TOOL
    return None if available_set is not None else DEFAULT_TOOL


@dataclass
class ConflictResolution:
    """一轮仲裁的结果汇总。"""

    resolved: int = 0
    escalated: int = 0
    tool_calls: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    hitl_item_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    resolved_ids: list[str] = field(default_factory=list)
    escalated_ids: list[str] = field(default_factory=list)


class ConflictArbitrator:
    """R4 协调器：对 R3 检测到的冲突逐条仲裁。"""

    def __init__(
        self,
        *,
        board: EvidenceBlackboard,
        as_of: Any,
        run_id: str = "",
        registry: Any = None,
        hitl: Any = None,
        trace: Any = None,
        role_specs: Mapping[Any, RoleSpec] | None = None,
        display_names: Mapping[str, str] | None = None,
        budget: dict[str, dict[str, int]] | None = None,
        abs_tol: float = DEFAULT_ABS_TOL,
        rel_tol: float = DEFAULT_REL_TOL,
    ) -> None:
        self.board = board
        self.as_of = as_of
        self.run_id = run_id
        self.registry = registry
        self.hitl = hitl
        self.trace = trace
        self.role_specs = role_specs or {}
        self.display_names = display_names or {}
        self.budget = budget
        self.abs_tol = float(abs_tol)
        self.rel_tol = float(rel_tol)
        self.tool_calls = 0
        self._tried: set[tuple[str, str]] = set()

    # -- 主入口 ------------------------------------------------------------
    def resolve(
        self,
        conflicts: Iterable[Conflict],
        claims_index: Mapping[str, Claim],
        cards: Mapping[str, Any] | None = None,
        *,
        final_round: bool = True,
    ) -> ConflictResolution:
        """对未解决冲突做一轮仲裁；``final_round=False`` 时不升级 HITL（留待后续轮次）。"""
        outcome = ConflictResolution()
        tool_calls_before = self.tool_calls
        merged_index = dict(claims_index)
        if cards:
            for card in cards.values():
                for claim in getattr(card, "claims", []) or []:
                    merged_index.setdefault(claim.claim_id, claim)
        for conflict in conflicts:
            if conflict is None or conflict.resolved:
                continue
            involved = [merged_index[cid] for cid in conflict.claim_ids if cid in merged_index]
            if not involved:
                continue
            resolved = self._resolve_one(conflict, involved, outcome)
            if resolved:
                self._emit(
                    step="R4",
                    action="conflict_resolved",
                    detail={
                        "conflict_id": conflict.conflict_id,
                        "subject": conflict.subject,
                        "type": conflict.type.value,
                        "resolved_by": conflict.resolved_by,
                        "resolution": conflict.resolution,
                    },
                )
            elif final_round:
                self._escalate(conflict, involved, outcome)
        outcome.tool_calls = self.tool_calls - tool_calls_before
        return outcome

    # -- 单条冲突 ----------------------------------------------------------
    def _resolve_one(self, conflict: Conflict, claims: list[Claim], outcome: ConflictResolution) -> bool:
        if conflict.type == ConflictType.PREFERENCE:
            return self._resolve_preference(conflict, claims, outcome)
        if conflict.type == ConflictType.FACT:
            return self._resolve_fact(conflict, claims, outcome)
        if conflict.type == ConflictType.DIRECTIONAL:
            return self._resolve_directional(conflict, claims, outcome)
        return False

    def _resolve_preference(self, conflict: Conflict, claims: list[Claim], outcome: ConflictResolution) -> bool:
        for claim in claims:
            claim.status = ClaimStatus.PREFERENCE
        conflict.resolved = True
        conflict.severity = "low"
        conflict.resolved_by = "consensus"
        conflict.resolution = (
            "偏好差异：证据一致但阈值/权重或判断口径不同，保留差异并在决策卡中分主体呈现；"
            "按定义不判为错误，不计入核验错误率。"
        )
        outcome.resolved += 1
        outcome.resolved_ids.append(conflict.conflict_id)
        outcome.notes.append(f"{conflict.conflict_id} preference: 保留差异（{conflict.subject}）")
        return True

    def _resolve_fact(self, conflict: Conflict, claims: list[Claim], outcome: ConflictResolution) -> bool:
        authoritative = self._authoritative_claim(claims)
        if authoritative is not None:
            resolved_by = "tool" if self._is_recomputed_claim(authoritative) else "authority"
            reason = (
                "以工具重算证据为准（交叉验证产出的可复现数值）"
                if resolved_by == "tool"
                else "以权威证据质量为准（工具/知识库证据优先）"
            )
            self._apply_numeric_winner(conflict, claims, authoritative, reason=reason, resolved_by=resolved_by)
            outcome.resolved += 1
            outcome.resolved_ids.append(conflict.conflict_id)
            outcome.notes.append(
                f"{conflict.conflict_id} fact: {resolved_by} 裁决 → {conflict.resolution}"
            )
            return True

        evidence = self._recompute(conflict, claims)
        if evidence is not None:
            targets = [claim.value for claim in claims if claim.value is not None]
            scalar = self._evidence_scalar(evidence, targets)
            if scalar is not None:
                winner = min(
                    claims,
                    key=lambda claim: (
                        abs(float(claim.value) - scalar) if claim.value is not None else float("inf")
                    ),
                )
                self._apply_numeric_winner(
                    conflict,
                    claims,
                    winner,
                    recomputed=scalar,
                    evidence=evidence,
                    reason=f"权威工具重算值 {scalar:.6g}",
                    resolved_by="tool",
                )
                outcome.resolved += 1
                outcome.resolved_ids.append(conflict.conflict_id)
                outcome.evidence_ids.append(evidence.evidence_id)
                outcome.notes.append(
                    f"{conflict.conflict_id} fact: 工具重算 {scalar:.6g} → {conflict.resolution}"
                )
                return True

        # 证据质量裁决：一方有权威证据、另一方没有
        graded = [(evidence_grade(self._claim_evidence(claim)), claim) for claim in claims]
        graded = [item for item in graded if item[0] > 0]
        if graded:
            best = max(item[0] for item in graded)
            winners = [claim for grade, claim in graded if grade == best]
            if len(winners) == 1:
                self._apply_numeric_winner(
                    conflict,
                    claims,
                    winners[0],
                    reason=f"无法重算，按证据质量（grade={best}）裁决",
                    resolved_by="authority",
                )
                outcome.resolved += 1
                outcome.resolved_ids.append(conflict.conflict_id)
                return True
        return False

    def _resolve_directional(
        self, conflict: Conflict, claims: list[Claim], outcome: ConflictResolution
    ) -> bool:
        evidence = self._recompute(conflict, claims)
        direction = None
        if evidence is not None:
            payload = evidence.payload or {}
            raw = payload.get("direction") or payload.get("trend") or payload.get("signal_direction")
            if raw is not None:
                text = str(raw).strip().lower()
                if text in {"up", "down", "flat", "none"}:
                    direction = text
        if direction is not None:
            winners = [claim for claim in claims if claim.direction == direction]
            losers = [claim for claim in claims if claim.direction != direction]
            if winners:
                for claim in winners:
                    claim.status = ClaimStatus.VERIFIED
                for claim in losers:
                    claim.status = ClaimStatus.REJECTED
                conflict.resolved = True
                conflict.resolved_by = "tool"
                conflict.resolution = (
                    f"追加工具证据判定方向={direction}；采纳 "
                    f"{[c.claim_id for c in winners]}，驳回 {[c.claim_id for c in losers]}"
                )
                if evidence is not None and evidence.evidence_id not in conflict.evidence_ids:
                    conflict.evidence_ids.append(evidence.evidence_id)
                    outcome.evidence_ids.append(evidence.evidence_id)
                outcome.resolved += 1
                outcome.resolved_ids.append(conflict.conflict_id)
                outcome.notes.append(f"{conflict.conflict_id} directional: 工具证据判定 {direction}")
                return True

        # 证据质量：优先采纳有工具证据的一方
        authoritative = self._authoritative_claim(claims)
        if authoritative is not None and authoritative.direction in {"up", "down", "flat"}:
            losers = [claim for claim in claims if claim.direction != authoritative.direction]
            authoritative.status = ClaimStatus.VERIFIED
            for claim in losers:
                claim.status = ClaimStatus.REJECTED
            conflict.resolved = True
            conflict.resolved_by = "authority"
            conflict.resolution = (
                f"补充证据仍无法重算方向，按证据质量采纳 {authoritative.claim_id} 的方向 "
                f"{authoritative.direction}"
            )
            outcome.resolved += 1
            outcome.resolved_ids.append(conflict.conflict_id)
            return True
        return False

    # -- 裁决应用 ----------------------------------------------------------
    def _apply_numeric_winner(
        self,
        conflict: Conflict,
        claims: list[Claim],
        winner: Claim,
        *,
        reason: str,
        resolved_by: str,
        recomputed: float | None = None,
        evidence: Evidence | None = None,
    ) -> None:
        target = recomputed if recomputed is not None else winner.value
        winners: list[str] = []
        rejected: list[str] = []
        for claim in claims:
            if claim is winner:
                claim.status = ClaimStatus.VERIFIED
                winners.append(claim.claim_id)
                continue
            if (
                target is not None
                and claim.value is not None
                and numbers_match(claim.value, target, self.abs_tol, self.rel_tol)
            ):
                claim.status = ClaimStatus.VERIFIED
                winners.append(claim.claim_id)
            elif claim.status != ClaimStatus.PREFERENCE:
                claim.status = ClaimStatus.REJECTED
                rejected.append(claim.claim_id)
        conflict.resolved = True
        conflict.resolved_by = resolved_by  # type: ignore[assignment]
        target_text = f"{target:.6g}" if isinstance(target, (int, float)) else str(target)
        conflict.resolution = (
            f"{reason}：采纳 claim={winner.claim_id}（{conflict.subject}={target_text}），"
            f"一致主张 {winners}，驳回 {rejected or '—'}"
        )
        if evidence is not None and evidence.evidence_id not in conflict.evidence_ids:
            conflict.evidence_ids.append(evidence.evidence_id)

    def _escalate(self, conflict: Conflict, claims: list[Claim], outcome: ConflictResolution) -> None:
        conflict.resolved = False
        conflict.resolved_by = "unresolved"
        conflict.severity = "high" if conflict.severity in {"medium", "low"} else conflict.severity
        conflict.resolution = "补充证据后仍无法达成一致，升级人工（HITL）复核；该冲突不覆盖确定性数值。"
        for claim in claims:
            if claim.status not in (ClaimStatus.PREFERENCE, ClaimStatus.REJECTED):
                claim.status = ClaimStatus.CONFLICTED
        item = None
        if self.hitl is not None:
            try:
                item = self.hitl.enqueue(
                    kind="unresolved_conflict",
                    summary=f"未解决冲突 {conflict.conflict_id}：{conflict.description}",
                    run_id=self.run_id,
                    payload={
                        "conflict_id": conflict.conflict_id,
                        "subject": conflict.subject,
                        "type": conflict.type.value,
                        "claim_ids": conflict.claim_ids,
                        "roles": conflict.roles,
                    },
                )
            except Exception:  # pragma: no cover - HITL 不应拖垮主流程
                item = None
        if item is not None:
            outcome.hitl_item_ids.append(item.item_id)
        outcome.escalated += 1
        outcome.escalated_ids.append(conflict.conflict_id)
        outcome.notes.append(f"{conflict.conflict_id} unresolved: 升级 HITL")
        self._emit(
            step="R4",
            action="hitl_escalate",
            detail={
                "conflict_id": conflict.conflict_id,
                "subject": conflict.subject,
                "type": conflict.type.value,
                "hitl_item_id": getattr(item, "item_id", None),
            },
        )

    # -- 证据 / 工具 -------------------------------------------------------
    def _recompute(self, conflict: Conflict, claims: list[Claim]) -> Evidence | None:
        if self.registry is None:
            return None
        try:
            available = self.registry.names()
        except Exception:  # pragma: no cover
            available = None
        tool_name = tool_for_subject(conflict.subject, available)
        if tool_name is None:
            return None
        key = (conflict.subject, tool_name)
        if key in self._tried:
            return None
        self._tried.add(key)
        role = self._pick_allowed_role(tool_name, claims, require_budget=True)
        if role is None:
            self._emit(
                step="R4",
                action="tool_recompute_skipped",
                tool=tool_name,
                detail={"subject": conflict.subject, "reason": "permission_matrix_denied_or_budget_exhausted"},
            )
            return None
        try:
            tool = self.registry.get(tool_name)
            started = time.perf_counter()
            result = tool.run(self.as_of)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        except Exception as exc:  # 工具失败不得拖垮协同流程
            self._emit(
                step="R4",
                action="tool_call",
                role=role.value,
                tool=tool_name,
                detail={"purpose": "authoritative_recompute", "ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )
            return None
        self.tool_calls += 1
        if getattr(result, "ok", False) is not True:
            self._emit(
                step="R4",
                action="tool_call",
                role=role.value,
                tool=tool_name,
                detail={
                    "purpose": "authoritative_recompute",
                    "ok": False,
                    "error": getattr(result, "error", "tool failed"),
                },
                latency_ms=elapsed_ms,
            )
            return None
        evidence = getattr(result, "evidence", None)
        if evidence is None:
            data = dict(getattr(result, "data", {}) or {})
            evidence = Evidence(
                evidence_id=f"ev_recompute_{tool_name}_{getattr(self.as_of, 'isoformat', lambda: str(self.as_of))()}",
                kind=EvidenceKind.TOOL,
                as_of=self.as_of,
                title=f"{tool_name}（协调器权威重算）",
                summary=str(data)[:200],
                payload=data,
                value=data.get("value"),
                unit=getattr(result, "unit", None),
                tool=ToolRef(
                    name=tool_name,
                    version=str(getattr(tool, "version", "unknown")),
                    inputs_hash=hash_obj({"as_of": str(self.as_of), "tool": tool_name}),
                    elapsed_ms=elapsed_ms,
                ),
                produced_by=role.value,
            )
        evidence_id = self.board.add(evidence, role=role, count_shared=True)
        if self.budget is not None:
            bucket = self.budget.setdefault(role.value, {"tool_calls": 0, "tokens": 0})
            bucket["tool_calls"] = max(int(bucket.get("tool_calls", 0)) - 1, 0)
        self._emit(
            step="R4",
            action="tool_call",
            role=role.value,
            tool=tool_name,
            args_hash=hash_obj({"as_of": str(self.as_of), "tool": tool_name}),
            result_hash=hash_obj(evidence.model_dump(mode="json")),
            detail={
                "purpose": "authoritative_recompute",
                "ok": True,
                "subject": conflict.subject,
                "evidence_id": evidence_id,
                "value": evidence.value,
            },
            latency_ms=elapsed_ms,
        )
        return evidence

    def _pick_allowed_role(
        self, tool_name: str, claims: list[Claim], *, require_budget: bool = False
    ) -> Role | None:
        ordered: list[Role] = []
        for claim in claims:
            role = _as_role(claim.role)
            if role is not None and role not in ordered:
                ordered.append(role)
        for role in (Role.REGULATOR, Role.INVESTOR, Role.FINANCING):
            if role not in ordered:
                ordered.append(role)

        def _has_budget(role: Role) -> bool:
            if not require_budget or self.budget is None:
                return True
            bucket = self.budget.get(role.value)
            return bool(bucket) and int(bucket.get("tool_calls", 0)) > 0

        allow = getattr(self.registry, "allow", None)
        if callable(allow):
            for role in ordered:
                if not _has_budget(role):
                    continue
                try:
                    if allow(role, tool_name):
                        return role
                except Exception:  # pragma: no cover - 权限矩阵异常按拒绝处理
                    continue
            return None
        try:
            self.registry.get(tool_name)
        except Exception:  # pragma: no cover
            return None
        for role in ordered:
            if _has_budget(role):
                return role
        return None

    def _evidence_scalar(self, evidence: Evidence, targets: list[Any]) -> float | None:
        candidates: list[float] = []
        if evidence.value is not None:
            try:
                candidates.append(float(evidence.value))
            except (TypeError, ValueError):  # pragma: no cover
                pass
        for number in flatten_numbers(evidence.payload):
            if number not in candidates:
                candidates.append(number)
        if not candidates:
            return None
        numeric_targets = []
        for target in targets:
            try:
                numeric_targets.append(float(target))
            except (TypeError, ValueError):
                continue
        if numeric_targets:
            return min(
                candidates,
                key=lambda cand: min(abs(cand - target) for target in numeric_targets),
            )
        return candidates[0]

    def _claim_evidence(self, claim: Claim) -> Evidence | None:
        grades = [(evidence_grade(self.board.get(eid)), self.board.get(eid)) for eid in claim.evidence_ids]
        grades = [item for item in grades if item[1] is not None]
        if not grades:
            return None
        return max(grades, key=lambda item: item[0])[1]

    def _authoritative_claim(self, claims: list[Claim]) -> Claim | None:
        scored: list[tuple[tuple[int, float], Claim]] = []
        for claim in claims:
            evidence = self._claim_evidence(claim)
            recheck_bonus = 10 if str(claim.claim_id).startswith("recheck_") else 0
            score = (recheck_bonus + evidence_grade(evidence), float(claim.confidence or 0.0))
            scored.append((score, claim))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1:
            return scored[0][1] if scored[0][0][0] > 0 else None
        if scored[0][0] > scored[1][0]:
            return scored[0][1]
        return None

    @staticmethod
    def _is_recomputed_claim(claim: Claim) -> bool:
        return str(claim.claim_id).startswith("recheck_")

    # -- trace -------------------------------------------------------------
    def _emit(self, **kwargs: Any) -> None:
        if self.trace is None:
            return
        try:
            self.trace.emit(**kwargs)
        except Exception:  # pragma: no cover - 审计失败不影响主流程
            pass


__all__ = ["ConflictArbitrator", "ConflictResolution", "tool_for_subject", "SUBJECT_TOOL_RULES"]
