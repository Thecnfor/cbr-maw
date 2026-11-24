# R1 · MediaTone：媒体基调与跨境资产价格预测（研究域设计）

> 归属：`docs/00-设计基线.md` §5 研究方向 R1 · `[已定]` 四个方向全部在范围内。
> 上游材料：`ref/MediaTone/媒体基调构建及数据收集.docx`、`ref/MediaTone/Framework-Media tone and price prediction.docx`、`ref/MediaTone/Literature/`（9 篇 PDF）、`ref/数据汇总统计表-简化版(1).xlsx`。
> 状态标记沿用基线：`[已定]` / `[推定]` / `[建议·待复核]` / `[待定]`。
> 本文档**不含任何实验结果数值**；所有指标数值必须由真实数据运行产出。

---

## 研究问题

### 精确表述

> 在严格时点正确（PIT）与扩展窗口样本外协议下，**媒体基调（Media Tone / Positive Tone / Negative Tone）作为日频外生变量，对跨境金融资产（股票 / 债券 / 汇率 / 原油）价格或收益率是否具有超出常规金融数值变量的增量预测力？该增量在计量经济学模型、机器学习模型、LLM 模型三类方法中的排序如何？在 7 组模态消融下，全模态是否最优？**

拆成四个可分别证伪的子问题：

| 编号 | 子问题 | 对应源文档位置 |
|---|---|---|
| R1-Q1 | 媒体基调能否被稳定地测量（双轨打分是否一致） | `媒体基调构建及数据收集.docx` §思路一/思路二 |
| R1-Q2 | 媒体基调是否有增量预测力（相对数值变量） | `Framework-…docx` §5.6 |
| R1-Q3 | 三类模型（计量 / ML / LLM）谁更准 | `Framework-…docx` §5.1、§5.3 |
| R1-Q4 | 多模态是否优于单模态 | `Framework-…docx` §5.4 |

### 为什么对跨境金融风险重要

1. **前置性**：市场行情、财务报表、宏观指标都带发布滞后（基线 §4 已继承 `release_lag_days` 约定）；媒体报道是**当日可得**的日频外生变量，若有效则天然成为最早的风险信号之一。
2. **跨境属性**：跨境资产的风险定价高度依赖境外资金对中国/新兴市场主体的预期。境外媒体（IMF / Bloomberg / Refinitiv）与境外经营地的信息，正是普通境内指标覆盖不到的盲区。
3. **可解释性诉求**：R4 多智能体协同要求每条结论可回指到原文片段（基线 §7.2 证据链）。媒体基调天然携带**原文证据**，是 Agent 结论最容易做证据闭环的一类信号。

### 「回答了」长什么样

本研究域被判定为"已回答"，当且仅当同时产出下列 6 项**可复现产物**（产物落在 `artifacts/research/R1/<run_id>/`，不进安装包）：

| 产物 | 内容 | 判定标准 |
|---|---|---|
| `P1` 指标字典 | 三个指标的 定义 / 计算公式 / 经济含义 / 口径来源 / 版本 | 源文档表3-1、表3-2 的三列**全部填实**，且每条公式可被单元测试验证 |
| `P2` 双轨打分序列 | 日频 `media_tone` / `positive_tone` / `negative_tone`，含 `lexicon_version`、`scorer_version`、`as_of` | 覆盖全部有效交易日；缺失日显式为 null 而非 0 |
| `P3` 三模型 × 7 消融主表 | 滚动窗口下的 MSE / RMSE / R² | `windows=3, step=1`（源文档 §5.3 已定），样本外 |
| `P4` 增量信息检验 | 媒体基调相对数值变量的增量 R²、损失差 DM 检验 | 给出统计量、p 值、样本量；**不显著不得写成显著** |
| `P5` 可解释性 | SHAP / LIME / PDP 曲线 | 至少给出媒体基调在 Top-K 驱动因子中的位置与 PDP 单调性 |
| `P6` 漂移报告 | 基线漂移指标随时间曲线 | 见 §3.5 |

---

## 既有材料与结论

### 材料已确立的内容（可直接继承）

| # | 结论 / 设定 | 出处 |
|---|---|---|
| A1 | **双轨打分**：思路一 = Google Cloud（Google Cloud Natural Language 情绪 API）基线；思路二 = 爬取新闻/政策文本 + 词典法自建测度 | `媒体基调构建及数据收集.docx`「构建思路」 |
| A2 | **三个产出指标**：Media Tone、Positive Tone、Negative Tone（表3-1、表3-2 各列同名） | 同上 表3-1 / 表3-2 |
| A3 | **9 组关键词**及文档中填报的爬取量 | 同上 表1（见下表） |
| A4 | **数据来源清单**（中文 7 家 + 英文 4 家） | 同上「数据来源」段、表2 |
| A5 | **数据范围**与跨境金融资产起始时间对齐（文档写作"？2014-"，起始年**未定**） | 同上「数据范围」 |
| A6 | **语音数据线索**：英为财情（电话会议文字记录）；2017 年标普500 公司季度盈利电话会议，按关键词爬取（原文带"？"） | 同上「针对语音数据」 |
| A7 | **采集技术栈**：playwright（IMF、彭博社）、正则（清洗）、八爪鱼（证券时报） | 同上 表4 |
| A8 | **预处理口径**（仅一句话）："解析、降噪、清洗与信息筛选" | 同上「（4）数据预处理」 |
| A9 | **跨境金融资产定义** = stock、bond、exchange rate、crude oil | `Framework-…docx` §3.2 |
| A10 | **三类模型**：计量经济学模型 / 机器学习模型（NN、LSTM、决策树及集成学习如随机森林、SVM 等"数10种"）/ LLM | 同上 §5.1 |
| A11 | **评价指标**：MSE、RMSE、R²；滚动窗口 `windows=3, step=1`，图示 1..300，区分短期/中期/长期 | 同上 §5.3 |
| A12 | **7 组模态消融**：Numeric、Text、Audio、Numeric+Text、Numeric+Audio、Text+Audio、Text+Audio+Numeric | 同上 §5.4（示例引用 Cao et al. 2025 RiskLabs） |
| A13 | **文本分析两条路线**：基准文本分析 + LLM 分析（ChatGPT / DeepSeek / Google Gemini） | 同上 §4.1 |
| A14 | **可解释性方案**：计量模型 `Y = b1*X1 + b2*X2` 可解释；ML/LLM 需 SHAP / LIME / PDP | 同上 §7 |
| A15 | **9 篇参考文献**（`ref/MediaTone/Literature/`） | 见下表 |

