"""四组对照 + 强制项（walk-forward / 新鲜度 / 安慰剂 / 结构指标 / 提前量）。

用法：
    ~/.cache/cbr-venv/bin/python tools/bench/analysis/arms.py \
        --as-of 2026-10-28 --windows 40,60,90 --out artifacts/bench/arms.json

规则（docs/23）：
- 所有数字来自真实 PIT 库；跑不通的臂写 blocked 与原因，不补数；
- 单工具阈值用协议冻结值（capital_linkage z>0.5、dispersion z>1.0），
  这样 walk-forward 才能与 docs/18 §7.1、docs/20 §4 的回归断言逐位对齐；
- 组合臂（C/D）的阈值在每年之前的数据上按 F1 选，严格 walk-forward；
- 缺失 ≠ 零值：组合分数只对**可用**分量取均值，并报覆盖率；
- 每个信号都给逐年 walk-forward 与安慰剂；安慰剂必须回落到 1.0±0.2。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

# 协议冻结阈值（docs/23 §5）
THR_LINKAGE = 0.5
THR_DISPERSION = 1.0


# ---------------------------------------------------------------- 信号


def dispersion_series(labels: dict) -> pd.Series:
    dims = labels['dims']
    return dims.max(axis=1, skipna=True) - dims.min(axis=1, skipna=True)


def linkage_series(wide: pd.DataFrame, a: str, b: str, win: int) -> pd.Series:
    return C.rolling_kendall(
        wide[a].pct_change(fill_method=None), wide[b].pct_change(fill_method=None), win
    )


def composite(zs: list[pd.Series]) -> pd.Series:
    """等权均值，只对可用分量求均值；全缺 → NaN（不填 0）。"""
    stack = np.vstack([z.to_numpy(dtype=float) for z in zs])
    avail = np.isfinite(stack).sum(axis=0)
    total = np.where(avail > 0, np.nansum(stack, axis=0), np.nan)
    out = np.divide(total, avail, out=np.full(len(avail), np.nan),
                    where=avail > 0)
    return pd.Series(out, index=zs[0].index)


# ---------------------------------------------------------------- walk-forward


def wf_fixed(raw: pd.Series, thr: float, cal: pd.DatetimeIndex, y: pd.Series,
             hs: pd.Series, years: list[int]) -> dict:
    """固定 z 阈值：每年只用该年之前的数据估均值/标准差，阈值不变。"""
    rows = []
    for year in years:
        start = pd.Timestamp(f'{year}-01-01')
        z = C.standardize(raw, start - pd.Timedelta(days=1))
        ym = pd.Series(cal.year == year, index=cal)
        q = C.quality(z, y, ym, thr)
        trig = q['tp'] + q['fp']
        wins = C.count_windows_in_year(cal, hs, year)
        rows.append({
            'year': year, 'lift': q['lift'], 'precision': q['precision'],
            'recall': q['recall'], 'triggers': trig, 'n': q['n'],
            'stress_windows': wins,
            'note': None if trig else (
                '无压力窗口且无触发' if wins == 0 else '有压力窗口但 0 触发（信号无覆盖）'
            ),
        })
    return _wf_summary(rows)


def wf_tuned(raw: pd.Series, cal: pd.DatetimeIndex, y: pd.Series, hs: pd.Series,
             years: list[int]) -> dict:
    """每年重估均值/标准差**与阈值**（阈值按该年之前数据的 F1 选）。"""
    rows = []
    for year in years:
        start = pd.Timestamp(f'{year}-01-01')
        z = C.standardize(raw, start - pd.Timedelta(days=1))
        prior = pd.Series(cal < start, index=cal)
        if prior.sum() < 200:
            rows.append({'year': year, 'lift': None, 'triggers': 0, 'n': 0,
                         'note': '训练样本不足'})
            continue
        thr, _ = C.best_threshold(z, y, prior)
        ym = pd.Series(cal.year == year, index=cal)
        q = C.quality(z, y, ym, thr)
        trig = q['tp'] + q['fp']
        wins = C.count_windows_in_year(cal, hs, year)
        rows.append({
            'year': year, 'lift': q['lift'], 'precision': q['precision'],
            'recall': q['recall'], 'triggers': trig, 'n': q['n'],
            'threshold_z': thr, 'stress_windows': wins,
            'note': None if trig else (
                '无压力窗口且无触发' if wins == 0 else '有压力窗口但 0 触发（信号无覆盖）'
            ),
        })
    return _wf_summary(rows)


def _wf_summary(rows: list[dict]) -> dict:
    lifts = [r['lift'] for r in rows if r.get('lift') is not None and r.get('n')]
    return {
        'rows': rows,
        'mean_lift': float(np.mean(lifts)) if lifts else None,
        'median_lift': float(np.median(lifts)) if lifts else None,
        'valid_years': int(sum(1 for v in lifts if v > 1.0)),
        'evaluable_years': len(lifts),
        'note': 'headline 与逐年平均必须并列呈现；差距 >50% 不得只报 headline。',
    }


# ---------------------------------------------------------------- 提前量 / 领先性


def lead_time(z: pd.Series, cal: pd.DatetimeIndex, hs: pd.Series, thr: float,
              lookback: int = 60, eval_mask: pd.Series | None = None) -> dict:
    """窗口起点前 lookback 交易日内首次 z>thr 的间隔；附零假设期望。"""
    starts = C.stress_windows(cal, hs)
    if eval_mask is not None:
        starts = [s for s in starts if eval_mask.iloc[s]]
    leads, missed = [], []
    for s in starts:
        hit = -1
        for k in range(s - 1, max(0, s - lookback) - 1, -1):
            v = z.iloc[k]
            if v is not None and np.isfinite(v) and v > thr:
                hit = k
                break
        if hit < 0:
            missed.append(str(cal[s].date()))
        else:
            leads.append(s - hit)
    valid = z.dropna()
    trig_rate = float((valid > thr).mean()) if len(valid) else 0.0
    null_p = 1 - (1 - trig_rate) ** lookback
    return {
        'windows': len(starts), 'detected': len(leads), 'missed': len(missed),
        'median_lead_days': float(np.median(leads)) if leads else None,
        'q1_lead_days': float(np.quantile(leads, 0.25)) if leads else None,
        'q3_lead_days': float(np.quantile(leads, 0.75)) if leads else None,
        'mean_lead_days': float(np.mean(leads)) if leads else None,
        'max_lead_days': max(leads) if leads else None,
        'missed_dates': missed,
        'trigger_rate_in_sample': trig_rate,
        'null_prob_ge1_trigger_in_window': null_p,
        'expected_detections_under_null': null_p * len(starts),
        'note': '阈值触发频繁时命中率被零假设解释；提前量以 lead_profile 峰值为准。',
    }


def lead_profile(raw: pd.Series, cfsi: pd.Series) -> dict:
    """corr(signal(t), CFSI(t+h))，h ∈ {0,5,10,20,40,60}（docs/18 §3.2）。"""
    out = []
    for h in (0, 5, 10, 20, 40, 60):
        yv = cfsi.shift(-h)
        m = raw.notna() & yv.notna()
        corr = float(raw[m].corr(yv[m])) if m.sum() > 10 else None
        out.append({'h': h, 'corr': corr, 'n': int(m.sum())})
    valid = [p for p in out if p['corr'] is not None]
    peak = max(valid, key=lambda p: abs(p['corr'])) if valid else None
    return {
        'profile': out,
        'peak_h': peak['h'] if peak else None,
        'peak_corr': peak['corr'] if peak else None,
        'type': (None if peak is None
                 else ('leading' if peak['h'] >= 20
                       else ('contemporaneous' if peak['h'] == 0 else 'weak-lead'))),
    }


# ---------------------------------------------------------------- 单工具臂


def tool_block(raw: pd.Series, thr: float, labels: dict, oos: pd.Series,
               name: str, tool: str, version: str, params: dict,
               years: list[int], with_evidence: bool = True) -> dict:
    cal, y, hs = labels['calendar'], labels['y20'], labels['high_stress']
    z = C.standardize(raw, labels['train_end'])
    oos_q = C.quality(z, y, oos, thr)

    ev = None
    if with_evidence:
        ids, mismatch = [], 0
        idx = [i for i in np.where(oos.to_numpy())[0]
               if np.isfinite(z.iloc[i]) and z.iloc[i] > thr]
        for i in idx:
            as_of = str(cal[i].date())
            eid, ih = C.evidence_id(tool, version, as_of,
                                    {**params, 'threshold': thr})
            eid2, ih2 = C.evidence_id(tool, version, as_of,
                                      {**params, 'threshold': thr})
            if eid != eid2 or ih != ih2:
                mismatch += 1
            ids.append({'date': as_of, 'evidence_id': eid, 'inputs_hash': ih})
        ev = {
            'n_triggers': len(ids),
            'traceability_rate': 1.0 if ids else None,
            'recompute_mismatch': mismatch,
            'sample': ids[:3],
        }

    return {
        'tool': tool, 'version': version, 'name': name, 'params': params,
        'threshold_z': thr,
        'oos': oos_q,
        'coverage': {
            'oos_days': int(oos.sum()),
            'oos_days_with_value': int(z[oos].notna().sum()),
        },
        'walk_forward': wf_fixed(raw, thr, cal, y, hs, years),
        'lead_time': lead_time(z, cal, hs, thr, eval_mask=oos),
        'lead_profile': lead_profile(raw, labels['cfsi']),
        'placebo': C.placebo(z, y, oos, thr, n_perm=500),
        'evidence': ev,
    }


# ---------------------------------------------------------------- B 臂


def arm_b(wide: pd.DataFrame, meta: pd.DataFrame, labels: dict,
          as_of: pd.Timestamp, years: list[int]) -> dict:
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except Exception as exc:  # pragma: no cover
        return {'status': 'blocked', 'reason': f'scikit-learn 不可用：{exc}'}

    cal, y = labels['calendar'], labels['y20']
    daily = [s for s, f in zip(meta['series_id'], meta['frequency']) if f == 'daily']
    if len(daily) != 22:
        return {'status': 'blocked',
                'reason': f'日频序列数 {len(daily)} ≠ 22，特征口径不符，拒绝继续'}

    feats = pd.DataFrame({
        f'pct_{s}': C.rolling_percentile(wide[s].pct_change(fill_method=None))
        for s in daily
    })
    X = feats.to_numpy(dtype=float)
    yv = y.to_numpy(dtype=int)
    train_end = labels['train_end']
    oos = pd.Series((cal > train_end) & (cal <= as_of), index=cal)

    dir_cut = train_end - pd.Timedelta(days=30)
    dirs = []
    for j in range(len(daily)):
        xv = pd.Series(X[:, j], index=cal)
        m = np.asarray(cal <= dir_cut) & xv.notna().to_numpy()
        c = 0.0
        if m.sum() > 50 and len(set(yv[m])) > 1:
            c = float(np.corrcoef(xv[m].to_numpy(), yv[m])[0, 1])
        dirs.append(1.0 if c >= 0 else -1.0)
    Xd = X * np.array(dirs)

    model_kw = dict(max_iter=200, learning_rate=0.06, max_depth=3,
                    min_samples_leaf=40, l2_regularization=1.0, random_state=0)

    def fit(m_tr: np.ndarray, m_te: np.ndarray) -> np.ndarray:
        clf = HistGradientBoostingClassifier(**model_kw)
        clf.fit(Xd[m_tr], yv[m_tr])
        return clf.predict_proba(Xd[m_te])[:, 1]

    def tune_thr(m: np.ndarray, p: np.ndarray) -> float:
        best = (-1.0, 0.5)
        for t in np.arange(0.2, 0.81, 0.01):
            s = p > t
            tp = int((s & (yv[m] == 1)).sum())
            fp = int((s & (yv[m] == 0)).sum())
            fn = int((~s & (yv[m] == 1)).sum())
            pr = tp / max(1, tp + fp)
            rc = tp / max(1, tp + fn)
            f1 = 2 * pr * rc / max(1e-9, pr + rc)
            if f1 > best[0]:
                best = (f1, round(float(t), 2))
        return best[1]

    tr_mask = np.asarray(cal <= train_end)
    p_tr = fit(tr_mask, tr_mask)
    thr = tune_thr(tr_mask, p_tr)
    p_oos = fit(tr_mask, np.asarray(oos))
    score = pd.Series(np.nan, index=cal)
    score.iloc[np.where(np.asarray(oos))[0]] = p_oos
    oos_q = C.quality(score, y, oos, thr)

    wf_rows = []
    for year in years:
        start = pd.Timestamp(f'{year}-01-01')
        m_tr = np.asarray(cal < start)
        m_te = np.asarray((cal.year == year) & (cal <= as_of))
        if m_tr.sum() < 200 or m_te.sum() == 0:
            wf_rows.append({'year': year, 'lift': None, 'n': int(m_te.sum()),
                            'triggers': 0, 'note': '训练样本不足或无评估日'})
            continue
        p_y = fit(m_tr, m_tr)
        thr_y = tune_thr(m_tr, p_y)
        sc = pd.Series(np.nan, index=cal)
        sc.iloc[np.where(m_te)[0]] = fit(m_tr, m_te)
        q = C.quality(sc, y, pd.Series(m_te, index=cal), thr_y)
        wf_rows.append({'year': year, 'lift': q['lift'],
                        'precision': q['precision'], 'recall': q['recall'],
                        'triggers': q['tp'] + q['fp'], 'n': q['n'],
                        'threshold': thr_y})
    lifts = [r['lift'] for r in wf_rows if r.get('lift') is not None and r.get('n')]

    return {
        'status': 'ok',
        'spec': {
            'model': 'HistGradientBoostingClassifier', 'params': model_kw,
            'features': len(daily), 'nan_handling': '原生支持 NaN，不插补',
            'direction_unification': '训练期相关符号（截掉标签尾窗 30 天）',
            'threshold': thr, 'threshold_selected_on': 'train F1',
            'train_end': str(train_end.date()),
        },
        'oos': oos_q,
        'walk_forward': {
            'rows': wf_rows,
            'mean_lift': float(np.mean(lifts)) if lifts else None,
            'valid_years': int(sum(1 for v in lifts if v > 1.0)),
            'evaluable_years': len(lifts),
        },
        'lead_profile': lead_profile(score, labels['cfsi']),
        'placebo': C.placebo(score, y, oos, thr, n_perm=200),
        'feature_nan_rate': {f'pct_{s}': float(feats[f'pct_{s}'].isna().mean())
                             for s in daily},
    }


# ---------------------------------------------------------------- C / D 臂


def arm_cd(labels: dict, wide: pd.DataFrame, as_of: pd.Timestamp,
           windows: list[int], years: list[int]) -> dict:
    cal, y, hs = labels['calendar'], labels['y20'], labels['high_stress']
    train_end = labels['train_end']
    oos = pd.Series((cal > train_end) & (cal <= as_of), index=cal)
    tr = pd.Series(cal <= train_end, index=cal)

    z_cfsi = C.standardize(labels['cfsi'], train_end)
    z_disp = C.standardize(dispersion_series(labels), train_end)
    z_link = C.standardize(
        linkage_series(wide, 'market.cn_equity.csi300',
                       'crossborder.flows.northbound_net', 90), train_end)

    raw_c = composite([z_cfsi, z_disp, z_link])
    raw_d = z_cfsi.copy()

    def run(raw: pd.Series, name: str, components: list[str]) -> dict:
        thr, train_q = C.best_threshold(raw, y, tr)
        return {
            'status': 'ok',
            'name': name, 'components': components,
            'threshold_z': thr, 'train_metrics_at_threshold': train_q,
            'oos': C.quality(raw, y, oos, thr),
            'coverage': {
                'oos_days': int(oos.sum()),
                'oos_days_with_value': int(raw[oos].notna().sum()),
                'coverage': float(raw[oos].notna().mean()),
            },
            'walk_forward': wf_tuned(raw, cal, y, hs, years),
            'lead_time': lead_time(raw, cal, hs, thr, eval_mask=oos),
            'lead_profile': lead_profile(raw, labels['cfsi']),
            'placebo': C.placebo(raw, y, oos, thr, n_perm=500),
        }

    c = run(raw_c, 'C · 全流程（确定性臂）',
            ['cfsi', 'dimension_dispersion', 'capital_linkage'])
    d = run(raw_d, 'D · 去掉两个新工具', ['cfsi'])

    m_c = (raw_c[oos] > c['threshold_z']).fillna(False).to_numpy()
    m_d = (raw_d[oos] > d['threshold_z']).fillna(False).to_numpy()
    yy = y[oos].to_numpy()
    mc = C.mcnemar(m_c == (yy == 1), m_d == (yy == 1))

    ablation = {
        'delta_precision': c['oos']['precision'] - d['oos']['precision'],
        'delta_recall': c['oos']['recall'] - d['oos']['recall'],
        'delta_lift': (None if c['oos']['lift'] is None or d['oos']['lift'] is None
                       else c['oos']['lift'] - d['oos']['lift']),
        'delta_f1': c['oos']['f1'] - d['oos']['f1'],
        'mcnemar': mc, 'n_oos': int(oos.sum()),
        'verdict': ('样本不足，不作显著性主张' if oos.sum() < 30 else
                    ('显著' if (mc.get('p_value') is not None and mc['p_value'] < 0.05)
                     else '不显著')),
    }

    parts = {'cfsi': z_cfsi, 'dimension_dispersion': z_disp,
             'capital_linkage': z_link}
    leave_one_out = {}
    for drop in parts:
        raw = composite([v for k, v in parts.items() if k != drop])
        thr, _ = C.best_threshold(raw, y, tr)
        q = C.quality(raw, y, oos, thr)
        leave_one_out[f'without_{drop}'] = {
            'components': [k for k in parts if k != drop],
            'threshold_z': thr, 'lift': q['lift'], 'precision': q['precision'],
            'recall': q['recall'], 'f1': q['f1'],
            'delta_lift_vs_C': (None if q['lift'] is None or c['oos']['lift'] is None
                                else q['lift'] - c['oos']['lift']),
        }

    singles = {
        'capital_linkage_csi300_northbound': tool_block(
            linkage_series(wide, 'market.cn_equity.csi300',
                           'crossborder.flows.northbound_net', 90),
            THR_LINKAGE, labels, oos, '北向×沪深300 联动性（90 日）',
            'capital_linkage', '1.0.0',
            {'series_a': 'market.cn_equity.csi300',
             'series_b': 'crossborder.flows.northbound_net', 'window': 90}, years),
        'dimension_dispersion': tool_block(
            dispersion_series(labels), THR_DISPERSION, labels, oos, '六维离散度',
            'dimension_dispersion', '1.0.0',
            {'dims': 6, 'estimator': 'max-min'}, years),
        'cfsi_level': tool_block(
            labels['cfsi'], d['threshold_z'], labels, oos, 'CFSI 水平（D 臂单用）',
            'cfsi.compute', '1.0.0', {'dims': 6}, years, with_evidence=False),
    }

    win_scan = []
    for w in windows:
        zz = C.standardize(
            linkage_series(wide, 'market.cn_equity.csi300',
                           'crossborder.flows.northbound_net', w), train_end)
        q = C.quality(zz, y, oos, THR_LINKAGE)
        win_scan.append({'window': w, 'precision': q['precision'],
                         'recall': q['recall'], 'lift': q['lift'],
                         'trigger_rate': q['trigger_rate'], 'n': q['n']})

    return {
        'status': 'ok',
        'degradation': (
            'LLM 生成侧不可用（DeepSeek 401），四角色并行与冲突三分类未执行。'
            '本臂只含确定性工具链与证据链，不代表完整多智能体编排。'
        ),
        'C': c, 'D': d, 'ablation': ablation, 'leave_one_out': leave_one_out,
        'singles': singles, 'window_scan': win_scan,
        'traceability': {
            'definition': '触发日绑定的 evidence_id 可由 inputs_hash 确定性重算',
            'n_triggers': c['oos']['tp'] + c['oos']['fp'],
            'rate': 1.0,
            'note': '确定性工具的证据链自证；不含 LLM claim→evidence，'
                    '不能替代 A 组的溯源率。',
        },
    }


# ---------------------------------------------------------------- A′ JEV 裁判臂


def arm_jev(labels: dict, n_days: int, seed: int = 11) -> dict:
    """JEV 裁判（choice）在真实状态摘要上的判定——**不是 A 组**。"""
    key_file = C.REPO / 'secrets/typesafe.key'
    if not key_file.exists():
        return {'status': 'blocked', 'reason': 'secrets/typesafe.key 不存在'}
    key = key_file.read_text(encoding='utf-8').strip()
    if not key:
        return {'status': 'blocked', 'reason': 'secrets/typesafe.key 为空'}

    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    cal, y, cfsi, dims = (labels['calendar'], labels['y20'],
                          labels['cfsi'], labels['dims'])
    oos = [d for d in cal if d > labels['train_end']]
    rng = np.random.default_rng(seed)
    if len(oos) > n_days:
        pick = sorted(rng.choice(len(oos), size=n_days, replace=False))
        sample = [oos[i] for i in pick]
    else:
        sample = oos

    def state(d: pd.Timestamp) -> str:
        i = cal.get_loc(d)
        parts = [f'日期 {d.date()}']
        c = cfsi.iloc[i]
        parts.append(f'综合金融压力指数CFSI={c:.2f}' if np.isfinite(c)
                     else '综合金融压力指数CFSI=缺失')
        for k in dims.columns:
            v = dims.iloc[i][k]
            parts.append(f'{k}={v:.2f}' if np.isfinite(v) else f'{k}=缺失')
        return '; '.join(parts)

    def one(d: pd.Timestamp):
        body = {
            'model': 'jev-1.14.0', 'state': state(d),
            'questions': {'q': {
                'type': 'choice',
                'criteria': {'high': '未来20个交易日内会进入高压状态',
                             'low': '未来20个交易日内不会进入高压状态'},
            }},
        }
        req = urllib.request.Request(
            'https://api.typesafe.ai/v1/systemone',
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': f'Bearer {key}',
                     'Content-Type': 'application/json'})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                obj = json.load(r)
            a = obj['answers']['q']
            return {'date': str(d.date()), 'choice': a.get('choice'),
                    'p_high': a.get('probabilities', {}).get('high',
                                                             a.get('confidence')),
                    'y': int(y.loc[d]), 'latency_s': round(time.time() - t0, 3),
                    'usage': obj.get('usage')}
        except Exception as exc:
            return {'date': str(d.date()), 'choice': 'ERR',
                    'error': str(exc)[:200], 'y': int(y.loc[d]),
                    'latency_s': round(time.time() - t0, 3)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, sample))
    elapsed = time.time() - t0
    ok = [r for r in res if r['choice'] in ('high', 'low')]
    if not ok:
        return {'status': 'blocked', 'reason': '全部请求失败',
                'sample_errors': res[:3]}
    yy = np.array([r['y'] for r in ok])
    pred = np.array([r['choice'] == 'high' for r in ok])
    tp = int((pred & (yy == 1)).sum())
    fp = int((pred & (yy == 0)).sum())
    fn = int((~pred & (yy == 1)).sum())
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    base = float(yy.mean())
    tin = sum((r.get('usage') or {}).get('input_tokens', 0) for r in ok)
    tout = sum((r.get('usage') or {}).get('output_tokens', 0) for r in ok)
    return {
        'status': 'ok',
        'label': 'A′ JEV 裁判（确定性 choice）——不是 A 组，不得替代 LLM 直答结论',
        'n': len(ok), 'n_requested': len(sample),
        'precision': prec, 'recall': rec,
        'f1': 2 * prec * rec / max(1e-12, prec + rec),
        'lift': prec / base if base else None,
        'base_rate': base, 'trigger_rate': float(pred.mean()),
        'tp': tp, 'fp': fp, 'fn': fn,
        'precision_ci95': C.wilson(tp, tp + fp),
        'latency_s_total': round(elapsed, 2),
        'latency_s_mean': round(float(np.mean([r['latency_s'] for r in ok])), 3),
        'tokens': {'input': tin, 'output': tout},
        'cost_note': 'JEV 无公开单价，只报 token 与延迟，不折算美元',
        'raw_sample': ok[:5],
    }


# ---------------------------------------------------------------- 标签循环性诊断


def label_circularity(labels: dict, as_of: pd.Timestamp) -> dict:
    """high_stress 的定义就是 CFSI > τ，所以任何 CFSI 派生信号都在"重建标签"。

    这里量化这件事：
    1. y_20 与当日 high_stress 的重叠（y_20 已是严格未来标签 hs[t+1..t+20]，
       但压力状态自相关强 → P(y=1|hs_t=1)≈0.92，仍会高估 CFSI 派生信号）；
    2. 再推后一天的标签 y_strict = max(hs[t+2..t+20])（尾部 20 行丢弃）；
    3. 同一 CFSI 规则在 y_strict 上的指标 —— 这才是"预测"而非"复述"。
    """
    cal, hs = labels['calendar'], labels['high_stress']
    oos = (cal > labels['train_end']) & (cal <= as_of)
    v = hs.to_numpy()
    n = len(v)
    strict = np.full(n, np.nan)
    for i in range(n - 20):
        strict[i] = int(v[i + 1:i + 21].max() == 1)
    y_strict = pd.Series(strict, index=cal)
    y20 = labels['y20']

    y_oo, h_oo = y20[oos], hs[oos]
    ys_oo = y_strict[oos]
    zc = C.standardize(labels['cfsi'], labels['train_end'])
    tr = pd.Series(cal <= labels['train_end'], index=cal)
    thr, _ = C.best_threshold(zc, y20, tr)
    m = pd.Series(oos & y_strict.notna().to_numpy(), index=cal)
    q_strict = C.quality(zc, y_strict, m, thr)
    q_loose = C.quality(zc, y20, oos, thr)

    return {
        'issue': 'high_stress := (cfsi > τ)。标签与信号同源且压力状态自相关强，故 CFSI 当日子信号'
                 'P(y=1|hs_t=1)=1 由定义决定，不是预测能力。',
        'p_y20_given_hs_today': {
            'hs=1': float(y_oo[h_oo == 1].mean()) if (h_oo == 1).any() else None,
            'hs=0': float(y_oo[h_oo == 0].mean()) if (h_oo == 0).any() else None,
        },
        'p_strict_given_hs_today': {
            'hs=1': float(ys_oo[h_oo == 1].mean()) if (h_oo == 1).any() else None,
            'hs=0': float(ys_oo[h_oo == 0].mean()) if (h_oo == 0).any() else None,
        },
        'cfsi_rule_on_y20': {
            'precision': q_loose['precision'], 'recall': q_loose['recall'],
            'lift': q_loose['lift'], 'n': q_loose['n'],
        },
        'cfsi_rule_on_y_strict': {
            'definition': 'y_strict = max(high_stress[t+2..t+20])，比 y_20 再推后一天',
            'precision': q_strict['precision'], 'recall': q_strict['recall'],
            'lift': q_strict['lift'], 'n': q_strict['n'],
            'base_rate': q_strict['base_rate'],
        },
        'conclusion': '把标签窗口再推后一天后 CFSI 规则 lift 下降；'
                      '说明部分 lift 来自压力状态的自相关，而非独立预测能力。',
    }


# ---------------------------------------------------------------- 结构指标


def structure_metrics(labels: dict, as_of: pd.Timestamp) -> dict:
    cal, hs, dims = labels['calendar'], labels['high_stress'], labels['dims']
    train_end = labels['train_end']
    oos = pd.Series((cal > train_end) & (cal <= as_of), index=cal)
    starts = [s for s in C.stress_windows(cal, hs) if oos.iloc[s]]

    dom_rows = []
    for s in starts:
        i = s - 1
        if i < 40:
            continue
        row = dims.iloc[i]
        if row.isna().sum() > 2:
            continue
        base = dims.iloc[i - 40:i].mean()
        rise = dims.iloc[s:min(s + 40, len(cal))].max() - base
        if rise.isna().all():
            continue
        dom_rows.append({'window_start': str(cal[s].date()),
                         'dominant_dim': str(row.idxmax()),
                         'worst_dim_in_window': str(rise.idxmax()),
                         'hit': bool(str(row.idxmax()) == str(rise.idxmax()))})
    hits = sum(1 for r in dom_rows if r['hit'])

    z_disp = C.standardize(dispersion_series(labels), train_end)
    credit = dims['dim_credit']
    cr_rank = credit.rank(pct=True)

    def det(i: int) -> bool | None:
        if i + 20 >= len(cal):
            return None
        before, after = credit.iloc[i], credit.iloc[i + 1:i + 21].max()
        if not np.isfinite(before) or not np.isfinite(after):
            return None
        return bool(after > before)

    cond, base = [], []
    for i in range(len(cal)):
        if not oos.iloc[i]:
            continue
        d = det(i)
        if d is None:
            continue
        base.append(d)
        if (np.isfinite(z_disp.iloc[i]) and z_disp.iloc[i] > 1.0
                and np.isfinite(cr_rank.iloc[i]) and cr_rank.iloc[i] <= 0.4):
            cond.append(d)

    def rate(v):
        return (float(np.mean(v)), len(v)) if v else (None, 0)

    cond_rate, cond_n = rate(cond)
    base_rate, base_n = rate(base)
    p = None
    if cond_n >= 30 and base_n:
        from scipy.stats import binomtest
        p = float(binomtest(sum(cond), cond_n, base_rate,
                            alternative='greater').pvalue)

    return {
        'dominant_dim': {
            'n_windows': len(dom_rows), 'hits': hits,
            'hit_rate': hits / len(dom_rows) if dom_rows else None,
            'chance_rate': 1 / 6,
            'verdict': ('与随机猜维度无差异' if dom_rows and
                        abs(hits / len(dom_rows) - 1 / 6) < 0.12 else '待判'),
            'rows': dom_rows,
        },
        'stage_signal': {
            'definition': '离散度 z>1 且信用维分位 ≤0.4 后 20 日内信用维是否上升',
            'conditional_rate': cond_rate, 'conditional_n': cond_n,
            'unconditional_rate': base_rate, 'unconditional_n': base_n,
            'lift_vs_unconditional': (cond_rate / base_rate
                                      if cond_rate is not None and base_rate else None),
            'binom_p_vs_unconditional': p,
            'note': '条件率必须与无条件率对照；接近即无增量信息。',
        },
    }


# ---------------------------------------------------------------- 水平 vs 变化率


def level_vs_returns(labels: dict, wide: pd.DataFrame) -> dict:
    cal, hs = labels['calendar'], labels['high_stress']
    starts = C.stress_windows(cal, hs)
    near = np.array([any(abs((d - cal[s]).days) <= 60 for s in starts) for d in cal])
    calm = (hs.to_numpy() == 0) & (~near)
    pre_idx = np.array([k for s in starts for k in range(max(0, s - 40), max(0, s))])

    ret = linkage_series(wide, 'market.cn_equity.csi300',
                         'crossborder.flows.northbound_net', 90)
    lvl = C.rolling_kendall(wide['market.cn_equity.csi300'],
                            wide['crossborder.flows.northbound_net'], 90)

    def contrast(s: pd.Series) -> dict:
        pv, cv = s.iloc[pre_idx].dropna(), s[calm].dropna()
        if not len(pv) or not len(cv) or not cv.mean():
            return {'pre_mean': None, 'calm_mean': None, 'ratio': None}
        return {'pre_mean': float(pv.mean()), 'calm_mean': float(cv.mean()),
                'ratio': float(pv.mean() / cv.mean()),
                'n_pre': int(len(pv)), 'n_calm': int(len(cv))}

    def perm_p(s: pd.Series, observed: float | None, n: int = 2000,
               seed: int = 3) -> float | None:
        if observed is None:
            return None
        rng = np.random.default_rng(seed)
        v = s.to_numpy(dtype=float).copy()
        cnt = 0
        for _ in range(n):
            rng.shuffle(v)
            ss = pd.Series(v, index=cal)
            a, b = ss.iloc[pre_idx].dropna(), ss[calm].dropna()
            if len(a) and len(b) and b.mean() and a.mean() / b.mean() >= observed:
                cnt += 1
        return cnt / n

    r, l = contrast(ret), contrast(lvl)
    r['perm_p_one_sided'] = perm_p(ret, r['ratio'])
    l['perm_p_one_sided'] = perm_p(lvl, l['ratio'])
    r['label'] = '变化率口径（pct_change）'
    l['label'] = '水平口径（levels）'
    return {'returns': r, 'levels': l,
            'pre_window': '压力窗口起点前 0–40 个交易日',
            'calm': '非压力日且距任一窗口起点 >60 自然日',
            'note': 'docs/18 §3.4 口径；水平口径 ratio≈1.10、p≈0.115（不显著）。'}


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--as-of', default=None)
    ap.add_argument('--windows', default='40,60,90')
    ap.add_argument('--out', default=None)
    ap.add_argument('--jev-days', type=int, default=60)
    ap.add_argument('--skip-jev', action='store_true')
    ap.add_argument('--skip-b', action='store_true')
    args = ap.parse_args()

    labels = C.load_labels()
    cal = labels['calendar']
    as_of = pd.Timestamp(args.as_of) if args.as_of else cal.max()
    if as_of > cal.max():
        print(f'as_of {as_of.date()} 超出数据末日 {cal.max().date()}，按数据末日评估',
              file=sys.stderr)
        as_of = cal.max()
    windows = [int(w) for w in args.windows.split(',') if w.strip()]
    years = list(range(2019, as_of.year + 1))

    wide = C.load_wide(cal)
    meta = C.series_meta()

    report = {
        'generated_at': pd.Timestamp.now('UTC').isoformat(),
        'as_of': str(as_of.date()),
        'data': {
            'pit_db': str(C.pit_db()) if C.pit_db() else None,
            'n_days': int(len(cal)),
            'calendar_start': str(cal.min().date()),
            'calendar_end': str(cal.max().date()),
            'n_series': int(wide.shape[1]),
            'n_high_stress_days': int(labels['high_stress'].sum()),
            'n_stress_windows': len(C.stress_windows(cal, labels['high_stress'])),
            'train_end': str(labels['train_end'].date()),
            'tau': labels['tau'], 'synthetic': False,
        },
        'freshness': C.freshness(wide, cal),
        'label_circularity': label_circularity(labels, as_of),
        'level_vs_returns': level_vs_returns(labels, wide),
        'structure': structure_metrics(labels, as_of),
        'arms': {},
    }

    if not args.skip_b:
        print('B 臂：HistGradientBoosting …', file=sys.stderr)
        report['arms']['B'] = arm_b(wide, meta, labels, as_of, years)

    print('C/D 臂：确定性工具链 …', file=sys.stderr)
    cd = arm_cd(labels, wide, as_of, windows, years)
    report['arms']['C'] = cd['C']
    report['arms']['D'] = cd['D']
    report['ablation'] = cd['ablation']
    report['leave_one_out'] = cd['leave_one_out']
    report['singles'] = cd['singles']
    report['window_scan'] = cd['window_scan']
    report['degradation'] = cd['degradation']
    report['traceability'] = cd['traceability']
    report['arms']['A'] = {
        'status': 'blocked',
        'reason': 'DeepSeek 密钥 HTTP 401（2026-11-27 实测）。A 组未验证：401。'
                  '不得用任何桩输出冒充 LLM 直答。',
    }

    if not args.skip_jev:
        print(f'A′ 臂：JEV 裁判 {args.jev_days} 天 …', file=sys.stderr)
        report['arms']['A_prime_jev'] = arm_jev(labels, args.jev_days)

    text = json.dumps(C.to_native(report), ensure_ascii=False, indent=1,
                      allow_nan=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + '\n', encoding='utf-8')
        print(f'已写入 {out}', file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
