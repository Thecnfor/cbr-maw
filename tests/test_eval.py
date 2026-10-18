"""P1 评估指标单元测试（Lead 维护）。"""

from __future__ import annotations

import numpy as np

from cbr.eval.metrics import (
    bootstrap_ci,
    brier,
    ece,
    lead_time_days,
    paired_bootstrap_test,
    pr_auc,
    recall_at_fpr,
    recall_at_rate,
    summarize_classification,
    top_k_indices,
)


def test_pr_auc_perfect_and_random() -> None:
    y = np.array([0, 0, 0, 1, 1])
    assert pr_auc(y, [0.1, 0.2, 0.05, 0.9, 0.8]) == 1.0
    rng = np.random.default_rng(0)
    y2 = rng.integers(0, 2, 2000)
    s2 = rng.random(2000)
    auc = pr_auc(y2, s2)
    assert abs(auc - y2.mean()) < 0.05


def test_top_rate_metrics() -> None:
    y = np.array([0, 0, 0, 1, 1])
    s = [0.1, 0.2, 0.05, 0.9, 0.8]
    idx = top_k_indices(s, 0.4)
    assert idx.size == 2
    assert recall_at_rate(y, s, 0.4) == 1.0
    # 阈值放宽（更低的误报约束）时召回不应下降
    assert recall_at_fpr(y, s, 0.5) >= recall_at_fpr(y, s, 0.0)


def test_brier_and_ece() -> None:
    y = np.array([0, 1, 0, 1])
    perfect = y.astype(float)
    assert brier(y, perfect) == 0.0
    assert ece(y, perfect, n_bins=4) < 1e-9
    assert brier(y, [0.5, 0.5, 0.5, 0.5]) == 0.25


def test_lead_time() -> None:
    # 预警发生在 t=2，事件起点 t=6，提前 4 天
    w = [0, 0, 1, 0, 0, 0, 0, 0]
    y = [0, 0, 0, 0, 0, 0, 1, 1]
    res = lead_time_days(w, y)
    assert res["mean"] == 4.0
    assert res["n_events"] == 1.0
    assert res["n_warned"] == 1.0


def test_bootstrap_and_paired() -> None:
    rng = np.random.default_rng(7)
    y = (rng.random(300) < 0.2).astype(int)
    good = np.clip(0.2 + 0.5 * y + rng.normal(0, 0.15, 300), 0, 1)
    bad = np.clip(0.2 + 0.15 * y + rng.normal(0, 0.15, 300), 0, 1)
    ci = bootstrap_ci(y, good, pr_auc, n_boot=200)
    assert ci["ci_low"] <= ci["value"] <= ci["ci_high"]
    test = paired_bootstrap_test(y, good, bad, pr_auc, n_boot=200)
    assert test["delta"] > 0
    assert 0.0 <= test["p_value"] <= 1.0


def test_summarize_keys() -> None:
    rng = np.random.default_rng(1)
    y = (rng.random(100) < 0.3).astype(int)
    s = rng.random(100)
    out = summarize_classification(y, s, rate=0.2, n_boot=50)
    for key in ("pr_auc", "roc_auc", "recall_top_rate", "brier", "ece", "pr_auc_ci"):
        assert key in out
