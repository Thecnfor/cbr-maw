"""文本特征构造（关键词/事件词典 + 简单情感/主题分，无重依赖）。

设计要点：

- **时点过滤**：文档先按 ``publish_time`` 映射到"可用交易日"：
  政策类来源（央行/证监会/外管局/国务院，官网只有发布日期）保守地顺延到
  **下一个交易日**（shift 1 日）；财经媒体按 15:00 收盘切点，15:00 前发布
  当日可用、之后顺延到下一交易日。文本特征第 t 行只聚合可用日 ≤ t 的文档，
  与 ``DataProvider`` 的 PIT 语义一致。
- **轻量实现**：不做分词/重型模型，使用中文关键词词典统计类别密度与情感分，
  再以 5 日/20 日滚动聚合；语言无关、确定性、可解释，并可直接用于模态消融。
- **缺失处理**：无文档的窗口取 0（表示无文本信号），并保留文档计数/占比，
  避免把"没有新闻"误判为"风险很高"。
"""

from __future__ import annotations

from datetime import time as dt_time
from typing import Any

import numpy as np
import pandas as pd

from cbr.data.dataset import MarketDataset
from cbr.features.catalog import TEXT_FEATURE_NAMES

#: 收盘信息切点（该时间前发布的媒体新闻当日可用）
MARKET_CLOSE_CUTOFF = dt_time(15, 0)
#: 政策类来源（官网只有日期，无时分 → 保守顺延到下一交易日）
POLICY_SOURCES: tuple[str, ...] = ("中国人民银行", "中国证监会", "国家外汇管理局", "国务院")

#: 类别关键词词典（命中即计数；可按真实语料扩充）
KEYWORDS: dict[str, tuple[str, ...]] = {
    "risk": (
        "风险",
        "压力",
        "波动",
        "冲击",
        "流出",
        "贬值",
        "走阔",
        "收紧",
        "紧张",
        "下跌",
        "回调",
        "避险",
        "违约",
        "尾部",
        "传染",
        "危机",
        "警惕",
        "承压",
        "抛售",
        "异常",
        "下行",
    ),
    "policy_uncertainty": (
        "政策",
        "监管",
        "会议",
        "部署",
        "调整",
        "不确定性",
        "预期",
        "改革",
        "措施",
        "规定",
        "意见",
        "例会",
    ),
    "capital_control": (
        "跨境",
        "资金",
        "北向",
        "南向",
        "净流入",
        "净流出",
        "外资",
        "资本",
        "结售汇",
        "持仓",
        "外汇",
        "外储",
    ),
    "external_shock": (
        "美联储",
        "加息",
        "美元",
        "全球",
        "外部",
        "关税",
        "地缘",
        "美股",
        "标普",
        "VIX",
        "美债",
        "利差",
        "避险",
    ),
    "fx_pressure": (
        "汇率",
        "人民币",
        "贬值",
        "升值",
        "离岸",
        "在岸",
        "中间价",
        "汇差",
        "美元兑",
        "破7",
        "破 7",
    ),
    "liquidity": (
        "流动性",
        "逆回购",
        "降准",
        "降息",
        "资金面",
        "回购",
        "MLF",
        "公开市场",
        "融资",
        "流动性合理充裕",
    ),
    "positive": (
        "平稳",
        "回暖",
        "改善",
        "支撑",
        "合理",
        "稳定",
        "增长",
        "优化",
        "活跃",
        "回升",
        "向好",
        "韧性",
    ),
}

#: 类别 -> 文本特征列（滚动 5 日均值）
CATEGORY_FEATURE: dict[str, str] = {
    "risk": "text_risk_intensity_5d",
    "policy_uncertainty": "text_policy_uncertainty_5d",
    "capital_control": "text_capital_control_5d",
    "external_shock": "text_external_shock_5d",
    "fx_pressure": "text_fx_pressure_5d",
    "liquidity": "text_liquidity_5d",
}


