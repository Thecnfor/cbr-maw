"""确定性合成（SYNTHETIC）金融数据生成器。

本模块生成 CBR-MAW 演示与测试所需的**仿真数据**：

- 日频：中国市场指数/成交额、国债收益率、信用利差、资金利率、
  USDCNY/USDCNH、美元指数/VIX/标普500/美债收益率、北向/南向资金流与持仓、
  AH 溢价，以及派生序列（期限利差、中美利差、离岸-在岸汇差）；
- 月频：PMI、CPI、社融、外汇储备、LPR（含发布时滞）；
- 文本：政策/新闻语料（≥300 条，含发布时间、来源、标题、正文、URL、哈希）。

**可复现性**：全部随机数来自 ``numpy.random.default_rng(seed)``，相同
``seed + 起止日期`` 必然生成完全一致的数据集。数据中的压力状态由潜在
压力过程（AR(1) + 事件脉冲）驱动，股、债、汇、信用、跨境资金与全球波动
各分量与之相关，因此风险标签具有可学习的时序结构。

**重要声明**：数据为仿真数据（``source=synthetic-simulation``），不映射任何
真实历史行情，仅用于演示、单元测试与方法学验证；不得用于真实投资/监管决策。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cbr.data.catalog import (
    DAILY_SERIES_IDS,
    MONTHLY_SERIES_IDS,
    SERIES_IDS,
    SERIES_SPECS,
    SYNTHETIC_NOTE,
    SYNTHETIC_SOURCE,
    build_data_cards,
)
from cbr.data.dataset import DOC_COLUMNS, DOC_EXTRA_COLUMNS, OBS_COLUMNS, MarketDataset

#: 默认随机种子（固定，保证可复现）
SAMPLE_SEED = 20240601
#: 默认样本区间
SAMPLE_START = "2018-01-02"
SAMPLE_END = "2025-09-30"
#: 文档数量下限（任务要求 ≥300）
MIN_DOCUMENTS = 300
#: 文档生成密度（每交易日平均条数）
DOC_DENSITY = 0.30

#: 近似中国法定节假日休市区间（仿真用，非精确交易日历；用于跨市场日历对齐演示）
_CN_HOLIDAY_RANGES: tuple[tuple[str, str], ...] = (
    # 2018
    ("2018-01-01", "2018-01-01"),
    ("2018-02-15", "2018-02-21"),
    ("2018-04-05", "2018-04-06"),
    ("2018-04-30", "2018-05-01"),
    ("2018-06-18", "2018-06-18"),
    ("2018-09-24", "2018-09-24"),
    ("2018-10-01", "2018-10-05"),
    # 2019
    ("2019-01-01", "2019-01-01"),
    ("2019-02-04", "2019-02-08"),
    ("2019-04-05", "2019-04-05"),
    ("2019-05-01", "2019-05-03"),
    ("2019-06-07", "2019-06-07"),
    ("2019-09-13", "2019-09-13"),
    ("2019-10-01", "2019-10-07"),
    # 2020
    ("2020-01-01", "2020-01-01"),
    ("2020-01-24", "2020-01-31"),
    ("2020-04-06", "2020-04-06"),
    ("2020-05-01", "2020-05-05"),
    ("2020-06-25", "2020-06-26"),
    ("2020-10-01", "2020-10-08"),
    # 2021
    ("2021-01-01", "2021-01-01"),
    ("2021-02-11", "2021-02-17"),
    ("2021-04-05", "2021-04-05"),
    ("2021-05-03", "2021-05-05"),
    ("2021-06-14", "2021-06-14"),
    ("2021-09-20", "2021-09-21"),
    ("2021-10-01", "2021-10-07"),
    # 2022
    ("2022-01-03", "2022-01-03"),
    ("2022-01-31", "2022-02-04"),
    ("2022-04-04", "2022-04-05"),
    ("2022-05-02", "2022-05-04"),
    ("2022-06-03", "2022-06-03"),
    ("2022-09-12", "2022-09-12"),
    ("2022-10-03", "2022-10-07"),
    # 2023
    ("2023-01-02", "2023-01-02"),
    ("2023-01-23", "2023-01-27"),
    ("2023-04-05", "2023-04-05"),
    ("2023-05-01", "2023-05-03"),
    ("2023-06-22", "2023-06-23"),
    ("2023-09-29", "2023-10-06"),
    # 2024
    ("2024-01-01", "2024-01-01"),
    ("2024-02-12", "2024-02-16"),
    ("2024-04-04", "2024-04-05"),
    ("2024-05-01", "2024-05-03"),
    ("2024-06-10", "2024-06-10"),
    ("2024-09-16", "2024-09-17"),
    ("2024-10-01", "2024-10-07"),
    # 2025
    ("2025-01-01", "2025-01-01"),
    ("2025-01-28", "2025-02-04"),
    ("2025-04-04", "2025-04-04"),
    ("2025-05-01", "2025-05-05"),
    ("2025-06-02", "2025-06-02"),
)

#: 潜在压力过程的“历史压力事件”脉冲锚点（仅用于仿真数据生成）
_STRESS_EVENTS: tuple[tuple[str, float, int], ...] = (
    ("2018-02-06", 1.1, 8),
    ("2018-06-19", 0.9, 10),
    ("2018-10-11", 2.0, 28),
    ("2019-05-06", 1.2, 12),
    ("2019-08-05", 1.8, 20),
    ("2020-02-03", 2.6, 32),
    ("2020-03-16", 3.0, 38),
    ("2021-07-26", 1.0, 8),
    ("2022-03-07", 1.4, 18),
    ("2022-04-25", 2.1, 30),
    ("2022-10-31", 1.4, 20),
    ("2023-08-11", 1.1, 12),
    ("2024-01-22", 1.6, 20),
    ("2024-08-05", 2.2, 22),
    ("2025-04-07", 1.8, 20),
)


# --------------------------------------------------------------------------- #
# 交易日历
# --------------------------------------------------------------------------- #
def cn_trading_calendar(start: str | date, end: str | date) -> pd.DatetimeIndex:
    """生成近似的中国 A 股交易日历。

    规则：剔除周末与 ``_CN_HOLIDAY_RANGES`` 列出的法定节假日休市区间
    （节假日为近似值，数据卡中已注明；仿真数据不依赖精确交易所日历）。

    Args:
        start: 起始日期（含）。
        end: 结束日期（含）。

    Returns:
        升序 ``DatetimeIndex``。
    """
    days = pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end))
    holidays: set[pd.Timestamp] = set()
    for left, right in _CN_HOLIDAY_RANGES:
        for ts in pd.bdate_range(pd.Timestamp(left), pd.Timestamp(right)):
            holidays.add(ts.normalize())
    return pd.DatetimeIndex([ts for ts in days if ts.normalize() not in holidays])


# --------------------------------------------------------------------------- #
# 潜在压力过程
# --------------------------------------------------------------------------- #
def latent_stress_process(calendar: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    """生成潜在金融压力过程 ``z_t``（AR(1) + 事件脉冲）。

    该过程是仿真数据的“共同因子”：股、债、汇、信用、资金流与全球波动
    均随其变化，从而使风险标签对未来具有可学习信号。

    Args:
        calendar: 交易日历。
        rng: numpy 随机数生成器。

    Returns:
        长度等于交易日数的压力过程数组（约在 [-1.5, 3.5] 区间）。
    """
    n = len(calendar)
    z = np.zeros(n, dtype=float)
    ar_noise = rng.normal(0.0, 0.12, n)
    for t in range(1, n):
        z[t] = 0.92 * z[t - 1] + ar_noise[t]
    for when, amplitude, decay in _STRESS_EVENTS:
        anchor = pd.Timestamp(when).normalize()
        pos = int(calendar.searchsorted(anchor, side="left"))
        if pos >= n:
            continue
        steps = np.arange(0, min(n - pos, 4 * decay))
        # 事件前 2 天开始预热（消息面提前反应），事件后指数衰减
        for offset, weight in ((-2, 0.10), (-1, 0.18), (0, 0.25)):
            idx = pos + offset
            if 0 <= idx < n:
                z[idx] += amplitude * weight
        z[pos:] += amplitude * np.exp(-steps / float(decay))
    return z


# --------------------------------------------------------------------------- #
# 日频序列生成
# --------------------------------------------------------------------------- #
def _student_t_shocks(rng: np.random.Generator, n: int, df: float = 5.0) -> np.ndarray:
    """生成单位方差、带肥尾的标准化冲击（t 分布）。"""
    raw = rng.standard_t(df, n)
    return raw / np.sqrt(df / (df - 2.0))


def _ar1(rng: np.random.Generator, n: int, rho: float, sigma: float) -> np.ndarray:
    """生成平稳 AR(1) 噪声序列（平稳标准差 ≈ sigma/sqrt(1-rho^2)）。"""
    eps = rng.normal(0.0, sigma, n)
    out = np.zeros(n, dtype=float)
    for t in range(1, n):
        out[t] = rho * out[t - 1] + eps[t]
    return out


def generate_daily(
    calendar: pd.DatetimeIndex,
    z: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """生成全部日频仿真序列（含派生序列）。

    Args:
        calendar: 交易日历。
        z: 潜在压力过程。
        rng: numpy 随机数生成器。

    Returns:
        行=交易日、列=日频序列 ID 的 DataFrame（无缺失值）。
    """
    n = len(calendar)
    idx = pd.DatetimeIndex(calendar)
    z = np.asarray(z, dtype=float)
    zpos = np.maximum(z, 0.0)
    shocks = _student_t_shocks(rng, n)

    # -- 权益 ------------------------------------------------------------- #
    eq_vol = 0.0090 * np.exp(0.28 * zpos) * (1.0 + 0.10 * _ar1(rng, n, 0.90, 0.10))
    eq_ret = -0.0010 * z - 0.00015 + eq_vol * shocks
    csi300 = 4000.0 * np.exp(np.cumsum(eq_ret))
    idio = 0.0055 * _student_t_shocks(rng, n) * np.exp(0.25 * zpos)
    csi500 = 6200.0 * np.exp(np.cumsum(1.12 * eq_ret + idio))
    turnover = 4200.0 * np.exp(0.20 * zpos + 0.14 * _ar1(rng, n, 0.95, 0.12))
    turnover = np.clip(turnover, 1200.0, 30000.0)

    # -- 利率与信用 ------------------------------------------------------- #
    t_grid = np.arange(n, dtype=float)
    cgb10 = 3.85 - 0.00090 * t_grid - 0.22 * zpos + 0.05 * _ar1(rng, n, 0.985, 0.010)
    cgb2 = 3.10 - 0.00065 * t_grid - 0.26 * zpos + 0.05 * _ar1(rng, n, 0.985, 0.010)
    repo7 = 2.55 - 0.00025 * t_grid + 0.20 * zpos + 0.04 * _ar1(rng, n, 0.97, 0.010)
    aa_spread = 75.0 + 46.0 * zpos + 0.8 * _ar1(rng, n, 0.97, 0.60)
    aa_spread = np.clip(aa_spread, 40.0, 360.0)

    # -- 汇率 ------------------------------------------------------------- #
    log_cny = np.log(6.65) + np.zeros(n)
    log_cny[0] = np.log(6.50)
    cny_dev = _ar1(rng, n, 0.996, 0.0008)
    for t in range(1, n):
        log_cny[t] = (
            log_cny[t - 1] + 0.00012 + 0.0038 * zpos[t] + cny_dev[t]
        )
    usdcny = np.exp(log_cny)
    cnh_dev = 1.0 + 0.0016 * zpos + 0.0009 * _ar1(rng, n, 0.90, 1.0)
    usdcnh = usdcny * cnh_dev

    # -- 全球因子 --------------------------------------------------------- #
    dxy = 91.0 + 0.0055 * t_grid + 2.2 * zpos + _ar1(rng, n, 0.985, 0.25)
    vix = 13.0 + 7.5 * zpos + 0.85 * zpos**2 + _ar1(rng, n, 0.94, 0.60)
    vix = np.clip(vix, 9.0, 75.0)
    sp_ret = -0.0007 * z - 0.0001 + 0.0085 * _student_t_shocks(rng, n)
    sp500 = 2700.0 * np.exp(np.cumsum(sp_ret))
    us10y = 2.45 + 0.00075 * t_grid + 0.10 * zpos + 0.03 * _ar1(rng, n, 0.99, 0.010)

    # -- 跨境资金 --------------------------------------------------------- #
    northbound = -38.0 * z + 0.4 + 11.0 * _ar1(rng, n, 0.30, 1.0)
    southbound = 12.0 * z - 0.2 + 10.0 * _ar1(rng, n, 0.30, 1.0)
    northbound = np.clip(northbound, -185.0, 160.0)
    southbound = np.clip(southbound, -120.0, 150.0)
    northbound_hold = (
        9500.0
        + np.cumsum(northbound * 1.1)
        + 2200.0 * (csi300 / csi300[0] - 1.0)
        + 30.0 * _ar1(rng, n, 0.90, 1.0)
    )
    northbound_hold = np.clip(northbound_hold, 1500.0, None)
    southbound_hold = (
        6200.0
        + np.cumsum(southbound * 1.1)
        + 1600.0 * (sp500 / sp500[0] - 1.0)
        + 25.0 * _ar1(rng, n, 0.90, 1.0)
    )
    southbound_hold = np.clip(southbound_hold, 1200.0, None)
    ah_premium = 126.0 + 9.0 * zpos + 2.0 * _ar1(rng, n, 0.96, 1.0)

    columns: dict[str, np.ndarray] = {
        "market.cn_equity.csi300": csi300,
        "market.cn_equity.csi500": csi500,
        "market.cn_equity.turnover": turnover,
        "market.cn_bond.cgb_2y": cgb2,
        "market.cn_bond.cgb_10y": cgb10,
        "market.cn_bond.repo_7d": repo7,
        "market.cn_bond.term_spread": (cgb10 - cgb2) * 100.0,
        "rates.credit.aa_spread": aa_spread,
        "market.fx.usdcny": usdcny,
        "market.fx.usdcnh": usdcnh,
        "market.fx.cnh_cny_gap": (usdcnh - usdcny) * 10000.0,
        "market.global.dxy": dxy,
        "market.global.vix": vix,
        "market.global.sp500": sp500,
        "market.global.us10y": us10y,
        "market.global.cn_us_spread": (cgb10 - us10y) * 100.0,
        "crossborder.flows.northbound_net": northbound,
        "crossborder.flows.southbound_net": southbound,
        "crossborder.holdings.northbound_hold": northbound_hold,
        "crossborder.holdings.southbound_hold": southbound_hold,
        "crossborder.flows.ah_premium": ah_premium,
    }
    frame = pd.DataFrame(columns, index=idx)
    return frame.loc[:, list(DAILY_SERIES_IDS)]


# --------------------------------------------------------------------------- #
# 月频序列生成
# --------------------------------------------------------------------------- #
def _month_ends(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """生成区间内每个自然月的月末日期（作为月频观测日，截断到区间末尾）。"""
    days = pd.date_range(start=start.normalize().replace(day=1), end=end.normalize(), freq="D")
    series = pd.Series(1, index=days)
    month_ends = series.resample("ME").last()
    return pd.DatetimeIndex([ts for ts in month_ends.index if ts <= end.normalize()])


def _monthly_z(calendar: pd.DatetimeIndex, z: np.ndarray, month_end: pd.Timestamp) -> float:
    """取某月末所在月份内交易日压力过程的均值（仿真用，仅生成数据时使用）。"""
    period = calendar[(calendar.year == month_end.year) & (calendar.month == month_end.month)]
    if len(period) == 0:
        return 0.0
    pos = [int(np.searchsorted(calendar.values, ts)) for ts in period]
    pos = [p for p in pos if 0 <= p < len(z)]
    return float(np.mean(z[pos])) if pos else 0.0


def generate_macro(
    calendar: pd.DatetimeIndex,
    z: np.ndarray,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成月频仿真宏观序列及其发布时点表。

    Args:
        calendar: 交易日历（用于按月聚合潜在压力）。
        z: 潜在压力过程。
        rng: numpy 随机数生成器。

    Returns:
        ``(values, release)``：两者均以观测日（月末）为索引，
        ``values`` 为宏观指标值，``release`` 为对应的发布时刻 Timestamp。
    """
    month_ends = _month_ends(calendar[0], calendar[-1])
    eps = rng.normal(0.0, 1.0, (len(month_ends), 8))    rows: dict[str, list[float]] = {sid: [] for sid in MONTHLY_SERIES_IDS}
    release = pd.DataFrame(index=month_ends, columns=list(MONTHLY_SERIES_IDS), dtype="datetime64[ns]")
    for i, month_end in enumerate(month_ends):
        stress = _monthly_z(calendar, z, month_end)
        pmi = float(np.clip(51.2 - 2.3 * stress + 0.45 * eps[i, 0], 44.0, 57.0))
        cpi = float(np.clip(2.0 + 0.35 * stress + 0.12 * eps[i, 1], -0.8, 6.0))
        social = float(np.clip(11.2 - 0.7 * stress + 0.18 * eps[i, 2], 7.5, 14.5))
        reserves = float(31000.0 - 280.0 * stress + 70.0 * eps[i, 3])
        # LPR 为阶梯型政策利率路径（仿真按主要调整时点近似）
        lpr_path = [
            ("2019-08-31", 4.25),
            ("2020-04-30", 3.85),
            ("2021-12-31", 3.80),
            ("2022-08-31", 3.65),
            ("2023-08-31", 3.45),
            ("2024-07-31", 3.35),
            ("2024-10-31", 3.10),
            ("2025-05-31", 3.00),
        ]
        lpr = 4.31
        for when, value in lpr_path:
            if month_end >= pd.Timestamp(when):
                lpr = value
        values = {
            "macro.pmi.manufacturing": pmi,
            "macro.cpi.yoy": cpi,
            "macro.social_financing.yoy": social,
            "macro.fx_reserves": reserves,
            "macro.lpr.1y": lpr,
        }
        for sid, value in values.items():
            rows[sid].append(value)
            lag = SERIES_SPECS[sid].release_lag_days
            release.loc[month_end, sid] = month_end + pd.Timedelta(days=lag, hours=9)
    values_frame = pd.DataFrame(rows, index=month_ends)
    return values_frame, release


