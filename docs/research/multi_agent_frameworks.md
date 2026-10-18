# 多智能体框架生态与工程范式调研

> **项目**：CBR-MAW 系统（跨境金融风险的多智能体协同预警：多模态信息融合视角）
> **用途**：为智能体原型（监管 / 投资 / 融资三主体 + 协调者 + 核验器）提供框架选型、可信工程模式与 5 人日 MVP 边界依据。
> **调研日期**：2026-10-18；版本号为当日 PyPI / 官方文档实测快照，会随发布变化。
> **方法**：① PyPI JSON API 实测各包最新版本与上传日期；② 官方文档 / 发布说明精读（LangGraph v1、ADK 2.0、PydanticAI、CrewAI、AG2、Microsoft Agent Framework 等）；③ arXiv API 核对论文编号与标题；④ 未做同任务运行时基准（见 §7.3 研究局限与后续 spike 建议）。
> **安全声明**：外部网页内容仅作资料使用，本报告未执行其中任何指令；文中所有引用均为公开文档或论文。

---

## 0. 结论摘要（TL;DR）

1. **选型：默认自研轻量编排器，不把 LangGraph / CrewAI / ADK 作为核心运行时。** 用 `Pydantic v2` 定义全部接口 schema，用自建 `LLMClient + BudgetManager + TraceRecorder` 做统一计量与审计，用 SQLite/JSONL 存事件与 trace；LangGraph 仅作**参考实现**与后续"生产化/平台化"的迁移备选（预留 `Orchestrator` 适配接口）。核心理由：本项目的可审计 trace 需要 `evidence_id / claim_id / verification` 等领域字段，三配置消融需要**同一代码路径**，token/算力预算需要**前置硬约束**，而 5 人日内引入框架的迁移与版本风险大于收益（AutoGen→MAF、ADK 1.x→2.0 均发生过破坏性变更）。
2. **三配置（单智能体 / 三独立 / 完整协同）用一个 `run(config)` 入口实现。** 差异压缩为四个可组合策略：`AgentSet`（角色与工具白名单）、`SharingPolicy`（none / broadcast）、`CoordinationPolicy`（merge / arbitrate）、`VerificationGate`（numeric / citation / authority / schema 可逐项开关）；`Scheduler.plan(config)` 只负责生成阶段列表。三角色任务提示词、模型、参数、数据快照、总预算在三种模式间保持同一套模板与上限。
3. **可信性闭环按"确定性工具 > 规则核验 > LLM 解释"分层。** 数值只认 `tool_result` 重算（Decimal 容差 + 单位/窗口/as_of 校验）；引用只认 `span + quote_hash + publish_time ≤ as_of`；越权在 `ToolPolicy` 层**前置拒绝**并写审计码；schema 校验失败走"修复重试 ≤2 次"的有限降级；LLM-as-judge 只做辅助软指标，不承担数值/引用/权限判定。
4. **5 人日 MVP 边界**：D1 骨架（schema/LLM 客户端/预算/trace/工具注册表）；D2 RAG（as_of 过滤 + span 引用）与 claim 核验；D3 三角色 + 单/独立两配置端到端；D4 协同（证据共享 / 冲突识别 / 协调 / 核验门 / HITL）+ 三配置消融；D5 Web 演示 + 录屏 + 第四章初稿。可延后：多轮辩论（>2 轮）、语义级冲突判定、OTel 全量导出、多用户认证、生产数据库、完整统计检验。
5. **关键风险**：LLM 非确定性（缓存 + 温度 0 + 快照 + 重复实验）、框架版本漂移（锁依赖、不引入重型框架）、预训练知识泄漏（as_of 硬过滤 + 泄漏探针 + 论文中明确披露局限）、把 judge 当主指标（改用确定性规则 + 人工抽检）。

---

## 1. 调研范围与判断口径

### 1.1 覆盖对象

- **主流编排框架**：LangGraph / LangChain v1、OpenAI Agents SDK、PydanticAI（含 Pydantic Graph / Evals / Harness）、Google ADK 2.x、CrewAI、AutoGen 0.7 与 Microsoft Agent Framework（MAF）、AG2、MetaGPT。
- **相邻生态**：Agno、smolagents、Strands Agents、CAMEL、DSPy；可观测层（LangSmith、Langfuse、Pydantic Logfire、OpenTelemetry GenAI semconv）；工具协议（MCP、A2A）。
- **工程范式与代表性工作**：数值主张核验、RAG 引用溯源、越权工具阻断、schema 校验、LLM-as-judge 局限；MAD、AutoGen group chat、NLSOM/Society of Mind、TradingAgents、FinCon、FinAgent 及 2026 年金融预警/合规智能体工作。

### 1.2 对比维度（任务要求口径）

最新稳定版本 · 核心抽象 · 结构化输出（Pydantic / JSON schema）· 工具调用与权限控制 · 并行 / 轮流 / 图编排 · 事件流与 tracing 可观测性 · human-in-the-loop 中断恢复 · token / 成本统计 · 可复现性 · 学习曲线。

### 1.3 版本快照（PyPI 实测，2026-10-18）

| 包 | 最新版本 | 上传日期 | 状态判断 |
|---|---|---|---|
| langgraph | **1.2.16** | 2026-10-16 | 稳定主线，1.x 强调 API 稳定 |
| langchain | 1.4.6 | 2026-10-14 | v1 系列的 `create_agent` 构建于 LangGraph 之上 |
| langgraph-checkpoint | 4.3.0 | 2026-10-12 | 持久化/中断恢复基础件 |
| openai-agents | **0.24.0** | 2026-10-15 | 仍为 0.x，API 可能变动 |
| pydantic-ai | **2.57.0** | 2026-10-16 | 2.x 主线，类型与耐久执行强 |
| pydantic-evals | 2.57.0 | 2026-10-16 | 评测组件与主包同版本节奏 |
| google-adk | **2.12.0** | 2026-10-13 | ADK 2.0（Python）2026-05-19 GA，图执行引擎重构 |
| crewai | **1.15.28** | 2026-10-14 | 1.x 快速迭代（Crews + Flows） |
| ag2 | **1.1.2** | 2026-10-03 | 1.0 于 2026-07 发布，TealTiger 治理中间件 |
| agent-framework（Microsoft） | **1.22.0** | 2026-10-15 | AutoGen + Semantic Kernel 的统一继任者，GA |
| autogen-agentchat（旧） | 0.7.5 | 2025-09-30 | 维护模式，官方推荐迁移 MAF |
| semantic-kernel | 1.45.0 | 2026-10-06 | 与 MAF 同栈 |
| metagpt | **0.8.2** | 2025-03-09 | 发布停滞，偏研究代码库 |
| dspy | 3.4.1 | 2026-10-12 | 提示/程序优化，非编排框架 |
| agno | 3.1.4 | 2026-10-16 | 轻量多智能体框架 |
| smolagents | 1.26.0 | 2026-05-29 | 代码型 agent 轻量框架 |
| strands-agents（AWS） | 1.61.1 | 2026-10-15 | 模型/工具抽象 + 多智能体 |
| camel-ai | 0.2.90 | 2026-03-22 | 研究型多智能体框架 |
| langfuse | 5.0.2 | 2026-10-16 | 可观测/评测平台 |
| langsmith | 0.14.11 | 2026-10-16 | LangChain 系可观测平台 SDK |
| litellm | 1.106.0 | 2026-10-18 | 多模型统一网关（含成本表） |
| mcp | 2.3.0 | 2026-10-02 | 工具互操作协议 SDK |

> 说明：PyPI 上传日期由 PowerShell 解析，时区可能为 UTC；版本更新极快，正式开工前需再核对一次并锁定 lockfile。

---

## 2. 框架横向对比

### 2.1 主对比表（核心能力）

> 图例：✅ 内置且成熟；◐ 部分内置/需配置；○ 需自建或社区方案；— 不适用。

