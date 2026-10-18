# CBR-MAW 多智能体协同风险预警系统 · 架构设计 v0

> 论文：跨境金融风险的多智能体协同预警：多模态信息融合视角（方向2）
> 交付：① 可运行演示原型（Web 驾驶台） ② 技术文档第四章 ③ 供 kk 录屏的演示脚本/使用说明
> 截止：2026-10-23（周五）
> 状态：v0 待与用户对齐（2026-10-18）

---

## 0. 一句话定位

**以"跨境金融市场压力高位状态"为唯一共同预警目标，让三类主体智能体在共享的风险信号与证据黑板上分工、互验、协调，所有数值由确定性金融工具计算、所有结论可溯源、所有协同过程可审计、可消融。**

即：**确定性金融工具算数 + LLM 智能体编排解释 + 证据链核验 + 配置化消融实验**。

这篇论文/系统的学术卖点不是"能生成三类报告"，而是：
- P1：多模态（数值—文本）信息带来增量预警能力；
- P2：知识检索 + 专业工具让预警数值可复核、结论有依据；
- P3：专业化分工 + 证据共享 + 分歧协调在**可比资源预算**下降低预警与主体决策损失。

因此工程架构必须天然支持：**时点回放、逐项消融、资源预算对齐、证据可追溯、数字可重算**。

---

## 1. 五条设计原则（架构的约束条件）

| # | 原则 | 直接服务的论文章节/命题 |
|---|------|--------------------------|
| 1 | **单一风险锚**：所有 agent 共享同一基础风险信号（P(高压力@5/10/20日) + 驱动因子归因），角色差异只体现在目标函数、信息/工具权限、阈值、输出与决策损失 | 3.1、4.1、4.3；P1/P3 可比性 |
| 2 | **数值不由 LLM 生成**：所有数值来自版本化工具/模型；LLM 只做任务规划、工具选择、结果解释与比较；每条数值主张绑定 `evidence_id` 并可重算 | 4.2；P2 |
| 3 | **证据是一等数据结构**：统一 Evidence / Claim schema + 证据黑板 + 来源时点戳；文本证据强制 `publish_time <= as_of` | 4.2、4.4、5.1；P2 |
| 4 | **协同是可开关、可消融的模块**：单智能体 / 三个独立智能体 / 完整协同用同一代码路径、不同配置实现，统一工具调用与 token 预算 | 5.2、4.4；P3 |
| 5 | **时点回放是一等公民**：所有数据访问统一走 as-of 接口；实验、演示、生产用同一套数据接口，从架构上杜绝未来信息泄漏 | 5.1、6.4 |

---

## 2. 总体架构（六层 + 两条横切）

```
┌────────────────────────────────────────────────────────────────────────────┐
│ L6 决策支持与演示层（Web 驾驶台 / API / 报告导出）                            │
│   时间轴回放 · 风险仪表盘 · 三智能体卡片 · 证据板 · 分歧面板 · 审计轨迹 · 实验模式 │
├────────────────────────────────────────────────────────────────────────────┤
│ L5 协同编排层（Coordinator / Task Router / Blackboard / HITL）               │
│   R0 独立分析 → R1 证据共享 → R2 交叉验证 → R3 分歧识别 → R4 协调仲裁 → R5 决策卡 │
├────────────────────────────────────────────────────────────────────────────┤
│ L4 智能体层（监管 Agent │ 投资 Agent │ 融资 Agent）                           │
│   RoleSpec(目标/信息权限/工具权限/阈值/输出 schema/损失权重) · Agent Loop · RiskCard │
├────────────────────────────────────────────────────────────────────────────┤
│ L3 知识与工具层（RAG · 风险测度 · 连通性 · 情景分析 · 预测 · 融资成本）          │
│   工具注册表 + 权限矩阵 + 输入输出指纹 + 版本号 + 时点过滤的知识库               │
├────────────────────────────────────────────────────────────────────────────┤
│ L2 多模态融合层（数值特征 │ 政策/新闻文本特征 │ 融合预测器 + 模态贡献归因）       │
├────────────────────────────────────────────────────────────────────────────┤
│ L1 数据与时点层（采集 → 对齐校验 → Point-in-time Store：DuckDB + Parquet）       │
└────────────────────────────────────────────────────────────────────────────┘
  横切 A｜验证与审计层：数值核验 · 引文溯源 · 时点核验 · 越权阻断 · schema 校验 · trace
  横切 B｜实验与评估层：配置化消融 · 时点回放 · 指标 · 统计检验 · 运行注册表
```