#### A3 关键词与文档填报量（原样引用，不作为已核实事实）

| 关键词 | 文档填报"IMF/实际爬取量" | 备注 |
|---|---|---|
| Transcript | 1872 | 原表列头为"IMF/实际爬取量"，且右侧两列为空 → **该列口径不明**，见 §8 缺口 G-05 |
| finance risk | 1421 | |
| cross-border finance | 1093 | |
| capital flow | 834 | |
| climate risk | 503 | |
| offshore market | 319 | |
| cross-border market | 291 | |
| offshore finance | 86 | |
| cross-border + capital flow | 13 | 样本量明显偏小，提示关键词过窄 `[建议·待复核]` |

#### A4 数据来源（表2 原文摘录，空列保持为空）

| 数据来源 | 媒体基调特性 | 境内基调 | 时间范围 | 样本量 | 爬取及处理难点 | 具体来源 |
|---|---|---|---|---|---|---|
| 中国政府网 | (中国)官方定调，通常是政策风向标 | 境内 | — | — | 重点关注标题与政策发布时间，官方语态非常稳定，适合作为基准线（Baseline） | http://big5.www.gov.cn/ |
| 巨潮资讯网 | (企业)财务信用定调，通过强制性财务信息披露 | 境内 | — | — | — | — |
| IMF | (全球)货币政策定调，宏观维度 | 境内外 | 1995-2026 | 6432 | 既有官方文章也有个人写的文章，需要分类处理 | https://www.imf.org/en/news |
| Bloomberg | (全球)主流外媒 | — | 1991至今（网站可爬） | — | 或耗时久，或继续攻克代码 | — |
| Refinitiv | — | — | — | — | — | — |
| 人民日报 | (中国)官方定调 | — | 暂时只爬了近一年 | 95202 | 三阶段的页面不同，关键词搜索模式难以就任 | — |
| 光明日报 | (中国)官方定调 | — | — | — | — | — |
| 中国经济网 | — | — | — | — | — | — |
| 证券时报 | — | — | — | 472 | 感觉文章数过少 | — |
| 21世纪报道 | — | — | — | — | — | — |
| google cloud | — | — | — | — | — | — |

> 英文来源正文另列：World Bank、Bloomberg、Refinitiv Real-time News、Google cloud。

#### A15 Literature 9 篇（仅登记题名，不概括其结论）

| 文件 | 题名线索 |
|---|---|
| `#JBF-Lehkonen_2025_Media tone predicts currency market#.pdf` | 媒体基调 → 汇率市场 |
| `#JFM-Bie_2025_LLM, news predict firm bankrupty.pdf` | LLM + 新闻 → 企业违约（被 Framework §4.1 两次作为示例引用） |
| `arXiv_2024_Zhang_Multimodal Foundation Agent for Financial Trading#.pdf` | 多模态金融交易 |
| `arXiv_2025_Cao_Predicting Financial Risk Using LLM based on Multimodal and Multi-Sources Data##.pdf` | 被 §5.4 引为 7 组消融的示例来源 |
| `RAS-Li_2025_News-based investor disagreementand stock returns#.pdf` | 新闻 → 投资者分歧 → 股票回报 |
| `大语言模型、文本情绪与金融市场_姜富伟.pdf` | 中文 |
| `媒体文本情绪与股票回报预测_姜富伟.pdf` | 中文 |
| `电话会议中高管语言风格与投资者市场反应_张光利.pdf` | 中文，语音/电话会议 |
| `系统性金融风险研究：现状、局限性与新路径框架——基于大语言模型应用视角_高尚.pdf` | 中文，综述 |

### 材料仍然空缺 / 尚未确立（本设计必须逐条接手）

> 下列空白是源文档**客观存在**的空表或未定项。本设计一律把它们变成**显式产品配置项**，不做硬编码。

| 编号 | 空白项 | 源文档证据 | 本设计的接手方式 |
|---|---|---|---|
| **G-01** | **指标定义 / 计算公式 / 经济含义三列全空** | 表3-1（Google Cloud 口径）表头"指标\|定义\|计算公式\|经济含义"，6 行 4 列，Media Tone/Postive Tone/Negative Tone 三行的后三列**全空**，另 2 行连指标名也空 | → §3.2 `MetricDefinition` 配置 + §3.3 公式定义 + §3.8 指标字典页 |
| **G-02** | **跨境金融资产价格表全空** | §3.2 正文只写了 stock / bond / exchange rate / crude oil 与一个孤立的 "index" | → §3.4 `AssetUniverse` 配置（标的清单 + 交易日历 + 时区），标的 ID 来自来源台账 |
| **G-03** | **金融预测变量表全空** | §3.3 "we incorporate xx financial predictors, detail in Table xx. xxxxx" | → §3.4 `PredictorSet` 配置；变量名沿用旧系统 `src/cbr/features/catalog.py` 的 `NUMERIC_FEATURES` 命名体系（见 §3.4 注） |
| **G-04** | **日度聚合规则未定** | "同一日同一指标多行数据，如何归纳为唯一的 Media Tone 指标。算均值？" | → §3.2 `DailyAggregationPolicy`（mean / recency_weighted / median / count_sum 四选一 + 半衰期） |
| **G-05** | **关键词表的"爬取量"列口径不明** | 表1 列头"IMF/实际爬取量"但右侧两列空；且 §5.4 提示"避免只写…泛称"（Excel 填写说明第 5 条） | → §3.4 `KeywordGroup` 显式声明 `scope`（IMF-only / 全源），并在 UI 标注口径 |
| **G-06** | **词典法没有词表** | 「思路二」只写"词典法等建模测度媒体基调（正向&负向，具体数值）" | → §3.6 词表版本管理（金融情感词典 + 事件词典 + 否定/程度处理） |
| **G-07** | **训练/验证/测试期未定** | §5 "training period from xxxx to xxx and xxxx. xxxx"；§5.1 "预测精度评价指标计算"无区间 | → §3.7 采用旧系统已验证切分：`train_end=2021-12-31 / valid_end=2023-12-31 / test=2024-01-01…`，标注 `[推定·待复核]` |
| **G-08** | **Google Cloud 情绪 API 的具体模型/版本/配额/成本未定** | 表2 仅"google cloud"一行且全空；表4"google cloud"获取过程空 | → §3.5 基线适配器接口 + §8 缺口（需账号/密钥/计费确认） |
| **G-09** | **Audio 模态的方法与数据均未定** | §4.2 "Audio analysis（其他非结构化模态数据分析）"全空；语音来源带"？" | → §6 标注为「采集与转写先行、声学特征留插件位」 |
| **G-10** | **§5.5 Prompt engineering for LLM 全空** | 该节只有标题 | → §3.9 `LlmScorer` 提示模板版本化（提示模板是配置，不是硬编码 prompt） |
| **G-11** | **§5.6 增量信息检验 / §5.7 样本外 / §6.2 / §8 Conclusion 全空** | 只有标题 | → §3.7 明确检验协议（统计量 + 检验方法 + 显著性门槛） |
| **G-12** | **经济含义（为什么基调影响跨境价格）未给出机制** | 表3-1/3-2 第三列全空 | → §1「研究问题」给出候选机制（信息传递 / 风险偏好渠道 / 政策预期渠道），标记为**待检验假设**而非结论 |
| **G-13** | **主资产、基准货币、收益口径（价格 vs 收益率 vs 对数收益）未定** | §3.2 只列资产类别 | → §3.4 `AssetUniverse` 必须显式声明 `return_def` |

