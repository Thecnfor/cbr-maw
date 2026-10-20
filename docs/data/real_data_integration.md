# 真实数据接入（CBR-MAW custom 数据集）

本文件记录用户提供数据 → `data/custom/` → PIT/模型/实验的完整接入链路。**数据文件本身
不入库**（`data/raw/`、`data/custom/`、`data/pit_real.duckdb` 均被 gitignore）；入库的是
转换脚本、映射配置、文档与可复现命令。

## 1. 数据来源

| 编号 | 来源 | 内容 | 接入方式 |
|---|---|---|---|
| A | `docs/金融数据.zip`（11.2 MB，131 个文件） | B1 人民币汇率中间价（1994–2025）；B2 SHIBOR/CNH HIBOR/CIP 基差/USDCNY 即期与 3M 远期/美债 3M；B3 沪深300、上证指数、上证50、中证2000；B4 DXY、GPR、EPU；B5 北向数据来源说明；B6 CPI/本外币存款/海关进出口 | `data/raw/financial_data/` 解压后由 `build_real_custom_data.py` 读取 |
| B | 飞书多维表格「跨境金融风险数据汇总 / 07 沪深港通资金流」 | 14,459 行 × 6 个市场（北向资金/沪股通/深股通/南向资金/港股通沪/港股通深），2014-11-17 ~ 2025-12-31 | `lark-cli base +record-list` 导出 NDJSON → `data/raw/feishu/base/` |
| C | 飞书云盘「文本数据8.2.zip」（197.6 MB，9 个 JSONL） | 人民日报、光明日报、中国政府网、证券时报、跨境、黄金、BIS、IMF、Reddit | `build_text_corpus.py` → `data/custom/policy_news.csv`（9,758 篇） |
| D | 公开接口补齐（14 条序列） | 2Y/10Y 国债、AA 信用利差（AAA 代理）、PMI、SP500、AH 溢价、中证500、两市成交额、US10Y、VIX、CNH、社融同比、外储、LPR | `fetch_public_gaps.py` + `fetch_public_extra.py` → `data/raw/public/` |

## 2. 规范序列覆盖（27 条 = 22 日频 + 5 月频）

| 序列 | 来源 | 覆盖 |
|---|---|---|
| `market.cn_equity.csi300` | 用户 B3 | 2015-01-05 ~ 2025-09-30 |
| `market.cn_equity.csi500` | 公开补齐 | 2015-01-05 ~ 2025-09-30 |
| `market.cn_equity.turnover` | 公开补齐（沪+深综指成交额） | 2015-01-05 ~ 2025-09-30 |
| `market.cn_bond.cgb_2y` / `cgb_10y` | 公开补齐 | 2015-01-05 ~ 2025-09-30 |
| `market.cn_bond.repo_7d` | 用户 B2 SHIBOR 1W（代理） | 2015-01-05 ~ 2025-09-30 |
| `market.cn_bond.term_spread` / `cgb_index` | 派生 | 同上 |
| `rates.credit.aa_spread` | 公开补齐（AAA 中票 5Y−国债 5Y 代理） | 2015-01-05 ~ 2025-09-30 |
| `market.fx.usdcny` | 用户 B2 即期（B1 中间价兜底） | 2015-01-05 ~ 2025-09-30 |
| `market.fx.usdcnh` | 公开补齐（东财/新浪） | 2015-01-05 ~ 2025-09-30 |
| `market.fx.cnh_cny_gap` | 派生 | 同上 |
| `market.global.dxy` | 用户 B4 | 2015-01-05 ~ 2025-09-30 |
| `market.global.vix` / `sp500` / `us10y` | 公开补齐（CBOE / 东财 / Treasury） | 2015-01-05 ~ 2025-09-30 |
| `market.global.cn_us_spread` | 派生 | 同上 |
| `crossborder.flows.northbound_net` | 飞书 Base 07（北向资金） | 2015-01-05 ~ **2024-08-16**（披露停止后置缺失） |
| `crossborder.flows.southbound_net` | 飞书 Base 07（南向资金） | 2015-01-05 ~ 2025-09-30 |
| `crossborder.holdings.northbound_hold` / `southbound_hold` | 流量法代理（累计净流入） | 同对应流量序列 |
| `crossborder.flows.ah_premium` | 公开补齐（恒生沪深港通 AH 溢价） | 2015-01-05 ~ 2025-09-30 |
| `macro.pmi.manufacturing` | 公开补齐（统计局口径） | 128 个月（按发布日入样） |
| `macro.cpi.yoy` | 用户 B6（仅 2021+） | 2021-02 ~ 2025-09；2015–2020 缺失 |
| `macro.social_financing.yoy` | 公开补齐（12M 滚动增量同比代理） | 2017-01 ~ 2025-09 |
| `macro.fx_reserves` | 公开补齐（SAFE 口径） | 2015-01 ~ 2025-09 |
| `macro.lpr.1y` | 公开补齐（仅调整日） | 19 次调整（2015-03 ~ 2025-05） |

