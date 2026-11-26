# data/ · 数据目录说明

> 红线：`data/samples/` 是 **SYNTHETIC 仿真夹具**，产品代码**不得**把它当产品数据读；真实来源数据不进本仓库（见下方"仓库外真实数据锚点"）。

## 目录

| 路径 | 内容 | 入库 | 产品可读 |
|---|---|---|---|
| `data/samples/` | SYNTHETIC 仿真夹具（`MANIFEST.json` 声明 `synthetic=true`） | 是 | **否**（仅测试） |
| `data/knowledge/corpus/` | 知识库语料（JSONL：政策文本、方法论） | 是 | 是 |
| `data/knowledge/index/` | BM25 索引产物（可重建） | 否 | 是（只读缓存） |
| `data/judgment/` | 裁判用引文样本（seed / challenge） | 是 | 是 |
| `data/inbox/` | 运行时投递箱（用户拖入的文件） | 否 | 是 |
| `data/raw/`、`data/processed/`、`data/traces/` | 运行时产物 | 否 | 是 |

## 仓库外真实数据锚点

真实数据体量大、许可受限，**不入库**，但本机存在，开发与回归直接用：

| 数据 | 路径 | 内容 | 口径要点 |
|---|---|---|---|
| 日频宽面板 | `/mnt/shared/recently/commorcial/data/custom/daily_series.csv` | **2615 个交易日（2015-01-05 → 2025-09-30）× 22 条序列**，列名即 `series_id`，**自带 `release_time` 列** | 已含信用利差 `rates.credit.aa_spread`、离岸 `market.fx.usdcnh` → CFSI 六维可齐备 |
| 月频宏观 | `.../custom/monthly_series.csv` | 5 条（PMI/CPI/社融/外汇储备/LPR） | 月频，按发布日推 `release_time` |
| 政策与财经文本 | `.../custom/policy_news.csv` | **9758 篇**真实中文政策/财经新闻（`doc_id, publish_time, title, content, source, url`） | 文本维度的原料；`publish_time` 即 PIT 时间 |
| 知识库语料 | `.../knowledge/corpus/*.jsonl` | 分年政策文本 | 已做过严格 PIT 过滤与分层抽样 |
| 真实 PIT 库 | `.../pit_real.duckdb`（+`.wal`） | 旧版已落库的 PIT 序列 | **迁移导入前先 checkpoint `.wal`** |
| 合成 PIT 库 | `.../pit.duckdb` | 合成（`pit_manifest.json` 标 `synthetic=true`） | 仅回归 |
| 个股明细 | `.../结构化数据/北向股票日交易数据/*.zip`、`南向股票日交易数据/*.zip` | 逐年 ZIP，内含 xlsx + 说明 txt | **ZIP 投喂场景的真实样本**（编码/表头/脏数据都有） |
| 宏观微观 | `.../结构化数据/宏观经济信息.xlsx`、`微观经济信息.xlsx` | 官方统计 | Excel 清洗样本 |
| 原始抓取 | `.../raw/{feishu,financial_data,public}` | 原始未清洗 | 复现抓取口径 |

### 日频面板的缺失语义（必须照做）

- `crossborder.flows.northbound_net` 与 `crossborder.holdings.northbound_hold` 自 **2024-08-16** 起共 **273 个交易日缺失**（北向披露规则变更）。
- 缺失**不是 0**：特征侧不得填 0 或均值；CFSI 计算时缺席维度不参与，结果必须追加 `limitations`（见 ADR-008）。
- 该面板所有行都带 `release_time`，入库时**必须沿用**，不得用 `obs_date` 代替。

### 用它做什么

1. **MVP 真实数据入口**：把 `daily_series.csv` + `monthly_series.csv` 拖进应用（窗口或对话输入框）→ 清洗 → PIT 入库 → CFSI 六维 → 一次真实研判。
2. **离线回归基线**：固定历史压力窗口（2015 股灾 / 2016 熔断 / 2018 贸易战 / 2020 疫情 / 2022 加息 / 2024-08 北向中断）做对照实验。
3. **哈希黄金向量**：旧版 Python 实现的规范化哈希产物由本目录数据复算比对（见 `contracts/golden-vectors/`）。
