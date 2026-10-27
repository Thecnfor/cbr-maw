"""实时智能抓取 API（``/api/ingest/*``）。

- ``GET  /api/ingest/status``    子系统状态（调度器、来源健康、陈旧序列、最近报告）
- ``GET  /api/ingest/sources``   各来源健康快照
- ``GET  /api/ingest/freshness`` 各规范序列新鲜度
- ``GET  /api/ingest/plan``      当前待抓取计划（确定性缺口分析）
- ``POST /api/ingest/refresh``   按需触发一次抓取（写回 PIT 并热刷新 DataProvider）

设计约束：只读端点**不触发**核心服务全量装配（数据/知识/模型装配成本高），
仅在核心服务已经构建时复用其只读连接；``refresh`` 在服务未就绪时仍可写入 PIT。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException

from cbr.config import AppSettings, load_settings, resolve_path
from cbr.data.pit_store import PitStore
from cbr.ingest.agent import IngestAgent, load_source_specs
from cbr.ingest.gaps import analyze_freshness, analyze_gaps
from cbr.ingest.runtime import get_ingest_scheduler, provider_hooks
from cbr.schemas import (
    IngestRefreshRequest,
    IngestReport,
    IngestStatus,
    IngestTask,
    SeriesFreshness,
    SourceStatus,
)

router = APIRouter(prefix="/api/ingest", tags=["实时抓取"])


def _existing_service() -> Any | None:
    """返回**已构建**的服务单例；未构建时返回 ``None``（不触发全量装配）。"""
    from cbr import service as service_module

    getter = getattr(service_module, "get_service", None)
    cache_info = getattr(getter, "cache_info", None)
    if callable(cache_info):
        try:
            if cache_info().currsize == 0:
                return None
        except Exception:  # noqa: BLE001 - 非标准 getter（测试替身）时继续尝试
            pass
    try:
        return getter() if callable(getter) else None
    except Exception:  # noqa: BLE001
        return None


def _settings() -> AppSettings:
    """返回配置：优先复用已构建服务的配置（尊重 CBR_CONFIG），否则读本地配置。"""
    service = _existing_service()
    return getattr(service, "settings", None) or load_settings()


def _provider() -> Any | None:
    """返回已构建服务的 DataProvider（未构建时 ``None``）。"""
    service = _existing_service()
    return getattr(service, "provider", None) if service is not None else None


def _read_store(settings: AppSettings) -> PitStore | None:
    """返回只读 PIT 存储：优先复用 provider 的连接，否则打开配置指定的库。"""
    store = getattr(_provider(), "store", None)
    if isinstance(store, PitStore):
        return store
    path = resolve_path(settings.data.pit_db)
    if not path.exists():
        return None
    try:
        return PitStore.open(path)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _coverage(settings: AppSettings) -> dict[str, tuple[dt.date | None, dt.date | None]]:
    """读取序列覆盖期（无库/空库时返回空映射）。"""
    store = _read_store(settings)
    if store is None:
        return {}
    try:
        return store.coverage()
    except Exception:  # noqa: BLE001 - 空库/表缺失时视为无数据
        return {}


def _specs(settings: AppSettings) -> list[Any]:
    """加载来源规格（配置异常时不阻断状态查询）。"""
    try:
        return load_source_specs(settings.ingest.sources_config)
    except Exception:  # noqa: BLE001
        return []


@router.get("/status", response_model=IngestStatus, summary="实时抓取子系统状态")
def ingest_status() -> IngestStatus:
    """返回调度器状态、来源健康、陈旧序列与最近一次抓取报告。"""
    settings = _settings()
    as_of = dt.date.today()
    specs = _specs(settings)
    scheduler = get_ingest_scheduler(settings)
    status = scheduler.status(as_of)
    freshness = analyze_freshness(_coverage(settings), specs, as_of, settings)
    return IngestStatus(
        enabled=bool(settings.ingest.enabled),
        running=bool(status["running"]),
        as_of=as_of,
        interval_seconds=status.get("interval_seconds"),
        last_run_at=status.get("last_run_at"),
        next_run_at=status.get("next_run_at"),
        n_sources=len(specs),
        sources=scheduler.agent.source_statuses(),
        stale_series=[f for f in freshness if f.is_stale],
        last_report=scheduler.agent.last_report,
    )


@router.get("/sources", response_model=list[SourceStatus], summary="抓取来源健康快照")
def ingest_sources() -> list[SourceStatus]:
    """返回各来源的启用状态与最近一次运行结果。"""
    return get_ingest_scheduler(_settings()).agent.source_statuses()


@router.get("/freshness", response_model=list[SeriesFreshness], summary="序列新鲜度")
def ingest_freshness() -> list[SeriesFreshness]:
    """返回全部规范序列的陈旧程度与抓取可得性。"""
    settings = _settings()
    return analyze_freshness(_coverage(settings), _specs(settings), dt.date.today(), settings)


@router.get("/plan", response_model=list[IngestTask], summary="待抓取计划（缺口分析）")
def ingest_plan(force: bool = False) -> list[IngestTask]:
    """返回当前应抓取的任务清单（确定性，按优先级排序）。"""
    settings = _settings()
    return analyze_gaps(_coverage(settings), _specs(settings), dt.date.today(), settings, force=force)


@router.post("/refresh", response_model=IngestReport, summary="按需触发一次实时抓取")
def ingest_refresh(request: IngestRefreshRequest) -> IngestReport:
    """按需抓取：写回 PIT 存储并热刷新 DataProvider（决策随即使用新数据）。"""
    settings = _settings()
    specs = _specs(settings)
    if not specs:
        raise HTTPException(status_code=503, detail="source 配置不可用：请检查 configs/sources.yaml")

    as_of = request.as_of or dt.date.today()
    series_ids = tuple(request.series_ids) if request.series_ids else None

    provider = _provider()
    pre_run, on_written = provider_hooks()
    store = PitStore(resolve_path(settings.data.pit_db), read_only=False)
    try:
        agent = IngestAgent(store, specs, settings)
        report = agent.run(
            as_of,
            series_ids=series_ids,
            mode=request.mode,
            pre_run=pre_run if provider is not None else None,
            on_written=on_written if provider is not None else None,
        )
    finally:
        store.close()
    # 无论成功与否都恢复 provider 连接
    reload_fn = getattr(provider, "reload", None)
    if callable(reload_fn):
        try:
            reload_fn()
        except Exception:  # noqa: BLE001
            pass
    return report
