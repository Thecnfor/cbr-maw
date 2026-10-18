"""forecast：只读调用 ``DataProvider.risk_signal``，返回共享风险信号 Evidence。

共享信号是三主体智能体的"单一风险锚"（架构原则 1）：若信号自带
``evidence_id``，本工具复用该 id，保证所有角色引用同一证据、P3 可比。
"""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from ..schemas import EvidenceKind, SourceRef
from ._numeric import r
from .base import BaseTool, ToolError, ToolOutput, normalize_as_of


class ForecastParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: int = Field(5, ge=1, le=250)
    include_drivers: bool = True


class ForecastTool(BaseTool):
    name = "forecast"
    description = "读取共享多模态风险信号（P1 产物，只读）并输出统一 Evidence"
    unit = "probability"
    params_model = ForecastParams

    def compute(self, as_of: date, params: ForecastParams) -> ToolOutput:
        if self.provider is None:
            raise ToolError("data provider is not configured for forecast tool")
        signal = self.provider.risk_signal(as_of)
        if signal is None:
            raise ToolError(f"risk_signal unavailable at as_of={as_of}")
        signal_day = normalize_as_of(signal.as_of)
        if signal_day > as_of:
            raise ToolError(
                f"point-in-time violation: risk signal as_of {signal_day} > requested {as_of}"
            )

        horizons = {int(k): float(v) for k, v in (signal.horizons or {}).items()}
        if not horizons:
            raise ToolError("risk signal has empty horizons")
        if params.horizon not in horizons:
            raise ToolError(
                f"horizon {params.horizon} not provided by risk signal; "
                f"available={sorted(horizons)}"
            )

        probability = float(horizons[params.horizon])
        level = signal.level.value if hasattr(signal.level, "value") else str(signal.level)
        drivers = []
        if params.include_drivers:
            drivers = [
                {
                    "factor": d.factor,
                    "contribution": r(d.contribution),
                    "direction": d.direction,
                    "description": d.description,
                }
                for d in signal.drivers
            ]
        data = {
            "model_version": signal.model_version,
            "signal_as_of": signal_day.isoformat(),
            "horizon": params.horizon,
            "probability": r(probability),
            "horizons": {str(k): r(v) for k, v in sorted(horizons.items())},
            "percentile": r(signal.percentile) if signal.percentile is not None else None,
            "level": level,
            "drivers": drivers,
            "modality_contrib": {
                str(k): r(v) for k, v in (signal.modality_contrib or {}).items()
            },
            "label_version": signal.label_version,
            "signal_evidence_id": signal.evidence_id,
            "unit_map": {
                "probability": "probability",
                "horizons": "probability",
                "percentile": "quantile_0_1",
                "modality_contrib": "share_0_1",
            },
        }
        percentile_txt = (
            f"{signal.percentile:.0%}" if signal.percentile is not None else "NA"
        )
        summary = (
            f"共享风险信号 {signal.model_version}（as_of {signal_day}）："
            f"{params.horizon} 日高压力概率 {probability:.2%}，历史分位 {percentile_txt}，"
            f"等级 {level}。"
        )
        source = SourceRef(
            name=f"risk_signal:{signal.model_version}",
            doc_id=f"risk_signal:{signal_day.isoformat()}",
            release_time=datetime.combine(signal_day, time.min),
            extra={"horizon": params.horizon},
        )
        return ToolOutput(
            data=data,
            unit="probability",
            value=r(probability),
            title=f"共享风险信号（{params.horizon}日）@ {as_of.isoformat()}",
            summary=summary,
            kind=EvidenceKind.SIGNAL,
            evidence_id=signal.evidence_id,
            source=source,
        )
