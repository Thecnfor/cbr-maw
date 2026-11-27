#!/usr/bin/env python3
"""把真实基准产物渲染成论文用的 LaTeX 表与宏。

设计约束（docs/23、docs/24）：
- **不编造数字**：所有单元格来自 `artifacts/bench/console.json`，或（当它还不存在时）
  由 `shard*.json` 只读合并；缺指标一律写 `--`，绝不写 0 或占位值。
- **可重复**：不对产物做任何平滑、插补或选择性丢弃；同一输入得到同一输出。
- **不静默**：分片不完整、字段缺失、时点重复、分片口径不一致都会在 stderr 明说。
- **论文宏**：同时写 `tables/macros.tex`，供 `paper.tex` 里的
  `\\RESULT{arm}{metric}` 展开；这样正文与表格不会各写一份数字。

用法：
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/render_tables.py
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/render_tables.py \\
        --bench artifacts/bench --out docs/25-paper/tables

输出：
    main.tex        三臂主表（precision / recall / lift / 触发率 / CI / 耗时 / token）
    mcnemar.tex     配对 McNemar 精确检验（collaborative vs 其余两臂）
    coverage.tex    覆盖率与遮蔽计数（两张表）
    circularity.tex 标签循环性诊断（由黄金向量直接计算）
    macros.tex      \\RESULT 展开所需的全部宏
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / 'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json'
ARMS = ('collaborative', 'single', 'independent')
ARM_LABEL = {
    'collaborative': '协同 C',
    'single': '单智能体 S',
    'independent': '独立 I',
}
LEVEL_ORDER = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
BASE_ARMS = ('single', 'independent')


# ------------------------------------------------------------------ 数据读取


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        print(f'[warn] {path.name} 不是完整 JSON（{exc.msg}），按仍在写入跳过',
              file=sys.stderr)
        return None


def load_dataset(bench: Path) -> dict[str, Any]:
    """优先 console.json；不存在时只读合并 shard*.json。"""
    console = bench / 'console.json'
    if console.exists():
        data = _read_json(console)
        if data is None:
            raise SystemExit(f'✘ {console} 存在但无法解析；请等合并完成或删除损坏文件')
        records = data.get('records')
        if not isinstance(records, list):
            raise SystemExit(f'✘ {console} 缺少 records 数组')
        return {
            'source': console.name,
            'records': records,
            'dates': (data.get('sampling') or {}).get('dates') or [],
            'model': data.get('model'),
            'base_url': data.get('base_url'),
            'arms': data.get('arms'),
            'seed': (data.get('sampling') or {}).get('seed'),
            'pairs': (data.get('sampling') or {}).get('pairs'),
            'generated_at': data.get('generated_at'),
            'shards': data.get('shards') or [console.name],
            'partial': False,
        }

    pattern = re.compile(r'^shard(\d+)\.json$')
    paths = sorted(
        (p for p in bench.iterdir() if pattern.match(p.name)),
        key=lambda p: int(pattern.match(p.name).group(1)),  # type: ignore[union-attr]
    )
    if not paths:
        raise SystemExit(f'✘ 未找到 {console} 或 {bench}/shard*.json；先跑基准')

    print(f'[warn] 未找到 {console}；改为只读合并 {len(paths)} 个 shard*.json。\n'
          '       分片可能仍在写入，缺失时点不会补数，覆盖率只代表当前已有产物。',
          file=sys.stderr)

    base: dict[str, Any] | None = None
    records: dict[str, dict[str, Any]] = {}
    dates: dict[str, dict[str, Any]] = {}
    used: list[str] = []
    for path in paths:
        data = _read_json(path)
        if data is None:
            continue
        arm_list = data.get('arms')
        if not isinstance(arm_list, list):
            print(f'[warn] {path.name} 尚无 arms 字段，跳过', file=sys.stderr)
            continue
        meta = {
            'model': data.get('model'),
            'base_url': data.get('base_url'),
            'arms': arm_list,
            'seed': (data.get('sampling') or {}).get('seed'),
        }
        if base is None:
            base = meta
            base['pairs'] = (data.get('sampling') or {}).get('pairs')
        else:
            for key, value in meta.items():
                if value != base[key]:
                    raise SystemExit(
                        f'✘ {path.name}: {key} 与其他分片不一致'
                        f'（{value!r} vs {base[key]!r}）；拒绝混合不同实验口径')
        used.append(path.name)
        shard_records = data.get('records')
        if not isinstance(shard_records, list):
            print(f'[warn] {path.name} 尚无 records（运行刚开始），跳过',
                  file=sys.stderr)
            continue
        for record in shard_records:
            day = record.get('as_of')
            if not day:
                print(f'[warn] {path.name} 有一条记录缺 as_of，跳过', file=sys.stderr)
                continue
            if day in records:
                raise SystemExit(
                    f'✘ 时点重复：{day}（{path.name} 与其他分片重叠；不静默取其一）')
            records[day] = record
        for item in (data.get('sampling') or {}).get('dates') or []:
            if item.get('as_of'):
                dates[item['as_of']] = item

    if base is None:
        raise SystemExit('✘ 所有分片都不可读；没有可渲染的数据')

    gens = []
    for path in paths:
        try:
            gens.append(json.loads(path.read_text(encoding='utf-8')).get('generated_at'))
        except Exception:
            pass
    return {
        'source': '+'.join(used) + '（分片，部分产物）',
        'records': [records[k] for k in sorted(records)],
        'dates': [dates[k] for k in sorted(dates)],
        'model': base['model'],
        'base_url': base['base_url'],
        'arms': base['arms'],
        'seed': base['seed'],
        'pairs': base.get('pairs'),
        'generated_at': max((g for g in gens if g), default=None),
        'shards': used,
        'partial': True,
    }


def load_golden(path: Path = GOLDEN) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f'✘ 缺少黄金向量：{path}')
    return json.loads(path.read_text(encoding='utf-8'))


# ------------------------------------------------------------------ 指标（与 score_arms.py 同口径）


def binary(level: str | None, threshold: str) -> int | None:
    if level is None or level not in LEVEL_ORDER:
        return None
    return 1 if LEVEL_ORDER[level] >= LEVEL_ORDER[threshold] else 0


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def arm_metrics(preds: list[int], truth: list[int]) -> dict[str, Any]:
    tp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 1)
    fp = sum(1 for p, t in zip(preds, truth) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 1)
    tn = sum(1 for p, t in zip(preds, truth) if p == 0 and t == 0)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    base = (tp + fn) / len(truth) if truth else None
    lift = precision / base if precision is not None and base else None
    return {
        'n': len(truth), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': precision, 'recall': recall, 'base_rate': base, 'lift': lift,
        'trigger_rate': (tp + fp) / len(truth) if truth else None,
        'precision_ci95': wilson(tp, tp + fp) if tp + fp else None,
        'recall_ci95': wilson(tp, tp + fn) if tp + fn else None,
        'balanced_accuracy': (
            (tp / (tp + fn) + tn / (tn + fp)) / 2
            if (tp + fn) and (tn + fp) else None
        ),
    }


def mcnemar(a_correct: list[int], b_correct: list[int]) -> dict[str, Any]:
    """精确双侧 McNemar。b=仅 b 正确，c=仅 a 正确（与 score_arms 同口径）。"""
    n01 = sum(1 for x, y in zip(a_correct, b_correct) if x == 0 and y == 1)
    n10 = sum(1 for x, y in zip(a_correct, b_correct) if x == 1 and y == 0)
    n = n01 + n10
    if n == 0:
        return {'only_b': 0, 'only_a': 0, 'p': None, 'note': '无不一致对'}
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n) * 2
    return {'only_b': n01, 'only_a': n10, 'p': min(1.0, p)}


def holm(pvalues: list[float | None]) -> list[float | None]:
    indexed = [(p, i) for i, p in enumerate(pvalues) if p is not None]
    indexed.sort()
    m = len(indexed)
    out: list[float | None] = [None] * len(pvalues)
    running = 0.0
    for rank, (p, i) in enumerate(indexed):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out


def placebo_test(preds: list[int], truths: list[int], *, draws: int = 2000,
                 seed: int = 20261127) -> dict[str, Any]:
    """标签置换安慰剂：保持预测与正例数不变，打乱真值顺序后重算 lift。

    这不是重跑 LLM 的安慰剂，而是评分向量层面的零分布检验；它只能回答
    「该预测向量相对随机标签分配是否异常」，不能替代独立重跑。
    """
    if not preds or not truths or len(preds) != len(truths):
        return {'p': None, 'obs_lift': None, 'null_mean': None,
                'null_q95': None, 'draws': 0}
    n_pos = sum(truths)
    base = n_pos / len(truths)
    if base == 0:
        return {'p': None, 'obs_lift': None, 'null_mean': None,
                'null_q95': None, 'draws': 0}
    tp = sum(1 for p, t in zip(preds, truths) if p == 1 and t == 1)
    triggered = sum(preds)
    if triggered == 0:
        return {'p': None, 'obs_lift': None, 'null_mean': None,
                'null_q95': None, 'draws': 0}
    obs_lift = (tp / triggered) / base
    rng = random.Random(seed)
    null = []
    pool = list(truths)
    for _ in range(draws):
        rng.shuffle(pool)
        tp_i = sum(1 for p, t in zip(preds, pool) if p == 1 and t == 1)
        null.append((tp_i / triggered) / base)
    null.sort()
    ge = sum(1 for v in null if v >= obs_lift)
    q95 = null[min(len(null) - 1, int(round(0.95 * (len(null) - 1))))]
    return {
        'p': (1 + ge) / (draws + 1),
        'obs_lift': obs_lift,
        'null_mean': sum(null) / len(null),
        'null_q95': q95,
        'draws': draws,
    }


# ------------------------------------------------------------------ 统计汇总


def summarize(data: dict[str, Any], golden: dict[str, Any], threshold: str) -> dict[str, Any]:
    truth = {
        row['date']: int(row['y_20'])
        for row in golden.get('rows', [])
        if row.get('y_20') is not None
    }
    planned = [d for d in data['dates'] if d.get('as_of') in truth]
    if not planned:
        # console 合并产物可能没有 sampling.dates；退回记录日期。
        planned = [{'as_of': r['as_of']} for r in data['records'] if r['as_of'] in truth]
        print('[warn] 产物没有 sampling.dates，覆盖率分母改用「有真值的记录日」',
              file=sys.stderr)

    mismatched = 0
    rows_by_day = {r['as_of']: r for r in data['records'] if r.get('as_of')}
    for day, rec in rows_by_day.items():
        if day in truth and rec.get('y20') is not None and int(rec['y20']) != truth[day]:
            mismatched += 1
    if mismatched:
        print(f'[warn] {mismatched} 条记录的 y20 与黄金向量不一致；评分以黄金向量为准',
              file=sys.stderr)

    planned_total = len(planned)
    if data.get('pairs'):
        planned_total = max(planned_total, int(data['pairs']) * 2)

    per_arm: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        attempted = 0
        valid = 0
        null_risk = 0
        failures = 0
        partials = 0
        degraded_runs = 0
        degraded_roles = 0
        verify_present = 0
        verify_passed = 0
        verify_failed = 0
        leakage = 0
        unsupported = 0
        latencies: list[float] = []
        tokens: list[float] = []
        preds: list[int] = []
        truths: list[int] = []
        for day, rec in rows_by_day.items():
            payload = (rec.get('arms') or {}).get(arm)
            if not isinstance(payload, dict):
                continue
            attempted += 1
            if payload.get('failure'):
                failures += 1
            if payload.get('partial'):
                partials += 1
            degraded = payload.get('degraded') or []
            if degraded:
                degraded_runs += 1
                degraded_roles += len(degraded)
            verification = payload.get('verification') or {}
            if verification:
                verify_present += 1
                if verification.get('passed'):
                    verify_passed += 1
                else:
                    verify_failed += 1
                leakage += int(verification.get('leakage_events') or 0)
                unsupported += int(verification.get('unsupported_claims') or 0)
            level = payload.get('risk')
            pred = binary(level, threshold)
            if pred is None:
                null_risk += 1
            else:
                valid += 1
                if day in truth:
                    preds.append(pred)
                    truths.append(truth[day])
            if isinstance(payload.get('ms'), (int, float)):
                latencies.append(float(payload['ms']))
            if isinstance(payload.get('tokens'), (int, float)):
                tokens.append(float(payload['tokens']))
        metrics = arm_metrics(preds, truths) if truths else None
        per_arm[arm] = {
            'attempted': attempted,
            'valid': valid,
            'null_risk': null_risk,
            'planned': planned_total,
            'coverage': valid / planned_total if planned_total and attempted else None,
            'partial_rate': partials / attempted if attempted else None,
            'degraded_rate': degraded_runs / attempted if attempted else None,
            'degraded_roles': degraded_roles,
            'verify_pass': verify_passed / verify_present if verify_present else None,
            'verify_failed': verify_failed,
            'failures': failures,
            'leakage': leakage,
            'unsupported': unsupported,
            'latency_s': (sum(latencies) / len(latencies) / 1000.0) if latencies else None,
            'tokens': (sum(tokens) / len(tokens)) if tokens else None,
            'metrics': metrics,
            'preds': preds,
            'truths': truths,
        }

    # 配对检验：collaborative vs single / independent。
    comparisons: dict[str, dict[str, Any]] = {}
    for base_arm in BASE_ARMS:
        a_correct: list[int] = []
        b_correct: list[int] = []
        for day, rec in rows_by_day.items():
            if day not in truth:
                continue
            pa = (rec.get('arms') or {}).get(base_arm) or {}
            pc = (rec.get('arms') or {}).get('collaborative') or {}
            va = binary(pa.get('risk'), threshold)
            vc = binary(pc.get('risk'), threshold)
            if va is None or vc is None:
                continue
            y = truth[day]
            a_correct.append(int(va == y))
            b_correct.append(int(vc == y))
        test = mcnemar(a_correct, b_correct)
        comparisons[base_arm] = {
            'n': len(a_correct),
            'only_collab': test['only_b'],
            'only_base': test['only_a'],
            'p': test['p'],
            'note': test.get('note'),
        }
    ps = holm([comparisons[a]['p'] for a in BASE_ARMS])
    for arm, p_adj in zip(BASE_ARMS, ps):
        comparisons[arm]['p_holm'] = p_adj

    complete = (
        len(rows_by_day) >= planned_total
        and all(per_arm[arm]['attempted'] >= planned_total for arm in ARMS)
    )
    circularity = compute_circularity(golden)
    placebo = {
        arm: placebo_test(per_arm[arm]['preds'], per_arm[arm]['truths'])
        for arm in ARMS
    }
    return {
        'truth': truth,
        'planned': planned,
        'planned_total': planned_total,
        'complete': complete,
        'records': data['records'],
        'per_arm': per_arm,
        'comparisons': comparisons,
        'circularity': circularity,
        'placebo': placebo,
    }


def compute_circularity(golden: dict[str, Any]) -> dict[str, Any]:
    """标签循环性：high_stress 由 CFSI>τ 定义，与标签同源；并给更严格对照。

    两层对照：
    - 未来窗口 t+1..t+20：用来核验 y_20 本身是否含当日（一致即不含当日）；
    - 更严格标签 t+2..t+21：再推后一天，用来估计压力状态自相关带来的折扣。
    """
    rows = golden.get('rows') or []
    hs = [int(r.get('high_stress') or 0) for r in rows]
    y20 = [r.get('y_20') for r in rows]
    pairs = [(int(y), h) for y, h in zip(y20, hs) if y is not None]
    hs1 = [y for y, h in pairs if h == 1]
    hs0 = [y for y, h in pairs if h == 0]

    horizon = 20
    future_pairs: list[tuple[int, int]] = []
    agree = 0
    for i in range(len(rows) - horizon):
        y = y20[i]
        if y is None:
            continue
        future = 1 if any(hs[i + 1:i + 1 + horizon]) else 0
        future_pairs.append((future, hs[i]))
        agree += int(y == future)

    strict_pairs: list[tuple[int, int]] = []
    for i in range(len(rows) - horizon - 1):
        strict = 1 if any(hs[i + 2:i + 2 + horizon]) else 0
        strict_pairs.append((strict, hs[i]))
    s_hs1 = [s for s, h in strict_pairs if h == 1]
    s_hs0 = [s for s, h in strict_pairs if h == 0]

    def mean(values: list[int]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        'n': len(pairs),
        'n_future': len(future_pairs),
        'n_strict': len(strict_pairs),
        'n_agree': agree,
        'base_y20': mean([y for y, _ in pairs]),
        'base_strict': mean([s for s, _ in strict_pairs]),
        'p_y_hs1': mean(hs1),
        'p_y_hs0': mean(hs0),
        'p_strict_hs1': mean(s_hs1),
        'p_strict_hs0': mean(s_hs0),
        'n_hs1': len(hs1),
        'n_hs0': len(hs0),
    }

# ------------------------------------------------------------------ 格式化


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return '--'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return '--'
        return f'{value:.{digits}f}'
    return str(value)


def fmt_ci(ci: Any) -> str:
    if not ci or ci[0] is None or ci[1] is None:
        return '--'
    return f'[{ci[0]:.3f}, {ci[1]:.3f}]'


def fmt_p(p: Any) -> str:
    if p is None:
        return '--'
    return '$<$0.001' if p < 0.001 else f'{p:.3f}'


def fmt_seconds(value: Any) -> str:
    if value is None:
        return '--'
    return f'{value:.1f}'


def fmt_int(value: Any) -> str:
    if value is None:
        return '--'
    return f'{int(round(value))}'


def tex_escape(text: Any) -> str:
    if text is None:
        return '--'
    table = {
        '\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
        '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    return ''.join(table.get(ch, ch) for ch in str(text))


def verdict(n: int, p: float | None, p_holm: float | None) -> str:
    if p is None:
        return '无不一致对'
    if n < 30:
        return '样本不足'
    if p_holm is not None and p_holm < 0.05:
        return '显著'
    return '不显著'


# ------------------------------------------------------------------ 组装输出


def build_outputs(data: dict[str, Any], summary: dict[str, Any], threshold: str) -> tuple[dict[str, str], dict[str, str]]:
    per_arm = summary['per_arm']
    comparisons = summary['comparisons']
    circ = summary['circularity']

    macros: dict[str, str] = {
        'meta@source': tex_escape(
            data['source'].replace('（分片，部分产物）', '（分片，全部时点）')
            if summary['complete'] else data['source']),
        'meta@model': tex_escape(data['model']),
        'meta@base_url': tex_escape(data['base_url']),
        'meta@seed': fmt(data['seed']),
        'meta@threshold': tex_escape(threshold),
        'meta@n_planned': fmt(summary['planned_total']),
        'meta@n_records': fmt(len(summary['records'])),
        'meta@n_scored': fmt(len({r['as_of'] for r in summary['records'] if r['as_of'] in summary['truth']})),
        'meta@n_shards': fmt(len(data['shards'])),
        'meta@generated_at': tex_escape(data['generated_at']),
        'meta@partial': '否' if summary['complete'] else '是',
    }

    for arm in ARMS:
        item = per_arm[arm]
        metrics = item['metrics'] or {}
        values = {
            'planned': item['planned'],
            'attempted': item['attempted'],
            'valid': item['valid'],
            'coverage': item['coverage'],
            'null_risk': item['null_risk'],
            'failures': item['failures'],
            'partial_rate': item['partial_rate'],
            'degraded_rate': item['degraded_rate'],
            'degraded_roles': item['degraded_roles'],
            'verify_pass': item['verify_pass'],
            'verify_failed': item['verify_failed'],
            'leakage': item['leakage'],
            'unsupported': item['unsupported'],
            'latency_s': item['latency_s'],
            'tokens': item['tokens'],
            'n': metrics.get('n'),
            'tp': metrics.get('tp'),
            'fp': metrics.get('fp'),
            'fn': metrics.get('fn'),
            'tn': metrics.get('tn'),
            'precision': metrics.get('precision'),
            'precision_ci': fmt_ci(metrics.get('precision_ci95')),
            'recall': metrics.get('recall'),
            'recall_ci': fmt_ci(metrics.get('recall_ci95')),
            'lift': metrics.get('lift'),
            'trigger': metrics.get('trigger_rate'),
            'base_rate': metrics.get('base_rate'),
            'balacc': metrics.get('balanced_accuracy'),
        }
        for key, value in values.items():
            if key == 'precision_ci' or key == 'recall_ci':
                macros[f'{arm}@{key}'] = value
            elif key in ('planned', 'attempted', 'valid', 'null_risk', 'failures',
                         'degraded_roles', 'verify_failed', 'leakage', 'unsupported',
                         'n', 'tp', 'fp', 'fn', 'tn'):
                macros[f'{arm}@{key}'] = fmt_int(value)
            elif key in ('coverage', 'partial_rate', 'degraded_rate', 'verify_pass',
                         'precision', 'recall', 'lift', 'trigger', 'balacc'):
                macros[f'{arm}@{key}'] = fmt(value, 3)
            elif key == 'latency_s':
                macros[f'{arm}@{key}'] = fmt_seconds(value)
            elif key == 'tokens':
                macros[f'{arm}@tokens'] = fmt_int(value)
            else:
                macros[f'{arm}@{key}'] = fmt(value)

    for base in BASE_ARMS:
        item = comparisons[base]
        macros[f'mcnemar_{base}@n'] = fmt_int(item['n'])
        macros[f'mcnemar_{base}@only_collab'] = fmt_int(item['only_collab'])
        macros[f'mcnemar_{base}@only_base'] = fmt_int(item['only_base'])
        macros[f'mcnemar_{base}@p'] = fmt_p(item['p'])
        macros[f'mcnemar_{base}@p_holm'] = fmt_p(item.get('p_holm'))
        macros[f'mcnemar_{base}@verdict'] = tex_escape(
            verdict(item['n'], item['p'], item.get('p_holm')))

    for arm in ARMS:
        item = summary['placebo'][arm]
        macros[f'placebo_{arm}@p'] = fmt_p(item['p'])
        macros[f'placebo_{arm}@obs_lift'] = fmt(item['obs_lift'])
        macros[f'placebo_{arm}@null_mean'] = fmt(item['null_mean'])
        macros[f'placebo_{arm}@null_q95'] = fmt(item['null_q95'])
        macros[f'placebo_{arm}@draws'] = fmt_int(item['draws'])
        macros[f'placebo_{arm}@verdict'] = (
            '未执行（无触发或无真值）' if item['p'] is None
            else ('异常' if item['p'] < 0.05 else '不显著')
        )

    # ---------------- 结论句宏（正文用 \CONCLUSION 引用，不手写数字）
    # 规则：所有句子只陈述脚本可判定的事实；判定不成立时输出「不成立/无法判定」，
    # 而不是挑一个好看的说法。这样跑批完成后正文自动变成真实结论。
    collab = per_arm['collaborative']['metrics'] or {}
    single = per_arm['single']['metrics'] or {}
    indep = per_arm['independent']['metrics'] or {}

    def _delta(a, b):
        if a is None or b is None:
            return None
        return a - b

    bal_delta_single = _delta(collab.get('balanced_accuracy'),
                              single.get('balanced_accuracy'))
    bal_delta_indep = _delta(collab.get('balanced_accuracy'),
                             indep.get('balanced_accuracy'))
    p_single = comparisons['single'].get('p_holm')
    p_indep = comparisons['independent'].get('p_holm')
    enough = all((per_arm[a]['metrics'] or {}).get('n') is not None
                 and (per_arm[a]['metrics'] or {}).get('n') >= 30 for a in ARMS)

    def _verdict(delta, p):
        if delta is None or p is None or not enough:
            return '无法判定（样本不足或指标缺失）'
        if p < 0.05 and delta > 0:
            return '显著优于'
        if p < 0.05 and delta < 0:
            return '显著劣于'
        return '无显著差异'

    macros['concl@balacc_delta_single'] = (
        '--' if bal_delta_single is None else f'{bal_delta_single:+.3f}')
    macros['concl@balacc_delta_indep'] = (
        '--' if bal_delta_indep is None else f'{bal_delta_indep:+.3f}')
    macros['concl@vs_single'] = tex_escape(_verdict(bal_delta_single, p_single))
    macros['concl@vs_indep'] = tex_escape(_verdict(bal_delta_indep, p_indep))
    macros['concl@enough_n'] = '是' if enough else '否'

    # 成本对比：协同相对单智能体的 token 与耗时倍数。
    tok_ratio = None
    sec_ratio = None
    if single.get('n') and collab.get('n'):
        st = per_arm['single']['tokens']
        ct = per_arm['collaborative']['tokens']
        if st:
            tok_ratio = ct / st
        ss = per_arm['single']['latency_s']
        cs = per_arm['collaborative']['latency_s']
        if ss:
            sec_ratio = cs / ss
    macros['concl@token_ratio'] = '--' if tok_ratio is None else f'{tok_ratio:.2f}'
    macros['concl@latency_ratio'] = '--' if sec_ratio is None else f'{sec_ratio:.2f}'

    # 判别力同形判定：三臂预测向量是否逐点一致（协同无增量的最直接证据）。
    same_single = comparisons['single']['only_collab'] == 0 and comparisons['single']['only_base'] == 0
    same_indep = (comparisons['independent']['only_collab'] == 0
                  and comparisons['independent']['only_base'] == 0)
    if not enough:
        macros['concl@identical'] = '无法判定（样本不足）'
    elif same_single and same_indep:
        macros['concl@identical'] = '是（三臂在全部配对时点上预测一致）'
    elif same_single:
        macros['concl@identical'] = '与单智能体一致，与独立臂存在差异'
    else:
        macros['concl@identical'] = '否（存在配对不一致）'

    # 覆盖与降级：会不会「看起来跑完其实没跑」。
    min_cov = min((per_arm[a]['coverage'] or 0) for a in ARMS)
    macros['concl@min_coverage'] = fmt(min_cov, 3)
    max_degraded = max((per_arm[a]['degraded_rate'] or 0) for a in ARMS)
    macros['concl@max_degraded'] = fmt(max_degraded, 3)
    macros['concl@partial_any'] = (
        '是' if any((per_arm[a]['partial_rate'] or 0) > 0 for a in ARMS) else '否')

    for key in ('n', 'n_future', 'n_strict', 'n_hs1', 'n_hs0', 'n_agree'):
        macros[f'label@{key}'] = fmt_int(circ.get(key))
    for key in ('base_y20', 'base_strict', 'p_y_hs1', 'p_y_hs0',
                'p_strict_hs1', 'p_strict_hs0'):
        macros[f'label@{key}'] = fmt(circ.get(key), 3)

    # ---------------- main.tex
    n_short = [ARM_LABEL[a] for a in ARMS
               if (per_arm[a]['metrics'] or {}).get('n') is not None
               and (per_arm[a]['metrics'] or {}).get('n') < 30]
    short_note = ('另：' + '、'.join(n_short) + ' 的 $n<30$，按协议不作显著性主张。') if n_short else ''
    main_rows = []
    for arm in ARMS:
        item = per_arm[arm]
        m = item['metrics'] or {}
        main_rows.append(
            f"{ARM_LABEL[arm]} & {fmt_int(m.get('n'))} & {fmt(m.get('precision'))} & "
            f"{fmt_ci(m.get('precision_ci95'))} & {fmt(m.get('recall'))} & "
            f"{fmt(m.get('lift'))} & {fmt(m.get('trigger_rate'))} & "
            f"{fmt(m.get('balanced_accuracy'))} & {fmt_seconds(item['latency_s'])} & "
            f"{fmt_int(item['tokens'])} \\\\")
    base_note = '缺失指标（含无正例预测时的 precision）写作 \\texttt{--}，不以 0 代替。'
    if short_note:
        base_note += ' ' + short_note
    main = f"""% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。
