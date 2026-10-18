"""内存数据集抽象与 Point-in-Time 查询工具。

``MarketDataset`` 是数据层内部的**统一内存表示**：所有观测以长表
``obs(series_id, obs_date, value, release_time, source, unit)`` 保存，
文档以 ``documents(doc_id, publish_time, source, title, body, url, hash)`` 保存。
所有读取接口都显式接收 ``as_of``，仅返回 ``release_time <= as_of 当日 23:59:59``
的观测，从数据访问入口保证无未来信息泄漏。

数据来源可以是确定性仿真数据（默认）、PIT Store（DuckDB）或用户自建数据；
特征、标签、模型与 DataProvider 均基于本抽象实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from cbr.data.catalog import (
    DAILY_SERIES_IDS,
    KEY_SNAPSHOT_SERIES,
    MONTHLY_SERIES_IDS,
    SERIES_SPECS,
    SYNTHETIC_SOURCE,
    build_data_cards,
    series_unit,
)
from cbr.schemas import DataCard

#: 观测长表必需列
OBS_COLUMNS: tuple[str, ...] = ("series_id", "obs_date", "value", "release_time", "source", "unit")

#: 文档表必需列
DOC_COLUMNS: tuple[str, ...] = ("doc_id", "publish_time", "source", "title", "body", "url", "hash")

#: 文档表可选附加列（标签、主题等；不进入 PIT 数据库的 documents 核心表）
DOC_EXTRA_COLUMNS: tuple[str, ...] = ("tags", "topic", "sentiment")


def as_of_timestamp(as_of: date | datetime | str | pd.Timestamp) -> pd.Timestamp:
    """把 ``as_of`` 规范化为“当日结束时刻”（含当日全部发布信息）。

    Args:
        as_of: 日期 / 日期时间 / 字符串。

    Returns:
        当日 23:59:59.999999 的 Timestamp，用于 ``release_time <= as_of`` 比较。
    """
    ts = pd.Timestamp(as_of)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)


def _normalize_date(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


@dataclass
class MarketDataset:
    """时点数据集：观测长表 + 文档表 + 元信息。

    Attributes:
        obs: 观测长表，列见 ``OBS_COLUMNS``。
        documents: 文本/政策文档表，列见 ``DOC_COLUMNS``（可含 ``DOC_EXTRA_COLUMNS``）。
        seed: 生成/导入数据的随机种子（用于可复现性记录）。
        source: 数据来源标记；仿真数据必须为 ``synthetic-simulation``。
        meta: 附加元信息（如生成区间、市场日历说明）。
    """

    obs: pd.DataFrame
    documents: pd.DataFrame
    seed: int = 0
    source: str = SYNTHETIC_SOURCE
    meta: dict[str, Any] = field(default_factory=dict)
    _daily_frame: pd.DataFrame | None = field(default=None, init=False, repr=False)
    _coverage: dict[str, tuple[date | None, date | None]] | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # 构造 / 校验
    # ------------------------------------------------------------------ #
    def __post_init__(self) -> None:
        self.obs = self._normalize_obs(self.obs)
        self.documents = self._normalize_documents(self.documents)

    @staticmethod
    def _normalize_obs(obs: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in OBS_COLUMNS if c not in obs.columns]
        if missing:
            raise ValueError(f"观测长表缺少必需列: {missing}")
        frame = obs.loc[:, list(OBS_COLUMNS)].copy()
        frame["series_id"] = frame["series_id"].astype("string").astype(str)
        frame["obs_date"] = pd.to_datetime(frame["obs_date"]).dt.normalize()
        frame["release_time"] = pd.to_datetime(frame["release_time"])
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(float)
        frame["source"] = frame["source"].astype("string").astype(str)
        frame["unit"] = frame["unit"].astype("string").astype(str)
        frame = frame.sort_values(["series_id", "obs_date", "release_time"], kind="mergesort")
        frame = frame.drop_duplicates(subset=["series_id", "obs_date"], keep="last").reset_index(drop=True)
        return frame

    @staticmethod
    def _normalize_documents(documents: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in DOC_COLUMNS if c not in documents.columns]
        if missing:
            raise ValueError(f"文档表缺少必需列: {missing}")
        extra = [c for c in DOC_EXTRA_COLUMNS if c in documents.columns]
        frame = documents.loc[:, list(DOC_COLUMNS) + extra].copy()
        frame["doc_id"] = frame["doc_id"].astype("string").astype(str)
        frame["publish_time"] = pd.to_datetime(frame["publish_time"])
        frame["source"] = frame["source"].astype("string").astype(str)
        frame["title"] = frame["title"].astype("string").astype(str)
        frame["body"] = frame["body"].astype("string").astype(str)
        frame["url"] = frame["url"].astype("string").astype(str)
        frame["hash"] = frame["hash"].astype("string").astype(str)
        frame = frame.sort_values(["publish_time", "doc_id"], kind="mergesort").reset_index(drop=True)
        return frame

    # ------------------------------------------------------------------ #
    # 基本视图
    # ------------------------------------------------------------------ #
    @property
    def calendar(self) -> pd.DatetimeIndex:
        """交易日历（日频序列出现的全部交易日，升序）。"""
        daily = self.obs[self.obs["series_id"].isin(DAILY_SERIES_IDS)]
        return pd.DatetimeIndex(sorted(daily["obs_date"].unique()))

    @property
    def start(self) -> pd.Timestamp | None:
        """数据覆盖起始日。"""
        cal = self.calendar
        return cal[0] if len(cal) else None

    @property
    def end(self) -> pd.Timestamp | None:
        """数据覆盖结束日。"""
        cal = self.calendar
        return cal[-1] if len(cal) else None

    def daily_frame(self, series_ids: Iterable[str] | None = None) -> pd.DataFrame:
        """日频宽表：行=交易日，列=序列 ID。

        Args:
            series_ids: 需要的序列集合；默认全部日频序列（含派生序列）。

        Returns:
            按交易日升序索引的宽表；缺失值为 ``NaN``（不做前向填充）。
        """
        ids = list(series_ids) if series_ids is not None else list(DAILY_SERIES_IDS)
        if series_ids is None and self._daily_frame is not None:
            return self._daily_frame
        frame = self.obs[self.obs["series_id"].isin(ids)]
        wide = frame.pivot(index="obs_date", columns="series_id", values="value")
        wide = wide.reindex(columns=[c for c in ids if c in wide.columns]).sort_index()
        if series_ids is None:
            self._daily_frame = wide
        return wide

    def monthly_frame(self) -> pd.DataFrame:
        """月频宽表：行=观测月，列=月频序列 ID（不重复发布时滞，仅原始观测）。"""
        frame = self.obs[self.obs["series_id"].isin(MONTHLY_SERIES_IDS)]
        wide = frame.pivot(index="obs_date", columns="series_id", values="value")
        return wide.sort_index()

    def macro_asof_frame(self, calendar: pd.DatetimeIndex | None = None) -> pd.DataFrame:
        """把月频数据按**发布时点**对齐到日频交易日历。

        对每个交易日 t，只取 ``release_time <= t 当日结束`` 的最新一次月频观测，
        因此 t 不包含尚未发布的月频数据（无未来信息）。

        Args:
            calendar: 目标交易日历；默认使用 ``self.calendar``。

        Returns:
            行=交易日、列=月频序列 ID 的 DataFrame（未发布为 NaN）。
        """
        cal = pd.DatetimeIndex(calendar) if calendar is not None else self.calendar
        result = pd.DataFrame(index=cal)
        monthly_ids = list(MONTHLY_SERIES_IDS)
        frame = self.obs[self.obs["series_id"].isin(monthly_ids)]
        if frame.empty:
            for sid in monthly_ids:
                result[sid] = float("nan")
            return result.sort_index()
        right = frame.loc[:, ["series_id", "release_time", "value"]].sort_values("release_time")
        for sid in monthly_ids:
            sub = right[right["series_id"] == sid][["release_time", "value"]].sort_values("release_time")
            if sub.empty:
                result[sid] = float("nan")
                continue
            merged = pd.merge_asof(
                pd.DataFrame({"as_of_ts": cal}),
                sub.rename(columns={"release_time": "as_of_ts"}),
                on="as_of_ts",
                direction="backward",
            )
            result[sid] = merged["value"].to_numpy()
        return result.sort_index()

    # ------------------------------------------------------------------ #
    # Point-in-time 查询
    # ------------------------------------------------------------------ #
    def asof_obs(
        self,
        as_of: date | datetime | str | pd.Timestamp,
        series_ids: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """返回 ``as_of`` 当日可得的最新观测（点对点长表）。

        Args:
            as_of: 时点（含当日全部已发布信息）。
            series_ids: 过滤序列；默认全部序列。

        Returns:
            列 ``series_id, obs_date, value, release_time, source, unit`` 的长表，
            每个序列最多一行（最新可得观测）。
        """
        end_ts = as_of_timestamp(as_of)
        frame = self.obs
        if series_ids is not None:
            frame = frame[frame["series_id"].isin(list(series_ids))]
        frame = frame[frame["release_time"] <= end_ts]
        if frame.empty:
            return frame.loc[:, list(OBS_COLUMNS)].reset_index(drop=True)
        latest = frame.sort_values(["series_id", "obs_date", "release_time"]).groupby("series_id", as_index=False).tail(1)
        return latest.loc[:, list(OBS_COLUMNS)].sort_values("series_id").reset_index(drop=True)

    def asof_values(
        self,
        as_of: date | datetime | str | pd.Timestamp,
        series_ids: Iterable[str] | None = None,
    ) -> dict[str, float]:
        """返回 ``as_of`` 当日可得的最新值 ``{series_id: value}``（缺失序列不出现）。"""
        latest = self.asof_obs(as_of, series_ids)
        return {
            str(row.series_id): float(row.value)
            for row in latest.itertuples(index=False)
            if pd.notna(row.value)
        }

    def history(
        self,
        series_id: str,
        as_of: date | datetime | str | pd.Timestamp,
        lookback: int = 120,
    ) -> list[dict[str, Any]]:
        """返回截至 ``as_of`` 的序列历史 ``[{"date": date, "value": float}, ...]``。

        Args:
            series_id: 序列 ID。
            as_of: 截止时点。
            lookback: 最多返回的观测数量（取最近 ``lookback`` 条）。

        Returns:
            按日期升序的字典列表；未知序列返回空列表。
        """
        end_ts = as_of_timestamp(as_of)
        frame = self.obs[(self.obs["series_id"] == series_id) & (self.obs["release_time"] <= end_ts)]
        frame = frame.sort_values("obs_date").tail(max(int(lookback), 0))
        return [
            {"date": row.obs_date.date(), "value": float(row.value)}
            for row in frame.itertuples(index=False)
            if pd.notna(row.value)
        ]

    def snapshot_values(
        self, as_of: date | datetime | str | pd.Timestamp
    ) -> tuple[dict[str, float], list[str]]:
        """返回关键行情/资金快照及其缺失序列列表。"""
        series = self.asof_values(as_of, KEY_SNAPSHOT_SERIES)
        missing = [sid for sid in KEY_SNAPSHOT_SERIES if sid not in series]
        return series, missing

    def documents_asof(self, as_of: date | datetime | str | pd.Timestamp) -> pd.DataFrame:
        """返回 ``publish_time <= as_of 当日结束`` 的文档（时点过滤）。"""
        end_ts = as_of_timestamp(as_of)
        mask = self.documents["publish_time"] <= end_ts
        return self.documents.loc[mask].sort_values("publish_time").reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # 数据卡 / 覆盖期
    # ------------------------------------------------------------------ #
    def coverage(self) -> dict[str, tuple[date | None, date | None]]:
        """返回每个序列的覆盖期 ``{series_id: (start, end)}``。"""
        if self._coverage is not None:
            return self._coverage
        grouped = self.obs.dropna(subset=["value"]).groupby("series_id")["obs_date"]
        coverage: dict[str, tuple[date | None, date | None]] = {}
        for sid, values in grouped:
            coverage[str(sid)] = (values.min().date(), values.max().date())
        self._coverage = coverage
        return coverage

    def data_cards(self) -> list[DataCard]:
        """构造全部序列的数据卡（含覆盖期与 SYNTHETIC 标记）。"""
        return build_data_cards(self.coverage(), source=self.source)

    def series_meta(self, series_id: str) -> dict[str, Any]:
        """返回序列的目录元数据摘要（名称/域/单位/来源）。"""
        spec = SERIES_SPECS.get(series_id)
        start, end = self.coverage().get(series_id, (None, None))
        return {
            "series_id": series_id,
            "name": spec.name if spec else series_id,
            "domain": spec.domain if spec else "unknown",
            "unit": spec.unit if spec else series_unit(series_id),
            "source": self.source,
            "frequency": spec.frequency if spec else "daily",
            "coverage_start": start,
            "coverage_end": end,
        }

    # ------------------------------------------------------------------ #
    # 构造辅助
    # ------------------------------------------------------------------ #
    @classmethod
    def from_tables(
        cls,
        obs: pd.DataFrame,
        documents: pd.DataFrame,
        seed: int = 0,
        source: str = SYNTHETIC_SOURCE,
        meta: dict[str, Any] | None = None,
    ) -> "MarketDataset":
        """由观测长表与文档表构造数据集（供 PIT Store / 自定义适配器使用）。"""
        return cls(obs=obs, documents=documents, seed=seed, source=source, meta=dict(meta or {}))

    @classmethod
    def empty(cls, seed: int = 0, source: str = SYNTHETIC_SOURCE) -> "MarketDataset":
        """构造空数据集（无数据时的占位，保证 DataProvider 契约可用）。"""
        obs = pd.DataFrame(
            {
                "series_id": pd.Series(dtype=str),
                "obs_date": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype=float),
                "release_time": pd.Series(dtype="datetime64[ns]"),
                "source": pd.Series(dtype=str),
                "unit": pd.Series(dtype=str),
            }
        )
        documents = pd.DataFrame(
            {
                "doc_id": pd.Series(dtype=str),
                "publish_time": pd.Series(dtype="datetime64[ns]"),
                "source": pd.Series(dtype=str),
                "title": pd.Series(dtype=str),
                "body": pd.Series(dtype=str),
                "url": pd.Series(dtype=str),
                "hash": pd.Series(dtype=str),
            }
        )
        return cls(obs=obs, documents=documents, seed=seed, source=source)
