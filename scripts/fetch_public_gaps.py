#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""CBR-MAW 公开数据补齐：抓取用户自建数据集中缺失的关键系统序列。

本脚本只负责“把公开可访问的原始接口取回、清洗、加上时点（PIT）列、落成
长表 CSV”，供 ``data/custom`` 接入流程使用；不改动 ``src/`` 与 ``configs/``。

输出
----
``data/raw/public/<series_id>.csv``（每序列一个文件）+ ``data/raw/public/manifest.json``。
CSV 列固定为::

    series_id,date,value,unit,frequency,source,source_url,publish_ts,fetch_ts,version

- ``date``：观测日（日频=交易日；月频=该月最后一个自然日，与项目
  ``data/samples/macro_monthly.csv`` 的 ``obs_date`` 口径一致）。
- ``publish_ts``：**保守可得时点**（见下表 ``PIT`` 列），带 ``+08:00`` 偏移；
  下游做点时特征时用 ``publish_ts <= t`` 过滤即可，不要用 ``date`` 过滤。
- ``version``：数据版本 / vintage 标记，当前 ``v1``（这些序列无修订）。

覆盖序列与数据源
----------------
=============================== ====== ============ ==========================================
series_id                       频率   单位         主源 -> 备源
=============================== ====== ============ ==========================================
market.cn_bond.cgb_10y          日     %            东财数据中心 -> 中债（chinabond）国债曲线
rates.credit.aa_spread          日     bp           中债 中票AAA 5Y − 国债 5Y
macro.pmi.manufacturing         月     点           东财数据中心（统计局口径）
market.global.sp500             日     点           东财 push2his（100.SPX）-> 腾讯（us.INX）
crossborder.flows.ah_premium    日     点           东财 push2his（100.HSAHP）-> 同花顺
market.cn_equity.csi500         日     点           东财 push2his（1.000905）-> 中证指数官网 -> 腾讯
market.cn_equity.turnover       日     亿元         东财 push2his（沪综指+深综指成交额）-> 腾讯
=============================== ====== ============ ==========================================

PIT 假设（保守）
---------------
- 日频（A 股/中债/港股）：观测日当日 18:00 +08:00。理由：A 股 15:00 收盘、港股 16:00
  收盘、中债估值曲线约 17:30 发布，18:00 为留足余量的保守时点。
- ``market.global.sp500``：观测日 **次日 09:00 +08:00**。美股 16:00 ET 收盘对应北京时间
  次日 04:00（夏令时）/05:00（冬令时），若按当日 18:00 标记会引入前视偏差。
- 月频（PMI）：**次月首个交易日 09:00 +08:00**。统计局实际在月末最后一日 09:30 发布，
  故该标记偏保守（最多晚约 1 个交易日，遇长假更晚），不会泄漏未来信息。

用法
----
.. code-block:: powershell

    .\.venv\Scripts\python.exe scripts\fetch_public_gaps.py            # 全量
    .\.venv\Scripts\python.exe scripts\fetch_public_gaps.py --only market.cn_bond.cgb_10y
    .\.venv\Scripts\python.exe scripts\fetch_public_gaps.py --start 2015-01-01

依赖：``requests``、``pandas``、``lxml``（``pd.read_html`` 解析中债 HTML 表格）。
不需要 akshare / yfinance；所有接口均为公开、免 key。
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlsplit

import pandas as pd
import requests

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
CST = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "raw" / "public"
DEFAULT_START = date(2015, 1, 1)
VERSION = "v1"

OUT_COLUMNS = [
    "series_id",
    "date",
    "value",
    "unit",
    "frequency",
    "source",
    "source_url",
    "publish_ts",
    "fetch_ts",
    "version",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: 东方财富 push2his 日 K 线
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8"
EM_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64"
#: 东方财富数据中心（美国/中国国债收益率）
EM_DATACENTER_URL = "https://datacenter.eastmoney.com/api/data/get"
EM_DATACENTER_TOKEN = "894050c76af8597a853f5b408b759f5d"
#: 东方财富数据中心 v1（PMI 等宏观）
EM_DATACENTER_V1_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
#: 中债收益率曲线（中国债券信息网）
CHINABOND_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
#: 中证指数官网（历史行情 JSON）
CSINDEX_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
#: 腾讯行情（日 K 线，可按 end 日期向前翻页）
TENCENT_KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
#: 同花顺（日线，JSONP）
THS_LINE_URL = "https://d.10jqka.com.cn/v6/line/{symbol}/01/all.js"


# --------------------------------------------------------------------------- #
# HTTP 客户端：按 host 限速 + 指数退避重试
# --------------------------------------------------------------------------- #
class FetchError(RuntimeError):
    """抓取失败（网络/接口返回异常/数据为空）。"""


class HttpClient:
    """带超时、限速与重试的极简 HTTP 客户端。

    Args:
        min_interval: 同一 host 两次请求的最小间隔（秒），避免触发风控。
        timeout: 单次请求超时（秒）。
        retries: 失败重试次数（含首次）。
    """

    def __init__(self, min_interval: float = 1.2, timeout: float = 45.0, retries: int = 3) -> None:
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        self._last_hit: dict[str, float] = {}
        self.calls: list[dict[str, str]] = []

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)

    def get(
        self,
        url: str,
        params: dict | None = None,
        *,
        headers: dict | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> requests.Response:
        """GET 一个 URL，失败时指数退避重试；最终仍失败则抛 :class:`FetchError`。"""
        host = urlsplit(url).netloc
        attempts = retries or self.retries
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._throttle(host)
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=timeout or self.timeout
                )
                self._last_hit[host] = time.monotonic()
                if resp.status_code >= 500:
                    raise FetchError(f"HTTP {resp.status_code} from {host}")
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} from {host}")
                self.calls.append({"host": host, "url": resp.url, "status": str(resp.status_code)})
                return resp
            except (requests.RequestException, FetchError) as exc:  # noqa: PERF203
                last_exc = exc
                self._last_hit[host] = time.monotonic()
                if attempt < attempts:
                    time.sleep(min(2.0 * attempt, 8.0))
        raise FetchError(f"{host} 请求失败（{attempts} 次）：{last_exc}")


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Fetched:
    """单个 provider 的抓取结果。"""

    frame: pd.DataFrame  # 列：date(datetime64)、value(float)
    source: str
    source_url: str
    detail: str = ""