---

## 方法设计

### 3.1 端到端流水线

```
[来源抓取 SourceCrawler]                    ← 真实抓取，运行时执行（基线 §4）
      │  raw_document(publish_time, source, lang, title, body, url, fetched_at)
      ▼
[解析与清洗 DocumentParser]                 ← parse / denoise / clean / filter（源文档 §4 预处理口径）
      │  clean_document(doc_id, ..., boilerplate_removed, lang, body_sha256)
      ▼
[PIT 有效日映射 PITDayMapper]               ← 继承旧系统 features/text.py 语义
      │  effective_trading_day(publish_time, source, calendar)
      ▼
[双轨打分 DualScorer]
      ├─ Track A: Google Cloud NL 情绪 API  → gc_score, gc_magnitude
      └─ Track B: 词典法 LexiconScorer      → lex_score, pos_score, neg_score
      ▼
[日度聚合 DailyAggregator]                  ← G-04：显式配置项
      │  media_tone / positive_tone / negative_tone（按 source_id × lang × keyword_group 分层）
      ▼
[特征层 FeatureBuilder]                     ← 数值特征（PredictorSet）+ 文本特征（tone）
      ▼
[建模与评价 ModelRunner]                    ← 3 类模型 × 7 组模态消融，滚动 windows=3 step=1
      ▼
[增量信息检验 + 可解释性 + 漂移检测]
```

### 3.2 指标定义与公式（接手 G-01、G-04）

**Dart 类**：`MetricDefinition`（id, name_cn, formula_id, economic_meaning, unit, range, source_doc_ref, version）

**公式定义（`FormulaId` 枚举，全部为可切换配置项，不硬编码）**：

设某日 `t` 的有效文档集合为 `D_t`（经 PIT 映射），文档 `d` 的词典打分为 `s(d)`（见 §3.6），权重 `w(d)` 由聚合策略给出：

| 公式 ID | 定义 | 表达式 | 经济含义（候选，需 §8 复核） |
|---|---|---|---|
| `F1_signed` | 有符号基调 | `MediaTone_t = (Σ_d w(d)·s(d)) / Σ_d w(d)`，取值 `[-1, 1]` | 净基调：净正/负情绪占全部命中强度的比例 |
| `F2_split` | 正负分离 | `PosTone_t = Σ_d w(d)·max(s(d),0) / Σ_d w(d)`；`NegTone_t = Σ_d w(d)·max(-s(d),0) / Σ_d w(d)` | 上涨/下跌压力各自的大小，可与 `F1` 交叉验证 |
| `F3_normalized` | 净比例 | `MediaTone_t = (PosTone_t - NegTone_t) / (PosTone_t + NegTone_t)` | 类"语调指数"，尺度与 Polity 类指标可比 `[建议·待复核]` |
| `F4_count` | 计数口径 | `PosTone_t = #(d: s(d)>0) / |D_t|`；`NegTone_t = #(d: s(d)<0) / |D_t|` | 稳健但丢强度信息，作为敏感性分析口径 |
| `F5_cloud` | Google Cloud 口径 | `MediaTone_t = mean_d(gc_score(d))`，`PosTone_t = mean_d(gc_score(d)·1[gc_score>0])` … | 基线轨口径，用于双轨一致性校验 |

> **注**：源文档表3-1 与表3-2 的"计算公式"列全空，本表是**本设计提出的候选公式集**，其取舍属 `[建议·待复核]`，需在 §7-M2 阶段由用户拍板后写入 `MetricDefinition`。

**`DailyAggregationPolicy`（接手 G-04）**：

| 字段 | 取值 | 默认 `[建议·待复核]` |
|---|---|---|
| `strategy` | `mean` / `recency_weighted` / `median` / `count_sum` | `recency_weighted`（当天多篇报道时新稿更重要） |
| `half_life_days` | 数值（仅 `recency_weighted` 用） | `2.0` |
| `min_docs` | 达到该文档数才输出 tone，否则为 null | `3` |
| `layering` | `by_source` / `by_source_and_lang` / `global` | `by_source_and_lang`（中英文基线必须分层，否则口径混用） |
| `null_policy` | `null`（缺数据即缺）/ `carry_forward` | `null`（**基线 §4 零 Mock：不允许用 0 冒充"没有新闻"**） |

**产品化含义**：以上每一项都是 **UI 上可改的设置项**，而不是代码里的常量。用户在「媒体基调控件」顶部切换口径 → 立即重算 → 重跑回测。

### 3.3 双轨打分与基线漂移检测（接手 G-08）

**Dart 类**：`DualScorer`（trackA: CloudNlScorer, trackB: LexiconScorer）、`CloudNlScorer`（adapter + 限流 + 重试 + 计费计数）、`LexiconScorer`

**漂移检测指标（全部落到具体指标名）**：

