"""CBR-MAW 数据序列目录（series catalog）。

本模块集中定义数据层与下游工具/智能体共用的**序列 ID、信息域、单位、
频率、发布时滞与口径说明**。约定：

- 序列 ID 的域前缀与 ``configs/roles.yaml`` 中 ``info_permissions`` 保持一致，
  例如 ``market.cn_equity.*``、``market.cn_bond.*``、``market.fx.*``、
  ``market.global.*``、``crossborder.flows.*``、``crossborder.holdings.*``、
  ``macro.*``、``rates.credit.*``。工具层可据此做信息权限过滤。
- 样例数据全部为**合成仿真数据（SYNTHETIC）**，源标记 ``synthetic-simulation``，
  仅用于演示、测试与方法学验证，不代表任何真实市场行情。
- 真实数据接入时只需替换数据源，序列 ID / 单位 / 时点语义保持不变。

下游可用接口：

.. code-block:: python

    from cbr.data.catalog import SERIES_SPECS, KEY_SNAPSHOT_SERIES, series_domain
    spec = SERIES_SPECS["market.cn_equity.csi300"]
    spec.to_data_card()          # -> schemas.DataCard
    series_domain("macro.pmi.manufacturing")  # -> "macro"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cbr.schemas import DataCard

#: 仿真数据源标记（所有样例数据、DataCard 必须携带此标记）
SYNTHETIC_SOURCE = "synthetic-simulation"

#: 仿真数据统一说明（写入 DataCard.notes 与 MANIFEST）
SYNTHETIC_NOTE = "SYNTHETIC 仿真数据：由固定随机种子确定性生成，仅用于演示/测试，非真实市场数据"


@dataclass(frozen=True)
class SeriesSpec:
    """单条数据序列的口径元数据。

    Attributes:
        series_id: 全局唯一序列 ID（域前缀 + 语义名）。
        name: 中文名称，用于数据卡与 UI 展示。
        domain: 信息域，对应 ``configs/roles.yaml`` 中角色的 ``info_permissions``。
        unit: 计量单位（点 / % / bp / 亿元 / 亿美元 / 指数等）。
        frequency: 数据频率，取值 ``daily`` / ``monthly`` / ``event`` / ``text``。
        release_lag_days: 观测日到发布日的时滞（交易日或自然日，依频率而定）。
        derived: 是否为派生序列（由其他序列计算得到，如期限利差）。
        in_snapshot: 是否进入默认 ``MarketSnapshot`` 的快照集合。
        notes: 口径/来源补充说明。
    """

    series_id: str
    name: str
    domain: str
    unit: str
    frequency: str = "daily"
    release_lag_days: int = 0
    derived: bool = False
    in_snapshot: bool = True
    pit_grade: str = "strict"
    notes: str = ""

    def to_data_card(
        self,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
        source: str = SYNTHETIC_SOURCE,
        pit_grade: str | None = None,
    ) -> DataCard:
        """构造数据卡（DataCard），记录口径、覆盖期与时点可得性评级。

        Args:
            coverage_start: 数据实际覆盖起始日。
            coverage_end: 数据实际覆盖结束日。
            source: 数据来源标记；仿真数据固定为 ``synthetic-simulation``。
            pit_grade: 时点可得性评级 ``strict`` / ``approximate`` / ``unavailable``。

        Returns:
            ``schemas.DataCard`` 实例。
        """
        notes = SYNTHETIC_NOTE if source == SYNTHETIC_SOURCE else ""
        if self.notes:
            notes = f"{notes}；{self.notes}" if notes else self.notes
        return DataCard(
            series_id=self.series_id,
            name=self.name,
            source=source,
            frequency=self.frequency,  # type: ignore[arg-type]
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            release_lag_days=self.release_lag_days,
            pit_grade=(pit_grade or self.pit_grade),  # type: ignore[arg-type]
            unit=self.unit,
            notes=notes,
        )


def _spec(
    series_id: str,
    name: str,
    domain: str,
    unit: str,
    frequency: str = "daily",
    release_lag_days: int = 0,
    derived: bool = False,
    in_snapshot: bool = True,
    pit_grade: str = "strict",
    notes: str = "",
) -> SeriesSpec:
    return SeriesSpec(
        series_id=series_id,
        name=name,
        domain=domain,
        unit=unit,
        frequency=frequency,
        release_lag_days=release_lag_days,
        derived=derived,
        in_snapshot=in_snapshot,
        pit_grade=pit_grade,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# 序列目录（24 条；日频 19 + 月频 5）
# --------------------------------------------------------------------------- #
_SPECS: list[SeriesSpec] = [
    # -- 中国市场：权益 ----------------------------------------------------- #
    _spec(
        "market.cn_equity.csi300",
        "沪深300指数",
        "market.cn_equity",
        "点",
        notes="收盘价，用于收益、已实现波动与压力指数的权益分量",
    ),
    _spec(
        "market.cn_equity.csi500",
        "中证500指数",
        "market.cn_equity",
        "点",
        notes="中小盘代表，用于风格/集中度与同步性刻画",
    ),
    _spec(
        "market.cn_equity.turnover",
        "沪深两市成交额",
        "market.cn_equity",
        "亿元",
        notes="日成交金额，用于流动性/换手压力代理",
    ),
    # -- 中国市场：利率与信用 ---------------------------------------------- #
    _spec(
        "market.cn_bond.cgb_2y",
        "2年期国债到期收益率",
        "market.cn_bond",
        "%",
        notes="银行间国债收益率曲线短端",
    ),
    _spec(
        "market.cn_bond.cgb_10y",
        "10年期国债到期收益率",
        "market.cn_bond",
        "%",
        notes="长端基准利率；避险情景下通常下行",
    ),
    _spec(
        "market.cn_bond.repo_7d",
        "银行间7天质押式回购利率",
        "market.cn_bond",
        "%",
        notes="资金面松紧与流动性压力代理",
    ),
    _spec(
        "market.cn_bond.term_spread",
        "10Y-2Y国债期限利差",
        "market.cn_bond",
        "bp",
        derived=True,
        notes="派生：cgb_10y - cgb_2y，乘以 100 转为 bp",
    ),
    _spec(
        "market.cn_bond.cgb_index",
        "中债国债全价指数（仿真派生）",
        "market.cn_bond",
        "点",
        derived=True,
        notes="派生：由 10 年期国债收益率日变动按久期约 7.5 年近似，供债券价格类风险测度使用",
    ),
    _spec(
        "rates.credit.aa_spread",
        "AA级中票信用利差",
        "rates.credit",
        "bp",
        notes="信用风险溢价代理，压力期走阔",
    ),
    # -- 汇率 -------------------------------------------------------------- #
    _spec(
        "market.fx.usdcny",
        "美元兑人民币在岸即期汇率",
        "market.fx",
        "CNY/USD",
        notes="在岸收盘价；数值上升表示人民币贬值",
    ),
    _spec(
        "market.fx.usdcnh",
        "美元兑离岸人民币即期汇率",
        "market.fx",
        "CNH/USD",
        notes="离岸收盘价，对跨境资金与外部冲击更敏感",
    ),
    _spec(
        "market.fx.cnh_cny_gap",
        "离岸-在岸人民币汇差",
        "market.fx",
        "pips",
        derived=True,
        notes="派生：(usdcnh - usdcny) * 10000，正值表示离岸贬值预期更强",
    ),
    # -- 全球因子（按 t-1 海外收盘对齐：北京时间 t 日早间可得） -------------- #
    _spec(
        "market.global.dxy",
        "美元指数",
        "market.global",
        "点",
        notes="全球美元流动性/避险需求代理；按 t-1 海外收盘对齐",
    ),
    _spec(
        "market.global.vix",
        "VIX恐慌指数",
        "market.global",
        "点",
        notes="全球风险偏好与波动率代理；按 t-1 海外收盘对齐",
    ),
    _spec(
        "market.global.sp500",
        "标普500指数",
        "market.global",
        "点",
        notes="全球风险资产基准；按 t-1 海外收盘对齐",
    ),
    _spec(
        "market.global.us10y",
        "美国10年期国债收益率",
        "market.global",
        "%",
        notes="全球无风险利率；按 t-1 海外收盘对齐，用于中美利差",
    ),
    _spec(
        "market.global.cn_us_spread",
        "中美10年期国债利差",
        "market.global",
        "bp",
        derived=True,
        notes="派生：(cgb_10y - us10y) * 100，负值表示中美利差倒挂",
    ),
    # -- 跨境资金 ---------------------------------------------------------- #
    _spec(
        "crossborder.flows.northbound_net",
        "北向资金净流入",
        "crossborder.flows",
        "亿元",
        notes="沪深港通北向每日净买入；压力期通常转为流出；2024-08-16 后停止披露（仿真同样置缺失）",
    ),
    _spec(
        "crossborder.flows.southbound_net",
        "南向资金净流入",
        "crossborder.flows",
        "亿元",
        notes="沪深港通南向每日净买入；与北向可能分化",
    ),
    _spec(
        "crossborder.holdings.northbound_hold",
        "北向持股总市值",
        "crossborder.holdings",
        "亿元",
        notes="外资持仓存量，用于持仓变动/集中度分析；2024-08-16 后停止披露（仿真同样置缺失）",
    ),
    _spec(
        "crossborder.holdings.southbound_hold",
        "南向持股总市值",
        "crossborder.holdings",
        "亿元",
        notes="内资港股持仓存量",
    ),
    _spec(
        "crossborder.flows.ah_premium",
        "AH股溢价指数",
        "crossborder.flows",
        "点",
        notes="A/H 价差，衡量跨境定价分割与资金扰动",
    ),
    # -- 宏观（月频，含发布时滞） ------------------------------------------ #
    _spec(
        "macro.pmi.manufacturing",
        "制造业PMI",
        "macro",
        "点",
        frequency="monthly",
        release_lag_days=1,
        notes="月末后约 1 天由国家统计局发布（仿真按自然日近似）",
    ),
    _spec(
        "macro.cpi.yoy",
        "CPI同比",
        "macro",
        "%",
        frequency="monthly",
        release_lag_days=10,
        notes="次月约 10 日发布，标签/特征使用时必须遵守发布时滞",
    ),
    _spec(
        "macro.social_financing.yoy",
        "社融存量同比",
        "macro",
        "%",
        frequency="monthly",
        release_lag_days=12,
        notes="次月约 12 日发布",
    ),
    _spec(
        "macro.fx_reserves",
        "外汇储备",
        "macro",
        "亿美元",
        frequency="monthly",
        release_lag_days=7,
        notes="次月约 7 日发布",
    ),
    _spec(
        "macro.lpr.1y",
        "1年期贷款市场报价利率(LPR)",
        "macro",
        "%",
        frequency="monthly",
        release_lag_days=0,
        notes="每月 20 日发布，当日可得",
    ),
]

SERIES_SPECS: dict[str, SeriesSpec] = {spec.series_id: spec for spec in _SPECS}

#: 全部序列 ID（有序，便于生成宽表列顺序）
SERIES_IDS: tuple[str, ...] = tuple(SERIES_SPECS)

#: 日频序列 ID
DAILY_SERIES_IDS: tuple[str, ...] = tuple(
    sid for sid, spec in SERIES_SPECS.items() if spec.frequency == "daily"
)

#: 月频序列 ID
MONTHLY_SERIES_IDS: tuple[str, ...] = tuple(
    sid for sid, spec in SERIES_SPECS.items() if spec.frequency == "monthly"
)

#: 进入默认行情/资金快照的序列（供 MarketSnapshot 使用）
KEY_SNAPSHOT_SERIES: tuple[str, ...] = tuple(
    sid for sid, spec in SERIES_SPECS.items() if spec.in_snapshot
)

#: 派生序列（由主序列计算，生成脚本中统一后处理）
DERIVED_SERIES: tuple[str, ...] = tuple(
    sid for sid, spec in SERIES_SPECS.items() if spec.derived
)

#: 北向资金/持仓披露断点（真实数据自 2024-08-19 起不再披露每日净买入）
NORTHBOUND_DISCLOSURE_END = date(2024, 8, 16)

#: 兼容别名：历史写法 / 其他模块早期约定 -> 规范序列 ID。
#: ``DataProvider`` 的读取接口会自动归一化；下游应尽量直接使用规范 ID。
SERIES_ALIASES: dict[str, str] = {
    # 工具层默认映射兼容
    "market.global.us_equity": "market.global.sp500",
    "market.global.equity": "market.global.sp500",
    "market.cn_equity": "market.cn_equity.csi300",
    "market.cn_bond": "market.cn_bond.cgb_index",
    "crossborder.northbound_net": "crossborder.flows.northbound_net",
    "crossborder.southbound_net": "crossborder.flows.southbound_net",
    "crossborder.ah_premium": "crossborder.flows.ah_premium",
    "crossborder.holdings.northbound": "crossborder.holdings.northbound_hold",
    "crossborder.holdings.southbound": "crossborder.holdings.southbound_hold",
    # 常见简写
    "market.fx.cny": "market.fx.usdcny",
    "market.fx.cnh": "market.fx.usdcnh",
    "market.global.vix_level": "market.global.vix",
    "market.global.dollar_index": "market.global.dxy",
    "market.global.cn10y": "market.cn_bond.cgb_10y",
    "market.global.us10y_yield": "market.global.us10y",
    "rates.credit.credit_spread": "rates.credit.aa_spread",
    "macro.pmi": "macro.pmi.manufacturing",
    "macro.cpi": "macro.cpi.yoy",
    "macro.fx_reserve": "macro.fx_reserves",
}

#: 信息域 -> 中文说明（用于权限/UI 展示）
DOMAIN_DESCRIPTIONS: dict[str, str] = {
    "market.cn_equity": "中国权益市场",
    "market.cn_bond": "中国债券与资金利率",
    "market.fx": "人民币汇率",
    "market.global": "全球市场因子",
    "crossborder.flows": "跨境资金流",
    "crossborder.holdings": "跨境持仓",
    "macro": "宏观经济",
    "rates.credit": "信用利差",
    "policy.fulltext": "政策文本全文",
    "news.headlines": "财经新闻标题",
}


def series_domain(series_id: str) -> str:
    """返回序列所属的信息域；未知序列按前缀推断。

    支持兼容别名：先归一化为规范序列 ID，再查目录/前缀。

    Args:
        series_id: 序列 ID。

    Returns:
        信息域字符串（用于角色信息权限过滤）。
    """
    canonical = canonical_series_id(series_id)
    spec = SERIES_SPECS.get(canonical)
    if spec is not None:
        return spec.domain
    parts = canonical.split(".")
    for i in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in DOMAIN_DESCRIPTIONS:
            return candidate
    return parts[0] if parts else "unknown"


def series_unit(series_id: str) -> str | None:
    """返回序列单位；未知序列返回 ``None``。"""
    spec = SERIES_SPECS.get(series_id)
    return spec.unit if spec is not None else None


def canonical_series_id(series_id: str) -> str:
    """把兼容别名归一化为规范序列 ID（未知 ID 原样返回）。

    Args:
        series_id: 可能是别名或规范 ID 的序列标识。

    Returns:
        规范序列 ID；若本身就是规范 ID 或未知 ID 则返回原值。
    """
    return SERIES_ALIASES.get(series_id, series_id)


def resolve_series_id(series_id: str) -> str:
    """兼容旧名 ``canonical_series_id``（语义更直观的别名解析入口）。"""
    return canonical_series_id(series_id)


def build_data_cards(
    coverage: dict[str, tuple[date | None, date | None]] | None = None,
    source: str = SYNTHETIC_SOURCE,
) -> list[DataCard]:
    """按序列目录构造全部数据卡。

    Args:
        coverage: 可选覆盖期映射 ``{series_id: (start, end)}``。
        source: 数据来源标记（仿真数据保持默认，真实数据接入时替换）。

    Returns:
        数据卡列表（顺序与 ``SERIES_IDS`` 一致）。
    """
    coverage = coverage or {}
    cards: list[DataCard] = []
    for sid in SERIES_IDS:
        spec = SERIES_SPECS[sid]
        start, end = coverage.get(sid, (None, None))
        cards.append(spec.to_data_card(coverage_start=start, coverage_end=end, source=source))
    return cards


#: 模块自检：确保目录与 roles.yaml 的域命名兼容（导入时不抛异常即可）
assert len(SERIES_IDS) == len(set(SERIES_IDS)), "序列 ID 必须唯一"