@dataclass
class Provider:
    """一个数据源实现（主源或备源）。"""

    name: str
    source: str
    url: str
    fn: Callable[["HttpClient", date, date], Fetched]


@dataclass
class SeriesJob:
    """一条待补齐序列的抓取与校验规格。"""

    series_id: str
    name: str
    unit: str
    frequency: str  # daily | monthly
    pit: str  # close_1800_cst | next_day_0900_cst | next_trading_day_0900_cst
    providers: tuple[Provider, ...]
    min_rows: int
    value_range: tuple[float, float]
    max_gap_days: int
    sanity: tuple[tuple[str, Callable[[pd.DataFrame], tuple[bool, str]]], ...] = ()
    notes: str = ""
    required: bool = True
    start_tolerance_days: int = 15
    freshness_days: int = 10


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _norm_frame(df: pd.DataFrame, date_col: str, value_col: str) -> pd.DataFrame:
    """统一成 ``date``(datetime64) + ``value``(float) 两列，去空、去重、排序。"""
    if date_col not in df.columns or value_col not in df.columns:
        raise FetchError(f"缺少列：{date_col}/{value_col}（实际列 {list(df.columns)}）")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce").dt.normalize(),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["date", "value"])
    out = out[out["value"].map(lambda x: x == x and abs(x) != float("inf"))]
    out = out.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return out.reset_index(drop=True)


def _slice_window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end)
    return df[(df["date"] >= lo) & (df["date"] <= hi)].reset_index(drop=True)


def _jsonp_to_json(text: str) -> dict:
    """把 ``callback({...})`` / ``var x({...})`` 形式的 JSONP 解成 dict。"""
    match = re.search(r"\((\{.*\})\)", text, re.S)
    if not match:
        raise FetchError("JSONP 解析失败")
    return json.loads(match.group(1))


# --------------------------------------------------------------------------- #
# Provider：东方财富 push2his 日 K 线
# --------------------------------------------------------------------------- #
def em_kline(client: HttpClient, secid: str) -> pd.DataFrame:
    """取东方财富 push2his 日 K 线全量（含 open/close/high/low/volume/amount）。

    注意：``lmt`` 必须与 ``end`` 同时给出，否则接口返回 ``rc=102``（空数据）。
    """
    resp = client.get(
        EM_KLINE_URL,
        params={
            "secid": secid,
            "klt": "101",  # 日线
            "fqt": "0",  # 不复权（指数无需复权）
            "lmt": "10000",
            "end": "20500000",
            "fields1": EM_FIELDS1,
            "fields2": EM_FIELDS2,
        },
        headers={"Referer": "https://quote.eastmoney.com/"},
        timeout=40,
    )
    payload = resp.json()
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        raise FetchError(f"东财 K 线为空 rc={payload.get('rc')} secid={secid}")
    rows = [line.split(",") for line in klines]
    df = pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "open": pd.to_numeric([r[1] for r in rows], errors="coerce"),
            "close": pd.to_numeric([r[2] for r in rows], errors="coerce"),
            "high": pd.to_numeric([r[3] for r in rows], errors="coerce"),
            "low": pd.to_numeric([r[4] for r in rows], errors="coerce"),
            "volume": pd.to_numeric([r[5] for r in rows], errors="coerce"),
            "amount": pd.to_numeric([r[6] for r in rows], errors="coerce"),
        }
    )
    df.attrs["name"] = data.get("name")
    return df


def _em_close_provider(name: str, secid: str, tag: str) -> Provider:
    """构造“东财 K 线收盘价”provider。"""

    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        raw = em_kline(client, secid)
        df = _norm_frame(raw, "date", "close")
        df = _slice_window(df, start, end)
        return Fetched(
            frame=df,
            source=tag,
            source_url=EM_KLINE_URL,
            detail=f"secid={secid}, name={raw.attrs.get('name')}",
        )

    return Provider(name=name, source=tag, url=EM_KLINE_URL, fn=_fn)


# --------------------------------------------------------------------------- #
# Provider：腾讯行情（可按 end 日期向前翻页，每页 640 根）
# --------------------------------------------------------------------------- #
TENCENT_PAGE = 640


def tencent_kline(
    client: HttpClient, code: str, start: date, end: date, max_pages: int = 30
) -> pd.DataFrame:
    """抓取腾讯日 K 线：``param=code,day,,<end>,640,qfq``，逐页向前回溯。

    返回列：``date/open/close/high/low/volume/amount_wan``（amount 单位：万元）。
    """
    records: list[dict] = []
    cursor = ""  # 空表示最新一页
    for _ in range(max_pages):
        resp = client.get(
            TENCENT_KLINE_URL,
            params={"param": f"{code},day,,{cursor},{TENCENT_PAGE},qfq"},
            headers={"Referer": "https://gu.qq.com/"},
            timeout=40,
        )
        payload = resp.json()
        node = (payload.get("data") or {}).get(code) or {}
        rows = node.get("qfqday") or node.get("day") or []
        if not rows:
            break
        for row in rows:
            records.append(
                {
                    "date": row[0],
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]) if row[5] not in ("", None) else float("nan"),
                    # 腾讯成交额字段单位为“万元”
                    "amount_wan": float(row[8]) if len(row) > 8 and row[8] not in ("", None) else float("nan"),
                }
            )
        oldest = pd.Timestamp(rows[0][0])
        if oldest.date() <= start:
            break
        cursor = (oldest - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    if not records:
        raise FetchError(f"腾讯 K 线为空 code={code}")
    df = pd.DataFrame(records).drop_duplicates(subset=["date"], keep="first")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def _tencent_close_provider(name: str, code: str) -> Provider:
    """构造“腾讯收盘价”provider。"""

    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        raw = tencent_kline(client, code, start, end)
        df = _norm_frame(raw, "date", "close")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="tencent-finance", source_url=TENCENT_KLINE_URL,
                       detail=f"code={code}")

    return Provider(name=name, source="tencent-finance", url=TENCENT_KLINE_URL, fn=_fn)