**分层理由**：L1/L2 对应论文第三节与 4.1，L3 对应 4.2，L4 对应 4.3，L5 对应 4.4，横切 A 对应 4.4 的"核验闭环"与 5.3 的 P2 指标，横切 B 对应第五节全部实验设计。技术文档第四章按这个结构展开即可。

---

## 3. 模块设计

### 3.1 L1 数据与时点层（Data & Point-in-Time）

**数据域划分**

| 域 | 内容（首选公开源） | 频率 | 用途 |
|----|--------------------|------|------|
| 中国市场 | 沪深300、中证500、国债收益率曲线、信用利差、成交/换手 | 日 | 压力指数、VaR/CVaR、标签 |
| 跨境资金 | 沪深港通北向/南向资金流、持仓、成交、AH 溢价 | 日 | 异常资金流、同步撤离 |
| 全球因子 | 标普500、VIX、MOVE、美元指数、USDCNY/CNH、中美利差 | 日 | 外部冲击、溢出 |
| 宏观 | PMI、社融、外储、政策利率 | 月/日 | 背景变量 |
| 文本 | 央行/证监会/外管局/国务院政策文本、财经新闻标题、GDELT 事件 | 日/事件 | 多模态文本模态 |

**Point-in-time 存储**

```sql
-- pit.duckdb 核心表
series_obs(series_id, obs_date, value, release_time, source, revision, unit)
documents(doc_id, publish_time, source, title, body, url, hash)
evidence(...)  -- 运行时生成，见 L5
```

- 统一入口 `PitStore.asof(series_id, as_of) -> DataFrame`：只返回 `release_time <= as_of` 的记录；
- 文本检索强制 `publish_time <= as_of`（RAG 层再校验一次，双保险）；
- **数据卡（data card）**：每个序列记录覆盖期、频率、缺失、修订、口径、时点可得性评级（严格/近似/不可得）；
- **风险标签构造（可替换，服务稳健性 6.4）**：跨境金融压力指数（股/债/汇 + 信用利差 + 跨境资金 + 全球波动，PCA 或分位复合）→ 滚动分位阈值定义"高位状态"（如 top 10%/15%）→ 标签 `y_{t+h} ∈ {0,1}`，h∈{5,10,20} 交易日；标签版本号写入配置。

### 3.2 L2 多模态融合层（Multimodal Fusion）

```
数值分支：行情/资金/宏观 → 特征(收益、波动、利差、异常资金流 z、同步性、集中度) → LASSO/Logit/XGBoost 基线
文本分支：政策/新闻 → 时点过滤 → 事件/情绪/主题(政策不确定性、资本管制、外部冲击) → 文本特征
融合：早期/晚期融合对比 → 融合预测器（输出概率 + 模态贡献归因）
```

**统一输出（所有角色的共同输入）**

```json
{
  "as_of": "2024-08-05",
  "signal_version": "fusion-xgb-v1",
  "prob_high_stress": {"h5": 0.12, "h10": 0.28, "h20": 0.41},
  "percentile": 0.86,
  "drivers": [{"factor": "northbound_outflow_z", "contribution": 0.31}, ...],
  "modality_contrib": {"numeric": 0.72, "text": 0.28},
  "evidence_id": "ev_sig_20240805_v1"
}
```

- 该信号写入证据黑板，三个 agent 引用同一 `evidence_id`（保证 P3 可比、P1 可消融）；
- P1 消融：`numeric-only` vs `numeric+text`，样本外滚动评估（PR-AUC、召回、校准、提前期）。