# --------------------------------------------------------------------------- #
# 文本语料生成
# --------------------------------------------------------------------------- #
_NEUTRAL_TITLES: dict[str, tuple[str, ...]] = {
    "中国人民银行": (
        "中国人民银行开展{n}亿元公开市场操作",
        "人民银行发布{n}月金融统计数据报告",
        "中国人民银行货币政策委员会召开例会",
        "人民银行有关负责人就{n}月金融数据答记者问",
        "人民银行开展中期借贷便利操作，中标利率{n}%",
        "中国人民银行下调金融机构存款准备金率{n}个百分点",
    ),
    "中国证监会": (
        "证监会发布《上市公司信息披露管理办法》修订稿",
        "证监会新闻发言人就市场运行情况答记者问",
        "证监会核准{n}家企业首发申请",
        "证监会召开资本市场改革座谈会",
        "证监会就{name}行业并购重组问询作出回应",
    ),
    "国家外汇管理局": (
        "外汇局公布{n}月银行结售汇数据",
        "外汇局：我国跨境资金流动总体平稳",
        "外汇局发布{n}月外汇市场交易数据",
        "外汇局就跨境资金流动形势答记者问",
    ),
    "国务院": (
        "国务院常务会议研究部署稳外贸稳外资工作",
        "国务院印发关于促进外贸稳定增长的意见",
        "国务院常务会议部署金融服务实体经济措施",
        "国务院办公厅发布优化营商环境重点任务",
    ),
    "财经媒体": (
        "A股市场资金净流入{n}亿元，北向资金交投活跃",
        "人民币对美元汇率中间价报{n}",
        "债券市场收益率小幅波动，成交平稳",
        "市场人士：跨境资本流动保持基本稳定",
        "全球主要股指涨跌互现，避险情绪温和",
        "国内经济数据边际改善，市场情绪回暖",
    ),
}

