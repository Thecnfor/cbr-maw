#!/usr/bin/env python3
"""两组条件对照（配对 McNemar + Wilson CI）。

用于「记忆开 / 记忆关」这类同一臂、不同开关的对照：两个产物文件的
`records[].arms` 各只有一臂，本脚本按 `as_of` 配对后比较。

用法：
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/compare_conditions.py \
        --a artifacts/bench/mem_on/console.json --label-a 记忆开 \
        --b artifacts/bench/mem_off/console.json --label-b 记忆关

规则：
- 只用两边都有有效 risk 的时点（缺失即缺失，不补值）；
- 正例真值来自 golden y_20，与其他脚本一致；
- n < 30 时只报描述统计，不给显著性主张。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[3] / 'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json'
LEVEL_ORDER = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}


def load(records: list[dict]) -> dict[str, dict]:
    out = {}
    for record in records:
        for arm, payload in record.get('arms', {}).items():
            out[record['as_of']] = payload
            break
    return out


def binary(level: str | None, threshold: str) -> int | None:
    if level is None or level not in LEVEL_ORDER:
        return None
    return 1 if LEVEL_ORDER[level] >= LEVEL_ORDER[threshold] else 0


def metrics(preds: list[int], truth: list[int]) -> dict:
    tp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 1)
    fp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 1)
    tn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 0)
    n = len(truth)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    base = (tp + fn) / n if n else None
    return {
        'n': n, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': precision, 'recall': recall,
        'lift': (precision / base) if precision and base else None,
        'balanced_accuracy': ((tp / (tp + fn)) + (tn / (tn + fp))) / 2
        if (tp + fn) and (tn + fp) else None,
    }


def mcnemar(b: int, c: int) -> float | None:
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--a', required=True)
    parser.add_argument('--label-a', default='A')
    parser.add_argument('--b', required=True)
    parser.add_argument('--label-b', default='B')
    parser.add_argument('--threshold', default='high')
    args = parser.parse_args()

    golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
    truth = {r['date']: int(r['y_20']) for r in golden['rows'] if r.get('y_20') is not None}

    a = load(json.loads(Path(args.a).read_text(encoding='utf-8'))['records'])
    b = load(json.loads(Path(args.b).read_text(encoding='utf-8'))['records'])

    shared = sorted(set(a) & set(b) & set(truth))
    pa, pb, y = [], [], []
    for day in shared:
        va = binary(a[day].get('risk'), args.threshold)
        vb = binary(b[day].get('risk'), args.threshold)
        if va is None or vb is None:
            continue
        pa.append(va)
        pb.append(vb)
        y.append(truth[day])

    if not pa:
        print('没有可配对时点')
        return 2

    ma, mb = metrics(pa, y), metrics(pb, y)
    print(f'配平时点 {len(pa)}（阈值 {args.threshold}）\n')
    print(f'{"条件":<12}{"n":>5}{"prec":>8}{"recall":>8}{"lift":>8}{"balacc":>9}')
    for label, m in ((args.label_a, ma), (args.label_b, mb)):
        print(f'{label:<12}{m["n"]:>5}'
              f'{(m["precision"] or 0):>8.3f}{(m["recall"] or 0):>8.3f}'
              f'{(m["lift"] or 0):>8.3f}{(m["balanced_accuracy"] or 0):>9.3f}')

    # 配对：按「是否判对」做 McNemar
    only_a = sum(1 for x, yy, t in zip(pa, pb, y) if x == t and yy != t)
    only_b = sum(1 for x, yy, t in zip(pa, pb, y) if yy == t and x != t)
    p = mcnemar(only_a, only_b)
    print(f'\nMcNemar：仅{args.label_a}对 {only_a} / 仅{args.label_b}对 {only_b}'
          f' → p={p:.4f}' if p is not None else '\nMcNemar：无配对不一致')
    if len(pa) < 30:
        print('n<30：不作显著性主张')
    delta = (ma['balanced_accuracy'] or 0) - (mb['balanced_accuracy'] or 0)
    print(f'均衡准确率差（{args.label_a} − {args.label_b}）：{delta:+.3f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