### 3.3 L3 知识与工具层（Knowledge & Tools）

**知识库（KB）**

- 内容：监管政策、跨境资本管理规则、金融风险方法学定义（VaR/CoVaR/DY 溢出）、历史压力事件复盘、指标口径说明；
- 切块（chunk）级元数据：`{chunk_id, doc_id, publish_time, source, section, version, hash}`；
- 检索：embedding 召回 + 关键词/元数据过滤 + 时点过滤，返回 `chunk_id + 原文片段 + publish_time`；
- 输出必须携带 `chunk_id`，供引文核验（P2 证据准确率）。

**确定性工具清单（版本化、可重算）**

| 工具 | 功能 | 主要服务角色 |
|------|------|--------------|
| `risk_measure` | 波动率、VaR/CVaR、回撤、压力分位 | 投资、监管 |
| `systemic_risk` | ΔCoVaR、MES、Diebold-Yilmaz 溢出指数 | 监管、投资 |
| `capital_flow` | 异常净流入 z、同步撤离、集中度、AH 溢价 | 监管、投资 |
| `scenario` | 情景冲击（汇率贬 x%、美股跌 y%）下的压力传导 | 监管、融资 |
| `forecast` | 调用融合预测器（只读） | 全部 |
| `funding_cost` | 融资成本、信用利差、现金流压力情景 | 融资 |
| `knowledge_search` | 时点过滤 RAG | 全部 |
| `report_export` | 结构化预警简报导出 | 协调者 |

**工具契约**：Pydantic 输入/输出 schema；返回 `{value/table, unit, inputs_hash, tool_version, as_of, citations, elapsed_ms}`；错误必须显式抛出（工具失败不允许 LLM 编造数值）。

**权限矩阵**：`role × tool → allow / deny`；越权调用被拦截、记审计，并计入 P2/P3 指标（越权阻断次数）。

### 3.4 L4 智能体层（Three Role Agents）

**RoleSpec（角色配置，YAML 化，论文 4.3 的表格来源）**

| 字段 | 监管主体 | 投资主体 | 融资主体 |
|------|----------|----------|----------|
| 目标函数 | 市场压力↑、跨市场外溢↑ | 组合尾部损失↓、最大回撤↓ | 融资成本↑、现金流压力↑ |
| 信息权限 | 宏观、市场、政策全文、跨境总量 | 市场、行业、组合暴露、个股资金流 | 利率、信用利差、融资事件、行业景气 |
| 工具权限 | risk_measure、systemic_risk、scenario、knowledge_search | risk_measure、capital_flow、scenario | funding_cost、scenario、knowledge_search |
| 预警阈值 | 系统性阈值（高） | 组合损失阈值 | 融资成本阈值 |
| 输出 | 监管预警简报 + 建议措施 | 仓位/对冲建议 | 融资安排与现金流预警 |
| 决策损失权重 | 漏报 >> 误报 | 尾部损失主导 | 成本超支主导 |

**RiskCard 输出 schema（结构化，可核验）**

```json
{
  "role": "regulator",
  "as_of": "2024-08-05",
  "risk_level": "high",
  "base_signal_ref": "ev_sig_20240805_v1",
  "key_metrics": [{"name": "dy_spillover", "value": 0.63, "unit": "index", "evidence_id": "ev_tool_..."}],
  "claims": [
    {"claim_id": "c1", "text": "北向资金异常流出处于近一年 92% 分位",
     "value": 1.42, "unit": "z", "evidence_ids": ["ev_tool_..."], "confidence": 0.8}
  ],
  "recommendation": "...",
  "limitations": ["..."],
  "tool_calls": 6, "tokens": 3120
}
```

**Agent Loop（每角色相同代码，配置不同）**

