"""回测与消融对照单元测试（Lead 维护）。"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from cbr.eval.backtest import BacktestResult, compare_ablation, run_backtest
from cbr.schemas import RiskLevel, RiskSignal

DATES = [date(2024, 1, 1) + timedelta(days=i) for i in range(60)]


def _signal_factory(good: bool):
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.1, len(DATES))

    def signal_fn(d: date) -> RiskSignal:
        idx = DATES.index(d)
        base = 0.5 + 0.2 * np.sin(idx / 6.0)
        p = float(np.clip(base if good else 0.5 + noise[idx], 0.01, 0.99))
        return RiskSignal(
            as_of=d,
            model_version="test",
            horizons={5: p, 10: p * 0.9, 20: p * 0.8},
            level=RiskLevel.HIGH if p > 0.6 else RiskLevel.LOW,
            evidence_id=f"ev_test_{d}",
        )

    return signal_fn


def _label_fn(d: date, horizon: int) -> int | None:
    idx = DATES.index(d)
    if idx + horizon >= len(DATES):
        return None
    return 1 if np.sin((idx + horizon) / 6.0) > 0.5 else 0


def test_backtest_runs() -> None:
    result = run_backtest("test", _signal_factory(True), _label_fn, DATES, horizons=(5,))
    assert isinstance(result, BacktestResult)
    assert result.horizons and result.horizons[0].n > 0
    assert "pr_auc" in result.horizons[0].metrics
    assert "mean" in result.horizons[0].lead_time
    assert "PR-AUC" in result.table_markdown()


def test_compare_ablation() -> None:
    a = run_backtest("good", _signal_factory(True), _label_fn, DATES, horizons=(5,), n_boot=100)
    b = run_backtest("noise", _signal_factory(False), _label_fn, DATES, horizons=(5,), n_boot=100)
    out = compare_ablation(a, b, horizon=5, n_boot=100)
    assert out["n"] > 0
    assert out["horizon"] == 5
    assert 0.0 <= out["p_value"] <= 1.0


def test_save(tmp_path) -> None:
    result = run_backtest("t", _signal_factory(True), _label_fn, DATES[:20], horizons=(5,), n_boot=20)
    path = result.save(tmp_path / "result.json")
    assert path.exists()
    assert "horizons" in path.read_text(encoding="utf-8")