# --------------------------------------------------------------------------- #
# Provider：中国 10 年期国债收益率（东方财富数据中心 / 中债）
# --------------------------------------------------------------------------- #
def em_cgb_yields(client: HttpClient, start: date, end: date) -> pd.DataFrame:
    """东财数据中心「中美国债收益率」：逐页回溯到 ``start``。

    字段：``EMM00166466`` = 中国国债收益率10年（%），``EMM00588704`` = 2年。
    """
    page_size = 500
    frames: list[pd.DataFrame] = []
    for page in range(1, 21):  # 2015 至今约 6~7 页，上限 20 页足够
        resp = client.get(
            EM_DATACENTER_URL,
            params={
                "type": "RPTA_WEB_TREASURYYIELD",
                "sty": "ALL",
                "st": "SOLAR_DATE",
                "sr": "-1",
                "token": EM_DATACENTER_TOKEN,
                "p": str(page),
                "ps": str(page_size),
                "pageNo": str(page),
                "pageNum": str(page),
            },
            timeout=40,
        )
        payload = resp.json()
        result = payload.get("result") or {}
        rows = result.get("data") or []
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        oldest = pd.Timestamp(str(rows[-1]["SOLAR_DATE"])[:10])
        if oldest.date() <= start:
            break
    if not frames:
        raise FetchError("东财中美国债收益率接口返回为空")
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["SOLAR_DATE"])
    raw = raw.rename(columns={"SOLAR_DATE": "date", "EMM00166466": "cgb_10y", "EMM00588704": "cgb_2y"})
    for col in ("cgb_10y", "cgb_2y"):
        if col not in raw.columns:
            raise FetchError(f"东财国债收益率缺少字段 {col}")
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.normalize()
    return raw.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Provider：中债收益率曲线（中国债券信息网）
# --------------------------------------------------------------------------- #
CURVE_GOV = "中债国债收益率曲线"
CURVE_MT_AAA = "中短期票据收益率曲线(AAA)"


def chinabond_curves(client: HttpClient, start: date, end: date) -> dict[str, pd.DataFrame]:
    """按年分片抓取中债收益率曲线（一次请求区间需 < 1 年，长区间会返回空表）。

    Returns:
        ``{"gov": DataFrame(date, 10年, 5年), "mt_aaa": DataFrame(date, 5年, 10年)}``
    """
    gov_frames: list[pd.DataFrame] = []
    mt_frames: list[pd.DataFrame] = []
    year = start.year
    while year <= end.year:
        lo = max(date(year, 1, 1), start)
        hi = min(date(year, 12, 31), end)
        resp = client.get(
            CHINABOND_URL,
            params={
                "startDate": lo.strftime("%Y-%m-%d"),
                "endDate": hi.strftime("%Y-%m-%d"),
                "gjqx": "0",
                "qxId": "ycqx",
                "locale": "cn_ZH",
            },
            headers={"Referer": "https://yield.chinabond.com.cn/"},
            timeout=120,
            retries=4,
        )
        tables = pd.read_html(io.StringIO(resp.text.replace("&nbsp", "")), header=0)
        target = None
        for table in tables:
            if "曲线名称" in table.columns and len(table) > 0:
                target = table
                break
        if target is None:
            raise FetchError(f"中债 {year} 年返回表中未找到收益率曲线数据")
        target = target.copy()
        target["日期"] = pd.to_datetime(target["日期"], errors="coerce").dt.normalize()
        for curve_name, bucket in ((CURVE_GOV, gov_frames), (CURVE_MT_AAA, mt_frames)):
            sub = target[target["曲线名称"].astype(str).str.contains(curve_name, regex=False)]
            if sub.empty:
                continue
            keep = ["日期"] + [c for c in ("5年", "10年") if c in sub.columns]
            bucket.append(sub[keep].rename(columns={"日期": "date"}))
        year += 1
    if not gov_frames:
        raise FetchError("中债国债收益率曲线未取到数据")
    gov = pd.concat(gov_frames, ignore_index=True)
    gov = gov.assign(date=pd.to_datetime(gov["date"], errors="coerce").dt.normalize())
    for col in ("5年", "10年"):
        if col in gov.columns:
            gov[col] = pd.to_numeric(gov[col], errors="coerce")
    gov = gov.dropna(subset=["date"]).drop_duplicates(subset=["date"]).sort_values("date")
    mt = pd.DataFrame()
    if mt_frames:
        mt = pd.concat(mt_frames, ignore_index=True)
        mt = mt.assign(date=pd.to_datetime(mt["date"], errors="coerce").dt.normalize())
        if "5年" in mt.columns:
            mt["5年"] = pd.to_numeric(mt["5年"], errors="coerce")
        mt = mt.dropna(subset=["date"]).drop_duplicates(subset=["date"]).sort_values("date")
    return {"gov": gov.reset_index(drop=True), "mt_aaa": mt.reset_index(drop=True)}


