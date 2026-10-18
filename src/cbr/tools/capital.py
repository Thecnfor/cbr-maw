"""capital_flow：北向/南向异常净流入 z-score、同步撤离指标、集中度、AH 溢价。

单位约定：资金流沿用 ``flow_unit``（默认"亿元"）；z-score 为无量纲；
同步撤离份额/集中度/分位为 0~1 比例；AH 溢价为溢价指数点位（基期 100，单位"点"）。

数据仅来自 ``DataProvider.history``；南向与 AH 溢价序列缺失时降级为 None，
并在 ``missing_series`` 中显式标注（不编造数值）。
"""

from __future__ import annotations

from datetime import date

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ._numeric import (
    concentration_metrics,
    percentile_rank,
    r,
    series_map,
    values_of,
    zscore_latest,
)
from .base import BaseTool, ToolError, ToolOutput
from .settings import DEFAULT_SERIES

AH_CHANGE_WINDOW = 20


class CapitalFlowParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inflow_series_id: str | None = None
    outflow_series_id: str | None = None
    ah_premium_series_id: str | None = None
    lookback: int = Field(60, ge=20, le=500)
    z_window: int = Field(60, ge=10, le=500)
    anomaly_z: float = Field(1.5, gt=0.0)
    top_n: int = Field(5, ge=1, le=20)
    flow_unit: str = "亿元"