1. 读取任务与共享风险信号（L2 输出）；
2. 按 RoleSpec 选择工具 → 权限校验 → 调用 → 获得 Evidence；
3. 基于证据形成 Claims（每条 claim 必须绑定 evidence_id）；
4. 自检：数字回填工具输出、文本断言回填 citation；
5. 发布 RiskCard + Evidence 到黑板；
6. 等待协调轮（交叉验证/回应质询），必要时修订并保留版本。

**反幻觉硬约束**：输出 schema 校验 + 数值核验器（横切 A）+ 无证据断言率指标；LLM 不得直接输出未出现在工具/知识库中的数字。

### 3.5 L5 协同编排层（Orchestration & Collaboration）

**Coordinator**：生成任务 DAG；控制预算（工具调用次数 / token / 时延）；调度轮次；汇总决策卡；不覆盖确定性数值。

**协同流程（论文 4.4 的核心算法）**

```
R0 独立分析：三 agent 各自产出 RiskCard（互不可见）
R1 证据共享：Evidence 入黑板，去重、编号、标注来源
R2 交叉验证：每个 agent 被分配复核他人 1-2 条关键数值 claim（用工具重算）
R3 分歧识别：对同一 subject 的 claims 做比对
      - 数值差异 > 容差           → 事实冲突（fact conflict）
      - 方向/风险等级相反          → 方向冲突（directional conflict）
      - 证据一致但阈值/权重不同    → 偏好差异（preference divergence，不算错）
R4 协调：
      - 事实冲突 → 权威工具重算 / 权威数据源 → 以可复现证据为准
      - 方向冲突 → 追加证据（补充工具调用）→ 仍不一致则升级 Coordinator
      - 偏好差异 → 保留差异，在决策卡中分主体呈现
      - 未解决 → 升级人工（HITL）
R5 汇总：综合决策卡（公共事实部分 + 三主体差异化建议 + 分歧说明 + 核验状态）
```

**冲突判定规则（写入配置，可消融）**：数值容差；方向一致性；证据等级（工具重算 > 权威数据源 > 文本引用 > LLM 推断）；协调轮次上限。

**HITL 触发点**：高风险预警、未解决冲突、越权尝试、核验失败；人工可批准/修改/驳回，全部写审计。

**协同指标**：分歧率、冲突解决率、平均协调轮次、重复证据率、协调成本（工具调用/token/时延）。

### 3.6 横切 A：验证与审计层（Verification & Audit）

| 核验项 | 规则 | 输出指标 |
|--------|------|----------|
| 数值核验 | 抽取卡片中所有数字，与 claims / 工具输出比对（绝对/相对容差） | 数值错误率（P2） |
| 引文核验 | 每条文本 claim 必须映射到 `evidence_id → chunk_id → 原文`，且 `publish_time <= as_of` | 证据准确率、无依据断言率（P2） |
| 时点核验 | 任何证据/数据 `publish_time > as_of` 即泄漏事件 | 泄漏次数（应为 0） |
| 越权核验 | 工具调用前查权限矩阵 | 越权阻断次数（P2/P3） |
| Schema 核验 | RiskCard / Claim 必须过 Pydantic | 格式失败率 |
| 审计 trace | `trace.jsonl`：run_id, step, agent, action, tool, args_hash, result_hash, latency, tokens, cost, timestamp | 复现、成本核算、视频演示素材 |

**审计 trace 是"可信 AI"卖点的可视化素材**：演示界面里可以直接展开"第 3 步：投资智能体调用 VaR 工具，输入哈希 xxx，耗时 120ms，结果来自 2024-08-05 快照"。

### 3.7 横切 B：实验与评估层（Experiment Harness）

**配置化实验（一个 yaml 跑完所有对照）**

