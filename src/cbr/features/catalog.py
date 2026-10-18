"""特征元数据目录：特征名、所属模态、信息域、单位、方向与中文说明。

数值特征 → ``NUMERIC_FEATURES``；文本特征 → ``TEXT_FEATURES``。
模态贡献归因、驱动因子解释、UI 展示与实验指标都通过本目录取中文标签，
避免在模型/工具/UI 中重复硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Modality = Literal["numeric", "text"]


@dataclass(frozen=True)
class FeatureMeta:
    """单个特征的元数据。

    Attributes:
        name: 特征名（数据列名）。
        name_cn: 中文名称（UI/报告展示）。
        modality: 所属模态 ``numeric`` / ``text``。
        domain: 信息域（与 ``configs/roles.yaml`` 的 info_permissions 对齐）。
        unit: 单位。
        direction: 与“压力/风险”方向的关系：+1 数值越大风险越高，-1 数值越大风险越低，0 方向不固定。
        description: 口径与构造说明（用于技术文档与归因解释）。
    """

    name: str
    name_cn: str
    modality: Modality
    domain: str
    unit: str = ""
    direction: int = 0
    description: str = ""


def _m(
    name: str,
    name_cn: str,
    domain: str,
    unit: str,
    direction: int,
    description: str,
) -> FeatureMeta:
    return FeatureMeta(
        name=name,
        name_cn=name_cn,
        modality="numeric",
        domain=domain,
        unit=unit,
        direction=direction,
        description=description,
    )


def _t(
    name: str,
    name_cn: str,
    direction: int,
    description: str,
    domain: str = "news.headlines",
) -> FeatureMeta:
    return FeatureMeta(
        name=name,
        name_cn=name_cn,
        modality="text",
        domain=domain,
        unit="",
        direction=direction,
        description=description,
    )


_NUMERIC_LIST: list[FeatureMeta] = [
    # -- 中国权益 --------------------------------------------------------- #
    _m("ret_csi300_1d", "沪深300日收益", "market.cn_equity", "ratio", -1, "沪深300指数日收益率"),
    _m("ret_csi300_5d", "沪深300近5日收益", "market.cn_equity", "ratio", -1, "沪深300指数5交易日累计收益率"),
    _m("ret_csi300_20d", "沪深300近20日收益", "market.cn_equity", "ratio", -1, "沪深300指数20交易日累计收益率"),
    _m("vol_csi300_20d", "沪深300 20日已实现波动", "market.cn_equity", "ratio", 1, "日收益滚动20日标准差（年化）"),
    _m("vol_ratio_5_20", "波动率短长比", "market.cn_equity", "ratio", 1, "5日已实现波动 / 20日已实现波动，刻画波动聚集"),
    _m("maxdd_csi300_20d", "沪深300 20日最大回撤", "market.cn_equity", "ratio", 1, "20日滚动窗口内最大回撤幅度"),
    _m("ret_csi500_5d", "中证500近5日收益", "market.cn_equity", "ratio", -1, "中证500指数5交易日累计收益率"),
    _m("turnover_z_60", "成交额60日z", "market.cn_equity", "z", 1, "两市成交额相对过去60日的标准化偏离"),
    # -- 中国债券/资金 ---------------------------------------------------- #
    _m("term_spread", "10Y-2Y期限利差", "market.cn_bond", "bp", -1, "国债期限利差；平坦/倒挂表示压力上升"),
    _m("term_spread_chg_5d", "期限利差5日变动", "market.cn_bond", "bp", -1, "期限利差5交易日变化（收窄为压力）"),
    _m("cgb10_chg_20d", "10Y国债收益率20日变动", "market.cn_bond", "bp", 1, "10年期国债收益率20交易日变化"),
    _m("repo7_chg_5d", "7天回购利率5日变动", "market.cn_bond", "bp", 1, "资金利率短期变化，上升表示资金面趋紧"),
    # -- 信用 ------------------------------------------------------------- #
    _m("credit_spread", "AA信用利差", "rates.credit", "bp", 1, "AA级中票信用利差水平"),
    _m("credit_spread_chg_20d", "信用利差20日变动", "rates.credit", "bp", 1, "信用利差20交易日变化（走阔为压力）"),
    _m("credit_spread_z_60", "信用利差60日z", "rates.credit", "z", 1, "信用利差相对过去60日的标准化偏离"),
    # -- 汇率 ------------------------------------------------------------- #
    _m("ret_usdcny_1d", "人民币日变动", "market.fx", "ratio", 1, "USDCNY日收益率（人民币贬值时为正）"),
    _m("ret_usdcny_5d", "人民币5日变动", "market.fx", "ratio", 1, "USDCNY 5交易日累计变动"),
    _m("ret_usdcny_20d", "人民币20日变动", "market.fx", "ratio", 1, "USDCNY 20交易日累计变动"),
    _m("vol_usdcny_20d", "人民币20日已实现波动", "market.fx", "ratio", 1, "USDCNY日变动滚动20日标准差（年化）"),
    _m("cnh_cny_gap", "离岸-在岸汇差", "market.fx", "pips", 1, "CNH与CNY价差，正值表示离岸贬值预期更强"),
    _m("cnh_cny_gap_chg_5d", "离岸-在岸汇差5日变动", "market.fx", "pips", 1, "汇差5交易日变化"),
    # -- 全球因子 --------------------------------------------------------- #
    _m("ret_dxy_5d", "美元指数5日收益", "market.global", "ratio", 1, "美元指数5交易日累计收益率"),
    _m("vix_level", "VIX水平", "market.global", "点", 1, "VIX恐慌指数水平"),
    _m("vix_chg_5d", "VIX 5日变动", "market.global", "点", 1, "VIX 5交易日变化"),
    _m("ret_sp500_5d", "标普500近5日收益", "market.global", "ratio", -1, "标普500 5交易日累计收益率（t-1收盘对齐）"),
    _m("ret_sp500_20d", "标普500近20日收益", "market.global", "ratio", -1, "标普500 20交易日累计收益率"),
    _m("cn_us_spread", "中美10Y利差", "market.global", "bp", -1, "中美10年期国债利差；倒挂/收窄为压力"),
    _m("cn_us_spread_chg_20d", "中美利差20日变动", "market.global", "bp", -1, "中美利差20交易日变化"),
    # -- 跨境资金 --------------------------------------------------------- #
    _m("flow_northbound_net", "北向资金净流入", "crossborder.flows", "亿元", -1, "北向每日净流入（2024-08-16 后缺失）"),
    _m("flow_northbound_z_60", "北向资金60日z", "crossborder.flows", "z", -1, "北向净流入相对过去60日的标准化偏离"),
    _m("flow_northbound_20d_sum", "北向资金20日累计", "crossborder.flows", "亿元", -1, "北向20日累计净流入"),
    _m("flow_southbound_z_60", "南向资金60日z", "crossborder.flows", "z", -1, "南向净流入相对过去60日的标准化偏离"),
    _m("flow_southbound_20d_sum", "南向资金20日累计", "crossborder.flows", "亿元", -1, "南向20日累计净流入"),
    _m("northbound_hold_chg_20d", "北向持仓20日变动", "crossborder.holdings", "ratio", -1, "北向持股总市值20日变化（2024-08-16 后缺失）"),
    _m("northbound_missing", "北向披露缺失标记", "crossborder.flows", "flag", 0, "1=北向每日净买入停披露期（2024-08-19 起）"),
    _m("ah_premium", "AH溢价指数", "crossborder.flows", "点", 1, "AH股溢价指数水平"),
    _m("ah_premium_z_60", "AH溢价60日z", "crossborder.flows", "z", 1, "AH溢价相对过去60日的标准化偏离"),
    # -- 同步性/集中度/全球因子 ------------------------------------------ #
    _m("corr_eq_bond_60", "股债60日相关性", "market.cn_equity", "corr", 0, "沪深300收益与国债指数收益的60日滚动相关"),
    _m("corr_cn_us_60", "中美股指60日相关性", "market.global", "corr", 1, "沪深300与标普500日收益的60日滚动相关（传染性代理）"),
    _m(
        "concentration_20d",
        "风格集中度20日",
        "market.cn_equity",
        "ratio",
        0,
        "中小盘/大盘相对强弱日变化的20日波动（市场分化/集中度代理）",
    ),
    _m("global_factor", "全球风险因子", "market.global", "index", 1, "VIX、标普收益、美元指数的60日z等权复合"),
    # -- 宏观（按发布时点对齐） ------------------------------------------ #
    _m("macro_pmi", "制造业PMI", "macro", "点", -1, "制造业PMI（按发布时点对齐）"),
    _m("macro_pmi_chg_3m", "PMI 3月变动", "macro", "点", -1, "PMI 相对3个月前的变化"),
    _m("macro_cpi_yoy", "CPI同比", "macro", "%", 0, "CPI同比增速"),
    _m("macro_social_financing_yoy", "社融同比", "macro", "%", -1, "社融存量同比增速"),
    _m("macro_fx_reserves_chg_3m", "外储3月变动", "macro", "亿美元", -1, "外汇储备相对3个月前的变化"),
    _m("macro_lpr", "1年期LPR", "macro", "%", -1, "1年期LPR水平"),
    _m("macro_lpr_chg_3m", "LPR 3月变动", "macro", "%", -1, "LPR相对3个月前的变化（降息为宽松）"),
]

_TEXT_LIST: list[FeatureMeta] = [
    _t("text_doc_count_5d", "近5日文档数", 0, "政策/新闻文档5日计数（文本活跃度，非方向性）"),
    _t("text_risk_docs_5d", "近5日风险文档数", 1, "含风险关键词的文档5日计数"),
    _t("text_risk_ratio_5d", "风险文档占比5日", 1, "风险关键词文档占全部文档比例（5日）"),
    _t("text_risk_intensity_5d", "风险语义强度5日", 1, "文档风险关键词密度（长度归一）5日均值"),
    _t("text_policy_uncertainty_5d", "政策不确定性5日", 1, "政策/监管/调整类词汇密度5日均值", "policy.fulltext"),
    _t("text_capital_control_5d", "资本流动关注度5日", 1, "跨境/资金/外资类词汇密度5日均值"),
    _t("text_external_shock_5d", "外部冲击关注度5日", 1, "美联储/关税/全球/美股类词汇密度5日均值"),
    _t("text_fx_pressure_5d", "汇率压力关注度5日", 1, "汇率/贬值/离岸/中间价类词汇密度5日均值"),
    _t("text_liquidity_5d", "流动性关注度5日", 1, "流动性/逆回购/降准/资金面类词汇密度5日均值", "policy.fulltext"),
    _t("text_sentiment_5d", "文本情感5日", -1, "正向词与风险词占比之差（-1~1，越低越悲观）"),
    _t("text_risk_momentum", "文本风险动量", 1, "5日风险强度 - 20日风险强度（文本压力边际变化）"),
]

#: 数值特征元数据
NUMERIC_FEATURES: dict[str, FeatureMeta] = {meta.name: meta for meta in _NUMERIC_LIST}
#: 文本特征元数据
TEXT_FEATURES: dict[str, FeatureMeta] = {meta.name: meta for meta in _TEXT_LIST}
#: 全部特征元数据
FEATURES: dict[str, FeatureMeta] = {**NUMERIC_FEATURES, **TEXT_FEATURES}
#: 特征 -> 模态
FEATURE_MODALITY: dict[str, Modality] = {name: meta.modality for name, meta in FEATURES.items()}

#: 数值特征列（模型输入的稳定顺序）
NUMERIC_FEATURE_NAMES: tuple[str, ...] = tuple(NUMERIC_FEATURES)
#: 文本特征列
TEXT_FEATURE_NAMES: tuple[str, ...] = tuple(TEXT_FEATURES)
#: 全部特征列
FEATURE_NAMES: tuple[str, ...] = NUMERIC_FEATURE_NAMES + TEXT_FEATURE_NAMES


def feature_meta(name: str) -> FeatureMeta:
    """返回特征元数据；未知特征给出保守默认（中文名=特征名）。"""
    meta = FEATURES.get(name)
    if meta is not None:
        return meta
    if name.startswith("text_"):
        return FeatureMeta(name=name, name_cn=name, modality="text", domain="news.headlines")
    return FeatureMeta(name=name, name_cn=name, modality="numeric", domain="unknown")


def feature_modality(name: str) -> Modality:
    """返回特征所属模态（未知特征按命名推断：text_ 前缀为文本）。"""
    meta = FEATURES.get(name)
    if meta is not None:
        return meta.modality
    return "text" if name.startswith("text_") else "numeric"


def modality_weight(feature_names: list[str] | tuple[str, ...]) -> dict[str, float]:
    """按特征数量统计模态构成 ``{"numeric": 0.8, "text": 0.2}``。"""
    counts: dict[str, int] = {"numeric": 0, "text": 0}
    for name in feature_names:
        counts[feature_modality(name)] += 1
    total = sum(counts.values())
    if total == 0:
        return {"numeric": 1.0, "text": 0.0}
    return {key: value / total for key, value in counts.items()}
