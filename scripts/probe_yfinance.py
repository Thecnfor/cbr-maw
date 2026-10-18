# -*- coding: utf-8 -*-
"""CBR-MAW yfinance probe. Run inside .venv-probe.

Usage: .venv-probe\\Scripts\\python.exe scripts\\probe_yfinance.py
Checks history depth, timezone handling, fields for global risk factors.
"""
import time

import pandas as pd
import yfinance as yf

print(f"# yfinance {yf.__version__} | pandas {pd.__version__} | {time.strftime('%Y-%m-%d %H:%M:%S')}")

SYMS = ["^GSPC", "^VIX", "^HSI", "000300.SS", "CNY=X", "CNH=X", "^TNX", "^MOVE", "^VHSI"]

for sym in SYMS:
    t0 = time.time()
    try:
        df = yf.download(sym, start="2014-01-01", end="2026-10-19",
                         interval="1d", progress=False, auto_adjust=False,
                         threads=False)
        ms = int((time.time() - t0) * 1000)
        if df is None or len(df) == 0:
            print(f"RESULT|yf_{sym}|EMPTY|ms={ms}")
            continue
        cols = list(df.columns) if not isinstance(df.columns, pd.MultiIndex) else [c[-1] for c in df.columns]
        close = df["Close"]
        close = close.iloc[:, 0] if getattr(close, "ndim", 1) > 1 else close
        valid = close.dropna()
        print(f"RESULT|yf_{sym}|OK|ms={ms}|rows={len(df)}|cols={cols[:8]}|"
              f"first={valid.index[0].date() if len(valid) else ''}|"
              f"last={valid.index[-1].date() if len(valid) else ''}|"
              f"last_close={round(float(valid.iloc[-1]), 4) if len(valid) else ''}")
    except Exception as e:  # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        print(f"RESULT|yf_{sym}|FAIL|ms={ms}|err={type(e).__name__}: {str(e)[:220]}")

# FRED through pandas_datareader is not installed; test requests-based download from .venv
print("\n## FRED via requests (inside venv)")
try:
    import requests
    h = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "Chrome/126 Safari/537.36")}
    for sid in ["VIXCLS", "DGS10", "BAMLH0A0HYM2", "DEXCHUS"]:
        for url in [f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                    f"https://fredgraph.stlouisfed.org/graph/fredgraph.csv?id={sid}"]:
            t0 = time.time()
            try:
                r = requests.get(url, headers=h, timeout=30)
                ms = int((time.time() - t0) * 1000)
                ok = r.status_code == 200 and r.text.startswith("DATE")
                lines = [x for x in r.text.strip().splitlines() if x] if ok else []
                print(f"RESULT|fred_req_{sid}|{'OK' if ok else 'FAIL'}|ms={ms}|"
                      f"http={r.status_code}|n={max(len(lines) - 1, 0)}|"
                      f"tail={lines[-1] if lines else r.text[:120]!r}")
                if ok:
                    break
            except Exception as e:  # noqa: BLE001
                ms = int((time.time() - t0) * 1000)
                print(f"RESULT|fred_req_{sid}|FAIL|ms={ms}|err={type(e).__name__}: {str(e)[:200]}")
except ImportError:
    print("RESULT|fred_req|FAIL|requests not installed")

# yfinance sector/macro extras
print("\n## yfinance extras")
import urllib.parse
import urllib.request
for sym in ["^VIX9D", "^VIX3M", "^SKEW", "HG=F", "GC=F", "CL=F", "DX-Y.NYB", "^N225"]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&range=5d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": h["User-Agent"]})
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            j = json.loads(resp.read().decode("utf-8"))
        res = (j.get("chart") or {}).get("result")
        print(f"RESULT|yahoo_extra_{sym}|{'OK' if res else 'FAIL'}|"
              f"last={res[0]['indicators']['quote'][0]['close'][-1] if res else ''}")
    except Exception as e:  # noqa: BLE001
        print(f"RESULT|yahoo_extra_{sym}|FAIL|{type(e).__name__}: {str(e)[:120]}")
print("\n# done")