| 框架（版本） | 核心抽象 | 编排范式（并行/轮流/图） | 结构化输出 | 工具调用与权限控制 |
|---|---|---|---|---|
| **LangGraph 1.2.16** | `StateGraph`（状态、节点、边、`Command`、子图、`Send` 扇出）、checkpointer、store、`interrupt()` | ✅ 图编排 + 循环 + 并行扇出；轮流/条件路由由边表达 | ◐ 状态可用 Pydantic/TypedDict；模型侧 `with_structured_output`，图边界不强制 | ○ `ToolNode` + 自定义中间件；无内置角色策略引擎、无工具审批 DSL |
| **OpenAI Agents SDK 0.24.0** | `Agent`、`Runner`、`Handoff`、`Guardrail`、`Session`、`Trace` | ◐ handoff 链 + 代码内 `asyncio.gather`；无图/循环原语 | ✅ `output_type`（Pydantic）强校验 + 重试 | ◐ 工具级 guardrail / 人工审批（approvals）；无角色权限模型 |
| **PydanticAI 2.57.0** | `Agent[Deps, Output]`、`RunContext` 依赖注入、`Capability`、Pydantic Graph、Evals、Harness | ✅ Pydantic Graph 图编排；并行靠 `asyncio`；委派靠子智能体 | ✅ 全链路类型化，输出强制校验、工具参数校验 + 模型重试 | ◐ 工具参数校验、`requires_approval` / deferred 工具；无策略引擎 |
| **Google ADK 2.12.0** | `Agent`（继承 `BaseNode`）、Workflow Runtime 图引擎、Event/Session、Tool、Callback | ✅ 图工作流 + 动态工作流 + 协作式 coordinator/subagent；Sequential/Parallel/Loop 让位于图 | ✅ `input_schema` / `output_schema` / `state_schema`，Pydantic 校验 | ◐ 每 agent 工具集 + 回调；`isolationScope` 控制事件可见性；无策略 DSL |
| **CrewAI 1.15.28** | `Agent`（role/goal/backstory）、`Task`、`Crew`、`Flow`（`@start/@listen/@router`） | ◐ Crew 顺序/层级流程；Flow 支持分支/循环；并行任务有限 | ✅ `output_pydantic` / `output_json` + task guardrail | ◐ agent 级工具绑定 + guardrail 函数；无策略引擎 |
| **AutoGen 0.7.5 / MAF 1.22.0** | AutoGen：actor + `AssistantAgent` / `GroupChat`；MAF：executor/edge 图工作流 + 类型化 agent | ✅ 群聊/轮流/选择器/移交；MAF 图工作流（含并行）；AutoGen 事件驱动并发 | ◐ AutoGen 模型客户端可配置结构化输出；MAF 类型化工作流 | ○ 工具审批需自建；MAF 提供 middleware/审批钩子思路 |
| **AG2 1.1.2** | `ConversableAgent`、`GroupChat`、嵌套对话、swarm、TealTiger 治理中间件 | ✅ 群聊/轮流/嵌套/移交；并发靠多会话；无图运行时 | ◐ 可配置结构化回复（依模型能力） | ✅ **TealTiger 策略引擎**：工具白名单、参数校验、注入拦截、PII/密钥脱敏、成本预算、限流、冻结 agent、结构化拒绝码 |
| **MetaGPT 0.8.2** | `Role` / `Action` / `Environment`、SOP、共享消息池 + 发布订阅 | ◐ SOP 顺序 + 发布订阅并发；无通用图编排 | ◐ Action 输出 Pydantic 模型（提示层约束，非强 schema 校验） | ○ 角色级 action 绑定，无运行时策略/审批 |
| **自研轻量编排器（建议）** | `Stage` 图 + `MessageBus` + `Evidence/Claim Store` + `ToolRegistry/Policy` + `Verifier` | ✅ 显式阶段图（并行/轮流/循环均可编程），便于同一路径切换配置 | ✅ 全接口 Pydantic v2 强校验 + 修复重试 | ✅ 角色×工具×参数×时点×预算×审批五层策略，拒绝码入 trace |

### 2.2 主对比表（工程与运维）

| 框架 | 事件流 / tracing | HITL 中断与恢复 | token / 成本统计 | 可复现性 | 学习曲线 | 适用判断（对本项目） |
|---|---|---|---|---|---|---|
| LangGraph 1.2.16 | ✅ 流式多模式 + LangSmith（含 token/成本、评估）；自建事件需包装 | ✅ `interrupt()` + `Command(resume=...)`、checkpoint 重放、time travel、Studio | ◐ 平台侧统计（LangSmith）；运行时无强制预算账本 | ◐ 可从 checkpoint 重放；LLM 调用本身不确定 | 中高 | 若做长期平台化/生产多租户可选；5 日 MVP 偏重 |
| OpenAI Agents SDK 0.24.0 | ✅ 内置 trace/span、可接 Logfire/Braintrust/Langfuse 等处理器 | ◐ 工具审批 + 可恢复 session 快照（2026-04 引入沙箱/可恢复会话） | ◐ trace 含 usage；无预算强制 | ◐ session 可恢复；无确定性保证 | 低 | 适合轻量工具链原型；缺图/审计领域字段 |
| PydanticAI 2.57.0 | ✅ OTel 原生 span + Logfire（含成本，基于 genai-prices）+ Evals | ✅ `requires_approval` / deferred + 九种耐久执行引擎（Temporal、DBOS、Prefect、Restate、AWS Lambda 等） | ◐ OTel/Logfire 成本可视；Gateway 支持预算控制（托管/自托管） | ◐ 耐久执行可重放；模型调用不确定 | 中低 | 若想少写 agent loop 可作"库"引入；编排/审计仍需自建 |
| Google ADK 2.12.0 | ✅ 内置 OTel、事件流、`node_info/output` 扩展、Cloud Trace 集成 | ✅ 节点中断（`NodeInterruptedError`/`RequestedInput`）+ 会话持久化 + 自动重试 | ◐ 事件 `usage_metadata` 聚合；无预算强制 | ◐ 事件可回放、确定性路由设计；模型不确定 | 中高 | 面向 GCP 部署的重型方案；2.0 有 breaking change |
| CrewAI 1.15.28 | ◐ 事件总线 + 平台遥测；trace 粒度较粗 | ◐ task `human_input`、Flow 人工反馈；checkpoint 支持 fork/谱系与 TUI | ✅ `usage_metrics`（按任务/agent）；平台侧报表 | ◐ checkpoint 可 fork 复跑；无确定性 | 低 | 角色 DSL 直观，但"三配置同路径"与细粒度审计改造量大 |
| AutoGen / MAF | ✅ OTel（MAF 内置）；AutoGen 事件驱动 | ◐ AutoGen `UserProxyAgent`/移交；MAF 图工作流 checkpoint + HITL + time travel | ◐ OTel/事件中 usage；无预算强制 | ◐ checkpoint 重放；迁移期不确定性高 | 中高 | AutoGen 已进维护模式；MAF 企业向、依赖 Azure 生态 |
| AG2 1.1.2 | ◐ 对话事件 + 治理回执（receipts）；OTel 需自建 | ◐ 群聊人工输入模式；ACP server 可恢复会话 | ✅ TealTiger 成本预算硬约束（`BUDGET_EXCEEDED`） | ◐ 会话可恢复；无确定性 | 中 | 治理/权限需求可直接借鉴；无图编排 |
| MetaGPT 0.8.2 | ○ 日志与消息池，无标准 trace | ○ 基本无 HITL | ◐ 自带 token 成本统计（简单） | ○ 弱 | 中高 | 研究参考（SOP 思想），不宜作为工程底座 |
| 自研轻量编排器（建议） | ✅ 领域事件 + OTel `gen_ai.*` 映射（P1）+ JSONL/SQLite 双写，可哈希链防篡改 | ✅ 三类中断点（冲突未决/高影响/预算超限）+ 状态持久化 + 恢复 API | ✅ 前置硬预算 + 逐调用对账（prompt/completion/reasoning/cached token × 价格表） | ✅ 全量 manifest（代码/依赖/模型/提示词/数据 as_of 哈希）+ 响应缓存 | 中（自写约 1.5–2k 行核心） | **推荐：与论文"可审计、可消融、预算可比"诉求最匹配** |

### 2.3 逐框架要点（只列影响选型的证据）

**LangGraph（1.2.16，2026-10-16）**
- v1 是"稳定性优先"版本：图原语与执行模型不变，checkpointing、持久化、流式、HITL 为一等公民；`create_react_agent` 已废弃，转向 LangChain v1 的 `create_agent`（其底层仍是 LangGraph）。
- 强项：图/循环/条件路由/子图/扇出并行、checkpoint 与 time travel、流式事件、LangSmith 全链路与评估、生态与文档最厚。
- 弱项：**图是"编排图"，不是"证据/主张图"**——`evidence_id / claim_id / verification / policy_denied` 等领域事件需自建中间件；token 预算需自行在模型包装层强制；v1 仍在快速修 bug（1.2.16 的 release notes 多为恢复/重放类修复，说明中断恢复是高复杂度区域）。
- 判断：**作为参考架构与备选迁移目标最合适，不作为 5 日 MVP 的底座。**

**OpenAI Agents SDK（0.24.0）**
- 三原语 Agent / Handoffs / Guardrails + Sessions + 内置 tracing；2026-04 更新引入沙箱执行、文件系统工具、可恢复 session 快照，强化生产可用性。
- 强项：极低学习曲线、结构化输出直接、tracing 开箱即用、与 OpenAI 模型/Responses API 贴合。
- 弱项：仍为 0.x；无图/循环编排原语；无预算强制；角色权限与领域审计需自建。
- 判断：适合快速 demo 的"单 agent + 工具"，不满足三角色协同 + 三配置消融的核心诉求。

