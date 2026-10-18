"""证据黑板：共享证据、去重、主张登记与跨角色分歧检测（架构 3.5 的 R1/R3）。

设计要点：

- **证据是一等数据结构**：黑板只存 :class:`~cbr.schemas.Evidence`，按
  ``evidence.hash`` → ``tool.inputs_hash`` → 内容哈希 三级键去重；
- 去重后保留最早 ``evidence_id`` 为规范 id，后到的同内容证据登记为别名，
  这样各角色用自己的 evidence_id 引用同一份证据时仍能在核验/UI 中解析；
- **冲突检测规则**（写入代码、可被配置容差调节，论文 4.4）：

  ===========  ==========================================================
  fact         同 subject 的数值型主张超过绝对/相对容差
  directional  同 subject 的方向（up/down）相反
  preference   证据一致但判断口径/阈值不同（方向 up vs flat、类型不同），
               保留差异、不算错误
  ===========  ==========================================================

  卡级风险等级差异（不同主体阈值不同）**不判为冲突**，按偏好差异处理。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from ..schemas import (
    Claim,
    ClaimType,
    Conflict,
    ConflictType,
    Evidence,
    EvidenceKind,
    RiskCard,
    Role,
    RoleSpec,
)
from ..verification.numeric import (
    DEFAULT_ABS_TOL,
    DEFAULT_REL_TOL,
    flatten_numbers,
    numbers_match,
)


# --------------------------------------------------------------------------- #
# 证据键 / 等级 / 工具函数
# --------------------------------------------------------------------------- #
def _jsonable(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover
        return repr(obj)


def canonical_evidence_key(evidence: Evidence) -> str:
    """证据去重键：hash > tool.inputs_hash > 内容哈希。"""
    if evidence.hash:
        return f"hash:{evidence.hash}"
    if evidence.tool and evidence.tool.inputs_hash:
        return f"tool:{evidence.tool.name}@{evidence.tool.version}:{evidence.tool.inputs_hash}"
    payload = {
        "kind": evidence.kind.value if hasattr(evidence.kind, "value") else evidence.kind,
        "as_of": str(evidence.as_of),
        "title": evidence.title,
        "summary": evidence.summary,
        "value": evidence.value,
        "unit": evidence.unit,
        "payload": evidence.payload,
        "source": evidence.source.model_dump(mode="json"),
        "tool": evidence.tool.model_dump(mode="json") if evidence.tool else None,
    }
    return "content:" + hashlib.sha256(_jsonable(payload).encode("utf-8")).hexdigest()[:24]


def evidence_grade(evidence: Evidence | None) -> int:
    """证据可信/权威等级：工具重算 > 权威数据源/知识库 > 共享信号/行情 > 无证据。"""
    if evidence is None:
        return 0
    if evidence.kind == EvidenceKind.TOOL:
        return 3
    if evidence.kind in (EvidenceKind.KB, EvidenceKind.POLICY):
        return 2
    return 1


def normalize_subject(subject: str | None) -> str:
    """subject 归一化：去空格、小写，作为“同一口径”的分组键。"""
    return "_".join(str(subject or "").strip().lower().split())


def _units_comparable(unit_a: str | None, unit_b: str | None) -> bool:
    if not unit_a or not unit_b:
        return True
    return unit_a.strip().lower() == unit_b.strip().lower()


def _evidence_overlap(claim_a: Claim, claim_b: Claim) -> bool:
    return bool(set(claim_a.evidence_ids) & set(claim_b.evidence_ids))


def _role_value(claim: Claim) -> str:
    role = claim.role
    return role.value if hasattr(role, "value") else str(role)


def _role_threshold_difference(
    claim_a: Claim,
    claim_b: Claim,
    role_specs: Mapping[Any, RoleSpec] | None,
) -> str | None:
    """判断两角色在阈值/损失权重上是否存在差异（用于偏好差异的解释）。"""
    if not role_specs:
        return None

    def _lookup(role_name: str) -> RoleSpec | None:
        for key, spec in role_specs.items():
            key_value = key.value if hasattr(key, "value") else str(key)
            if key_value == role_name:
                return spec
        return None

    spec_a = _lookup(_role_value(claim_a))
    spec_b = _lookup(_role_value(claim_b))
    if spec_a is None or spec_b is None:
        return None
    if spec_a.thresholds != spec_b.thresholds:
        keys = sorted(set(spec_a.thresholds) | set(spec_b.thresholds))
        diff = [
            key
            for key in keys
            if spec_a.thresholds.get(key) != spec_b.thresholds.get(key)
        ]
        sample = ", ".join(diff[:3])
        return f"角色阈值不同（{sample}）"
    if spec_a.decision_loss_weights != spec_b.decision_loss_weights:
        return "角色决策损失权重不同"
    return None


def classify_claim_pair(
    claim_a: Claim,
    claim_b: Claim,
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
    role_specs: Mapping[Any, RoleSpec] | None = None,
) -> tuple[ConflictType, str, str] | None:
    """对同一 subject 的两条跨角色主张分类。

    Returns:
        ``(ConflictType, severity, description)``；无冲突/一致时返回 ``None``。
    """
    if claim_a.claim_id == claim_b.claim_id:
        return None
    if _role_value(claim_a) == _role_value(claim_b):
        return None

    a_is_numeric = claim_a.claim_type == ClaimType.NUMERIC and claim_a.value is not None
    b_is_numeric = claim_b.claim_type == ClaimType.NUMERIC and claim_b.value is not None
    units_ok = _units_comparable(claim_a.unit, claim_b.unit)

    # 1) 事实冲突：同口径数值差异超过容差
    if a_is_numeric and b_is_numeric and units_ok:
        if not numbers_match(claim_a.value, claim_b.value, abs_tol, rel_tol):
            scale = max(abs(float(claim_a.value)), abs(float(claim_b.value)), 1e-12)
            rel_diff = abs(float(claim_a.value) - float(claim_b.value)) / scale
            severity = "high" if rel_diff > 0.05 else "medium"
            subject = claim_a.subject
            return (
                ConflictType.FACT,
                severity,
                f"同一口径「{subject}」数值不一致："
                f"{_role_value(claim_a)}={claim_a.value}{claim_a.unit or ''} vs "
                f"{_role_value(claim_b)}={claim_b.value}{claim_b.unit or ''}（相对差异 {rel_diff:.1%}）",
            )

    # 2) 方向冲突：同 subject 方向相反
    directions = {d for d in (claim_a.direction, claim_b.direction) if d in ("up", "down")}
    if directions == {"up", "down"}:
        severity = "high" if _evidence_overlap(claim_a, claim_b) else "medium"
        return (
            ConflictType.DIRECTIONAL,
            severity,
            f"同一 subject「{claim_a.subject}」方向相反："
            f"{_role_value(claim_a)}={claim_a.direction} vs {_role_value(claim_b)}={claim_b.direction}",
        )

    # 3) 偏好差异：证据一致/数值一致，但判断口径或阈值权重不同
    overlap = _evidence_overlap(claim_a, claim_b)
    numeric_consistent = (
        numbers_match(claim_a.value, claim_b.value, abs_tol, rel_tol)
        if (a_is_numeric and b_is_numeric)
        else None
    )
    directions_differ = (
        claim_a.direction is not None
        and claim_b.direction is not None
        and "none" not in (claim_a.direction, claim_b.direction)
        and claim_a.direction != claim_b.direction
    )
    type_differs = claim_a.claim_type != claim_b.claim_type
    threshold_reason = _role_threshold_difference(claim_a, claim_b, role_specs)
    evidence_consistent = overlap or bool(numeric_consistent)
    if evidence_consistent and (directions_differ or type_differs or threshold_reason):
        reason = threshold_reason or ("判断口径不同（方向/类型不一致）" if directions_differ else "主张类型不同")
        return (
            ConflictType.PREFERENCE,
            "low",
            f"同一 subject「{claim_a.subject}」为偏好差异（{reason}）：证据一致但阈值/权重或判断口径不同，"
            f"保留差异、分主体呈现，不判为错误",
        )
    return None


# --------------------------------------------------------------------------- #
# 黑板
# --------------------------------------------------------------------------- #
class EvidenceBlackboard:
    """共享证据黑板。

    典型用法::

        board = EvidenceBlackboard(abs_tol=1e-6, rel_tol=1e-3)
        board.add(evidence, role=Role.REGULATOR)
        board.register_card(role, card)
        board.index()                     # {evidence_id: Evidence}（含别名）
        board.add_claims([...])           # 登记主张，供 R3 分歧识别
    """

    def __init__(
        self,
        abs_tol: float = DEFAULT_ABS_TOL,
        rel_tol: float = DEFAULT_REL_TOL,
        role_specs: Mapping[Any, RoleSpec] | None = None,
    ) -> None:
        self.abs_tol = float(abs_tol)
        self.rel_tol = float(rel_tol)
        self.role_specs = role_specs
        self.evidence_shared = 0   # 新入板（共享）证据数
        self.duplicate_evidence = 0  # 去重命中数
        self._canonical: dict[str, str] = {}          # dedup key -> canonical evidence_id
        self._evidence: dict[str, Evidence] = {}      # canonical evidence_id -> Evidence
        self._aliases: dict[str, str] = {}            # alias evidence_id -> canonical evidence_id
        self._origins: dict[str, set[str]] = {}       # canonical id -> 产出角色集合
        self._claims: list[Claim] = []
        self._claim_index: dict[str, Claim] = {}
        self._cards: dict[str, RiskCard] = {}

    # -- 证据 --------------------------------------------------------------
    def add(self, evidence: Evidence, *, role: Role | str | None = None, count_shared: bool = True) -> str:
        """加入一条证据，返回其规范 evidence_id。

        同内容证据只保留一份：``count_shared=False`` 时（single/independent 模式）
        仍然去重并建立别名，但不计入“共享证据/重复证据”统计。
        """
        if evidence is None:
            raise ValueError("evidence 不能为 None")
        key = canonical_evidence_key(evidence)
        evidence_id = evidence.evidence_id or key
        role_name = role.value if isinstance(role, Role) else (str(role) if role is not None else None)
        canonical_id = self._canonical.get(key)
        if canonical_id is not None:
            if count_shared:
                self.duplicate_evidence += 1
            if evidence_id and evidence_id != canonical_id:
                self._aliases[evidence_id] = canonical_id
            if role_name:
                self._origins.setdefault(canonical_id, set()).add(role_name)
            return canonical_id

        self._canonical[key] = canonical_id = evidence_id
        if evidence_id in self._evidence:
            # 同 evidence_id 但内容不同：保留先到版本，避免黑板内容被覆盖
            if count_shared:
                self.duplicate_evidence += 1
            if role_name:
                self._origins.setdefault(canonical_id, set()).add(role_name)
            return canonical_id
        self._evidence[canonical_id] = evidence
        if snapshot_id := evidence.evidence_id:
            if snapshot_id != canonical_id:  # 理论上不会发生
                self._aliases[snapshot_id] = canonical_id
        if role_name:
            self._origins.setdefault(canonical_id, set()).add(role_name)
        if count_shared:
            self.evidence_shared += 1
        return canonical_id

    def add_many(
        self,
        evidences: Iterable[Evidence],
        *,
        role: Role | str | None = None,
        count_shared: bool = True,
    ) -> list[str]:
        return [self.add(ev, role=role, count_shared=count_shared) for ev in evidences]

    def contains_equivalent(self, evidence: Evidence) -> bool:
        """黑板上是否已有同内容证据（用于审计“共享 vs 去重”事件）。"""
        return canonical_evidence_key(evidence) in self._canonical

    def resolve_id(self, evidence_id: str) -> str:
        """别名 id → 规范 id（找不到原样返回）。"""
        return self._aliases.get(evidence_id, evidence_id)

    def get(self, evidence_id: str) -> Evidence | None:
        if evidence_id in self._evidence:
            return self._evidence[evidence_id]
        canonical = self._aliases.get(evidence_id)
        return self._evidence.get(canonical) if canonical else None

    def all(self) -> list[Evidence]:
        return list(self._evidence.values())

    def by_kind(self, kind: EvidenceKind) -> list[Evidence]:
        return [ev for ev in self._evidence.values() if ev.kind == kind]

    def index(self) -> dict[str, Evidence]:
        """``{evidence_id: Evidence}``，同时包含规范 id 与别名，供核验/API 解析。"""
        index: dict[str, Evidence] = dict(self._evidence)
        for alias, canonical in self._aliases.items():
            evidence = self._evidence.get(canonical)
            if evidence is not None:
                index[alias] = evidence
        return index

    def origin_roles(self, evidence_id: str) -> set[str]:
        return set(self._origins.get(self.resolve_id(evidence_id), set()))

    # -- 卡片 / 主张 -------------------------------------------------------
    def register_card(self, role: Role | str, card: RiskCard) -> None:
        role_name = role.value if isinstance(role, Role) else str(role)
        self._cards[role_name] = card
        self.add_claims(card.claims, card=card)

    def add_claims(self, claims: Iterable[Claim], *, card: RiskCard | None = None) -> None:
        for claim in claims:
            if claim is None:
                continue
            existing = self._claim_index.get(claim.claim_id)
            if existing is not None and existing is not claim:
                # 同 id 不被覆盖：冲突检测/仲裁必须基于确定对象
                continue
            self._claims.append(claim)
            if claim.claim_id:
                self._claim_index[claim.claim_id] = claim

    @property
    def claims(self) -> list[Claim]:
        return list(self._claims)

    @property
    def claim_index(self) -> dict[str, Claim]:
        return dict(self._claim_index)

    @property
    def cards(self) -> dict[str, RiskCard]:
        return dict(self._cards)

    def claims_by_subject(self) -> dict[str, list[Claim]]:
        groups: dict[str, list[Claim]] = {}
        for claim in self._claims:
            subject = normalize_subject(claim.subject)
            if not subject:
                continue
            groups.setdefault(subject, []).append(claim)
        return groups

    # -- 统计 --------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        return {
            "evidence_total": len(self._evidence),
            "evidence_shared": self.evidence_shared,
            "duplicate_evidence": self.duplicate_evidence,
            "claims": len(self._claims),
            "cards": len(self._cards),
        }

    def clear(self) -> None:
        self.evidence_shared = 0
        self.duplicate_evidence = 0
        self._canonical.clear()
        self._evidence.clear()
        self._aliases.clear()
        self._origins.clear()
        self._claims.clear()
        self._claim_index.clear()
        self._cards.clear()

    def __len__(self) -> int:
        return len(self._evidence)


# --------------------------------------------------------------------------- #
# R3 分歧识别
# --------------------------------------------------------------------------- #
def detect_conflicts(
    claims: Iterable[Claim],
    *,
    cards: Mapping[str, RiskCard] | None = None,
    role_specs: Mapping[Any, RoleSpec] | None = None,
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
) -> list[Conflict]:
    """对跨角色主张做同 subject 比对，返回冲突列表（每个 subject 至多一个冲突）。"""
    groups: dict[str, list[Claim]] = {}
    for claim in claims:
        if claim is None:
            continue
        subject = normalize_subject(claim.subject)
        if not subject:
            continue
        groups.setdefault(subject, []).append(claim)

    conflicts: list[Conflict] = []
    for subject in sorted(groups):
        group = groups[subject]
        if len({_role_value(c) for c in group}) < 2:
            continue
        chosen: tuple[ConflictType, str, str] | None = None
        chosen_pair: tuple[Claim, Claim] | None = None
        # 断言评分：fact > directional > preference，按此优先级找第一个可分类的跨角色对
        candidates: list[tuple[int, tuple[ConflictType, str, str], tuple[Claim, Claim]]] = []
        for index_a, claim_a in enumerate(group):
            for claim_b in group[index_a + 1:]:
                if _role_value(claim_a) == _role_value(claim_b):
                    continue
                classified = classify_claim_pair(
                    claim_a, claim_b, abs_tol=abs_tol, rel_tol=rel_tol, role_specs=role_specs
                )
                if classified is None:
                    continue
                priority = {ConflictType.FACT: 0, ConflictType.DIRECTIONAL: 1, ConflictType.PREFERENCE: 2}
                candidates.append((priority[classified[0]], classified, (claim_a, claim_b)))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0])
        _, (conflict_type, severity, description), (claim_a, claim_b) = candidates[0]
        involved = [
            claim
            for claim in group
            if _role_value(claim) in {_role_value(claim_a), _role_value(claim_b)}
        ]
        evidence_ids: list[str] = []
        for claim in involved:
            for evidence_id in claim.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        conflicts.append(
            Conflict(
                conflict_id=f"cf_{len(conflicts) + 1:03d}",
                subject=subject,
                claim_ids=[claim.claim_id for claim in involved if claim.claim_id],
                roles=sorted({_role_value(claim) for claim in involved}),
                type=conflict_type,
                description=description,
                severity=severity,  # type: ignore[arg-type]
                resolved=False,
                resolution="",
                resolved_by=None,
                evidence_ids=evidence_ids,
            )
        )
    return conflicts


__all__ = [
    "EvidenceBlackboard",
    "canonical_evidence_key",
    "evidence_grade",
    "normalize_subject",
    "classify_claim_pair",
    "detect_conflicts",
]
