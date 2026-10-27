"""抓取器实现与注册表（按 ``kind`` 选择）。

支持的抓取器 ``kind``：

- ``http_csv``：公开 CSV 端点（如 CBOE VIX 历史），列映射可配置；
- ``http_json``：返回 JSON 列表的端点（如东财 push2his kline），支持字典行或分隔字符串行；
- ``akshare``：通过 ``akshare`` 调用的公开接口（未安装时状态为 ``skipped``，不影响其它来源）；
- ``rss``：RSS/Atom 新闻源，产出文本文档。

所有抓取器都只产出**标准化的观测/文档行**，不做插值、不伪造缺失值；时点（``release_time``）
按来源声明的保守假设（``release_lag_days`` + ``publish_hour`` + ``tz_offset``）计算。
"""

from __future__ import annotations

import io
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd
import requests

from cbr.config import AppSettings, load_settings

from .contracts import (
    FetchResult,
    SourceSpec,
    content_hash,
    doc_id_for,
    empty_documents,
    empty_observations,
)

logger = logging.getLogger(__name__)

#: 支持的抓取器类型
FETCHER_KINDS: tuple[str, ...] = ("http_csv", "http_json", "akshare", "rss")


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _release_time(
    obs_date: Any,
    lag_days: int,
    hour: int,
    minute: int,
    tz_offset: str,
) -> pd.Timestamp | None:
    """把观测日转换为带时区的可得时点（``obs_date + lag`` 的 ``hour:minute``）。"""
    ts = pd.to_datetime(obs_date, errors="coerce")
    if ts is pd.NaT or pd.isna(ts):
        return None
    ts = (ts.normalize() + pd.Timedelta(days=int(lag_days))).replace(
        hour=int(hour), minute=int(minute), second=0, microsecond=0
    )
    return ts.tz_localize(tz_offset)


def _http_get(url: str, params: dict[str, Any], settings: AppSettings) -> str:
    """带重试与统一 UA 的 HTTP GET（返回文本）。"""
    headers = {"User-Agent": settings.ingest.user_agent}
    headers.update(params.get("headers") or {})
    query = params.get("query") or {}
    attempts = max(1, settings.ingest.http_retries + 1)
    last: Exception | None = None
    for index in range(attempts):
        try:
            resp = requests.get(
                url,
                headers=headers,
                params=query or None,
                timeout=settings.ingest.http_timeout_seconds,
            )
            resp.raise_for_status()
            resp.encoding = params.get("encoding") or resp.encoding or "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001 - 公开接口不稳定，重试后上抛
            last = exc
            if index + 1 < attempts:
                time.sleep(1.0 * (index + 1))
    raise RuntimeError(f"HTTP 抓取失败: {type(last).__name__}: {last}") from last


def _within(frame: pd.DataFrame, since: date | None, until: date) -> pd.DataFrame:
    """按观测日窗口过滤（``since`` 为空表示不限下界）。"""
    if frame.empty:
        return frame
    obs = pd.to_datetime(frame["obs_date"])
    mask = obs <= pd.Timestamp(until)
    if since is not None:
        mask &= obs >= pd.Timestamp(since)
    return frame.loc[mask].reset_index(drop=True)


class _BaseFetcher:
    """抓取器基类：保存规格与配置，缓存 ``series_id`` 等公共参数。"""

    def __init__(self, spec: SourceSpec, settings: AppSettings | None = None) -> None:
        self.spec = spec
        self.settings = settings or load_settings()
        self.params = spec.params

    # -- 公共参数读取 ----------------------------------------------------- #
    def _series_id(self, override: tuple[str, ...] | None = None) -> str:
        ids = override or self.spec.series_ids
        if not ids:
            raise ValueError(f"来源 {self.spec.source_id} 未声明 series")
        return str(ids[0])

    def _lag(self) -> int:
        return int(self.params.get("release_lag_days", 0))

    def _publish(self) -> tuple[int, int, str]:
        return (
            int(self.params.get("publish_hour", 18)),
            int(self.params.get("publish_minute", 0)),
            str(self.params.get("tz_offset", "+08:00")),
        )

    def _unit(self) -> str | None:
        return self.params.get("unit")

    def _source_name(self) -> str:
        return str(self.params.get("source") or self.spec.source_id)

    def _make_observations(
        self,
        dates: pd.Series,
        values: pd.Series,
        series_id: str,
    ) -> pd.DataFrame:
        """把 (日期, 数值) 序列标准化为观测行。"""
        frame = pd.DataFrame(
            {
                "series_id": series_id,
                "obs_date": pd.to_datetime(dates, errors="coerce").dt.date,
                "value": pd.to_numeric(values, errors="coerce"),
            }
        )
        scale = float(self.params.get("value_scale", 1.0))
        if scale != 1.0:
            frame["value"] = frame["value"] * scale
        hour, minute, tz = self._publish()
        lag = self._lag()
        frame["release_time"] = [
            _release_time(d, lag, hour, minute, tz) for d in frame["obs_date"]
        ]
        frame["source"] = self._source_name()
        frame["unit"] = self._unit()
        frame = frame.dropna(subset=["obs_date", "value", "release_time"])
        frame = frame.drop_duplicates(subset=["series_id", "obs_date"], keep="last")
        return frame.loc[:, list(empty_observations().columns)]