**PydanticAI（2.57.0）**
- v2 以 `Capability` 为组合原语（工具 + 指令 + 钩子 + 模型设置打包），强调端到端类型化；Pydantic Graph 提供图控制流，Evals 提供 pytest 式评测；耐久执行覆盖 Temporal/DBOS/Prefect/Restate/AWS Lambda 等九种引擎，并内置 HITL 审批；OTel 原生 + Logfire 成本追踪（genai-prices 价格表）；支持 YAML/JSON agent 规格与 MCP。
- 强项：**schema 与校验工程最扎实**，可观测性标准（OTel）最规范，HITL 与耐久执行成熟。
- 弱项：多智能体"协同模式"（证据共享、冲突仲裁、越权策略）不是其开箱能力；编排仍需自己写。
- 判断：若不愿自写 agent loop，**可仅把 PydanticAI 当作"agent 执行库"**（保留自己的调度/审计/预算层）；纯自研也完全可以只用 Pydantic + 官方模型 SDK。

**Google ADK（2.12.0；2.0 GA 2026-05-19）**
- 2.0 把执行器从"层级 agent executor"改为 **Workflow Runtime 图引擎**：Agent/Tool/Function 都是节点；新增 Event 字段 `node_info`、`output`、`route`、`isolationScope`、`RequestedInput`（HITL 暂停）；`RetryConfig` 自动重试；支持动态工作流、协作式 coordinator/subagent；每个节点可配 `input_schema/output_schema/state_schema`；Sequential/Parallel/Loop 在 2.0 中被图工作流替代（TS 已弃用）。
- 强项：确定性图路由 + 事件 schema + OTel + GCP 部署路径 + A2A 协议适配。
- 弱项：2.0 有 breaking change（数据库 schema、严格 JSON 校验、`BaseException` 捕获会破坏 HITL 暂停等）；与 Google Cloud 生态绑定较深；对本地 5 日原型偏重。
- 判断：**若团队已在 GCP 且需要托管部署**可考虑；本项目不建议。

**CrewAI（1.15.28）**
- Crews（角色/任务/流程）+ Flows（事件驱动确定性编排）；2026 年加入 checkpoint 分叉与谱系、checkpoint TUI、事件系统、task guardrail、`human_input` 与 Flow 层人工反馈；平台侧有使用报表。
- 强项：上手最快，角色化提示与任务 DSL 直观，适合"角色扮演型"多 agent demo。
- 弱项：控制粒度与审计字段不足；"三个独立智能体 vs 协同"需要绕开 Crew 的拓扑假设；token 预算无硬约束。
- 判断：**不推荐作为研究主底座**；可作为快速对照 demo 的备选。

**AutoGen 0.7.5 → Microsoft Agent Framework 1.22.0**
- AutoGen 已进入维护模式（最后发布 2025-09），微软将 AutoGen 与 Semantic Kernel 合并为 MAF；MAF 提供 executor/edge 图工作流、checkpoint、HITL、time travel、内置 OTel、类型化工作流，AutoGen 0.4 的异步 actor 架构仍是其思想来源。
- 判断：**新项目不应直接采用 AutoGen 0.7**；MAF 适合 Azure 企业栈，但 5 日内学习与迁移成本高，且与论文所需的"轻量可审计"不匹配。

**AG2（1.1.2）**
- 社区延续 AutoGen 0.2 血脉，GroupChat/嵌套对话/swarm 成熟；**TealTiger 治理中间件是目前框架中少见的"运行时策略引擎"**：工具白名单、参数校验、提示注入拦截、PII/密钥检测与脱敏、成本预算（`BUDGET_EXCEEDED`）、限流、冻结 agent、决策回执（receipts），拒绝码结构化（`TOOL_NOT_ALLOWED`、`ARG_VALIDATION:*`、`PROMPT_INJECTION:*` 等），且"先声明先判、DENY 短路"。
- 判断：**"越权阻断"与"成本硬约束"的现成参考实现**，建议在自研策略层中借鉴其拒绝码与回执设计；不作为编排底座（无图运行时、群聊式协同难以做同路径消融）。

**MetaGPT（0.8.2，2025-03 后停滞）**
- SOP/角色/Action/共享消息池 + 发布订阅，是"软件公司模拟"的经典工作；但发布停滞、无标准 trace/HITL、工程化程度低。
- 判断：**只作文献参考**（SOP 思想、角色分工），不作为依赖。

**其他值得关注**
- **Agno 3.1.4**：轻量、性能导向的多智能体框架，适合快速原型；治理/审计仍需自建。
- **smolagents 1.26.0**：代码写作型（CodeAgent）轻量框架，适合"LLM 写代码调工具"的范式参考，但金融数值安全需强约束。
- **Strands Agents 1.61.1**（AWS）：模型/工具抽象 + 多智能体编排，云厂商生态型。
- **DSPy 3.4.1**：用于提示/程序自动优化，可作为"提示词版本化与优化"实验工具，但不是编排框架。
- **MCP 2.3.0 / A2A**：工具与 agent 互操作协议；本项目工具层可用 MCP 风格 manifest 描述（schema + 权限 + 版本），**不必引入 MCP 运行时**；A2A 可作为未来跨系统扩展。

### 2.4 关键维度深评（对选型真正重要的四点）

**(1) 编排范式：本项目需要"显式阶段图 + 共享证据库"，而不是"群聊自由讨论"。**
金融预警流程天然是阶段化的：数据快照 → 三主体独立分析 → 证据共享 → 冲突识别 → 协调/仲裁 → 核验门 → 输出/人工复核。群聊（AutoGen/AG2）把控制权交给 LLM 选择下一个发言者，**难以保证同一输入下三配置可比**；图（LangGraph/ADK/MAF/Pydantic Graph）能表达阶段，但领域证据总线仍要自建。自研阶段图的成本最低且最透明（阶段列表是显式的 Python 数据），同时天然支持"消融=删阶段"。

**(2) 结构化输出：框架级 schema 校验只解决"格式合法"，不解决"数值/引用正确"。**
PydanticAI、OpenAI SDK、ADK、CrewAI 都能让 LLM 输出符合 JSON schema；但"数值是否等于工具计算结果""引用是否真存在于原文"必须由独立核验器完成。因此**选型不应以 schema 能力为主要区分点**，而应以"能否在每一步插入核验/审计钩子"为主要区分点——这正是自研编排器的优势。

**(3) 工具权限：只有 AG2 TealTiger 提供了较完整的策略层，其余都需要自建。**
本项目的"越权阻断"是研究贡献（P2/P3 的一部分），**必须做到可配置、可消融、可审计**：策略不能藏在框架内部，必须成为我们自己的 `ToolPolicy` 模块，才能对不同角色做差异化白名单、对 as_of 参数做强制注入、对拒绝行为做统计。框架内置权限（如 OpenAI 的 approvals、MAF 的审批）粒度不够且不可控。

**(4) tracing：框架 trace 是"运行级 span"，论文需要"证据/主张级事件"。**
LangSmith/Logfire/OTel 能回答"第几步调了哪个模型、用了多少 token"，但论文附录需要回答"这条数值主张来自哪次工具调用、哪个数据版本、哪个 as_of""哪条引用对应原文 span 的哪个偏移""哪个越权调用被哪条策略拒绝"。因此 trace 分两层：**领域事件层（自建，主数据）+ OTel span 层（可选导出，便于通用工具查看）**。

---

## 3. 选型建议：自研轻量编排器 vs LangGraph

### 3.1 决策矩阵（权重按本项目诉求设定，1–5 分）

| 维度（权重） | 自研轻量编排器 | LangGraph | PydanticAI（作库） | Google ADK | CrewAI | OpenAI Agents SDK |
|---|---|---|---|---|---|---|
| 精确控制编排（25%） | **5** | 4 | 3 | 4 | 2 | 2 |
| 可审计 trace 领域字段（20%） | **5** | 3 | 3 | 3 | 2 | 2 |
| 三配置同路径消融（20%） | **5** | 3 | 2 | 3 | 2 | 2 |
| 预算强制与成本对账（10%） | **5** | 2 | 3 | 2 | 2 | 2 |
| 5 人日交付速度（10%） | 3 | 3 | **4** | 2 | 4 | 4 |
| 生态 / 文档 / 招聘（5%） | 2 | **5** | 3 | 3 | 3 | 4 |
| 版本稳定性 / 迁移风险（5%） | **5** | 3 | 4 | 2 | 3 | 2 |
| Web 演示与部署便利（5%） | 4 | 4 | 3 | 3 | **5** | 4 |
| **加权总分** | **4.60** | **3.30** | **2.95** | **3.00** | **2.45** | **2.40** |

### 3.2 结论与适用条件

**默认结论：自研轻量编排器（约 1.5–2k 行核心代码），LangGraph 作为参考实现与迁移备选。**