```yaml
run_id: p3_collab_v1
data: {window: [2015-01-01, 2025-09-30], as_of_step: daily, snapshot: pit-20251018}
target: {label_version: stress_pca_q90, horizons: [5, 10, 20]}
modality: {numeric: true, text: true}          # P1
augment: {rag: true, tools: true}               # P2
agents: {mode: collaborative, roles: [regulator, investor, financing], rounds: 2}
coordination: {evidence_share: true, cross_validation: true, conflict_resolution: true}  # P3
budget: {max_tool_calls: 12, max_tokens: 8000, equal_across_configs: true}
llm: {provider: deepseek, model: deepseek-chat, temperature: 0, seed: 42}
eval: {bootstrap: 1000, metrics: [pr_auc, recall, ece, lead_time, numeric_error, evidence_acc, unsupported_rate, task_completion, decision_loss, coordination_cost]}
```

**四类对照 + 逐项消融**（论文 5.2）

1. 传统金融预测基线（仅数值、无 LLM）；
2. 单智能体（一个通用 agent 完成三主体任务）；
3. 三个独立智能体（无共享、无协调）；
4. 完整协同系统（证据共享 + 交叉验证 + 分歧协调）；
逐项消融：文本模态、RAG、工具、专业化分工、协调机制；**统一信息集、预测时点、工具预算、token 预算**。

**时点回放**：对每个评估日 t，只用 `as_of <= t` 的数据/KB/模型版本；滚动重训；评估日集合固定，写入 run 配置。

**输出**：`artifacts/runs/<run_id>/{config.yaml, metrics.json, traces/, figures/, tables/}`；自动生成论文表格/图（P1/P2/P3 各一组），可直接进技术文档与论文第六节。

### 3.8 L6 决策支持与演示层（Web 驾驶台）

**页面结构（录屏脚本就按这个顺序讲）**

1. **场景选择**：历史压力事件（如 2015 股灾、2018 贸易摩擦、2020 疫情冲击、2022 加息/地缘、2024 汇率压力），选择后自动设定 `as_of`；
2. **时间轴回放**：拖动日期 → 系统仅用当日可得信息重新生成预警；
3. **风险仪表盘**：5/10/20 日高压力概率、历史分位、驱动因子归因、模态贡献（数值 vs 文本）；
4. **三智能体卡片**：监管/投资/融资的风险等级、关键证据、建议、置信度、局限；
5. **证据板**：证据卡片（数值/文本/工具），点击查看来源、时点、工具版本、重算入口；
6. **分歧与协调面板**：冲突列表、类型（事实/方向/偏好）、协调过程与结果、未解决项；
7. **核验与审计面板**：数值核验通过率、引文覆盖率、越权拦截、时点泄漏检查；展开 trace；
8. **导出**：结构化预警简报（Markdown/JSON/PDF）——"可复核的决策支持产物"；
9. **实验模式页**：P1/P2/P3 消融结果图（论文图复用，演示"这不是玩具"）。

**技术选型**：Streamlit 首发（最快，Python 单栈，ECharts/Plotly 组件足够好看），后端逻辑全部在 API/服务层，UI 可后续升级 React 而不动核心。**API 与 UI 分离**：`FastAPI` 暴露 `/api/asof/{date}/warning`、`/api/run/{run_id}`、`/api/evidence/{id}`，Streamlit 只做展示。

---

## 4. 与论文第四章的映射（技术文档写作大纲）

| 论文章节 | 工程模块 | 文档内容 |
|----------|----------|----------|
| 4.1 多模态风险信息融合 | L1 + L2 | 数据域与标签、时点对齐、数值/文本特征、融合预测器与归因、P1 消融设计 |
| 4.2 金融知识增强与工具调用 | L3 + 横切 A | KB 结构与时点过滤、工具契约表、权限矩阵、数值核验与引文溯源、P2 指标 |
| 4.3 三角色预警智能体设计 | L4 | RoleSpec 表（目标/信息/工具/阈值/输出/损失）、RiskCard schema、Agent Loop、反幻觉约束 |
| 4.4 多智能体协同与决策支持机制 | L5 + 横切 A | 黑板与证据 schema、R0-R5 协同算法伪代码、冲突分类与仲裁规则、HITL、审计、P3 指标 |
| 5.x 实验设计（支撑材料） | 横切 B | 配置化消融、时点回放、可比预算、指标定义、统计检验 |