# --------------------------------------------------------------------------- #
# Provider：中证指数官网
# --------------------------------------------------------------------------- #
def csindex_history(client: HttpClient, index_code: str, start: date, end: date) -> pd.DataFrame:
    """中证指数官网历史行情（免 key，含 close/open/high/low/tradingValue）。"""
    resp = client.get(
        CSINDEX_URL,
        params={
            "indexCode": index_code,
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
        },
        headers={"Referer": "https://www.csindex.com.cn/"},
        timeout=60,
    )
    payload = resp.json()
    rows = payload.get("data") or []
    if not rows:
        raise FetchError(f"中证指数 {index_code} 返回为空：{str(payload)[:160]}")
    df = pd.DataFrame(rows).rename(columns={"tradeDate": "date"})
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Provider：同花顺日线（JSONP）
# --------------------------------------------------------------------------- #
def ths_daily(client: HttpClient, symbol: str, start: date, end: date) -> pd.DataFrame:
    """同花顺日线全量：``date,open,high,low,close,volume,...``。"""
    resp = client.get(
        THS_LINE_URL.format(symbol=symbol),
        headers={"Referer": "https://stockpage.10jqka.com.cn/"},
        timeout=60,
    )
    payload = _jsonp_to_json(resp.text)
    raw = payload.get("data") or ""
    records = []
    for item in raw.split(";"):
        parts = item.split(",")
        if len(parts) < 5:
            continue
        records.append({"date": parts[0], "open": parts[1], "high": parts[2],
                        "low": parts[3], "close": parts[4], "volume": parts[5] if len(parts) > 5 else ""})
    if not records:
        raise FetchError(f"同花顺 {symbol} 日线为空")
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.attrs["name"] = payload.get("name")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 各序列的 provider 组装
# --------------------------------------------------------------------------- #
def _provider_cgb_em() -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        raw = em_cgb_yields(client, start, end)
        df = _norm_frame(raw, "date", "cgb_10y")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="eastmoney-datacenter", source_url=EM_DATACENTER_URL,
                       detail="RPTA_WEB_TREASURYYIELD / EMM00166466（中国国债收益率10年）")

    return Provider("eastmoney-datacenter", "eastmoney-datacenter", EM_DATACENTER_URL, _fn)


def _provider_cgb_chinabond(shared: dict) -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        curves = shared.get("chinabond") or chinabond_curves(client, start, end)
        shared["chinabond"] = curves
        gov = curves["gov"]
        if "10年" not in gov.columns:
            raise FetchError("中债国债曲线缺少 10年 列")
        df = _norm_frame(gov, "date", "10年")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="chinabond", source_url=CHINABOND_URL,
                       detail="中债国债收益率曲线 10年（%）")

    return Provider("chinabond", "chinabond", CHINABOND_URL, _fn)


def _provider_aa_spread(shared: dict) -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        curves = shared.get("chinabond") or chinabond_curves(client, start, end)
        shared["chinabond"] = curves
        gov, mt = curves["gov"], curves["mt_aaa"]
        if mt.empty or "5年" not in mt.columns:
            raise FetchError("中债中短期票据 AAA 曲线未取到 5年 数据")
        merged = gov[["date", "5年"]].rename(columns={"5年": "gov_5y"}).merge(
            mt[["date", "5年"]].rename(columns={"5年": "mt_aaa_5y"}), on="date", how="inner"
        )
        merged["value"] = (merged["mt_aaa_5y"] - merged["gov_5y"]) * 100.0  # % -> bp
        df = _norm_frame(merged, "date", "value")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="chinabond", source_url=CHINABOND_URL,
                       detail="中债中短期票据收益率曲线(AAA) 5年 − 中债国债收益率曲线 5年，×100 转 bp")

    return Provider("chinabond", "chinabond", CHINABOND_URL, _fn)


def _provider_pmi_em() -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        resp = client.get(
            EM_DATACENTER_V1_URL,
            params={
                "columns": "REPORT_DATE,TIME,MAKE_INDEX,MAKE_SAME,NMAKE_INDEX,NMAKE_SAME",
                "pageNumber": "1",
                "pageSize": "2000",
                "sortColumns": "REPORT_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB",
                "reportName": "RPT_ECONOMY_PMI",
                "p": "1",
                "pageNo": "1",
                "pageNum": "1",
            },
            timeout=40,
        )
        rows = (resp.json().get("result") or {}).get("data") or []
        if not rows:
            raise FetchError("东财 PMI 接口返回为空")
        raw = pd.DataFrame(rows)
        # 参考月取自 TIME 字段（如 “2026年09月份”），避免依赖 REPORT_DATE 的具体日
        month = raw["TIME"].astype(str).str.extract(r"(\d{4})\D+(\d{1,2})")
        fallback = pd.to_datetime(raw["REPORT_DATE"], errors="coerce")
        parsed = pd.to_datetime(
            month[0].fillna(fallback.dt.strftime("%Y")) + "-"
            + month[1].fillna(fallback.dt.strftime("%m")).str.zfill(2).fillna("01") + "-01",
            errors="coerce",
        )
        raw["date"] = parsed
        df = _norm_frame(raw, "date", "MAKE_INDEX")
        # 月频：观测日统一为“该月最后一个自然日”，与项目 obs_date 口径一致
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)
        df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="eastmoney-datacenter-web", source_url=EM_DATACENTER_V1_URL,
                       detail="RPT_ECONOMY_PMI / MAKE_INDEX（制造业 PMI，指数点）")

    return Provider("eastmoney-datacenter-web", "eastmoney-datacenter-web",
                    EM_DATACENTER_V1_URL, _fn)


def _provider_csi500_csindex() -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        raw = csindex_history(client, "000905", start, end)
        df = _norm_frame(raw, "date", "close")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="csindex-official", source_url=CSINDEX_URL,
                       detail="indexCode=000905 中证500 收盘点位")

    return Provider("csindex-official", "csindex-official", CSINDEX_URL, _fn)


