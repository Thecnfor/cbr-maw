"""执行 harness 的稳定契约（与具体实现解耦）。

``harness`` 负责「怎么把一个任务交给智能体执行并拿回结果」，与「智能体怎么思考」
（orchestration）解耦。默认实现是进程内的 :class:`cbr.harness.local.InProcessHarness`，
未来可替换为 OpenHands 二开或 Python+TS 二开的外部执行器（见
``docs/architecture/adr-2026-10-27-agent-harness.md``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class TaskSpec:
    """一个可被 harness 执行的任务。

    Attributes:
        task_id: 任务 ID（幂等/审计用）。
        kind: 任务类型（如 ``decision`` / ``crawl`` / ``custom``）。
        payload: 任务负载（harness 实现自行解释）。
        timeout_seconds: 超时（``None`` 表示实现默认）。
        metadata: 附加元数据（写回结果，便于追踪）。
    """

    task_id: str
    kind: str = "custom"
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """harness 执行结果。"""

    task_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    runtime: str = "in-process"
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentHarness(Protocol):
    """执行 harness 协议：任何实现都必须提供 ``info`` 与 ``run``。"""

    def info(self) -> dict[str, Any]:
        """返回 harness 名称 / 版本 / 可用性（供健康检查与 UI 展示）。"""
        ...

    def run(self, task: TaskSpec) -> RunResult:
        """执行任务并返回结果（实现必须自行捕获异常并转成 ``RunResult``）。"""
        ...