| 指标名 | 定义 | 阈值 `[建议·待复核]` | 触发后行为 |
|---|---|---|---|
| `tone_baseline_psi_cloud` | 月度 GC 分数分布相对基线月的 PSI | > 0.25 | UI 顶部黄条：「基线分布漂移，建议复核词表与 API 版本」 |
| `tone_track_agreement_spearman` | 逐日 GC 分数 vs 词典分的 Spearman ρ（滚动 60 日） | < 0.3 | 提示两轨背离，**不自动改词典** |
| `tone_track_divergence_rate` | `|gc − lex|` 超阈天数占比 | > 0.3 | 同上 |
| `tone_doc_coverage_rate` | 命中词典的文档数 / 有效文档数 | < 0.4 | 提示词表覆盖不足（新词/新说法） |
| `tone_oov_rate` | 未登录词占分词后 token 的比例 | 环比 +20% | 提示需要词表更新 |
| `tone_kw_group_volume` | 9 组关键词的日度文档量 | 某组连续 7 日为 0 | 提示该组抓取可能失效（对照 G-05：样本量 13 的 `cross-border+capital flow` 组） |

> **纪律**：漂移检测**只报警、不自动改配置**。任何词表改动都必须走 §3.6 的版本流程并留下审计记录（基线 §7 幂等写 + 证据链）。

### 3.4 输入与配置对象

| 配置对象（Dart class） | 内容 | 来源 |
|---|---|---|
| `AssetUniverse` | 跨境金融资产清单：标的 ID、资产类别（stock/bond/fx/crude）、市场、币种、交易日历、`return_def`（price / simple_return / log_return）、时区、`release_lag_days` | 接手 G-02 / G-13；标的 ID 与 `release_lag_days` 来自 `configs/sources.yaml` 风格的来源台账 |
| `PredictorSet` | 金融预测变量集合：变量名、来源 ID、频率、变换、方向 | 接手 G-03；命名沿用旧系统 `features/catalog.py` 的 `NUMERIC_FEATURES`（如 `market.cn_equity.csi300`、`market.fx.usdcny`、`market.global.vix`、`rates.credit.aa_spread`、`crossborder.flows.northbound_net`），便于旧新对照 |
| `KeywordGroup` | 9 组关键词：`group_id`（`transcript` / `finance_risk` / `cross_border_finance` / `capital_flow` / `climate_risk` / `offshore_market` / `cross_border_market` / `offshore_finance` / `cross_border_capital_flow`）、`terms`、`scope`（`imf_only` / `all_sources`）、`since` | 接手 G-05；`scope` 必须显式，因为表1 的"IMF/实际爬取量"列口径不明 |
| `SourceBinding` | 媒体源 ↔ 抓取器 ↔ 许可 ↔ 可达性 | 基线 §4 三档处理 |

**关键约束**：以上**全部为 JSON 配置**（基线 §2 推定：旧 yaml 不直接沿用），运行期读取，不硬编码在 Dart 源码里。

### 3.5 处理规则

| 环节 | 规则 | Dart 类 |
|---|---|---|
| 抓取 | 运行时真实抓取；持牌源无凭证时显式标注"需授权"；不可达源在来源台账列出原因 | `SourceCrawler` / `SourceLedger` |
| 解析 | HTML/PDF → 正文；去导航/版权/订阅墙残留 | `DocumentParser` |
| 降噪 | 样板句去除、重复稿去重（`body_sha256` + SimHash 近似去重）、URL 追踪参数剥离 | `DocumentCleaner` |
| 语言识别 | 中/英分别打标（双轨必须分层） | `LanguageTagger` |
| PIT 映射 | 政策类来源（央行/证监会/外管局/国务院）顺延到**下一个交易日**；财经媒体按 **15:00 收盘切点**，15:00 前当日可用、之后顺延次日 | `PITDayMapper`（继承 `src/cbr/features/text.py: effective_trading_day`） |
| 聚合 | §3.2 `DailyAggregationPolicy` | `DailyAggregator` |
| 缺失 | 无文档 → tone 为 `null`（不是 0）；`tone_doc_count` 保留以区分"无新闻"与"抓取失败" | — |

> **PIT 纪律**：第 t 行的任何 tone 值，只能由 `effective_trading_day ≤ t` 的文档构成。

### 3.6 词表版本管理（接手 G-06）

**三层词表**：

| 层 | Dart 结构 | 内容 |
|---|---|---|
| 金融情感词典 | `LexiconVersion.entries[positives] / [negatives]` | 词 + 权重（连续值）+ 适用领域（`policy` / `market` / `corporate` / `macro`） |
| 事件词典 | `LexiconVersion.events[]` | `event_id`、触发词表、方向（`risk_on`/`risk_off`）、强度、传导渠道（`fx`/`rates`/`equity`/`credit`/`capital_flow`/`commodity`）、`source`（权威出处） |
| 否定/程度处理 | `NegationRule` / `DegreeRule` | 否定词表、否定作用域窗口 `negation_scope`（token 数）、程度词表与乘子 `degree_multiplier` |

**打分公式（词典轨）**：

```
s(doc) = Σ_i  w(term_i) · m(deg_i) · (1 − λ · neg_i)  +  Σ_j  ev_dir_j · ev_w_j
```

- `w(term_i)`：词权重；`m(deg_i)`：程度词乘子（默认 1.0）；`neg_i ∈ {0,1}`：命中否定词（作用域内）；`λ`：否定惩罚系数（默认 1.0，可配置）；`ev_*`：事件词典贡献（按事件类型去重计数，避免同事件多词重复计分）。

**版本管理**：

| 机制 | 规则 |
|---|---|
| 版本号 | `lexicon_vYYYYMMDD_n`；每次发布计算全表 `sha256`，写入 `LexiconVersion.hash` |
| 生效范围 | 每条打分结果落库时带 `lexicon_version`；改版**不回溯重算**历史（回溯需显式执行 `recompute(range, from_version)`，产出新的 run_id） |
| 差异审计 | `LexiconDiffView` 展示两版之间的新增/删除/改权重条目数与逐条 diff；来源与理由必填 |
| 校验 | `lexicon.validate` 工具：检查重复词、冲突词（同一词同时在正负表）、缺权重、事件词典缺 `source` |
| 词表来源 | 词条必须带 `source`（公开词典出处 / 自建并注明理由）；**不得引用不存在的文献** |

**与 R2 的关系**：R1 的词典轨是"可解释基线"，R2 的 LLM 轨是"上下文轨"。两轨结果并列展示，不互相覆盖。

### 3.7 模型与评价协议

**三类模型（对应 A10）**：

