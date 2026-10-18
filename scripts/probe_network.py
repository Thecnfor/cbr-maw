# -*- coding: utf-8 -*-
"""CBR-MAW raw HTTP probe (stdlib only, works in main env without requests).

Usage: <python> scripts/probe_network.py
Prints machine-readable blocks: RESULT|<source>|OK/FAIL|key=value...
Run:  python scripts/probe_network.py > docs/research/probe_network.log 2>&1
"""
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA,
        "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=15, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or HDRS, data=data)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(enc, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
            return dict(ok=True, status=r.status, ms=int((time.time() - t0) * 1000),
                        len=len(raw), text=text, ctype=r.headers.get("Content-Type", ""))
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, status=getattr(e, "code", None),
                    ms=int((time.time() - t0) * 1000), len=0, text="",
                    err=f"{type(e).__name__}: {e}")


def emit(name, res, note=""):
    status = "OK" if res["ok"] else "FAIL"
    print(f"RESULT|{name}|{status}|status={res.get('status')}|ms={res['ms']}|len={res['len']}"
          + (f"|err={res.get('err')}" if not res["ok"] else "") + (f"|note={note}" if note else ""))


def json_body(res):
    if not res["ok"]:
        return None
    try:
        return json.loads(res["text"])
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- eastmoney
def probe_eastmoney():
    print("\n## eastmoney push2")
    quotes = {
        "hs300": "1.000300", "sse": "1.000001", "hsi": "100.HSI",
        "usd_cny_133": "133.USDCNY", "usd_cnh_133": "133.USDCNH",
        "usd_cny_119": "119.USDCNY", "cn_10y_100": "100.CN10Y",
        "us_10y_100": "100.US10Y", "us_10y_101": "101.US10Y",
    }
    for name, secid in quotes.items():
        u = (f"https://push2.eastmoney.com/api/qt/stock/get?"
             f"secid={secid}&fields=f43,f57,f58,f60,f170,f169")
        r = fetch(u, timeout=10)
        j = json_body(r)
        data = (j or {}).get("data")
        if data:
            print(f"RESULT|em_quote_{name}|OK|secid={secid}|"
                  f"code={data.get('f57')}|name={data.get('f58')}|"
                  f"price_raw={data.get('f43')}|prev={data.get('f60')}|pct_raw={data.get('f170')}")
        else:
            print(f"RESULT|em_quote_{name}|FAIL|secid={secid}|err={r.get('err')}|raw={r['text'][:120]!r}")
    # 沪深港通资金流
    u = ("https://push2.eastmoney.com/api/qt/kamt/get?"
         "fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56")
    r = fetch(u, timeout=10)
    print("RESULT|em_kamt|%s|%s" % ("OK" if r["ok"] else "FAIL",
                                   (r["text"][:500] if r["ok"] else r.get("err"))))
    # K线（沪深300/HSI）: 日线 不复权
    for name, secid in [("hs300", "1.000300"), ("hsi", "100.HSI")]:
        u = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
             f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
             "fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=0"
             "&beg=20240101&end=20261231")
        r = fetch(u, timeout=15)
        j = json_body(r)
        klines = ((j or {}).get("data") or {}).get("klines") or []
        print(f"RESULT|em_kline_{name}|{'OK' if klines else 'FAIL'}|n={len(klines)}|"
              f"first={klines[0] if klines else ''}|last={klines[-1] if klines else ''}")
    # 新闻列表接口（需 req_trace）
    u = ("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?"
         "client=web&biz=web_news_col&column=345&order=1&needInteractData=0"
         "&page_index=1&page_size=3&req_trace=" + str(int(time.time() * 1000)))
    r = fetch(u, timeout=10)
    j = json_body(r)
    items = (((j or {}).get("data") or {}).get("list")) or []
    print(f"RESULT|em_news|{'OK' if items else 'FAIL'}|n={len(items)}|"
          f"sample={json.dumps(items[:1], ensure_ascii=False)[:300]}|"
          f"err={(r.get('err') or r['text'][:150]) if not items else ''}")
    # 快讯接口
    u = ("https://np-weblist.eastmoney.com/comm/web/getFastNewsList?"
         "client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=3&req_trace="
         + str(int(time.time() * 1000)))
    r = fetch(u, timeout=10)
    j = json_body(r)
    items = (((j or {}).get("data") or {}).get("fastNewsList")) or []
    print(f"RESULT|em_fastnews|{'OK' if items else 'FAIL'}|n={len(items)}|"
          f"sample={json.dumps(items[:1], ensure_ascii=False)[:300]}")