_RISK_TITLES: dict[str, tuple[str, ...]] = {
    "中国人民银行": (
        "央行：跨境资本流动压力有所上升，将加强宏观审慎管理",
        "人民银行开展逆回购操作对冲资金面波动",
        "央行关注汇率波动风险，保持流动性合理充裕",
    ),
    "中国证监会": (
        "证监会：密切关注市场异常波动，维护市场稳定运行",
        "证监会部署防范化解资本市场风险重点工作",
    ),
    "国家外汇管理局": (
        "外汇局：防范跨境资金异常流动风险",
        "外汇局加强外汇市场自律管理，警惕人民币贬值预期升温",
        "外汇局：跨境资金流出压力需密切关注",
    ),
    "国务院": (
        "国务院常务会议强调防范化解金融风险",
        "国务院部署做好稳外贸稳外资与跨境风险应对工作",
    ),
    "财经媒体": (
        "北向资金大幅净流出，市场避险情绪升温",
        "人民币汇率承压，离岸汇差扩大",
        "信用利差走阔，企业融资成本上升",
        "全球风险资产回调，VIX指数快速飙升",
        "市场流动性趋紧，资金面压力显现",
        "外部冲击加剧，跨境金融风险仍需警惕",
        "债市收益率快速下行，期限利差明显走阔",
    ),
}