| 家族 | Dart 侧实现 | 说明 |
|---|---|---|
| 计量经济学 | `ArdlModel`（OLS + Newey-West 稳健标准误，滞后阶数由 AIC/BIC 选） | 保留 `Y = b1*X1 + b2*X2` 的可解释结构（A14）；系数表进 UI |
| 机器学习 | `SklearnLikeEnsemble` → **Dart 侧手写 GBDT / 或调用外部训练产物**（见下注） | 源文档列 NN、LSTM、决策树/集成（随机森林）、SVM 等"数10种" `[建议·待复核：首版取子集]` |
| LLM | `LlmScorer`（DeepSeek 走 `genkit_openai`） | 提示模板版本化（G-10），输出打分与理由；成本按基线 §7.7 折算 `J = L + μ·C` |

> **实现边界提示**：Dart 生态缺少成熟的 XGBoost/LightGBM 绑定（基线 §2 推论已指出旧项目 XGBoost 需在 Dart 侧重实现或替换）。首版建议：**GAM/岭回归/Lasso（可手写）+ 树模型以"训练期离线产出 → 落 JSON 权重 → Dart 侧只做推理"的方式接入**，不在 Dart 侧做完整 GBDT 训练。`[推定·待复核]`

**评价协议（接手 G-07、G-11）**：

| 项 | 设定 | 依据 |
|---|---|---|
| 切分 | train `≤ 2021-12-31` / valid `2022-01-01…2023-12-31` / test `2024-01-01…2025-09-30` | 旧系统 `labels.py: time_split` 与 `StudyConfig` 已用同一口径 `[推定·待复核]` |
| 滚动窗口 | `windows = 3`（每个测试窗口 3 个交易日），`step = 1`；窗口数上限 300（源文档图示） | A11 |
| 目标 | 未来 h 交易日收益率或价格水平（由 `AssetUniverse.return_def` 决定） | G-13 |
| 主指标 | MSE、RMSE、R² | A11 |
| 增量信息检验 | ① 嵌套模型 F 检验（加入 tone 后是否显著）；② 样本外损失差的 Diebold–Mariano 检验（数值 vs 数值+tone）；③ 增量 R² `ΔR² = R²_full − R²_numeric` | A11/A14 + §5.6 |
| 样本外 | **扩展窗口**：训练样本截止 `t − h`；任何标准化参数（均值/方差、winsorize 边界）只在训练期估计并冻结 | 旧系统 `models/signal.py` 滚动快照语义 |
| 显著性 | 主期限上 `p < 0.05` 且 DM 方向一致（数值+tone 损失更小）方记为"有增量" | 不显著不得写成显著 |
| 可解释性 | SHAP（树模型/线性模型精确值；LLM 用置换近似）、LIME、PDP | A14 |
| 多重比较 | 资产 × 期限 × 模型族的组合数大 → 用 Holm 校正，并预先声明主终点（`[建议·待复核]`） | 防止"扫出显著性" |

**Prompt engineering（接手 G-10）**：`LlmScorer` 使用版本化提示模板 `prompt_v1`（系统提示 + 输出 JSON schema：score / evidence_spans / uncertainty）。模板文件与词典同版本体系管理；JEV 判断层做证据核验（基线 §2 JEV 适配）。

### 3.8 输出产物

| 产物 | 关键字段 |
|---|---|
| `ToneSeries` | `date, media_tone, positive_tone, negative_tone, doc_count, source_id, lang, keyword_group, formula_id, aggregation_policy_id, lexicon_version, scorer_version, as_of` |
| `ToneFeature`（进入特征矩阵） | `tone_media`, `tone_pos`, `tone_neg`, `tone_dispersion`（日内分数标准差）、`tone_source_entropy`、`tone_rolling_5d`, `tone_rolling_20d` |
| `ToneBacktestResult` | `asset_id, horizon, model_family, modality_set, window_start, window_end, mse, rmse, r2, n_train, n_test` |
| `ToneIncrementalityResult` | `asset_id, horizon, delta_r2, dm_stat, dm_p, f_stat, f_p, holm_adjusted_p, verdict` |
| `ToneExplainResult` | `feature, shap_mean, shap_abs_mean, lime_weight, pdp_points, global_rank` |
| `ToneDriftReport` | §3.3 全部指标的时间序列 + 当前告警项 |

---

## 数据依赖

### 4.1 从 `ref/数据汇总统计表-简化版(1).xlsx`（`数据来源汇总` 表）映射

> 事实：该表 35 行中，**只有第 1 行（中国人民银行）填报了"预计数据量 3000 / 实际获取数据量 1200 / 规模 300MB"**，其余 34 行的"预计数据量 / 实际获取数据量 / 规模"**全为空**。因此本节列出的所有"量级"均为**待核实**，运行期由 App 实际采集统计（基线 §4 推定）。