% 数据源：{tex_escape(data['source'])}
% 生成时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec='seconds')}
\\begin{{table}}[t]
\\centering
\\caption{{三臂预警判别结果（二值化阈值：\\texttt{{{tex_escape(threshold)}}}；缺指标显示 \\texttt{{--}}）}}
\\label{{tab:main}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lrrrrrrrrr}}
\\toprule
臂 & $n$ & precision & 95\\% CI & recall & lift & 触发率 & 均衡准确率 & 耗时(s) & token \\\\
\\midrule
{chr(10).join(main_rows)}
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：$n$ 为进入评分的配对数；CI 为 precision 的 Wilson 95\\% 区间；
lift $=$ precision $/$ 基准发生率；耗时与 token 为各臂在全部已跑记录上的均值。
{base_note}
\\end{{table}}
"""

    # ---------------- mcnemar.tex
    mc_rows = []
    for base in BASE_ARMS:
        item = comparisons[base]
        mc_rows.append(
            f"{ARM_LABEL[base]} vs 协同 & {fmt_int(item['n'])} & "
            f"{fmt_int(item['only_collab'])} & {fmt_int(item['only_base'])} & "
            f"{fmt_p(item['p'])} & {fmt_p(item.get('p_holm'))} & "
            f"{verdict(item['n'], item['p'], item.get('p_holm'))} \\\\")
    mcnemar_tex = f"""% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。
