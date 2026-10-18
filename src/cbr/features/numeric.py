"""数值特征构造（仅使用 t 及以前信息）。

输入为 ``MarketDataset``，输出为按交易日索引的数值特征宽表（列名与
``cbr.features.catalog.NUMERIC_FEATURES`` 一致）。所有滚动统计、z-score、
收益率、差分均为**向后看**（rolling/shift 正向），因此第 t 行只包含 ≤t 的信息；
宏观月频指标按 ``release_time`` 时点对齐到交易日，未发布时为 NaN。

特征覆盖：收益率、已实现波动、波动短长比、回撤、期限利差与资金利率、
信用利差、人民币汇率与汇差、全球因子（VIX/标普/美元/中美利差）、
跨境资金流异常 z、持仓变动、AH 溢价、股债/中美同步性、风格集中度、
宏观变量，以及北向披露缺失标记（regime dummy）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbr.data.catalog import (
    MONTHLY_SERIES_IDS,
    NORTHBOUND_DISCLOSURE_END,
    SERIES_SPECS,
)
from cbr.data.dataset import MarketDataset
from cbr.features.catalog import NUMERIC_FEATURE_NAMES

_ANNUALIZE = 252


# --------------------------------------------------------------------------- #
# 通用滚动工具（均向后看）
# --------------------------------------------------------------------------- #
def _returns(series: pd.Series, periods: int = 1) -> pd.Series:
    """简单收益率（``X_t / X_{t-periods} - 1``）。"""
    return series / series.shift(periods) - 1.0


def _realized_vol(series: pd.Series, window: int = 20) -> pd.Series:
    """已实现波动率（日收益滚动标准差，年化）。"""
    return series.pct_change().rolling(window, min_periods=max(5, window // 4)).std() * np.sqrt(_ANNUALIZE)


def _drawdown(series: pd.Series, window: int = 20) -> pd.Series:
    """滚动窗口内最大回撤幅度（正数）。"""
    rolling_max = series.rolling(window, min_periods=max(5, window // 4)).max()
    return (1.0 - series / rolling_max).clip(lower=0.0)


def _zscore(series: pd.Series, window: int = 60, min_periods: int = 20) -> pd.Series:
    """滚动 z-score（用过去 window 日数据标准化当前值）。"""
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    std = std.replace(0.0, np.nan)
    return (series - mean) / std


def _rolling_change(series: pd.Series, periods: int) -> pd.Series:
    """滞后差分（``X_t - X_{t-periods}``）。"""
    return series - series.shift(periods)


def _rolling_corr(left: pd.Series, right: pd.Series, window: int = 60) -> pd.Series:
    """两个收益序列的滚动相关系数。"""
    return left.rolling(window, min_periods=max(20, window // 3)).corr(right)


# --------------------------------------------------------------------------- #
# 月频 -> 日频（按发布时点对齐）
# --------------------------------------------------------------------------- #
def _as_ns(series: pd.Series) -> pd.Series:
    """把时间列统一为 ``datetime64[ns]``（避免 pandas 3 精度不一致导致 merge 失败）。"""
    return pd.to_datetime(series).astype("datetime64[ns]")


def _released_frame(dataset: MarketDataset, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """把月频序列按 ``release_time`` 对齐到交易日（未发布为 NaN）。"""
    if not calendar.size:
        return pd.DataFrame(index=calendar, columns=list(MONTHLY_SERIES_IDS), dtype=float)
    frame = dataset.obs[dataset.obs["series_id"].isin(MONTHLY_SERIES_IDS)]
    if frame.empty:
        return pd.DataFrame(index=calendar, columns=list(MONTHLY_SERIES_IDS), dtype=float)
    wide = frame.pivot(index="obs_date", columns="series_id", values="value").sort_index()
    release = frame.pivot(index="obs_date", columns="series_id", values="release_time").sort_index()
    rows: dict[str, pd.Series] = {}
    base = pd.DataFrame({"as_of_ts": pd.DatetimeIndex(calendar).astype("datetime64[ns]")})
    for series_id in MONTHLY_SERIES_IDS:
        if series_id not in wide.columns:
            rows[series_id] = pd.Series(np.nan, index=calendar)
            continue
        sub = pd.DataFrame(
            {
                "release_time": _as_ns(pd.Series(release[series_id].to_numpy())).to_numpy(),
                "value": wide[series_id].to_numpy(),
            }
        ).sort_values("release_time")
        merged = pd.merge_asof(
            base.rename(columns={"as_of_ts": "release_time"}),
            sub,
            on="release_time",
            direction="backward",
        )
        rows[series_id] = pd.Series(merged["value"].to_numpy(), index=calendar)
    return pd.DataFrame(rows, index=calendar)


def _macro_features(dataset: MarketDataset, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """构造宏观特征（月频计算 → 按发布时点对齐到日频）。"""
    monthly = dataset.monthly_frame()
    release = dataset.obs[dataset.obs["series_id"].isin(MONTHLY_SERIES_IDS)].pivot(
        index="obs_date", columns="series_id", values="release_time"
    )
    derived: dict[str, tuple[pd.Series, str]] = {}
    pmi_id = "macro.pmi.manufacturing"
    cpi_id = "macro.cpi.yoy"
    social_id = "macro.social_financing.yoy"
    reserves_id = "macro.fx_reserves"
    lpr_id = "macro.lpr.1y"
    if pmi_id in monthly.columns:
        derived["macro_pmi"] = (monthly[pmi_id], pmi_id)
        derived["macro_pmi_chg_3m"] = (monthly[pmi_id] - monthly[pmi_id].shift(3), pmi_id)
    if cpi_id in monthly.columns:
        derived["macro_cpi_yoy"] = (monthly[cpi_id], cpi_id)
    if social_id in monthly.columns:
        derived["macro_social_financing_yoy"] = (monthly[social_id], social_id)
    if reserves_id in monthly.columns:
        derived["macro_fx_reserves_chg_3m"] = (
            monthly[reserves_id] - monthly[reserves_id].shift(3),
            reserves_id,
        )
    if lpr_id in monthly.columns:
        derived["macro_lpr"] = (monthly[lpr_id], lpr_id)
        derived["macro_lpr_chg_3m"] = (monthly[lpr_id] - monthly[lpr_id].shift(3), lpr_id)
    out = pd.DataFrame(index=calendar)
    base = pd.DataFrame({"as_of_ts": pd.DatetimeIndex(calendar).astype("datetime64[ns]")})
    for name, (values, base_id) in derived.items():
        if base_id not in release.columns:
            out[name] = np.nan
            continue
        sub = pd.DataFrame(
            {
                "release_time": _as_ns(pd.Series(release[base_id].to_numpy())).to_numpy(),
                "value": values.to_numpy(),
            }
        ).dropna(subset=["release_time"]).sort_values("release_time")
        merged = pd.merge_asof(
            base.rename(columns={"as_of_ts": "release_time"}),
            sub,
            on="release_time",
            direction="backward",
        )
        out[name] = merged["value"].to_numpy()
    return out


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def build_numeric_features(dataset: MarketDataset) -> pd.DataFrame:
    """构造全部数值特征（行=交易日，列=``NUMERIC_FEATURE_NAMES``）。

    Args:
        dataset: 时点数据集。

    Returns:
        数值特征 DataFrame，索引为交易日升序；未覆盖的序列对应列为 NaN。
    """
    daily = dataset.daily_frame()
    calendar = pd.DatetimeIndex(daily.index)
    if not calendar.size:
        return pd.DataFrame(index=calendar, columns=list(NUMERIC_FEATURE_NAMES), dtype=float)
    out = pd.DataFrame(index=calendar)

    def col(series_id: str) -> pd.Series | None:
        if series_id not in daily.columns:
            return None
        return daily[series_id].astype(float)

    # -- 权益 ------------------------------------------------------------- #
    equity = col("market.cn_equity.csi300")
    if equity is not None:
        out["ret_csi300_1d"] = _returns(equity, 1)
        out["ret_csi300_5d"] = _returns(equity, 5)
        out["ret_csi300_20d"] = _returns(equity, 20)
        vol20 = _realized_vol(equity, 20)
        out["vol_csi300_20d"] = vol20
        out["vol_ratio_5_20"] = _realized_vol(equity, 5) / vol20.replace(0.0, np.nan)
        out["maxdd_csi300_20d"] = _drawdown(equity, 20)
    csi500 = col("market.cn_equity.csi500")
    if csi500 is not None:
        out["ret_csi500_5d"] = _returns(csi500, 5)
    turnover = col("market.cn_equity.turnover")
    if turnover is not None:
        out["turnover_z_60"] = _zscore(np.log(turnover.clip(lower=1e-6)), 60)

    # -- 债券/资金/信用 --------------------------------------------------- #
    term_spread = col("market.cn_bond.term_spread")
    if term_spread is not None:
        out["term_spread"] = term_spread
        out["term_spread_chg_5d"] = _rolling_change(term_spread, 5)
    cgb10 = col("market.cn_bond.cgb_10y")
    if cgb10 is not None:
        out["cgb10_chg_20d"] = _rolling_change(cgb10, 20) * 100.0  # % -> bp
    repo7 = col("market.cn_bond.repo_7d")
    if repo7 is not None:
        out["repo7_chg_5d"] = _rolling_change(repo7, 5) * 100.0  # % -> bp
    credit = col("rates.credit.aa_spread")
    if credit is not None:
        out["credit_spread"] = credit
        out["credit_spread_chg_20d"] = _rolling_change(credit, 20)
        out["credit_spread_z_60"] = _zscore(credit, 60)

    # -- 汇率 ------------------------------------------------------------- #
    usdcny = col("market.fx.usdcny")
    if usdcny is not None:
        out["ret_usdcny_1d"] = _returns(usdcny, 1)
        out["ret_usdcny_5d"] = _returns(usdcny, 5)
        out["ret_usdcny_20d"] = _returns(usdcny, 20)
        out["vol_usdcny_20d"] = _realized_vol(usdcny, 20)
    fx_gap = col("market.fx.cnh_cny_gap")
    if fx_gap is not None:
        out["cnh_cny_gap"] = fx_gap
        out["cnh_cny_gap_chg_5d"] = _rolling_change(fx_gap, 5)

    # -- 全球因子 --------------------------------------------------------- #
    dxy = col("market.global.dxy")
    if dxy is not None:
        out["ret_dxy_5d"] = _returns(dxy, 5)
    vix = col("market.global.vix")
    if vix is not None:
        out["vix_level"] = vix
        out["vix_chg_5d"] = _rolling_change(vix, 5)
    sp500 = col("market.global.sp500")
    if sp500 is not None:
        out["ret_sp500_5d"] = _returns(sp500, 5)
        out["ret_sp500_20d"] = _returns(sp500, 20)
    cn_us = col("market.global.cn_us_spread")
    if cn_us is not None:
        out["cn_us_spread"] = cn_us
        out["cn_us_spread_chg_20d"] = _rolling_change(cn_us, 20)

    # -- 跨境资金 --------------------------------------------------------- #
    northbound = col("crossborder.flows.northbound_net")
    if northbound is not None:
        out["flow_northbound_net"] = northbound
        out["flow_northbound_z_60"] = _zscore(northbound, 60)
        out["flow_northbound_20d_sum"] = northbound.rolling(20, min_periods=10).sum()
    southbound = col("crossborder.flows.southbound_net")
    if southbound is not None:
        out["flow_southbound_z_60"] = _zscore(southbound, 60)
        out["flow_southbound_20d_sum"] = southbound.rolling(20, min_periods=10).sum()
    north_hold = col("crossborder.holdings.northbound_hold")
    if north_hold is not None:
        out["northbound_hold_chg_20d"] = _returns(north_hold, 20)
    out["northbound_missing"] = (calendar > pd.Timestamp(NORTHBOUND_DISCLOSURE_END)).astype(float)
    ah_premium = col("crossborder.flows.ah_premium")
    if ah_premium is not None:
        out["ah_premium"] = ah_premium
        out["ah_premium_z_60"] = _zscore(ah_premium, 60)

    # -- 同步性 / 集中度 / 全球因子 --------------------------------------- #
    bond_index = col("market.cn_bond.cgb_index")
    if equity is not None and bond_index is not None:
        out["corr_eq_bond_60"] = _rolling_corr(equity.pct_change(), bond_index.pct_change(), 60)
    if equity is not None and sp500 is not None:
        out["corr_cn_us_60"] = _rolling_corr(equity.pct_change(), sp500.pct_change(), 60)
    if equity is not None and csi500 is not None:
        ratio = (csi500 / equity.replace(0.0, np.nan)).pct_change()
        out["concentration_20d"] = ratio.rolling(20, min_periods=10).std()
    global_parts: list[pd.Series] = []
    if vix is not None:
        global_parts.append(_zscore(vix, 60))
    if sp500 is not None:
        global_parts.append(-_zscore(_returns(sp500, 5), 60))
    if dxy is not None:
        global_parts.append(_zscore(_returns(dxy, 5), 60))
    if global_parts:
        out["global_factor"] = pd.concat(global_parts, axis=1).mean(axis=1, skipna=True)

    # -- 宏观 ------------------------------------------------------------- #
    macro = _macro_features(dataset, calendar)
    for name in macro.columns:
        out[name] = macro[name]

    # -- 对齐到目录列顺序（缺失列补 NaN） --------------------------------- #
    for name in NUMERIC_FEATURE_NAMES:
        if name not in out.columns:
            out[name] = np.nan
    return out.loc[:, list(NUMERIC_FEATURE_NAMES)].sort_index()
