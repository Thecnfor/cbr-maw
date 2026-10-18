"""LLM 结构化输出的 Pydantic schema（智能体层与 mock 层共享）。

这些 schema 是"模型输出契约"，不是系统领域契约（领域契约见 ``cbr.schemas``）：

- ``RoleAnalysisDraft``：一次角色分析中 LLM 应当给出的文本结论骨架。数值字段
  只是"从证据包中抄录的候选值"，最终由 RoleAgent 与确定性工具证据逐项核对、
  回填后才进入 ``RiskCard``（LLM 不产数）。
- ``CrossCheckDraft``：交叉验证轮中，对 peer 证据/数值主张的复核结论。

把它们放在 llm 层可以让 MockLLM 与真实模型共用同一个 schema，
从而保证 mock / DeepSeek 两种模式走**完全相同**的代码路径（P3 可比性）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ClaimTypeLiteral = Literal["numeric", "text", "directional"]
DirectionLiteral = Literal["up", "down", "flat", "none"]
RiskLevelLiteral = Literal["low", "medium", "high", "critical"]
VerdictLiteral = Literal["confirmed", "refuted", "uncertain"]


class DraftClaim(BaseModel):
    """LLM 给出的单条主张草稿（尚未经过证据自检）。"""

    claim_type: ClaimTypeLiteral = "text"
    subject: str = ""
    text: str = ""
    value: float | None = None
    unit: str | None = None
    direction: DirectionLiteral | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class RoleAnalysisDraft(BaseModel):
    """一次角色分析的结构化草稿。"""

    headline: str = ""
    risk_level_assessment: RiskLevelLiteral | None = None  # 仅作参考，最终等级由角色阈值确定
    claims: list[DraftClaim] = Field(default_factory=list)
    recommendation: str = ""
    limitations: list[str] = Field(default_factory=list)
    decision_loss_comment: str = ""


class CrossCheckFinding(BaseModel):
    """对单条 peer 证据/数值主张的复核结果。"""

    evidence_id: str
    verdict: VerdictLiteral = "uncertain"
    note: str = ""
    recomputed_value: float | None = None


class CrossCheckDraft(BaseModel):
    """交叉验证轮的完整复核输出。"""

    findings: list[CrossCheckFinding] = Field(default_factory=list)
    summary: str = ""