_NEUTRAL_SENTENCES: tuple[str, ...] = (
    "市场运行总体平稳，主要指标处于合理区间",
    "有关部门表示将继续保持政策连续性、稳定性与可预期性",
    "数据显示跨境资金流动保持基本平衡，外汇市场供求总体平衡",
    "机构认为基本面因素对市场形成一定支撑",
    "投资者情绪温和，成交活跃度处于近期均值附近",
    "政策面强调稳字当头、稳中求进，注重跨周期与逆周期调节",
    "债券收益率窄幅波动，流动性保持合理充裕",
    "人民币汇率在合理均衡水平上保持基本稳定",
    "分析人士建议关注外部环境变化与结构性机会",
    "实体经济融资需求边际改善，信贷结构继续优化",
    "监管部门表示将持续提升市场透明度与投资者保护水平",
)

_RISK_SENTENCES: tuple[str, ...] = (
    "跨境资金流出压力有所上升，需关注异常流动风险",
    "人民币贬值预期升温，离岸与在岸汇差扩大",
    "信用利差明显走阔，低评级主体再融资压力加大",
    "全球风险偏好下降，避险资产需求上升",
    "市场流动性边际收紧，资金面波动加大",
    "外部冲击通过汇率与资本流动渠道向境内传导",
    "债市收益率快速调整，期限利差走阔",
    "权益市场波动加剧，北向资金出现连续净流出",
    "监管部门提示关注跨境金融风险与市场异常波动",
    "美联储加息预期强化，中美利差收窄甚至倒挂",
    "市场对经济下行与信用风险的担忧上升",
    "机构建议提高风险预算，防范尾部风险传染",
)