| Excel 序号 | 模态 | 来源 | 时间范围 | 本研究域用途 | 公开 / 持牌 |
|---|---|---|---|---|---|
| 1 | 文本·政策监管 | 中国人民银行 | 2015.01.01—2024.12.31（季度） | 政策基调（与 MediaTone 的"官方定调"轨呼应） | **公开** |
| 2 | 文本·政策监管 | 美国联邦储备系统 | 2015—2024 | 境外政策基调 | **公开** |
| 3 | 文本·国际机构 | 国际货币基金组织（IMF） | 2015—2024（半年/发布日） | 源文档表1、表2 的主抓取对象 | **公开** |
| 4 | 文本·全球财经新闻 | Bloomberg News | 2015—2024 | 英文基调轨 | 持牌付费 |
| 5 | 文本·全球财经新闻 | LSEG / Refinitiv News | 2015—2024 | 英文基调轨（备选） | 持牌付费 |
| 6 | 文本·财经媒体 | The Wall Street Journal | 2015—2024 | 英文深度基调 | 持牌付费（付费墙） |
| 7 | 文本·投资者评论 | 雪球 | 2010—2024 | 中文市场情绪补充轨 | 公开（需合规） |
| 8 | 文本·投资者评论 | X（原 Twitter） | 2010—2024 | 境外投资者情绪轨 | 公开（需合规） |
| 9 | 文本·企业披露 | 香港交易所披露易 | 2015—2024 | 发行人信用定调 | 公开 |
| 10 | 文本·风险事件 | Bloomberg Intelligence | 2015—2024 | 信用事件（可做事件词典校验） | 持牌付费 |
| 11 | 语音·财报电话会议 | Wind 3C 会议数据库 | 2012—2024 | Audio 模态（**本代仅转写**） | 持牌付费 |
| 12 | 语音·财经音频 | Bloomberg TV | 2012—2024 | Audio 模态（**本代仅转写**） | 持牌付费 |
| 13 | 语音·央行沟通 | 美国联邦储备系统 | 2015—2024 | 政策发布会语音（**本代仅转写**） | 公开（音频可得性待核实） |
| 14 | 语音·央行沟通 | 欧洲中央银行（ECB） | 2015—2024 | 同上 | 公开（音频可得性待核实） |
| 15 | 语音·国际政策会议 | OPEC | 2015—2024 | 能源政策语调 | 公开（音频可得性待核实） |
| 26 | 数值·跨境资金流 | Wind 终端（沪深港通北向/南向） | 2014—2024（日/分钟） | **Numeric 模态核心**；北向 2024-08 后停披露 → 需 regime dummy（承接旧系统 `features/numeric.py` 的"北向披露缺失标记"） | 持牌付费 |
| 27 | 数值·跨境债券 | Bloomberg Terminal（中资离岸债） | 2006—2024（日/分钟/Tick） | 债券类被解释变量 | 持牌付费 |
| 28 | 数值·外汇及利率 | LSEG / Refinitiv（USDCNH 等） | 1986—2024 | 汇率类被解释变量 | 持牌付费 |
| 29 | 数值·企业财务 | CSMAR | 2000—2024（年/季） | 预测变量（杠杆/流动比率/到期债务） | 持牌付费 |
| 30 | 数值·跨境企业特征 | Bloomberg Terminal | 1986—2024 | 预测变量（规模/行业/注册地/违约率/币种错配） | 持牌付费 |
| 31 | 数值·跨境产品发行 | Bloomberg Terminal | 1986—2025 | 发行条款/评级/期限 | 持牌付费 |
| 32 | 数值·美国宏观金融 | FRED | 2000—2024 | 预测变量（UST5Y、期限结构、通胀、金融条件） | **公开** |
| 33 | 数值·全球宏观经济 | World Bank Data | 2000—2024 | 预测变量（GDP、贸易开放度、资本流动、对外债务） | **公开** |
| 34 | 数值·跨境收支统计 | 国家外汇管理局 | 2000—2024（月/季/年） | 预测变量（国际收支、结售汇） | **公开** |
| 35 | 数值·金融波动指标 | Cboe（VIX） | 2000—2024（日） | 预测变量（市场隐含波动） | 公开（许可需核实） |

**取用矩阵（本研究域需要的最小集）**：

| 用途 | 必需来源 | 缺失时的降级 |
|---|---|---|
| 被解释变量（股票/债券/汇率/原油） | 27、28（+ 26 作汇率/权益代理）、35 | 只能用 32/33 宏观代理，结论降级为"宏观资产"而非"跨境资产" |
| 数值预测变量（Numeric 基线） | 26、32、33、34、35 | 无法做增量信息检验（没有 Numeric 基线）→ **结论不成立** |
| 文本轨（Text） | 3（IMF）+ 1/2（政策）+ 9（披露）+ 4/5（英文新闻，持牌） | 仅有中文轨时，`tone_track_agreement_spearman` 不可算 |
| 音频轨（Audio） | 11、12（持牌）+ 13/14/15（公开音频） | 本代仅转写；无音频时 7 组消融中 3 组（含 Audio）**标记为"未运行"而非"无差异"** |

**"无 mock"纪律**：本研究域的任何数字、任何 tone 值、任何图表，**只能来自上表来源的真实抓取结果**。无凭证时：UI 显示"需授权"占位（基线 §4 第 2 档），**不显示 0、不显示插值、不显示上一日值冒充当期**。

### 4.2 许可与合规

| 来源 | 许可状态（据 `ref/技术工具/4 多模态数据来源汇总.xlsx` 的"许可协议"列） | 备注 |
|---|---|---|
| 中国政府网 / 财政部 / 外汇局 / 人民银行 | 政府公开信息许可 / 非商业用途可合理使用 | 可抓 |
| 证券时报 | 非商业用途可引用 | 可抓 |
| 巨潮资讯 / 上交所 | 上市公司公开披露信息 | 可抓（详情页可能需手动下载） |
| IMF | 公开数据可自由引用 | 可抓 |
| 美联储理事会 | 无版权 | 可抓 |
| 东方财富 / 同花顺 / 财新 | 非商业用途 | **学术研究用途需再确认** |
| 慧博投研 | 免费版仅摘要，反爬严 | 需凭证 |
| Wind / Bloomberg / LSEG / CSMAR / Wind 3C | 商业授权 | 用户提供凭证的适配器 |
| 英为财情 investing.com | 表中明示"禁止爬取…敏感目录" | **只抓公开新闻文本，不碰图表/后台** |

> **合规红线**：`4 多模态数据来源汇总.xlsx` 中"蜻蜓 FM"一行写有"模拟真实浏览器，注入反检测脚本绕过自动化识别"。**本设计不采纳任何绕过反爬的手段**；仅使用公开 API、公开页面、站点许可的下载通道。抓取频率与礼貌性延迟必须配置化并遵守站点条款。

---

## 产品化形态

### 5.1 屏幕与路由

| 路由 | 屏幕 | 用途 |
|---|---|---|
| `/research/r1/media-tone` | **媒体基调工作台**（主屏） | 选资产 / 选口径 / 看 tone 曲线 / 看两轨一致性 / 看漂移告警 |
| `/research/r1/metric-dictionary` | **指标字典编辑器** | 编辑 `MetricDefinition`（定义/公式/经济含义/版本），落地 G-01 |
| `/research/r1/lexicon` | **词表版本管理** | 版本列表、diff、校验、发布、回溯重算 |
| `/research/r1/ablation` | **消融实验编排** | 7 组模态 × 3 类模型 × 滚动窗口，产出主表 |
| `/research/r1/incrementality` | **增量信息检验报告** | ΔR² / DM / F 检验 / Holm 校正 / 结论卡 |
| `/research/r1/explain` | **可解释性** | SHAP / LIME / PDP |

### 5.2 组件（Widget）

