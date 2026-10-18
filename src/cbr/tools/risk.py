"""risk_measure：年化波动率、历史/参数 VaR、CVaR、最大回撤、压力分位。

全部为确定性纯计算；数据仅来自 ``DataProvider.history``（as_of 时点过滤）。
单位约定：VaR/CVaR 以"损失为正数"的比率表示（0.03 = 3% 损失）；
最大回撤为正幅度（0.35 = 35%）。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._numeric import (
    annualized_volatility,
    distribution_summary,
    historical_tail,
    max_drawdown,
    max_drawdown_from_returns,
    parametric_tail,
    quantile,
    r,
    returns_percentile,
    simple_returns,
    values_of,
)
from .base import BaseTool, ToolError, ToolOutput
from .settings import DEFAULT_SERIES


class RiskMeasureParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str | None = None
    lookback: int = Field(252, ge=30, le=2000)
    annualization: int = Field(252, ge=1, le=366)
    confidence: float = Field(0.95, gt=0.5, lt=1.0)
    horizon_days: int = Field(1, ge=1, le=60)
    values_are: Literal["price", "return"] = "price"
    min_observations: int = Field(20, ge=2, le=2000)


class RiskMeasureTool(BaseTool):
    name = "risk_measure"
    description = "年化波动率、历史/参数 VaR 与 CVaR、最大回撤、压力分位（确定性纯计算）"
    unit = "loss_ratio"
    params_model = RiskMeasureParams

    def compute(self, as_of: date, params: RiskMeasureParams) -> ToolOutput:
        series_id = self._series_param(params.series_id, "series_id", DEFAULT_SERIES)
        items = self._history(series_id, as_of, params.lookback)
        values = values_of(items)
        if values.size < 2:
            raise ToolError(f"series {series_id} has <2 observations as of {as_of}")

        if params.values_are == "price":
            returns = simple_returns(values)
            path = values
            mdd = max_drawdown(path)
        else:
            returns = values
            mdd = max_drawdown_from_returns(values)

        returns = returns[np.isfinite(returns)]
        if returns.size < params.min_observations:
            raise ToolError(
                f"insufficient return observations for {series_id}: "
                f"{returns.size} < min_observations={params.min_observations}"
            )

        var_hist, cvar_hist, _ = historical_tail(
            returns, params.confidence, params.horizon_days
        )
        var_param, cvar_param = parametric_tail(
            returns, params.confidence, params.horizon_days
        )
        vol_ann = annualized_volatility(returns, params.annualization)
        stress_quantiles = {
            "q01": r(quantile(returns, 0.01)),
            "q05": r(quantile(returns, 0.05)),
            "q10": r(quantile(returns, 0.10)),
        }
        dist = distribution_summary(returns)

        data = {
            "series_id": series_id,
            "values_are": params.values_are,
            "lookback": params.lookback,
            "observations": int(returns.size),
            "window_start": items[0][0].isoformat(),
            "window_end": items[-1][0].isoformat(),
            "annualization": params.annualization,
            "confidence": params.confidence,
            "horizon_days": params.horizon_days,
            # ---- 主指标（损失为正数，horizon 按 sqrt(h) 缩放） ----
            "annualized_volatility": r(vol_ann),
            "var_hist": r(var_hist),
            "cvar_hist": r(cvar_hist),
            "var_param": r(var_param),
            "cvar_param": r(cvar_param),
            "max_drawdown": r(mdd),
            "stress_quantiles": stress_quantiles,
            # ---- 当前状态 ----
            "latest_return": r(returns[-1]),
            "mean_daily_return": r(np.mean(returns)),
            "current_return_percentile": r(returns_percentile(returns)),
            "distribution": dist,
            "unit_map": {
                "annualized_volatility": "ratio_annual",
                "var_hist": "loss_ratio",
                "cvar_hist": "loss_ratio",
                "var_param": "loss_ratio",
                "cvar_param": "loss_ratio",
                "max_drawdown": "loss_ratio",
                "stress_quantiles": "return_ratio",
                "latest_return": "return_ratio",
                "mean_daily_return": "return_ratio",
                "current_return_percentile": "quantile_0_1",
            },
        }
        summary = (
            f"{series_id} 近 {returns.size} 个收益观测：年化波动率 "
            f"{(r(vol_ann) or 0) * 100:.2f}%，{params.confidence:.0%} "
            f"{params.horizon_days}日历史 VaR {(r(var_hist) or 0) * 100:.2f}%、"
            f"CVaR {(r(cvar_hist) or 0) * 100:.2f}%，最大回撤 "
            f"{(r(mdd) or 0) * 100:.2f}%。"
        )
        return ToolOutput(
            data=data,
            unit="loss_ratio",
            value=r(var_hist),
            title=f"风险测度：{series_id} @ {as_of.isoformat()}",
            summary=summary,
        )
