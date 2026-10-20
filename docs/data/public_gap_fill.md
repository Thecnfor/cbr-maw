# 公开数据补齐（缺失序列）

用户提供的 `docs/金融数据.zip` 覆盖汇率、利率、股债指数、全球风险因子与宏观控制变量，
但缺少系统规范序列中的 7 条关键日频/月频数据。`scripts/fetch_public_gaps.py`（主）
与 `scripts/fetch_public_extra.py`（补充）从公开、免 key 接口抓取并时点化，
统一写入 `data/raw/public/<series_id>.csv`（列：
`series_id,date,value,unit,frequency,source,source_url,publish_ts,fetch_ts,version`）。

## 1. 序列清单与来源

| series_id | 频率 | 单位 | 来源（主 → 备） | 覆盖 |
|---|---|---|---|---|
| `market.cn_bond.cgb_10y` | 日 | % | 东方财富数据中心 → 中债（chinabond）曲线 | 2015-01-04 ~ 2025-09-30（2,690 行） |
| `market.cn_bond.cgb_2y` | 日 | % | 中国货币网（akshare `bond_zh_us_rate`） | 2015-01-05 ~ 2026-10-19（3,143 行） |
| `rates.credit.aa_spread` | 日 | bp | 中债「中票 AAA 5Y − 国债 5Y」代理 | 2015-01-04 ~ 2025-09-30（2,690 行） |
| `macro.pmi.manufacturing` | 月 | 点 | 国家统计局口径（东方财富数据中心） | 2015-01-31 ~ 2025-07-31（129 行） |
| `market.global.sp500` | 日 | 点 | 东方财富 push2his → CBOE 官方 CSV 兜底 | 2015-01-05 ~ 2025-09-30（2,703 行） |
| `crossborder.flows.ah_premium` | 日 | 点 | 东方财富（恒生沪深港通 AH 股溢价指数） | 2015-01-05 ~ 2025-09-30（2,722 行） |
| `market.cn_equity.csi500` | 日 | 点 | 东方财富 push2his → 中证指数官网 | 2015-01-05 ~ 2025-09-30（2,614 行） |
| `market.cn_equity.turnover` | 日 | 亿元 | 东方财富（沪综指 + 深综指成交额合计） | 2015-01-05 ~ 2025-09-30（2,614 行） |
| `market.global.us10y` | 日 | % | US Treasury（经 akshare） | 2015-01-02 ~ 2026-10-19 |
| `market.global.vix` | 日 | 点 | CBOE 官方历史 CSV | 1990-01-02 ~ 2026-10-19 |
| `market.fx.usdcnh` | 日 | CNH/USD | 东方财富外汇历史（新浪外汇兜底） | 2014-11-10 ~ 2026-10-16 |
| `macro.social_financing.yoy` | 月 | % | 人民银行社融增量 → 12 个月滚动同比（代理） | 2016-12 ~ 2026-04 |
| `macro.fx_reserves` | 月 | 亿美元 | 国家外汇管理局（akshare `macro_china_fx_gold`） | 2008-01 ~ 2026-09 |
| `macro.lpr.1y` | 月 | % | 全国银行间同业拆借中心 LPR（仅调整日） | 2013-10-25 ~ 2025-05-20（29 次调整） |

> 说明：`market.cn_equity.turnover` 的「沪深两市成交额」若东财接口不可用，退化为
> 上证指数 + 深证综指成交额合计；`rates.credit.aa_spread` 公开渠道仅有 AAA 中票曲线，
> AA 曲线需付费接口，故为**偏低估计的代理口径**；`macro.social_financing.yoy` 使用
> 12 个月滚动增量同比，与官方「存量同比」口径存在差异，仅作宏观控制变量。

## 2. PIT（时点可得性）规则

- 中国日频（A 股/中债/港股）：`publish_ts = 观测日 18:00 +08:00`（A 股 15:00 收盘、
  港股 16:00 收盘、中债估值约 17:30 发布，取保守值）。
- 全球日频（`sp500` / `us10y` / `vix`）：`date` 为美东交易日，`publish_ts = 次日
  09:00 +08:00`，避免把美股当日收盘当作北京时间当日可得。
- 月频（PMI）：`date` = 参考月最后一日，`publish_ts` = 次月首个交易日 09:00（统计局
  实际月末最后一日 09:30 发布，此处更保守）；其他月频按发布日在 6–12 日左右。
- 所有序列**不做插值/填充**，缺失即缺行；下游按 `release_time` 入样。

## 3. 失败与替代

- 首轮抓取（2026-10-20 20:03）因本机网络短时中断（DNS/连接失败）全部失败，已重跑成功。
- FRED / Yahoo Finance 在本机网络不可达；故 10Y 美债改用 US Treasury 官方 CSV，
  VIX/SPX 改用 CBOE 官方 CSV，CNH 改用东财/新浪外汇历史。
- AKShare 的 `macro_china_cpi` 走东方财富数据中心，本机偶发连接失败；CPI 因此仍以
  用户 B6 文件（2021+）为准，2015–2020 的 CPI 保留缺失（不伪造）。

## 4. 复现

```powershell
.venv\Scripts\python.exe scripts/fetch_public_gaps.py --start 2015-01-01 --end 2025-09-30
.venv\Scripts\python.exe scripts/fetch_public_extra.py
.venv\Scripts\python.exe scripts/build_real_custom_data.py --report
```

两次抓取分别写 `data/raw/public/manifest.json` 与 `manifest_extra.json`；随后
`build_real_custom_data.py` 把它们与用户 zip、飞书 Base 资金流合并为
`data/custom/daily_series.csv` / `monthly_series.csv`，并生成 `configs/data_mapping.yaml`。
