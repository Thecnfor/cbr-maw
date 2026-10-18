"""funding_cost：信用利差代理、融资成本变化（bp）、再融资窗口估计。

口径约定：
- 输入序列默认按 ``spread_unit="pct"`` 解读（1.5 = 1.5 个百分点 = 150bp）；
- ``funding_cost_change_bp`` = 最新利差 - ``momentum_window`` 个观测前的利差（bp）；
- ``refinancing_window_days``：以近 ``lookback`` 利差中位数为"正常融资条件"锚，
  若当前利差低于中位数，则按近 ``momentum_window`` 的日均走阔速度估计回到中位数
  所需交易日数（上限 ``refinancing_horizon_days``）；高于中位数则窗口关闭（0 日）。
- ``stress_level`` 按成本变化相对 ``cost_jump_bp`` / ``cost_medium_bp`` 阈值分档。
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._numeric import percentile_rank, r, values_of
from .base import BaseTool, ToolError, ToolOutput
from .settings import DEFAULT_SERIES


class FundingCostParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spread_series_id: str | None = None
    lookback: int = Field(252, ge=60, le=2000)
    momentum_window: int = Field(20, ge=1, le=120)
    spread_unit: Literal["pct", "bp"] = "pct"
    cost_jump_bp: float = Field(50.0, gt=0.0)
    cost_medium_bp: float = Field(25.0, ge=0.0)
    refinancing_horizon_days: int = Field(90, ge=1, le=365)


class FundingCostTool(BaseTool):
    name = "funding_cost"
    description = "信用利差代理、融资成本变化（bp）、再融资窗口估计（确定性纯计算）"
    unit = "bp"
    params_model = FundingCostParams

    def compute(self, as_of: date, params: FundingCostParams) -> ToolOutput:
        spread_id = self._series_param(
            params.spread_series_id, "spread_series_id", DEFAULT_SERIES
        )
        items = self._history(spread_id, as_of, params.lookback)
        levels = values_of(items)
        if levels.size < max(20, params.momentum_window + 5):
            raise ToolError(
                f"insufficient credit spread observations for {spread_id}: {levels.size}"
            )

        if params.spread_unit == "pct":
            spread_pct = levels
            spread_bp = levels * 100.0
        else:
            spread_bp = levels
            spread_pct = levels / 100.0

        latest_bp = float(spread_bp[-1])
        latest_pct = float(spread_pct[-1])
        base_idx = max(0, levels.size - 1 - params.momentum_window)
        change_bp = float(spread_bp[-1] - spread_bp[base_idx])
        momentum_bp_per_day = change_bp / float(max(1, levels.size - 1 - base_idx))
        median_bp = float(np.median(spread_bp))
        pct_rank = percentile_rank(spread_bp)

        # ---- 再融资窗口估计（可解释的确定性规则） ----
        if latest_bp <= median_bp:
            gap_bp = median_bp - latest_bp
            if momentum_bp_per_day > 0:
                estimate_days = int(math.ceil(gap_bp / momentum_bp_per_day))
                window_days = min(params.refinancing_horizon_days, estimate_days)
                window_status = "closing"  # 利差仍低于中位数但正在走阔
            else:
                window_days = params.refinancing_horizon_days
                window_status = "open"
        else:
            window_days = 0
            window_status = "closed"

        if change_bp >= params.cost_jump_bp:
            stress_level = "high"
        elif change_bp >= params.cost_medium_bp:
            stress_level = "medium"
        else:
            stress_level = "low"

        data = {
            "spread_series_id": spread_id,
            "lookback": params.lookback,
            "momentum_window": params.momentum_window,
            "spread_unit": params.spread_unit,
            "observations": int(levels.size),
            "window_start": items[0][0].isoformat(),
            "window_end": items[-1][0].isoformat(),
            # ---- 信用利差与融资成本 ----
            "credit_spread_pct": r(latest_pct),
            "credit_spread_bp": r(latest_bp),
            "credit_spread_min_bp": r(float(np.min(spread_bp))),
            "credit_spread_max_bp": r(float(np.max(spread_bp))),
            "credit_spread_median_bp": r(median_bp),
            "spread_percentile": r(pct_rank),
            "funding_cost_change_bp": r(change_bp),
            "momentum_bp_per_day": r(momentum_bp_per_day),
            # ---- 再融资窗口 ----
            "refinancing_window_days": int(window_days),
            "refinancing_window_status": window_status,
            "refinancing_horizon_days": params.refinancing_horizon_days,
            "stress_level": stress_level,
            "thresholds": {
                "cost_jump_bp": params.cost_jump_bp,
                "cost_medium_bp": params.cost_medium_bp,
                "refinancing_horizon_days": params.refinancing_horizon_days,
            },
            "unit_map": {
                "credit_spread_pct": "pct",
                "credit_spread_bp": "bp",
                "credit_spread_min_bp": "bp",
                "credit_spread_max_bp": "bp",
                "credit_spread_median_bp": "bp",
                "spread_percentile": "quantile_0_1",
                "funding_cost_change_bp": "bp",
                "momentum_bp_per_day": "bp_per_day",
                "refinancing_window_days": "trading_days",
            },
        }
        summary = (
            f"{spread_id} 最新信用利差 {latest_bp:.1f}bp（近 {levels.size} 期分位 "
            f"{(r(pct_rank) or 0):.0%}），{params.momentum_window} 期变化 "
            f"{change_bp:+.1f}bp，融资压力档位={stress_level}；再融资窗口 "
            f"{window_status}（约 {window_days} 个交易日）。"
        )
        return ToolOutput(
            data=data,
            unit="bp",
            value=r(change_bp),
            title=f"融资成本与再融资窗口 @ {as_of.isoformat()}",
            summary=summary,
        )