- ✅ 选**自研**，当：目标是可审计/可消融的研究原型；需要严格同路径三配置；需要领域级 trace 与预算硬约束；交付窗口 ≤2 周；团队 2–3 人。
- ⚠️ 改选 **LangGraph**，当满足任一：① 需要长期平台化（多租户、可视化编排、生产级持久化与监控）；② 需要复杂的图动态性与 time-travel 调试；③ 团队已熟练掌握 LangGraph 且能承受 1–2 天学习成本；④ 项目从"5 日 MVP"升格为"3 个月以上产品"。
- ❌ 不选 **CrewAI / MetaGPT / AG2 / AutoGen 0.7** 作为核心：抽象与本研究诉求错位（角色扮演 DSL、群聊自治、维护模式）。
- ❌ 不选 **ADK / MAF** 作为核心：企业云栈重、2.0 破坏性变更、5 日窗口不合适。
- ◐ **PydanticAI 可选择性引入**：若不想自写"模型调用 + 工具循环 + 输出校验"，可用其 `Agent` 作为单步执行库，但调度、证据总线、预算、审计仍自研；代价是引入一个 2.x 依赖与学习成本（团队若 1 天内能掌握则收益为正）。
- 🔁 **"借用而非依赖"清单**（从 LangGraph 借鉴到自研实现）：`StateGraph` 状态机语义、checkpointer 快照、`interrupt()/Command(resume)` 的中断恢复模型、多模式 streaming 事件、time-travel 调试思路；实现上可用"阶段列表 + SQLite run/step 表 + JSON 快照"达到 80% 效果。

### 3.3 自研最小依赖集（建议锁版本）

| 类别 | 选型 | 说明 |
|---|---|---|
| 数据校验 | `pydantic>=2.x` + `pydantic-settings` | 全部消息/证据/claim/config/trace 模型 |
| 模型调用 | `openai`/`anthropic` 官方 SDK 或 `litellm` | 统一多模型；自建 `LLMClient` 包装：usage、价格表、缓存、重试、超时 |
| HTTP/并发 | `httpx` + `asyncio` | 并行的三主体分析与工具调用 |
| Web 演示 | `fastapi` + `uvicorn` + `sse-starlette` + 轻量前端（原生 JS 或 Jinja2） | SSE 推送事件流；不引入前端构建链 |
| 存储 | `sqlite3`（标准库）/ `aiosqlite` + JSONL | run/step/evidence/claim/trace 表；JSONL 作为审计原件 |
| 检索 | `rank_bm25` 或 `sentence-transformers` + `faiss`/`chroma` | 先用 BM25 快速验证 as_of 过滤与引用溯源，向量检索可延后 |
| 评测 | `pytest` + `pydantic-evals`（可选） | 规则化单测优先（数值/引用/权限），LLM 评测辅助 |
| 可观测（可选） | `opentelemetry-sdk` + `langfuse`/`logfire` | 领域事件为主，OTel 导出为辅（P1） |
| 文档/录屏 | Markdown + 截图 + 录屏工具 | 演示脚本固定、缓存回放 |

### 3.4 与论文第四章的映射

| 论文章节 | 工程模块 | 论文可写内容 |
|---|---|---|
| 4.1 多模态融合 | `data/fusion.py`、`features.py` | 数值-文本时点对齐、特征组消融 |
| 4.2 知识与工具增强 | `rag/`、`tools/`、`ToolPolicy` | 可溯源 RAG、工具计算、越权阻断 |
| 4.3 三主体智能体 | `agents/regulator.py` 等 + `schemas` | 角色目标/输入/权限/输出契约 |
| 4.4 协同与决策支持 | `orchestrator.py`、`coordinator.py`、`verifier.py` | 证据共享、分歧识别、核验闭环、HITL |
| 5.2 消融实验 | `runner.py` + `RunConfig` | 四种配置与模块开关矩阵 |
| 6.2/6.3 结果 | `trace` 统计 + 指标脚本 | 数值一致性、引用准确率、决策损失、成本 |

---

## 4. 可验证 / 可审计 LLM 智能体的工程模式

### 4.1 数值主张核验（numeric consistency）

**核心原则：LLM 不产生数值，只"引用"确定性工具的结果。** 所有 `numeric` 类型主张必须携带 `tool_call_id` 或 `evidence_id`，由核验器重算/比对；LLM 自行推算的数字一律标记为 `llm_inference` 并降低可信等级（默认不得进入最终预警数字）。

**五类核验检查（P0 全部实现，成本极低）：**
1. **存在性**：`claim.tool_call_id` 必须存在且属于同一 run；缺失 → `UNSUPPORTED_NUMERIC_CLAIM`。
2. **重算一致性**：用工具输出的 `payload`（原始输入 + 版本）重新调用/直接比对 `value`；`Decimal` 相对误差 ≤ 1e-6（可配置）；不一致 → `NUMERIC_MISMATCH`。
3. **派生一致性**：合计数、比率、方向符号（如"压力指数 0.82 > 阈值 0.75 → 高位"）、单位换算；对派生数值同样要求可重算。
4. **单位与量纲**：`unit` 必须匹配指标定义（%、bps、指数点、USD）；跨币种需显式汇率与 as_of。
5. **时效一致性**：`claim.as_of` 与 `window` 必须在数据快照覆盖范围内；使用未来数据 → `AS_OF_VIOLATION`（同时是 P2 指标）。

**文本级补充**：从最终报告中抽取数字（正则 + LLM 抽取双通道），与 claim 表匹配；未匹配的数字 → `UNSUPPORTED_NUMERIC_CLAIM`。参考：NuFact（CIKM 2025）用 LLM 上下文理解 + 外部证据核验数值断言；QuanTemp 类基准提示数值断言需要"分解-检索-比较"链路；"Think Right, Not More" 表明数值核验需要合适的推理预算而非简单加长推理；Chain-of-Verification 的"先核验再回答"只在有外部证据时可靠，不能替代工具重算；FActScore 的原子事实分解思路可用于拆分长报告中的可核验数字。

**指标（对接论文 P2）**：
`numeric_error_rate`（错误数值主张 / 全部数值主张）、`unsupported_claim_rate`（无证据/无工具支撑的论断占比）、`evidence_coverage`（有证据的主张占比）、`recompute_match_rate`（工具重算一致率）。

### 4.2 RAG 引用溯源（citation provenance）

**时点过滤是硬约束，不是提示词约束。**
- 索引层：每个 chunk 存 `{doc_id, chunk_id, publish_time, available_at, source, uri, span, quote_hash, revision}`；检索时**在代码层**强制 `publish_time <= as_of AND available_at <= as_of`，禁止靠 LLM 自行判断"是否已发布"。
- 证据粒度：**chunk + 原文 span（start/end 偏移）+ quote**；引用必须回指 span；生成后由 verifier 做子串/高相似匹配（quote 必须出现在原文对应位置）。
- 修订与泄漏：同 `doc_id` 多版本时按 `available_at` 取当时可见版本；对"事后修订/回填"的文本打标记；报告中披露历史回放的局限。
- 预训练知识泄漏：`as_of` 过滤只能约束检索，不能约束模型参数知识。缓解：① 设计"泄漏探针"（让模型在无检索条件下预测已知未来事件，统计其表现）；② 关键数字全部走工具；③ 论文中明确声明局限。参考：JFE 2026 "Chronologically consistent large language models"（时间一致训练可降低前视偏差但需专门构建）、DatedGPT（严格时间截断预训练）、"Detecting Lookahead Bias in LLM Forecasts"（用统计方法度量 LLM 预测中的前视倾向）。

**指标**：`citation_coverage`（有引用的论断占比）、`citation_precision`（引用确实支持论断的比例，规则 + 人工抽检）、`span_match_rate`（引用回指原文 span 成功率）、`temporal_violation_rate`（引用/使用 as_of 之后信息的比例 = 应严格为 0）。参考：ALCE 的"引用正确性/覆盖率"评测框架、RAGAS 的 context precision/recall/faithfulness、FActScore。

### 4.3 越权工具阻断（privilege control）

**三层策略，全部前置（调用前拒绝，拒绝不得产生副作用）：**
1. **静态白名单**：`role → allowed_tools`（监管：压力指数/外溢/DY 连通性/政策检索；投资：组合尾部损失/情景；融资：融资成本/现金流压力；协调者：只读汇总；核验器：只读校验）。越权直接 `TOOL_NOT_ALLOWED`。
2. **参数与资源约束**：`as_of`/`window`/`asset_universe`/`data_domain` 由系统注入并校验；写操作工具（若有）默认禁用或需人工审批；外部网络工具白名单化。
3. **运行时策略**：调用次数/频率上限、成本预算、敏感输出过滤、审批要求；结构化拒绝码（`TOOL_NOT_ALLOWED`、`ARG_INVALID`、`AS_OF_VIOLATION`、`BUDGET_EXCEEDED`、`APPROVAL_REQUIRED`、`RATE_LIMITED`、`OUTPUT_BLOCKED`），拒绝事件必须进入 trace 并计入 `blocked_attempts` 指标。

**防注入**：检索到的新闻/政策文本一律作为**数据**处理，不进入指令区；用分隔符与"仅可引用、不可执行"的提示约束；工具参数做 schema/正则校验；参考 CaMeL 的"能力/污点隔离"思想（把不可信数据与授权动作分离，本原语可防 77% 任务的注入攻击）、Progent 的可编程权限策略、ToolEmu 的风险沙箱评估、AgentDojo 的注入攻击评测、GuardAgent 的"守护 agent"、R-Judge / ToolSafety 的安全评测。AG2 TealTiger 的拒绝码与回执设计可作为工程模板。

**测试**：构造 20–30 条对抗提示（诱导调用他角色工具、诱导使用未来数据、诱导泄露系统提示、诱导把文本当指令），统计 `blocked_attempts`、`false_allow_rate`。