def _provider_ahp_ths() -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        raw = ths_daily(client, "hk_HSAHP", start, end)
        df = _norm_frame(raw, "date", "close")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="ths-10jqka", source_url=THS_LINE_URL.format(symbol="hk_HSAHP"),
                       detail=f"同花顺 hk_HSAHP（{raw.attrs.get('name')}）收盘点位")

    return Provider("ths-10jqka", "ths-10jqka", THS_LINE_URL.format(symbol="hk_HSAHP"), _fn)


def _provider_turnover_em() -> Provider:
    """沪深两市成交额：上证指数成交额 + 深证综指成交额（元 -> 亿元）。"""

    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        sh = em_kline(client, "1.000001")  # 上证指数
        sz = em_kline(client, "0.399106")  # 深证综指（覆盖深市全部 A 股）
        sh = sh[["date", "amount"]].rename(columns={"amount": "sh"})
        sz = sz[["date", "amount"]].rename(columns={"amount": "sz"})
        merged = sh.merge(sz, on="date", how="inner")
        merged["value"] = (merged["sh"] + merged["sz"]) / 1e8  # 元 -> 亿元
        df = _norm_frame(merged, "date", "value")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="eastmoney-push2his", source_url=EM_KLINE_URL,
                       detail="1.000001 上证指数 + 0.399106 深证综指 成交额之和（亿元）")

    return Provider("eastmoney-push2his", "eastmoney-push2his", EM_KLINE_URL, _fn)


def _provider_turnover_tencent() -> Provider:
    def _fn(client: HttpClient, start: date, end: date) -> Fetched:
        sh = tencent_kline(client, "sh000001", start, end)
        sz = tencent_kline(client, "sz399106", start, end)
        sh = sh[["date", "amount_wan"]].rename(columns={"amount_wan": "sh"})
        sz = sz[["date", "amount_wan"]].rename(columns={"amount_wan": "sz"})
        merged = sh.merge(sz, on="date", how="inner")
        merged["value"] = (merged["sh"] + merged["sz"]) / 1e4  # 万元 -> 亿元
        df = _norm_frame(merged, "date", "value")
        df = _slice_window(df, start, end)
        return Fetched(frame=df, source="tencent-finance", source_url=TENCENT_KLINE_URL,
                       detail="sh000001 + sz399106 成交额之和（万元/1e4=亿元）")

    return Provider("tencent-finance", "tencent-finance", TENCENT_KLINE_URL, _fn)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _year_mean_check(year: int, lo: float, hi: float) -> Callable[[pd.DataFrame], tuple[bool, str]]:
    def _fn(df: pd.DataFrame) -> tuple[bool, str]:
        sub = df[df["date"].dt.year == year]["value"]
        if sub.empty:
            return False, f"{year} 年无数据"
        mean = float(sub.mean())
        return lo <= mean <= hi, f"{year} 年均值 {mean:.4f}（期望 {lo}~{hi}）"

    return _fn


def _overall_mean_check(lo: float, hi: float) -> Callable[[pd.DataFrame], tuple[bool, str]]:
    def _fn(df: pd.DataFrame) -> tuple[bool, str]:
        mean = float(df["value"].mean())
        return lo <= mean <= hi, f"全样本均值 {mean:.4f}（期望 {lo}~{hi}）"

    return _fn


def _extreme_check(year: int, lo: float, hi: float, how: str = "max") -> Callable[[pd.DataFrame], tuple[bool, str]]:
    def _fn(df: pd.DataFrame) -> tuple[bool, str]:
        sub = df[df["date"].dt.year == year]["value"]
        if sub.empty:
            return False, f"{year} 年无数据"
        val = float(sub.max() if how == "max" else sub.min())
        ok = lo <= val <= hi
        return ok, f"{year} 年{how} {val:.4f}（期望 {lo}~{hi}）"

    return _fn


