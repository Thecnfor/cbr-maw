"""进程内 harness：直接调用注入的处理器（默认实现，零外部依赖）。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .contracts import RunResult, TaskSpec

logger = logging.getLogger(__name__)


class InProcessHarness:
    """在同一进程内执行任务：按 ``task.kind`` 分派到注册的处理器。

    Args:
        handlers: ``{kind: handler}``；handler 接收 ``TaskSpec`` 并返回任意可序列化输出。
        name: harness 名称（写入 ``RunResult.runtime``）。
    """

    def __init__(self, handlers: Mapping[str, Callable[[TaskSpec], Any]] | None = None, name: str = "in-process") -> None:
        self._handlers: dict[str, Callable[[TaskSpec], Any]] = dict(handlers or {})
        self._name = name

    def register(self, kind: str, handler: Callable[[TaskSpec], Any]) -> None:
        """注册/覆盖某类任务的处理器。"""
        self._handlers[kind] = handler

    def info(self) -> dict[str, Any]:
        """返回 harness 信息。"""
        return {
            "name": self._name,
            "runtime": "in-process",
            "available": True,
            "kinds": sorted(self._handlers),
        }

    def run(self, task: TaskSpec) -> RunResult:
        """执行任务；未注册的 kind 或处理器异常都转为失败结果，不抛出。"""
        started = datetime.now(timezone.utc)
        t0 = time.time()
        handler = self._handlers.get(task.kind)
        if handler is None:
            return RunResult(
                task_id=task.task_id,
                ok=False,
                error=f"未注册的任务类型: {task.kind}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                runtime=self._name,
            )
        try:
            output = handler(task)
            return RunResult(
                task_id=task.task_id,
                ok=True,
                output=output,
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                runtime=self._name,
                metadata={"elapsed_ms": int((time.time() - t0) * 1000)},
            )
        except Exception as exc:  # noqa: BLE001 - harness 边界统一转结果
            logger.warning("harness 执行任务 %s 失败: %s", task.task_id, exc)
            return RunResult(
                task_id=task.task_id,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                runtime=self._name,
            )
