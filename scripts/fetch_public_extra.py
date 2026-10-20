#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""公开数据补齐（补充序列）：cgb_2y / us10y / vix / usdcnh / 社融 / 外储 / LPR / CPI。

``scripts/fetch_public_gaps.py`` 负责 7 条主缺口（10Y 国债、信用利差、PMI、标普 500、
AH 溢价、中证 500、成交额）；本脚本补齐其余系统规范序列，并按同一 CSV 契约输出到
``data/raw/public/<series_id>.csv``：

    series_id,date,value,unit,frequency,source,source_url,publish_ts,fetch_ts,version

数据源（公开、免 key）
----------------------
- 中国 2Y 国债 / 美国 10Y 国债：akshare ``bond_zh_us_rate``（chinamoney 口径）
- VIX：CBOE 官方历史 CSV
- 美元兑离岸人民币（CNH）：akshare ``forex_hist_em``，失败回退新浪外汇日 K
- 社融同比：akshare ``macro_china_shrzgm`` 月度增量 → 12 个月滚动增量同比（代理）
- 外汇储备：akshare ``macro_china_fx_gold``（国家外汇储备，亿美元）
- LPR 1Y：akshare ``macro_china_lpr``（仅保留调整日）
- CPI 同比：akshare ``macro_china_cpi``（统计局口径；失败则跳过，构建脚本保留 B6 2021+）

PIT：A 股/中债日频当日 18:00；全球因子（US10Y/VIX）次日 09:00；月频按发布日 09:00/10:00。
所有序列只写原始可解析值，缺失即缺行，不做插值/伪造。

运行：``.venv\\Scripts\\python.exe scripts/fetch_public_extra.py``
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "public"
FETCH_TS = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
VERSION = "v1"
OUT_COLUMNS = [
    "series_id", "date", "value", "unit", "frequency", "source",
    "source_url", "publish_ts", "fetch_ts", "version",
]


def _save(series_id: str, frame: pd.DataFrame, *, unit: str, frequency: str,
          source: str, source_url: str) -> Path:
    """把标准化后的 (date, value, publish_ts) 写为契约 CSV。"""
    out = frame.copy()
    out["series_id"] = series_id
    out["unit"] = unit
    out["frequency"] = frequency
    out["source"] = source
    out["source_url"] = source_url
    out["fetch_ts"] = FETCH_TS.isoformat(timespec="seconds")
    out["version"] = VERSION
    out = out.loc[:, OUT_COLUMNS]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{series_id}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _retry(fn: Callable[[], pd.DataFrame], attempts: int = 3, sleep: float = 2.0) -> pd.DataFrame:
    last: Exception | None = None
    for index in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 公开接口不稳定，记录后重试
            last = exc
            time.sleep(sleep * (index + 1))
    raise RuntimeError(f"全部重试失败: {type(last).__name__}: {last}") from last


def _frame(dates: pd.Series, values: pd.Series, publish: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(dates).dt.normalize(),
            "value": pd.to_numeric(values, errors="coerce"),
            "publish_ts": pd.to_datetime(publish),
        }
    ).dropna(subset=["date", "value"])
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return out


# --------------------------------------------------------------------------- #
# 各序列抓取
# --------------------------------------------------------------------------- #
def fetch_bond_yields() -> pd.DataFrame:
    """中国 2Y 国债 / 美国 10Y 国债（akshare bond_zh_us_rate）。"""
    import akshare as ak

    raw = _retry(lambda: ak.bond_zh_us_rate(start_date="20140101"))
    raw = raw.rename(columns={"日期": "date"})
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    cn2 = raw.dropna(subset=["date", "中国国债收益率2年"]).copy()
    cn2["publish_ts"] = cn2["date"] + pd.Timedelta(hours=18)
    _save(
        "market.cn_bond.cgb_2y",
        _frame(cn2["date"], cn2["中国国债收益率2年"], cn2["publish_ts"]),
        unit="%", frequency="daily",
        source="chinamoney（经 akshare bond_zh_us_rate）",
        source_url="https://www.chinamoney.com.cn/chinese/bkcurvfx/",
    )
    us10 = raw.dropna(subset=["date", "美国国债收益率10年"]).copy()
    us10["publish_ts"] = us10["date"] + pd.Timedelta(days=1, hours=9)
    _save(
        "market.global.us10y",
        _frame(us10["date"], us10["美国国债收益率10年"], us10["publish_ts"]),
        unit="%", frequency="daily",
        source="US Treasury（经 akshare bond_zh_us_rate）",
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
    )
    return raw