# --------------------------------------------------------------------------- #
# HTTP CSV
# --------------------------------------------------------------------------- #
class HttpCsvFetcher(_BaseFetcher):
    """公开 CSV 端点抓取器（列名/格式可配置）。"""

    def fetch(
        self,
        *,
        since: date | None,
        until: date,
        series_ids: tuple[str, ...] | None = None,
    ) -> FetchResult:
        started = time.time()
        series_id = self._series_id(series_ids)
        try:
            url = str(self.params["url"]).format(
                start=pd.Timestamp(since or until).strftime("%Y%m%d"),
                end=pd.Timestamp(until).strftime("%Y%m%d"),
            )
            text = _http_get(url, self.params, self.settings)
            frame = pd.read_csv(
                io.StringIO(text),
                sep=str(self.params.get("sep", ",")),
                skiprows=int(self.params.get("skiprows", 0)),
            )
            dates = frame[self.params["date_column"]]
            values = frame[self.params["value_column"]]
            date_format = self.params.get("date_format")
            if date_format:
                dates = pd.to_datetime(dates, format=str(date_format), errors="coerce")
            observations = self._make_observations(dates, values, series_id)
            observations = _within(observations, since, until)
            status = "ok" if len(observations) else "empty"
            return FetchResult(
                source_id=self.spec.source_id,
                status=status,
                observations=observations,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 单来源失败不影响整体
            logger.warning("来源 %s 抓取失败: %s", self.spec.source_id, exc)
            return FetchResult(
                source_id=self.spec.source_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - started) * 1000),
            )


# --------------------------------------------------------------------------- #
# HTTP JSON（列表型端点）
# --------------------------------------------------------------------------- #
def _dig(payload: Any, path: str | None) -> Any:
    """按点分路径取嵌套字段（``a.b.c``）；``None`` 表示取顶层。"""
    if not path:
        return payload
    current = payload
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


class HttpJsonFetcher(_BaseFetcher):
    """JSON 列表端点抓取器。

    行可为字典（用 ``date_field`` / ``value_field`` 取字段），也可为分隔字符串
    （配置 ``row_split`` 后用整数下标取字段，如东财 kline 的 ``"日期,开,收,高,低,..."``）。
    """

    def fetch(
        self,
        *,
        since: date | None,
        until: date,
        series_ids: tuple[str, ...] | None = None,
    ) -> FetchResult:
        started = time.time()
        series_id = self._series_id(series_ids)
        try:
            url = str(self.params["url"]).format(
                start=pd.Timestamp(since or until).strftime("%Y%m%d"),
                end=pd.Timestamp(until).strftime("%Y%m%d"),
            )
            raw = _http_get(url, self.params, self.settings)
            payload = json.loads(raw)
            rows = _dig(payload, self.params.get("rows_path")) or []
            if not rows:
                return FetchResult(
                    source_id=self.spec.source_id,
                    status="empty",
                    latency_ms=int((time.time() - started) * 1000),
                )
            date_field = self.params.get("date_field", "date")
            value_field = self.params.get("value_field", "value")
            row_split = self.params.get("row_split")

            def _field(row: Any, field: Any) -> Any:
                """取字段：字典行按键，列表/元组行按整数下标，字符串行按分隔符切分。"""
                if isinstance(row, dict):
                    return row.get(field)
                if isinstance(row, (list, tuple)):
                    return row[int(field)]
                text = str(row)
                return text.split(str(row_split))[int(field)] if row_split else text

            dates = [_field(r, date_field) for r in rows]
            values = [_field(r, value_field) for r in rows]
            date_format = self.params.get("date_format")
            dates_series = pd.Series(dates)
            if date_format:
                dates_series = pd.to_datetime(dates_series, format=str(date_format), errors="coerce")
            observations = self._make_observations(dates_series, pd.Series(values), series_id)
            observations = _within(observations, since, until)
            return FetchResult(
                source_id=self.spec.source_id,
                status="ok" if len(observations) else "empty",
                observations=observations,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("来源 %s 抓取失败: %s", self.spec.source_id, exc)
            return FetchResult(
                source_id=self.spec.source_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - started) * 1000),
            )