# --------------------------------------------------------------------------- #
# 文档评分
# --------------------------------------------------------------------------- #
def _count_hits(text: str, keywords: tuple[str, ...]) -> int:
    """统计文本中关键词命中次数（简单子串匹配，中文无需分词）。"""
    return sum(1 for keyword in keywords if keyword in text)


def score_documents(documents: pd.DataFrame) -> pd.DataFrame:
    """对每篇文档做关键词/事件词典打分。

    Args:
        documents: 文档表（至少含 ``title`` / ``body``）。

    Returns:
        与输入等长的 DataFrame，包含类别密度分（按正文长度归一）、
        情感分（-1~1）与风险文档标记。
    """
    if documents.empty:
        columns = list(KEYWORDS) + ["sentiment", "risk_flag", "title_risk_hits", "body_risk_hits"]
        return pd.DataFrame(columns=columns)
    frame = documents.copy()
    titles = frame["title"].fillna("").astype(str)
    bodies = frame["body"].fillna("").astype(str)
    texts = titles + "。" + bodies
    lengths = texts.str.len().clip(lower=20)
    records: dict[str, list[float]] = {}
    for category, keywords in KEYWORDS.items():
        hits = np.array([_count_hits(text, keywords) for text in texts], dtype=float)
        records[category] = hits / (lengths.to_numpy(dtype=float) / 100.0)
    risk_hits = np.array([_count_hits(text, KEYWORDS["risk"]) for text in texts], dtype=float)
    positive_hits = np.array([_count_hits(text, KEYWORDS["positive"]) for text in texts], dtype=float)
    total = risk_hits + positive_hits + 1.0
    records["sentiment"] = (positive_hits - risk_hits) / total
    records["risk_flag"] = (risk_hits > 0).astype(float)
    records["title_risk_hits"] = np.array(
        [_count_hits(title, KEYWORDS["risk"]) for title in titles], dtype=float
    )
    records["body_risk_hits"] = risk_hits
    return pd.DataFrame(records, index=frame.index)