### 4.4 schema 校验（structured output contract）

- 所有跨组件接口都用 Pydantic v2 模型；LLM 输出必须通过 schema 校验，失败时**修复重试 ≤2 次**（把校验错误回传给模型），仍失败则降级为结构化错误，不产生自由文本。
- 版本化：`schema_version`、`prompt_version`、`tool_schema_hash` 写入 trace 与 manifest；消融实验可比较"有/无 schema 强校验"的影响。
- 注意：schema 合法 ≠ 语义正确；schema 校验只是第一道门，数值/引用/权限三道门不可省。

### 4.5 LLM-as-judge 的局限（不能作为主评价）

- 已知偏差：位置偏差、长度/啰嗦偏好、自我偏好（同源模型打分更高）、谄媚、格式偏好等 12 类（"Justice or Prejudice?" ICLR 2025 系统量化了 12 类偏差并给出 CALM 框架）；MT-Bench 的 judge 与人类一致性也只是"较高但非可靠"。
- **本项目原则**：P2 的主指标（数值错误率、引用准确率、越权率）必须由**确定性规则**计算；judge 仅用于"解释质量、结构完整性、易读性"等软指标，且需 ① 双模型交叉；② 人工抽检 10–20% 并报告 Cohen's κ；③ 报告 judge prompt、模型版本、采样温度；④ 对 judge 的输出同样做 schema 校验。Agent-as-a-Judge 可用于过程性评测，但成本高、且引入新的模型偏差，仅作探索项。

### 4.6 多智能体辩论 / 冲突解决代表性工作

| 工作（年份） | 任务场景 | 架构要点 | 冲突/协调机制 | 对本项目的启示 |
|---|---|---|---|---|
| **MAD: Multiagent Debate**（Du et al., ICML 2024） | 事实性/推理 | 多个 LLM 实例多轮互相阅读并批评 | 多轮辩论后收敛/投票 | 辩论确实提升事实性，但成本随轮数线性增长 → 本项目限制 ≤2 轮 + 预算上限 + 只在冲突时触发 |
| **AutoGen**（2023/2024） | 通用多 agent | 可对话 agent + GroupChat/manager/selector | 群聊轮次、manager 选择发言者 | 群聊适合开放探索；金融预警需**结构化黑板 + 显式阶段**，避免 LLM 决定流程 |
| **NLSOM / Mindstorms**（2023–2025） | 多任务推理 | 自然语言社会心智，多专家协作、黑板式共享 | 语言接口 + 多角色互评 | "分工 + 共享黑板 + 多轮反思"可作为协同机制设计依据；需加角色权限与证据溯源 |
| **TradingAgents**（2024/2025，arXiv 2412.20138） | 股票交易 | 分析师团队（基本面/情绪/技术）+ 多空研究员辩论 + 交易员 + 风险管理团队 + 反思记忆 | 多空辩论、风险团队审议、历史反思 | **与本项目三角色最接近的金融多智能体架构**；但其数值/证据核验与可审计性弱 → 本项目补强"工具重算 + 引用溯源 + 越权阻断 + trace" |
| **FinCon**（NeurIPS 2024） | 单股/组合决策 | Manager–Analyst 层级 + 风险控制组件 + 概念化语言强化（CVaR 信念更新） | 层级汇报 + episodic 自批评 | 风险目标要**显式建模**（CVaR/损失口径），不能只靠提示词；跨 episode 的"经验信念"可作为 P3 协同机制的可选增强 |
| **FinAgent**（KDD 2024） | 多模态交易 | 工具增强的基础智能体 + 多模态输入 | 工具调用 + 市场状态识别 | 工具接口设计（输入/输出/版本）比 agent 角色数量更重要 |
| **Cassandra**（IJF 2026） | 银行困境预警 | 新闻情绪 + AI 预警 | 单模型/规则 | 金融预警的"新闻→困境"链路可作外部效度参考 |
| **RAG-Enhanced LLM+RL 期货异常监控**（2026） | 期货监管 | 多 agent 监控 + RAG + RL 调度 | 分工 + 强化学习调度 | 监管类多 agent 与 RAG 结合的直接先例；注意其"监管"目标与本文监管主体对齐 |
| **TRIAG**（2026, ISWA） | 金融风险合规 | 三强化生成式 agent | 合规规则 + 生成式 | 合规约束与生成结合，可参考其约束注入方式 |

**本项目冲突分类与处理建议（重要设计决定）：**

| 冲突类型 | 定义 | 检测方法 | 处理规则 |
|---|---|---|---|
| 数值冲突 | 同一指标不同值 | 工具结果/claim 值比对（Decimal 容差） | **工具仲裁**：以同版本工具重算为准；数据版本不同则记录并重跑 |
| 证据冲突 | 不同来源对同一事实表述不一 | 证据 id/来源/时点比对 + quote 差异 | 按 source trust + 时点新旧排序；仍不一致 → 记入 `evidence_conflict` 并披露 |
| 解释冲突 | 同一证据不同推断 | 语义聚类/LLM 分类（仅分类，不裁决） | 允许并存（合理分歧）；协调者汇总差异与理由，不强行统一 |
| 目标冲突 | 监管/投资/融资风险偏好不同 | 角色决策/阈值差异 | **不是错误**：输出主体差异化建议，由协调者给出"分歧账本"，必要时人工接管 |

> 关键立场：**金融场景中的"分歧"往往是主体目标差异的合理体现，不能简单用投票/多数决消除。** 协调机制应"识别 + 归因 + 披露 + 有限仲裁（仅对事实性冲突）"，这本身即是论文 4.4 的机制贡献点。

---

## 5. 针对 CBR-MAW 的具体工程建议（最重要）

### 5.1 目标架构

```
┌──────────────────────────── 演示层 Web (FastAPI + SSE) ────────────────────────────┐
│  运行面板 / 事件流 / trace 查看器 / 三配置对比 / 人工接管按钮 / 报告导出          │
└───────────────────────────────────────▲─────────────────────────────────────────────┘
                                        │ RunResult + TraceEvent
┌───────────────────────────────────────┴─────────────────────────────────────────────┐
│ 编排层 Orchestrator                                                                  │
│  RunConfig ─▶ Scheduler.plan() ─▶ [Stage...] ─▶ AgentRunner ─▶ VerificationGate ─▶  │
│  BudgetManager（前置硬约束）    TraceRecorder（领域事件）    HITLManager（中断/恢复）  │
│  MessageBus + EvidenceStore + ClaimStore（共享黑板，append-only，hash chain）        │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ 智能体层：监管 / 投资 / 融资 / 协调者 / 核验器（同一 Agent 基类，提示词与工具不同）  │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ 能力层：ToolRegistry + ToolPolicy（白名单/参数/as_of/预算/审批）                      │
│         RetrievalService（as_of 硬过滤 + span 引用）   FinancialTools（确定性数值）  │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ 数据层：数值时序快照（as_of）、政策/新闻知识库（publish_time）、情景参数、fixtures     │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**关键约束**：编排层是"显式 Python 状态机"，LLM 只负责**角色内部**的规划、工具选择与解释，**不决定阶段跳转**；所有跨角色通信走结构化消息，不走自由文本。

### 5.2 编排器核心模块清单

| # | 模块 | 优先级 | 职责 | 验收标准 |
|---|---|---|---|---|
| M1 | `config.py`（RunConfig / RunManifest） | P0 | 模式、角色、预算、模型、as_of、seed、开关、版本号 | 一次配置可完整复现一次 run；manifest 落盘 |
| M2 | `schemas.py` | P0 | 全部 Pydantic 模型（消息/证据/主张/工具/决策/trace） | JSON Schema 可导出；跨模块无裸 dict |
| M3 | `llm.py`（LLMClient） | P0 | 模型调用统一封装：结构化输出、重试、超时、缓存、usage 计量、价格表、seed/温度 | 每次调用记录 token/cost/latency；缓存命中可复现 |
| M4 | `budget.py`（BudgetManager） | P0 | run/agent/阶段三级 token 与成本预算；调用前预估、调用后对账、超限降级或中断 | 超限行为可配置且入 trace；三配置同总预算可强制 |
| M5 | `trace.py`（TraceRecorder） | P0 | 领域事件 JSONL + SQLite 双写；hash chain；OTel 映射（可选） | 任一最终数字可沿 trace 回溯到工具调用与数据版本 |
| M6 | `tools/registry.py` + `tools/policy.py` | P0 | 工具注册（schema/版本/只读或计算）、角色白名单、参数校验、as_of 注入、拒绝码 | 越权测试 100% 阻断并留痕；无副作用 |
| M7 | `tools/financial.py` | P0 | 风险测度（VaR/CVaR/ES）、DY 连通性、情景分析、预测器封装 | 纯函数、可重算、版本固定；输入输出带证据元数据 |
| M8 | `rag/index.py` + `rag/retriever.py` | P0 | 文档入库（publish_time/available_at/span/hash）、BM25/向量检索、as_of 硬过滤 | 任何检索结果满足 `publish_time <= as_of`；引用可回指 span |
| M9 | `agents/base.py` + 5 个角色 | P0 | 统一 Agent 基类（上下文、工具白名单、输出 schema）；角色提示词模板 | 角色输出全部过 schema；角色间无越权工具 |
| M10 | `scheduler.py` + `orchestrator.py` | P0 | 阶段图、并行执行、消息投递、共享策略、协调策略 | 三配置差异只在 config/策略，`git diff` 无角色逻辑分叉 |
| M11 | `verifier.py` | P0 | 数值/引用/权限/schema 四类核验，输出 `VerificationReport` | 注入错误数字/伪造引用能被 100% 检出（测试集） |
| M12 | `coordinator.py` | P1 | 冲突识别、归因、有限仲裁、分歧账本、最终汇总 | 冲突分类正确率人工抽检；合理分歧不被强行统一 |
| M13 | `hitl.py` | P1 | 中断点、待办持久化、恢复 API、审批记录 | 中断后进程重启可恢复并继续 |
| M14 | `runner.py`（消融运行器） | P0 | 配置矩阵、重复实验、指标聚合、结果表/图 | 一条命令产出三配置对比表 + 成本表 |
| M15 | `report.py` | P1 | 报告渲染（含证据附录、claim 表、核验状态） | 报告内每个数字可点击回 trace |
| M16 | `web/app.py` + 前端 | P0 | 运行、事件流、trace 查看、HITL、对比视图 | 演示脚本 5 分钟内跑通；断网可缓存回放 |
| M17 | `data/fixtures/` | P0 | 2–3 个历史情景（含 as_of 快照与标签）、知识库小样本 | 可离线复现；时点对齐已验证 |

> P0 为 MVP 必须项；P1 可在 D4–D5 完成或延后；P2 见 §5.7。

### 5.3 消息 / 证据 / claim 的 schema 要点

```python
# 证据：可溯源的最小单元
class Evidence(BaseModel):
    evidence_id: str                 # ev_yyyy..., 由 payload_hash + 元数据派生，稳定可查
    run_id: str
    source: Literal["market_db", "policy_doc", "news", "knowledge", "tool_output"]
    doc_id: str | None
    chunk_id: str | None
    span: tuple[int, int] | None     # 原文起止偏移，引用必须回指
    quote: str | None                # 原文摘录；数值证据可为空
    quote_hash: str | None           # sha256(quote)，防篡改
    publish_time: datetime           # 发布时间
    available_at: datetime           # 系统实际可获取时间（>= publish_time）
    as_of: datetime                  # 本次运行时点
    uri: str | None
    tool_name: str | None
    tool_version: str | None
    payload: dict                    # 结构化数值/元数据（工具输出）
    payload_hash: str
    trust: Literal["authoritative", "documented", "model_output"]