def fetch_vix() -> pd.DataFrame:
    """VIX：CBOE 官方历史 CSV（美东交易日；PIT 次日 09:00 +08）。"""
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    from io import StringIO

    raw = pd.read_csv(StringIO(response.text))
    dates = pd.to_datetime(raw["DATE"])
    publish = dates + pd.Timedelta(days=1, hours=9)
    return _frame(dates, raw["CLOSE"], publish)


def fetch_sp500_cboe() -> pd.DataFrame:
    """SPX：CBOE 官方历史 CSV（``scripts/fetch_public_gaps.py`` 失败时兜底）。"""
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv"
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    from io import StringIO

    raw = pd.read_csv(StringIO(response.text))
    dates = pd.to_datetime(raw["DATE"])
    publish = dates + pd.Timedelta(days=1, hours=9)
    return _frame(dates, raw["SPX"], publish)


def fetch_usdcnh() -> pd.DataFrame:
    """美元兑离岸人民币：akshare 东财外汇历史；失败回退新浪外汇日 K。"""
    import akshare as ak

    try:
        raw = _retry(lambda: ak.forex_hist_em(symbol="USDCNH"), attempts=2)
        date_col = next((c for c in ("日期", "date") if c in raw.columns), None)
        close_col = next((c for c in ("收盘", "close", "最新价") if c in raw.columns), None)
        if date_col is None or close_col is None:
            raise KeyError(f"forex_hist_em 列不匹配: {list(raw.columns)}")
        dates = pd.to_datetime(raw[date_col], errors="coerce")
        publish = dates + pd.Timedelta(hours=18)
        return _frame(dates, raw[close_col], publish)
    except Exception:  # noqa: BLE001 - 回退新浪
        raw = _retry(lambda: _sina_forex_hist("fx_susdcnh"), attempts=2)
        return raw


def _sina_forex_hist(symbol: str) -> pd.DataFrame:
    """新浪外汇日 K（JSONP）：``date,open,high,low,close`` 逗号分隔。"""
    url = (
        "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_fx=/"
        f"NewForexService.getDayKLine?symbol={symbol}"
    )
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
        timeout=30,
    )
    response.raise_for_status()
    text = response.text
    start, end = text.find("("), text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("新浪外汇返回格式异常")
    body = text[start + 1 : end]
    rows: list[tuple[pd.Timestamp, float]] = []
    for item in body.split("|"):
        parts = [part.strip() for part in item.strip().split(",") if part.strip()]
        if len(parts) < 2:
            continue
        try:
            date = pd.Timestamp(parts[0])
            # 新浪日 K 字段为 open/high/low/close；取最后一个有效字段作为收盘
            value = float(parts[-1])
        except (ValueError, TypeError):
            continue
        if not (4.0 < value < 10.0):
            continue
        rows.append((date, value))
    if not rows:
        raise ValueError("新浪外汇历史为空")
    frame = pd.DataFrame(rows, columns=["date", "value"]).sort_values("date")
    frame["publish_ts"] = frame["date"] + pd.Timedelta(hours=18)
    frame["value"] = frame["value"].astype(float)
    return frame


