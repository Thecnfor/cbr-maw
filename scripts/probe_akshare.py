# -*- coding: utf-8 -*-
"""CBR-MAW akshare probe. Run inside .venv-probe.

Usage: .venv-probe\\Scripts\\python.exe scripts\\probe_akshare.py
Every probe is wrapped: failures never abort the run.
"""
import sys
import time
import traceback

import pandas as pd

import akshare as ak

print(f"# akshare {ak.__version__} | pandas {pd.__version__} | {time.strftime('%Y-%m-%d %H:%M:%S')}")
TMPL = "RESULT|{name}|{status}|ms={ms}|shape={shape}|cols={cols}|head={head}"


def run(name, fn, note=""):
    t0 = time.time()
    try:
        df = fn()
        ms = int((time.time() - t0) * 1000)
        if df is None:
            print(TMPL.format(name=name, status="EMPTY", ms=ms, shape="None",
                              cols="", head="returned None"))
            return None
        shape = getattr(df, "shape", "?")
        cols = list(getattr(df, "columns", []))[:20]
        head = ""
        try:
            head = df.head(2).to_json(force_ascii=False, orient="records")[:420]
        except Exception:  # noqa: BLE001
            head = str(df)[:420]
        print(TMPL.format(name=name, status="OK", ms=ms, shape=shape,
                          cols=[str(c) for c in cols], head=head))
        return df
    except Exception as e:  # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        err = f"{type(e).__name__}: {e}"[:300]
        print(f"RESULT|{name}|FAIL|ms={ms}|err={err}")
        return None


def run_multi(name, fns):
    """Try (label, func) candidates until one works."""
    for label, fn in fns:
        df = run(f"{name}[{label}]", fn)
        if df is not None and getattr(df, "shape", (0,))[0] > 0:
            return df
    return None


print("\n## A. 沪深港通 (northbound disclosure changed after 2024-08-19)")
run("hsgt_fund_flow_summary", lambda: ak.stock_hsgt_fund_flow_summary_em())
nb = run("hsgt_hist_north", lambda: ak.stock_hsgt_hist_em(symbol="北向资金"))
if nb is not None:
    try:
        col = "当日成交净买额" if "当日成交净买额" in nb.columns else nb.columns[2]
        nb2 = nb.copy()
        nb2["日期"] = pd.to_datetime(nb2["日期"] if "日期" in nb2.columns else nb2.iloc[:, 0], errors="coerce")
        tail = nb2.sort_values("日期").tail(6)
        print("RESULT|hsgt_hist_north_tail|OK|" + tail.to_json(force_ascii=False, orient="records")[:800])
        nz = nb2[pd.to_numeric(nb2[col], errors="coerce").fillna(0) != 0]
        print(f"RESULT|hsgt_hist_north_range|OK|rows={len(nb2)}|"
              f"last_nonzero={nz.tail(1).to_json(force_ascii=False, orient='records')[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"RESULT|hsgt_hist_north_tail|FAIL|{type(e).__name__}: {e}")
run("hsgt_hist_south", lambda: ak.stock_hsgt_hist_em(symbol="南向资金"))
run_multi("hsgt_hold", [
    ("hold_em", lambda: ak.stock_hsgt_hold_stock_em(market="北向", indicator="今日排行")),
    ("hold_detail", lambda: ak.stock_hsgt_hold_stock_em(market="北向")),
])

print("\n## B. indices / rates / fx")
hs300 = run_multi("index_zh_a_hist_000300", [
    ("em", lambda: ak.index_zh_a_hist(symbol="000300", period="daily",
                                      start_date="20150101", end_date="20261018")),
])
run_multi("hsi_hist", [
    ("hk_index_daily_em", lambda: ak.stock_hk_index_daily_em(symbol="HSI")),
    ("hk_index_daily_sina", lambda: ak.stock_hk_index_daily_sina(symbol="HSI")),
    ("stock_hk_index_spot_em", lambda: ak.stock_hk_index_spot_em()),
])
run_multi("cn_gov_yield", [
    ("bond_china_yield", lambda: ak.bond_china_yield(start_date="20240101", end_date="20240701")),
    ("bond_zh_us_rate", lambda: ak.bond_zh_us_rate(start_date="20240101")),
])
run_multi("usd_cny", [
    ("forex_hist_em", lambda: ak.forex_hist_em(symbol="USDCNY")),
    ("currency_boc", lambda: ak.currency_boc_safe()),
    ("forex_spot_em", lambda: ak.forex_spot_em()),
    ("fx_spot_quote", lambda: ak.fx_spot_quote()),
])
run_multi("usd_cnh", [
    ("forex_hist_em_cnh", lambda: ak.forex_hist_em(symbol="USDCNH")),
    ("currency_hist", lambda: ak.currency_hist(symbol="USDCNH")),
])

print("\n## C. news / policy text via akshare")
run("global_news_em", lambda: ak.stock_info_global_em())
run("global_news_cls", lambda: ak.stock_info_global_cls(symbol="全部"))
run_multi("cctv_news", [("news_cctv", lambda: ak.news_cctv(date="20241018"))])
run_multi("macro_china_news", [
    ("macro_china_news", lambda: ak.macro_china_news()),
    ("news_economic_baidu", lambda: ak.news_economic_baidu(date="20241018")),
])

print("\n## D. extra: 中债收益率曲线明细 / 银行间")
run_multi("bond_yield_curve", [
    ("bond_zh_us_rate_curve", lambda: ak.bond_zh_us_rate(start_date="20250101")),
])

print("\n# done")
