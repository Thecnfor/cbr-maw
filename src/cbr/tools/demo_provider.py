"""演示/测试用的确定性合成 DataProvider（不访问网络、无随机性）。

用途：在没有 data-model 真实实现时，让工具层 demo 与独立验收可运行；
真实系统请使用 ``cbr.data.build_data_provider(settings)``。
所有序列由固定种子的 numpy RandomState 生成，结果跨进程可复现。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from ..schemas import (
    DataCard,
    MarketSnapshot,
    RiskDriver,
    RiskLevel,
    RiskSignal,
)

START_DAY = date(2018, 1, 1)
END_DAY = date(2025, 12, 31)


def business_days(start: date = START_DAY, end: date = END_DAY) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:  # 周一~周五
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _price_series(days: list[date], *, seed: int, base: float, drift: float, vol: float) -> dict[date, float]:
    rng = np.random.RandomState(seed)
    returns = rng.normal(drift, vol, len(days))
    levels = base * np.exp(np.cumsum(returns))
    return {day: float(level) for day, level in zip(days, levels)}


def _flow_series(days: list[date], *, seed: int, mean: float, scale: float) -> dict[date, float]:
    rng = np.random.RandomState(seed)
    values = rng.normal(mean, scale, len(days))
    return {day: float(value) for day, value in zip(days, values)}


def _premium_series(days: list[date], *, seed: int) -> dict[date, float]:
    """AH 溢价指数（基期 100，点位）——与 data-model 的 crossborder.flows.ah_premium 口径一致。"""
    rng = np.random.RandomState(seed)
    noise = rng.normal(0.0, 1.5, len(days))
    values = [126.0 + 9.0 * np.sin(i / 50.0) + noise[i] for i in range(len(days))]
    return {day: float(value) for day, value in zip(days, values)}


def _spread_series(days: list[date], *, seed: int) -> dict[date, float]:
    """AA 信用利差（bp）——与 data-model 的 rates.credit.aa_spread 口径一致。"""
    rng = np.random.RandomState(seed)
    values = np.clip(120.0 + np.cumsum(rng.normal(0.05, 2.2, len(days))), 40.0, 360.0)
    return {day: float(value) for day, value in zip(days, values)}


class SyntheticProvider:
    """满足 ``cbr.contracts.DataProvider`` 协议的确定性合成数据实现。"""

    def __init__(self) -> None:
        self._days = business_days()
        self._series: dict[str, dict[date, float]] = {
            "market.cn_equity.csi300": _price_series(
                self._days, seed=11, base=3500.0, drift=0.00015, vol=0.012
            ),
            "market.cn_bond.cgb_index": _price_series(
                self._days, seed=12, base=100.0, drift=0.00002, vol=0.0025
            ),
            "market.global.sp500": _price_series(
                self._days, seed=13, base=2700.0, drift=0.00035, vol=0.011
            ),
            "market.global.vix": _price_series(
                self._days, seed=19, base=18.0, drift=0.0, vol=0.02
            ),
            "market.fx.usdcny": _price_series(
                self._days, seed=14, base=6.5, drift=0.00003, vol=0.003
            ),
            "rates.credit.aa_spread": _spread_series(self._days, seed=15),
            "crossborder.flows.northbound_net": _flow_series(
                self._days, seed=16, mean=20.0, scale=55.0
            ),
            "crossborder.flows.southbound_net": _flow_series(
                self._days, seed=17, mean=15.0, scale=45.0
            ),
            "crossborder.flows.ah_premium": _premium_series(self._days, seed=18),
        }
        self._data_cards = [
            DataCard(
                series_id=series_id,
                name=series_id,
                source="synthetic",
                frequency="daily",
                coverage_start=START_DAY,
                coverage_end=END_DAY,
                pit_grade="strict",
                notes="demo 合成序列",
            )
            for series_id in sorted(self._series)
        ]

    # -- DataProvider 协议 -------------------------------------------------
    def risk_signal(self, as_of: date) -> RiskSignal:
        idx = self._index_of(as_of)
        # 用权益近 20 日收益构造确定性的概率信号，仅用于 demo
        history = self.history("market.cn_equity.csi300", as_of, lookback=21)
        values = np.asarray([row["value"] for row in history], dtype=float)
        momentum = float(np.mean(np.diff(values) / values[:-1])) if values.size > 1 else 0.0
        base = 0.35 + 60.0 * momentum
        prob5 = float(np.clip(base + 0.02 * np.sin(idx / 30.0), 0.01, 0.99))
        prob10 = float(np.clip(prob5 + 0.05, 0.01, 0.99))
        prob20 = float(np.clip(prob5 + 0.09, 0.01, 0.99))
        level = (
            RiskLevel.CRITICAL
            if prob20 >= 0.7
            else RiskLevel.HIGH
            if prob20 >= 0.5
            else RiskLevel.MEDIUM
            if prob20 >= 0.3
            else RiskLevel.LOW
        )
        return RiskSignal(
            as_of=as_of,
            model_version="demo-fusion-v1",
            horizons={5: round(prob5, 4), 10: round(prob10, 4), 20: round(prob20, 4)},
            percentile=round(0.5 + 0.4 * np.sin(idx / 60.0), 4),
            level=level,
            drivers=[
                RiskDriver(
                    factor="northbound_outflow_z",
                    contribution=round(0.2 + 0.1 * np.sin(idx / 25.0), 4),
                    direction="up",
                    description="北向资金异常流出",
                ),
                RiskDriver(
                    factor="us_equity_drawdown",
                    contribution=round(0.15 + 0.05 * np.cos(idx / 40.0), 4),
                    direction="up",
                    description="外部权益市场回撤",
                ),
            ],
            modality_contrib={"numeric": 0.72, "text": 0.28},
            label_version="stress_pca_q90",
            evidence_id=f"ev_sig_{as_of:%Y%m%d}_demo",
        )

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        idx = self._index_of(as_of)
        day = self._days[idx]
        return MarketSnapshot(
            as_of=as_of,
            series={
                series_id: values[day]
                for series_id, values in self._series.items()
                if day in values
            },
            missing=[],
            data_cards=self._data_cards,
        )

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict[str, Any]]:
        values = self._series.get(series_id)
        if not values:
            return []
        end = self._index_of(as_of)
        start = max(0, end + 1 - max(1, int(lookback)))
        return [
            {"date": day, "value": values[day]}
            for day in self._days[start : end + 1]
            if day in values
        ]

    def label(self, as_of: date, horizon: int) -> int | None:
        return None

    def data_cards(self) -> list[DataCard]:
        return list(self._data_cards)

    # -- 内部 --------------------------------------------------------------
    def _index_of(self, as_of: date) -> int:
        if as_of <= self._days[0]:
            return 0
        if as_of >= self._days[-1]:
            return len(self._days) - 1
        # 二分查找最后一个 <= as_of 的交易日
        low, high = 0, len(self._days) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if self._days[mid] <= as_of:
                low = mid
            else:
                high = mid - 1
        return low


__all__ = ["SyntheticProvider", "business_days"]