\\begin{{table}}[t]
\\centering
\\caption{{配对 McNemar 精确检验（以协同臂为处理组；$b$/$c$ 为不一致对计数）}}
\\label{{tab:mcnemar}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lrrrrrr}}
\\toprule
比较 & $n$ & 仅协同正确 & 仅基线正确 & $p$ & Holm $p$ & 判定 \\\\
\\midrule
{chr(10).join(mc_rows)}
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：双侧精确二项检验；Holm 校正覆盖两张配对比较。
按预注册协议，$n<30$ 或无不一致对时只报描述统计，不作显著性主张。
\\end{{table}}
"""

    # ---------------- coverage.tex
    cov_rows = []
    mask_rows = []
    for arm in ARMS:
        item = per_arm[arm]
        cov_rows.append(
            f"{ARM_LABEL[arm]} & {fmt_int(item['planned'])} & {fmt_int(item['attempted'])} & "
            f"{fmt_int(item['valid'])} & {fmt(item['coverage'])} & "
            f"{fmt(item['partial_rate'])} & {fmt(item['degraded_rate'])} & "
            f"{fmt(item['verify_pass'])} \\\\")
        mask_rows.append(
            f"{ARM_LABEL[arm]} & {fmt_int(item['null_risk'])} & {fmt_int(item['failures'])} & "
            f"{fmt_int(item['degraded_roles'])} & {fmt_int(item['leakage'])} & "
            f"{fmt_int(item['unsupported'])} & {fmt_int(item['verify_failed'])} \\\\")
    coverage_tex = f"""% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。
