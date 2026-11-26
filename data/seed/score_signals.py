"""独立信号评分器（不信任实现自评）。

用途：对任意实现（Dart/Rust/Go）产出的信号序列，按统一口径重算指标，并与黄金向量比对。
原则：
  - 标签只用旧版口径（stress_pca_q90 的 high_stress / y_20），由旧版 Python 在真实库上算出；
  - 阈值一律**训练期分位冻结**，样本外只评估；
  - 与黄金向量逐点比对，任何超出容差的偏差直接判失败；
  - 同时输出前置相关曲线（lead profile），判断是领先还是同期。

用法：
    /tmp/cbrvenv/bin/python data/seed/score_signals.py \
        --signal data/seed/impl_capital_linkage.jsonl \
        --kind capital_linkage \
        [--golden contracts/golden-vectors/capital_linkage_reference.json] \
        [--out artifacts/score_capital_linkage.json]
"""
import argparse, json, math, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, '/mnt/shared/recently/commorcial/src')
from cbr.data.pit_store import PitStore
from cbr.data.labels import build_stress_labels

DB = os.environ.get('CBR_PIT_DB', '/mnt/shared/recently/commorcial/data/pit_real.duckdb')
TOL = 1e-8


def load_golden_labels():
    store = PitStore.open(DB, writable=True)
    ds = store.load_market_dataset(with_documents=True)
    res = build_stress_labels(ds, label_version='stress_pca_q90')
    df = res.frame.copy()
    hs = df['high_stress'].fillna(0).astype(int)
    future = pd.Series(0, index=df.index)
    for i in range(len(df) - 1):
        future.iloc[i] = int(hs.iloc[i:i + 20].max() == 1)
    return df, pd.Timestamp(res.train_end), future


def load_signal(path):
    vals = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            vals[d['date']] = d
    return vals


def to_series(vals, df, field):
    return pd.Series({pd.Timestamp(k): (v.get(field) if v.get(field) is not None else np.nan)
                       for k, v in vals.items()}).reindex(df.index).astype(float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--signal', required=True)
    ap.add_argument('--kind', required=True, choices=['capital_linkage', 'dimension_dispersion'])
    ap.add_argument('--pair', default=None, help='capital_linkage 的配对名（默认取黄金文件里的第一个）')
    ap.add_argument('--golden', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    df, TE, future = load_golden_labels()
    oos = df.index > TE
    base_rate = float((future[oos] == 1).mean())
    vals = load_signal(args.signal)

    if args.kind == 'capital_linkage':
        sig = to_series(vals, df, 'tau')
        train_mean = float(sig[sig.index <= TE].mean())
        train_std = float(sig[sig.index <= TE].std(ddof=1))
        z = (sig - train_mean) / (train_std or 1.0)
        thresholds = [0.5, 0.75, 1.0, 1.25]
    else:
        sig = to_series(vals, df, 'dispersion')
        train_mean = float(sig[sig.index <= TE].mean())
        train_std = float(sig[sig.index <= TE].std(ddof=1))
        z = (sig - train_mean) / (train_std or 1.0)
        thresholds = [0.5, 1.0, 1.5]

    out = {'kind': args.kind, 'signal_file': args.signal, 'train_end': str(TE.date()),
           'train_mean': train_mean, 'train_std': train_std, 'base_rate_20d': base_rate,
           'thresholds': {}, 'lead_profile': []}

    for thr in thresholds:
        s = (z[oos] > thr)
        s = s.fillna(False)
        y = future[oos]
        tp = int((s & (y == 1)).sum()); fp = int((s & (y == 0)).sum()); fn = int((~s & (y == 1)).sum())
        prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
        out['thresholds'][str(thr)] = {
            'trigger_rate': float(s.mean()), 'precision': prec, 'recall': rec,
            'f1': 2 * prec * rec / max(1e-12, prec + rec),
            'lift': prec / base_rate if base_rate else None, 'tp': tp, 'fp': fp, 'fn': fn}

    cs = df['cfsi']
    for h in [0, 5, 10, 20, 40, 60]:
        c = sig.corr(cs.shift(-h))
        out['lead_profile'].append({'h': h, 'corr': None if c != c else float(c)})
    valid = [p for p in out['lead_profile'] if p['corr'] is not None]
    out['peak_h'] = max(valid, key=lambda p: abs(p['corr']))['h'] if valid else None

    # 与黄金向量逐点比对
    golden_path = args.golden or f'/mnt/shared/recently/CBR/contracts/golden-vectors/{args.kind}_reference.json'
    if os.path.exists(golden_path):
        g = json.load(open(golden_path, encoding='utf-8'))
        field = 'tau' if args.kind == 'capital_linkage' else 'dispersion'
        grows = g['rows']
        if 'pairs' in g:
            pname = args.pair or sorted(g['pairs'])[0]
            gpair = g['pairs'][pname]
            grows = gpair['rows']
            out['golden_pair'] = pname
        gmap = {r['date']: r.get(field) for r in grows}
        diffs, n = [], 0
        for d, v in sig.items():
            gv = gmap.get(str(d.date()))
            if gv is None or v != v:
                continue
            n += 1
            diffs.append(abs(v - gv))
        out['golden'] = {'file': golden_path, 'compared_points': n,
                         'max_abs_diff': max(diffs) if diffs else None,
                         'mean_abs_diff': float(np.mean(diffs)) if diffs else None,
                         'tolerance': TOL,
                         'pass': bool(diffs and max(diffs) <= TOL)}
    else:
        out['golden'] = {'file': golden_path, 'pass': None, 'note': '黄金向量不存在，跳过比对'}

    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
        json.dump(out, open(args.out, 'w'), ensure_ascii=False, indent=1)
    if out['golden'].get('pass') is False:
        sys.exit(3)


if __name__ == '__main__':
    main()
