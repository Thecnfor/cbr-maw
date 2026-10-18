"""模型评估指标（P1 预警能力）：PR-AUC、ROC-AUC、Brier、ECE、召回率等。

所有指标在给定评估日集合上计算；``y_prob`` 为未来 h 日高压力的预测概率，
``y_true`` 为对应标签。对单类/样本不足的退化情形返回保守值，保证实验流水线
不因个别期限样本不足而崩溃。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:  # pragma: no cover
    from sklearn.metrics import average_precision_score, roc_auc_score

    HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    HAS_SKLEARN = False


def expected_calibration_error(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> float:
    """期望校准误差（ECE）：按预测概率分箱后 |准确率 - 平均预测概率| 的加权和。"""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    valid = np.isfinite(y_true) & np.isfinite(y_prob)
    y_true, y_prob = y_true[valid], y_prob[valid]
    if y_true.size == 0:
        return 0.0
    bins = np.clip((y_prob * n_bins).astype(int), 0, n_bins - 1)
    ece = 0.0
    for bin_id in range(n_bins):
        mask = bins == bin_id
        if not mask.any():
            continue
        gap = abs(float(y_true[mask].mean()) - float(y_prob[mask].mean()))
        ece += gap * float(mask.mean())
    return float(ece)


def recall_at_top_fraction(y_true: np.ndarray, y_prob: np.ndarray, fraction: float = 0.1) -> float:
    """Top-k% 高概率样本的召回率（预警场景：高风险端召回）。"""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    valid = np.isfinite(y_true) & np.isfinite(y_prob)
    y_true, y_prob = y_true[valid], y_prob[valid]
    if y_true.size == 0 or y_true.sum() == 0:
        return 0.0
    k = max(1, int(round(y_true.size * float(fraction))))
    order = np.argsort(-y_prob)[:k]
    return float(y_true[order].sum() / y_true.sum())


def classification_metrics(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    threshold: float = 0.5,
    top_fraction: float = 0.1,
) -> dict[str, Any]:
    """计算二分类预警指标。

    Args:
        y_true: 0/1 标签（可含 NaN，自动剔除）。
        y_prob: 正类概率。
        threshold: 固定阈值（用于 precision/recall/f1）。
        top_fraction: Top-k% 召回的分位。

    Returns:
        指标字典：``n``、``n_pos``、``pos_rate``、``pr_auc``、``roc_auc``、
        ``brier``、``ece``、``precision``、``recall``、``f1``、``recall_top10pct``。
    """
    truth = pd.Series(y_true, dtype=float).reset_index(drop=True)
    prob = pd.Series(y_prob, dtype=float).reset_index(drop=True)
    valid = truth.notna() & prob.notna()
    truth = truth[valid].to_numpy(dtype=float)
    prob = prob[valid].to_numpy(dtype=float)
    n = int(truth.size)
    n_pos = int(np.nansum(truth > 0.5)) if n else 0
    base: dict[str, Any] = {
        "n": n,
        "n_pos": n_pos,
        "pos_rate": float(n_pos / n) if n else 0.0,
        "pr_auc": 0.0,
        "roc_auc": 0.5,
        "brier": 0.0,
        "ece": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "recall_top10pct": 0.0,
        "threshold": float(threshold),
    }
    if n == 0:
        return base
    base["brier"] = float(np.mean((prob - truth) ** 2))
    base["ece"] = expected_calibration_error(truth, prob)
    base["recall_top10pct"] = recall_at_top_fraction(truth, prob, top_fraction)
    predicted = (prob >= threshold).astype(float)
    tp = float(np.sum((predicted > 0) & (truth > 0.5)))
    fp = float(np.sum((predicted > 0) & (truth <= 0.5)))
    fn = float(np.sum((predicted <= 0) & (truth > 0.5)))
    base["precision"] = tp / (tp + fp) if (tp + fp) else 0.0
    base["recall"] = tp / (tp + fn) if (tp + fn) else 0.0
    if base["precision"] + base["recall"] > 0:
        base["f1"] = 2 * base["precision"] * base["recall"] / (base["precision"] + base["recall"])
    if HAS_SKLEARN and 0 < n_pos < n:
        base["pr_auc"] = float(average_precision_score(truth > 0.5, prob))
        base["roc_auc"] = float(roc_auc_score(truth > 0.5, prob))
    elif 0 < n_pos < n:  # pragma: no cover - 无 sklearn 的兜底实现
        order = np.argsort(-prob)
        truth_sorted = (truth[order] > 0.5).astype(float)
        precision_curve = np.cumsum(truth_sorted) / (np.arange(n) + 1)
        base["pr_auc"] = float(np.sum(precision_curve * truth_sorted) / max(n_pos, 1))
        # ROC-AUC 用秩和公式
        ranks = np.argsort(np.argsort(prob)) + 1
        pos_ranks = ranks[truth > 0.5]
        base["roc_auc"] = float(
            (pos_ranks.sum() - n_pos * (n_pos + 1) / 2) / (n_pos * (n - n_pos))
        )
    return base


def summarize_by_horizon(metrics: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """把多个期限的指标聚合成平均值（便于论文表格/实验对比）。"""
    if not metrics:
        return {}
    keys = [key for key in next(iter(metrics.values())).keys() if isinstance(metrics[next(iter(metrics))][key], (int, float))]
    summary: dict[str, Any] = {}
    for key in keys:
        values = [float(metrics[h][key]) for h in metrics if key in metrics[h]]
        summary[f"mean_{key}"] = float(np.mean(values)) if values else 0.0
    return summary