\\begin{{table}}[t]
\\centering
\\caption{{覆盖率：有效定级占计划评分时点的比例（缺指标显示 \\texttt{{--}}）}}
\\label{{tab:coverage}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lrrrrrrr}}
\\toprule
臂 & 计划时点 & 已跑记录 & 有效定级 & 覆盖率 & partial & 有降级 & 核验通过率 \\\\
\\midrule
{chr(10).join(cov_rows)}
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：覆盖率 $=$ 有效定级 / 计划评分时点（有 $y_{{20}}$ 真值的抽样日期）。
partial 与「有降级」为占已跑记录的比例；核验通过率为 verification 非空记录中的通过比例。
\\end{{table}}

\\begin{{table}}[t]
\\centering
\\caption{{遮蔽计数：被排除在评分之外或未通过核验的记录（计数，不是比例）}}
\\label{{tab:masking}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lrrrrrr}}
\\toprule
臂 & 无有效定级 & 运行失败 & 降级角色数 & 泄漏事件 & 无证据主张 & 核验未通过 \\\\
\\midrule
{chr(10).join(mask_rows)}
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：无有效定级指 risk 缺失或不在四档枚举内；泄漏事件与无证据主张为
verification 字段的累计计数；这些记录不会被改写成负例。
\\end{{table}}
"""

    # ---------------- circularity.tex
    circularity_tex = f"""% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。
