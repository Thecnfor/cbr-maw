"""实时抓取的进程内运行时：调度器单例 + 与 DataProvider 的连接协调。

关键约束：DuckDB 同一进程内不能同时持有同一文件的读写连接与只读连接。因此运行时
在写入前调用 ``provider.detach()`` 释放只读连接，写入后 ``provider.reload()`` 重新
打开并热刷新数据集。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from cbr.config import AppSettings, load_settings
from cbr.data.pit_store import PitStore

from .agent import IngestAgent, load_source_specs
from .scheduler import IngestScheduler

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()  # 可重入：get_ingest_scheduler 会调用 get_ingest_agent
_SCHEDULER: IngestScheduler | None = None
_AGENT: IngestAgent | None = None


def _service_provider() -> Any:
    """尽力获取已装配服务的 DataProvider（未就绪时返回 ``None``）。"""
    try:
        from cbr.api import readiness

        service, _error = readiness.acquire_service()
    except Exception:  # noqa: BLE001
        return None
    return getattr(service, "provider", None) if service is not None else None


def provider_hooks() -> tuple[Any, Any]:
    """返回 (pre_run, on_written) 回调：写前释放只读连接、写后热刷新。"""

    def pre_run() -> None:
        provider = _service_provider()
        detach = getattr(provider, "detach", None)
        if callable(detach):
            detach()

    def on_written() -> None:
        provider = _service_provider()
        reload_fn = getattr(provider, "reload", None)
        if callable(reload_fn):
            reload_fn()

    return pre_run, on_written


def _open_write_store(settings: AppSettings) -> PitStore:
    """打开（必要时创建）PIT 存储的读写连接（懒连接，首次使用才真正打开）。"""
    from cbr.config import resolve_path

    path = resolve_path(settings.data.pit_db)
    store = PitStore(path, read_only=False)
    return store


def get_ingest_agent(settings: AppSettings | None = None) -> IngestAgent:
    """返回进程内单例抓取智能体（延迟构建）。"""
    global _AGENT
    with _LOCK:
        if _AGENT is None:
            settings = settings or load_settings()
            specs = load_source_specs(settings.ingest.sources_config)
            _AGENT = IngestAgent(_open_write_store(settings), specs, settings)
        return _AGENT


def get_ingest_scheduler(settings: AppSettings | None = None) -> IngestScheduler:
    """返回进程内单例调度器（延迟构建，不自动启动）。"""
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is None:
            settings = settings or load_settings()
            agent = get_ingest_agent(settings)
            pre_run, on_written = provider_hooks()
            _SCHEDULER = IngestScheduler(agent, settings, on_written=on_written)
            _SCHEDULER._pre_run_hook = pre_run  # 由 run_once 读取
        return _SCHEDULER


def start_if_enabled(settings: AppSettings | None = None) -> bool:
    """若配置启用则启动后台调度器；返回是否已启动（或已在运行）。"""
    settings = settings or load_settings()
    if not settings.ingest.enabled:
        return False
    scheduler = get_ingest_scheduler(settings)
    if scheduler.is_running:
        return True
    return scheduler.start()


def stop_scheduler() -> None:
    """停止后台调度器（可重复调用）。"""
    scheduler = _SCHEDULER
    if scheduler is not None:
        scheduler.stop()


def reset_ingest_runtime() -> None:
    """重置单例（测试/热重载用）。"""
    global _SCHEDULER, _AGENT
    stop_scheduler()
    with _LOCK:
        _SCHEDULER = None
        _AGENT = None
