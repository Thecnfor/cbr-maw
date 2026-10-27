# CBR-MAW 文档导航（INDEX）

> 本页是全部文档的唯一入口。所有链接均指向仓库内真实文件；本页中的相对链接按 `docs/` 目录解析（指向仓库根时用 `../`）。
> 维护约定：新增/移动文档时同步更新本页与 [README 文档索引](../README.md#8-文档索引)。

---

## 1. 按角色进入

### 1.1 新读者（第一次接触项目）

| 顺序 | 文档 | 说明 |
|---|---|---|
| 1 | [README](../README.md) | 一句话定位、核心特性、架构概览、快速开始 |
| 2 | [docs/guides/quickstart.md](guides/quickstart.md) | 从零跑通：环境、数据、测试、API、UI |
| 3 | [试运行截图](assets/screenshots/dashboard-light.png) | 驾驶台实拍（[运行进度](assets/screenshots/run-progress-light.png)、[对话](assets/screenshots/chat-light.png)） |
| 4 | [docs/techdoc/pilot_results_synthetic.md](techdoc/pilot_results_synthetic.md) | 试点实验结论（SYNTHETIC 数据，读结论前必看数据声明） |

### 1.2 开发者 / 贡献者

| 文档 | 说明 |
|---|---|
| [CONTRIBUTING.md](../CONTRIBUTING.md) | 开发环境、分支与提交规范、PR 检查清单 |
| [AGENTS.md](../AGENTS.md) | 仓库结构、角色分工、任务看板、验证命令、写入范围（面向 AI agent 与人类协作者） |
| [架构设计 v1](architecture/CBR-MAW_architecture_v1.md) | 六层架构、模块映射、关键机制、实现细节 |
| [AI-native 交互契约](design/ai-native-interaction-spec.md) | SSE 契约、前端交互与状态约定 |
| [流式接口备注](design/streaming-api-notes.md) | 后端 SSE 实现、事件序列、回退语义 |
| [web/README.md](../web/README.md) | 前端技术栈、目录、端口、路由、验证结果 |
| [web/DESIGN-NOTES.md](../web/DESIGN-NOTES.md) | 设计系统、token 映射、规范偏离与验收记录 |
| [docs/guides/troubleshooting.md](guides/troubleshooting.md) | 常见问题（Mock LLM、无 key、端口、bun、数据缺失） |
| [docs/guides/realtime-ingestion.md](guides/realtime-ingestion.md) | 实时智能抓取（L1.5）：来源配置、缺口分析、多源回退、增量写库、`/api/ingest/*` |
| [执行 Harness 选型（ADR）](architecture/adr-2026-10-27-agent-harness.md) | OpenHands / Python+TS 二开的 harness 契约与选型 |
| [可选基础设施与 RAG（ADR）](architecture/adr-2026-10-27-infra-and-rag.md) | PG/Redis/Mongo/向量库的可降级接入、混合检索设计 |
| [docker-compose.yml](../docker-compose.yml) · [configs/infra.yaml](../configs/infra.yaml) | 可选基础设施一键起停与配置 |

### 1.3 研究者 / 论文读者

| 文档 | 说明 |
|---|---|
| [技术文档第四章（Markdown）](techdoc/chapter4_method.md) | 方法章 v1.0：融合信号、知识与工具、三类智能体、协同与核验、实现组织 |
| [技术文档第四章（Word）](techdoc/第四章_多模态多智能体协同预警方法.docx) | 排版稿（由 `scripts/md_to_docx.py` 生成） |
| [章节大纲与写作计划](techdoc/chapter4_outline.md) | 第四章结构与边界 |
| [open issues 清单](techdoc/open_issues.md) | EXP/INT/DOC/LIM 待办与关闭记录（版本头 v1.0） |
| [SYNTHETIC 试点结果](techdoc/pilot_results_synthetic.md) | Mock LLM 下的 P1/P2/P3 流程验证 |
| [真实数据试点结果](techdoc/pilot_results_real_data.md) | 真实数据 + 真实 DeepSeek 的 P1/P2/P3（含诚实边界） |
| [真实 LLM 试点报告](techdoc/pilot_results_real_llm.md) | 真实 DeepSeek 的 P2/P3 复跑、token/成本/延迟 |
| [v1.0.0 发布说明](releases/v1.0.0.md) | 正式发布内容、验证清单、已知限制与升级方式 |
| [多智能体框架调研](research/multi_agent_frameworks.md) | 框架选型与可信工程模式 |
| [数据源实测报告](research/data_sources.md) | 公开数据源可得性、PIT 口径与标签方案 |

### 1.4 团队协作者 / 发布负责人

| 文档 | 说明 |
|---|---|
| [docs/guides/team-collaboration.md](guides/team-collaboration.md) | 多人/多 agent 并行协作：任务看板、写入范围、依赖、验证门禁 |
| [docs/guides/deployment.md](guides/deployment.md) | 本地/服务器部署、uvicorn、`/ui`、环境变量、反向代理注意 |
| [docs/guides/real-data.md](guides/real-data.md) | 真实数据接入：目录、`data_mapping.yaml`、PIT 口径、校验 |
| [docs/guides/experiments.md](guides/experiments.md) | P1/P2/P3 与 E0–E12 消融矩阵怎么跑、结果在哪 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) · [CHANGELOG.md](../CHANGELOG.md) | 贡献流程与版本演进 |
| [v1.0.0 发布说明](releases/v1.0.0.md) · [CITATION.cff](../CITATION.cff) | 正式发布内容、验证清单、引用信息 |
| [LICENSE](../LICENSE) | MIT 许可证全文（Copyright © 2026 Thecnfor） |
| [SECURITY.md](../SECURITY.md) · [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | 安全报告与行为准则 |

---

## 2. 按主题浏览

### 2.1 架构与方法

| 文档 | 版本 | 内容 |
|---|---|---|
| [architecture/CBR-MAW_architecture_v1.md](architecture/CBR-MAW_architecture_v1.md) | v1.0 | 实现定稿：六层架构、模块映射、R0–R5、核验、API/UI、实验 harness |
| [architecture/CBR-MAW_architecture_v0.md](architecture/CBR-MAW_architecture_v0.md) | v0（草案） | 设计草案与 v1 差异背景 |
| [techdoc/chapter4_method.md](techdoc/chapter4_method.md) | v1.0 | 方法章正文：5 图 / 13 表 / 21 公式 |
| [techdoc/chapter4_outline.md](techdoc/chapter4_outline.md) | v0.5 | 写作计划与边界 |

### 2.2 实现与设计契约

| 文档 | 内容 |
|---|---|
| [design/ai-native-interaction-spec.md](design/ai-native-interaction-spec.md) | SSE 端点契约、前端 RunProgress / ⌘K / 上下文追问 |
| [design/streaming-api-notes.md](design/streaming-api-notes.md) | 后端流式实现：heartbeat、trace tail、超时、回退 |
| [web/DESIGN-NOTES.md](../web/DESIGN-NOTES.md) | 视觉与交互裁决记录（token、组件、a11y、动效） |

### 2.3 操作指南

| 文档 | 适用场景 |
|---|---|
| [guides/quickstart.md](guides/quickstart.md) | 首次跑通（Windows / Linux） |
| [guides/real-data.md](guides/real-data.md) | 接入自建真实数据、重建 PIT |
| [guides/deployment.md](guides/deployment.md) | 本地/服务器部署、进程与端口、环境变量 |
| [guides/experiments.md](guides/experiments.md) | 复现 P1–P3 与消融矩阵 |
| [guides/troubleshooting.md](guides/troubleshooting.md) | 报错与异常排查 |

### 2.4 实验与数据产物

| 文档 | 内容 |
|---|---|
| [techdoc/pilot_results_synthetic.md](techdoc/pilot_results_synthetic.md) | SYNTHETIC 数据试点：P1 指标、P2/P3 流程 |
| [techdoc/pilot_results_real_llm.md](techdoc/pilot_results_real_llm.md) | 真实 DeepSeek：18 runs / 54 calls、tokens 与成本 |
| [techdoc/open_issues.md](techdoc/open_issues.md) | 待办：EXP/INT/DOC/LIM 与关闭记录 |
| [data/real_data_integration.md](data/real_data_integration.md) | 真实数据接入全链路：来源、27 条序列覆盖、PIT/派生口径与复现命令 |
| [data/public_gap_fill.md](data/public_gap_fill.md) | 公开数据补齐：缺失序列、来源、PIT 规则与覆盖 |
| [data/text_corpus.md](data/text_corpus.md) | 真实文本语料：来源、抽样、时点化与已知偏差 |
| [data/samples/README.md](../data/samples/README.md) | 仿真数据说明与 SYNTHETIC 声明 |

### 2.5 图片与其它材料

| 资源 | 说明 |
|---|---|
| [docs/assets/screenshots/](assets/screenshots/) | README 使用的 5 张关键 UI 截图（light/dark/运行进度/命令面板/对话） |
| [docs/techdoc/figures/](techdoc/figures/) | 第四章 5 张 Mermaid 渲染图与 manifest |
| [docs/research/](research/) | 调研报告与探测日志（`probe_*.log`） |
| [docs/todo.txt](todo.txt) | 早期内部 TODO（历史材料，非当前计划源） |
| [docs/direction2_extracted.txt](direction2_extracted.txt) | 方向 2 原始材料抽取文本（论文背景） |

---

## 3. 文档维护约定

1. **单一事实源**：数字以代码/配置/实测产物为准；文档只引用，不重复造数。版本头（`docs/techdoc/*`）每次实质修改都递增并写明变更。
2. **链接必须有效**：提交前运行断链检查脚本（见 [团队协作指南 §6](guides/team-collaboration.md#6-验证命令)），相对路径以文件自身位置解析。
3. **不引用不入库文件**：`data/raw/`、`data/custom/`、`artifacts/`、`secrets/`、`.env` 与用户原始数据压缩包不得作为文档链接目标。
4. **论文口径**：涉及实验结果时区分「pilot 指针」与「正式结果」；不显著结论不得写成显著提升（见 [open_issues §0](techdoc/open_issues.md)）。
5. **截图统一放** `docs/assets/screenshots/`，用语义化文件名（如 `dashboard-light.png`），README 只引用这里。
