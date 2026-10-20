# 真实数据接入指南

> 目标：把用户自建的跨境金融数据接入 CBR-MAW，并保证 **point-in-time（PIT）** 口径——任何 as_of 时点的决策只能看到该时点前已发布的信息。
> 相关：数据契约 [`src/cbr/data/custom.py`](../../src/cbr/data/custom.py)、[`configs/data_mapping.yaml`](../../configs/data_mapping.yaml)、[数据源实测报告](../research/data_sources.md)。
> 注意：`data/raw/`、`data/custom/` 均被 `.gitignore` 忽略，**不得入库、不得作为文档链接**；用户原始数据压缩包同样不属于仓库内容。

---

## 1. 数据放在哪里

```text
data/
├─ raw/                     # 用户原始文件（zip/xlsx/csv/ndjson），全部忽略
│  ├─ financial_data/       # 用户提供的原始金融数据
│  ├─ feishu/               # 飞书导出的资金流 / 文本语料
│  └─ public/               # 公开接口补齐的序列（可选）
└─ custom/                  # 转换后的标准数据集，被 custom 适配器读取
   ├─ daily_series.csv      # 日频宽表：date, release_time, 各 series_id 列
   ├─ monthly_series.csv    # 月频宽表：date(=发布日), release_time, 各 series_id 列
   ├─ policy_news.csv       # 文本语料：publish_time, title, content, source, url, doc_id
   └─ real_data_manifest.json  # 覆盖期 / 来源 / 口径 / PIT 假设（建议一并生成）
```

- 支持 **CSV 或 Parquet**；宽表（一列一个序列）或长表都可以，由 `configs/data_mapping.yaml` 显式声明，或按列名启发式识别。
- 统一序列 ID 必须与 `src/cbr/data/catalog.py` 的 `SERIES_IDS` 对得上（`crossborder.*`、`market.*`、`macro.*`、`rates.*` 等）；别名归一规则见 `SERIES_ALIASES`。

---

## 2. 配置 `configs/data_mapping.yaml`

文件结构（当前仓库版本）：

```yaml
custom_data_dir: data/custom

series:
  - series_id: market.cn_equity.csi300      # 规范序列 ID
    file: daily_series.csv                  # data/custom 下的文件名
    date_column: date                       # 观测日列
    value_column: market.cn_equity.csi300   # 值列
    release_time_column: release_time       # 发布时点列（PIT 的关键）
    release_lag_days: 0                     # 缺 release_time 列时用 obs + 时滞近似
    unit: '点'
    frequency: daily                        # daily | monthly
    source: user-provided

documents:
  - file: policy_news.csv
    publish_time_column: publish_time
    title_column: title
    body_column: content
    source_column: source
    url_column: url
    doc_id_column: doc_id
    source_name: feishu-text-corpus
```

字段要点：

| 字段 | 必填 | 说明 |
|---|---|---|
| `series_id` | 是 | 规范序列 ID；不在目录中的序列会被忽略或按别名归一 |
| `file` / `value_column` | 是 | 文件与值列；同一文件可映射多条序列 |
| `date_column` | 否 | 缺省按 `date`/`obs_date` 等候选列名识别 |
| `release_time_column` | 强烈建议 | 缺省时用 `date + release_lag_days` 近似，PIT 精度下降 |
| `frequency` | 否 | `daily` / `monthly`，影响时点对齐与重采样 |
| `documents.*` | 否 | 提供文本语料时配置；缺省用列名启发式识别 |

PIT 口径建议（与仓库内置构建脚本一致）：

- **A 股 / 中债日频**：`release_time = obs_date 18:00`（收盘后可得）；
- **全球因子**（美债、VIX、标普等）：按 `t-1` 海外收盘对齐到中国交易日，**绝不使用未来信息**；
- **月频宏观**：`obs_date` 取发布日（CPI 次月 10 日、PMI 月末/次月初等），按发布时点入样，而不是月末值当天可用；
- 解析失败或缺失的时点行直接丢弃，不做插值、不猜年份。

---

## 3. 切换数据源

编辑 [`configs/app.yaml`](../../configs/app.yaml) 的 `data` 段：

```yaml
data:
  dataset: custom            # auto | custom | public | synthetic
  custom_data_dir: data/custom
  sample_start: "2018-01-01"
  sample_end: "2025-09-30"
  synthetic_fallback: false  # 真实数据实验建议关闭回退，避免仿真值混入
```

- `dataset: auto`：有 custom 用 custom，缺失序列按 `synthetic_fallback` 决定是否回退仿真；
- `dataset: custom`：强制使用自建数据；
- 真实数据推荐直接使用仓库内的 [`configs/app.real.yaml`](../../configs/app.real.yaml)（`dataset: custom`、`synthetic_fallback: false`、独立 `artifacts_real`），通过 `CBR_CONFIG=configs/app.real.yaml` 启用，避免改动默认 `app.yaml`（默认仍为 auto/synthetic-friendly，保证离线测试可复现）。

---

## 4. 已有构建脚本（原始数据 → 标准数据集）

仓库 `scripts/` 下已有把原始数据转换为 `data/custom/` 的脚本。它们依赖用户本地原始数据，**不是通用命令**，按需执行并阅读脚本头部说明：

