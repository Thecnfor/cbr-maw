"""生成两个新工具的黄金参考向量（供 Rust/Dart 回归断言逐点比对）。
输出：contracts/golden-vectors/capital_linkage_reference.json
      contracts/golden-vectors/dimension_dispersion_reference.json
数据源：真实 PIT 库（pit_real.duckdb）。运行：/tmp/cbrvenv/bin/python data/seed/gen_tool_golden.py
"""
import json, os, sys, math
import numpy as np, pandas as pd

sys.path.insert(0, '/mnt/shared/recently/commorcial/src')
from cbr.data.pit_store import PitStore
from cbr.data.labels import build_stress_labels

OUT = '/mnt/shared/recently/CBR/contracts/golden-vectors'
DB = os.environ.get('CBR_PIT_DB', '/mnt/shared/recently/commorcial/data/pit_real.duckdb')

def clean(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, (np.floating,)): return clean(float(o))
    if isinstance(o, (np.integer,)): return int(o)
    return o

def rolling_kendall(x, y, win=90, min_ratio=0.5):
    n = len(x); out = np.full(n, np.nan); xv, yv = x.values, y.values
    for i in range(win - 1, n):
        a, b = xv[i-win+1:i+1], yv[i-win+1:i+1]
        m = ~(np.isnan(a) | np.isnan(b)); k = int(m.sum())
        if k < max(15, int(win * min_ratio)): continue
        sa = np.sign(a[m][:, None] - a[m][None, :]); sb = np.sign(b[m][:, None] - b[m][None, :])
        iu = np.triu_indices(k, 1); out[i] = (sa[iu] * sb[iu]).mean()
    return pd.Series(out, index=x.index)