| Widget | 职责 | 关键参数 |
|---|---|---|
| `ToneSparkline` | 三条 tone 曲线（media/pos/neg）+ 缺失日留空 | `series`, `formulaId`, `showMissingAsNull` |
| `ToneAgreementGauge` | 双轨一致性（ρ + 分歧率 + 散点） | `trackA`, `trackB`, `window` |
| `ToneDriftBanner` | 漂移告警条（黄/红） | `ToneDriftReport` |
| `AblationMatrixTable` | 7 组 × 3 模型的主指标热力表 | `ToneBacktestResult[]` |
| `IncrementalityCard` | 单资产单期限的增量结论卡（含 p 值与 Holm 校正） | `ToneIncrementalityResult` |
| `LexiconDiffView` | 两版词表差异 | `fromVersion`, `toVersion` |
| `MetricDefinitionForm` | 指标字典编辑表单（三列 + 公式下拉 + 经济含义） | `MetricDefinition` |
| `PITTimeline` | 交易日历 + 发布滞后可视化 | `SourceBinding` |

### 5.3 Agent 角色与工具

| 角色 / 工具 | 职责 | 风险级别 |
|---|---|---|
| Agent：`研究编排员`（Research Orchestrator） | 按用户意图生成实验配置（资产集合、窗口、口径、模态组合），调用工具跑批 | L1（写实验产物） |
| Agent：`数据质量审计员`（Data QA） | 检查词表命中率、两轨分歧、抓取失败率、缺失日分布，出具审计报告 | L0 |
| Agent：`证据核验员`（Evidence Verifier / JEV） | 核验 LLM 轨打分所引用的原文片段是否真实存在、时间戳是否早于 `as_of` | L0 |
| 工具 `media_tone.compute` | 按 `MetricDefinition` + `DailyAggregationPolicy` + `LexiconVersion` 计算日频 tone | L1 |
| 工具 `media_tone.explain` | 返回某日 tone 的 Top-K 贡献文档与片段（证据链） | L0 |
| 工具 `tone.drift_check` | 运行 §3.3 全部漂移指标 | L0 |
| 工具 `lexicon.validate` | 词表一致性校验（重复/冲突/缺权重/缺来源） | L0 |
| 工具 `lexicon.diff` | 两版差异 | L0 |
| 工具 `ablation.run` | 跑 7 组消融并返回主表 | L1 |
| 工具 `incrementality.test` | 跑增量信息检验（ΔR² + DM + Holm） | L1 |

> **证据链要求（基线 §7.2）**：`media_tone.explain` 返回的每条结论必须能回指到 `doc_id + 原文片段 + 发布时间`。LLM 轨必须由 JEV 核验后才能进入最终判定。

### 5.4 用户实际做什么

1. **设定基线**：在「指标字典」里确认 Media Tone 的公式与经济含义（此前为空），选定聚合口径与词表版本。
2. **盯数据质量**：看「漂移告警条」与「覆盖率」，发现某来源抓取断了或词表过期。
3. **跑实验**：选 1–3 个跨境资产、选 7 组模态、选三类模型，点"开始"，等滚动窗口跑完。
4. **读增量信息**：在「增量信息检验报告」看"媒体基调相对数值变量是否有增量"，含 p 值与多重比较校正后的结论。
5. **读解释**：在「可解释性」看 tone 是正向还是负向驱动、PDP 是否单调。
6. **把结论交给 R4**：带证据片段与 `as_of` 的 tone 结论，作为多智能体判定的输入之一。

---

## 消融与可证伪性

### 6.1 7 组模态消融（源文档 §5.4，已定）

| 组 | 模态集合 | 本代可运行性 | 说明 |
|---|---|---|---|
| A1 | Numeric | ✅ | 依赖持牌数值源；无凭证时显式"需授权" |
| A2 | Text | ✅ | 双轨（词典 + LLM） |
| A3 | Audio | ⚠️ 仅转写 | 本代做转写与文本化；**声学特征（语速/停顿/音高/抖动/说话人切换）留插件位**；未实现时该组标"未运行" |
| A4 | Numeric + Text | ✅ | 主对照组 |
| A5 | Numeric + Audio | ⚠️ | 同 A3 限制 |
| A6 | Text + Audio | ⚠️ | 同 A3 限制 |
| A7 | Text + Audio + Numeric | ⚠️ | 全模态组；A3 未落地前不可比 |

**诚实标注**：A3/A5/A6/A7 在本代**不产出结论**，只能在 UI 上显示"待音频特征插件"。源文档 §5.4 引用了 Cao et al. (2025) RiskLabs 作为示例来源，**该论文的具体实验数值不作为本项目的任何预期值**。

### 6.2 消融矩阵（完整）

| 维度 | 取值 | 作用 |
|---|---|---|
| 模态组合 | 上述 7 组 | 模态增量 |
| 模型族 | 计量 / ML / LLM | 方法排序 |
| 目标 | 价格水平 / 简单收益 / 对数收益 | 口径敏感性 |
| 资产 | `AssetUniverse` 全集 | 跨资产稳健性 |
| 期限 | 短期 / 中期 / 长期（按 `h` 网格，源文档图示 1..300） | 期限结构 |
| 公式 | `F1_signed` / `F2_split` / `F3_normalized` / `F4_count` / `F5_cloud` | 口径敏感性 |
| 聚合 | `mean` / `recency_weighted` / `median` / `count_sum` | 聚合敏感性 |
| 词表版本 | 至少 2 个版本 | 词表敏感性 |
| 切分 | 固定切分 + 滚动起点扰动 | 切分敏感性 |

### 6.3 可证伪性：什么结果会推翻假设

| 假设 | 表述 | 证伪条件（预注册） |
|---|---|---|
| **H1 增量预测力** | 媒体基调相对数值变量对跨境资产有增量预测力 | 在**主期限**上 `ΔR² ≤ 0` **且** DM 检验 `p ≥ 0.05`（Holm 校正后）→ 判为"无增量" |
| **H2 模型族排序** | LLM > ML > 计量 | 三类模型在主设定下 RMSE 排序反转 → 判为"排序不成立"，如实报告 |
| **H3 全模态最优** | 全模态优于任一子集 | A7 不优于 A4（Numeric+Text）→ 判为"多模态无增益" |
| **H4 双轨一致** | 词典轨与 GC 轨刻画同一现象 | 滚动 60 日 `tone_track_agreement_spearman` 持续 < 0.3 → 判为"两轨刻画不同现象"，需分别报告 |
| **H5 基线稳定** | 词表与打分口径在样本期内稳定 | `tone_baseline_psi_cloud > 0.25` 连续 2 个月 → 判为"基线漂移"，结论只对漂移前区间有效 |
| **H6 事件窗口有效** | 媒体基调在压力事件窗口内显著更负 | 压力事件窗口 vs 平静窗口的 tone 差异不显著 → 判为"无事件区分度" |