def build_jobs(shared: dict) -> tuple[SeriesJob, ...]:
    """组装全部待补序列的规格（含主源/备源与校验规则）。"""
    return (
        SeriesJob(
            series_id="market.cn_bond.cgb_10y",
            name="10年期国债到期收益率",
            unit="%",
            frequency="daily",
            pit="close_1800_cst",
            providers=(
                _provider_cgb_em(),
                _provider_cgb_chinabond(shared),
            ),
            min_rows=2500,
            value_range=(1.0, 5.0),
            max_gap_days=15,
            sanity=(
                ("2020 年 2.4~3.4%", _year_mean_check(2020, 2.4, 3.4)),
                ("2024 年 1.5~2.5%", _year_mean_check(2024, 1.5, 2.5)),
            ),
            notes="中债估值口径的银行间国开/国债到期收益率曲线 10 年；东财与中债交叉校验",
        ),
        SeriesJob(
            series_id="rates.credit.aa_spread",
            name="中债 AAA 中票信用利差（5Y − 国债 5Y）",
            unit="bp",
            frequency="daily",
            pit="close_1800_cst",
            providers=(_provider_aa_spread(shared),),
            min_rows=2400,
            value_range=(5.0, 400.0),
            max_gap_days=15,
            sanity=(
                ("全样本均值 40~200bp", _overall_mean_check(40.0, 200.0)),
                ("2020 年 4 月最大值 >90bp（流动性冲击）", _extreme_check(2020, 90.0, 400.0, "max")),
            ),
            notes="序列 ID 沿用目录命名 aa_spread；公开渠道仅有中债 AAA 中票曲线，AA 曲线需付费接口，"
                  "故以 AAA 中票 5Y − 国债 5Y 作为信用利差代理（偏低估计）",
        ),
        SeriesJob(
            series_id="macro.pmi.manufacturing",
            name="制造业 PMI",
            unit="点",
            frequency="monthly",
            pit="next_trading_day_0900_cst",
            providers=(_provider_pmi_em(),),
            min_rows=120,
            value_range=(35.0, 60.0),
            max_gap_days=70,
            start_tolerance_days=35,
            freshness_days=45,
            sanity=(
                ("全样本均值 48~52", _overall_mean_check(48.0, 52.0)),
                ("2020 年 2 月 <40（疫情低点）", _extreme_check(2020, 30.0, 40.0, "min")),
                ("2020 年 3 月 >50（复工反弹）", _extreme_check(2020, 50.0, 60.0, "max")),
            ),
            notes="国家统计局/中采 PMI 制造业指数；观测日=当月最后自然日",
        ),
        SeriesJob(
            series_id="market.global.sp500",
            name="标普500指数",
            unit="点",
            frequency="daily",
            pit="next_day_0900_cst",
            providers=(
                _em_close_provider("eastmoney-push2his", "100.SPX", "eastmoney-push2his"),
                _tencent_close_provider("tencent-finance", "us.INX"),
            ),
            min_rows=2400,
            value_range=(1500.0, 12000.0),
            max_gap_days=8,
            sanity=(
                ("2020 年 3 月最低 <2400", _extreme_check(2020, 1800.0, 2400.0, "min")),
                ("2024 年均值 4800~6200", _year_mean_check(2024, 4800.0, 6200.0)),
            ),
            notes="标普500 收盘点位；date 为美东交易日，publish_ts 顺延至次日 09:00 北京时间",
        ),
        SeriesJob(
            series_id="crossborder.flows.ah_premium",
            name="恒生沪深港通 AH 股溢价指数",
            unit="点",
            frequency="daily",
            pit="close_1800_cst",
            providers=(
                _em_close_provider("eastmoney-push2his", "100.HSAHP", "eastmoney-push2his"),
                _provider_ahp_ths(),
            ),
            min_rows=2400,
            value_range=(80.0, 250.0),
            max_gap_days=15,
            sanity=(
                ("全样本均值 110~170", _overall_mean_check(110.0, 170.0)),
                ("2024 年均值 >120（A 股相对溢价）", _year_mean_check(2024, 120.0, 250.0)),
            ),
            notes="恒生指数公司编制、东方财富/同花顺转载；收盘价（港股 16:00）",
        ),
        SeriesJob(
            series_id="market.cn_equity.csi500",
            name="中证500指数",
            unit="点",
            frequency="daily",
            pit="close_1800_cst",
            providers=(
                _em_close_provider("eastmoney-push2his", "1.000905", "eastmoney-push2his"),
                _provider_csi500_csindex(),
                _tencent_close_provider("tencent-finance", "sh000905"),
            ),
            min_rows=2400,
            value_range=(1000.0, 12000.0),
            max_gap_days=15,
            sanity=(
                ("2020 年均值 5000~6500", _year_mean_check(2020, 5000.0, 6500.0)),
                ("2024 年均值 4500~6200", _year_mean_check(2024, 4500.0, 6200.0)),
            ),
            notes="中证指数有限公司编制；收盘点位",
        ),
        SeriesJob(
            series_id="market.cn_equity.turnover",
            name="沪深两市成交额",
            unit="亿元",
            frequency="daily",
            pit="close_1800_cst",
            providers=(
                _provider_turnover_em(),
                _provider_turnover_tencent(),
            ),
            min_rows=2400,
            value_range=(1000.0, 40000.0),
            max_gap_days=15,
            sanity=(
                ("全样本均值 3000~15000 亿元", _overall_mean_check(3000.0, 15000.0)),
                ("2020 年均值 >5000 亿元", _year_mean_check(2020, 5000.0, 20000.0)),
            ),
            notes="上证指数成交额 + 深证综指成交额（沪市全市场 + 深市全市场）",
            required=False,
        ),
    )


def validate(job: SeriesJob, df: pd.DataFrame, start: date, end: date,
             cross_check: dict | None) -> list[dict]:
    """对一条序列跑结构化校验，返回 ``[{name, ok, detail}]``。"""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("row_count", len(df) >= job.min_rows, f"行数 {len(df)}（下限 {job.min_rows}）")
    add("non_empty", not df.empty, f"非空行 {len(df)}")
    if df.empty:
        return checks

    add("date_unique_sorted", df["date"].is_monotonic_increasing and df["date"].is_unique,
        "日期唯一且升序" if df["date"].is_monotonic_increasing else "日期非升序")
    add("coverage_start", df["date"].min().date() <= start + timedelta(days=job.start_tolerance_days),
        f"首日 {df['date'].min().date()}（目标起点 {start}，容差 {job.start_tolerance_days} 天）")
    add("coverage_end", df["date"].max().date() >= end - timedelta(days=job.freshness_days),
        f"末日 {df['date'].max().date()}（抓取截止 {end}，容差 {job.freshness_days} 天）")

    lo, hi = job.value_range
    add("value_range", bool(df["value"].between(lo, hi).all()),
        f"取值范围 {df['value'].min():.4f}~{df['value'].max():.4f}（期望 {lo}~{hi}）")
    add("no_nan", bool(df["value"].notna().all()), f"空值 {int(df['value'].isna().sum())} 个")

    gaps = df["date"].diff().dt.days.dropna()
    big_gaps = gaps[gaps > job.max_gap_days]
    add("max_gap", len(big_gaps) == 0,
        f"最大间隔 {gaps.max():.0f} 天（阈值 {job.max_gap_days}），超阈值 {len(big_gaps)} 处")

    for name, fn in job.sanity:
        try:
            ok, detail = fn(df)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"校验异常 {type(exc).__name__}: {exc}"
        add(f"sanity: {name}", ok, detail)

    if cross_check:
        add("cross_check", cross_check.get("ok", False), cross_check.get("detail", ""))
    return checks


# --------------------------------------------------------------------------- #
# PIT 时点计算
# --------------------------------------------------------------------------- #
class TradingCalendar:
    """用本次抓到的中国市场日频日期构造交易日历（用于月频发布时点）。"""

    def __init__(self, dates: Sequence[pd.Timestamp]) -> None:
        self.days = sorted({pd.Timestamp(d).date() for d in dates})

    def next_trading_day(self, anchor: date) -> date:
        for day in self.days:
            if day > anchor:
                return day
        # 日历未覆盖（例如末月）：退化为下一自然日
        return anchor + timedelta(days=1)