## 3. 时点（PIT）与派生口径

- **日频**：`release_time = obs_date 18:00 +08:00`（A 股 15:00 收盘、中债估值约 17:30）。
  全球因子按 **t-1 海外收盘**对齐到中国交易日（`dxy/vix/sp500/us10y` 值取该中国日前最近
  一个海外收盘），避免前视。
- **月频**：`obs_date` 取**保守发布日**（PMI 次月首个交易日、CPI 次月 10 日、外储次月
  7 日、社融次月 12 日、LPR 调整日 09:15），按 `release_time` 入样。
- **派生**：`term_spread = (cgb10 - cgb2) × 100`（bp）；
  `cgb_index = 100 × exp(cumsum(-7.5 × diff(cgb10) / 100))`；
  `cnh_cny_gap = (usdcnh - usdcny) × 10⁴`（pips）；
  `cn_us_spread = (cgb10 - us10y) × 100`（bp）。
- **代理口径（已标注，不伪装为原口径）**：
  - `repo_7d` = SHIBOR 1W（回购利率可得代理）；
  - `turnover` = 沪综指 + 深综指成交额合计（全市场成交额代理）；
  - `aa_spread` = AAA 中票 5Y − 国债 5Y（对 AA 利差偏低估计）；
  - `northbound_hold` = 北向累计净流入（流量法持仓代理；无逐股持仓全量）；
  - `social_financing.yoy` = 12 个月滚动增量同比（与官方存量同比口径不同）；
  - `macro.cpi.yoy` 仅 2021+（不插值、不伪造）。

## 4. 构建产物与命令

```powershell
# 1) 用户 zip 解压（一次性）
Expand-Archive docs/金融数据.zip data/raw/financial_data -Force
# 2) 飞书 Base 资金流导出（需要 lark-cli 登录；07 资金流）
#    lark-cli base +record-list --base-token WeXEbr3m6a96m1soyXYcJRQSnYf `
#      --table-id tblXB4U2TyqlnjXP --limit 2000 --offset <N> `
#      --format ndjson --output data/raw/feishu/base/07_flows_p<N>.ndjson
# 3) 公开补齐
.venv\Scripts\python.exe scripts/fetch_public_gaps.py --start 2015-01-01 --end 2025-09-30
.venv\Scripts\python.exe scripts/fetch_public_extra.py
# 4) 文本语料
.venv\Scripts\python.exe scripts/build_text_corpus.py
# 5) 合并为 custom 数据集 + 映射
.venv\Scripts\python.exe scripts/build_real_custom_data.py --report
# 6) 真实数据 PIT + 模型产物（独立 artifacts_real，避免复用 synthetic 预计算信号）
$env:CBR_CONFIG="configs/app.real.yaml"
.venv\Scripts\python.exe scripts/build_dataset.py --custom-only `
  --pit-db data/pit_real.duckdb --artifacts artifacts_real --demo-date 2024-08-05
```

PIT 构建结果（2026-10-20）：

- `dataset_snapshot_id = ds_94c8b84b60cd1248dd57`；`corpus_hash = corpus_a7e87cba9e85e67525ae`；
- 57,421 条观测 / 27 条序列 / 9,758 篇文档 / 2,615 个交易日（2015-01-05 ~ 2025-09-30）；
- 标签 `stress_pca_q90`：训练截止 2021-12-31，阈值 τ=91.51，高压力日占比 12.7%
  （训练 10.0% / 测试 2.6%）；
- 特征包 2,615 × 59（数值 48 + 文本 11）。

## 5. 运行形态

- **真实数据 profile**：`configs/app.real.yaml`（`data.dataset: custom`、
  `synthetic_fallback: false`、`paths.artifacts: artifacts_real`）。
  启动：`$env:CBR_CONFIG="configs/app.real.yaml"; uvicorn cbr.api.main:app`。
- **默认 profile**：`configs/app.yaml` 仍为 `auto`/synthetic 优先，保证 249+ 项测试与
  离线演示可复现；真实数据通过环境变量显式启用。
- 真实数据下 `data/custom` 若缺失序列，**不回退仿真值**，特征层按缺失处理（NaN），
  避免真实实验混入 synthetic。

## 6. 已知限制

1. 北向资金 2024-08-16 后停止披露：净流入与持仓代理保持缺失，`northbound_missing` 特征标记
   该状态；不能用未来数据回填。
2. 无逐股持仓/行情全量（飞书 Base 08/02 为逐股日频、体量过大未导出），故持仓用流量法代理。
3. CPI 2015–2020 缺失；LPR 为调整日阶梯；信用利差为 AAA 代理。
4. 文本语料来源时间不均衡，详见 [text_corpus.md](text_corpus.md)。
5. 真实数据上的预测性能仍待全窗口与更多消融验证（对应报告待补，进度见
   [open_issues.md](../techdoc/open_issues.md) 的 EXP 系列）。
