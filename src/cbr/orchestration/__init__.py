"""L5 协同编排层（架构 3.5 / 论文 4.4）。

对外稳定入口：

- :func:`build_orchestrator`：``build_orchestrator(settings, provider, registry, kb, llm)``
  装配 :class:`OrchestratorImpl`（实现 ``cbr.contracts.Orchestrator`` 协议）；
- :class:`EvidenceBlackboard` / :func:`detect_conflicts`：证据黑板与 R3 分歧识别；
- :class:`ConflictArbitrator`：R4 冲突仲裁（工具重算 > 权威数据源 > 证据质量）；
- :class:`HITLQueue`：人工接管队列（approve/reject/override，动作写审计 trace）。
"""

from .blackboard import (
    EvidenceBlackboard,
    canonical_evidence_key,
    classify_claim_pair,
    detect_conflicts,
    evidence_grade,
    normalize_subject,
)
from .conflict import ConflictArbitrator, ConflictResolution, tool_for_subject
from .hitl import DEFAULT_AUTO_POLICIES, HITLItem, HITLQueue
from .orchestrator import (
    DEFAULT_ROLES,
    MODE_FLAGS,
    ModeFlags,
    OrchestratorImpl,
    RoleAgentLike,
    build_orchestrator,
    build_role_agent_from_module,
    build_role_agents_from_module,
    build_single_agent_from_module,
)

__all__ = [
    "build_orchestrator",
    "OrchestratorImpl",
    "RoleAgentLike",
    "ModeFlags",
    "MODE_FLAGS",
    "DEFAULT_ROLES",
    "build_role_agent_from_module",
    "build_role_agents_from_module",
    "build_single_agent_from_module",
    "EvidenceBlackboard",
    "detect_conflicts",
    "classify_claim_pair",
    "canonical_evidence_key",
    "evidence_grade",
    "normalize_subject",
    "ConflictArbitrator",
    "ConflictResolution",
    "tool_for_subject",
    "HITLQueue",
    "HITLItem",
    "DEFAULT_AUTO_POLICIES",
]