# 主张：LLM 输出的最小可核验单元
class Claim(BaseModel):
    claim_id: str
    run_id: str
    agent: Literal["regulator", "investor", "financier", "single", "coordinator"]
    claim_type: Literal["numeric", "directional", "causal", "policy", "recommendation"]
    statement: str
    metric: str | None
    value: Decimal | None
    unit: str | None
    window: str | None               # 如 "t-20 ~ t"
    as_of: datetime
    evidence_ids: list[str] = []
    tool_call_id: str | None
    derivation: Literal["tool", "rag", "llm_inference"]
    confidence: float = Field(ge=0, le=1)
    verification: Literal["pending", "pass", "warn", "fail"] = "pending"

# 消息：跨角色通信（结构化，非自由文本）
class AgentMessage(BaseModel):
    msg_id: str
    run_id: str
    round: int
    sender: Literal["regulator", "investor", "financier", "coordinator", "verifier", "human"]
    recipients: list[str] = []       # 空 = 广播
    kind: Literal["task", "evidence_share", "claim", "question", "dissent", "decision", "verification"]
    content: str
    claim_ids: list[str] = []
    evidence_ids: list[str] = []
    as_of: datetime
    token_count: int = 0
    cost_usd: Decimal = Decimal("0")

# 工具调用与策略拒绝
class ToolCallRecord(BaseModel):
    call_id: str
    run_id: str
    round: int
    agent: str
    tool: str
    tool_version: str
    args: dict                       # 已脱敏
    args_hash: str
    policy_decision: Literal["allow", "deny", "require_approval"]
    deny_code: str | None            # TOOL_NOT_ALLOWED / AS_OF_VIOLATION / BUDGET_EXCEEDED ...
    result_hash: str | None
    result_summary: dict | None
    latency_ms: int
    cost_usd: Decimal = Decimal("0")

# 核验报告（最终门禁）
class VerificationReport(BaseModel):
    run_id: str
    numeric_checked: int
    numeric_failed: list[str]
    citation_checked: int
    citation_failed: list[str]
    authority_violations: list[str]
    schema_failures: list[str]
    unsupported_claim_ids: list[str]
    coverage: float
    gate: Literal["pass", "needs_human", "fail"]
    notes: str = ""
```

> 设计要点：① 所有 id 稳定可派生（hash 前缀），便于跨 run 对比；② 证据与主张分离，主张必须引用证据/工具调用；③ `trust` 区分权威数据/文档/模型输出，核验规则按 trust 分级；④ 所有模型输出都带 `derivation`，用于统计"无依据判断率"。

### 5.4 trace 记录字段

**分四层，全部落盘（JSONL 原件 + SQLite 索引），并做 hash chain（`prev_hash`）防篡改。**

| 层级 | 字段 |
|---|---|
| **run 级** | `run_id`, `config`（mode + 全部开关）, `git_commit`, `package_lock_hash`, `model_snapshot`, `prompt_version`, `schema_version`, `dataset_manifest_hash`, `as_of`, `seed`, `temperature`, `start/end`, `status`, `budget_allocated/consumed`, `metrics`, `artifacts` |
| **stage/step 级** | `stage_id`, `round`, `actor`, `span_id`, `parent_span_id`, `start/end`, `status`, `inputs_hash`, `outputs_hash` |
| **LLM 调用级** | `model`, `provider`, `params`（temperature/top_p/max_tokens/tool_choice/seed）, `messages_hash`（可选存原文）, `response_text`, `structured_output`, `tool_calls_requested`, `tokens{prompt, completion, reasoning, cached}`, `cost_usd`, `latency_ms`, `retries`, `cache_hit`, `error_code` |
| **工具/检索/核验/HITL 级** | 工具：`tool, version, schema_hash, args, result_hash, deterministic, policy_decision, deny_code, cost, latency`；检索：`query, filters(as_of), top_k, returned[evidence_ids, score, publish_time]`；核验：`checks, failed_ids, gate`；人工：`operator, action, reason, timestamp` |
| **决策级** | `decision_id, agent, action, threshold, claim_ids, dissent, human_review_required` |

**OTel 对齐（P1，可选）**：把 LLM 调用映射为 `gen_ai.*` span（`gen_ai.request.model`、`gen_ai.usage.input_tokens/output_tokens` 等），工具调用映射为 `execute_tool` span；领域事件保持自建 schema，不强行塞进 OTel。参考 OpenTelemetry GenAI semantic conventions（仍处演进期，2026 年仍在调整属性集），以及 Langfuse/Logfire 的通用 span 模型。

### 5.5 "单智能体 vs 三独立 vs 完整协同"三配置的同一代码路径

**一个入口，四个策略，零角色代码分叉：**

```python
class RunConfig(BaseModel):
    run_id: str
    as_of: datetime
    seed: int = 42
    mode: Literal["single", "independent", "collaborative"]
    roles: list[Role] = [Role.REGULATOR, Role.INVESTOR, Role.FINANCIER]
    sharing: Literal["none", "broadcast"] = "none"
    coordination: Literal["merge", "arbitrate"] = "merge"
    verification: dict[str, bool] = {
        "numeric": True, "citation": True, "authority": True, "schema": True
    }
    rag_enabled: bool = True
    tools_enabled: set[str] = ALL_TOOLS
    budget: BudgetSpec = BudgetSpec(total_tokens=90_000, total_cost_usd=3.0, total_tool_calls=30)
    max_rounds: int = 2
    models: dict[Role, str] = {"*": "<model-id>"}   # 三角色与协调者同模型，保证可比
    prompt_version: str = "p1.0"
    schema_version: str = "s1.0"
```

```python
# 同一代码路径：模式只影响 plan 与策略，不影响角色实现
def plan(cfg: RunConfig) -> list[Stage]:
    if cfg.mode == "single":
        return [Stage("universal", agents=["single"], parallel=False),
                Stage("verify", agents=["verifier"]),
                Stage("finalize", agents=["single"])]
    if cfg.mode == "independent":
        return [Stage("role_task", agents=cfg.roles, parallel=True),
                Stage("merge", agents=["merger"]),          # 仅拼接，无仲裁
                Stage("verify", agents=["verifier"]),
                Stage("finalize", agents=["single"])]
    # collaborative：同一角色任务 + 共享/冲突/协调/核验/人工门
    return [Stage("brief", agents=["coordinator"]),
            Stage("role_task", agents=cfg.roles, parallel=True),
            Stage("share", agents=["all"], sharing="broadcast"),
            Stage("detect_conflicts", agents=["coordinator"]),
            Stage("arbitrate", agents=["coordinator", "verifier"]),
            Stage("verify", agents=["verifier"]),
            Stage("finalize", agents=["coordinator"])]