# ---------------------------------------------------------------- yahoo
def probe_yahoo():
    print("\n## yahoo finance chart API (yfinance backend)")
    syms = ["^GSPC", "^VIX", "^HSI", "000300.SS", "CNY=X", "CNH=X", "^TNX", "^MOVE", "^VHSI"]
    for sym in syms:
        u = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             f"{urllib.parse.quote(sym)}?interval=1d&range=5d")
        r = fetch(u, timeout=15)
        j = json_body(r)
        result = (((j or {}).get("chart") or {}).get("result"))
        if result:
            res0 = result[0]
            ts = res0.get("timestamp") or []
            closes = ((res0.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            last = next((c for c in reversed(closes) if c is not None), None)
            print(f"RESULT|yahoo_{sym}|OK|n={len(ts)}|last={last}|"
                  f"ts_last={time.strftime('%Y-%m-%d', time.gmtime(ts[-1])) if ts else ''}")
        else:
            err = ((j or {}).get("chart") or {}).get("error")
            print(f"RESULT|yahoo_{sym}|FAIL|err={err}|http={r.get('status')}")


# ---------------------------------------------------------------- FRED
def probe_fred():
    print("\n## FRED")
    series = ["VIXCLS", "DGS10", "BAMLH0A0HYM2", "BAMLC0A0CM", "DEXCHUS", "T10Y2Y"]
    cands = [
        lambda s: f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}",
        lambda s: f"https://fredgraph.stlouisfed.org/graph/fredgraph.csv?id={s}",
    ]
    for s in series:
        for i, mk in enumerate(cands):
            r = fetch(mk(s), timeout=25)
            if r["ok"] and "DATE" in r["text"][:200]:
                lines = [x for x in r["text"].strip().splitlines() if x]
                print(f"RESULT|fred_{s}|OK|via=cand{i}|n={len(lines)-1}|"
                      f"head={lines[1] if len(lines) > 1 else ''}|"
                      f"tail={lines[-1] if len(lines) > 1 else ''}")
                break
            print(f"RESULT|fred_{s}|FAIL|via=cand{i}|status={r.get('status')}|"
                  f"ms={r['ms']}|err={r.get('err')}")
    # GDELT
    print("\n## GDELT")
    q = urllib.parse.quote('("People\'s Bank of China" OR "PBOC") (rate OR policy)')
    u = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&maxrecords=5&format=json&sort=datedesc"
    ok = False
    for attempt in range(3):
        r = fetch(u, timeout=30)
        j = json_body(r)
        arts = (j or {}).get("articles") if isinstance(j, dict) else None
        if arts:
            ok = True
            print(f"RESULT|gdelt|OK|attempt={attempt+1}|ms={r['ms']}|n={len(arts)}|"
                  f"sample={arts[0].get('title', '')[:80]}|seendate={arts[0].get('seendate')}")
            break
        time.sleep(2)
    if not ok:
        print(f"RESULT|gdelt|FAIL|ms={r['ms']}|status={r.get('status')}|err={r.get('err')}|"
              f"raw={r['text'][:200]!r}")


# ---------------------------------------------------------------- policy sites
DATE_RE = re.compile(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})")


def probe_policy():
    print("\n## policy / news list pages")
    pages = {
        "pbc_goutong": "http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        "pbc_huobizhengce": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html",
        "csrc_news": "http://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
        "safe_news": "https://www.safe.gov.cn/safe/whxw/index.html",
        "gov_zuixin": "http://www.gov.cn/zhengce/zuixin/",
        "sina_roll_news": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=5&page=1",
        "em_news_home": "https://finance.eastmoney.com/",
    }
    for name, u in pages.items():
        r = fetch(u, timeout=20)
        if not r["ok"]:
            print(f"RESULT|page_{name}|FAIL|status={r.get('status')}|ms={r['ms']}|err={r.get('err')}")
            continue
        text = r["text"]
        if name == "sina_roll_news":
            j = json_body(r)
            items = (((j or {}).get("result") or {}).get("data")) or []
            print(f"RESULT|page_{name}|OK|status={r['status']}|ms={r['ms']}|len={r['len']}|"
                  f"json_items={len(items)}|sample={json.dumps(items[:1], ensure_ascii=False)[:250]}")
            continue
        hrefs = re.findall(r'href="([^"]+)"[^>]*>([^<]{6,80})<', text)
        dated = sum(1 for h, t in hrefs if DATE_RE.search(t))
        arts = [(h, t.strip()) for h, t in hrefs
                if re.search(r"/\d{6,}|/20\d{2}", h) and len(t.strip()) > 5][:3]
        js = re.findall(r'(?:src|url)\s*[:=]\s*["\']([^"\']+\.(?:js|json)[^"\']*)["\']', text)[:5]
        print(f"RESULT|page_{name}|OK|status={r['status']}|ms={r['ms']}|len={r['len']}|"
              f"links={len(hrefs)}|dated={dated}|sample_links={json.dumps(arts, ensure_ascii=False)[:300]}|"
              f"js={js}")


if __name__ == "__main__":
    t0 = time.time()
    print(f"# probe_network start {time.strftime('%Y-%m-%d %H:%M:%S')}")
    for fn in (probe_eastmoney, probe_yahoo, probe_fred, probe_policy):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"RESULT|{fn.__name__}|FAIL|unexpected={type(e).__name__}: {e}")
    print(f"\n# done in {int(time.time() - t0)}s")