def main():
    store = PitStore.open(DB, writable=True)
    ds = store.load_market_dataset(with_documents=True)
    res = build_stress_labels(ds, label_version='stress_pca_q90')
    df = res.frame.copy(); wide = ds.daily_frame()
    TE = pd.Timestamp(res.train_end)
    hs = df['high_stress'].fillna(0).astype(int)
    future = pd.Series(0, index=df.index)
    for i in range(len(df)-1): future.iloc[i] = int(hs.iloc[i:i+20].max() == 1)
    oos = df.index > TE
    base_rate = float((future[oos] == 1).mean())

    # ---------- 1) capital_linkage（三组配对） ----------
    PAIRS = [
        ('csi300_x_northbound', 'market.cn_equity.csi300', 'crossborder.flows.northbound_net'),
        ('usdcny_x_vix', 'market.fx.usdcny', 'market.global.vix'),
        ('csi300_x_sp500', 'market.cn_equity.csi300', 'market.global.sp500'),
    ]
    y = future[oos]
    cap = {"pairs": {}, "base_rate_20d": base_rate,
           "spec_common": {"mode": "returns(pct_change)", "window": 90, "min_obs_ratio": 0.5,
                           "estimator": "kendall_tau", "train_end": str(TE.date()),
                           "threshold_z": 0.5},
           "note": "变化率口径；水平口径无效（比值 1.10、p=0.115），实现必须用 pct_change。窗口内有效样本不足 50% → null。"}
    for pname, sa, sb in PAIRS:
        tau = rolling_kendall(wide[sa].pct_change(), wide[sb].pct_change(), 90)
        tr = tau.index <= TE
        mu, sd = float(tau[tr].mean()), float(tau[tr].std(ddof=1))
        z = (tau - mu) / (sd or 1)
        thr = 0.5
        sig = (z[oos] > thr)
        tp = int((sig & (y == 1)).sum()); fp = int((sig & (y == 0)).sum())
        fn = int((~sig & (y == 1)).sum())
        prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
        rows = [{"date": str(d.date()),
                 "tau": None if pd.isna(tau.loc[d]) else round(float(tau.loc[d]), 10),
                 "z": None if pd.isna(z.loc[d]) else round(float(z.loc[d]), 10)}
                for d in df.index]
        lead = [{"h": h, "corr": (None if pd.isna(tau.corr(df['cfsi'].shift(-h))) else round(float(tau.corr(df['cfsi'].shift(-h))), 6))}
                for h in [0, 5, 10, 20, 40, 60]]
        cap['pairs'][pname] = {
            "series_a": sa, "series_b": sb,
            "train_mean": mu, "train_std": sd, "threshold_z": thr,
            "metrics": {"base_rate_20d": base_rate, "precision": prec, "recall": rec,
                        "f1": 2*prec*rec/max(1e-12, prec+rec), "lift": prec/base_rate if base_rate else None,
                        "trigger_rate": float(sig.mean()), "tp": tp, "fp": fp, "fn": fn},
            "lead_profile": lead,
            "n_rows": len(rows), "rows": rows}
        print(f"capital_linkage[{pname}]: precision={prec:.4f} recall={rec:.4f} lift={prec/base_rate:.3f}")
    json.dump(clean(cap), open(f'{OUT}/capital_linkage_reference.json', 'w'), ensure_ascii=False, indent=1)

    # ---------- 2) dimension_dispersion ----------
    DIMS = ['dim_equity', 'dim_bond', 'dim_credit', 'dim_fx', 'dim_crossborder', 'dim_global']
    disp = df[DIMS].max(axis=1) - df[DIMS].min(axis=1)
    trd = disp.index <= TE
    dmu, dsd = float(disp[trd].mean()), float(disp[trd].std(ddof=1))
    dz = (disp - dmu) / (dsd or 1)
    dsig = (dz[oos] > 1.0)
    tp = int((dsig & (y == 1)).sum()); fp = int((dsig & (y == 0)).sum())
    fn = int((~dsig & (y == 1)).sum())
    p2 = tp / max(1, tp+fp); r2 = tp / max(1, tp+fn)
    # 压力窗前 40 日各维度均值 vs 平静期
    starts, prev = [], None
    for d in df.index[hs == 1]:
        if prev is None or (d - prev).days > 6: starts.append(d)
        prev = d
    near = np.array([any(abs((d - s).days) <= 60 for s in starts) for d in df.index])
    calm_mask = (hs.values == 0) & (~near)
    pre_idx = [df.index.get_loc(s) for s in starts if s > TE]
    pre_mean = pd.concat([df[DIMS].iloc[max(0, i-40):i] for i in pre_idx]).mean()
    calm_mean = df[DIMS][calm_mask].mean()
    rows2 = [{"date": str(d.date()),
              "dispersion": None if pd.isna(disp.loc[d]) else round(float(disp.loc[d]), 10),
              "z": None if pd.isna(dz.loc[d]) else round(float(dz.loc[d]), 10),
              "dominant_dim": None if df[DIMS].iloc[df.index.get_loc(d)].isna().all() else
                              str(df[DIMS].iloc[df.index.get_loc(d)].idxmax())}
             for d in df.index]
    dim = {
        "spec": {"dims": DIMS, "estimator": "max(dim)-min(dim)", "train_end": str(TE.date()),
                 "threshold_z": 1.0, "min_available_dims": 4},
        "train_mean": dmu, "train_std": dsd,
        "metrics": {"base_rate_20d": base_rate, "precision": p2, "recall": r2,
                    "f1": 2*p2*r2/max(1e-12, p2+r2), "lift": p2/base_rate if base_rate else None,
                    "trigger_rate": float(dsig.mean()), "tp": tp, "fp": fp, "fn": fn},
        "structure": {"pre_window_40d_mean": {k: float(pre_mean[k]) for k in DIMS},
                      "calm_mean": {k: float(calm_mean[k]) for k in DIMS},
                      "delta": {k: float(pre_mean[k] - calm_mean[k]) for k in DIMS}},
        "n_rows": len(rows2), "rows": rows2,
        "note": "缺失维度不参与、不得填 0；可用维度 <4 → insufficient_data。压力前结构：跨境资金/股票/全球恶化而信用与债券缓解。",
    }
    json.dump(clean(dim), open(f'{OUT}/dimension_dispersion_reference.json', 'w'), ensure_ascii=False, indent=1)
    print(f"capital_linkage: precision={prec:.4f} recall={rec:.4f} lift={prec/base_rate:.3f}")
    print(f"dimension_dispersion: precision={p2:.4f} recall={r2:.4f} lift={p2/base_rate:.3f}")

if __name__ == '__main__':
    main()
