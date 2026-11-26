"""多臂对照评分：把 live_arms.json 换算成论文主表（docs/23 §3、§4）。

用法：
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/score_arms.py \
        artifacts/bench/arms_live.json

真值：`contracts/golden-vectors/cfsi_stress_pca_q90_reference.json` 的 y_20
（未来 20 交易日内进入 high_stress，含当日——黄金向量定义）。

不编造数字：缺哪个臂就标 n/a 并写明原因；样本不足不给显著性主张。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / 'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json'
LEVEL_ORDER = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}


def load_y20() -> dict[str, int]:
    rows = json.loads(GOLDEN.read_text(encoding='utf-8'))['rows']
    out = {}
    for row in rows:
        y = row.get('y_20')
        if y is not None:
            out[row['date']] = int(y)
    return out


def binary(level: str | None, threshold: str) -> int | None:
    """把四档等级二值化（>= threshold 视为「预警」）。"""
    if level is None or level not in LEVEL_ORDER:
        return None
    return 1 if LEVEL_ORDER[level] >= LEVEL_ORDER[threshold] else 0


def mcnemar(b: list[int], c: list[int]) -> dict:
    """配对 McNemar（精确二项检验，小样本适用）。"""
    n01 = sum(1 for x, y in zip(b, c) if x == 0 and y == 1)
    n10 = sum(1 for x, y in zip(b, c) if x == 1 and y == 0)
    n = n01 + n10
    if n == 0:
        return {'b': n01, 'c': n10, 'p': None, 'note': '无不一致对'}
    k = min(n01, n10)
    # 双侧精确二项
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n) * 2
    return {'b': n01, 'c': n10, 'p': min(1.0, p)}


def arm_metrics(preds: list[int], truth: list[int]) -> dict:
    tp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 1)
    fp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 1)
    tn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 0)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    base = (tp + fn) / len(truth) if truth else None
    lift = precision / base if precision and base else None
    return {
        'n': len(truth), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': precision, 'recall': recall, 'base_rate': base, 'lift': lift,
        'trigger_rate': (tp + fp) / len(truth) if truth else None,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    data = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    y20 = load_y20()

    rows = []
    for record in data['records']:
        day = record['as_of']
        if day not in y20:
            continue
        row = {'as_of': day, 'y20': y20[day]}
        for arm, payload in record['arms'].items():
            row[arm] = payload.get('risk')
            row[f'{arm}_ms'] = payload.get('ms')
            row[f'{arm}_tokens'] = payload.get('tokens')
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        print('没有可用时点（黄金向量里找不到对应 y_20）')
        return 2

    print(f'时点数 {len(frame)}；正例 {int(frame["y20"].sum())}'
          f'（基准发生率 {frame["y20"].mean():.3f}）\n')

    arms = [a for a in ('A', 'single', 'independent', 'collaborative')
            if a in frame.columns]
    threshold = 'high'  # 「高压力预警」= high 及以上
    results = {}
    print(f'{"臂":<16}{"n":>4}{"prec":>8}{"recall":>8}{"lift":>8}'
          f'{"触发率":>8}{"ms":>9}{"tokens":>8}')
    for arm in arms:
        pairs = [(binary(lv, threshold), int(y))
                 for lv, y in zip(frame[arm], frame['y20'])
                 if binary(lv, threshold) is not None]
        if not pairs:
            print(f'{arm:<16} 无有效预测')
            continue
        preds = [p for p, _ in pairs]
        truth = [t for _, t in pairs]
        m = arm_metrics(preds, truth)
        ms = frame[f'{arm}_ms'].dropna()
        tok = frame[f'{arm}_tokens'].dropna() if f'{arm}_tokens' in frame else pd.Series()
        results[arm] = m
        print(f'{arm:<16}{m["n"]:>4}'
              f'{(m["precision"] or 0):>8.3f}{(m["recall"] or 0):>8.3f}'
              f'{(m["lift"] or 0):>8.3f}{(m["trigger_rate"] or 0):>8.3f}'
              f'{(ms.mean() if len(ms) else 0):>9.0f}'
              f'{(tok.mean() if len(tok) else 0):>8.0f}')

    # 配对比较：单模型 vs 协同（这是论文的核心问题）。
    print()
    for base_arm in ('A', 'single', 'independent'):
        if base_arm not in frame.columns or 'collaborative' not in frame.columns:
            continue
        pairs = [(binary(a, threshold), binary(b, threshold), int(y))
                 for a, b, y in zip(frame[base_arm], frame['collaborative'],
                                    frame['y20'])
                 if binary(a, threshold) is not None
                 and binary(b, threshold) is not None]
        if len(pairs) < 30:
            print(f'{base_arm} vs collaborative：n={len(pairs)} < 30，'
                  '样本不足，不作显著性主张')
            continue
        # 配对正确性
        correct_a = [int(pa == y) for pa, _, y in pairs]
        correct_c = [int(pc == y) for _, pc, y in pairs]
        test = mcnemar(correct_a, correct_c)
        print(f'{base_arm} vs collaborative：n={len(pairs)} '
              f'仅{base_arm}对 {test["b"]} / 仅协同对 {test["c"]} '
              f'p={test["p"]:.4f}' if test['p'] is not None
              else f'{base_arm} vs collaborative：无不一致对')

    # A 组结构性泄漏（论文里最硬的一条）。
    leaks = [len(r['arms']['A'].get('future_data_series') or {})
             for r in data['records'] if 'A' in r['arms']]
    if leaks:
        print(f'\nA 组结构性泄漏：{sum(1 for v in leaks if v > 0)}/{len(leaks)} '
              f'个时点拿到了晚于评估日的行情（平均 {sum(leaks)/len(leaks):.1f} 条序列）')

    out = Path(argv[1]).with_suffix('.scored.json')
    out.write_text(json.dumps({'threshold': threshold, 'arms': results,
                               'n_days': len(frame)}, ensure_ascii=False,
                              indent=1, default=str), encoding='utf-8')
    print(f'\n已写入 {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
