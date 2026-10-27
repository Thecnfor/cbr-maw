"""实时智能抓取智能体：计划（计划器）→ 抓取（抓取器）→ 增量落库 → 重算派生。

设计要点：

- **计划器是确定性的**：由 :func:`cbr.ingest.gaps.analyze_gaps` 基于覆盖期与陈旧阈值
  产出任务，天然可复现、可审计；LLM 若接入只用于优先级微调，不作为正确性依赖。
- **按来源批处理**：一次运行对每个来源只发一次请求，减少公开接口压力。
- **增量落库**：只写新数据（``PitStore.upsert_observations``），不重建全库。
- **写后重算派生**：基础序列更新后，重算依赖它的派生序列，保证下游看到一致视图。
- **全程留痕**：每次运行产出 ``IngestReport``（可序列化），落盘到 ``artifacts/ingest/``。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from cbr.config import AppSettings, load_settings
from cbr.data.pit_store import PitStore
from cbr.schemas import (
    IngestReport,
    IngestRunResult,
    IngestTask,
    SeriesFreshness,
    SourceStatus,
)

from .contracts import SourceSpec, empty_documents
from .derive import DERIVED_INPUTS, recompute_derived
from .gaps import analyze_freshness, analyze_gaps, source_candidates, source_index
from .sources import build_fetcher

logger = logging.getLogger(__name__)


def _today() -> date:
    """本地（项目约定 Asia/Shanghai）当天日期。"""
    return datetime.now().date()


class IngestAgent:
    """实时抓取智能体。

    Args:
        store: 写入 / 读取的 PIT 存储（需可写）。
        specs: 来源规格列表（``configs/sources.yaml``）。
        settings: 应用配置。
        fetchers: 可选的 ``source_id -> Fetcher`` 注入（测试用，避免真实网络）。
    """

    def __init__(
        self,
        store: PitStore,
        specs: list[SourceSpec],
        settings: AppSettings | None = None,
        fetchers: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.specs = list(specs)
        self.settings = settings or load_settings()
        self._fetchers = dict(fetchers or {})
        self._spec_by_id = {spec.source_id: spec for spec in self.specs}
        self._candidates: dict[str, list[SourceSpec]] = {}
        for spec in self.enabled_specs():
            for series_id in spec.series_ids:
                self._candidates.setdefault(series_id, []).append(spec)
        self.last_report: IngestReport | None = None
        self._last_source_run: dict[str, datetime] = {}

    # ------------------------------------------------------------------ #
    # 基础信息
    # ------------------------------------------------------------------ #
    def enabled_specs(self) -> list[SourceSpec]:
        """返回已启用的来源规格。"""
        return [spec for spec in self.specs if spec.enabled]

    def _fetcher_for(self, spec: SourceSpec) -> Any:
        if spec.source_id in self._fetchers:
            return self._fetchers[spec.source_id]
        fetcher = build_fetcher(spec, self.settings)
        self._fetchers[spec.source_id] = fetcher
        return fetcher

    # ------------------------------------------------------------------ #
    # 计划
    # ------------------------------------------------------------------ #
    def plan(
        self,
        as_of: date | None = None,
        *,
        series_ids: tuple[str, ...] | None = None,
        force: bool = False,
    ) -> list[IngestTask]:
        """产出待抓取任务（确定性、按优先级降序）。"""
        as_of = as_of or _today()
        coverage = self.store.coverage()
        return analyze_gaps(
            coverage,
            self.enabled_specs(),
            as_of,
            self.settings,
            series_ids=series_ids,
            force=force,
        )

    def freshness(self, as_of: date | None = None) -> list[SeriesFreshness]:
        """返回全部序列的新鲜度。"""
        as_of = as_of or _today()
        return analyze_freshness(self.store.coverage(), self.enabled_specs(), as_of, self.settings)

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def run(
        self,
        as_of: date | None = None,
        *,
        series_ids: tuple[str, ...] | None = None,
        mode: str = "gap",
        write: bool | None = None,
        pre_run: Callable[[], None] | None = None,
        on_written: Callable[[], None] | None = None,
    ) -> IngestReport:
        """执行一次抓取运行。

        Args:
            as_of: 基准日（默认今天）。
            series_ids: 仅抓取这些序列（``None`` 表示按缺口自动选择）。
            mode: ``gap``（按缺口）/ ``full``（全部来源）/ ``forced``（忽略阈值）。
            write: 是否写回 PIT（默认读配置 ``ingest.write_to_pit``）。
            pre_run: 写回前的回调（用于释放只读连接，避免 DuckDB 读写连接冲突）。
            on_written: 写回成功后的回调（用于刷新在内存中的 DataProvider）。

        Returns:
            ``IngestReport``。
        """
        as_of = as_of or _today()
        write = self.settings.ingest.write_to_pit if write is None else write
        started = datetime.now(timezone.utc)
        run_id = f"ingest-{as_of.isoformat()}-{uuid.uuid4().hex[:8]}"

        if pre_run is not None:
            pre_run()
        tasks = self.plan(as_of, series_ids=series_ids, force=(mode == "forced"))
        if mode == "full":
            # full：不按陈旧度筛选，抓取全部可抓取序列
            tasks = self._all_tasks(as_of, series_ids)

        results: list[IngestRunResult] = []
        n_obs = n_docs = 0
        written_series: list[str] = []
        written_base: list[str] = []

        for result in self._execute(tasks, as_of, mode=mode, write=write):
            results.append(result)
            n_obs += result.n_observations
            n_docs += result.n_documents
            written_series.extend(result.series_ids)
            self._last_source_run[result.source_id] = result.finished_at or datetime.now(timezone.utc)

        if write and n_obs:
            written_base = sorted({sid for sid in self._base_series(results)})
            derived = recompute_derived(self.store, as_of)
            written_series.extend(derived.keys())
            if on_written is not None:
                try:
                    on_written()
                except Exception as exc:  # noqa: BLE001 - 回调失败不影响抓取结果
                    logger.warning("写后回调失败: %s", exc)

        report = IngestReport(
            run_id=run_id,
            as_of=as_of,
            mode="forced" if mode == "forced" else ("full" if mode == "full" else "gap"),
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            n_tasks=len(tasks),
            n_observations=n_obs,
            n_documents=n_docs,
            n_errors=sum(1 for r in results if r.status == "error"),
            written_series=sorted(set(written_series)),
            results=results,
            tasks=tasks,
            notes=f"抓取来源 {len(results)} 个，写入基础序列 {len(written_base)} 条",
        )
        self.last_report = report
        self._persist_report(report)
        return report

    def _all_tasks(self, as_of: date, series_ids: tuple[str, ...] | None) -> list[IngestTask]:
        """``full`` 模式：为所有可抓取序列构造任务。"""
        index = source_index(self.enabled_specs())
        wanted = set(series_ids) if series_ids else None
        tasks: list[IngestTask] = []
        coverage = self.store.coverage()
        for series_id, spec in index.items():
            if wanted is not None and series_id not in wanted:
                continue
            _start, end = coverage.get(series_id, (None, None))
            tasks.append(
                IngestTask(
                    series_id=series_id,
                    reason="forced",
                    last_obs_date=end,
                    target_date=as_of,
                    source_id=spec.source_id,
                )
            )
        return tasks

    @staticmethod
    def _base_series(results: Iterable[IngestRunResult]) -> list[str]:
        out: list[str] = []
        for result in results:
            if result.status in ("ok", "empty"):
                out.extend(result.series_ids)
        return out

    def _execute(
        self,
        tasks: list[IngestTask],
        as_of: date,
        *,
        mode: str,
        write: bool,
    ) -> list[IngestRunResult]:
        """执行抓取：主源失败/空时自动切换备源；附带纯文档来源。

        每个序列按 ``configs/sources.yaml`` 的声明顺序尝试来源，直到拿到数据或
        备源耗尽，避免单点（如某公开接口限流）导致整条序列断供。
        """
        results: list[IngestRunResult] = []
        pending = self._group_by_source(tasks)
        tried: dict[str, set[str]] = {}
        seen_groups: set[tuple[str, tuple[str, ...]]] = set()

        while pending:
            next_pending: list[tuple[str, list[IngestTask]]] = []
            for source_id, group in pending:
                spec = self._spec_by_id.get(source_id)
                if spec is None:
                    continue
                key = (source_id, tuple(sorted(t.series_id for t in group)))
                if key in seen_groups:
                    continue
                seen_groups.add(key)

                result = self._run_source(spec, group, as_of, write=write)
                results.append(result)
                observed = set(result.series_ids)
                for task in group:
                    if task.series_id in observed:
                        continue
                    tried.setdefault(task.series_id, set()).add(source_id)
                    alt = self._next_source(task.series_id, tried[task.series_id])
                    if alt is not None:
                        next_pending.append((alt.source_id, [task]))
            pending = self._merge_pending(next_pending)

        for spec in self._document_sources_impl(mode=mode):
            results.append(self._run_source(spec, [], as_of, write=write))
        return results

    @staticmethod
    def _merge_pending(
        pending: list[tuple[str, list[IngestTask]]],
    ) -> list[tuple[str, list[IngestTask]]]:
        """合并同一来源的任务，保持顺序。"""
        order: list[str] = []
        groups: dict[str, list[IngestTask]] = {}
        for source_id, group in pending:
            if source_id not in groups:
                groups[source_id] = []
                order.append(source_id)
            groups[source_id].extend(group)
        return [(sid, groups[sid]) for sid in order]

    def _next_source(self, series_id: str, tried: set[str]) -> SourceSpec | None:
        """返回该序列下一个未尝试的来源（无则 ``None``）。"""
        for spec in self._candidates.get(series_id, []):
            if spec.source_id not in tried:
                return spec
        return None

    def _group_by_source(self, tasks: list[IngestTask]) -> list[tuple[str, list[IngestTask]]]:
        """按来源聚合任务，保持优先级顺序。"""
        order: list[str] = []
        groups: dict[str, list[IngestTask]] = {}
        for task in tasks:
            if not task.source_id or not task.fetchable:
                continue
            if task.source_id not in groups:
                groups[task.source_id] = []
                order.append(task.source_id)
            groups[task.source_id].append(task)
        return [(sid, groups[sid]) for sid in order]

    def _run_source(
        self,
        spec: SourceSpec,
        tasks: list[IngestTask],
        as_of: date,
        *,
        write: bool,
    ) -> IngestRunResult:
        """抓取单个来源并（可选）增量落库。"""
        series_ids = tuple(task.series_id for task in tasks)
        last_dates = [task.last_obs_date for task in tasks if task.last_obs_date is not None]
        since = min(last_dates) if last_dates else None
        started = datetime.now(timezone.utc)
        try:
            fetcher = self._fetcher_for(spec)
            result = fetcher.fetch(since=since, until=as_of, series_ids=series_ids)
        except Exception as exc:  # noqa: BLE001 - 构造抓取器失败
            return IngestRunResult(
                source_id=spec.source_id,
                status="error",
                series_ids=[],
                error=f"{type(exc).__name__}: {exc}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
            )

        observations = result.observations
        if not observations.empty and series_ids:
            observations = observations[observations["series_id"].isin(series_ids)]
        documents = result.documents if result.documents is not None else empty_documents()

        n_obs = int(len(observations))
        n_docs = int(len(documents))
        if write:
            if n_obs:
                n_obs = self.store.upsert_observations(observations)
                self.store.touch_coverage(sorted(observations["series_id"].unique()))
            if n_docs:
                n_docs = self.store.upsert_documents(documents)
        return IngestRunResult(
            source_id=spec.source_id,
            status=result.status,  # type: ignore[arg-type]
            n_observations=n_obs,
            n_documents=n_docs,
            series_ids=sorted(observations["series_id"].unique().tolist()) if n_obs else [],
            error=result.error,
            latency_ms=result.latency_ms,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )

    def _document_sources_impl(self, *, mode: str) -> list[SourceSpec]:
        """返回本次运行需要抓取的纯文档来源（RSS/新闻）。"""
        out: list[SourceSpec] = []
        for spec in self.enabled_specs():
            if not spec.documents or spec.series_ids:
                continue
            if mode == "full" or self._document_source_due(spec):
                out.append(spec)
        return out

    def _document_source_due(self, spec: SourceSpec) -> bool:
        """文档来源是否到达抓取间隔（首次运行始终到期）。"""
        last = self._last_source_run.get(spec.source_id)
        if last is None:
            return True
        interval = spec.interval_seconds or self.settings.ingest.interval_seconds
        return (datetime.now(timezone.utc) - last).total_seconds() >= interval

    # ------------------------------------------------------------------ #
    # 状态 / 持久化
    # ------------------------------------------------------------------ #
    def source_statuses(self) -> list[SourceStatus]:
        """返回各来源的状态快照（最近一次运行结果）。"""
        last: dict[str, Any] = {}
        if self.last_report is not None:
            for result in self.last_report.results:
                last[result.source_id] = result
        statuses: list[SourceStatus] = []
        for spec in self.specs:
            result = last.get(spec.source_id)
            statuses.append(
                SourceStatus(
                    source_id=spec.source_id,
                    kind=spec.kind,
                    enabled=spec.enabled,
                    series_ids=list(spec.series_ids),
                    documents=spec.documents,
                    interval_seconds=spec.interval_seconds,
                    last_status=(result.status if result else "never"),  # type: ignore[arg-type]
                    last_error=(result.error if result else None),
                    last_records=((result.n_observations + result.n_documents) if result else 0),
                    latency_ms=(result.latency_ms if result else None),
                )
            )
        return statuses

    def derived_targets(self) -> list[str]:
        """返回派生序列清单（供状态展示）。"""
        return list(DERIVED_INPUTS)

    def _persist_report(self, report: IngestReport) -> None:
        """把报告落盘到 ``ingest.log_dir``（失败不影响主流程）。"""
        try:
            log_dir = Path(self.settings.ingest.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{report.run_id}.json"
            path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            latest = log_dir / "latest.json"
            latest.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("写抓取报告失败: %s", exc)


def load_source_specs(path: str | None = None) -> list[SourceSpec]:
    """从 YAML 加载来源规格（``None`` 时读配置默认路径）。"""
    from cbr.config import load_yaml, resolve_path

    settings = load_settings()
    config_path = path or settings.ingest.sources_config
    raw = load_yaml(config_path, default={}) or {}
    items = raw.get("sources") if isinstance(raw, dict) else raw
    specs: list[SourceSpec] = []
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            specs.append(SourceSpec.from_dict(item))
    # 校验引用：来源声明的系列必须存在于目录，派生序列不可声明为可抓取
    from cbr.data.catalog import SERIES_SPECS

    for spec in specs:
        for series_id in spec.series_ids:
            if series_id not in SERIES_SPECS:
                raise ValueError(f"来源 {spec.source_id} 声明了未知序列 {series_id}")
            if SERIES_SPECS[series_id].derived:
                raise ValueError(f"来源 {spec.source_id} 不能声明派生序列 {series_id}")
    _ = resolve_path(config_path)
    return specs