_POLICY_SENTENCES: tuple[str, ...] = (
    "会议强调要防范化解重大金融风险，守住不发生系统性金融风险的底线",
    "会议要求加强宏观审慎管理，完善跨境资金流动监测预警",
    "有关部门将保持流动性合理充裕，引导金融机构加大对实体经济的支持",
    "会议提出要稳步扩大金融高水平对外开放，提升跨境金融服务能力",
    "监管部门表示将强化市场监测，依法维护市场秩序",
)

_SOURCE_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("中国人民银行", 0.22),
    ("中国证监会", 0.16),
    ("国家外汇管理局", 0.20),
    ("国务院", 0.12),
    ("财经媒体", 0.30),
)


def _compose_document(
    doc_index: int,
    publish_ts: pd.Timestamp,
    source: str,
    risk: bool,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """拼装单篇仿真政策/新闻文档（标题 + 2~4 句正文）。"""
    templates = _RISK_TITLES[source] if risk else _NEUTRAL_TITLES[source]
    title = templates[int(rng.integers(0, len(templates)))]
    title = title.replace("{n}", str(int(rng.choice([50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000]))))
    title = title.replace("{name}", str(rng.choice(["制造", "地产", "科技", "消费", "医药"])))
    n_sentences = int(rng.integers(2, 5))
    pool = list(_RISK_SENTENCES) if risk else list(_NEUTRAL_SENTENCES)
    if rng.random() < 0.5:
        pool.extend(_POLICY_SENTENCES)
    picks = rng.choice(len(pool), size=min(n_sentences, len(pool)), replace=False)
    body = "。".join(pool[int(i)] for i in picks) + "。"
    body = f"【{source}】{body}"
    doc_id = f"doc_{doc_index:05d}"
    digest = hashlib.sha256(f"{doc_id}|{title}|{body}".encode("utf-8")).hexdigest()[:32]
    sentiment = (-0.75 if risk else 0.35) + float(rng.normal(0.0, 0.10))
    return {
        "doc_id": doc_id,
        "publish_time": publish_ts,
        "source": source,
        "title": title,
        "body": body,
        "url": f"https://synthetic.example/cbr-maw/doc/{doc_id}",
        "hash": digest,
        "tags": ["风险", "跨境"] if risk else ["常规", "政策"],
        "topic": "risk" if risk else "neutral",
        "sentiment": float(np.clip(sentiment, -1.0, 1.0)),
    }


def generate_documents(
    calendar: pd.DatetimeIndex,
    z: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """生成政策/新闻仿真语料（≥300 条，含发布时间、来源、标题、正文、URL、哈希）。

    文档的“风险语义强度”与潜在压力过程相关（并带有约 5 日的提前量），
    从而让文本特征对未来压力具有可学习的增量信息（服务 P1 多模态消融）。

    Args:
        calendar: 交易日历。
        z: 潜在压力过程。
        rng: numpy 随机数生成器。

    Returns:
        列见 ``DOC_COLUMNS + DOC_EXTRA_COLUMNS`` 的文档表。
    """
    n = len(calendar)
    n_docs = max(MIN_DOCUMENTS, int(round(n * DOC_DENSITY)))
    # 文档发布日期近似服从交易日均匀分布
    positions = np.sort(rng.integers(0, n, size=n_docs))
    source_names = [name for name, _ in _SOURCE_WEIGHTS]
    source_probs = np.array([weight for _, weight in _SOURCE_WEIGHTS])
    source_probs = source_probs / source_probs.sum()
    hours = np.array([8, 9, 10, 11, 14, 15, 16, 17, 20])
    hour_probs = np.array([0.08, 0.16, 0.14, 0.10, 0.10, 0.12, 0.12, 0.10, 0.08])
    forward_window = 5
    records: list[dict[str, Any]] = []
    for i, pos in enumerate(positions):
        z_now = float(z[pos])
        forward = z[pos : min(n, pos + forward_window + 1)]
        z_forward = float(np.mean(forward)) if len(forward) else z_now
        logit = 1.6 * z_now + 0.9 * z_forward
        p_risk = float(np.clip(0.12 + 0.55 / (1.0 + np.exp(-logit)), 0.05, 0.95))
        risk = bool(rng.random() < p_risk)
        source = str(rng.choice(source_names, p=source_probs))
        day = pd.Timestamp(calendar[pos]).normalize()
        hour = int(rng.choice(hours, p=hour_probs))
        minute = int(rng.choice([0, 5, 10, 15, 20, 30, 40, 45, 50], p=np.full(9, 1.0 / 9.0)))
        publish_ts = day + pd.Timedelta(hours=hour, minutes=minute)
        records.append(_compose_document(i, publish_ts, source, risk, rng))
    frame = pd.DataFrame(records)
    return frame.loc[:, list(DOC_COLUMNS) + list(DOC_EXTRA_COLUMNS)]


# --------------------------------------------------------------------------- #
# 组装观测长表
# --------------------------------------------------------------------------- #
def _build_obs(
    daily: pd.DataFrame,
    macro_values: pd.DataFrame,
    macro_release: pd.DataFrame,
) -> pd.DataFrame:
    """把日频宽表与月频表转换为 PIT 长表 ``series_obs``。"""
    rows: list[pd.DataFrame] = []
    for series_id in daily.columns:
        spec = SERIES_SPECS.get(series_id)
        unit = spec.unit if spec else None
        # 全球因子用“前一交易日海外收盘”，在北京时间早间可得；其余序列当日 16:00 可得
        hour = 7 if (spec is not None and spec.domain == "market.global") else 16
        frame = pd.DataFrame(
            {
                "series_id": series_id,
                "obs_date": daily.index,
                "value": daily[series_id].to_numpy(dtype=float),
                "release_time": daily.index + pd.Timedelta(hours=hour),
                "source": SYNTHETIC_SOURCE,
                "unit": unit,
            }
        )
        rows.append(frame)
    for series_id in macro_values.columns:
        spec = SERIES_SPECS.get(series_id)
        unit = spec.unit if spec else None
        frame = pd.DataFrame(
            {
                "series_id": series_id,
                "obs_date": macro_values.index,
                "value": macro_values[series_id].to_numpy(dtype=float),
                "release_time": macro_release[series_id].to_numpy(),
                "source": SYNTHETIC_SOURCE,
                "unit": unit,
            }
        )
        rows.append(frame)
    obs = pd.concat(rows, ignore_index=True)
    return obs.loc[:, list(OBS_COLUMNS)]


# --------------------------------------------------------------------------- #
# 对外主入口
# --------------------------------------------------------------------------- #
def generate_dataset(
    seed: int = SAMPLE_SEED,
    start: str | date = SAMPLE_START,
    end: str | date = SAMPLE_END,
) -> MarketDataset:
    """生成完整的确定性仿真数据集（日频 + 月频 + 文本）。

    Args:
        seed: 随机种子；相同种子与起止日期生成完全一致的数据。
        start: 起始日期。
        end: 结束日期。

    Returns:
        ``MarketDataset``，``source="synthetic-simulation"``，
        ``meta`` 中记录 seed / 起止日期 / 仿真声明。
    """
    calendar = cn_trading_calendar(start, end)
    if len(calendar) == 0:
        raise ValueError(f"样本区间 {start}~{end} 内没有交易日")
    rng = np.random.default_rng(seed)
    z = latent_stress_process(calendar, rng)
    daily = generate_daily(calendar, z, rng)
    macro_values, macro_release = generate_macro(calendar, z, rng)
    documents = generate_documents(calendar, z, rng)
    obs = _build_obs(daily, macro_values, macro_release)
    dataset = MarketDataset(
        obs=obs,
        documents=documents,
        seed=seed,
        source=SYNTHETIC_SOURCE,
        meta={
            "synthetic": True,
            "note": SYNTHETIC_NOTE,
            "seed": seed,
            "start": str(calendar[0].date()),
            "end": str(calendar[-1].date()),
            "n_trading_days": int(len(calendar)),
            "n_documents": int(len(documents)),
            "calendar": "approximate CN A-share trading calendar (weekdays minus holidays)",
        },
    )
    return dataset


# --------------------------------------------------------------------------- #
# 落盘 / 读取
# --------------------------------------------------------------------------- #
def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    """以 UTF-8-SIG 写 CSV（便于 Excel 打开中文）。"""
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_sample_data(dataset: MarketDataset, out_dir: str | Path) -> dict[str, Path]:
    """把仿真数据集写入磁盘（parquet + csv + 数据卡 + MANIFEST + README）。

    Args:
        dataset: 待写入的数据集（应为 ``source=synthetic-simulation``）。
        out_dir: 输出目录（默认 ``data/samples``）。

    Returns:
        ``{文件类别: 绝对路径}`` 映射。
    """
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    daily = dataset.daily_frame()
    monthly = dataset.monthly_frame()
    documents = dataset.documents
    # 宽表落盘时把索引列显式写出，便于非 pandas 用户读取
    daily_out = daily.copy()
    daily_out.insert(0, "trade_date", daily_out.index.date)
    monthly_out = monthly.copy()
    monthly_out.insert(0, "obs_date", monthly_out.index.date)
    paths: dict[str, Path] = {}
    paths["market_daily_parquet"] = out / "market_daily.parquet"
    daily_out.to_parquet(paths["market_daily_parquet"], index=False)
    paths["market_daily_csv"] = out / "market_daily.csv"
    _write_csv(daily_out, paths["market_daily_csv"])
    paths["macro_monthly_parquet"] = out / "macro_monthly.parquet"
    monthly_out.to_parquet(paths["macro_monthly_parquet"], index=False)
    paths["macro_monthly_csv"] = out / "macro_monthly.csv"
    _write_csv(monthly_out, paths["macro_monthly_csv"])
    paths["documents_parquet"] = out / "documents.parquet"
    documents.to_parquet(paths["documents_parquet"], index=False)
    paths["documents_csv"] = out / "documents.csv"
    _write_csv(documents, paths["documents_csv"])
    # 数据卡
    cards = [card.model_dump(mode="json") for card in dataset.data_cards()]
    paths["data_cards_json"] = out / "data_cards.json"
    paths["data_cards_json"].write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    # 序列目录
    catalog = {
        sid: {
            "name": spec.name,
            "domain": spec.domain,
            "unit": spec.unit,
            "frequency": spec.frequency,
            "release_lag_days": spec.release_lag_days,
            "derived": spec.derived,
            "notes": spec.notes,
        }
        for sid, spec in SERIES_SPECS.items()
    }
    paths["series_catalog_json"] = out / "series_catalog.json"
    paths["series_catalog_json"].write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    # MANIFEST（明确标注 synthetic）
    manifest = {
        "dataset": "cbr-maw-synthetic-sample",
        "synthetic": True,
        "source": SYNTHETIC_SOURCE,
        "note": SYNTHETIC_NOTE,
        "seed": dataset.seed,
        "start": dataset.meta.get("start"),
        "end": dataset.meta.get("end"),
        "n_trading_days": int(len(daily)),
        "n_series": int(len(dataset.obs["series_id"].unique())),
        "n_documents": int(len(documents)),
        "files": {key: path.name for key, path in paths.items() if key != "manifest_json" and key != "readme"},
        "usage": "python scripts/build_sample_data.py 可复现；禁止用于真实投资/监管决策",
    }
    paths["manifest_json"] = out / "MANIFEST.json"
    paths["manifest_json"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = (
        "# data/samples · SYNTHETIC 仿真样例数据\n\n"
        "> **本目录全部为确定性仿真数据（synthetic），不映射任何真实历史行情；**\n"
        "> 仅用于 CBR-MAW 演示、单元测试与方法学验证，不得用于真实投资/监管决策。\n\n"
        f"- 随机种子：`{dataset.seed}`（固定，可复现）\n"
        f"- 覆盖区间：{manifest['start']} ~ {manifest['end']}（{manifest['n_trading_days']} 个交易日）\n"
        f"- 序列数：{manifest['n_series']}（日频 + 月频 + 派生序列）\n"
        f"- 文本语料：{manifest['n_documents']} 条（含发布时间/来源/标题/正文/URL/哈希）\n\n"
        "## 文件说明\n\n"
        "- `market_daily.parquet` / `.csv`：日频宽表（行=交易日，列=序列 ID）\n"
        "- `macro_monthly.parquet` / `.csv`：月频指标（行=观测月末）\n"
        "- `documents.parquet` / `.csv`：政策/新闻语料（含 publish_time）\n"
        "- `data_cards.json`：每个序列的数据卡（口径/单位/来源/时点评级）\n"
        "- `series_catalog.json`：序列目录（ID/域/单位/频率/发布时滞）\n"
        "- `MANIFEST.json`：数据集清单与声明\n\n"
        "重新生成：`python scripts/build_sample_data.py`\n"
    )
    paths["readme"] = out / "README.md"
    paths["readme"].write_text(readme, encoding="utf-8")
    return paths


def load_sample_dataset(sample_dir: str | Path) -> MarketDataset:
    """从磁盘重新加载样例数据集（用于 PIT 构建与 Provider）。

    Args:
        sample_dir: 样例数据目录（默认 ``data/samples``）。

    Returns:
        ``MarketDataset``。

    Raises:
        FileNotFoundError: 目录或必需文件不存在。
    """
    out = Path(sample_dir).resolve()
    required = ["market_daily.parquet", "macro_monthly.parquet", "documents.parquet", "MANIFEST.json"]
    missing = [name for name in required if not (out / name).exists()]
    if missing:
        raise FileNotFoundError(f"样例数据目录 {out} 缺少文件: {missing}；请先运行 scripts/build_sample_data.py")
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    seed = int(manifest.get("seed", 0))
    daily = pd.read_parquet(out / "market_daily.parquet")
    monthly = pd.read_parquet(out / "macro_monthly.parquet")
    documents = pd.read_parquet(out / "documents.parquet")
    rows: list[pd.DataFrame] = []
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    for series_id in [c for c in daily.columns if c != "trade_date"]:
        spec = SERIES_SPECS.get(series_id)
        hour = 7 if (spec is not None and spec.domain == "market.global") else 16
        rows.append(
            pd.DataFrame(
                {
                    "series_id": series_id,
                    "obs_date": daily["trade_date"],
                    "value": daily[series_id].astype(float),
                    "release_time": daily["trade_date"] + pd.Timedelta(hours=hour),
                    "source": SYNTHETIC_SOURCE,
                    "unit": spec.unit if spec else None,
                }
            )
        )
    monthly["obs_date"] = pd.to_datetime(monthly["obs_date"])
    for series_id in [c for c in monthly.columns if c != "obs_date"]:
        spec = SERIES_SPECS.get(series_id)
        lag = spec.release_lag_days if spec else 0
        rows.append(
            pd.DataFrame(
                {
                    "series_id": series_id,
                    "obs_date": monthly["obs_date"],
                    "value": monthly[series_id].astype(float),
                    "release_time": monthly["obs_date"] + pd.Timedelta(days=lag, hours=9),
                    "source": SYNTHETIC_SOURCE,
                    "unit": spec.unit if spec else None,
                }
            )
        )
    obs = pd.concat(rows, ignore_index=True)
    return MarketDataset(
        obs=obs,
        documents=documents,
        seed=seed,
        source=SYNTHETIC_SOURCE,
        meta={**manifest, "reloaded": True},
    )
                     