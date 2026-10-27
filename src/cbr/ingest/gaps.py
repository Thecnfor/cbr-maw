"""缺口 / 陈旧度分析：把「库里有什么」和「系统需要什么」对比成抓取任务。

这是「智能」的确定性内核——不依赖 LLM 也能稳定产出「该抓谁」的清单；
LLM 只用于在优先级相近时做取舍（见 :mod:`cbr.ingest.agent`）。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from cbr.config import AppSettings, load_settings
from cbr.data.catalog import SERIES_SPECS, SeriesSpec
from cbr.schemas import IngestTask, SeriesFreshness

from .contracts import SourceSpec


def stale_threshold_days(series: SeriesSpec, settings: AppSettings) -> int:
    """按序列频率给出陈旧的判定阈值（自然日）。"""
    if series.frequency == "monthly":
        return int(settings.ingest.monthly_stale_threshold_days)
    if series.frequency in ("daily", "weekly"):
        return int(settings.ingest.stale_threshold_days)
    return int(settings.ingest.monthly_stale_threshold_days)


def source_index(specs: list[SourceSpec], *, enabled_only: bool = False) -> dict[str, SourceSpec]:
    """构造 ``series_id -> SourceSpec`` 的索引（同一序列取首个声明者）。"""
    index: dict[str, SourceSpec] = {}
    for spec in specs:
        if enabled_only and not spec.enabled:
            continue
        for series_id in spec.series_ids:
            index.setdefault(series_id, spec)
    return index


def source_candidates(specs: list[SourceSpec], series_id: str) -> list[SourceSpec]:
    """返回某个序列可用的全部来源（按声明顺序，首个为主源，其余为备源）。"""
    return [spec for spec in specs if series_id in spec.series_ids]


def _staleness(last_date: date | None, as_of: date) -> int | None:
    if last_date is None:
        return None
    last = pd.Timestamp(last_date).date()
    ref = pd.Timestamp(as_of).date()
    return max(0, (ref - last).days)


def analyze_freshness(
    coverage: dict[str, tuple[date | None, date | None]],
    specs: list[SourceSpec],
    as_of: date,
    settings: AppSettings | None = None,
) -> list[SeriesFreshness]:
    """计算全部规范序列的新鲜度（含抓取可得性与来源归属）。"""
    settings = settings or load_settings()
    index = source_index(specs)
    out: list[SeriesFreshness] = []
    for series_id, series in SERIES_SPECS.items():
        _start, end = coverage.get(series_id, (None, None))
        threshold = stale_threshold_days(series, settings)
        staleness = _staleness(end, as_of)
        src = index.get(series_id)
        fetchable = src is not None and not series.derived
        is_stale = bool(fetchable) and (end is None or (staleness is not None and staleness > threshold))
        out.append(
            SeriesFreshness(
                series_id=series_id,
                name=series.name,
                frequency=series.frequency,
                last_obs_date=end,
                staleness_days=staleness,
                threshold_days=threshold,
                is_stale=is_stale,
                fetchable=fetchable,
                source_id=src.source_id if src else None,
            )
        )
    out.sort(key=lambda item: (item.fetchable is False, -(item.staleness_days or 99999)))
    return out


def analyze_gaps(
    coverage: dict[str, tuple[date | None, date | None]],
    specs: list[SourceSpec],
    as_of: date,
    settings: AppSettings | None = None,
    *,
    series_ids: tuple[str, ...] | None = None,
    force: bool = False,
) -> list[IngestTask]:
    """产出待抓取任务清单（按优先级降序）。

    Args:
        coverage: ``PitStore.coverage()`` 的结果。
        specs: 已启用的来源规格。
        as_of: 分析基准日（通常是今天）。
        settings: 应用配置。
        series_ids: 仅分析这些序列（``None`` 表示全部）。
        force: 为真时忽略陈旧阈值，所有可抓取序列都进入计划。

    Returns:
        ``IngestTask`` 列表，优先级从高到低。
    """
    settings = settings or load_settings()
    index = source_index(specs)
    wanted = set(series_ids) if series_ids else None
    tasks: list[IngestTask] = []
    for series_id, series in SERIES_SPECS.items():
        if wanted is not None and series_id not in wanted:
            continue
        if series.derived:
            continue  # 派生序列由写入后的重算逻辑处理，不直接抓取
        src = index.get(series_id)
        if src is None:
            continue  # 无来源可抓
        _start, end = coverage.get(series_id, (None, None))
        threshold = stale_threshold_days(series, settings)
        staleness = _staleness(end, as_of)
        if end is None:
            reason, priority = "missing", 100.0
        elif force or (staleness is not None and staleness > threshold):
            reason = "forced" if force else "stale"
            priority = float(min(99, max(1, (staleness or 0) - threshold)))
        else:
            continue
        tasks.append(
            IngestTask(
                series_id=series_id,
                name=series.name,
                frequency=series.frequency,
                reason=reason,
                last_obs_date=end,
                target_date=as_of,
                staleness_days=staleness,
                priority=priority,
                source_id=src.source_id,
                fetchable=True,
            )
        )
    tasks.sort(key=lambda item: item.priority, reverse=True)
    return tasks