def fetch_social_financing() -> pd.DataFrame:
    """社融同比：月度增量 → 12 个月滚动增量同比（代理口径，单位 %）。"""
    import akshare as ak

    raw = _retry(lambda: ak.macro_china_shrzgm())
    raw = raw.copy()
    raw["month"] = raw["月份"].astype(str).str.zfill(6)
    raw["date"] = pd.to_datetime(raw["month"], format="%Y%m", errors="coerce") + pd.offsets.MonthEnd(0)
    raw["value"] = pd.to_numeric(raw["社会融资规模增量"], errors="coerce")
    raw = raw.dropna(subset=["date", "value"]).sort_values("date")
    rolling = raw.set_index("date")["value"].rolling(12, min_periods=12).sum()
    yoy = (rolling / rolling.shift(12) - 1.0) * 100.0
    out = pd.DataFrame({"date": yoy.index, "value": yoy.values})
    out = out.replace([float("inf"), float("-inf")], pd.NA).dropna(subset=["value"])
    out["publish_ts"] = out["date"] + pd.offsets.MonthBegin(1) + pd.Timedelta(days=11, hours=10)
    return out


def fetch_fx_reserves() -> pd.DataFrame:
    """外汇储备（亿美元）：akshare macro_china_fx_gold。"""
    import akshare as ak

    raw = _retry(lambda: ak.macro_china_fx_gold())
    raw = raw.copy()
    raw["month"] = (
        raw["月份"].astype(str).str.replace("年", "-", regex=False).str.replace("月份", "", regex=False)
    )
    raw["date"] = pd.to_datetime(raw["month"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    raw["value"] = pd.to_numeric(raw["国家外汇储备-数值"], errors="coerce")
    raw = raw.dropna(subset=["date", "value"]).sort_values("date")
    raw["publish_ts"] = raw["date"] + pd.offsets.MonthBegin(1) + pd.Timedelta(days=6, hours=10)
    return _frame(raw["date"], raw["value"], raw["publish_ts"])


def fetch_lpr() -> pd.DataFrame:
    """LPR 1Y：akshare macro_china_lpr，仅保留调整日（发布日 09:15）。"""
    import akshare as ak

    raw = _retry(lambda: ak.macro_china_lpr())
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["TRADE_DATE"], errors="coerce")
    raw["value"] = pd.to_numeric(raw["LPR1Y"], errors="coerce")
    raw = raw.dropna(subset=["date", "value"]).sort_values("date")
    raw = raw[raw["value"].diff().fillna(1.0) != 0]
    raw["publish_ts"] = raw["date"] + pd.Timedelta(hours=9, minutes=15)
    return _frame(raw["date"], raw["value"], raw["publish_ts"])


def fetch_cpi() -> pd.DataFrame:
    """CPI 同比（%，统计局口径；仅当 B6 覆盖不足时使用）。"""
    import akshare as ak

    raw = _retry(lambda: ak.macro_china_cpi(), attempts=2)
    raw = raw.copy()
    month_col = next((c for c in ("月份", "month") if c in raw.columns), None)
    value_col = next((c for c in ("全国-当月同比", "全国-同比增长", "全国-当月") if c in raw.columns), None)
    if month_col is None or value_col is None:
        raise KeyError(f"macro_china_cpi 列不匹配: {list(raw.columns)}")
    month = (
        raw[month_col].astype(str).str.replace("年", "-", regex=False).str.replace("月份", "", regex=False)
    )
    dates = pd.to_datetime(month, format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    values = pd.to_numeric(raw[value_col], errors="coerce")
    publish = dates + pd.offsets.MonthBegin(1) + pd.Timedelta(days=9, hours=10)
    return _frame(dates, values, publish)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
JOBS: list[tuple[str, str, str, str, str, Callable[[], pd.DataFrame]]] = [
    # series_id, unit, frequency, source, source_url, fetcher
    ("market.cn_bond.cgb_2y", "%", "daily", "chinamoney", "https://www.chinamoney.com.cn/", fetch_bond_yields),
    ("market.global.us10y", "%", "daily", "US Treasury", "https://home.treasury.gov/", fetch_bond_yields),
    ("market.global.vix", "点", "daily", "CBOE", "https://www.cboe.com/", fetch_vix),
    ("market.fx.usdcnh", "CNH/USD", "daily", "东方财富/新浪外汇", "https://quote.eastmoney.com/", fetch_usdcnh),
    ("macro.social_financing.yoy", "%", "monthly", "中国人民银行（经 akshare）", "http://www.pbc.gov.cn/", fetch_social_financing),
    ("macro.fx_reserves", "亿美元", "monthly", "国家外汇管理局（经 akshare）", "https://www.safe.gov.cn/", fetch_fx_reserves),
    ("macro.lpr.1y", "%", "monthly", "全国银行间同业拆借中心（经 akshare）", "https://www.chinamoney.com.cn/", fetch_lpr),
]


def main(argv: list[str] | None = None) -> int:
    results: dict[str, dict[str, Any]] = {}
    shared_yields: pd.DataFrame | None = None

    for series_id, unit, frequency, source, source_url, fetcher in JOBS:
        try:
            if fetcher is fetch_bond_yields:
                if shared_yields is None:
                    shared_yields = fetch_bond_yields()
                # fetch_bond_yields 内部已写两个文件
                results[series_id] = {"status": "ok"}
                print(f"[ok] {series_id} (已随 bond_zh_us_rate 写入)")
                continue
            frame = fetcher()
            _save(series_id, frame, unit=unit, frequency=frequency, source=source, source_url=source_url)
            results[series_id] = {
                "status": "ok",
                "rows": int(len(frame)),
                "start": str(frame["date"].min().date()),
                "end": str(frame["date"].max().date()),
            }
            print(f"[ok] {series_id}: {len(frame)} rows {frame['date'].min().date()} ~ {frame['date'].max().date()}")
        except Exception as exc:  # noqa: BLE001 - 单序列失败不阻塞其他序列
            results[series_id] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            print(f"[FAIL] {series_id}: {type(exc).__name__}: {exc}", file=sys.stderr)

    # SP500 / PMI 兜底：仅当主脚本未产出对应文件时
    for series_id, fetcher, unit, source, url in [
        ("market.global.sp500", fetch_sp500_cboe, "点", "CBOE", "https://www.cboe.com/"),
        ("macro.pmi.manufacturing", None, "点", "国家统计局（经 akshare）", "https://www.stats.gov.cn/"),
    ]:
        path = OUT_DIR / f"{series_id}.csv"
        if path.exists():
            results.setdefault(series_id, {"status": "skipped(existing)"})
            continue
        try:
            if series_id == "market.global.sp500":
                frame = fetcher()
            else:
                import akshare as ak

                raw = ak.macro_china_pmi()
                raw = raw.copy()
                month = (
                    raw["月份"].astype(str).str.replace("年", "-", regex=False).str.replace("月份", "", regex=False)
                )
                dates = pd.to_datetime(month, format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
                values = pd.to_numeric(raw["制造业-指数"], errors="coerce")
                publish = dates + pd.Timedelta(days=1, hours=9)
                frame = _frame(dates, values, publish)
            _save(series_id, frame, unit=unit, frequency="daily" if series_id.startswith("market.global") else "monthly",
                  source=source, source_url=url)
            results[series_id] = {"status": "ok", "rows": int(len(frame))}
            print(f"[ok] fallback {series_id}: {len(frame)} rows")
        except Exception as exc:  # noqa: BLE001
            results[series_id] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            print(f"[FAIL] fallback {series_id}: {exc}", file=sys.stderr)

    manifest_path = OUT_DIR / "manifest_extra.json"
    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": FETCH_TS.isoformat(timespec="seconds"),
                "script": "scripts/fetch_public_extra.py",
                "window": {"start": "2015-01-01", "end": str(FETCH_TS.date())},
                "series": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("manifest ->", manifest_path)
    failed = [sid for sid, item in results.items() if item.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