```

**公平性控制（论文 5.2/5.3 的可比性关键）：**
1. **同一套角色提示词模板**：single 模式下把三份角色任务说明拼接给一个 agent（不另写提示词）；independent/collaborative 用同一角色模板。
2. **同一模型/参数/种子/温度**；同一 `as_of` 数据快照；同一工具集合（single 合并白名单，独立/协同按角色白名单）。
3. **总预算对齐**：设总 token 上限 `T`。single 用 `T`；independent 每角色 `T/3`；collaborative 每角色 `T/3` 并预留 10–15% 协调预算（从 `T` 中扣，而非额外追加）——这样比较的是"同等资源下的协同收益"。另做一组"每角色同额 + 协调额外计入成本"的稳健性对照。
4. **固定最大轮数**（2 轮）与重试上限；相同 scenario 集、相同评价脚本。
5. **报告实际消耗**（tokens、成本、工具调用、时延、HITL 次数），而不是只报结果——协作成本本身是 P3 的因变量。

**消融矩阵（同一 runner 配置驱动）：**

| 配置 | RAG | 工具 | 证据共享 | 协调/仲裁 | 核验门 | 说明 |
|---|---|---|---|---|---|---|
| S1 单智能体 | ✅ | ✅ | — | — | ✅ | 合并任务 |
| S2 三独立 | ✅ | ✅(分角色) | ❌ | merge | ✅ | 无共享、无仲裁 |
| S3 完整协同 | ✅ | ✅(分角色) | ✅ | arbitrate | ✅ | 主实验组 |
| A1 | ❌ | ✅ | ✅ | arbitrate | ✅ | RAG 消融 |
| A2 | ✅ | ❌ | ✅ | arbitrate | ✅ | 工具消融（P2） |
| A3 | ✅ | ✅ | ❌ | arbitrate | ✅ | 共享消融（P3） |
| A4 | ✅ | ✅ | ✅ | merge | ✅ | 仲裁消融（P3） |
| A5 | ✅ | ✅ | ✅ | arbitrate | ❌ | 核验消融（P2） |
| A6 | ✅ | ✅ | ✅ | arbitrate | ✅ | 3 次重复 × 固定 seed，报告方差 |

> 实现技巧：`verification` 是 dict，可逐项关闭；`sharing/coordination` 是枚举；`rag_enabled/tools_enabled` 是布尔/集合。所有开关都写入 `RunManifest`，runner 自动生成矩阵与结果表。

### 5.6 预算与成本统计方法（可复现的关键）

- **计量点唯一**：所有模型调用必须经过 `LLMClient`；在返回处读取 `usage`（prompt/completion/reasoning/cached tokens），用本地价格表（可参考 `genai-prices`，或自维护 JSON）折算 `cost_usd`；**禁止绕过封装直接调 SDK**。
- **前置预算**：调用前按"输入 token 估算 + max_output_tokens"预扣，超限则触发降级（缩短上下文/跳过可选步骤/请求 HITL）；调用后按实际 usage 对账。
- **预算分配**：总预算 → 阶段预算 → 角色预算；协调/核验预算独立列支；输出 `budget_report.json`（分配/实际/差异）。
- **缓存**：以 `hash(model + params + messages + tool_schema_hash)` 为 key 缓存响应（可选 TTL），演示与重复实验时显著降本并提升可复现性；报告需注明缓存命中率。
- **成本可比**：三配置报告同一格式的成本表（tokens/成本/工具调用/时延），并给出"单位预警任务成本"。

### 5.7 5 人日 MVP 范围建议

| 天 | 目标 | 交付物 | 验收 |
|---|---|---|---|
| **D1**（1 人日） | 骨架与计量：仓库结构、`config/schemas/llm/budget/trace`、工具注册表与策略、2 个仿真情景 fixtures、1 个真实数值工具（VaR/CVaR）+ 1 个情景工具；pytest 覆盖 schema/预算/策略 | 可运行的最小 runner：单 agent 读取 fixture → 调工具 → 结构化输出 → trace 落盘 | `pytest` 通过；trace 能回溯任一数字到工具与快照 |
| **D2**（1 人日） | 知识层与核验：RAG 索引（50–200 文档，带 publish_time/span/hash）、as_of 过滤、检索；数值核验器 + 引用核验器 + 主张抽取；错误注入测试集 | `Verifier` 可对报告做四类核验并给出门禁结论；伪造数字/引用 100% 检出 | 核验测试集全绿；as_of 违规为 0 |
| **D3**（1 人日） | 三角色与两配置：角色提示词、工具白名单、单/独立模式并行执行、三配置对比 runner 雏形；首次端到端 | `runner.py --mode single` 与 `--mode independent` 分别产出报告 + trace + 成本表 | 两配置同一 scenario 均能跑通；角色无越权 |
| **D4**（1 人日） | 协同与消融：证据共享、冲突识别（数值优先）、协调者、核验门、HITL 中断/恢复；三配置 + A1–A5 消融 | `runner.py --suite all` 产出对比表；HITL 可中断/恢复 | 三配置差异只体现在 config；冲突账本可读；成本表完整 |
| **D5**（1 人日） | 演示与文档：FastAPI + SSE + 事件/trace/对比视图、演示脚本、录屏、第四章 4.2–4.4 初稿、复现 manifest、冻结版本 | 可演示的 Web 页面 + 录屏 + 文档初稿 | 5 分钟内完整演示；断网缓存回放可用 |

**必须做（P0）**：数值工具 + as_of RAG + 三角色 + 三配置同路径 + claim/evidence schema + 数值/引用/权限核验 + trace + 预算 + HITL 基本中断 + Web 演示 + 第四章 4.2–4.4 初稿。

**可延后（P1/P2）**：多轮辩论（>2 轮）、语义级冲突（NLI/嵌入）、协调者复杂仲裁策略、OTel 全量导出、Langfuse/Logfire 接入、认证/多用户、生产数据库、真实行情数据接入、图像/音频模态、统计检验与置信区间（需要更多重复与样本，论文阶段再做）、LangGraph 迁移或适配层。

**明确不做（避免范围蔓延）**：复杂前端框架、实时协作编辑、模型微调、生产级高可用部署、多租户权限系统。

### 5.8 评价指标映射（对接论文 P1–P3）

| 命题 | 指标 | 数据来源 | 备注 |
|---|---|---|---|
| P1 多模态信息增益 | PR-AUC、召回率@阈值、Brier/ECE 校准、预警提前期 | 预测输出 + 标签 | 固定 as_of、固定预测期限（5/10/20 交易日） |
| P2 知识与工具增强 | `numeric_error_rate`、`unsupported_claim_rate`、`citation_precision/coverage`、`span_match_rate`、`authority_violation_rate`、`schema_pass_rate` | Verifier + trace | 主指标全确定性规则；judge 仅辅助 |
| P3 协同增益 | 任务完成率、主体决策损失（监管漏警/投资尾部损失/融资成本压力）、协作成本（token/成本/工具调用/时延/HITL 次数）、冲突解决率 | RunResult + 成本表 | 同一总预算下比较；报告单位任务成本 |
| 稳健性 | 重复实验方差、阈值/期限敏感性、模型版本替换 | runner 矩阵 | 固定 seed + 缓存 + manifest |

### 5.9 风险清单与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| LLM 非确定性 | 结果不可复现、演示翻车 | 温度 0 + seed + 响应缓存 + 快照 manifest + 重复实验报告方差；演示用缓存回放 |
| 框架/依赖版本漂移 | 临期升级破坏 | 不引入重型框架；`uv.lock`/`pip-tools` 锁版本；D5 冻结；记录 `git_commit` + `lock_hash` |
| 预训练知识泄漏 | 高估 P1 | as_of 硬过滤 + 泄漏探针 + 论文明确披露局限；关键数字全部走工具 |
| 提示注入（新闻/政策文本） | 越权/输出污染 | 文本仅作数据、分隔符、工具参数校验、策略层阻断、对抗测试集 |
| Judge 偏差 | P2 指标失真 | 规则优先；judge 双模型 + 人工抽检 + 报告 κ |
| 范围蔓延（UI/功能） | 5 日交付风险 | P0 清单驱动；UI 只做"运行/事件/trace/对比/HITL"五件套 |
| 多人并行改动冲突 | 集成失败 | 模块 owner 制 + 接口冻结（D1 结束）+ 每日集成 + Lead 最终 review |
| 演示环境/网络问题 | 录屏失败 | 本地 fixtures + 缓存 + 离线模式；提前彩排 2 次 |

### 5.10 建议目录结构（只做规划，不在本次交付中创建）

```
docs/research/multi_agent_frameworks.md     # 本报告
src/cbrmaw/
  config.py  schemas.py  llm.py  budget.py  trace.py  hitl.py
  orchestrator.py  scheduler.py  runner.py  report.py
  tools/{registry.py, policy.py, financial.py}
  rag/{index.py, retriever.py}
  agents/{base.py, regulator.py, investor.py, financier.py, coordinator.py, verifier.py}
  web/{app.py, static/}
