# -*- coding: utf-8 -*-
"""CBR-MAW consolidated fast probe (round 3): only slow/uncertain items left.

Run: .venv-probe\\Scripts\\python.exe -u scripts\\probe_final.py
Writes plain lines to stdout; redirect to docs/research/probe_final.log.
"""
import json
import re
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


def get(url, timeout=15):
    t0 = time.time()
    try:
        r = requests.get(url, headers=H, timeout=timeout)
        return dict(ok=True, http=r.status_code, ms=int((time.time() - t0) * 1000),
                    text=r.text, len=len(r.content))
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, http=None, ms=int((time.time() - t0) * 1000),
                    text="", len=0, err=f"{type(e).__name__}: {str(e)[:180]}")


print(f"# probe_final {time.strftime('%Y-%m-%d %H:%M:%S')}")

print("\n## 1. yahoo extras (global risk factors)")
for sym in ["^VIX9D", "^VIX3M", "^SKEW", "HG=F", "GC=F", "CL=F", "DX-Y.NYB", "^N225", "^HSI"]:
    q = urllib.parse.quote(sym)
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=1d&range=5d")
    try:
        j = json.loads(r["text"]) if r["ok"] else {}
        res = (j.get("chart") or {}).get("result")
        last = None
        if res:
            closes = res[0]["indicators"]["quote"][0]["close"]
            last = next((c for c in reversed(closes) if c is not None), None)
        print(f"RESULT|yahoo_extra|{sym}|{'OK' if res else 'FAIL'}|http={r['http']}|ms={r['ms']}|last={last}")
    except Exception as e:  # noqa: BLE001
        print(f"RESULT|yahoo_extra|{sym}|FAIL|{type(e).__name__}: {str(e)[:120]}")

print("\n## 2. GDELT (retry 3x)")
q = urllib.parse.quote('("People\'s Bank of China" OR PBOC) (rate OR policy)')
u = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&maxrecords=5&format=json&sort=datedesc"
for i in range(3):
    r = get(u, timeout=35)
    try:
        j = json.loads(r["text"])
        arts = j.get("articles") or []
    except Exception:  # noqa: BLE001
        arts = []
    if arts:
        print(f"RESULT|gdelt|OK|attempt={i+1}|ms={r['ms']}|n={len(arts)}|"
              f"sample={arts[0].get('title', '')[:80]}|seendate={arts[0].get('seendate')}")
        break
    print(f"RESULT|gdelt|RETRY|attempt={i+1}|http={r['http']}|ms={r['ms']}|"
          f"body={r['text'][:120]!r}")
    time.sleep(2)

print("\n## 3. policy list pages: article extraction test")
pages = {
    "PBOC_news": "http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
    "PBOC_MP": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html",
    "SAFE_news": "https://www.safe.gov.cn/safe/whxw/index.html",
    "CSRC_xwfb": "http://www.csrc.gov.cn/csrc/xwfb/index.shtml",
    "CSRC_yw": "http://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml",
}
for name, u in pages.items():
    r = get(u, timeout=20)
    if not r["ok"]:
        print(f"RESULT|page|{name}|FAIL|http={r['http']}|err={r.get('err')}")
        continue
    text = r["text"]
    # generic: anchor with title attr + href, or text link with 20xx date nearby
    items = re.findall(r'href="([^"]+)"[^>]*title="([^"]{8,90})"', text)
    dated = re.findall(r"20\d{2}[-年./]\d{1,2}[-月./]\d{1,2}", text)
    print(f"RESULT|page|{name}|OK|http={r['http']}|len={r['len']}|ms={r['ms']}|"
          f"titled_links={len(items)}|dates={len(dated)}|sample={json.dumps(items[:2], ensure_ascii=False)[:260]}")

print("\n## 4. 国务院政策文件库 JSON API")
u = ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw&q=%E9%87%91%E8%9E%8D"
     "&timetype=timeqb&mintime=&maxtime=&sort=pubtime&sortType=1&searchfield=title"
     "&pcodeJiguan=&childtype=&subchildtype=&tsbq=&pubtimeyear=&puborg=&pcodeYear=&pcodeNum="
     "&filetype=&p=1&n=3&inpro=&bmfl=&dup=&orpro=&type=gwyzcwjk")
r = get(u, timeout=25)
try:
    j = json.loads(r["text"])
    lst = (((j.get("searchVO") or {}).get("listVO")) or [])
    print(f"RESULT|govlib|{'OK' if lst else 'FAIL'}|http={r['http']}|ms={r['ms']}|n={len(lst)}|"
          f"sample={json.dumps([{k: x.get(k) for k in ('title', 'pubtimeStr', 'pcode', 'id')} for x in lst[:2]], ensure_ascii=False)}")
except Exception as e:  # noqa: BLE001
    print(f"RESULT|govlib|FAIL|{type(e).__name__}: {str(e)[:120]}|body={r['text'][:150]!r}")

print("\n## 5. eastmoney: HSGT kamt + USDCNH kline + 中债10Y?")
r = get("https://push2.eastmoney.com/api/qt/kamt/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56")
print(f"RESULT|em_kamt|{'OK' if r['ok'] else 'FAIL'}|http={r['http']}|ms={r['ms']}|body={r['text'][:400]}")
r = get("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=133.USDCNH"
        "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=0"
        "&beg=20110101&end=20261018")
try:
    j = json.loads(r["text"])
    kl = ((j.get("data") or {}).get("klines")) or []
    print(f"RESULT|em_usdcnh_kline|{'OK' if kl else 'FAIL'}|http={r['http']}|ms={r['ms']}|"
          f"n={len(kl)}|first={kl[0] if kl else ''}|last={kl[-1] if kl else ''}")
except Exception as e:  # noqa: BLE001
    print(f"RESULT|em_usdcnh_kline|FAIL|{type(e).__name__}: {str(e)[:120]}")

print("\n# done")
