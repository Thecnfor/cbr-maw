"""systemic_risk：ΔCoVaR（分位数回归近似）、MES、简化 Diebold-Yilmaz 溢出指数。

方法说明（确定性，无 LLM / 无随机数）：
- ΔCoVaR：对 (市场收益, 资产收益) 做 tau 分位数回归 r_asset = a + b·r_market，
  CoVaR = a + b·Q_tau(r_market)，ΔCoVaR = b·(Q_tau(r_market) - Q_0.5(r_market))；
- MES：E[-r_asset | r_market <= Q_tau(r_market)]（条件尾部损失期望，正数=损失）；
- DY 溢出指数：对跨市场收益矩阵拟合 VAR(lag)，计算广义预测误差方差分解（GFEVD），
  总溢出指数 = 100 × 非对角份额均值 / N，以 0~1 比例（``dy_spillover_index``）与
  百分数（``dy_spillover_percent``）两种口径给出，便于与 roles.yaml 阈值比较。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._numeric import (
    align_series,
    fit_var,
    generalized_fevd,
    quantile,
    quantile_regression,
    r,
    simple_returns,
    spillover_index,
    values_of,
)
from .base import BaseTool, ToolError, ToolOutput
from .settings import DEFAULT_DY_SERIES, DEFAULT_SERIES


class SystemicRiskParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_series_id: str | None = None
    asset_series_id: str | None = None
    series_ids: list[str] | None = None
    lookback: int = Field(252, ge=60, le=2000)
    tail_q: float = Field(0.05, gt=0.0, lt=0.5)
    dy_window: int = Field(120, ge=40, le=2000)
    dy_lag: int = Field(1, ge=1, le=5)
    dy_horizon: int = Field(10, ge=1, le=50)
    values_are: Literal["price", "return"] = "price"


def _returns_series(
    items: list[tuple[date, float]], values_are: str
) -> dict[date, float]:
    """(date, value) 序列 -> {date: return}（价格模式丢弃首日）。"""
    if values_are == "price":
        vals = values_of(items)
        if vals.size < 2:
            return {}
        rets = simple_returns(vals)
        return {items[i + 1][0]: float(rets[i]) for i in range(rets.size)}
    return {d: float(v) for d, v in items}


class SystemicRiskTool(BaseTool):
    name = "systemic_risk"
    description = "ΔCoVaR、MES、Diebold-Yilmaz 跨市场溢出指数（确定性纯计算）"
    unit = "ratio"
    params_model = SystemicRiskParams

    def _try_history(self, series_id: str, as_of: date, lookback: int):
        try:
            return self._history(series_id, as_of, lookback)
        except ToolError:
            return None

    def compute(self, as_of: date, params: SystemicRiskParams) -> ToolOutput:
        market_id = self._series_param(params.market_series_id, "market_series_id", DEFAULT_SERIES)
        asset_id = self._series_param(params.asset_series_id, "asset_series_id", DEFAULT_SERIES)
        market_items = self._history(market_id, as_of, params.lookback)
        asset_items = self._history(asset_id, as_of, params.lookback)
        market = _returns_series(market_items, params.values_are)
        asset = _returns_series(asset_items, params.values_are)

        common = sorted(set(market) & set(asset))
        if len(common) < 30:
            raise ToolError(
                f"insufficient co-movement observations: {len(common)} < 30 "
                f"({market_id} vs {asset_id})"
            )
        m_ret = np.asarray([market[d] for d in common], dtype=float)
        a_ret = np.asarray([asset[d] for d in common], dtype=float)
        if not (np.all(np.isfinite(m_ret)) and np.all(np.isfinite(a_ret))):
            raise ToolError("non-finite returns encountered after alignment")

        # ---- ΔCoVaR（分位数回归近似） ----
        q_market = quantile(m_ret, params.tail_q)
        median_market = quantile(m_ret, 0.5)
        intercept, beta, qr_iters = quantile_regression(m_ret, a_ret, params.tail_q)
        covar = intercept + beta * q_market
        covar_median = intercept + beta * median_market
        delta_covar = covar - covar_median

        # ---- MES（条件尾部损失期望） ----
        tail_mask = m_ret <= q_market + 1e-12
        if int(tail_mask.sum()) == 0:
            raise ToolError("no market observations in the tail for MES")
        mes = max(0.0, -float(np.mean(a_ret[tail_mask])))
        market_var_loss = max(0.0, -q_market)

        # ---- DY 溢出指数（可用序列不足时降级并显式标注） ----
        dy_ids = list(params.series_ids or self.defaults.get("series_ids") or DEFAULT_DY_SERIES)
        dy_data: dict[str, dict[date, float]] = {}
        dy_missing: list[str] = []
        for sid in dy_ids:
            items = self._try_history(sid, as_of, params.lookback)
            rets = _returns_series(items, params.values_are) if items else {}
            if len(rets) < 40:
                dy_missing.append(sid)
                continue
            dy_data[sid] = rets
        if len(dy_data) < 2:
            raise ToolError(
                f"DY spillover requires >=2 available series; have {sorted(dy_data)} "
                f"(missing={dy_missing})"
            )
        _, aligned = align_series({sid: sorted(m.items()) for sid, m in dy_data.items()})
        matrix = np.column_stack([aligned[sid] for sid in dy_data])
        if matrix.shape[0] < params.dy_lag + len(dy_data) + 10:
            raise ToolError("insufficient aligned observations for VAR estimation")
        matrix = matrix[-params.dy_window :] if matrix.shape[0] > params.dy_window else matrix
        try:
            _, a_list, sigma = fit_var(matrix, params.dy_lag)
            fevd = generalized_fevd(a_list, sigma, params.dy_horizon)
            dy_index = spillover_index(fevd)
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise ToolError(f"VAR/FEVD estimation failed: {exc}") from exc

        data = {
            "market_series_id": market_id,
            "asset_series_id": asset_id,
            "values_are": params.values_are,
            "lookback": params.lookback,
            "tail_q": params.tail_q,
            "observations": int(m_ret.size),
            "window_start": common[0].isoformat(),
            "window_end": common[-1].isoformat(),
            # ---- 尾部依赖 ----
            "market_var_loss_q": r(market_var_loss),
            "asset_covar": r(covar),
            "asset_covar_loss": r(max(0.0, -covar)),
            "delta_covar": r(delta_covar),
            "delta_covar_abs": r(abs(delta_covar)),
            "quantile_beta": r(beta),
            "quantile_intercept": r(intercept),
            "quantile_regression_iters": qr_iters,
            "mes_q": r(mes),
            "tail_observations": int(tail_mask.sum()),
            # ---- 跨市场溢出 ----
            "dy_spillover_index": r(dy_index),          # 0~1 比例
            "dy_spillover_percent": r(dy_index * 100.0),  # 0~100
            "dy_series_order": list(dy_data),
            "dy_missing_series": dy_missing,
            "dy_window": int(matrix.shape[0]),
            "dy_lag": params.dy_lag,
            "dy_horizon": params.dy_horizon,
            "dy_fevd_matrix": [[r(x) for x in row] for row in fevd],
            "unit_map": {
                "market_var_loss_q": "loss_ratio",
                "asset_covar": "return_ratio",
                "asset_covar_loss": "loss_ratio",
                "delta_covar": "return_ratio",
                "delta_covar_abs": "return_ratio",
                "quantile_beta": "beta",
                "mes_q": "loss_ratio",
                "dy_spillover_index": "ratio_0_1",
                "dy_spillover_percent": "pct",
                "dy_fevd_matrix": "share_0_1",
            },
        }
        summary = (
            f"{market_id}→{asset_id}：市场 {params.tail_q:.0%} 尾部时 ΔCoVaR "
            f"{(r(delta_covar) or 0) * 100:.2f}%、MES {(r(mes) or 0) * 100:.2f}%；"
            f"DY 溢出指数 {(r(dy_index) or 0) * 100:.1f}%（基于 {len(dy_data)} 条序列，"
            f"{int(matrix.shape[0])} 个观测）。"
        )
        return ToolOutput(
            data=data,
            unit="ratio",
            value=r(dy_index),
            title=f"系统性风险连通性 @ {as_of.isoformat()}",
            summary=summary,
        )