% 直接由 contracts/golden-vectors/cfsi_stress_pca_q90_reference.json 计算。
\\begin{{table}}[t]
\\centering
\\caption{{标签循环性诊断（$y_{{20}}$ 为 $t+1$ 至 $t+20$ 的严格未来标签；\\texttt{{strict}} 再推后一天至 $t+2$）}}
\\label{{tab:circularity}}
\\footnotesize
\\begin{{tabular}}{{lr}}
\\toprule
统计量 & 值 \\\\
\\midrule
样本日数（$y_{{20}}$ 可用） & {fmt_int(circ.get('n'))} \\\\
基准发生率 $P(y_{{20}}=1)$ & {fmt(circ.get('base_y20'))} \\\\
$P(y_{{20}}=1\\mid hs_t=1)$ & {fmt(circ.get('p_y_hs1'))} \\\\
$P(y_{{20}}=1\\mid hs_t=0)$ & {fmt(circ.get('p_y_hs0'))} \\\\
$t+1$ 至 $t+20$ 未来窗口样本日数 & {fmt_int(circ.get('n_future'))} \\\\
$y_{{20}}$ 与 $t+1$ 至 $t+20$ 窗口一致的日数 & {fmt_int(circ.get('n_agree'))} \\\\
更严格标签 $y^{{\\mathrm{{strict}}}}$（$t+2$ 至 $t+21$）样本日数 & {fmt_int(circ.get('n_strict'))} \\\\
基准发生率 $P(y^{{\\mathrm{{strict}}}}=1)$ & {fmt(circ.get('base_strict'))} \\\\
$P(y^{{\\mathrm{{strict}}}}=1\\mid hs_t=1)$ & {fmt(circ.get('p_strict_hs1'))} \\\\
$P(y^{{\\mathrm{{strict}}}}=1\\mid hs_t=0)$ & {fmt(circ.get('p_strict_hs0'))} \\\\
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：$hs_t$ 为当日 high\\_stress（定义即 CFSI $>\\tau$）。
$y_{{20}}$ 与 $t+1$ 至 $t+20$ 窗口逐日一致，说明本产物口径不含当日；
更严格标签再从 $t+2$ 起算，用于量化压力状态自相关带来的折扣。
两者都与 CFSI 同源，$P(y\\mid hs_t=1)$ 只能作为循环性诊断，不能当作预测能力。
\\end{{table}}
"""


    # ---------------- placebo.tex
    placebo_rows = []
    for arm in ARMS:
        item = summary['placebo'][arm]
        placebo_rows.append(
            f"{ARM_LABEL[arm]} & {fmt(item['obs_lift'])} & {fmt(item['null_mean'])} & "
            f"{fmt(item['null_q95'])} & {fmt_p(item['p'])} & "
            f"{fmt_int(item['draws'])} & "
            f"{('未执行' if item['p'] is None else ('异常' if item['p'] < 0.05 else '不显著'))} \\\\")
    placebo_tex = f"""% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。