# --------------------------------------------------------------------------- #
# 可用交易日映射（PIT 核心）
# --------------------------------------------------------------------------- #
def effective_trading_day(
    publish_time: pd.Timestamp,
    source: str,
    calendar: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    """把文档发布时间映射到"文本特征可用交易日"（保守、无未来信息）。

    - 政策类来源（官网只有日期）：顺延到发布日**之后**的第一个交易日（shift 1 日）；
    - 财经媒体：若发布日是交易日且时间 ≤ 15:00，当日可用；否则顺延到下一交易日；
    - 发布日不是交易日：顺延到下一交易日；
    - 超出样本区间：返回 None。

    Args:
        publish_time: 发布时间。
        source: 文档来源（用于区分政策/媒体口径）。
        calendar: 交易日历（升序）。

    Returns:
        可用交易日（``Timestamp``）或 None。
    """
    if pd.isna(publish_time) or len(calendar) == 0:
        return None
    ts = pd.Timestamp(publish_time)
    day = ts.normalize()
    position = int(calendar.searchsorted(day, side="left"))
    is_trading_day = position < len(calendar) and pd.Timestamp(calendar[position]).normalize() == day
    is_policy = source in POLICY_SOURCES
    if is_policy:
        pos = int(calendar.searchsorted(day, side="right"))  # 严格下一交易日
        return pd.Timestamp(calendar[pos]).normalize() if pos < len(calendar) else None
    if is_trading_day:
        if ts.time() <= MARKET_CLOSE_CUTOFF:
            return day
        pos = position + 1
        return pd.Timestamp(calendar[pos]).normalize() if pos < len(calendar) else None
    pos = int(calendar.searchsorted(day, side="left"))
    return pd.Timestamp(calendar[pos]).normalize() if pos < len(calendar) else None


def _assign_effective_days(documents: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.Series:
    """为全部文档计算可用交易日（无法映射的为 ``NaT``）。"""
    cache: dict[tuple[Any, str], pd.Timestamp | None] = {}

    def resolve(row: pd.Series) -> pd.Timestamp | None:
        key = (row["publish_time"], str(row["source"]))
        if key not in cache:
            cache[key] = effective_trading_day(row["publish_time"], str(row["source"]), calendar)
        return cache[key]

    return documents.apply(resolve, axis=1)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def _rolling_weighted_mean(
    numerator: pd.Series,
    denominator: pd.Series,
    window: int,
) -> pd.Series:
    """滚动加权均值（分子为加权和，分母为权重和，避免无文档时被稀释为 0）。"""
    sum_num = numerator.rolling(window, min_periods=1).sum()
    sum_den = denominator.rolling(window, min_periods=1).sum()
    return sum_num / sum_den.replace(0.0, np.nan)


def build_text_features(
    dataset: MarketDataset,
    calendar: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """构造文本特征（行=交易日，列=``TEXT_FEATURE_NAMES``）。

    Args:
        dataset: 时点数据集（使用 ``documents`` 表）。
        calendar: 目标交易日历（默认 ``dataset.calendar``）。

    Returns:
        文本特征 DataFrame；无文档时返回全 0（保留列结构，便于模态消融）。
    """
    cal = pd.DatetimeIndex(calendar if calendar is not None else dataset.calendar).sort_values()
    out = pd.DataFrame(0.0, index=cal, columns=list(TEXT_FEATURE_NAMES))
    documents = dataset.documents
    if documents.empty or cal.size == 0:
        return out

    scores = score_documents(documents)
    effective = _assign_effective_days(documents, cal)
    frame = pd.concat([documents[["source"]], scores], axis=1)
    frame["effective_day"] = effective.to_numpy()
    frame = frame.dropna(subset=["effective_day"])
    if frame.empty:
        return out
    positions = cal.get_indexer(pd.DatetimeIndex(frame["effective_day"]))
    valid = positions >= 0
    frame = frame.loc[valid].copy()
    positions = positions[valid]
    n_days = cal.size

    # 每日聚合：文档数、风险文档数、类别分数和
    doc_count = np.bincount(positions, minlength=n_days).astype(float)
    risk_count = np.bincount(
        positions, weights=frame["risk_flag"].to_numpy(dtype=float), minlength=n_days
    )
    category_sums = {
        category: np.bincount(
            positions, weights=frame[category].to_numpy(dtype=float), minlength=n_days
        )
        for category in KEYWORDS
    }
    sentiment_sum = np.bincount(
        positions, weights=frame["sentiment"].to_numpy(dtype=float), minlength=n_days
    )
    daily = pd.DataFrame(
        {
            "doc_count": doc_count,
            "risk_count": risk_count,
            "sentiment_sum": sentiment_sum,
            **{f"sum_{category}": values for category, values in category_sums.items()},
        },
        index=cal,
    )
    # 累计文档数（作为滚动加权均值分母）
    daily["cum_doc_count"] = daily["doc_count"].cumsum()

    # 1) 文档计数 / 占比
    out["text_doc_count_5d"] = daily["doc_count"].rolling(5, min_periods=1).sum()
    out["text_risk_docs_5d"] = daily["risk_count"].rolling(5, min_periods=1).sum()
    risk_ratio_den = daily["doc_count"].rolling(5, min_periods=1).sum().replace(0.0, np.nan)
    out["text_risk_ratio_5d"] = (
        daily["risk_count"].rolling(5, min_periods=1).sum() / risk_ratio_den
    ).fillna(0.0)

    # 2) 类别语义强度（按文档数加权，范围与密度分一致）
    for category, feature_name in CATEGORY_FEATURE.items():
        numerator = daily[f"sum_{category}"]
        out[feature_name] = _rolling_weighted_mean(
            numerator, daily["doc_count"], window=5
        ).fillna(0.0)
    out["text_sentiment_5d"] = _rolling_weighted_mean(
        daily["sentiment_sum"], daily["doc_count"], window=5
    ).fillna(0.0)
    out["text_risk_momentum"] = out["text_risk_intensity_5d"] - _rolling_weighted_mean(
        daily["sum_risk"], daily["doc_count"], window=20
    ).fillna(0.0)

    return out.loc[:, list(TEXT_FEATURE_NAMES)].astype(float)