def compute_publish_ts(dates: pd.Series, pit: str, calendar: TradingCalendar) -> list[datetime]:
    """按序列的 PIT 规则生成保守可得时点列表。"""
    out: list[datetime] = []
    for ts in dates:
        day = ts.date()
        if pit == "close_1800_cst":
            out.append(datetime.combine(day, dtime(18, 0), tzinfo=CST))
        elif pit == "next_day_0900_cst":
            out.append(datetime.combine(day + timedelta(days=1), dtime(9, 0), tzinfo=CST))
        elif pit == "next_trading_day_0900_cst":
            out.append(datetime.combine(calendar.next_trading_day(day), dtime(9, 0), tzinfo=CST))
        else:  # pragma: no cover - 防御
            raise ValueError(f"未知 PIT 规则: {pit}")
    return out


PIT_DESCRIPTION = {
    "close_1800_cst": "观测日当日 18:00 +08:00（A 股 15:00/港股 16:00 收盘、中债估值约 17:30 发布，取保守值）",
    "next_day_0900_cst": "观测日次日 09:00 +08:00（美股 16:00 ET 收盘 = 北京次日 04:00/05:00，避免前视）",
    "next_trading_day_0900_cst": "次月首个交易日 09:00 +08:00（统计局实际月末最后一日 09:30 发布，此处更保守）",
}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _format_value(value: float) -> str:
    """数值输出：最多 6 位小数并去掉无意义的尾随 0。"""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def fetch_one(client: HttpClient, job: SeriesJob, start: date, end: date) -> tuple[Fetched, list[dict]]:
    """按 provider 顺序尝试抓取，返回首个成功结果与尝试记录。"""
    attempts: list[dict] = []
    for provider in job.providers:
        t0 = time.time()
        try:
            fetched = provider.fn(client, start, end)
            elapsed = int((time.time() - t0) * 1000)
            if fetched.frame.empty:
                raise FetchError("返回 0 行")
            attempts.append({"provider": provider.name, "ok": True, "ms": elapsed,
                             "rows": int(len(fetched.frame)), "detail": fetched.detail})
            print(f"    [ok] {provider.name}: {len(fetched.frame)} 行 / {elapsed} ms", flush=True)
            return fetched, attempts
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.time() - t0) * 1000)
            reason = f"{type(exc).__name__}: {exc}"
            attempts.append({"provider": provider.name, "ok": False, "ms": elapsed,
                             "error": reason[:400]})
            print(f"    [fail] {provider.name}: {reason[:160]}", flush=True)
    raise FetchError("全部数据源均失败：" + " | ".join(a["provider"] for a in attempts))


