# -*- coding: utf-8 -*-
"""CBR-MAW akshare probe round 2: fill gaps found in round 1.

Run: .venv-probe\\Scripts\\python.exe scripts\\probe_akshare2.py
"""
import time

import pandas as pd
import akshare as ak

print(f"# akshare {ak.__version__} round2 | {time.strftime('%Y-%m-%d %H:%M:%S')}")


def run(name, fn):
    t0 = time.time()
    try:
        df = fn()
        ms = int((time.time() - t0) * 1000)
        if df is None:
            print(f"RESULT|{name}|EMPTY|ms={ms}")
            return None
        print(f"RESULT|{name}|OK|ms={ms}|shape={getattr(df, 'shape', '?')}|"
              f"cols={[str(c) for c in list(getattr(df, 'columns', []))[:14]]}|"
              f"head={df.head(2).to_json(force_ascii=False, orient='records')[:400]}")
        return df
    except Exception as e:  # noqa: BLE001
        print(f"RESULT|{name}|FAIL|ms={int((time.time() - t0) * 1000)}|err={type(e).__name__}: {str(e)[:250]}")
        return None


print("\n## 沪深300 日线（三种取法）")
hs = run("hs300_index_zh_a_hist_retry", lambda: ak.index_zh_a_hist(
    symbol="000300", period="daily", start_date="20150101", end_date="20261018"))
if hs is None:
    hs = run("hs300_stock_zh_index_daily_em", lambda: ak.stock_zh_index_daily_em(symbol="sh000300"))
if hs is None:
    hs = run("hs300_stock_zh_index_daily", lambda: ak.stock_zh_index_daily(symbol="sh000300"))

print("\n## 中美国债收益率长历史")
run("bond_zh_us_rate_2015", lambda: ak.bond_zh_us_rate(start_date="20150101"))

print("\n## 汇率（即期/中间价）")
run("fx_spot_quote", lambda: ak.fx_spot_quote())
run("currency_boc_safe_short", lambda: ak.currency_boc_safe())
run("forex_spot_em", lambda: ak.forex_spot_em())

print("\n## 沪港通持股（替代接口）")
run("hsgt_individual_600519", lambda: ak.stock_hsgt_individual_em(symbol="600519"))
run("hsgt_hold_em_retry", lambda: ak.stock_hsgt_hold_stock_em(market="北向", indicator="今日排行"))

print("\n## 快讯/新闻补充")
run("stock_info_global_em_again", lambda: ak.stock_info_global_em())
run("stock_info_global_cls_again", lambda: ak.stock_info_global_cls(symbol="全部"))

print("\n## 中债收益率：只取国债曲线（长区间）")
try:
    t0 = time.time()
    df = ak.bond_china_yield(start_date="20150101", end_date="20261018")
    ms = int((time.time() - t0) * 1000)
    print(f"RESULT|bond_china_yield_long|OK|ms={ms}|shape={df.shape}|"
          f"curves={df['曲线名称'].unique()[:8] if '曲线名称' in df.columns else 'NA'}|"
          f"min_date={pd.to_datetime(df['日期']).min() if '日期' in df.columns else ''}|"
          f"max_date={pd.to_datetime(df['日期']).max() if '日期' in df.columns else ''}")
except Exception as e:  # noqa: BLE001
    print(f"RESULT|bond_china_yield_long|FAIL|err={type(e).__name__}: {str(e)[:250]}")
print("\n# done")
