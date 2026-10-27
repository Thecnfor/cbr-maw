"""实时智能抓取层（L1.5 数据接入）：把「手动找数据」升级为「系统自动实时抓取」。

对外主要接口：

.. code-block:: python

    from cbr.ingest import build_ingest_agent, IngestAgent, IngestScheduler

    agent = build_ingest_agent()            # 读 configs/sources.yaml + PIT 存储
    tasks = agent.plan()                    # 确定性缺口分析（该抓什么）
    report = agent.run()                    # 抓取 → 增量落库 → 重算派生序列

    scheduler = IngestScheduler(agent)      # 可选：后台定时抓取
    scheduler.start()

来源全部由 ``configs/sources.yaml`` 声明；抓取器按 ``kind`` 选择（见 ``sources.py``）。
抓取只增量写入 PIT 存储，不重建全库；派生序列在写入后按文档口径重算。
"""

from __future__ import annotations

from typing import Any

from cbr.config import AppSettings, load_settings
from cbr.data.pit_store import PitStore

from .agent import IngestAgent, load_source_specs
from .contracts import (
    DOC_COLUMNS,
    OBS_COLUMNS,
    FetchResult,
    Fetcher,
    SourceSpec,
)
from .derive import DERIVED_INPUTS, compute_derived, recompute_derived
from .gaps import analyze_freshness, analyze_gaps, stale_threshold_days
from .scheduler import IngestScheduler
from .sources import FETCHER_KINDS, build_fetcher

__all__ = [
    "DERIVED_INPUTS",
    "DOC_COLUMNS",
    "FETCHER_KINDS",
    "FetchResult",
    "Fetcher",
    "IngestAgent",
    "IngestScheduler",
    "OBS_COLUMNS",
    "SourceSpec",
    "analyze_freshness",
    "analyze_gaps",
    "build_fetcher",
    "build_ingest_agent",
    "compute_derived",
    "load_source_specs",
    "recompute_derived",
    "stale_threshold_days",
]


def _open_store(settings: AppSettings) -> PitStore:
    """打开（必要时创建）配置指定的 PIT 存储。"""
    from cbr.config import resolve_path

    path = resolve_path(settings.data.pit_db)
    if not path.exists():
        store = PitStore(path, read_only=False)
        store.initialize_schema()
        return store
    return PitStore(path, read_only=False)


def build_ingest_agent(
    settings: AppSettings | None = None,
    store: PitStore | None = None,
    fetchers: dict[str, Any] | None = None,
) -> IngestAgent:
    """按配置装配抓取智能体。

    Args:
        settings: 应用配置（默认 ``load_settings()``）。
        store: PIT 存储（默认打开 ``settings.data.pit_db``，缺失则创建空库）。
        fetchers: 可选注入的抓取器（测试用）。

    Returns:
        ``IngestAgent``。
    """
    settings = settings or load_settings()
    specs = load_source_specs(settings.ingest.sources_config)
    store = store or _open_store(settings)
    return IngestAgent(store, specs, settings, fetchers=fetchers)