\\begin{{table}}[t]
\\centering
\\caption{{标签置换安慰剂：打乱真值顺序后的 lift 零分布（$B$ 次置换）}}
\\label{{tab:placebo}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{lrrrrrr}}
\\toprule
臂 & 观测 lift & 零分布均值 & 零分布 95\\% 分位 & $p$ & $B$ & 判定 \\\\
\\midrule
{chr(10).join(placebo_rows)}
\\bottomrule
\\end{{tabular}}
\\par\\smallskip
\\raggedright\\scriptsize
注：保持预测向量与正例数不变，仅置换真值顺序；$p=(1+\\#\\{{lift_{{\\rm null}}\\ge lift_{{\\rm obs}}\\}})/(B+1)$。
该检验只说明「相对随机标签分配是否异常」，\\emph{{不替代}}独立重跑的安慰剂。
\\end{{table}}
"""

    macro_lines = [
        '% 由 tools/bench/analysis/render_tables.py 生成，请勿手改。',
        f'% 数据源：{tex_escape(data["source"])}',
        f'% 生成时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec="seconds")}',
        '',
    ]
    for key in sorted(macros):
        macro_lines.append(
            f'\\expandafter\\def\\csname res@{key}\\endcsname{{{macros[key]}}}')
    macro_tex = '\n'.join(macro_lines) + '\n'

    return {
        'main.tex': main,
        'mcnemar.tex': mcnemar_tex,
        'coverage.tex': coverage_tex,
        'circularity.tex': circularity_tex,
        'placebo.tex': placebo_tex,
        'macros.tex': macro_tex,
    }, macros


def print_summary(data: dict[str, Any], summary: dict[str, Any]) -> None:
    state = '完整' if summary['complete'] else '部分'
    suffix = '' if ('部分产物' in data['source'] or '全部时点' in data['source']) else f'（{state}）'
    print(f"数据源：{data['source']}{suffix}")
    print(f"模型：{data['model']}  seed={data['seed']}  "
          f"记录 {len(summary['records'])}  计划评分时点 {summary['planned_total']}"
          f"（已见 {len(summary['planned'])}）")
    print(f"{'臂':<16}{'n':>4}{'prec':>8}{'recall':>8}{'lift':>8}"
          f"{'trig':>8}{'balacc':>8}{'sec':>8}{'tok':>8}{'cov':>8}")
    for arm in ARMS:
        item = summary['per_arm'][arm]
        m = item['metrics'] or {}
        print(f"{arm:<16}{fmt_int(m.get('n')):>4}{fmt(m.get('precision')):>8}"
              f"{fmt(m.get('recall')):>8}{fmt(m.get('lift')):>8}"
              f"{fmt(m.get('trigger_rate')):>8}{fmt(m.get('balanced_accuracy')):>8}"
              f"{fmt_seconds(item['latency_s']):>8}{fmt_int(item['tokens']):>8}"
              f"{fmt(item['coverage']):>8}")
    for base in BASE_ARMS:
        item = summary['comparisons'][base]
        print(f"McNemar {base} vs collaborative: n={item['n']} "
              f"only_collab={item['only_collab']} only_base={item['only_base']} "
              f"p={fmt_p(item['p'])} p_holm={fmt_p(item.get('p_holm'))}")
    for arm in ARMS:
        item = summary['placebo'][arm]
        print(f"安慰剂 {arm}: obs_lift={fmt(item['obs_lift'])} "
              f"null_q95={fmt(item['null_q95'])} p={fmt_p(item['p'])}")
    c = summary['circularity']
    print(f"标签循环性：P(y20=1|hs=1)={fmt(c['p_y_hs1'])} "
          f"P(y20=1|hs=0)={fmt(c['p_y_hs0'])} "
          f"P(strict=1|hs=1)={fmt(c['p_strict_hs1'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='把 artifacts/bench 的真实产物渲染为 docs/25-paper/tables/*.tex',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--bench', type=Path, default=REPO / 'artifacts/bench',
                        help='基准产物目录（默认 artifacts/bench）')
    parser.add_argument('--out', type=Path, default=REPO / 'docs/25-paper/tables',
                        help='LaTeX 表输出目录（默认 docs/25-paper/tables）')
    parser.add_argument('--threshold', choices=('high', 'critical'), default='high',
                        help='四档到二值的阈值（默认 high，与 docs/23 一致）')
    parser.add_argument('--golden', type=Path, default=GOLDEN,
                        help='黄金向量（默认 contracts/.../cfsi_stress_pca_q90_reference.json）')
    args = parser.parse_args(argv)

    if not args.bench.exists():
        print(f'✘ 产物目录不存在：{args.bench}', file=sys.stderr)
        return 2

    data = load_dataset(args.bench)
    golden = load_golden(args.golden)
    summary = summarize(data, golden, args.threshold)
    files, macros = build_outputs(data, summary, args.threshold)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (args.out / name).write_text(text, encoding='utf-8')
    print_summary(data, summary)
    print(f'\n已写入 {len(files)} 个文件到 {args.out}（{len(macros)} 个宏）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
