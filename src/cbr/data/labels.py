"""风险标签构造：中国金融压力指数代理（CFSI-CN）+ 未来 h 日高压力状态标签。

设计目标（对应论文 4.1 与 P1）：

- **中国金融压力指数代理 CFSI-CN（0–100）**：由股票、债券、信用、汇率、
  跨境资金、全球风险六个维度构造；每个子指标先做“方向统一（数值越大越紧张）”，
  再用**滚动经验分位**转为 0–1 的无量纲压力分数，维度内等权、维度间等权
  （``stress_pca_q90`` 版本用训练期拟合的 PCA 第一主成分，载荷冻结）；
- **高位状态标签**：``high_stress = CFSI >= τ``，``τ`` 取**训练期**分位阈值并冻结
  （默认 q90）；稳健性版本支持滚动分位阈值；
- **预测标签** ``y_{t,h}``：默认 B1（未来 h 个交易日内任一日 high_stress=1，
  即 ``max_{s=1..h} high_stress_{t+s}``），也支持任务书字面定义 B0
  （``high_stress_{t+h}``）与 B2（持续性：未来 h 日内至少 2 日高压力）；
- **无未来信息泄漏**：所有子指标、滚动分位、winsorize 边界、PCA 载荷、阈值
  都只使用 t 及以前的数据；标签本身使用未来信息（标签不是特征），并且
  只在 ``label/as_of`` 评估接口中暴露。

``label_version`` 可配置（例如 ``stress_pca_q90``、``cfsi_cn_q90``、
``stress_pca_q85_rolling``、``stress_pca_q90_point``、``stress_pca_q90_b2``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd

from cbr.data.dataset import MarketDataset

#: 默认预测期限（交易日）
DEFAULT_HORIZONS: tuple[int, ...] = (5, 10, 20)
#: 默认标签版本（与 configs/app.yaml 的 data.label_version 保持一致）
DEFAULT_LABEL_VERSION = "stress_pca_q90"

#: 维度 -> 中文说明（用于报告/归因展示）
DIMENSION_NAMES: dict[str, str] = {
    "equity": "股票市场压力",
    "bond": "债券与资金面压力",
    "credit": "信用风险溢价",
    "fx": "人民币汇率压力",
    "crossborder": "跨境资金压力",
    "global": "全球风险传导",
    "text": "政策/新闻文本压力",
}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LabelConfig:
    """标签构造配置（可由 ``label_version`` 解析得到，也可显式覆盖）。

    Attributes:
        label_version: 标签版本号，写入 ``RiskSignal.label_version`` 与模型注册表。
        horizons: 预测期限（交易日），默认 {5,10,20}。
        quantile: 高位状态阈值分位（默认 0.90，即 top 10%）。
        rolling_window: 滚动经验分位窗口（交易日）。
        min_periods: 滚动分位最少样本数。
        threshold_mode: ``frozen``（训练期阈值冻结，主方案）或 ``rolling``（滚动分位）。
        threshold_window: 滚动阈值窗口（仅 ``rolling`` 模式）。
        label_mode: ``max``（未来 h 日内任一高压力日）或 ``point``（第 t+h 日）。
        persistence_days: 持续性标签要求未来 h 日内至少高压力日数（1=普通 B1）。
        pca: True 用训练期 PCA 第一主成分；False 用分位等权复合。
        train_fraction: 训练期占比（未显式给 train_end 时使用）。
        train_end: 训练期截止日（阈值/PCA 载荷只在此前数据上估计并冻结）。
    """

    label_version: str = DEFAULT_LABEL_VERSION
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    quantile: float = 0.90
    rolling_window: int = 1250
    min_periods: int = 252
    threshold_mode: str = "frozen"
    threshold_window: int = 1250
    label_mode: str = "max"
    persistence_days: int = 1
    pca: bool = True
    train_fraction: float = 0.55
    train_end: str | None = None


def parse_label_version(version: str) -> LabelConfig:
    """把标签版本字符串解析为 ``LabelConfig``。

    支持的约定：

    - 含 ``pca`` -> PCA 复合；含 ``equal`` / ``cfsi`` -> 分位等权复合；
    - ``qNN`` / ``qNNN`` -> 分位阈值（``q90``=0.90，``q85``=0.85）；
    - ``rolling`` -> 滚动分位阈值（默认训练期冻结）；
    - ``point`` -> ``y_t = high_stress_{t+h}``（任务书字面定义）；
    - ``b2`` -> 持续性标签（未来 h 日内至少 2 个高压力日）。

    Args:
        version: 标签版本字符串。

    Returns:
        ``LabelConfig``。
    """
    raw = version.strip()
    tokens = raw.lower().replace("-", "_").split("_")
    quantile = 0.90
    for token in tokens:
        if token.startswith("q") and token[1:].isdigit():
            quantile = int(token[1:]) / 100.0
    pca = "pca" in tokens
    if any(tok in tokens for tok in ("equal", "cfsi")):
        pca = False
    threshold_mode = "rolling" if "rolling" in tokens else "frozen"
    label_mode = "point" if "point" in tokens else "max"
    persistence_days = 2 if "b2" in tokens else 1
    return LabelConfig(
        label_version=raw,
        quantile=quantile,
        threshold_mode=threshold_mode,
        label_mode=label_mode,
        persistence_days=persistence_days,
        pca=pca,
    )


# --------------------------------------------------------------------------- #
# 基础滚动工具（全部仅使用 t 及以前信息）
# --------------------------------------------------------------------------- #
def _rolling_percentile(
    series: pd.Series,
    window: int = 1250,
    min_periods: int = 252,
) -> pd.Series:
    """滚动经验分位：``p_t = P(X_t >= X_s, s in [t-window+1, t])``。

    仅使用 t 及以前的数据，因此可安全用于特征/标签阈值构造。

    Args:
        series: 原始指标序列（可能含 NaN）。
        window: 滚动窗口长度（交易日）。
        min_periods: 有效样本数下限。

    Returns:
        0–1 的分位序列；样本不足或当前值缺失时为 NaN。
    """
    arr = series.to_numpy(dtype=float)
    out = np.full(arr.size, np.nan, dtype=float)
    for t in range(arr.size):
        last = arr[t]
        if not np.isfinite(last):
            continue
        start = max(0, t - window + 1)
        window_values = arr[start : t + 1]
        valid = window_values[np.isfinite(window_values)]
        if valid.size < min_periods:
            continue
        out[t] = float(np.count_nonzero(valid <= last)) / float(valid.size)
    return pd.Series(out, index=series.index, name=series.name)


def _safe_diff(series: pd.Series, periods: int) -> pd.Series:
    """滞后差分（``X_t - X_{t-periods}``）。"""
    return series - series.shift(periods)


def _pct_change(series: pd.Series, periods: int) -> pd.Series:
    """区间收益率（``X_t / X_{t-periods} - 1``）。"""
    return series / series.shift(periods) - 1.0


def _rolling_vol(series: pd.Series, window: int = 20, annualize: int = 252) -> pd.Series:
    """已实现波动率（日收益率滚动标准差，年化）。"""
    returns = series.pct_change()
    return returns.rolling(window, min_periods=max(5, window // 4)).std() * np.sqrt(annualize)


def _rolling_drawdown(series: pd.Series, window: int = 20) -> pd.Series:
    """滚动窗口内最大回撤幅度（正数表示回撤深度）。"""
    rolling_max = series.rolling(window, min_periods=max(5, window // 4)).max()
    return (1.0 - series / rolling_max).clip(lower=0.0)


def _dimension_percentile(
    sub_percentiles: dict[str, pd.Series],
    min_ratio: float = 0.5,
) -> pd.Series:
    """维度内子指标分位等权平均；有效子指标不足时返回 NaN。"""
    frame = pd.DataFrame(sub_percentiles)
    count = frame.notna().sum(axis=1)
    required = max(1, int(np.ceil(len(frame.columns) * min_ratio)))
    mean = frame.mean(axis=1, skipna=True)
    return mean.where(count >= required)


# --------------------------------------------------------------------------- #
# 六个维度的子指标（方向统一：数值越大表示压力越高）
# --------------------------------------------------------------------------- #
def _build_dimension_indicators(df: pd.DataFrame) -> dict[str, pd.Series]:
    """由日频宽表计算六个维度的原始压力指标（方向：越大越紧张）。

    所有指标只使用 t 及以前的行情（滚动窗口 / 滞后差分 / 收益率），
    不引入未来信息。缺失序列（如北向资金停披露后）自动退化为 NaN，
    由维度内其他子指标补齐。

    Args:
        df: 日频宽表（``dataset.daily_frame()``，索引为交易日）。

    Returns:
        ``{indicator_name: Series}``，键名即后续分位化的子指标名。
    """
    indicators: dict[str, pd.Series] = {}

    def add(name: str, series: pd.Series, sign: float) -> None:
        indicators[name] = sign * series

    equity = df.get("market.cn_equity.csi300")
    if equity is not None:
        add("equity_ret_5d", _pct_change(equity, 5), -1.0)
        add("equity_ret_20d", _pct_change(equity, 20), -1.0)
        add("equity_vol_20d", _rolling_vol(equity, 20), 1.0)
        add("equity_drawdown_20d", _rolling_drawdown(equity, 20), 1.0)

    term_spread = df.get("market.cn_bond.term_spread")
    if term_spread is not None:
        # 期限利差水平低（倒挂/平坦）与快速收窄均视为压力
        add("bond_term_spread_level", term_spread, -1.0)
        add("bond_term_spread_chg_20d", _safe_diff(term_spread, 20), -1.0)
    repo7 = df.get("market.cn_bond.repo_7d")
    if repo7 is not None:
        add("bond_repo_chg_20d", _safe_diff(repo7, 20), 1.0)

    credit = df.get("rates.credit.aa_spread")
    if credit is not None:
        add("credit_spread_level", credit, 1.0)
        add("credit_spread_chg_20d", _safe_diff(credit, 20), 1.0)

    usdcny = df.get("market.fx.usdcny")
    if usdcny is not None:
        add("fx_ret_20d", _pct_change(usdcny, 20), 1.0)
        add("fx_vol_20d", _rolling_vol(usdcny, 20), 1.0)
    fx_gap = df.get("market.fx.cnh_cny_gap")
    if fx_gap is not None:
        add("fx_cnh_cny_gap", fx_gap, 1.0)
        add("fx_cnh_cny_gap_chg_20d", _safe_diff(fx_gap, 20), 1.0)

    northbound = df.get("crossborder.flows.northbound_net")
    if northbound is not None:
        add("crossborder_north_20d", northbound.rolling(20, min_periods=10).sum(), -1.0)
    southbound = df.get("crossborder.flows.southbound_net")
    if southbound is not None:
        add("crossborder_south_20d", southbound.rolling(20, min_periods=10).sum(), -1.0)
    ah_premium = df.get("crossborder.flows.ah_premium")
    if ah_premium is not None:
        add("crossborder_ah_chg_20d", _safe_diff(ah_premium, 20), 1.0)
    north_hold = df.get("crossborder.holdings.northbound_hold")
    if north_hold is not None:
        add("crossborder_hold_ret_20d", _pct_change(north_hold, 20), -1.0)

    vix = df.get("market.global.vix")
    if vix is not None:
        add("global_vix_level", vix, 1.0)
        add("global_vix_chg_5d", _safe_diff(vix, 5), 1.0)
    sp500 = df.get("market.global.sp500")
    if sp500 is not None:
        add("global_sp_ret_20d", _pct_change(sp500, 20), -1.0)
    dxy = df.get("market.global.dxy")
    if dxy is not None:
        add("global_dxy_ret_20d", _pct_change(dxy, 20), 1.0)
    cn_us = df.get("market.global.cn_us_spread")
    if cn_us is not None:
        add("global_cn_us_spread_chg_20d", _safe_diff(cn_us, 20), -1.0)

    return {name: series.astype(float) for name, series in indicators.items()}


#: 子指标 -> 所属维度
INDICATOR_DIMENSION: dict[str, str] = {
    "equity_ret_5d": "equity",
    "equity_ret_20d": "equity",
    "equity_vol_20d": "equity",
    "equity_drawdown_20d": "equity",
    "bond_term_spread_level": "bond",
    "bond_term_spread_chg_20d": "bond",
    "bond_repo_chg_20d": "bond",
    "credit_spread_level": "credit",
    "credit_spread_chg_20d": "credit",
    "fx_ret_20d": "fx",
    "fx_vol_20d": "fx",
    "fx_cnh_cny_gap": "fx",
    "fx_cnh_cny_gap_chg_20d": "fx",
    "crossborder_north_20d": "crossborder",
    "crossborder_south_20d": "crossborder",
    "crossborder_ah_chg_20d": "crossborder",
    "crossborder_hold_ret_20d": "crossborder",
    "global_vix_level": "global",
    "global_vix_chg_5d": "global",
    "global_sp_ret_20d": "global",
    "global_dxy_ret_20d": "global",
    "global_cn_us_spread_chg_20d": "global",
}


# --------------------------------------------------------------------------- #
# 结果容器
# --------------------------------------------------------------------------- #
@dataclass
class LabelResult:
    """标签构造结果。

    Attributes:
        frame: 索引为交易日的 DataFrame，包含各维度分位、CFSI、阈值、
            高压力状态与各期限标签列（``y_5``/``y_10``/``y_20``）。
        config: 实际使用的 ``LabelConfig``。
        train_end: 训练期截止日（阈值/PCA 载荷估计窗口的右端点，已冻结）。
        threshold: 高位状态阈值 τ（CFSI 尺度 0–100）。
        loadings: PCA 载荷 ``{dimension: loading}``（等权版本为各维度等权权重）。
    """

    frame: pd.DataFrame
    config: LabelConfig
    train_end: pd.Timestamp
    threshold: float
    loadings: dict[str, float] = field(default_factory=dict)

    # -- 便捷访问 ---------------------------------------------------------
    @property
    def calendar(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.frame.index)

    def _row(self, as_of: date | str | pd.Timestamp) -> pd.Series | None:
        ts = pd.Timestamp(as_of)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts = ts.normalize()
        if ts not in self.frame.index:
            return None
        return self.frame.loc[ts]

    def label(self, as_of: date | str | pd.Timestamp, horizon: int) -> int | None:
        """返回 ``as_of`` 的未来 ``horizon`` 交易日高压力标签（缺失返回 None）。

        仅供评估/训练使用（标签天然使用未来信息）；演示与推理链路不得把
        该值当作特征。
        """
        column = f"y_{int(horizon)}"
        row = self._row(as_of)
        if row is None or column not in row.index:
            return None
        value = row[column]
        if pd.isna(value):
            return None
        return int(value)

    def stress_index(self, as_of: date | str | pd.Timestamp) -> float | None:
        """返回 ``as_of`` 的 CFSI 压力指数（0–100，缺失 None）。"""
        row = self._row(as_of)
        if row is None or "cfsi" not in row.index or pd.isna(row["cfsi"]):
            return None
        return float(row["cfsi"])

    def percentile(self, as_of: date | str | pd.Timestamp) -> float | None:
        """返回 ``as_of`` 的压力分位（0–1，训练期/滚动分位口径）。"""
        row = self._row(as_of)
        if row is None or "percentile" not in row.index or pd.isna(row["percentile"]):
            return None
        return float(row["percentile"])

    def high_stress(self, as_of: date | str | pd.Timestamp) -> int | None:
        """返回 ``as_of`` 是否处于高压力状态（0/1，缺失 None）。"""
        row = self._row(as_of)
        if row is None or "high_stress" not in row.index or pd.isna(row["high_stress"]):
            return None
        return int(row["high_stress"])


# --------------------------------------------------------------------------- #
# 主构造函数
# --------------------------------------------------------------------------- #
def _resolve_train_end(calendar: pd.DatetimeIndex, config: LabelConfig) -> pd.Timestamp:
    """确定训练期截止日（阈值/PCA 载荷估计窗口）。

    规则：显式 ``train_end`` 优先；若样本覆盖到 2022 年以后，采用研究方案的
    固定训练期截止日 **2021-12-31**；短样本（单元测试/子区间）按 ``train_fraction``
    比例切分。
    """
    if config.train_end:
        return pd.Timestamp(config.train_end).normalize()
    fixed = pd.Timestamp("2021-12-31")
    if len(calendar) and pd.Timestamp(calendar[-1]) > pd.Timestamp("2022-06-30") and pd.Timestamp(
        calendar[0]
    ) <= fixed:
        return fixed
    fraction = min(max(config.train_fraction, 0.2), 0.9)
    pos = int(round(len(calendar) * fraction)) - 1
    pos = min(max(pos, 0), len(calendar) - 1)
    return pd.Timestamp(calendar[pos]).normalize()


def _winsorize(series: pd.Series, lower: float, upper: float) -> pd.Series:
    """winsorize 到给定分位边界（边界由训练期确定并冻结）。"""
    return series.clip(lower=lower, upper=upper)


def build_stress_labels(
    dataset: MarketDataset,
    label_version: str | None = None,
    horizons: Iterable[int] | None = None,
    train_end: str | None = None,
    config: LabelConfig | None = None,
) -> LabelResult:
    """构造 CFSI-CN 压力指数、高位状态与未来 h 日预测标签。

    Args:
        dataset: 时点数据集（使用其日频宽表）。
        label_version: 标签版本号；默认 ``stress_pca_q90``。
        horizons: 预测期限（交易日）；默认 {5,10,20}。
        train_end: 训练期截止日（覆盖版本配置）。
        config: 显式 ``LabelConfig``（优先于 ``label_version``）。

    Returns:
        ``LabelResult``。

    Raises:
        ValueError: 数据不含可用日频序列或样本过短。
    """
    df = dataset.daily_frame()
    if df.empty:
        raise ValueError("数据集没有日频序列，无法构造风险标签")
    calendar = pd.DatetimeIndex(df.index)
    if config is None:
        config = parse_label_version(label_version or DEFAULT_LABEL_VERSION)
    if horizons is not None:
        config = LabelConfig(**{**config.__dict__, "horizons": tuple(int(h) for h in horizons)})
    if train_end is not None:
        config = LabelConfig(**{**config.__dict__, "train_end": train_end})
    train_end_ts = _resolve_train_end(calendar, config)

    # 1) 子指标原始压力分数（方向统一，仅用 t 及以前）
    raw_indicators = _build_dimension_indicators(df)
    if not raw_indicators:
        raise ValueError("无法从数据中计算任何压力子指标（检查序列 ID）")

    # 2) 训练期 winsorize 边界（冻结，无未来信息）
    train_mask = calendar <= train_end_ts
    indicator_pcts: dict[str, pd.Series] = {}
    for name, series in raw_indicators.items():
        train_values = series[train_mask].dropna()
        if train_values.size >= 30:
            lower = float(train_values.quantile(0.01))
            upper = float(train_values.quantile(0.99))
            clipped = _winsorize(series, lower, upper)
        else:
            clipped = series
        indicator_pcts[name] = _rolling_percentile(
            clipped, window=config.rolling_window, min_periods=config.min_periods
        )

    # 3) 维度分位 = 维度内子指标分位等权平均
    dimension_pcts: dict[str, pd.Series] = {}
    for dimension in DIMENSION_NAMES:
        members = {name: pct for name, pct in indicator_pcts.items() if INDICATOR_DIMENSION.get(name) == dimension}
        if members:
            dimension_pcts[dimension] = _dimension_percentile(members)
    if not dimension_pcts:
        raise ValueError("维度分位计算结果为空")

    dim_frame = pd.DataFrame(dimension_pcts, index=calendar)
    available_dims = list(dim_frame.columns)

    # 4) 合成 CFSI（pca 或分位等权）
    loadings: dict[str, float] = {}
    if config.pca and len(available_dims) >= 2:
        cfsi, percentile, loadings = _compose_cfsi_pca(dim_frame, train_mask, config)
    else:
        cfsi, percentile = _compose_cfsi_equal(dim_frame, config)
        loadings = {dim: 1.0 / len(available_dims) for dim in available_dims}

    # 5) 高位状态阈值（训练期冻结 或 滚动分位）
    if config.threshold_mode == "rolling":
        threshold = cfsi.rolling(
            config.threshold_window, min_periods=config.min_periods
        ).quantile(config.quantile)
        threshold_label = "rolling_quantile"
    else:
        train_cfsi = cfsi[train_mask].dropna()
        if train_cfsi.empty:
            raise ValueError("训练期没有可用 CFSI 值，无法估计阈值")
        tau = float(train_cfsi.quantile(config.quantile))
        threshold = pd.Series(tau, index=calendar)
        threshold_label = f"frozen_train_q{int(round(config.quantile * 100))}"
    high_stress = (cfsi >= threshold).astype(float)
    high_stress = high_stress.where(cfsi.notna() & threshold.notna())

    # 6) 未来 h 日标签（标签可以使用未来信息）
    label_columns: dict[str, pd.Series] = {}
    for horizon in config.horizons:
        label_columns[f"y_{int(horizon)}"] = _make_label(
            high_stress, int(horizon), config.label_mode, config.persistence_days
        )

    frame = pd.DataFrame(
        {
            "cfsi": cfsi,
            "percentile": percentile,
            "threshold": threshold,
            "high_stress": high_stress,
            **label_columns,
            **{f"dim_{dim}": dim_frame[dim] for dim in dim_frame.columns},
            **{f"pct_{name}": series for name, series in indicator_pcts.items()},
        },
        index=calendar,
    )
    frame.attrs["threshold_mode"] = threshold_label
    return LabelResult(
        frame=frame,
        config=config,
        train_end=train_end_ts,
        threshold=float(threshold.dropna().iloc[0]) if threshold.notna().any() else float("nan"),
        loadings=loadings,
    )


def _compose_cfsi_equal(dim_frame: pd.DataFrame, config: LabelConfig) -> tuple[pd.Series, pd.Series]:
    """分位等权复合：``CFSI_t = 100 * mean_j pct_{j,t}``（至少 2 个维度可用）。"""
    count = dim_frame.notna().sum(axis=1)
    cfsi = 100.0 * dim_frame.mean(axis=1, skipna=True)
    cfsi = cfsi.where(count >= 2)
    percentile = (cfsi / 100.0).clip(0.0, 1.0)
    return cfsi, percentile


def _compose_cfsi_pca(
    dim_frame: pd.DataFrame,
    train_mask: np.ndarray | pd.Series,
    config: LabelConfig,
) -> tuple[pd.Series, pd.Series, dict[str, float]]:
    """训练期 PCA 第一主成分（载荷与标准化参数冻结）合成 CFSI。

    步骤：
    1. 用训练期各维度分位的均值/标准差标准化（NaN 以训练均值填充）；
    2. 对训练期标准化矩阵做 SVD，取第一右奇异向量作为载荷并冻结；
    3. 将载荷应用到全样本，得到主成分得分；
    4. 用训练期得分的经验 CDF 把得分映射到 0–1（分位），再 ×100。
    """
    dims = list(dim_frame.columns)
    train_values = dim_frame.loc[train_mask]
    train_valid = train_values.dropna()
    if len(train_valid) < 30:
        return (*_compose_cfsi_equal(dim_frame, config), {dim: 1.0 / len(dims) for dim in dims})
    means = train_valid.mean()
    stds = train_valid.std().replace(0.0, 1.0).fillna(1.0)
    z = (dim_frame - means) / stds
    z = z.fillna(0.0)
    train_z = z.loc[train_mask].to_numpy(dtype=float)
    # SVD 第一主成分（等价于协方差矩阵最大特征向量）
    centered = train_z - train_z.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    loading = vt[0]
    # 方向对齐：让权益维度载荷为正（压力上升 -> 指数上升）
    equity_pos = dims.index("equity") if "equity" in dims else 0
    if loading[equity_pos] < 0:
        loading = -loading
    loadings = {dim: float(loading[i]) for i, dim in enumerate(dims)}
    score = pd.Series(z.to_numpy(dtype=float) @ loading, index=dim_frame.index)
    train_scores = np.sort(score.loc[train_mask].to_numpy(dtype=float))
    percentile = pd.Series(
        np.searchsorted(train_scores, score.to_numpy(dtype=float), side="right") / float(len(train_scores)),
        index=dim_frame.index,
    ).clip(0.0, 1.0)
    valid_mask = dim_frame.notna().sum(axis=1) >= 2
    percentile = percentile.where(valid_mask)
    cfsi = percentile * 100.0
    return cfsi, percentile, loadings


def _make_label(
    high_stress: pd.Series,
    horizon: int,
    label_mode: str,
    persistence_days: int,
) -> pd.Series:
    """构造未来 h 日标签。

    - ``max``：未来 h 日内任一日 high_stress=1（B1）；``persistence_days>1`` 为 B2；
    - ``point``：``high_stress_{t+h}``（任务书字面定义 B0）。
    """
    hs = high_stress.astype(float)
    horizon = max(1, int(horizon))
    if label_mode == "point":
        future = hs.shift(-horizon)
        label = (future >= 1.0).astype(float)
        label[future.isna()] = np.nan
        return label
    if persistence_days > 1:
        future_sum = hs.rolling(horizon, min_periods=1).sum().shift(-horizon)
        label = (future_sum >= float(persistence_days)).astype(float)
        label[future_sum.isna()] = np.nan
        return label
    future_max = hs.rolling(horizon, min_periods=1).max().shift(-horizon)
    label = (future_max >= 1.0).astype(float)
    label[future_max.isna()] = np.nan
    return label


# --------------------------------------------------------------------------- #
# 训练/验证/测试切分（供模型评估与论文实验使用）
# --------------------------------------------------------------------------- #
def time_split(
    calendar: pd.DatetimeIndex,
    train_end: str = "2021-12-31",
    valid_end: str = "2023-12-31",
) -> dict[str, pd.DatetimeIndex]:
    """按固定日期切分训练/验证/测试期（研究方案：训练 2018–2021、验证 2022–2023、测试 2024–2025）。

    若样本区间与固定日期不重叠（例如短样本测试），退化为按比例 55%/15%/30% 切分。

    Args:
        calendar: 交易日历。
        train_end: 训练期截止日（含）。
        valid_end: 验证期截止日（含）。

    Returns:
        ``{"train": ..., "valid": ..., "test": ...}`` 的 ``DatetimeIndex`` 字典。
    """
    cal = pd.DatetimeIndex(sorted(calendar))
    if len(cal) == 0:
        return {"train": cal, "valid": cal, "test": cal}
    train_ts = pd.Timestamp(train_end)
    valid_ts = pd.Timestamp(valid_end)
    train = cal[cal <= train_ts]
    valid = cal[(cal > train_ts) & (cal <= valid_ts)]
    test = cal[cal > valid_ts]
    if len(train) < 100 or len(test) == 0:
        n = len(cal)
        train = cal[: int(n * 0.55)]
        valid = cal[int(n * 0.55) : int(n * 0.70)]
        test = cal[int(n * 0.70) :]
    return {"train": train, "valid": valid, "test": test}