| 脚本 | 作用 |
|---|---|
| `scripts/build_real_custom_data.py` | 用户金融数据（汇率/利率/股债/全球因子/宏观）+ 飞书资金流 → `daily_series.csv` / `monthly_series.csv` / `data_mapping.yaml` / manifest |
| `scripts/build_text_corpus.py` | 飞书文本 JSONL(zip) → 流式清洗 + PIT 过滤 + 分层抽样 → `policy_news.csv` + `text_manifest.json` |
| `scripts/fetch_public_gaps.py` | 公开接口补齐主缺口（10Y 国债、信用利差、PMI、标普、AH 溢价等）→ `data/raw/public/` |
| `scripts/fetch_public_extra.py` | 补齐 2Y 国债、US10Y、VIX、CNH、社融、外储、LPR、CPI → `data/raw/public/` |

公开数据脚本需要联网并安装 `akshare`（不在 `requirements.txt` 中，按需 `pip install akshare`）；它们只负责取数与落原始 CSV，不改 `src/`。

补齐序列的来源、覆盖期与 PIT 规则见 [公开数据补齐说明](../data/public_gap_fill.md)；文本语料的筛选、抽样与已知偏差见 [真实文本语料说明](../data/text_corpus.md)；完整链路（27 条序列覆盖、派生口径、复现命令）见 [真实数据接入说明](../data/real_data_integration.md)。

---

## 5. 重建 PIT 库并验证

```powershell
# 真实数据：仅使用 data/custom（不回退仿真），独立 PIT 与模型产物
$env:CBR_CONFIG="configs/app.real.yaml"
.venv\Scripts\python.exe scripts\build_dataset.py --custom-only `
  --pit-db data/pit_real.duckdb --artifacts artifacts_real --demo-date 2024-08-05

# 测试：自建数据接入端到端
.venv\Scripts\python.exe -m pytest tests\test_custom_data.py -q
```

启动服务后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5   # 数据源与快照
Invoke-RestMethod http://127.0.0.1:8000/api/data-cards | ConvertTo-Json -Depth 3  # 序列覆盖期/时点评级
Invoke-RestMethod "http://127.0.0.1:8000/api/decision?as_of=2024-08-05&mode=collaborative" | Select-Object run_id
```

看什么：

- `data-cards` 中每个序列的 `coverage_start/coverage_end`、`source`、`pit_grade`（`strict` / `approximate`）；
- 缺失序列的 `notes` 是否出现「SYNTHETIC 仿真数据回退」——真实数据实验应避免；
- `as_of` 取数据覆盖期内、且早于最新发布日的日期；发布会话/文本同理。

---

## 6. 常见坑

1. **把发布日期当观测日**：宏观月度值按月末入样会造成前视；必须按发布日对齐（见 §2）。
2. **混用仿真回退**：`dataset: auto` + 缺失序列回退会让真实实验混入合成值；正式实验设 `synthetic_fallback: false` 并补齐缺失序列。
3. **relabel 与阈值**：`high_stress_quantile` 默认 0.90，阈值在主分析中 `frozen`；换数据后需重新确认训练期与阈值口径（见 `docs/techdoc/chapter4_method.md` 4.1.1）。
4. **序列 ID 不匹配**：未识别的列名会被忽略，检查 `series_catalog` 与 `SERIES_IDS`。
5. **数据文件入库**：`data/custom/`、`data/raw/` 已被忽略；提交前确认 `git status` 不出现数据文件。
6. **原始压缩包**：用户提供的原始数据 zip 不属于仓库内容，不要引用、不要提交。

---

## 7. v1.0 已接入的真实数据快照

2026-10-20 已完成一次真实数据接入，可直接复用（原始数据与 `data/custom/` 不入库，需要本地重建）：

| 项 | 值 |
|---|---|
| 快照 | `dataset_snapshot_id=ds_94c8b84b60cd1248dd57`、`corpus_hash=corpus_a7e87cba9e85e67525ae` |
| 覆盖 | 2015-01-05 ~ 2025-09-30，2,615 交易日；27 条规范序列 / 57,421 观测 / 9,758 篇文本 |
| 数据源 | 用户 `docs/金融数据.zip`（B1/B2/B3/B4/B6） + 飞书 Base「07 沪深港通资金流」 + 飞书「文本数据8.2」 + 公开接口补齐 14 条序列 |
| PIT/模型 | `data/pit_real.duckdb`、`artifacts_real/fusion-xgb-v1@20250904/`（signals.parquet 58 个滚动快照） |
| 真实数据 P1 | 数值-only PR-AUC 0.695/0.632/0.612；融合 0.684/0.639/0.617（文本增益不显著），详见 [真实数据试点](../techdoc/pilot_results_real_data.md) |
| 已知限制 | 北向 2024-08-16 停披露；CPI 2015–2020 缺失；SHIBOR 1W/AAA 中票/累计净流入/滚动增量等为明示代理口径 |

复现命令见 [真实数据接入说明 §4](../data/real_data_integration.md#4-构建产物与命令)；真实数据实验使用
`CBR_CONFIG=configs/app.real.yaml`（P1/P2/P3 脚本见 README §7），结果写入
`artifacts/runs/p1_real_q90`、`p2_real`、`p3_real`。
