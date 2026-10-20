#!/usr/bin/env python
"""把用户提供的真实金融数据（zip + 飞书 Base 资金流 + 公开补齐序列）转换为 CBR-MAW custom 数据集。

输入
----
- ``data/raw/financial_data/金融数据/``：用户提供的 B1 汇率 / B2 利率 / B3 股债指数 /
  B4 全球风险因子 / B6 宏观控制变量（xlsx / csv / 原始抓取文件）。
- ``data/raw/feishu/base/07_flows_p*.ndjson``：飞书多维表格「07 沪深港通资金流」
  （北向/南向每日净买入，2014-11-17 ~ 2025-12-31；北向 2024-08-16 后停披露）。
- ``data/raw/public/<series_id>.csv``：公开接口补齐的缺失序列（10Y/2Y 国债、信用利差、
  PMI、标普 500、VIX、AH 溢价等；列约定见 ``load_public_series``）。

输出
----
- ``data/custom/daily_series.csv``：日频宽表（列 = 规范 series_id + ``release_time``）。
- ``data/custom/monthly_series.csv``：月频宽表（按**发布日**作为 obs_date，避免前视）。
- ``configs/data_mapping.yaml``：显式字段映射（series + documents）。
- ``data/custom/real_data_manifest.json``：覆盖期/来源/口径/PIT 假设/派生公式。

口径要点（与 ``src/cbr/data/catalog.py`` 对齐）
------------------------------------------------
- 日频：``release_time = obs_date 18:00``（中国收盘后）；全球因子按 **t-1 海外收盘**
  对齐到中国交易日（值取该中国日前最近一个海外收盘，绝无未来信息）。
- 月频：``obs_date = 发布日 10:00`` 的保守日期（CPI = 次月 10 日；其他按公开发布规律），
  这样按发布时点入样，不会把月末值当成月末当天可得。
- 派生序列：期限利差 ``(10Y-2Y)*100``、国债全价指数（久期 7.5 年近似）、
  离岸-在岸汇差 ``(CNH-CNY)*1e4``、中美利差 ``(10Y-美10Y)*100``。
- 北向持股总市值：缺少逐股持仓全量数据，使用「北向累计净流入」作为**流量法代理**，
  并在 manifest / 数据卡中标注 proxy；2024-08-16 后随北向披露停止置缺失。

运行：``.venv\\Scripts\\python.exe scripts/build_real_custom_data.py --report``
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIN_DIR = ROOT / "data" / "raw" / "financial_data" / "金融数据"
FEISHU_BASE = ROOT / "data" / "raw" / "feishu" / "base"
PUBLIC_DIR = ROOT / "data" / "raw" / "public"
OUT_DIR = ROOT / "data" / "custom"
MAPPING_PATH = ROOT / "configs" / "data_mapping.yaml"

DAILY_START = pd.Timestamp("2015-01-01")
SAMPLE_START = pd.Timestamp("2018-01-01")
SAMPLE_END = pd.Timestamp("2025-09-30")
SOURCE_REAL = "user-provided"

#: 规范日频序列（与 catalog 对齐；顺序仅影响 CSV 列序）
DAILY_SERIES = [
    "market.cn_equity.csi300",
    "market.cn_equity.csi500",
    "market.cn_equity.turnover",
    "market.cn_bond.cgb_2y",
    "market.cn_bond.cgb_10y",
    "market.cn_bond.repo_7d",
    "market.cn_bond.term_spread",
    "market.cn_bond.cgb_index",
    "rates.credit.aa_spread",
    "market.fx.usdcny",
    "market.fx.usdcnh",
    "market.fx.cnh_cny_gap",
    "market.global.dxy",
    "market.global.vix",
    "market.global.sp500",
    "market.global.us10y",
    "market.global.cn_us_spread",
    "crossborder.flows.northbound_net",
    "crossborder.flows.southbound_net",
    "crossborder.holdings.northbound_hold",
    "crossborder.holdings.southbound_hold",
    "crossborder.flows.ah_premium",
]
MONTHLY_SERIES = [
    "macro.pmi.manufacturing",
    "macro.cpi.yoy",
    "macro.social_financing.yoy",
    "macro.fx_reserves",
    "macro.lpr.1y",
]
#: 全球因子（按 t-1 海外收盘对齐到中国交易日）
GLOBAL_SERIES = [
    "market.global.dxy",
    "market.global.vix",
    "market.global.sp500",
    "market.global.us10y",
]
#: 单位（写 manifest / 数据卡）
UNITS = {
    "market.cn_equity.csi300": "点",
    "market.cn_equity.csi500": "点",
    "market.cn_equity.turnover": "亿元",
    "market.cn_bond.cgb_2y": "%",
    "market.cn_bond.cgb_10y": "%",
    "market.cn_bond.repo_7d": "%",
    "market.cn_bond.term_spread": "bp",
    "market.cn_bond.cgb_index": "点",
    "rates.credit.aa_spread": "bp",
    "market.fx.usdcny": "CNY/USD",
    "market.fx.usdcnh": "CNH/USD",
    "market.fx.cnh_cny_gap": "pips",
    "market.global.dxy": "点",
    "market.global.vix": "点",
    "market.global.sp500": "点",
    "market.global.us10y": "%",
    "market.global.cn_us_spread": "bp",
    "crossborder.flows.northbound_net": "亿元",
    "crossborder.flows.southbound_net": "亿元",
    "crossborder.holdings.northbound_hold": "亿元",
    "crossborder.holdings.southbound_hold": "亿元",
    "crossborder.flows.ah_premium": "点",
    "macro.pmi.manufacturing": "点",
    "macro.cpi.yoy": "%",
    "macro.social_financing.yoy": "%",
    "macro.fx_reserves": "亿美元",
    "macro.lpr.1y": "%",
}


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, **kwargs)


def _series(frame: pd.DataFrame, date_col: str, value_col: str, name: str) -> pd.Series:
    """标准化为以日期为索引的 float Series（去重、按日排序）。"""
    dates = pd.to_datetime(frame[date_col], errors="coerce").dt.normalize()
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates).dropna()
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.name = name
    return out


# --------------------------------------------------------------------------- #
# 用户提供数据
# --------------------------------------------------------------------------- #
def load_b1_parity() -> pd.Series:
    """人民币汇率中间价（B1，1994-2025；美元列为每 100 美元折人民币，除以 100）。"""
    path = FIN_DIR / "B1-汇率" / "人民币汇率中间价（1994-2025）.xlsx"
    frame = pd.read_excel(path)
    frame.columns = [str(col).strip() for col in frame.columns]
    return _series(frame, "日期", "美元", "market.fx.usdcny") / 100.0


def load_b2_spot() -> pd.Series:
    """在岸即期收盘（B2 支撑数据，2013-06 ~ 2026-10，优先于中间价）。"""
    path = FIN_DIR / "B2-利率" / "过程文件" / "支撑数据" / "B2_即期_USDCNY.csv"
    return _series(_read_csv(path), "date", "usdcny_spot", "market.fx.usdcny")


def load_shibor_1w() -> pd.Series:
    """SHIBOR 1W（B2 全量长表）；作为 7 天回购利率的可得代理。"""
    path = FIN_DIR / "B2-利率" / "B2_SHIBOR.csv"
    frame = _read_csv(path)
    sub = frame[frame["tenor"].astype(str).str.upper() == "1W"]
    return _series(sub, "date", "rate_pct", "market.cn_bond.repo_7d")


def load_b3_index(filename: str, field: str = "close") -> pd.Series:
    """B3 指数 CSV（tradeDate 为 YYYYMMDD 整数）。"""
    path = FIN_DIR / "B3-股债指数" / filename
    frame = _read_csv(path, usecols=["tradeDate", field])
    frame = frame.assign(tradeDate=pd.to_datetime(frame["tradeDate"].astype(str), format="%Y%m%d"))
    return _series(frame, "tradeDate", field, filename)


def load_b4_dxy() -> pd.Series:
    path = FIN_DIR / "B4-全球风险因子" / "dxy" / "DXY.csv"
    return _series(_read_csv(path), "date", "value", "market.global.dxy")


def load_feishu_flows() -> tuple[pd.Series, pd.Series]:
    """飞书 Base「07 沪深港通资金流」：北向 / 南向每日净买入（亿元）。"""
    files = sorted(glob.glob(str(FEISHU_BASE / "07_flows_p*.ndjson")))
    if not files:
        raise FileNotFoundError("缺少飞书 Base 资金流导出 data/raw/feishu/base/07_flows_p*.ndjson")
    frame = pd.concat([pd.read_json(path, lines=True) for path in files], ignore_index=True)
    frame["交易日期"] = pd.to_datetime(frame["交易日期"], errors="coerce").dt.normalize()
    frame["净买入额"] = pd.to_numeric(frame["净买入额"], errors="coerce")
    north = frame[frame["市场"] == "北向资金"].set_index("交易日期")["净买入额"].sort_index()
    south = frame[frame["市场"] == "南向资金"].set_index("交易日期")["净买入额"].sort_index()
    north = north[~north.index.duplicated(keep="last")].dropna()
    south = south[~south.index.duplicated(keep="last")].dropna()
    north.name = "crossborder.flows.northbound_net"
    south.name = "crossborder.flows.southbound_net"
    return north, south


def load_b6_cpi() -> pd.Series:
    """B6 CPI（上年同月=100，宽表）；转为同比 %，并按次月 10 日作为保守发布日。"""
    path = FIN_DIR / "B6-宏观控制变量" / "CPI居民消费价格指数.xls"
    frame = pd.read_excel(path, header=None)
    # 第 3 行（0-based 2）为「指标 + 各月」；第 4 行为「居民消费价格指数(上年同月=100)」
    header = frame.iloc[2]
    row = frame.iloc[3]
    rows: list[tuple[pd.Timestamp, float]] = []
    for col in range(1, len(header)):
        label = str(header.iloc[col])
        if "年" not in label or "月" not in label:
            continue
        value = pd.to_numeric(row.iloc[col], errors="coerce")
        if not np.isfinite(value):
            continue
        try:
            year = int(label.split("年")[0])
            month = int(label.split("年")[1].split("月")[0])
        except (IndexError, ValueError):
            continue
        release = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthBegin(1) + pd.Timedelta(days=9)
        rows.append((release.normalize(), float(value) / 100.0 - 1.0))
    series = pd.Series({date: value for date, value in rows}).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    series.name = "macro.cpi.yoy"
    return series


# --------------------------------------------------------------------------- #
# 公开补齐数据
# --------------------------------------------------------------------------- #
def load_public_series() -> dict[str, pd.DataFrame]:
    """读取 data/raw/public 下公开补齐序列。

    约定（任一满足即可）：
    - 文件名即 ``<series_id>.csv``，或
    - CSV 含 ``series_id`` 列（可多序列拼接），列名 ``date`` / ``value``
      （兼容 ``publish_ts`` / ``release_time``）。

    返回 ``{series_id: DataFrame(date, value, release_time)}``；``release_time``
    按行保留（月频用于确定发布日，日频用于 PIT 校验）。
    """
    out: dict[str, pd.DataFrame] = {}
    if not PUBLIC_DIR.exists():
        return out
    for path in sorted(PUBLIC_DIR.glob("*.csv")):
        try:
            frame = _read_csv(path)
        except Exception:  # noqa: BLE001 - 单个坏文件不影响整体
            continue
        if frame.empty:
            continue
        date_col = next((c for c in ("date", "trade_date", "日期", "交易日期", "obs_date") if c in frame.columns), None)
        value_col = next((c for c in ("value", "收盘", "close", "rate", "值") if c in frame.columns), None)
        if date_col is None or value_col is None:
            continue
        if "series_id" in frame.columns:
            groups = list(frame.groupby("series_id"))
        else:
            groups = [(path.stem, frame)]
        for sid, sub in groups:
            sid = str(sid)
            if sid not in DAILY_SERIES + MONTHLY_SERIES:
                continue
            data = pd.DataFrame(
                {
                    "date": pd.to_datetime(sub[date_col], errors="coerce").dt.normalize(),
                    "value": pd.to_numeric(sub[value_col], errors="coerce"),
                }
            ).dropna(subset=["date", "value"])
            if data.empty:
                continue
            release = None
            for column in ("publish_ts", "release_time", "published_at"):
                if column in sub.columns:
                    parsed = pd.to_datetime(sub[column], errors="coerce", utc=True)
                    release = (
                        parsed.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).to_numpy()
                        if parsed.notna().any()
                        else None
                    )
                    break
            if release is None:
                release = (
                    data["date"] + pd.Timedelta(days=1, hours=6)
                    if sid in GLOBAL_SERIES
                    else data["date"] + pd.Timedelta(hours=18)
                ).to_numpy()
            data["release_time"] = pd.to_datetime(pd.Series(release)).to_numpy()
            data = (
                data.sort_values(["date", "release_time"])
                .drop_duplicates("date", keep="last")
                .reset_index(drop=True)
            )
            out[sid] = data
    return out


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def build() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """组装日频/月频宽表，返回 (daily, monthly, manifest)。"""
    daily: dict[str, pd.Series] = {}
    notes: list[str] = []

    # 中国权益：沪深300；中证500 可用公开数据补齐；成交额用上证指数成交额作代理
    csi300 = load_b3_index("沪深300指数/沪深300指数.csv")
    daily["market.cn_equity.csi300"] = csi300
    turnover = load_b3_index("上证指数/上证指数.csv", field="tradingValue")
    daily["market.cn_equity.turnover"] = turnover
    notes.append("market.cn_equity.turnover：以上证指数成交额（沪市）作为两市成交额代理，口径见 manifest")

    # 汇率：优先 B2 在岸即期，早期回退 B1 中间价
    spot = load_b2_spot()
    parity = load_b1_parity()
    usdcny = spot.combine_first(parity)
    daily["market.fx.usdcny"] = usdcny

    # 资金利率：SHIBOR 1W 作为 7 天回购代理
    daily["market.cn_bond.repo_7d"] = load_shibor_1w()
    notes.append("market.cn_bond.repo_7d：以 SHIBOR 1W 作为银行间 7 天回购利率的可得代理")

    # 全球因子（B4 DXY；VIX/SP500/US10Y 由公开数据补齐）
    daily["market.global.dxy"] = load_b4_dxy()

    # 跨境资金流：飞书 Base 07
    north, south = load_feishu_flows()
    daily["crossborder.flows.northbound_net"] = north
    daily["crossborder.flows.southbound_net"] = south
    # 持仓市值：流量法代理（累计净流入），北向披露停止后置缺失
    north_hold = north.cumsum()
    north_hold[north_hold.index > pd.Timestamp("2024-08-16")] = np.nan
    daily["crossborder.holdings.northbound_hold"] = north_hold
    daily["crossborder.holdings.southbound_hold"] = south.cumsum()
    notes.append(
        "crossborder.holdings.*：无逐股持仓全量（Base 08 为逐股日频、体量过大），"
        "以累计净流入作流量法代理；北向 2024-08-16 后置缺失"
    )

    # 公开补齐序列（日频进入 daily；月频进入下方 monthly）
    public = load_public_series()
    for sid, public_frame in public.items():
        if sid in DAILY_SERIES:
            daily[sid] = public_frame.set_index("date")["value"]
    notes.append(f"公开补齐序列：{sorted(public)}")

    # 中国日历：以沪深300交易日为准，限制在预热起点之后
    calendar = csi300.index[(csi300.index >= DAILY_START)]
    calendar = calendar.sort_values()

    # 全球因子按 t-1 海外收盘对齐（取该中国日前最近一个海外收盘）
    for sid in GLOBAL_SERIES:
        if sid not in daily:
            continue
        source = daily[sid].sort_index()
        aligned = source.reindex(calendar - pd.Timedelta(days=1), method="ffill")
        aligned.index = calendar
        daily[sid] = aligned

    # 中国日频序列按交易日日历对齐；仅允许短缺口前向填充（避免节假日/停牌小缺口），
    # 北向披露停止等长缺口保持 NaN（下游 northbound_missing 特征依赖缺失标记）。
    cn_daily = [sid for sid in DAILY_SERIES if sid in daily and sid not in GLOBAL_SERIES]
    global_daily = [sid for sid in GLOBAL_SERIES if sid in daily]
    frame = pd.DataFrame(index=calendar)
    for sid in cn_daily:
        series = daily[sid].reindex(calendar).ffill(limit=5)
        frame[sid] = series
    for sid in global_daily:
        frame[sid] = daily[sid].reindex(calendar)
    # 北向披露于 2024-08-16 后停止：净流入与流量法持仓均置缺失
    north_stop = pd.Timestamp("2024-08-16")
    for sid in ("crossborder.flows.northbound_net", "crossborder.holdings.northbound_hold"):
        if sid in frame.columns:
            frame.loc[frame.index > north_stop, sid] = np.nan

    # 公开月度序列：obs_date 取保守发布日（publish_ts 的日期），值即发布日可得值
    monthly_series: dict[str, pd.DataFrame] = {}
    for sid in MONTHLY_SERIES:
        if sid not in public:
            continue
        monthly_frame = public[sid].copy()
        monthly_frame["obs_date"] = pd.to_datetime(monthly_frame["release_time"]).dt.normalize()
        monthly_frame = monthly_frame.sort_values("obs_date").drop_duplicates("obs_date", keep="last")
        monthly_series[sid] = monthly_frame.loc[:, ["obs_date", "value"]].rename(columns={"obs_date": "date"})
    # CPI 独立处理：优先公开补齐版（若有），否则用 B6（2021+）
    if "macro.cpi.yoy" in public:
        cpi_frame = public["macro.cpi.yoy"].copy()
        cpi_frame["obs_date"] = pd.to_datetime(cpi_frame["release_time"]).dt.normalize()
        monthly_series["macro.cpi.yoy"] = cpi_frame.loc[:, ["obs_date", "value"]].rename(columns={"obs_date": "date"})
    else:
        cpi = load_b6_cpi()
        monthly_series["macro.cpi.yoy"] = pd.DataFrame({"date": cpi.index, "value": cpi.to_numpy()})
        notes.append("macro.cpi.yoy：B6 原始文件仅提供 2021-01 起同比（更早月份缺失，保留 NaN）")

    # 派生序列（仅当基础序列齐全）
    def col(sid: str) -> pd.Series | None:
        return frame[sid] if sid in frame.columns else None

    cgb10, cgb2 = col("market.cn_bond.cgb_10y"), col("market.cn_bond.cgb_2y")
    if cgb10 is not None and cgb2 is not None:
        frame["market.cn_bond.term_spread"] = (cgb10 - cgb2) * 100.0
    if cgb10 is not None:
        bond_ret = -7.5 * cgb10.diff() / 100.0
        frame["market.cn_bond.cgb_index"] = 100.0 * np.exp(bond_ret.fillna(0.0).cumsum())
    usdcnh, usdcny_series = col("market.fx.usdcnh"), col("market.fx.usdcny")
    if usdcnh is not None and usdcny_series is not None:
        frame["market.fx.cnh_cny_gap"] = (usdcnh - usdcny_series) * 10000.0
    us10y = col("market.global.us10y")
    if cgb10 is not None and us10y is not None:
        frame["market.global.cn_us_spread"] = (cgb10 - us10y) * 100.0

    # 仅保留样本窗口前后（预热从 2015 起）
    frame = frame.loc[frame.index <= SAMPLE_END]

    # 发布时点：日频统一 18:00（全球因子已在 t 日前一交易日收盘，早于 18:00 可得）
    release_time = frame.index + pd.Timedelta(hours=18)
    daily_out = frame.copy()
    daily_out.insert(0, "release_time", release_time)
    daily_out.index.name = "date"
    daily_out = daily_out.reset_index()

    all_dates = sorted({date for frame in monthly_series.values() for date in frame["date"]})
    monthly_out = pd.DataFrame(index=pd.DatetimeIndex(all_dates))
    for sid in MONTHLY_SERIES:
        if sid in monthly_series:
            frame = monthly_series[sid].dropna(subset=["value"])
            series = frame.set_index("date")["value"]
            monthly_out[sid] = series.reindex(monthly_out.index)
    monthly_out.insert(0, "release_time", monthly_out.index + pd.Timedelta(hours=10))
    monthly_out.index.name = "date"
    monthly_out = monthly_out.reset_index()
    monthly_out = monthly_out[(monthly_out["date"] >= pd.Timestamp("2015-01-01")) & (monthly_out["date"] <= SAMPLE_END)]

    manifest = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": SOURCE_REAL,
        "sample_window": [str(SAMPLE_START.date()), str(SAMPLE_END.date())],
        "daily_series": [sid for sid in DAILY_SERIES if sid in daily_out.columns],
        "monthly_series": [sid for sid in MONTHLY_SERIES if sid in monthly_out.columns],
        "missing_series": [sid for sid in DAILY_SERIES + MONTHLY_SERIES if sid not in daily_out.columns and sid not in monthly_out.columns],
        "coverage": {
            sid: [
                str(pd.to_datetime(daily_out["date"][daily_out[sid].notna()].min()).date()) if daily_out[sid].notna().any() else None,
                str(pd.to_datetime(daily_out["date"][daily_out[sid].notna()].max()).date()) if daily_out[sid].notna().any() else None,
            ]
            for sid in daily_out.columns
            if sid not in ("date", "release_time")
        },
        "units": {sid: UNITS.get(sid, "") for sid in DAILY_SERIES + MONTHLY_SERIES},
        "pit": {
            "daily": "release_time = obs_date 18:00（中国收盘后）；全球因子按 t-1 海外收盘对齐",
            "monthly": "obs_date = 保守发布日 10:00（CPI 次月 10 日）",
        },
        "notes": notes,
        "sources": {
            "B1/B2/B3/B4/B6": "用户提供 zip（docs/金融数据.zip）",
            "northbound/southbound": "飞书多维表格「跨境金融风险数据汇总 / 07 沪深港通资金流」",
            "public_gap_fill": "data/raw/public（公开接口补齐，详见 docs/data/public_gap_fill.md）",
        },
        "derived": {
            "market.cn_bond.term_spread": "(cgb_10y - cgb_2y) * 100",
            "market.cn_bond.cgb_index": "100 * exp(cumsum(-7.5 * diff(cgb_10y) / 100))",
            "market.fx.cnh_cny_gap": "(usdcnh - usdcny) * 10000",
            "market.global.cn_us_spread": "(cgb_10y - us10y) * 100",
        },
    }
    return daily_out, monthly_out, manifest


def _yaml_quote(value: str) -> str:
    """YAML 安全标量：单引号包裹（内部单引号双写），避免 % / 冒号等被解析为语法。"""
    return "'" + str(value).replace("'", "''") + "'"


def write_mapping(daily_columns: list[str], monthly_columns: list[str]) -> None:
    """写入 configs/data_mapping.yaml（显式映射，含文本语料映射）。"""
    lines = [
        "# CBR-MAW custom 数据字段映射（由 scripts/build_real_custom_data.py 生成）",
        "# 数据来源：用户提供 zip + 飞书 Base 资金流 + 公开接口补齐 + 飞书文本语料。",
        "custom_data_dir: data/custom",
        "",
        "series:",
    ]
    for sid in DAILY_SERIES:
        if sid not in daily_columns:
            continue
        lines += [
            f"  - series_id: {sid}",
            "    file: daily_series.csv",
            "    date_column: date",
            f"    value_column: {sid}",
            "    release_time_column: release_time",
            "    release_lag_days: 0",
            f"    unit: {_yaml_quote(UNITS.get(sid, ''))}",
            "    frequency: daily",
            f"    source: {SOURCE_REAL}",
        ]
    for sid in MONTHLY_SERIES:
        if sid not in monthly_columns:
            continue
        lines += [
            f"  - series_id: {sid}",
            "    file: monthly_series.csv",
            "    date_column: date",
            f"    value_column: {sid}",
            "    release_time_column: release_time",
            "    release_lag_days: 0",
            f"    unit: {_yaml_quote(UNITS.get(sid, ''))}",
            "    frequency: monthly",
            f"    source: {SOURCE_REAL}",
        ]
    lines += [
        "",
        "documents:",
        "  - file: policy_news.csv",
        "    publish_time_column: publish_time",
        "    title_column: title",
        "    body_column: content",
        "    source_column: source",
        "    url_column: url",
        "    doc_id_column: doc_id",
        "    source_name: feishu-text-corpus",
    ]
    MAPPING_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="打印覆盖报告")
    args = parser.parse_args(argv)

    daily, monthly, manifest = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily.to_csv(OUT_DIR / "daily_series.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(OUT_DIR / "monthly_series.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "real_data_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_mapping(list(daily.columns), list(monthly.columns))

    if args.report:
        print(f"daily rows={len(daily)} cols={len(daily.columns) - 2} | {daily['date'].min().date()} ~ {daily['date'].max().date()}")
        print(f"monthly rows={len(monthly)} cols={len(monthly.columns) - 2} | {monthly['date'].min().date()} ~ {monthly['date'].max().date()}")
        for sid in DAILY_SERIES:
            if sid not in daily.columns:
                print(f"  MISSING daily   {sid}")
                continue
            valid = daily["date"][daily[sid].notna()]
            if valid.empty:
                print(f"  EMPTY   daily   {sid}")
            else:
                print(f"  daily   {sid:42s} {valid.min().date()} ~ {valid.max().date()}  n={daily[sid].notna().sum()}")
        for sid in MONTHLY_SERIES:
            if sid not in monthly.columns:
                print(f"  MISSING monthly {sid}")
                continue
            valid = monthly["date"][monthly[sid].notna()]
            if valid.empty:
                print(f"  EMPTY   monthly {sid}")
            else:
                print(f"  monthly {sid:42s} {valid.min().date()} ~ {valid.max().date()}  n={monthly[sid].notna().sum()}")
        print("manifest ->", OUT_DIR / "real_data_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
