"""校验已锁定的回归断言（docs/23 §5）。跑完 arms.py 后执行。

用法：
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/verify.py artifacts/bench/arms.json

退出码 0 = 全部通过；1 = 有断言失败（实现偏离口径）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

# docs/23 §5 锁定的断言（容差见括号）
ASSERTIONS = [
    ('capital_linkage_csi300_northbound', 'precision', 0.7941176470588235, 1e-6),
    ('capital_linkage_csi300_northbound', 'recall', 0.17763157894736842, 1e-6),
    ('capital_linkage_csi300_northbound', 'lift', 2.0828173374613, 1e-6),
    ('dimension_dispersion', 'precision', 0.6513761467889908, 1e-6),
    ('dimension_dispersion', 'recall', 0.31140350877192985, 1e-6),
    ('dimension_dispersion', 'lift', 1.7084339288588442, 1e-6),
]

# walk-forward 逐年 lift（docs/18 §7.1 / docs/20 §4），容差 1e-3
WF_EXPECTED = {
    'capital_linkage_csi300_northbound': {
        2019: 0.3961, 2020: 1.9858, 2021: 1.0163,
        2022: 1.2941, 2023: 1.1382, 2024: 0.0, 2025: 0.0, 2026: 0.0,
    },
    'dimension_dispersion': {
        2019: 3.1688, 2020: 1.5855, 2021: 1.5, 2022: 1.2238,
        2023: 1.0884, 2024: 1.8681, 2025: 1.8458,
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('report')
    args = ap.parse_args()
    r = json.load(open(args.report, encoding='utf-8'))
    singles = r['singles']
    fails, checks = [], 0

    def check(name: str, got: float | None, exp: float, tol: float) -> None:
        nonlocal checks
        checks += 1
        if got is None:
            fails.append(f'{name}: 缺失')
            return
        diff = abs(got - exp)
        if diff > tol:
            fails.append(f'{name}: got={got:.6f} exp={exp:.6f} diff={diff:.2e}')

    for key, field, exp, tol in ASSERTIONS:
        check(f'{key}.{field}', singles[key]['oos'][field], exp, tol)

    for key, years in WF_EXPECTED.items():
        rows = {row['year']: row['lift'] for row in singles[key]['walk_forward']['rows']}
        for year, exp in years.items():
            check(f'{key}.wf[{year}]', rows.get(year), exp, 1e-3)

    # 峰值 h
    checks += 1
    peak = singles['capital_linkage_csi300_northbound']['lead_profile']['peak_h']
    if peak != 40:
        fails.append(f'capital_linkage peak_h: got={peak} exp=40')
    checks += 1
    peak = singles['dimension_dispersion']['lead_profile']['peak_h']
    if peak != 0:
        fails.append(f'dimension_dispersion peak_h: got={peak} exp=0（同期型）')

    # 水平口径必须失效
    lv = r['level_vs_returns']
    checks += 1
    ratio = lv['levels']['ratio']
    if ratio is None or not (0.9 <= ratio <= 1.2):
        fails.append(f'水平口径 ratio 应在 1.0 附近：got={ratio}')
    checks += 1
    p = lv['levels']['perm_p_one_sided']
    if p is not None and p < 0.05:
        fails.append(f'水平口径不应显著：p={p}')
    checks += 1
    if lv['returns']['ratio'] is None or lv['returns']['ratio'] < 2.0:
        fails.append(f'变化率口径应有明显区分度：ratio={lv["returns"]["ratio"]}')

    # 数据新鲜度
    fresh = {f['series_id']: f['last_available'] for f in r['freshness']}
    for sid, exp in [
        ('crossborder.flows.northbound_net', '2024-08-16'),
        ('crossborder.flows.southbound_net', '2025-09-30'),
        ('rates.credit.aa_spread', '2025-09-30'),
        ('market.global.vix', '2026-10-27'),
        ('market.global.sp500', '2026-10-27'),
    ]:
        checks += 1
        if fresh.get(sid) != exp:
            fails.append(f'freshness {sid}: got={fresh.get(sid)} exp={exp}')

    # 哈希口径：分析层的 evidence_id 必须与 contracts 黄金向量逐字节一致
    hv = C.REPO / 'contracts/golden-vectors/hash_vectors.json'
    if hv.exists():
        for v in json.load(hv.open(encoding='utf-8'))['vectors']:
            ih = C.inputs_hash(v['tool'], v['version'], v['as_of'], v['params'])
            eid = C.evidence_id(v['tool'], v['version'], v['as_of'],
                                v['params'])[0]
            checks += 1
            if ih != v['inputs_hash'] or eid != v['evidence_id']:
                fails.append(f'hash vector {v["name"]}: 与 contracts 黄金向量不一致')

    for msg in fails:
        print(f'FAIL {msg}')
    print(f'\n{checks - len(fails)}/{checks} 通过')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