def write_series_csv(path: Path, series_id: str, df: pd.DataFrame, job: SeriesJob,
                     fetched: Fetched, fetch_ts: datetime,
                     calendar: TradingCalendar) -> None:
    """按固定列序写出长表 CSV。"""
    publish = compute_publish_ts(df["date"], job.pit, calendar)
    out = pd.DataFrame(
        {
            "series_id": series_id,
            "date": df["date"].dt.strftime("%Y-%m-%d"),
            "value": [_format_value(v) for v in df["value"].tolist()],
            "unit": job.unit,
            "frequency": job.frequency,
            "source": fetched.source,
            "source_url": fetched.source_url,
            "publish_ts": [ts.isoformat() for ts in publish],
            "fetch_ts": fetch_ts.isoformat(),
            "version": VERSION,
        }
    )[OUT_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 公开数据补齐（缺失序列抓取 + 时点化 CSV）")
    parser.add_argument("--start", default=DEFAULT_START.isoformat(), help="起始日 YYYY-MM-DD（默认 2015-01-01）")
    parser.add_argument("--end", default=date.today().isoformat(), help="截止日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="输出目录（默认 data/raw/public）")
    parser.add_argument("--only", nargs="*", default=None, help="只抓指定 series_id")
    parser.add_argument("--min-interval", type=float, default=1.2, help="同 host 最小请求间隔（秒）")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = HttpClient(min_interval=args.min_interval)
    shared: dict = {}
    jobs = build_jobs(shared)
    if args.only:
        wanted = set(args.only)
        jobs = tuple(job for job in jobs if job.series_id in wanted)
        if not jobs:
            print(f"未匹配到序列：{args.only}", file=sys.stderr)
            return 2

    print("=" * 78)
    print(f"CBR-MAW 公开数据补齐 | 窗口 {start} ~ {end} | 输出 {out_dir}")
    print("=" * 78)

    results: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}
    failed: list[dict] = []

    # 第一轮：抓取
    for job in jobs:
        print(f"\n[{job.series_id}] {job.name}（{job.unit}, {job.frequency}）", flush=True)
        attempts: list[dict] = []
        try:
            fetched, attempts = fetch_one(client, job, start, end)
            frames[job.series_id] = fetched.frame
            results.append({"job": job, "fetched": fetched, "attempts": attempts, "ok": True})
        except FetchError as exc:
            print(f"    [FAILED] {exc}", flush=True)
            failed.append({"series_id": job.series_id, "name": job.name, "error": str(exc),
                           "attempts": attempts})
            results.append({"job": job, "ok": False, "error": str(exc), "attempts": attempts})

    # 交易日历：优先用中国日频序列的日期并集
    cn_ids = ("market.cn_bond.cgb_10y", "market.cn_equity.csi500",
              "market.cn_equity.turnover", "crossborder.flows.ah_premium")
    cal_dates: list[pd.Timestamp] = []
    for sid in cn_ids:
        if sid in frames:
            cal_dates.extend(frames[sid]["date"].tolist())
    if not cal_dates:
        cal_dates = list(pd.bdate_range(start, end))
    calendar = TradingCalendar(cal_dates)

    # 第二轮：校验 + 落盘
    manifest_series: dict[str, dict] = {}
    fetch_ts = datetime.now(CST)
    print("\n" + "=" * 78)
    print("校验与落盘")
    print("=" * 78)
    for item in results:
        job: SeriesJob = item["job"]
        sid = job.series_id
        if not item["ok"]:
            manifest_series[sid] = {
                "status": "failed",
                "name": job.name,
                "unit": job.unit,
                "frequency": job.frequency,
                "attempts": item.get("attempts", []),
                "error": item.get("error", ""),
            }
            continue
        fetched: Fetched = item["fetched"]
        df = frames[sid]
        cross = None
        # 10Y 国债：与中债国债曲线交叉校验（同一运行内已抓取则免费比对）
        if sid == "market.cn_bond.cgb_10y" and "chinabond" in shared:
            gov = shared["chinabond"]["gov"]
            if "10年" in gov.columns:
                merged = df.merge(_norm_frame(gov, "date", "10年"), on="date", suffixes=("", "_cb"))
                if not merged.empty:
                    diff = (merged["value"] - merged["value_cb"]).abs()
                    cross = {
                        "ok": bool(diff.max() < 0.15),
                        "detail": f"与中债国债曲线 10Y 比对 {len(merged)} 日，"
                                  f"平均绝对差 {diff.mean()*100:.2f}bp，最大 {diff.max()*100:.2f}bp",
                        "n_common": int(len(merged)),
                        "mean_abs_diff_bp": round(float(diff.mean()) * 100, 3),
                        "max_abs_diff_bp": round(float(diff.max()) * 100, 3),
                    }
        checks = validate(job, df, start, end, cross)
        path = out_dir / f"{sid}.csv"
        write_series_csv(path, sid, df, job, fetched, fetch_ts, calendar)

        ok = all(c["ok"] for c in checks)
        iso_dates = df["date"].dt.strftime("%Y-%m-%d")
        fetch_dates = pd.Series(pd.to_datetime(iso_dates, errors="coerce"))
        gaps = fetch_dates.diff().dt.days.dropna()
        manifest_series[sid] = {
            "status": "ok" if ok else "ok_with_warnings",
            "name": job.name,
            "unit": job.unit,
            "frequency": job.frequency,
            "rows": int(len(df)),
            "coverage": {"start": iso_dates.iloc[0], "end": iso_dates.iloc[-1]},
            "source": fetched.source,
            "source_url": fetched.source_url,
            "source_detail": fetched.detail,
            "file": path.name,
            "pit_rule": job.pit,
            "pit_note": PIT_DESCRIPTION.get(job.pit, ""),
            "max_gap_days": int(gaps.max()) if not gaps.empty else 0,
            "n_gaps_over_threshold": int((gaps > job.max_gap_days).sum()) if not gaps.empty else 0,
            "value_stats": {
                "min": round(float(df["value"].min()), 4),
                "max": round(float(df["value"].max()), 4),
                "mean": round(float(df["value"].mean()), 4),
                "last": round(float(df["value"].iloc[-1]), 4),
            },
            "cross_check": cross,
            "attempts": item["attempts"],
            "validation": {"all_ok": ok, "checks": checks},
            "notes": job.notes,
        }

    # 控制台汇总
    print("\n" + "=" * 78)
    print("汇总")
    print("=" * 78)
    header = f"{'series_id':34s} {'状态':6s} {'行数':>6s} {'首日':>11s} {'末日':>11s} {'单位':>6s} {'样例':>12s}"
    print(header)
    print("-" * len(header))
    for sid, meta in manifest_series.items():
        if meta["status"] == "failed":
            print(f"{sid:34s} {'FAILED':6s} {'-':>6s} {'-':>11s} {'-':>11s} {'-':>6s} {'-':>12s}")
            continue
        stats = meta["value_stats"]
        print(
            f"{sid:34s} {meta['status'][:6]:6s} {meta['rows']:6d} "
            f"{meta['coverage']['start']:>11s} {meta['coverage']['end']:>11s} "
            f"{meta['unit']:>6s} {stats['last']:12.4f}"
        )

    manifest = {
        "dataset": "cbr-maw-public-gap-fill",
        "synthetic": False,
        "version": VERSION,
        "generated_at": fetch_ts.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "script": "scripts/fetch_public_gaps.py",
        "columns": OUT_COLUMNS,
        "environment": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "requests": requests.__version__,
            "platform": platform.platform(),
        },
        "pit_conventions": PIT_DESCRIPTION,
        "n_series_ok": sum(1 for m in manifest_series.values() if m["status"].startswith("ok")),
        "n_series_failed": sum(1 for m in manifest_series.values() if m["status"] == "failed"),
        "series": manifest_series,
        "failures": failed,
        "http_calls": len(client.calls),
        "notes": [
            "数据均为公开、免 key 接口抓取；未做任何插值/填充/伪造，缺失即缺行。",
            "market.global.sp500 的 date 为美东交易日，publish_ts 已顺延至次日 09:00 +08:00。",
            "rates.credit.aa_spread 公开渠道仅有中债 AAA 中票曲线，AA 曲线需付费接口；"
            "故为 AAA 中票 5Y − 国债 5Y 的代理口径（对 AA 利差为偏低估计）。",
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmanifest: {manifest_path}")
    print(f"HTTP 调用 {len(client.calls)} 次；成功 {manifest['n_series_ok']} / 失败 {manifest['n_series_failed']}")

    required_failed = [
        job.series_id
        for job in jobs
        if job.required and manifest_series.get(job.series_id, {}).get("status") == "failed"
    ]
    if required_failed:
        print(f"必需序列失败：{required_failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
