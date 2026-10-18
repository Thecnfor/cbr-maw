"""CBR-MAW 共享领域模型（跨模块唯一契约）。

所有模块（数据层、信号模型、工具、智能体、协同编排、核验、API、UI、实验）
只通过本文件中的数据结构交互。修改需由 Lead 统一进行并通知全员。

设计约束（对应论文 4.1–4.4 与 P1–P3）：
- 数值证据：Evidence / ToolResult 携带工具名、版本、输入哈希，可重算；
- 文本证据：Evidence 携带来源、发布时间（release_time），强制 <= as_of；
- 智能体结论：RiskCard 中每条 Claim 必须绑定 evidence_ids；
- 协同：Conflict 区分事实冲突 / 方向冲突 / 偏好差异；
- 核验：VerificationReport 汇总数值、引文、时点、越权、schema、无依据断言六类问题。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #
class Role(str, Enum):
    REGULATOR = "regulator"    # 监管主体
    INVESTOR = "investor"      # 投资主体
    FINANCING = "financing"    # 融资主体
    COORDINATOR = "coordinator"
    VERIFIER = "verifier"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceKind(str, Enum):
    SIGNAL = "signal"      # 共享多模态风险信号
    TOOL = "tool"          # 确定性工具输出
    KB = "kb"              # 知识库片段（政策/方法学/事件）
    MARKET = "market"      # 行情/资金快照
    POLICY = "policy"      # 政策文本原文


class ClaimType(str, Enum):
    NUMERIC = "numeric"        # 数值型主张（必须绑定工具证据）
    TEXT = "text"              # 文本型主张（必须绑定知识库证据）
    DIRECTIONAL = "directional"  # 方向/等级型主张（基于数值证据的定性判断）


class ClaimStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"
    PREFERENCE = "preference"   # 主体偏好差异，保留但不算错误


class ConflictType(str, Enum):
    FACT = "fact"                # 事实冲突：同口径数值不一致
    DIRECTIONAL = "directional"  # 方向冲突：风险等级/方向相反
    PREFERENCE = "preference"    # 偏好差异：证据一致但阈值/权重不同


class ExperimentMode(str, Enum):
    SINGLE = "single"                # 单智能体（通用 agent 完成三主体任务）
    INDEPENDENT = "independent"      # 三个独立智能体（无共享、无协调）
    COLLABORATIVE = "collaborative"  # 完整协同系统


# --------------------------------------------------------------------------- #
# 数据与时点层
# --------------------------------------------------------------------------- #
class DataCard(BaseModel):
    """数据卡：记录序列口径、覆盖期与时点可得性评级。"""

    series_id: str
    name: str
    source: str
    frequency: Literal["daily", "weekly", "monthly", "event", "text"] = "daily"
    coverage_start: date | None = None
    coverage_end: date | None = None
    release_lag_days: int = 0
    pit_grade: Literal["strict", "approximate", "unavailable"] = "strict"
    unit: str | None = None
    notes: str = ""


class MarketSnapshot(BaseModel):
    as_of: date
    series: dict[str, float] = Field(default_factory=dict)  # series_id -> value
    missing: list[str] = Field(default_factory=list)
    data_cards: list[DataCard] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 共享风险信号（多模态融合输出，P1）
# --------------------------------------------------------------------------- #
class RiskDriver(BaseModel):
    factor: str
    contribution: float
    direction: Literal["up", "down"] = "up"
    description: str = ""


class RiskSignal(BaseModel):
    as_of: date
    model_version: str
    horizons: dict[int, float] = Field(default_factory=dict)  # {5: 0.12, 10: 0.28, 20: 0.41}
    percentile: float | None = None
    level: RiskLevel = RiskLevel.LOW
    drivers: list[RiskDriver] = Field(default_factory=list)
    modality_contrib: dict[str, float] = Field(default_factory=dict)
    label_version: str = "stress_pca_q90"
    evidence_id: str | None = None


# --------------------------------------------------------------------------- #
# 证据（协同黑板的原子单位）
# --------------------------------------------------------------------------- #
class SourceRef(BaseModel):
    name: str
    url: str | None = None
    doc_id: str | None = None
    chunk_id: str | None = None
    release_time: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolRef(BaseModel):
    name: str
    version: str
    inputs_hash: str | None = None
    elapsed_ms: int = 0


class Evidence(BaseModel):
    evidence_id: str
    kind: EvidenceKind
    as_of: date
    title: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    value: float | None = None
    source: SourceRef = Field(default_factory=lambda: SourceRef(name="unknown"))
    tool: ToolRef | None = None
    produced_by: str = "system"
    citations: list[SourceRef] = Field(default_factory=list)
    verified: bool | None = None
    created_at: datetime = Field(default_factory=utcnow)
    hash: str | None = None


# --------------------------------------------------------------------------- #
# 智能体输出（P2/P3）
# --------------------------------------------------------------------------- #
class Claim(BaseModel):
    claim_id: str
    role: str
    claim_type: ClaimType = ClaimType.TEXT
    subject: str
    text: str
    value: float | None = None
    unit: str | None = None
    direction: Literal["up", "down", "flat", "none"] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    status: ClaimStatus = ClaimStatus.UNVERIFIED


class MetricItem(BaseModel):
    name: str
    label: str = ""
    value: float | str | None = None
    unit: str | None = None
    evidence_id: str | None = None
    description: str = ""


class RiskCard(BaseModel):
    role: Role
    as_of: date
    risk_level: RiskLevel
    headline: str
    base_signal_ref: str | None = None
    key_metrics: list[MetricItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    recommendation: str = ""
    decision_loss: dict[str, float] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    round: int = 0


class RoleSpec(BaseModel):
    role: Role
    display_name: str
    objective: str
    focus: list[str] = Field(default_factory=list)
    info_permissions: list[str] = Field(default_factory=list)   # 数据域/序列权限
    tool_permissions: list[str] = Field(default_factory=list)   # 工具白名单
    thresholds: dict[str, float] = Field(default_factory=dict)  # 预警阈值
    decision_loss_weights: dict[str, float] = Field(default_factory=dict)
    forbidden_actions: list[str] = Field(default_factory=list)
    output_style: str = ""


# --------------------------------------------------------------------------- #
# 确定性工具
# --------------------------------------------------------------------------- #
class ToolResult(BaseModel):
    tool_name: str
    version: str
    as_of: date
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    evidence: Evidence | None = None
    citations: list[SourceRef] = Field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# 智能体运行上下文（agents-core 与 orchestration-core 之间的接口）
# --------------------------------------------------------------------------- #
class TraceEvent(BaseModel):
    """审计轨迹单条事件（写入 artifacts/traces/<run_id>.jsonl）。"""

    run_id: str
    ts: datetime = Field(default_factory=utcnow)
    step: str = ""                      # R0 / R1 / R2 / ...
    role: str | None = None
    action: str = ""                    # signal / tool_call / llm_call / claim / conflict / verify / hitl / finalize
    tool: str | None = None
    args_hash: str | None = None
    result_hash: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    tokens: int = 0


class AgentContext(BaseModel):
    """编排层交给单个智能体的一次分析任务。"""

    as_of: date
    mode: ExperimentMode = ExperimentMode.COLLABORATIVE
    signal: RiskSignal
    snapshot: MarketSnapshot
    round: int = 0
    peer_evidence: list[Evidence] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    task: str = ""


class AgentOutput(BaseModel):
    """单个智能体一次分析的完整产物（RiskCard + 新证据 + 用量）。"""

    role: Role
    card: RiskCard
    evidence: list[Evidence] = Field(default_factory=list)
    tool_calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    trace: list[TraceEvent] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 协同、核验、最终决策
# --------------------------------------------------------------------------- #
class Conflict(BaseModel):
    conflict_id: str
    subject: str
    claim_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    type: ConflictType
    description: str
    severity: Literal["low", "medium", "high"] = "medium"
    resolved: bool = False
    resolution: str = ""
    resolved_by: Literal["tool", "authority", "human", "consensus", "unresolved"] | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationIssue(BaseModel):
    issue_type: Literal[
        "numeric", "citation", "leakage", "permission", "schema", "unsupported"
    ]
    role: str | None = None
    claim_id: str | None = None
    detail: str
    severity: Literal["info", "warning", "error"] = "warning"


class VerificationReport(BaseModel):
    run_id: str = ""
    numeric_checks_total: int = 0
    numeric_checks_passed: int = 0
    numeric_error_rate: float = 0.0
    citation_checks_total: int = 0
    citation_checks_passed: int = 0
    evidence_accuracy: float = 0.0
    unsupported_claims: int = 0
    unsupported_claim_rate: float = 0.0
    permission_violations: int = 0
    leakage_events: int = 0
    schema_errors: int = 0
    issues: list[VerificationIssue] = Field(default_factory=list)
    passed: bool = True

    def finalize(self) -> "VerificationReport":
        """由计数派生比率，供 UI/实验直接使用。"""
        self.numeric_error_rate = (
            1.0 - self.numeric_checks_passed / self.numeric_checks_total
            if self.numeric_checks_total
            else 0.0
        )
        self.evidence_accuracy = (
            self.citation_checks_passed / self.citation_checks_total
            if self.citation_checks_total
            else 1.0
        )
        total_claims = self.citation_checks_total + self.unsupported_claims
        self.unsupported_claim_rate = (
            self.unsupported_claims / total_claims if total_claims else 0.0
        )
        self.passed = (
            self.numeric_error_rate == 0.0
            and self.permission_violations == 0
            and self.leakage_events == 0
            and self.schema_errors == 0
        )
        return self


class CoordinationStats(BaseModel):
    rounds: int = 0
    evidence_shared: int = 0
    duplicate_evidence: int = 0
    conflicts_total: int = 0
    conflicts_resolved: int = 0
    conflicts_escalated: int = 0
    tool_calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0


class DecisionCard(BaseModel):
    run_id: str
    as_of: date
    scenario: str | None = None
    mode: ExperimentMode = ExperimentMode.COLLABORATIVE
    signal: RiskSignal
    cards: dict[str, RiskCard] = Field(default_factory=dict)  # role -> card
    conflicts: list[Conflict] = Field(default_factory=list)
    verification: VerificationReport = Field(default_factory=VerificationReport)
    coordination: CoordinationStats = Field(default_factory=CoordinationStats)
    final_advice: str = ""
    trace_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# 对话入口 / API
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[SourceRef] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    as_of: date | None = None
    session_id: str | None = None
    mode: Literal["auto", "collaborative", "independent", "single"] = "auto"


class ChatResponse(BaseModel):
    reply: str
    as_of: date | None = None
    decision: DecisionCard | None = None
    citations: list[SourceRef] = Field(default_factory=list)
    trace_id: str | None = None


# --------------------------------------------------------------------------- #
# 场景与实验
# --------------------------------------------------------------------------- #
class Scenario(BaseModel):
    scenario_id: str
    name: str
    as_of: date
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class ExperimentConfig(BaseModel):
    run_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    modality: dict[str, bool] = Field(default_factory=lambda: {"numeric": True, "text": True})
    augment: dict[str, bool] = Field(default_factory=lambda: {"rag": True, "tools": True})
    agents: dict[str, Any] = Field(default_factory=dict)
    coordination: dict[str, bool] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    eval: dict[str, Any] = Field(default_factory=dict)


class MetricResult(BaseModel):
    name: str
    value: float
    unit: str | None = None
    n: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None


class ExperimentRun(BaseModel):
    run_id: str
    config: ExperimentConfig
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    artifacts_dir: str | None = None
    notes: str = ""
