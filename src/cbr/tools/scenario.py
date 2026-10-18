"""scenario：给定冲击（汇率贬 x%、美股跌 y%、利差走阔 z bp）的情景映射与压力传导。

两种确定性方法：
- ``linear``：在历史上回归 r_target ~ b1·r_us + b2·Δfx + b3·Δspread(bp)，
  再用冲击向量线性映射目标收益；贡献分解用于"压力传导渠道"解释；
- ``historical``：把冲击向量标准化后，在历史观测中找欧氏距离最近的 K 天
  （历史类比情景），统计目标收益的均值/中位数/最差表现与发生日期。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._numeric import ols, r, simple_returns
from .base import BaseTool, ToolError, ToolOutput
from .settings import DEFAULT_SERIES


class ScenarioParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_series_id: str | None = None
    us_equity_series_id: str | None = None
    fx_series_id: str | None = None
    spread_series_id: str | None = None
    lookback: int = Field(252, ge=60, le=2000)
    us_equity_drop_pct: float = Field(10.0, ge=0.0, le=100.0)
    fx_depreciation_pct: float = Field(5.0, ge=0.0, le=100.0)
    spread_widening_bp: float = Field(100.0, ge=0.0, le=1000.0)
    method: Literal["linear", "historical", "both"] = "both"
    analog_k: int = Field(10, ge=1, le=50)
    spread_unit: Literal["pct", "bp"] = "bp"
    min_observations: int = Field(60, ge=20, le=2000)
    values_are: Literal["price", "return"] = "price"


def _return_map(items: list[tuple[date, float]], values_are: str) -> dict[date, float]:
    if values_are == "price":
        vals = np.asarray([v for _, v in items], dtype=float)
        if vals.size < 2:
            return {}
        rets = simple_returns(vals)
        return {items[i + 1][0]: float(rets[i]) for i in range(rets.size)}
    return {d: float(v) for d, v in items}


def _spread_change_map(
    items: list[tuple[date, float]], spread_unit: Literal["pct", "bp"]
) -> dict[date, float]:
    """利差水平序列 -> 利差变化（bp）。"""
    vals = np.asarray([v for _, v in items], dtype=float)
    if vals.size < 2:
        return {}
    diffs = np.diff(vals)
    factor = 100.0 if spread_unit == "pct" else 1.0
    return {items[i + 1][0]: float(diffs[i] * factor) for i in range(diffs.size)}


class ScenarioTool(BaseTool):
    name = "scenario"
    description = "汇率/美股/利差冲击的线性与历史类比情景映射及压力传导（确定性纯计算）"
    unit = "ratio"
    params_model = ScenarioParams

    def compute(self, as_of: date, params: ScenarioParams) -> ToolOutput:
        target_id = self._series_param(params.target_series_id, "target_series_id", DEFAULT_SERIES)
        us_id = self._series_param(params.us_equity_series_id, "us_equity_series_id", DEFAULT_SERIES)
        fx_id = self._series_param(params.fx_series_id, "fx_series_id", DEFAULT_SERIES)
        spread_id = self._series_param(params.spread_series_id, "spread_series_id", DEFAULT_SERIES)

        target_items = self._history(target_id, as_of, params.lookback)
        us_items = self._history(us_id, as_of, params.lookback)
        fx_items = self._history(fx_id, as_of, params.lookback)
        spread_items = self._history(spread_id, as_of, params.lookback)

        target_map = _return_map(target_items, params.values_are)
        us_map = _return_map(us_items, params.values_are)
        fx_map = _return_map(fx_items, "price")  # 汇率按价格序列取变动率
        spread_map = _spread_change_map(spread_items, params.spread_unit)

        common = sorted(set(target_map) & set(us_map) & set(fx_map) & set(spread_map))
        if len(common) < params.min_observations:
            raise ToolError(
                f"insufficient aligned scenario observations: {len(common)} "
                f"< min_observations={params.min_observations}"
            )

        y = np.asarray([target_map[d] for d in common], dtype=float)
        factors = np.column_stack(
            [
                np.asarray([us_map[d] for d in common], dtype=float),
                np.asarray([fx_map[d] for d in common], dtype=float),
                np.asarray([spread_map[d] for d in common], dtype=float),
            ]
        )
        factor_names = ["us_equity_return", "fx_change", "spread_change_bp"]

        shocks = {
            "us_equity_drop_pct": params.us_equity_drop_pct,
            "fx_depreciation_pct": params.fx_depreciation_pct,
            "spread_widening_bp": params.spread_widening_bp,
        }
        shock_vector = np.asarray(
            [
                -params.us_equity_drop_pct / 100.0,  # 美股下跌的收益冲击
                params.fx_depreciation_pct / 100.0,  # 人民币贬值（USDCNY 上行）
                params.spread_widening_bp,  # 利差走阔（bp）
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(y)) or not np.all(np.isfinite(factors)):
            raise ToolError("non-finite values encountered in aligned scenario data")

        # ---- 线性映射 ----
        intercept, betas, r2 = ols(y, factors)
        contributions = {
            name: float(betas[i] * shock_vector[i]) for i, name in enumerate(factor_names)
        }
        expected_target_return = float(sum(contributions.values()))
        linear_payload = {
            "expected_target_return": r(expected_target_return),
            "contributions": {k: r(v) for k, v in contributions.items()},
            "betas": {name: r(float(betas[i])) for i, name in enumerate(factor_names)},
            "intercept": r(intercept),
            "r2": r(r2),
            "shock_vector": {
                "us_equity_return": r(shock_vector[0]),
                "fx_change": r(shock_vector[1]),
                "spread_change_bp": r(shock_vector[2]),
            },
        }

        # ---- 历史类比情景 ----
        means = np.mean(factors, axis=0)
        stds = np.std(factors, axis=0, ddof=1)
        safe_stds = np.where(stds > 1e-12, stds, 1.0)
        z_factors = (factors - means) / safe_stds
        z_shock = (shock_vector - means) / safe_stds
        distances = np.sqrt(np.sum((z_factors - z_shock) ** 2, axis=1))
        k = min(params.analog_k, len(common))
        analog_idx = np.argsort(distances, kind="stable")[:k]
        analog_returns = y[analog_idx]
        historical_payload = {
            "analog_count": int(k),
            "analog_mean_return": r(float(np.mean(analog_returns))),
            "analog_median_return": r(float(np.median(analog_returns))),
            "analog_worst_return": r(float(np.min(analog_returns))),
            "analog_best_return": r(float(np.max(analog_returns))),
            "analog_dates": [common[i].isoformat() for i in analog_idx],
            "analog_mean_factors": {
                name: r(float(means[i] + np.mean(z_factors[analog_idx, i]) * safe_stds[i]))
                for i, name in enumerate(factor_names)
            },
            "shock_distance_min": r(float(distances[analog_idx[0]])),
        }

        method = params.method
        linear = linear_payload if method in ("linear", "both") else None
        historical = historical_payload if method in ("historical", "both") else None
        primary_return = (
            float(linear_payload["expected_target_return"])
            if linear is not None
            else float(historical_payload["analog_mean_return"] or 0.0)
        )
        stress_transmission = {
            "target_return_linear": r(expected_target_return) if linear is not None else None,
            "target_return_analog_mean": (
                historical_payload["analog_mean_return"] if historical is not None else None
            ),
            "target_return_analog_worst": (
                historical_payload["analog_worst_return"] if historical is not None else None
            ),
            "primary_method": "linear" if method == "linear" else ("historical" if method == "historical" else "linear"),
        }

        data = {
            "target_series_id": target_id,
            "us_equity_series_id": us_id,
            "fx_series_id": fx_id,
            "spread_series_id": spread_id,
            "lookback": params.lookback,
            "observations": int(len(common)),
            "window_start": common[0].isoformat(),
            "window_end": common[-1].isoformat(),
            "method": method,
            "values_are": params.values_are,
            "spread_unit": params.spread_unit,
            "analog_k": params.analog_k,
            "shocks": shocks,
            "linear": linear,
            "historical": historical,
            "stress_transmission": stress_transmission,
            "unit_map": {
                "expected_target_return": "ratio",
                "contributions": "ratio",
                "analog_mean_return": "ratio",
                "analog_worst_return": "ratio",
                "spread_change_bp": "bp",
            },
        }
        summary = (
            f"情景冲击（美股 -{params.us_equity_drop_pct:.1f}%、人民币贬值 "
            f"{params.fx_depreciation_pct:.1f}%、利差 +{params.spread_widening_bp:.0f}bp）→ "
            f"{target_id} 线性映射收益 {expected_target_return * 100:+.2f}%"
        )
        if historical is not None:
            summary += (
                f"；历史近邻 {k} 日平均 "
                f"{(historical_payload['analog_mean_return'] or 0) * 100:+.2f}%、"
                f"最差 {(historical_payload['analog_worst_return'] or 0) * 100:+.2f}%"
            )
        summary += "。"

        return ToolOutput(
            data=data,
            unit="ratio",
            value=r(primary_return),
            title=f"情景压力测试 @ {as_of.isoformat()}",
            summary=summary,
        )
