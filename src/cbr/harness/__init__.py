"""执行 harness 层：把「任务」交给可替换的执行器（进程内 / 远程）。

默认进程内实现；外部执行器（OpenHands 二开、Python+TS 二开）通过 ``RemoteHarness``
接入，配置见 ``configs/harness.yaml``。设计说明见
``docs/architecture/adr-2026-10-27-agent-harness.md``。

.. code-block:: python

    from cbr.harness import build_harness, TaskSpec

    harness = build_harness()                 # 进程内；后端指向远程时自动切换
    result = harness.run(TaskSpec(task_id="t1", kind="decision", payload={...}))
"""

from __future__ import annotations

from typing import Any

from .contracts import AgentHarness, RunResult, TaskSpec
from .local import InProcessHarness
from .remote import RemoteHarness

__all__ = [
    "AgentHarness",
    "InProcessHarness",
    "RemoteHarness",
    "RunResult",
    "TaskSpec",
    "build_harness",
    "load_harness_settings",
]


def load_harness_settings(path: str = "configs/harness.yaml") -> dict[str, Any]:
    """读取 harness 配置（文件缺失时返回默认进程内配置）。"""
    from cbr.config import load_yaml

    raw = load_yaml(path, default={}) or {}
    return dict(raw.get("harness") or {})


def build_harness(
    settings: dict[str, Any] | None = None,
    handlers: dict[str, Any] | None = None,
) -> AgentHarness:
    """按配置构造 harness；``backend=remote`` 时返回 :class:`RemoteHarness`。

    Args:
        settings: harness 配置（默认读 ``configs/harness.yaml``）。
        handlers: 进程内 harness 的任务处理器 ``{kind: handler}``。

    Returns:
        ``AgentHarness`` 实例。
    """
    settings = settings if settings is not None else load_harness_settings()
    backend = str(settings.get("backend", "in-process"))
    if backend == "remote":
        return RemoteHarness(
            str(settings.get("base_url", "http://127.0.0.1:3000")),
            submit_path=str(settings.get("submit_path", "/v1/tasks")),
            timeout_seconds=float(settings.get("timeout_seconds", 60)),
            api_key=settings.get("api_key"),
        )
    return InProcessHarness(handlers=handlers)
