"""实时智能抓取层的内部契约（来源规格 / 抓取结果）。

设计目标：让「抓什么、从哪抓、怎么解析」全部由 ``configs/sources.yaml`` 描述，
运行时由 :mod:`cbr.ingest.sources` 按 ``kind`` 选择抓取器。抓取层只产出标准化的
观测行（``series_id, obs_date, value, release_time, source, unit``）与文档行，
落库/派生/时点语义统一交给 :class:`cbr.data.pit_store.PitStore` 处理。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

import pandas as pd

#: 观测行标准列（与 ``PitStore.series_obs`` 表一致）
OBS_COLUMNS: tuple[str, ...] = (
    "series_id",
    "obs_date",
    "value",
    "release_time",
    "source",
    "unit",
)
#: 文档行标准列（与 ``PitStore.documents`` 表一致）
DOC_COLUMNS: tuple[str, ...] = (
    "doc_id",
    "publish_time",
    "source",
    "title",
    "body",
    "url",
    "hash",
)


def empty_observations() -> pd.DataFrame:
    """返回空的观测行 DataFrame（含标准列）。"""
    return pd.DataFrame(columns=list(OBS_COLUMNS))


def empty_documents() -> pd.DataFrame:
    """返回空的文档行 DataFrame（含标准列）。"""
    return pd.DataFrame(columns=list(DOC_COLUMNS))


def doc_id_for(url: str | None, title: str, publish_time: datetime | str) -> str:
    """由 URL/标题/发布时间生成稳定的文档 ID（跨次抓取去重）。"""
    payload = f"{url or ''}|{title}|{publish_time}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:16]


def content_hash(title: str, body: str) -> str:
    """由标题+正文生成内容哈希（同文重复发布时去重）。"""
    return hashlib.sha256(f"{title}\n{body}".encode("utf-8")).hexdigest()[:32]


@dataclass
class SourceSpec:
    """单个抓取来源的声明式规格。

    Attributes:
        source_id: 来源唯一标识（``configs/sources.yaml`` 的 ``id``）。
        kind: 抓取器类型，见 :data:`cbr.ingest.sources.FETCHER_KINDS`。
        enabled: 是否启用（关闭后计划器不再为其分配任务）。
        series_ids: 该来源负责的规范序列 ID（派生序列不可抓取）。
        documents: 是否产出文本文档（新闻/语料）。
        interval_seconds: 该来源的建议抓取间隔（``None`` 表示沿用全局）。
        params: 抓取器专属参数（URL、列映射、时点假设等）。
    """

    source_id: str
    kind: str
    enabled: bool = True
    series_ids: tuple[str, ...] = ()
    documents: bool = False
    interval_seconds: int | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SourceSpec":
        """从 YAML 映射构造规格（键名宽松：``id`` 或 ``source_id``）。"""
        source_id = raw.get("id") or raw.get("source_id")
        if not source_id:
            raise ValueError("来源规格缺少 id")
        kind = raw.get("kind")
        if not kind:
            raise ValueError(f"来源 {source_id} 缺少 kind")
        series_ids = raw.get("series") or raw.get("series_ids") or []
        if isinstance(series_ids, str):
            series_ids = [series_ids]
        return cls(
            source_id=str(source_id),
            kind=str(kind),
            enabled=bool(raw.get("enabled", True)),
            series_ids=tuple(str(s) for s in series_ids),
            documents=bool(raw.get("documents", False)),
            interval_seconds=(
                int(raw["interval_seconds"]) if raw.get("interval_seconds") is not None else None
            ),
            params=dict(raw.get("params") or {}),
        )

    def series_for(self, series_id: str) -> bool:
        """判断该来源是否负责指定序列。"""
        return series_id in self.series_ids


@dataclass
class FetchResult:
    """单个来源一次抓取的结果。

    Attributes:
        source_id: 来源标识。
        status: ``ok`` / ``empty`` / ``error`` / ``skipped``。
        observations: 标准化观测行。
        documents: 标准化文档行。
        error: 失败原因（``status == "error"`` 时）。
        latency_ms: 抓取耗时（毫秒）。
        fetched_at: 抓取时间（UTC）。
    """

    source_id: str
    status: str = "ok"
    observations: pd.DataFrame = field(default_factory=empty_observations)
    documents: pd.DataFrame = field(default_factory=empty_documents)
    error: str | None = None
    latency_ms: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def ok(self) -> bool:
        """抓取是否成功（``ok`` 或 ``empty`` 都算成功执行）。"""
        return self.status in ("ok", "empty")

    def as_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的摘要（不含原始数据）。"""
        return {
            "source_id": self.source_id,
            "status": self.status,
            "n_observations": int(len(self.observations)),
            "n_documents": int(len(self.documents)),
            "error": self.error,
            "latency_ms": self.latency_ms,
            "fetched_at": self.fetched_at.isoformat(),
        }


class Fetcher(Protocol):
    """抓取器协议：给定时间窗，返回标准化观测/文档。"""

    spec: SourceSpec

    def fetch(
        self,
        *,
        since: date | None,
        until: date,
        series_ids: tuple[str, ...] | None = None,
    ) -> FetchResult:
        """抓取 ``since``（含）到 ``until``（含）之间的数据。"""
        ...
