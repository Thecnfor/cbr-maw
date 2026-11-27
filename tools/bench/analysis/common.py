"""基准测试公共层：数据加载、标签、指标、显著性、walk-forward、安慰剂。

口径全部来自 docs/23 与 contracts/README.md：
- 标签 = `stress_pca_q90`（train_end 冻结 2021-12-31，τ=91.506447831184）；
- 正例 y_20 = max(high_stress[t+1..t+20])（严格未来，不含当日；尾部不足 20 天为 null，
  这是黄金向量的定义，不是我们的选择）；
- 阈值一律在训练期冻结，样本外只评估；
- 缺失 ≠ 零值：任何填充都禁止，指标按可用样本计并报 n。

真实数据优先从 DuckDB 读；不可用时退回 `data/seed/pit_real_obs.jsonl`。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / 'contracts/golden-vectors'
TRAIN_END = pd.Timestamp('2021-12-31')
DEFAULT_DB = Path('/mnt/shared/recently/commorcial/data/pit_real.duckdb')


# ---------------------------------------------------------------- 数据


def pit_db() -> Path | None:
    p = Path(os.environ.get('CBR_PIT_DB', DEFAULT_DB))
    return p if p.exists() else None


def load_wide(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """全部序列的宽表，索引对齐到 CFSI 交易日历。"""
    db = pit_db()
    if db is not None:
        import duckdb

        con = duckdb.connect(str(db), read_only=True)
        try:
            df = con.execute(
                'select series_id, obs_date, value from series_obs'
            ).fetchdf()
        finally:
            con.close()
        df['obs_date'] = pd.to_datetime(df['obs_date'])
        return df.pivot(index='obs_date', columns='series_id', values='value').reindex(
            calendar
        )
    obs = REPO / 'data/seed/pit_real_obs.jsonl'
    rows = [json.loads(line) for line in obs.open(encoding='utf-8') if line.strip()]
    df = pd.DataFrame(rows)[['series_id', 'obs_date', 'value']]
    df['obs_date'] = pd.to_datetime(df['obs_date'])
    return df.pivot(index='obs_date', columns='series_id', values='value').reindex(
        calendar
    )


def series_meta() -> pd.DataFrame:
    db = pit_db()
    if db is not None:
        import duckdb

        con = duckdb.connect(str(db), read_only=True)
        try:
            return con.execute(
                'select series_id, name, frequency, coverage_start, coverage_end, '
                'release_lag_days, unit from series_meta'
            ).fetchdf()
        finally:
            con.close()
    rows = [
        json.loads(line)
        for line in (REPO / 'data/seed/pit_real_obs.jsonl').open(encoding='utf-8')
        if line.strip()
    ]
    df = pd.DataFrame(rows)
    keep = ['series_id', 'name', 'frequency', 'coverage_start', 'coverage_end',
            'release_lag_days', 'unit']
    return df[keep].drop_duplicates('series_id').reset_index(drop=True)


def load_labels() -> dict:
    """CFSI 黄金参考表：日历、cfsi、high_stress、六维。"""
    g = json.load((GOLDEN / 'cfsi_stress_pca_q90_reference.json').open(encoding='utf-8'))
    rows = g['rows']
    cal = pd.to_datetime([r['date'] for r in rows])
    dims = pd.DataFrame([r['dims'] for r in rows], index=cal, dtype=float)
    cfsi = pd.Series([r['cfsi'] for r in rows], index=cal, dtype=float)
    hs = (
        pd.Series([r['high_stress'] for r in rows], index=cal, dtype=float)
        .fillna(0)
        .astype(int)
    )
    y20 = future_label(hs)
    return {
        'calendar': cal,
        'cfsi': cfsi,
        'high_stress': hs,
        'dims': dims,
        'y20': y20,
        'tau': float(g['tau']),
        'train_end': pd.Timestamp(g['train_end']),
    }


def future_label(hs: pd.Series, horizon: int = 20) -> pd.Series:
    """y_h = max(high_stress[t..t+h-1])；尾部 h-1 行按 0（黄金向量定义）。"""
    v = hs.values
    n = len(v)
    out = np.zeros(n, dtype=int)
    for i in range(n - 1):
        out[i] = int(v[i : i + horizon].max() == 1)
    return pd.Series(out, index=hs.index)


# ---------------------------------------------------------------- 统计


def rolling_kendall(x: pd.Series, y: pd.Series, win: int = 90,
                    min_ratio: float = 0.5) -> pd.Series:
    """滚动 Kendall tau（配对 sign 乘积均值，并列对计入分母）。"""
    xv, yv = x.values.astype(float), y.values.astype(float)
    n = len(xv)
    out = np.full(n, np.nan)
    min_obs = max(15, int(win * min_ratio))
    for i in range(win - 1, n):
        a = xv[i - win + 1 : i + 1]
        b = yv[i - win + 1 : i + 1]
        m = ~(np.isnan(a) | np.isnan(b))
        k = int(m.sum())
        if k < min_obs:
            continue
        sa = np.sign(a[m][:, None] - a[m][None, :])
        sb = np.sign(b[m][:, None] - b[m][None, :])
        iu = np.triu_indices(k, 1)
        out[i] = float((sa[iu] * sb[iu]).mean())
    return pd.Series(out, index=x.index)


def rolling_percentile(s: pd.Series, win: int = 252, min_periods: int = 60) -> pd.Series:
    """滚动经验分位，弱不等号 `<=`，窗口含当日（contracts §5.1 同口径）。"""
    v = s.values.astype(float)
    n = len(v)
    out = np.full(n, np.nan)
    for i in range(n):
        if not np.isfinite(v[i]):
            continue
        w = v[max(0, i - win + 1) : i + 1]
        w = w[np.isfinite(w)]
        if len(w) < min_periods:
            continue
        out[i] = float(np.sum(w <= v[i]) / len(w))
    return pd.Series(out, index=s.index)


def standardize(values: pd.Series, train_end: pd.Timestamp) -> pd.Series:
    """训练期均值/标准差（ddof=1）冻结，样本外只套用。"""
    train = values[values.index <= train_end].dropna()
    if len(train) < 2:
        return pd.Series(np.nan, index=values.index)
    mu = float(train.mean())
    sd = float(train.std(ddof=1))
    return (values - mu) / (sd if sd else 1.0)


def wilson(k: int, n: int) -> list[float | None]:
    if n == 0:
        return [None, None]
    try:
        from scipy.stats import binomtest

        ci = binomtest(k, n).proportion_ci(method='wilson')
        return [float(ci.low), float(ci.high)]
    except Exception:
        return [None, None]


def quality(score: pd.Series, y: pd.Series, mask: pd.Series, threshold: float) -> dict:
    """分类指标；mask 为评估样本。触发 = score > threshold（严格大于）。"""
    s = (score[mask] > threshold).fillna(False)
    yy = y[mask]
    tp = int((s & (yy == 1)).sum())
    fp = int((s & (yy == 0)).sum())
    fn = int((~s & (yy == 1)).sum())
    n = int(len(yy))
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    base = float(yy.mean()) if n else None
    lo, hi = wilson(tp, tp + fp)
    return {
        'tp': tp, 'fp': fp, 'fn': fn, 'n': n,
        'precision': prec, 'recall': rec,
        'f1': 2 * prec * rec / max(1e-12, prec + rec),
        'lift': (prec / base) if base else None,
        'trigger_rate': float(s.mean()) if n else None,
        'base_rate': base,
        'precision_ci95': [lo, hi],
    }


def best_threshold(score: pd.Series, y: pd.Series, mask: pd.Series,
                   grid: np.ndarray | None = None) -> tuple[float, dict]:
    """训练期按 F1 选阈值；返回 (阈值, 该阈值下的训练期指标)。"""
    if grid is None:
        grid = np.arange(0.05, 0.951, 0.01)
    best = (0.5, -1.0, {})
    for t in grid:
        q = quality(score, y, mask, float(t))
        if q['f1'] > best[1]:
            best = (float(t), q['f1'], q)
    return round(best[0], 2), best[2]


def mcnemar(a_correct: np.ndarray, b_correct: np.ndarray) -> dict:
    """配对分类差异的 McNemar 精确检验（只统计不一致对）。"""
    from scipy.stats import binomtest

    a = np.asarray(a_correct, dtype=bool)
    b = np.asarray(b_correct, dtype=bool)
    n01 = int((~a & b).sum())
    n10 = int((a & ~b).sum())
    n = n01 + n10
    if n == 0:
        return {'n_discordant': 0, 'p_value': None, 'note': '无差异对'}
    p = float(binomtest(n01, n, 0.5).pvalue)
    return {'n_discordant': n, 'n_only_a_correct': n10, 'n_only_b_correct': n01,
            'p_value': p}


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 20) -> dict:
    """Diebold-Mariano（平方损失差，HLN 小样本修正）。"""
    from scipy.stats import t as tdist

    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {'n': n, 'stat': None, 'p_value': None, 'note': '样本不足'}
    mean_d = float(d.mean())
    # 长期方差：Newey-West（滞后 h-1）
    gamma0 = float(np.mean((d - mean_d) ** 2))
    var = gamma0
    for lag in range(1, min(h, n - 1)):
        cov = float(np.mean((d[lag:] - mean_d) * (d[:-lag] - mean_d)))
        var += 2 * (1 - lag / h) * cov
    var = max(var, 1e-12)
    stat = mean_d / math.sqrt(var / n)
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    stat_hln = stat * hln
    p = float(2 * (1 - tdist.cdf(abs(stat_hln), df=n - 1)))
    return {'n': n, 'stat': float(stat_hln), 'p_value': p,
            'mean_loss_diff': mean_d}


# ---------------------------------------------------------------- walk-forward


def walk_forward(fit_and_score, years: list[int], oos_mask: pd.Series,
                 calendar: pd.DatetimeIndex, y: pd.Series,
                 high_stress: pd.Series) -> dict:
    """逐年 walk-forward：每年只用该年之前的数据估参数。

    `fit_and_score(year_start: pd.Timestamp) -> pd.Series` 必须返回全序列分数，
    但只允许使用 year_start 之前的数据估参数（阈值/均值/模型）。
    """
    rows = []
    for year in years:
        start = pd.Timestamp(f'{year}-01-01')
        score = fit_and_score(start)
        ym = pd.Series(calendar.year == year, index=calendar) & oos_mask
        q = quality(score, y, ym, fit_and_score.threshold_for(start))
        windows = count_windows_in_year(calendar, high_stress, year)
        triggers = q['tp'] + q['fp']
        rows.append({
            'year': year,
            'lift': q['lift'], 'precision': q['precision'], 'recall': q['recall'],
            'triggers': triggers, 'n': q['n'],
            'stress_windows': windows,
            'note': None if triggers else (
                '无压力窗口且无触发' if windows == 0 else '有压力窗口但 0 触发（信号无覆盖）'
            ),
        })
    lifts = [r['lift'] for r in rows if r['lift'] is not None and r['n']]
    return {
        'rows': rows,
        'mean_lift': float(np.mean(lifts)) if lifts else None,
        'valid_years': int(sum(1 for v in lifts if v > 1.0)),
        'evaluable_years': len(lifts),
    }


def count_windows_in_year(calendar: pd.DatetimeIndex, hs: pd.Series, year: int) -> int:
    starts = stress_windows(calendar, hs)
    return sum(1 for i in starts if calendar[i].year == year)


def stress_windows(calendar: pd.DatetimeIndex, hs: pd.Series) -> list[int]:
    """压力窗口起点：high_stress=1 的连续区间（间隔 > 6 自然日算新窗口）。"""
    starts, prev = [], None
    for i in range(len(calendar)):
        if hs.iloc[i] != 1:
            continue
        if prev is None or (calendar[i] - prev).days > 6:
            starts.append(i)
        prev = calendar[i]
    return starts


# ---------------------------------------------------------------- 安慰剂


def placebo(score: pd.Series, y: pd.Series, mask: pd.Series, threshold: float,
            n_perm: int = 500, seed: int = 20261127) -> dict:
    """打乱评估期信号（保留触发次数），重算 lift；必须回落到 1.0 附近。"""
    rng = np.random.default_rng(seed)
    base = quality(score, y, mask, threshold)
    vals = score[mask].to_numpy(dtype=float).copy()
    yy = y[mask].to_numpy()
    obs_lift = base['lift']
    lifts, precs = [], []
    for _ in range(n_perm):
        rng.shuffle(vals)
        s = np.nan_to_num(vals, nan=-np.inf) > threshold
        tp = int((s & (yy == 1)).sum())
        fp = int((s & (yy == 0)).sum())
        if tp + fp == 0:
            continue
        p = tp / (tp + fp)
        precs.append(p)
        lifts.append(p / yy.mean())
    if not lifts:
        return {'n_perm': 0, 'observed_lift': obs_lift}
    arr = np.array(lifts)
    p_value = float((arr >= obs_lift).mean()) if obs_lift is not None else None
    return {
        'n_perm': len(arr),
        'observed_lift': obs_lift,
        'placebo_mean_lift': float(arr.mean()),
        'placebo_p05': float(np.quantile(arr, 0.05)),
        'placebo_p95': float(np.quantile(arr, 0.95)),
        'placebo_max_lift': float(arr.max()),
        'p_value_one_sided': p_value,
        'pass': bool(abs(arr.mean() - 1.0) <= 0.2),
    }


# ---------------------------------------------------------------- 哈希（evidence_id）

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def to_native(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: to_native(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_native(v) for v in o]
    if isinstance(o, (np.floating,)):
        return to_native(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return o


def sha256_canonical(obj) -> str:
    return hashlib.sha256(canonical_json(to_native(obj)).encode('utf-8')).hexdigest()


def inputs_hash(tool: str, version: str, as_of: str, params: dict) -> str:
    """与 contracts §6 / Dart `EvidenceHash.inputsHash` 同构：
    sha256(canonical_json({tool, version, as_of, params}))。"""
    return sha256_canonical(
        {'tool': tool, 'version': version, 'as_of': as_of, 'params': params}
    )


def evidence_id(tool: str, version: str, as_of: str, params: dict) -> tuple[str, str]:
    """返回 (evidence_id, inputs_hash)，口径与 contracts §6 一致。"""
    ih = inputs_hash(tool, version, as_of, params)
    eid = 'ev_' + sha256_canonical(
        {'tool': tool, 'version': version, 'inputs_hash': ih}
    )[:16]
    return eid, ih


# ---------------------------------------------------------------- 新鲜度

def freshness(wide: pd.DataFrame, calendar: pd.DatetimeIndex) -> list[dict]:
    """每个依赖序列：最新可用日、评估期 NaN 率、是否可实时。"""
    tracked = [
        'market.cn_equity.csi300', 'crossborder.flows.northbound_net',
        'crossborder.flows.southbound_net', 'rates.credit.aa_spread',
        'market.cn_bond.repo_7d', 'market.fx.usdcny', 'market.global.vix',
        'market.global.sp500', 'market.cn_equity.turnover',
        'market.cn_bond.cgb_10y', 'market.global.dxy',
    ]
    out = []
    for sid in tracked:
        if sid not in wide.columns:
            out.append({'series_id': sid, 'status': 'missing'})
            continue
        s = wide[sid]
        valid = s.dropna()
        last = valid.index.max() if len(valid) else None
        last_cal = calendar.max()
        out.append({
            'series_id': sid,
            'last_available': str(last.date()) if last is not None else None,
            'nan_rate': float(s.isna().mean()),
            'lag_days_vs_calendar_end': (
                int((last_cal - last).days) if last is not None else None
            ),
            'realtime_usable': bool(last is not None and (last_cal - last).days <= 10),
        })
    return out
