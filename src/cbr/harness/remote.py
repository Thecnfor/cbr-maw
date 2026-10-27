"""远程 harness：对接外部执行器（OpenHands / Python+TS 二开）的 HTTP 适配器。

本模块**不内置**任何外部框架依赖；只要对方暴露 ``POST {base_url}/v1/tasks`` 之类的
契约即可接入。服务不可达或契约不符时返回失败结果（``ok=False``），不抛出，便于降级。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .contracts import RunResult, TaskSpec

logger = logging.getLogger(__name__)


class RemoteHarness:
    """通过 HTTP 调用外部 agent 执行器。

    Args:
        base_url: 外部 harness 根地址（如 OpenHands 的 API 网关）。
        submit_path: 任务提交路径（默认 ``/v1/tasks``）。
        timeout_seconds: 单次请求超时。
        api_key: 可选 Bearer 令牌。
    """

    def __init__(
        self,
        base_url: str,
        *,
        submit_path: str = "/v1/tasks",
        timeout_seconds: float = 60.0,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.submit_path = submit_path
        self.timeout_seconds = float(timeout_seconds)
        self.api_key = api_key

    def info(self) -> dict[str, Any]:
        """返回 harness 信息（``available`` 依赖服务可达性，由 :meth:`available` 判断）。"""
        return {
            "name": "remote",
            "runtime": self.base_url,
            "available": self.available(),
            "submit_path": self.submit_path,
        }

    def available(self) -> bool:
        """探测外部 harness 是否可达（HTTP 探活）。"""
        try:
            import requests  # noqa: PLC0415

            resp = requests.get(f"{self.base_url}/health", timeout=min(self.timeout_seconds, 3.0))
            return resp.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    def run(self, task: TaskSpec) -> RunResult:
        """提交任务到外部执行器并解析结果；失败时返回 ``ok=False``。"""
        started = datetime.now(timezone.utc)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "task_id": task.task_id,
            "kind": task.kind,
            "payload": task.payload,
            "timeout_seconds": task.timeout_seconds,
            "metadata": task.metadata,
        }
        try:
            import requests  # noqa: PLC0415

            resp = requests.post(
                f"{self.base_url}{self.submit_path}",
                json=payload,
                headers=headers,
                timeout=task.timeout_seconds or self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return RunResult(
                task_id=task.task_id,
                ok=bool(data.get("ok", True)),
                output=data.get("output"),
                error=data.get("error"),
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                runtime=self.base_url,
            )
        except Exception as exc:  # noqa: BLE001 - 远程不可用时降级为失败结果
            logger.info("远程 harness 调用失败: %s", exc)
            return RunResult(
                task_id=task.task_id,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                runtime=self.base_url,
            )