class CapitalFlowTool(BaseTool):
    name = "capital_flow"
    description = "跨境资金异常净流入 z-score、同步撤离、集中度与 AH 溢价（确定性纯计算）"
    unit = "z"
    params_model = CapitalFlowParams

    def _try_history(self, series_id: str, as_of: date, lookback: int):
        try:
            return self._history(series_id, as_of, lookback)
        except ToolError:
            return None

    def compute(self, as_of: date, params: CapitalFlowParams) -> ToolOutput:
        inflow_id = self._series_param(
            params.inflow_series_id, "inflow_series_id", DEFAULT_SERIES
        )
        inflow = self._history(inflow_id, as_of, params.lookback)
        inflow_vals = values_of(inflow)
        z_inflow = zscore_latest(inflow_vals, params.z_window)
        if z_inflow is None:
            raise ToolError(
                f"insufficient observations for z-score on {inflow_id}: {inflow_vals.size}"
            )
        if z_inflow <= -params.anomaly_z:
            anomaly_direction = "outflow"
        elif z_inflow >= params.anomaly_z:
            anomaly_direction = "inflow"
        else:
            anomaly_direction = "none"
        top_share, hhi = concentration_metrics(inflow_vals, params.top_n)

        missing: list[str] = []
        data: dict[str, object] = {
            "inflow_series_id": inflow_id,
            "lookback": params.lookback,
            "z_window": params.z_window,
            "anomaly_z": params.anomaly_z,
            "flow_unit": params.flow_unit,
            "observations": int(inflow_vals.size),
            "window_start": inflow[0][0].isoformat(),
            "window_end": inflow[-1][0].isoformat(),
            # ---- 异常净流入 z-score ----
            "net_inflow_latest": r(inflow_vals[-1]),
            "net_inflow_mean": r(np.mean(inflow_vals)),
            "net_inflow_std": r(np.std(inflow_vals, ddof=1) if inflow_vals.size > 1 else 0.0),
            "net_inflow_z": r(z_inflow),
            "anomaly_direction": anomaly_direction,
            "is_anomaly": anomaly_direction != "none",
            # ---- 集中度（资金流在时间上的集中程度） ----
            "concentration_top_share": r(top_share),
            "flow_hhi": r(hhi),
            "concentration_top_n": params.top_n,
        }

        # ---- 南向资金：同步撤离指标 ----
        outflow_id = self._series_param(
            params.outflow_series_id, "outflow_series_id", DEFAULT_SERIES
        )
        outflow = self._try_history(outflow_id, as_of, params.lookback)
        if outflow:
            north_map = series_map(inflow)
            south_map = series_map(outflow)
            joint_dates = sorted(set(north_map) & set(south_map))[-params.lookback :]
            if len(joint_dates) >= 10:
                both_out = [
                    1.0
                    if (north_map[d] < 0.0 and south_map[d] < 0.0)
                    else 0.0
                    for d in joint_dates
                ]
                sync_share = float(np.mean(both_out))
                joint_values = np.asarray(
                    [north_map[d] + south_map[d] for d in joint_dates], dtype=float
                )
                data.update(
                    {
                        "outflow_series_id": outflow_id,
                        "southbound_net_latest": r(south_map[joint_dates[-1]]),
                        "synchronized_outflow_share": r(sync_share),
                        "synchronized_outflow_flag": bool(
                            north_map[joint_dates[-1]] < 0.0
                            and south_map[joint_dates[-1]] < 0.0
                        ),
                        "joint_net_flow_latest": r(joint_values[-1]),
                        "joint_flow_z": r(
                            zscore_latest(joint_values, params.z_window)
                        ),
                        "joint_observations": int(len(joint_dates)),
                    }
                )
            else:
                missing.append(outflow_id)
        else:
            missing.append(outflow_id)

        # ---- AH 溢价（可选序列） ----
        ah_id = self._series_param(
            params.ah_premium_series_id, "ah_premium_series_id", DEFAULT_SERIES
        )
        ah = self._try_history(ah_id, as_of, params.lookback)
        if ah:
            ah_vals = values_of(ah)
            change_idx = max(0, ah_vals.size - 1 - min(AH_CHANGE_WINDOW, ah_vals.size - 1))
            data.update(
                {
                    "ah_premium_series_id": ah_id,
                    "ah_premium_latest": r(ah_vals[-1]),
                    "ah_premium_z": r(zscore_latest(ah_vals, params.z_window)),
                    "ah_premium_percentile": r(percentile_rank(ah_vals)),
                    "ah_premium_change_20d": r(
                        float(ah_vals[-1] - ah_vals[change_idx])
                    ),
                    "ah_premium_observations": int(ah_vals.size),
                }
            )
        else:
            data["ah_premium_series_id"] = ah_id
            data["ah_premium_latest"] = None
            data["ah_premium_z"] = None
            data["ah_premium_percentile"] = None
            data["ah_premium_change_20d"] = None
            missing.append(ah_id)

        data["missing_series"] = missing
        data["unit_map"] = {
            "net_inflow_latest": params.flow_unit,
            "net_inflow_mean": params.flow_unit,
            "net_inflow_std": params.flow_unit,
            "net_inflow_z": "z",
            "concentration_top_share": "ratio_0_1",
            "flow_hhi": "index_0_1",
            "southbound_net_latest": params.flow_unit,
            "synchronized_outflow_share": "ratio_0_1",
            "joint_net_flow_latest": params.flow_unit,
            "joint_flow_z": "z",
            "ah_premium_latest": "点",
            "ah_premium_z": "z",
            "ah_premium_percentile": "quantile_0_1",
            "ah_premium_change_20d": "点_变化",
        }
        summary = (
            f"{inflow_id} 最新净流入 {r(inflow_vals[-1]):.2f}{params.flow_unit}，"
            f"z={z_inflow:.2f}（{'异常' + anomaly_direction if anomaly_direction != 'none' else '正常'}，"
            f"阈值 ±{params.anomaly_z}）；资金流前 {params.top_n} 日集中度 "
            f"{(r(top_share) or 0):.2f}"
        )
        if "synchronized_outflow_share" in data:
            summary += f"；北向/南向同时净流出日占比 {(r(data['synchronized_outflow_share']) or 0):.0%}"
        if data.get("ah_premium_latest") is not None:
            summary += f"；AH 溢价指数 {(r(data['ah_premium_latest']) or 0):.2f} 点"
        summary += "。"

        return ToolOutput(
            data=data,
            unit="z",
            value=r(z_inflow),
            title=f"跨境资金流状态 @ {as_of.isoformat()}",
            summary=summary,
        )
