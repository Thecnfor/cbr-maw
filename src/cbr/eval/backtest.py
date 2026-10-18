"""滚动样本外回测（P1 预警表现）与消融对照。

与具体数据实现解耦：只要求调用方提供
- ``signal_fn(as_of) -> RiskSignal``：as_of 当日可得的共享风险信号；
- ``label_fn(as_of, horizon) -> int | None``：as_of 之后 horizon 个交易日的高压力标签。

回测严格按日期滚动：每个评估日只使用当日信号，标签只用于事后评价。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .metrics import (
    bootstrap_ci,
    ece,
    lead_time_days,
    paired_bootstrap_test,
    pr_auc,
    recall_at_rate,
    summarize_classification,
)

SignalFn = Callable[[date], Any]
LabelFn = Callable[[date, int], int | None]


@dataclass
class HorizonResult:
    horizon: int
    n: int = 0
    positives: int = 0
    skipped: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    lead_time: dict[str, float] = field(default_factory=dict)
    y_true: list[int] = field(default_factory=list)
    y_score: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    name: str
    start: str
    end: str
    horizons: list[HorizonResult] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "config": self.config,
            "horizons": [asdict(h) for h in self.horizons],
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def table_markdown(self) -> str:
        """生成论文/技术文档用指标表（每个期限一行）。"""

        def fmt(value: float, digits: int = 3) -> str:
            return "—" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"

        head = (
            "| 期限 | n | 正例率 | PR-AUC | PR-AUC 95%CI | Recall@10% | Brier | ECE | 平均提前期(日) |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
        )
        rows = []
        for h in self.horizons:
            m = h.metrics
            ci = m.get("pr_auc_ci", {})
            ci_txt = f"[{fmt(ci.get('ci_low'))}, {fmt(ci.get('ci_high'))}]"
            rows.append(
                f"| h={h.horizon} | {h.n} | {fmt(m.get('prevalence'))} | "
                f"{fmt(m.get('pr_auc'))} | {ci_txt} | "
                f"{fmt(m.get('recall_top_rate'))} | "
                f"{fmt(m.get('brier'))} | {fmt(m.get('ece'))} | "
                f"{fmt(h.lead_time.get('mean'), 1)} |"
            )
        return head + "\n".join(rows) + "\n"


def _safe_signal(signal_fn: SignalFn, as_of: date):
    try:
        return signal_fn(as_of)
    except Exception:  # noqa: BLE001 - 单日失败跳过，不中断回测
        return None


def _safe_label(label_fn: LabelFn, as_of: date, horizon: int) -> int | None:
    try:
        value = label_fn(as_of, horizon)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return None
    return int(value)


def run_backtest(
    name: str,
    signal_fn: SignalFn,
    label_fn: LabelFn,
    eval_dates: Sequence[date],
    horizons: Sequence[int] = (5, 10, 20),
    warning_threshold: float | None = 0.5,
    warning_quantile: float | None = None,
    n_boot: int = 200,
    config: dict[str, Any] | None = None,
) -> BacktestResult:
    """在给定评估日集合上回测信号；返回每个期限的指标与预警提前期。

    Args:
        warning_threshold: 绝对概率阈值（默认 0.5）；``None`` 时忽略。
        warning_quantile: 若设置，则以该分位数的预测概率作为预警阈值（如 0.9=前10%预警日），
            与 top-decile 召回口径一致，用于计算预警提前期。
    """
    dates = sorted(set(eval_dates))
    result = BacktestResult(
        name=name,
        start=str(dates[0]) if dates else "",
        end=str(dates[-1]) if dates else "",
        config=config or {},
    )
    if not dates:
        return result

    # 真实高压力状态：actual_stress[d] = label(d-1, 1)（label 使用未来 1 日信息，仅评估用）
    stress_flags: list[int] = []
    for i, d in enumerate(dates):
        if i == 0:
            stress_flags.append(0)
            continue
        prev_label = _safe_label(label_fn, dates[i - 1], 1)
        stress_flags.append(int(prev_label) if prev_label is not None else 0)

    for horizon in horizons:
        y_true: list[int] = []
        y_score: list[float] = []
        keep_dates: list[str] = []
        skipped = 0
        for d in dates:
            label = _safe_label(label_fn, d, int(horizon))
            signal = _safe_signal(signal_fn, d)
            score: float | None = None
            if signal is not None:
                try:
                    score = float(signal.horizons[int(horizon)])
                except (KeyError, TypeError, ValueError):
                    score = None
            if label is None or score is None or not np.isfinite(score):
                skipped += 1
                continue
            y_true.append(int(label))
            y_score.append(score)
            keep_dates.append(str(d))

        hr = HorizonResult(horizon=int(horizon), n=len(y_true), positives=int(sum(y_true)),
                           skipped=skipped, y_true=y_true, y_score=y_score, dates=keep_dates)
        if y_true:
            hr.metrics = summarize_classification(y_true, y_score, n_boot=n_boot)
            if warning_quantile is not None:
                threshold = float(np.quantile(np.asarray(y_score), float(warning_quantile)))
            else:
                threshold = float(warning_threshold) if warning_threshold is not None else 0.5
            warn = [1 if s >= threshold else 0 for s in y_score]
            # 用与 y_true 对应的日期序列构造 stress 子序列（保持顺序）
            pos = {d: i for i, d in enumerate(keep_dates)}
            stress_seq = [stress_flags[dates.index(date.fromisoformat(d))] for d in keep_dates] if pos else []
            hr.lead_time = lead_time_days(warn, stress_seq)
        result.horizons.append(hr)
    return result


def compare_ablation(
    result_a: BacktestResult,
    result_b: BacktestResult,
    horizon: int,
    n_boot: int = 200,
) -> dict[str, float]:
    """同一评估日集合上比较两个方案（A-B）的 PR-AUC 差异与配对自助法 p 值。"""
    ha = next((h for h in result_a.horizons if h.horizon == horizon), None)
    hb = next((h for h in result_b.horizons if h.horizon == horizon), None)
    if ha is None or hb is None:
        raise ValueError(f"结果中缺少 horizon={horizon}")
    map_a = dict(zip(ha.dates, zip(ha.y_true, ha.y_score)))
    map_b = dict(zip(hb.dates, zip(hb.y_true, hb.y_score)))
    common = sorted(set(map_a) & set(map_b))
    if not common:
        raise ValueError("两个方案没有共同评估日")
    y = [map_a[d][0] for d in common]
    a = [map_a[d][1] for d in common]
    b = [map_b[d][1] for d in common]
    out = paired_bootstrap_test(y, a, b, pr_auc, n_boot=n_boot)
    out["n"] = len(common)
    out["horizon"] = horizon
    out["pr_auc_a"] = pr_auc(y, a)
    out["pr_auc_b"] = pr_auc(y, b)
    return out
