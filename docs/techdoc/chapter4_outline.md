# 第四章《多模态多智能体协同预警方法》· 章节大纲与写作计划

> 交付人：doc-writer（task-6）｜版本：v0.5（2026-10-18）｜状态：Lead 已确认；正文 v0.5 完成最终一致性核对（数据快照/数据卡、label/threshold 口径、R2 条数、HITL 触发等级、合成数据限制），open_issues 已同步关闭已完成项
> 主文档：`docs/techdoc/chapter4_method.md`（中文，目标 8000–12000 字，不含表格与代码）
> 依据：`docs/direction2_extracted.txt`、`docs/architecture/CBR-MAW_architecture_v0.md`、`src/cbr/schemas.py`、`src/cbr/contracts.py`、`configs/roles.yaml`、`configs/app.yaml`、`configs/experiments/p1_modality.yaml`

---

## 一、写作定位与边界

1. **体裁**：方法章（论文章节体例），学术中文，参照《管理科学学报》风格；以“方法设计 + 可检验含义”为主线，不写“系统开发报告”“我们做了一个系统”。
2. **回答三个必答问题**：①为什么是监管/投资/融资三个智能体；②协同增益如何被检验；③如何防数值错误、无依据断言与时点泄漏。
3. **对齐论文框架**：对应论文第四章 4.1–4.4 与第五章 5.1–5.3、第六章 6.1–6.4；每个方法模块标注命题（P1/P2/P3）与实验章节。
4. **不编造结果**：涉及实证结论处一律写“待实验验证（实验设计见 5.x / 6.x）”，只陈述可检验含义与评价口径。
5. **与代码一致**：类名、字段名、配置项、工具名以 `src/cbr/` 实现为准；当前按 `schemas.py`/`contracts.py` 契约写作，随实现推进逐轮核对修订。
6. **写作边界**（来自框架文档）：只写“数值—文本多模态融合”，不宣称音频/图像模态；预警表现、解释可靠性、决策价值分属三个评价层次，不相互替代。

---

## 二、全文结构与字数预算（正文约 10500–11500 字）

| 节 | 标题 | 核心内容 | 命题/章节映射 | 预算（字） |
|----|------|----------|----------------|-----------|
| 4.0 | 方法总览与设计原则 | 任务形式化；五条设计原则（单一风险锚、数值不由 LLM 生成、证据一等数据结构、协同可开关可消融、时点回放）；总体架构图（六层两横切）；方法—命题—实验对照表 | P1/P2/P3；5.1–5.3 | 1100 |
| 4.1 | 多模态风险信息融合 | 符号表；数据域与序列；压力指数与高位标签（含预测期 h∈{5,10,20}）；时点对齐与防泄漏（release_time/as_of、滚动重训、文本发布时点）；数值/文本特征；早期/晚期/堆叠融合预测器；模态贡献归因（SHAP 类）；P1 可检验设计与消融口径 | P1；6.1；5.1/5.2 | 2100 |
| 4.2 | 金融知识增强与专业工具调用 | 知识库 chunk 元数据（chunk_id/doc_id/publish_time/version/hash）与双时点过滤；检索—引文链；7 个确定性工具契约表（输入/输出/单位/版本）；角色×工具权限矩阵；数值核验与引文核验规则；LLM 与工具职责边界（LLM 不产数值）；P2 指标定义与消融 | P2；6.2；5.2/5.3 | 2000 |
| 4.3 | 监管/投资/融资智能体设计 | RoleSpec 完整表（7 字段）；RiskCard/Claim schema；解释 Agent Loop（编号步骤 + 伪代码）；三角色差异化但共享风险锚；反幻觉硬约束（schema/数值核验/越权阻断/禁止行为）；“为什么三个智能体”的分工必要性论证与可检验设计 | P3 基础（专业化分工）；6.3；5.2 | 2200 |
| 4.4 | 多智能体协同与决策支持机制 | 证据黑板与 Evidence schema；R0–R5 协同算法（伪代码）；冲突分类表（事实/方向/偏好）与仲裁规则（证据等级、容差、轮次上限）；HITL 触发与接管；审计 trace 结构；协同成本度量；协同增益的三重检验（单智能体/独立三智能体/完整协同）；决策卡输出 | P3；6.3；5.2/5.3 | 2300 |
| 4.5 | 实现与可复现性 | 代码目录与模块—接口映射；配置化实验（p1_modality.yaml 示例 + 三模式对照 + 逐项消融矩阵）；统一预算与资源对齐；指标定义表（P1/P2/P3 及统计检验：bootstrap CI、Diebold-Mariano 类检验）；已知限制 | 5.1–5.3；6.4 | 1300 |
| 附录 | 接口清单/配置示例/术语表 | Role/Evidence/Claim/RiskCard/Conflict/VerificationReport/DecisionCard 字段清单；关键接口（DataProvider/ToolRegistry/KnowledgeBase/Orchestrator）；配置片段；术语表 | — | 800 |

**图清单（Mermaid，≥3 张，计划 5 张）**

