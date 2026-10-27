"""派生序列的实时重算。

部分规范序列由其它序列实时计算得到（见 ``docs/data/real_data_integration.md`` §3）。
基础序列通过实时抓取更新后，这里按文档口径重算派生序列的增量部分并写回 PIT：

- ``market.cn_bond.term_spread`` = ``(cgb10 - cgb2) × 100``（bp）
- ``market.global.cn_us_spread`` = ``(cgb10 - us10y) × 100``（bp）
- ``market.fx.cnh_cny_gap`` = ``(usdcnh - usdcny) × 10⁴``（pips）
- ``market.cn_bond.cgb_index`` = ``100 × exp(cumsum(-7.5 × Δcgb10 / 100))``（指数）

派生行的 ``release_time`` 取参与计算的两个基础序列 ``release_time`` 的较大者，
保证不早于任一输入可得（无前视）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from cbr.data.pit_store import PitStore
from cbr.schemas import DataCard

logger = logging.getLogger(__name__)

#: 派生序列 -> 参与计算的基础序列
DERIVED_INPUTS: dict[str, tuple[str, ...]] = {
    "market.cn_bond.term_spread": ("market.cn_bond.cgb_10y", "market.cn_bond.cgb_2y"),
    "market.global.cn_us_spread": ("market.cn_bond.cgb_10y", "market.global.us10y"),
    "market.fx.cnh_cny_gap": ("market.fx.usdcnh", "market.fx.usdcny"),
    "market.cn_bond.cgb_index": ("market.cn_bond.cgb_10y",),
}

DERIVED_UNIT: dict[str, str] = {
    "market.cn_bond.term_spread": "bp",
    "market.global.cn_us_spread": "bp",
    "market.fx.cnh_cny_gap": "pips",
    "market.cn_bond.cgb_index": "点",
}


def _history(store: PitStore, series_id: str, as_of: date) -> pd.DataFrame:
    """读取基础序列的截至 ``as_of`` 的全量历史（含 ``release_time``）。"""
    frame = store.asof(series_id, as_of, lookback=None)
    if frame.empty:
        return frame
    frame = frame.loc[:, ["obs_date", "value", "release_time"]].copy()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["value"]).drop_duplicates(subset=["obs_date"], keep="last")
    return frame


def _diff_derived(left: pd.DataFrame, right: pd.DataFrame, scale: float) -> pd.DataFrame:
    """按观测日对齐后计算 ``(left - right) × scale``。"""
    merged = left.merge(right, on="obs_date", suffixes=("_l", "_r"))
    if merged.empty:
        return merged
    merged["value"] = (merged["value_l"] - merged["value_r"]) * scale
    merged["release_time"] = merged[["release_time_l", "release_time_r"]].max(axis=1)
    return merged.loc[:, ["obs_date", "value", "release_time"]]


def _cgb_index(base: pd.DataFrame) -> pd.DataFrame:
    """按累计价格效应构造国债全价指数（``100 × exp(cumsum(-7.5·Δy/100))``）。"""
    frame = base.sort_values("obs_date").reset_index(drop=True).copy()
    if frame.empty:
        return frame
    delta = frame["value"].diff().fillna(0.0) / 100.0
    frame["value"] = 100.0 * np.exp((-7.5 * delta).cumsum())
    return frame.loc[:, ["obs_date", "value", "release_time"]]


def compute_derived(
    store: PitStore,
    series_id: str,
    as_of: date,
) -> pd.DataFrame:
    """计算单个派生序列的截至 ``as_of`` 的全量观测行（未写回）。"""
    inputs = DERIVED_INPUTS[series_id]
    frames = {sid: _history(store, sid, as_of) for sid in inputs}
    if any(frame.empty for frame in frames.values()):
        return pd.DataFrame(columns=["series_id", "obs_date", "value", "release_time", "source", "unit"])
    if series_id == "market.cn_bond.term_spread":
        out = _diff_derived(frames[inputs[0]], frames[inputs[1]], 100.0)
    elif series_id == "market.global.cn_us_spread":
        out = _diff_derived(frames[inputs[0]], frames[inputs[1]], 100.0)
    elif series_id == "market.fx.cnh_cny_gap":
        out = _diff_derived(frames[inputs[0]], frames[inputs[1]], 1.0e4)
    elif series_id == "market.cn_bond.cgb_index":
        out = _cgb_index(frames[inputs[0]])
    else:  # pragma: no cover - 防御式兜底
        return pd.DataFrame(columns=["series_id", "obs_date", "value", "release_time", "source", "unit"])
    if out.empty:
        return pd.DataFrame(columns=["series_id", "obs_date", "value", "release_time", "source", "unit"])
    out["series_id"] = series_id
    out["source"] = "derived:realtime"
    out["unit"] = DERIVED_UNIT[series_id]
    return out.loc[:, ["series_id", "obs_date", "value", "release_time", "source", "unit"]]


def recompute_derived(
    store: PitStore,
    as_of: date,
    series_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, int]:
    """重算派生序列并写回 PIT；返回 ``{series_id: 新增/更新行数}``。

    只写「库里还没有或值发生变化」的行，避免每次全量重写派生序列。
    """
    targets = list(series_ids) if series_ids else list(DERIVED_INPUTS)
    written: dict[str, int] = {}
    for series_id in targets:
        if series_id not in DERIVED_INPUTS:
            continue
        try:
            frame = compute_derived(store, series_id, as_of)
            if frame.empty:
                continue
            existing = store.asof(series_id, as_of, lookback=None)
            if not existing.empty:
                existing_map = dict(
                    zip(existing["obs_date"].tolist(), existing["value"].astype(float).tolist(), strict=False)
                )
                frame = frame[
                    [
                        existing_map.get(row.obs_date) is None
                        or abs(float(row.value) - float(existing_map[row.obs_date])) > 1e-9
                        for row in frame.itertuples(index=False)
                    ]
                ]
            if frame.empty:
                continue
            written[series_id] = store.upsert_observations(frame)
        except Exception as exc:  # noqa: BLE001 - 派生失败不影响基础抓取结果
            logger.warning("派生序列 %s 重算失败: %s", series_id, exc)
    if written:
        store.touch_coverage(list(written))
    return written


def derived_data_cards() -> list[DataCard]:
    """返回派生序列的数据卡（标注来源为实时重算）。"""
    from cbr.data.catalog import SERIES_SPECS

    cards: list[DataCard] = []
    for series_id in DERIVED_INPUTS:
        spec = SERIES_SPECS.get(series_id)
        if spec is None:
            continue
        cards.append(
            spec.to_data_card(source="derived:realtime", notes="由基础序列实时重算（见 cbr.ingest.derive）")
        )
    return cards