技术文档体裁：方法概述 → 形式化定义（符号表）→ 模块设计 → 算法伪代码 → 实现与可复现性 → 与论文命题的对应关系。目标 8000-12000 字 + 架构图/流程图/表。

---

## 5. 技术栈与代码目录

**技术栈**：Python 3.12（.venv）；pandas/numpy/scikit-learn/xgboost/statsmodels；DuckDB + Parquet；Pydantic；FastAPI + Uvicorn；Streamlit + Plotly/ECharts；embedding 可用 bge-m3（本地）或 API；pytest + ruff；LLM provider 抽象层（DeepSeek/Qwen/OpenAI/local + mock 模式）。

**目录结构**

```
D:\recently\commorcial\
├─ configs/                  # 角色配置、实验配置、数据源配置
├─ data/                     # raw / interim / processed（parquet、pit.duckdb）
├─ src/cbr/
│  ├─ data/                  # 采集、清洗、PitStore、数据卡
│  ├─ features/              # 数值/文本特征、时点对齐
│  ├─ models/                # 基线 + 融合预测器 + 模型注册表
│  ├─ tools/                 # 确定性工具 + 注册表 + 权限矩阵
│  ├─ knowledge/             # KB 构建、时点过滤 RAG、引文
│  ├─ agents/                # RoleSpec、Prompt、Agent Loop、RiskCard schema
│  ├─ orchestration/         # Coordinator、黑板、冲突检测、仲裁、HITL
│  ├─ verification/          # 数值/引文/时点/越权/schema 核验 + trace
│  ├─ eval/                  # 指标、消融、时点回放、统计检验
│  └─ api/                   # FastAPI 路由
├─ app/                      # Streamlit 驾驶台
├─ scripts/                  # 数据构建、实验运行、演示种子
├─ tests/
├─ docs/                     # 架构文档、技术文档第四章、演示脚本
└─ artifacts/                # runs/ 实验结果、图表、示例报告
```

---

## 6. 里程碑（2026-10-18 → 10-23）

| 日期 | 交付 |
|------|------|
| 10-18（日） | 架构对齐、决策锁定、项目脚手架、子代理调研（框架/数据）|
| 10-19（一） | 数据采集 + PIT 存储 + 风险标签；融合预测器 v1；工具层 v1 |
| 10-20（二） | 三角色 agent + 黑板/协同/核验；mock LLM 全链路跑通 |
| 10-21（三） | Web 驾驶台 v1；真实 LLM 接入；演示场景固定；试点消融跑通 |
| 10-22（四） | 技术文档第四章初稿；演示脚本 + 使用说明；UI/流程打磨 |
| 10-23（五） | 缓冲修复、录屏支持、文档定稿 |

**关键风险**：LLM API 可用性（无 key 则 mock 模式先跑通，后期替换）；数据源反爬/口径（东方财富/yfinance 兜底）；历史回放泄漏（PIT 架构兜底）；范围膨胀（以"可演示 + 第四章 + 录屏"为第一优先级，完整论文实验后置）。

---

## 7. 待确认决策（影响实现路径）

| # | 决策 | 备选 | 建议 |
|---|------|------|------|
| D1 | 本周交付重点 | A 原型+文档+录屏 / B 论文实验 / C 仅文档 | A：先保证可演示与文档，实验 harness 内建、试点结果后补 |
| D2 | LLM 接入 | DeepSeek / Qwen / OpenAI / Claude / 本地 / 暂无 key | DeepSeek（便宜、中文好、OpenAI 兼容） |
| D3 | 数据来源 | 公开数据 / 用户提供 Wind/Choice / 自建数据 / 合成数据先行 | 公开数据优先，用户数据可后接 |
| D4 | 演示形态 | Web 驾驶台 / 聊天界面 / Notebook / 都要 | Web 驾驶台（可展示协同与证据链） |
| D5 | 协作方式 | Lead 自动推进 / 节点确认 / kk 参与实现 | Lead 拆分并行 + 关键节点对齐 |
