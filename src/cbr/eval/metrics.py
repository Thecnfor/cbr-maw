"""P1 预警表现评估指标与统计检验（论文 5.3 / 6.x）。

仅依赖 numpy / scikit-learn；所有函数输入为一维数组（y_true∈{0,1}, y_score∈[0,1]）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def _to_arrays(y_true: Sequence[int] | np.ndarray, y_score: Sequence[float] | np.ndarray):
    yt = np.asarray(y_true, dtype=float).ravel()
    ys = np.asarray(y_score, dtype=float).ravel()
    if yt.shape != ys.shape:
        raise ValueError(f"y_true/y_score 长度不一致: {yt.shape} vs {ys.shape}")
    if yt.size == 0:
        raise ValueError("输入为空数组")
    return yt, ys


def pr_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """PR-AUC（average precision）。"""
    yt, ys = _to_arrays(y_true, y_score)
    if yt.sum() == 0:
        return float("nan")
    return float(average_precision_score(yt, ys))


def roc_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    yt, ys = _to_arrays(y_true, y_score)
    if yt.sum() == 0 or yt.sum() == yt.size:
        return float("nan")
    return float(roc_auc_score(yt, ys))


def top_k_indices(y_score: Sequence[float], rate: float) -> np.ndarray:
    """按分数降序取前 rate 比例的样本索引。"""
    ys = np.asarray(y_score, dtype=float).ravel()
    k = max(1, int(np.ceil(rate * ys.size)))
    return np.argsort(-ys, kind="stable")[:k]


def recall_at_rate(y_true: Sequence[int], y_score: Sequence[float], rate: float = 0.1) -> float:
    """预警率固定为 rate 时的召回率（高风险事件被提前识别的比例）。"""
    yt, ys = _to_arrays(y_true, y_score)
    positives = yt.sum()
    if positives == 0:
        return float("nan")
    idx = top_k_indices(ys, rate)
    return float(yt[idx].sum() / positives)


def precision_at_rate(y_true: Sequence[int], y_score: Sequence[float], rate: float = 0.1) -> float:
    yt, ys = _to_arrays(y_true, y_score)
    idx = top_k_indices(ys, rate)
    return float(yt[idx].mean())


def recall_at_top_decile(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """固定预警率为前 10% 时的召回率（实验配置中的指标名）。"""
    return recall_at_rate(y_true, y_score, 0.1)


def precision_at_top_decile(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    return precision_at_rate(y_true, y_score, 0.1)


def recall_at_fpr(y_true: Sequence[int], y_score: Sequence[float], fpr_target: float = 0.1) -> float:
    """误报率不超过 fpr_target 时的最大召回率。"""
    yt, ys = _to_arrays(y_true, y_score)
    if yt.sum() == 0:
        return float("nan")
    order = np.argsort(-ys, kind="stable")
    yt_sorted = yt[order]
    total_pos = yt.sum()
    total_neg = yt.size - total_pos
    tp = np.cumsum(yt_sorted)
    fp = np.cumsum(1 - yt_sorted)
    fpr = fp / max(total_neg, 1)
    valid = fpr <= fpr_target
    if not valid.any():
        return 0.0
    return float((tp[valid] / total_pos).max())


def brier(y_true: Sequence[int], prob: Sequence[float]) -> float:
    yt, ps = _to_arrays(y_true, prob)
    return float(brier_score_loss(yt, np.clip(ps, 0.0, 1.0)))


def ece(y_true: Sequence[int], prob: Sequence[float], n_bins: int = 10) -> float:
    """期望校准误差（Expected Calibration Error）。"""
    yt, ps = _to_arrays(y_true, prob)
    ps = np.clip(ps, 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        if i == n_bins - 1:
            mask = (ps >= bins[i]) & (ps <= bins[i + 1])
        else:
            mask = (ps >= bins[i]) & (ps < bins[i + 1])
        if mask.sum() == 0:
            continue
        total += mask.mean() * abs(yt[mask].mean() - ps[mask].mean())
    return float(total)


def lead_time_days(
    warning_flags: Sequence[int],
    label_flags: Sequence[int],
    max_lookback: int = 30,
) -> dict[str, float]:
    """计算预警提前期（交易日）。

    warning_flags[t]=1 表示 t 日发出预警；label_flags[t]=1 表示 t 日处于高压力状态。
    对每个连续高压力事件段，取其起点之前 max_lookback 天内最近一次预警的起点：
    lead = 事件起点 - 预警起点。返回 mean/median/min/max/n_events。
    """
    w = np.asarray(warning_flags, dtype=int).ravel()
    y = np.asarray(label_flags, dtype=int).ravel()
    if w.shape != y.shape:
        raise ValueError("warning_flags/label_flags 长度不一致")
    if w.size != y.size:
        raise ValueError("长度不一致")
    events = []
    i = 0
    while i < y.size:
        if y[i] == 1:
            start = i
            while i < y.size and y[i] == 1:
                i += 1
            events.append(start)
        else:
            i += 1
    leads: list[int] = []
    for start in events:
        window_start = max(0, start - max_lookback)
        prior = np.where(w[window_start:start] == 1)[0]
        if prior.size:
            leads.append(start - (window_start + int(prior[0])))
    if not leads:
        return {"mean": float("nan"), "median": float("nan"), "min": float("nan"),
                "max": float("nan"), "n_events": float(len(events)), "n_warned": 0.0}
    arr = np.asarray(leads, dtype=float)
    return {
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "n_events": float(len(events)),
        "n_warned": float(len(leads)),
    }


# --------------------------------------------------------------------------- #
# 统计检验
# --------------------------------------------------------------------------- #
def bootstrap_ci(
    y_true: Sequence[int],
    y_score: Sequence[float],
    metric_fn: Callable[[Sequence[int], Sequence[float]], float] = pr_auc,
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float]:
    """对指标做样本自助法置信区间。"""
    rng = np.random.default_rng(seed)
    yt, ys = _to_arrays(y_true, y_score)
    n = yt.size
    vals: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            v = metric_fn(yt[idx], ys[idx])
        except ValueError:
            continue
        if np.isfinite(v):
            vals.append(float(v))
    point = float(metric_fn(yt, ys))
    if not vals:
        return {"value": point, "ci_low": float("nan"), "ci_high": float("nan")}
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"value": point, "ci_low": float(lo), "ci_high": float(hi)}


def paired_bootstrap_test(
    y_true: Sequence[int],
    score_a: Sequence[float],
    score_b: Sequence[float],
    metric_fn: Callable[[Sequence[int], Sequence[float]], float] = pr_auc,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict[str, float]:
    """配对自助法检验 H0: metric(A) == metric(B)。

    返回 delta = metric(A) - metric(B)、置信区间与双侧 p 值。
    用于 P1/P2/P3 消融对照（同一评估日、同一标签，仅模块不同）。
    """
    yt, a = _to_arrays(y_true, score_a)
    yt2, b = _to_arrays(y_true, score_b)
    if not np.array_equal(yt, yt2):
        raise ValueError("两个方案必须使用相同的 y_true")
    rng = np.random.default_rng(seed)
    n = yt.size
    base_a = metric_fn(yt, a)
    base_b = metric_fn(yt, b)
    delta = float(base_a - base_b)
    diffs: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            d = metric_fn(yt[idx], a[idx]) - metric_fn(yt[idx], b[idx])
        except ValueError:
            continue
        if np.isfinite(d):
            diffs.append(float(d))
    if not diffs:
        return {"delta": delta, "ci_low": float("nan"), "ci_high": float("nan"), "p_value": float("nan")}
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p = 2.0 * min((np.sum(np.asarray(diffs) <= 0) + 1) / (len(diffs) + 1),
                  (np.sum(np.asarray(diffs) >= 0) + 1) / (len(diffs) + 1))
    return {"delta": delta, "ci_low": float(lo), "ci_high": float(hi), "p_value": float(min(1.0, p))}


def summarize_classification(
    y_true: Sequence[int],
    y_score: Sequence[float],
    rate: float = 0.1,
    n_boot: int = 500,
) -> dict[str, Any]:
    """一次性输出 P1 常用指标与 PR-AUC 置信区间。"""
    yt, ys = _to_arrays(y_true, y_score)
    return {
        "n": int(yt.size),
        "positives": int(yt.sum()),
        "prevalence": float(yt.mean()),
        "pr_auc": pr_auc(yt, ys),
        "pr_auc_ci": bootstrap_ci(yt, ys, pr_auc, n_boot=n_boot),
        "roc_auc": roc_auc(yt, ys),
        "recall_top_rate": recall_at_rate(yt, ys, rate),
        "precision_top_rate": precision_at_rate(yt, ys, rate),
        "precision_top_rate_value": float(rate),
        "recall_at_fpr_10": recall_at_fpr(yt, ys, 0.1),
        "brier": brier(yt, ys),
        "ece": ece(yt, ys),
    }


# 实验配置中的指标名 -> 评估函数映射（供 scripts/run_experiment.py 使用）
METRIC_ALIASES: dict[str, Callable[..., float]] = {
    "pr_auc": pr_auc,
    "roc_auc": roc_auc,
    "recall_at_top_decile": recall_at_top_decile,
    "recall_at_rate": recall_at_rate,
    "precision_at_top_decile": precision_at_top_decile,
    "brier": brier,
    "ece": ece,
}