> 每条假设都必须在 `artifacts/research/R1/<run_id>/` 里留下**预注册文档**（开跑前写入），防止事后挑选口径。

---

## 里程碑与验收

| 阶段 | 内容 | 验收标准（可执行） | 依赖 |
|---|---|---|---|
| **M0 口径拍板**（无代码） | 确认 `MetricDefinition` 三列、公式集、聚合策略、`AssetUniverse` 初版、`PredictorSet` 初版 | ① 指标字典 3 条 × 4 字段全填；② 公式 ID 与表达式的单元测试通过；③ 资产清单含 ≥1 个股票、≥1 个汇率标的 | 用户拍板（G-01/G-02/G-03/G-04） |
| **M1 采集管线** | `SourceCrawler` + `DocumentParser` + `PITDayMapper` + 来源台账 | ① ≥3 个公开中文源 + ≥1 个公开英文源连续跑通 30 日；② 每篇文档有 `publish_time` 与 `effective_trading_day`；③ 抓取失败在台账显式列出原因；④ **零 mock**（无凭证时显示"需授权"） | 抓取可达性 |
| **M2 双轨打分** | `LexiconScorer` + `CloudNlScorer` + 词表 v1 + 日度聚合 | ① 词表 ≥300 条并带来源，`lexicon.validate` 通过；② 输出 `ToneSeries` 且缺失日为 null；③ 两轨 Spearman ρ 与分歧率可算并入 `ToneDriftReport` | GC 凭证（G-08） |
| **M3 建模与回测** | 3 类模型 + 7 组消融 + 滚动 `windows=3 step=1` | ① 主表完整（每个单元有 n_train/n_test）；② 扩展窗口样本外（训练样本 `≤ t−h`）；③ 标准化参数只在训练期估计 | 数值源凭证 |
| **M4 增量 + 解释 + 漂移** | 增量信息检验 + SHAP/LIME/PDP + 漂移面板 | ① 增量检验给出 ΔR²/DM/F 检验与 Holm 校正 p 值；② 结论卡显式写"有/无增量"；③ 漂移告警可触发 | M2+M3 |
| **M5 产品化收口** | Flutter 屏 + Agent + 工具 + 审计 trace | ① 6 个屏幕可用；② `media_tone.explain` 每条结论带原文片段 + 时间戳；③ JEV 核验通过率 100%（无未核验结论进入判定） | M4 |

**不做的事（明确排除）**：不在本代实现本地声学特征模型；不虚构任何论文结论作为对照基准；不在缺凭证时以任何形式填充数据。

---

## 风险与缺口

| 编号 | 风险 / 缺口 | 影响 | 应对 | 状态 |
|---|---|---|---|---|
| G-01 | 指标定义/公式/经济含义三列全空 | 无法定义主变量 | §3.2 提出候选公式集，M0 拍板 | `[待定]` |
| G-02 | 跨境金融资产清单全空 | 无法定义被解释变量 | `AssetUniverse` 配置化；标的来自来源台账 | `[待定]` |
| G-03 | 金融预测变量表全空 | 无法做增量信息检验 | `PredictorSet` + 沿用旧系统特征命名 | `[待定]` |
| G-04 | 日度聚合规则未定（"算均值？"） | 口径不可复现 | 4 种策略全配置化 + 敏感性消融 | `[待定]` |
| G-05 | 表1"爬取量"列口径不明（"IMF/实际爬取量" + 空列） | 关键词组样本量可能被误读 | `KeywordGroup.scope` 显式声明；UI 标注口径 | `[待定]` |
| G-06 | 词典法无词表 | 双轨打分不可实现 | §3.6 词表版本管理，v1 需人工构建并标注来源 | `[待定]` |
| G-07 | 训练/验证/测试期未定 | 结果不可比 | 沿用旧系统口径 `[推定·待复核]` | `[推定]` |
| G-08 | GC 情绪 API 的模型版本、配额、成本、密钥未知 | 基线轨可能不可用 | 适配器接口 + 无凭证降级；**双轨任一轨不可用时，另一轨单独报告并标注** | `[待定]` |
| G-09 | Audio 模态方法与数据均未定 | 4/7 组消融不可运行 | 本代仅转写；声学特征留插件位 | `[已定·分期]` |
| G-10 | §5.5 Prompt engineering 全空 | LLM 轨不可复现 | 提示模板版本化 + 证据链核验 | `[待定]` |
| G-11 | §5.6/5.7/6.2/8 全空 | 增量与样本外无原文协议 | §3.7 给出预注册协议 | `[建议·待复核]` |
| G-12 | 经济机制未在材料中论证 | tone 与价格的因果链无原文支撑 | 作为待检验假设写入 §1，不写成结论 | `[待定]` |
| G-13 | 收益口径（价格 vs 收益）未定 | 指标不可比 | `AssetUniverse.return_def` 显式声明 | `[待定]` |
| G-14 | 35 行数据源中仅 1 行填报了数据量 | 无法预估采集工期与成本 | 运行期实际统计（基线 §4）；M1 产出来源台账快照 | `[已定]` |
| G-15 | 持牌源（Bloomberg / LSEG / Wind / CSMAR / Wind 3C）占绝大多数关键资产与数值变量 | 无凭证则主结论不成立 | UI 显式"需授权"；提供公开源（IMF / 美联储 / FRED / World Bank / SAFE / 港交所）作为最小可行子集 | `[已定·零 Mock]` |
| G-16 | 北向资金 2024-08 后停披露 | Numeric 基线结构性断裂 | regime dummy + 特征可用性标记（承接旧系统做法） | `[已定]` |
| G-17 | 文献 9 篇 PDF 未逐篇解析 | 无法引用其结论 | 本文档只登记题名；**引用前必须逐篇读原文并标注页码** | `[待定]` |
| G-18 | Dart 侧缺少成熟 GBDT 绑定 | ML 家族实现受限 | 岭/Lasso/GAM 手写；树模型走"离线训练 → JSON 权重 → Dart 推理" | `[推定·待复核]` |
| G-19 | 双轨打分本身可能有系统性偏差（如官方媒体语态稳定 → 作 Baseline） | 词典轨对官方源偏置 | 官方源单列一条轨，不与媒体源混合聚合 | `[建议·待复核]` |
| G-20 | 多重比较 | 易扫出"假显著" | Holm 校正 + 预注册主终点 | `[建议·待复核]` |