data/fixtures/{scenario_2022_stress/, scenario_2023_calm/, knowledge/}
scripts/run_ablation.py
docs/ch4_method.md
```

---

## 6. 选型落地 checklist（开工前 30 分钟核对）

- [ ] 版本冻结：`uv lock` / `pip freeze`，记录 Python 版本、模型快照名、价格表版本。
- [ ] 接口冻结：`schemas.py` 中 `Evidence/Claim/AgentMessage/ToolCallRecord/VerificationReport/TraceEvent/RunConfig` 七个模型评审通过。
- [ ] 预算口径：三配置总预算数值、分配规则、超限行为（降级/中断）写进 `RunConfig` 并测试。
- [ ] 核验口径：数值容差（1e-6）、timeout、重试次数、门禁三态（pass/needs_human/fail）确定。
- [ ] 时点口径：`as_of` 与 `publish_time/available_at` 的语义、时区、修订处理写进文档。
- [ ] 角色权限：三角色工具白名单 + 禁止项 + 越权测试用例（≥20 条）定稿。
- [ ] 演示脚本：固定 1 个主 scenario + 1 个对照 scenario；录屏分镜与缓存回放方案确定。
- [ ] 分工与 owner：D1–D5 每项有唯一负责人；接口变更需 Lead 批准。

---

## 7. 参考来源

### 7.1 框架 / 平台官方资料（检索于 2026-10-18）

- LangGraph v1 发布说明：<https://docs.langchain.com/oss/python/releases/langgraph-v1>
- LangGraph v1 迁移指南：<https://docs.langchain.com/oss/javascript/migrate/langgraph-v1>
- LangGraph 包（PyPI）：<https://pypi.org/project/langgraph/>
- LangChain 文档：<https://docs.langchain.com/>
- LangSmith：<https://docs.langchain.com/langsmith/home>
- OpenAI Agents SDK 文档：<https://openai.github.io/openai-agents-python/>
- OpenAI Guardrails / approvals 指南：<https://developers.openai.com/api/docs/guides/agents/guardrails-approvals>
- OpenAI Agents SDK 沙箱与可恢复会话更新（DevOps.com，2026-04）：<https://devops.com/openai-upgrades-its-agents-sdk-with-sandboxing-and-a-new-model-harness/>
- PydanticAI 文档：<https://ai.pydantic.dev/>
- PydanticAI HITL 工具审批 PR #2581：<https://github.com/pydantic/pydantic-ai/pull/2581>
- PydanticAI 耐久执行（AWS Lambda）：<https://pydantic.dev/articles/harness-aws-lambda>
- Google ADK 2.0 文档：<https://adk.dev/2.0/>
- adk-python：<https://github.com/google/adk-python>
- CrewAI 文档：<https://docs.crewai.com/>
- CrewAI changelog（1.15.x，含 checkpoint/事件系统）：<https://docs.crewai.com/v1.15.22/en/changelog>
- AutoGen：<https://github.com/microsoft/autogen>
- Microsoft Agent Framework：<https://github.com/microsoft/agent-framework>
- MAF 包信息（workflow/checkpoint/HITL/OTel）：<https://libraries.io/pypi/agent-framework-core>
- AG2 文档：<https://docs.ag2.ai/>
- AG2 releases：<https://www.ag2.ai/developers/releases>
- AG2 TealTiger 治理：<https://docs.ag2.ai/docs/user-guide/extensions/tealtiger/>
- MetaGPT：<https://github.com/geekan/MetaGPT>
- OpenTelemetry GenAI semantic conventions：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- Model Context Protocol：<https://modelcontextprotocol.io/>
- Langfuse：<https://langfuse.com/>
- Pydantic Logfire：<https://logfire.pydantic.dev/>

### 7.2 论文与基准（arXiv 编号已用 arXiv API 核对）

- TradingAgents: Multi-Agents LLM Financial Trading Framework（2024/2025）：<https://arxiv.org/abs/2412.20138>
- FinCon: A Synthesized LLM Multi-Agent System（NeurIPS 2024）：<https://arxiv.org/abs/2407.06567>；<https://papers.nips.cc/paper_files/paper/2024/hash/f7ae4fe91d96f50abc2211f09b6a7e49-Abstract-Conference.html>
- FinAgent: A Multimodal Foundation Agent for Financial Trading（KDD 2024）：<https://doi.org/10.1145/3637528.3671801>
- Improving Factuality and Reasoning in Language Models through Multiagent Debate（MAD, ICML 2024）：<https://arxiv.org/abs/2305.14325>
- AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation：<https://arxiv.org/abs/2308.08155>
- Mindstorms in Natural Language-Based Societies of Mind / NLSOM：<https://arxiv.org/abs/2305.17066>；<https://ieeexplore.ieee.org/document/10903668>
- Chain-of-Verification Reduces Hallucination in LLMs：<https://arxiv.org/abs/2309.11495>
- Self-Consistency Improves Chain of Thought Reasoning：<https://arxiv.org/abs/2203.11171>
- RAGAS: Automated Evaluation of Retrieval Augmented Generation：<https://arxiv.org/abs/2309.15217>
- Enabling Large Language Models to Generate Text with Citations（ALCE）：<https://arxiv.org/abs/2305.14627>
- FActScore: Fine-grained Atomic Evaluation of Factual Precision：<https://arxiv.org/abs/2305.14251>
- Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena：<https://arxiv.org/abs/2306.05685>
- Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge（ICLR 2025）：<https://arxiv.org/abs/2410.02736>
- Agent-as-a-Judge: Evaluate Agents with Agents：<https://arxiv.org/abs/2410.10934>
- Identifying the Risks of LM Agents with an LM-Emulated Sandbox（ToolEmu）：<https://arxiv.org/abs/2309.15817>
- AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses：<https://arxiv.org/abs/2406.13352>
- Defeating Prompt Injections by Design（CaMeL）：<https://arxiv.org/abs/2503.18813>
- Progent: Securing AI Agents with Privilege Control：<https://arxiv.org/abs/2504.11703>
- GuardAgent: Safeguard LLM Agents by a Guard Agent：<https://arxiv.org/abs/2406.09187>
- R-Judge: Benchmarking Safety Risk Awareness for LLM Agents（EMNLP 2024 Findings）：<https://aclanthology.org/2024.findings-emnlp.79/>
- ToolSafety（EMNLP 2025）：<https://aclanthology.org/2025.emnlp-main.714/>
- NuFact: Validating Numerical Assertions for Knowledge Graphs（CIKM 2025）：<https://dl.acm.org/doi/10.1145/3746252.3760844>
- A Benchmark for Open-Domain Numerical Fact-Checking Enhanced by Claim Decomposition：<https://arxiv.org/abs/2510.22055>
- Think Right, Not More: Test-Time Scaling for Numerical Claim Verification：<https://arxiv.org/abs/2509.22101>
- Detecting Lookahead Bias in LLM Forecasts：<https://arxiv.org/abs/2512.23847>
- DatedGPT: Preventing Lookahead Bias in LLMs with Time-Aware Pretraining：<https://arxiv.org/abs/2603.11838>
- Chronologically consistent large language models（Journal of Financial Economics, 2026）：<https://www.sciencedirect.com/science/article/pii/S0304405X26001455>
- Cassandra: AI-based surveillance to forecast bank distress from financial news（International Journal of Forecasting, 2026）：<https://www.sciencedirect.com/science/article/abs/pii/S0169207026000518>
- RAG-Enhanced LLM and RL Scheduling: Multi-Agent Framework for Abnormal Futures Price Monitoring（2026）：<https://dl.acm.org/doi/full/10.1145/3795154.3795432>
- TRIAG: Tri-reinforced infused generative agents for financial risk compliance（2026）：<https://doi.org/10.1016/j.iswa.2026.200653>
- StillMe: 透明可验证 RAG 系统（2025）：<https://zenodo.org/records/17637315>

### 7.3 研究局限（诚实声明）

1. 本报告**未做同任务运行时基准**（时间预算 20–30 分钟）：版本、特性、API 以官方文档 + PyPI 实测为准；性能、稳定性、实际 token 开销需在选型 spike 中实测。
2. 部分框架能力描述来自官方文档的"宣称"（如耐久执行、成本追踪），未经本项目环境验证；正式使用前建议 0.5 人日 spike：用同一小任务（1 次工具调用 + 1 次 RAG + 1 次结构化输出）分别跑 LangGraph / PydanticAI / 自研骨架，比较代码量、trace 字段覆盖、预算控制、消融切换成本。
3. 框架版本迭代极快（如 ADK 1.x→2.0、AutoGen→MAF、OpenAI SDK 0.x→1.0 预期），本报告结论有约 1–2 个月时效性；开工前重新核对版本。
4. 论文引用（如 TradingAgents/FinCon 的实验结论）按原文摘要陈述，未独立复现。