# --------------------------------------------------------------------------- #
# akshare（可选依赖）
# --------------------------------------------------------------------------- #
class AkshareFetcher(_BaseFetcher):
    """通过 ``akshare`` 调用的公开接口抓取器（未安装时跳过）。"""

    def fetch(
        self,
        *,
        since: date | None,
        until: date,
        series_ids: tuple[str, ...] | None = None,
    ) -> FetchResult:
        started = time.time()
        series_id = self._series_id(series_ids)
        try:
            import akshare as ak  # noqa: PLC0415 - 可选依赖，延迟导入
        except ImportError:
            return FetchResult(
                source_id=self.spec.source_id,
                status="skipped",
                error="akshare 未安装（pip install akshare）",
                latency_ms=0,
            )
        try:
            func_name = str(self.params["func"])
            func: Callable[..., pd.DataFrame] = getattr(ak, func_name)
            frame = func(**(self.params.get("kwargs") or {}))
            if frame is None or len(frame) == 0:
                return FetchResult(
                    source_id=self.spec.source_id,
                    status="empty",
                    latency_ms=int((time.time() - started) * 1000),
                )
            dates = frame[self.params["date_column"]]
            values = frame[self.params["value_column"]]
            date_format = self.params.get("date_format")
            if date_format:
                dates = pd.to_datetime(dates, format=str(date_format), errors="coerce")
            observations = self._make_observations(dates, values, series_id)
            observations = _within(observations, since, until)
            return FetchResult(
                source_id=self.spec.source_id,
                status="ok" if len(observations) else "empty",
                observations=observations,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("akshare 来源 %s 抓取失败: %s", self.spec.source_id, exc)
            return FetchResult(
                source_id=self.spec.source_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - started) * 1000),
            )


# --------------------------------------------------------------------------- #
# RSS / Atom 新闻源
# --------------------------------------------------------------------------- #
def _strip_ns(tag: str) -> str:
    """去掉 XML 标签的命名空间前缀。"""
    return tag.split("}", 1)[1] if "}" in tag else tag


class RssFetcher(_BaseFetcher):
    """RSS / Atom 新闻源抓取器，产出文本文档（不产出数值观测）。"""

    def fetch(
        self,
        *,
        since: date | None,
        until: date,
        series_ids: tuple[str, ...] | None = None,
    ) -> FetchResult:
        started = time.time()
        try:
            url = str(self.params["url"]).format(
                start=pd.Timestamp(since or until).strftime("%Y%m%d"),
                end=pd.Timestamp(until).strftime("%Y%m%d"),
            )
            text = _http_get(url, self.params, self.settings)
            text = text.lstrip("\ufeff").strip()  # 去掉可能的 UTF-8 BOM
            root = ET.fromstring(text)  # noqa: S314 - 受信任的来源配置
            source_name = self._source_name()
            limit = int(self.params.get("limit", 200))
            records: list[dict[str, Any]] = []
            for node in list(root.iter()):
                if _strip_ns(node.tag) not in ("item", "entry"):
                    continue
                fields: dict[str, str] = {}
                link = ""
                for child in node:
                    name = _strip_ns(child.tag)
                    value = (child.text or "").strip()
                    if name == "link" and not value:
                        value = str(child.attrib.get("href") or "").strip()
                    fields[name] = value
                    if name == "link":
                        link = value
                title = fields.get("title", "")
                body = fields.get("description") or fields.get("summary") or fields.get("content") or ""
                published = (
                    fields.get("pubDate") or fields.get("published") or fields.get("updated") or ""
                )
                publish_ts = pd.to_datetime(published, errors="coerce", utc=True)
                if pd.isna(publish_ts):
                    publish_ts = pd.Timestamp.utcnow()
                if not title:
                    continue
                records.append(
                    {
                        "doc_id": doc_id_for(link, title, publish_ts.isoformat()),
                        "publish_time": publish_ts.tz_convert("Asia/Shanghai").tz_localize(None),
                        "source": source_name,
                        "title": title,
                        "body": body,
                        "url": link or None,
                        "hash": content_hash(title, body),
                    }
                )
            frame = pd.DataFrame(records, columns=list(empty_documents().columns))
            if not frame.empty:
                mask = frame["publish_time"] <= pd.Timestamp(until) + pd.Timedelta(days=1)
                if since is not None:
                    mask &= frame["publish_time"] >= pd.Timestamp(since)
                frame = frame.loc[mask].head(limit).reset_index(drop=True)
            return FetchResult(
                source_id=self.spec.source_id,
                status="ok" if len(frame) else "empty",
                documents=frame if not frame.empty else empty_documents(),
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RSS 来源 %s 抓取失败: %s", self.spec.source_id, exc)
            return FetchResult(
                source_id=self.spec.source_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.time() - started) * 1000),
            )


#: kind -> 抓取器类
_FETCHERS: dict[str, type[_BaseFetcher]] = {
    "http_csv": HttpCsvFetcher,
    "http_json": HttpJsonFetcher,
    "akshare": AkshareFetcher,
    "rss": RssFetcher,
}


def build_fetcher(spec: SourceSpec, settings: AppSettings | None = None) -> _BaseFetcher:
    """按 ``spec.kind`` 构造抓取器；未知 kind 报错。"""
    try:
        cls = _FETCHERS[spec.kind]
    except KeyError as exc:
        raise ValueError(
            f"未知抓取器 kind={spec.kind!r}（来源 {spec.source_id}）；可选：{', '.join(FETCHER_KINDS)}"
        ) from exc
    return cls(spec, settings)
