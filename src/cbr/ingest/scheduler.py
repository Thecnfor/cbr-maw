"""后台调度器：按固定间隔（或按需）触发实时抓取。

调度器是**可选**组件——默认关闭（``ingest.enabled=false``），开启后以守护线程运行，
不阻塞 FastAPI/Streamlit 主线程；单实例串行，避免并发重复抓取。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cbr.config import AppSettings, load_settings
from cbr.schemas import IngestReport

from .agent import IngestAgent

logger = logging.getLogger(__name__)


class IngestScheduler:
    """串行的定时抓取调度器（线程安全）。

    Args:
        agent: 抓取智能体。
        settings: 应用配置（读取 ``ingest.interval_seconds`` 等）。
        on_written: 抓取写回后的回调（刷新 DataProvider）。
    """

    def __init__(
        self,
        agent: IngestAgent,
        settings: AppSettings | None = None,
        on_written: Any = None,
    ) -> None:
        self.agent = agent
        self.settings = settings or load_settings()
        self.on_written = on_written
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.running = False
        self.last_run_at: datetime | None = None
        self.next_run_at: datetime | None = None
        self._pre_run_hook: Any = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    @property
    def interval_seconds(self) -> int:
        """抓取间隔（秒）。"""
        return int(self.settings.ingest.interval_seconds)

    def start(self, *, run_now: bool | None = None) -> bool:
        """启动后台循环；已在运行则返回 False。"""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        run_now = self.settings.ingest.run_on_start if run_now is None else run_now
        self._thread = threading.Thread(target=self._loop, args=(run_now,), name="cbr-ingest", daemon=True)
        self._thread.start()
        logger.info("实时抓取调度器已启动（间隔 %ss）", self.interval_seconds)
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台循环（可重复调用）。"""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        self.next_run_at = None

    @property
    def is_running(self) -> bool:
        """后台线程是否存活。"""
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def run_once(
        self,
        *,
        as_of: date | None = None,
        series_ids: tuple[str, ...] | None = None,
        mode: str = "gap",
    ) -> IngestReport:
        """执行一次抓取（串行；已在运行则等待其结束）。"""
        with self._lock:
            self.last_run_at = datetime.now(timezone.utc)
            report = self.agent.run(
                as_of,
                series_ids=series_ids,
                mode=mode,
                pre_run=self._pre_run_hook,
                on_written=self.on_written,
            )
            self.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=self.interval_seconds)
            return report

    def trigger(
        self,
        *,
        as_of: date | None = None,
        series_ids: tuple[str, ...] | None = None,
        mode: str = "gap",
        wait: bool = True,
    ) -> IngestReport | None:
        """按需触发一次抓取；``wait=False`` 时后台异步执行并返回 ``None``。"""
        if not wait:
            threading.Thread(
                target=self.run_once,
                kwargs={"as_of": as_of, "series_ids": series_ids, "mode": mode},
                name="cbr-ingest-once",
                daemon=True,
            ).start()
            return None
        return self.run_once(as_of=as_of, series_ids=series_ids, mode=mode)

    def _loop(self, run_now: bool) -> None:
        self.running = True
        try:
            if run_now:
                self._safe_run()
            while not self._stop.wait(self.interval_seconds):
                self._safe_run()
        finally:
            self.running = False

    def _safe_run(self) -> None:
        try:
            self.run_once()
        except Exception as exc:  # noqa: BLE001 - 调度线程永不因单次失败退出
            logger.warning("定时抓取失败: %s", exc)

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    def status(self, as_of: date | None = None) -> dict[str, Any]:
        """返回调度器状态摘要（供 API）。"""
        return {
            "enabled": bool(self.settings.ingest.enabled),
            "running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_report": self.agent.last_report,
        }