| 编号 | 类型 | 内容 | 位置 |
|------|------|------|------|
| 图 4-1 | flowchart | 总体架构：六层（L1 数据时点 / L2 多模态融合 / L3 知识工具 / L4 智能体 / L5 协同编排 / L6 决策支持）+ 两条横切（验证审计、实验评估） | 4.0 |
| 图 4-2 | flowchart LR | 多模态融合与 P1 消融数据流：数据域→时点对齐→数值/文本特征→融合预测器→RiskSignal→证据黑板 | 4.1 |
| 图 4-3 | flowchart | 单智能体 Agent Loop：读信号→工具选择与权限校验→Evidence→Claim→自检→发布 RiskCard→响应协调轮 | 4.3 |
| 图 4-4 | sequenceDiagram | 三智能体协同时序：R0 独立分析→R1 证据共享→R2 交叉验证→R3 分歧识别→R4 仲裁/HITL→R5 决策卡 | 4.4 |
| 图 4-5 | flowchart | 冲突判定与仲裁流程图（含容差、证据等级、升级 HITL 分支） | 4.4 |

**表清单（≥5 张，计划 8 张）**：表 4-1 符号表；表 4-2 数据域与序列（服务 4.1）；表 4-3 RoleSpec 完整规格；表 4-4 工具契约；表 4-5 角色—工具权限矩阵；表 4-6 冲突分类与仲裁；表 4-7 指标定义（P1/P2/P3）；表 4-8 消融矩阵；表 4-9 方法模块→实验配置→指标对应表；表 4-10 术语表（附录）。

**公式/伪代码清单**：压力指数与滚动分位阈值、高位标签、融合预测器（早期/晚期/堆叠）、模态贡献归因、数值核验容差、引文覆盖率/无依据断言率、预警提前期、决策损失与协同成本；算法 1 Agent Loop、算法 2 R0–R5 协同协议、算法 3 核验流水线（可选）。

---

## 三、与代码一致性基准（当前快照）

- 数据结构：`src/cbr/schemas.py` 中的 `RiskSignal`/`RiskDriver`/`Evidence`/`SourceRef`/`ToolRef`/`Claim`/`RiskCard`/`RoleSpec`/`ToolResult`/`Conflict`/`VerificationReport`/`CoordinationStats`/`DecisionCard`/`TraceEvent`/`ExperimentConfig`/`MetricResult`；枚举 `Role`、`RiskLevel`、`EvidenceKind`、`ClaimType`、`ClaimStatus`、`ConflictType`、`ExperimentMode`。
- 接口：`src/cbr/contracts.py` 中的 `DataProvider`（`risk_signal`/`market_snapshot`/`history`/`label`/`data_cards`）、`Tool`/`ToolRegistry`（含 `allow(role, tool)`）、`KnowledgeBase.search`、`LLMClient`、`Orchestrator.run/chat`、`RoleRegistry`。
- 配置：`configs/app.yaml`（`orchestration.rounds=2`、`max_tool_calls_per_agent=6`、`max_tokens_per_agent=4000`、`numeric_tolerance_abs/rel`、`trace_dir`；`signal.model_version=fusion-xgb-v1`、`roll_window=500`、`retrain_every=20`；`data.label_version=stress_pca_q90`、`horizons=[5,10,20]`）；`configs/roles.yaml`（三角色完整字段）；实验配置键（`run_id/data/target/modality/augment/agents/coordination/budget/llm/eval`）。
- 修订触发：每 1–2 轮读取 `src/cbr/` 新增实现 diff（数据层、工具层、Agent、编排、核验、评估），发现字段/命名/默认值差异即修订并记录变更点。

---

## 四、请 Lead 确认的 5 个问题（不阻塞写作，初稿按默认假设推进）

1. **工具表口径**：架构 v0 列 8 个工具，但 `configs/roles.yaml` 角色白名单只引用 7 个（`risk_measure`、`systemic_risk`、`capital_flow`、`scenario`、`forecast`、`funding_cost`、`knowledge_search`），`report_export` 属于协调者输出工具。默认：表 4-4 写 7 个角色可调用工具，`report_export` 在 4.4/附录作为协调层能力单列——是否同意？
2. **章节编号体例**：技术文档按 4.0–4.5 编号（4.0 为方法总览），附录编号 A/B/C；图题表题为“图 4-1”“表 4-1”。如论文正文要求从 4.1 起，可整体平移。
3. **三模式实验细节**：`single`（一个通用 agent 完成三任务）与 `independent`（三 agent 无共享无协调、但同 prompt/同工具预算）的差异需在 4.4/4.5 明确写死，供 6.3 对照；默认按此口径写。
4. **HITL 与 Web 驾驶台**：4.4 是否单列“人工接管与审计留痕”小节（含 L6 决策支持界面形态），还是仅在 4.4 内以段落实例说明？默认单列 4.4.4 小节并简述驾驶台信息架构，不展开 UI 技术细节。
5. **是否收录工程实现细节**：4.5 与附录保留代码路径/配置键/接口签名（技术文档必需），正文方法部分只用符号与文字描述、不出现代码路径。默认如此。

---

## 五、交付节奏

1. 本大纲 → 发送 Lead 确认（同时开始写正文，结构若无重大调整不回退）。
2. 正文初稿（4.0–4.5 + 附录）→ 自查字数/图表/公式/命题映射 → 发送 Lead（列章节字数、图表数量）。
3. 随实现推进每轮修订：读 `src/cbr/` 新增代码 → 核对字段/工具名/配置默认值 → 修订正文 → 汇报变更点。
4. 与实现不一致或缺失的实现点单独列清单发 Lead（转对应工程师），不在文档中掩盖。
