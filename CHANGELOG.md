# CHANGELOG

本文件记录 CBR-MAW 的重要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
版本号约定：采用语义化版本；`v0.8.0` 为首个公开发布准备版，**`v1.0.0` 为首个正式发布版**；**`v2.0.0` 为实时化版本（L1.5 实时智能抓取 + 可选基础设施/RAG + 执行 Harness）**；v0.1–v0.7 按技术文档第四章版本头与提交顺序回溯整理，v0.5 / v0.6 同批提交按主题拆分。日期为提交日期（2026-10-18 / 2026-10-20）。

---

## [2.0.0] - 2026-10-27

### 实时智能抓取（L1.5 数据接入层）
- 新增 `src/cbr/ingest/`：声明式数据源（`configs/sources.yaml`）+ 确定性缺口/陈旧度分析（`gaps.py`）
  + 抓取器（`http_csv` / `http_json` / `akshare` / `rss`）+ **多源回退**（同序列主源失败自动切备源）
  + 增量写 PIT（`PitStore.upsert_observations` / `upsert_documents` / `touch_coverage`）
  + 派生序列实时重算（`derive.py`）+ 进程内调度器与运行时（`scheduler.py` / `runtime.py`）。
- 新增 API `/api/ingest/{status,sources,freshness,plan,refresh}`；`/api/health` 增补 `ingest` 状态块。
- 新增 `data.dataset: pit` 模式（显式使用 PIT 存储的 provider，供实时抓取热刷新）；
  `PitStoreDataProvider` 增补 `detach()/reload()`：写入前释放只读连接、写入后热刷新数据集。
- 新增指南 [docs/guides/realtime-ingestion.md](docs/guides/realtime-ingestion.md)（用法/加源/边界/验证）。

### 可选基础设施与 RAG
- 新增 `docker-compose.yml`（postgres+pgvector / redis / mongo / qdrant）与 `configs/infra.yaml`。
- 新增 `src/cbr/infra/`：健康探测（标准库 socket）+ 可选客户端（缺驱动/不可达一律 `None` 降级）。
- 新增 `src/cbr/knowledge/vector.py`：可插拔向量化（默认离线 `HashingEmbedding`）+ 向量库
  （默认 `NumpyVectorStore`，可选 Qdrant / pgvector）+ BM25·向量加权 RRF 混合检索。

### 执行 Harness
- 新增 `src/cbr/harness/`：稳定契约（`AgentHarness`/`TaskSpec`/`RunResult`）+ 进程内实现
  + 远程适配器（OpenHands / Python+TS 二开）与 `configs/harness.yaml`；选型见 ADR。

### 工程
- 测试新增 `tests/test_ingest.py`、`tests/test_infra.py`、`tests/test_rag_vector.py`、`tests/test_harness.py`。

### 修复
- 腾讯备源 SP500 改用 `us.INX` 代码（`usINX` 仅返回当日 1 行）；JSON 路径新增键序列写法，
  以寻址键本身含 `.` 的端点（如 `data.us.INX.day`）。
- 向量库适配新版 `qdrant-client`（`search` → `query_points`，含旧版回退）；
  pgvector 读写改用 pgvector 向量字面量，修正真实服务下的检索失败。

---

## [1.0.0] - 2026-10-20

**首个正式发布版本（研究性原型 v1.0.0）。** 聚合 v0.1–v0.8 全部能力，完成真实数据接入、真实数据试点与发布工程化；默认数据仍为 SYNTHETIC，真实数据需本地重建。

### 发布内容
- **真实数据**：用户 zip + 飞书 Base「07 沪深港通资金流」 + 飞书文本语料（9,758 篇） + 公开接口补齐 14 条序列；快照 2015-01-05~2025-09-30、2,615 交易日 / 27 序列 / 57,421 观测 / 9,758 文本（`ds_94c8b84b60cd1248dd57`）；PIT `data/pit_real.duckdb`、模型 `artifacts_real/fusion-xgb-v1@20250904`。
- **真实数据试点（真实 DeepSeek）**：P1（1,152 日；数值-only PR-AUC 0.695/0.632/0.612，文本增益不显著）、P2（4 日 × full/no_tools；tool_evidence_gated 1 vs 0）、P3（4 日 × 三模式；冲突全解决但 decision_loss 无差异）。详见 `docs/techdoc/pilot_results_real_data.md`。
- **AI-native 交互**：SSE 流式 `/api/decision/stream`、`/api/chat/stream`；驾驶台 RunProgress、⌘K 命令面板、上下文追问、协同过程时间线、流式对话与克制动效；`web/dist` 入库，FastAPI `/ui` 免构建托管。
- **工程质量**：全量 pytest **249 项通过**；ruff 门禁、仓库卫生（大文件/密钥）与 Markdown 链接检查通过；`bun run build` 通过且产物可复现；CI（Python 3.12 + Web）与发布工程文件就绪。
- **文档**：第四章 v1.0（Markdown + DOCX，14 表 / 5 图）；架构 v1；README/AGENTS/CONTRIBUTING/SECURITY/CHANGELOG/INDEX/guides 完整；发布说明 `docs/releases/v1.0.0.md`。

### 已知限制
- 真实数据部分序列为明示代理口径；北向 2024-08-16 停披露、CPI 2015–2020 缺失；真实数据 P1 文本增益与 P3 协同决策收益均不显著，按 pilot 级报告，不构成投资或监管建议。
- 原始数据与 `data/custom/` 不入库，克隆后需按 `docs/data/real_data_integration.md` 本地重建；默认数据为 SYNTHETIC。

## [0.8.0] - 2026-10-20

首个公开发布准备版（tag `v0.8.0`）：真实数据接入、AI-native 交互、SSE 流式、文档体系与仓库治理；历史条目见下。


### 真实数据（v0.8，2026-10-20）
- 接入用户真实数据：`docs/金融数据.zip`（B1 汇率/B2 利率/B3 股债/B4 全球因子/B6 宏观）、飞书 Base「07 沪深港通资金流」（14,459 行）、飞书「文本数据8.2」（9,758 篇文本）；公开接口补齐 14 条缺失序列（2Y/10Y 国债、信用利差、PMI、标普500、VIX、US10Y、CNH、AH 溢价、中证500、成交额、社融、外储、LPR）。
- 新增 `scripts/build_real_custom_data.py`、`fetch_public_gaps.py`、`fetch_public_extra.py`、`build_text_corpus.py`；`configs/app.real.yaml`（custom-only、`synthetic_fallback:false`、`artifacts_real`）；`build_dataset.py --custom-only`；provider 新增 `data.synthetic_fallback` 开关。
- 真实数据快照：2015-01-05~2025-09-30、2,615 交易日、27 序列、57,421 观测、9,758 文档（`ds_94c8b84b60cd1248dd57`）；PIT `data/pit_real.duckdb`、模型 `artifacts_real/fusion-xgb-v1@20250904`。
- 真实数据试点：P1（1,152 日，数值-only PR-AUC 0.695/0.632/0.612；文本增益不显著）、P2（4 日 × full/no_tools，真实 DeepSeek）、P3（4 日 × 三模式，真实 DeepSeek）；详见 `docs/techdoc/pilot_results_real_data.md`。
- 文档：`docs/data/real_data_integration.md`、`text_corpus.md`、`public_gap_fill.md`；第四章 v0.8（4.1.1 + 附录 A.3）；架构 v1 §7；README/AGENTS/real-data 指南同步。

### 文档
- 重写根 [README.md](README.md) 为 GitHub 项目主页视角：定位、特性、架构 Mermaid、Windows/Linux 快速开始、目录、API、配置、实验、文档索引、许可证与免责声明。
- 新增 [docs/INDEX.md](docs/INDEX.md)（按角色导航）与 `docs/guides/` 五篇指南：quickstart、real-data、deployment、experiments、troubleshooting。
- 新增 [CONTRIBUTING.md](CONTRIBUTING.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)、[SECURITY.md](SECURITY.md)、[AGENTS.md](AGENTS.md)、[CHANGELOG.md](CHANGELOG.md)。
- 新增 `docs/guides/team-collaboration.md`（多 agent/多人并行：任务看板、写入范围、依赖、验证命令）。
- 新增 `docs/assets/screenshots/`：5 张关键 UI 截图（light/dark、流式运行、命令面板、对话），README 引用。
- 修正 [docs/techdoc/open_issues.md](docs/techdoc/open_issues.md) 版本头（v0.4 → v0.8，与实际内容一致）。
- 全仓 Markdown 相对链接检查：断链 0 处。

### 工程化（与仓库工程化/CI 任务并行合入，按仓库实际文件为准）
- 新增 [LICENSE](LICENSE)（MIT，Copyright © 2026 Thecnfor）、`requirements-dev.txt`（ruff / pytest-cov / pre-commit）。
- `pyproject.toml`：项目元数据、MIT 许可证声明、`[project.optional-dependencies] dev`、ruff 规则。
- 其余（`.github/` CI 与 Issue/PR 模板、`.gitignore`/`.gitattributes`、pre-commit、仓库校验脚本）随该任务合入后在此补充。

### 发布（2026-10-20，v0.8 首发）
- **公开发布**：仓库推送到 GitHub 公开仓库 <https://github.com/Thecnfor/cbr-maw>，默认分支 `main`。
- `README.md` / `docs/INDEX.md`：方法章版本号统一 v0.7 → **v0.8**；快速开始补 `git clone`；[AGENTS.md](AGENTS.md) / [CONTRIBUTING.md](CONTRIBUTING.md) 分支与发布地址同步为 `main`。
- `web/src/styles/index.css`：显式 `@source not "../../dist"`，修复 Tailwind v4 自动扫描已入库 `web/dist` 导致的构建不幂等；重跑 `bun run build`，`web/dist` 产物逐字节不变。
- `pyproject.toml` 启用 `[project.urls]`；Issue 模板 `config.yml` 启用 quickstart / troubleshooting 快捷入口。

---

## [v0.7] - 2026-10-18

提交：`2062f86`（feat(ai-native): SSE 流式 decision/chat + AI-native 驾驶台；docs: v0.7）

### 新增
- SSE 流式端点 `GET /api/decision/stream`、`POST /api/chat/stream`（`src/cbr/api/streaming.py`）：`run/stage/trace/decision|chat/error` 事件 + 心跳；独立 trace 目录与后台 tail；缓存命中直接返回 decision。
- 前端 AI-native 升级（`web/`）：流式 RunProgress（R0–R5 时间线 + 三主体状态 + 实时活动流 + 取消）、`⌘K` 命令面板（`?cmd=1`）、对话流式阶段 + 打字机 + 上下文 chip + 追问建议、上下文 AI 动作（智能体卡/证据/冲突 → 对话预填）、协同过程时间线、toast/tooltip/键盘/a11y/reduced-motion。
- 流式验收脚本 `scripts/verify_stream.py`。
- 文档：[AI-native 交互契约](docs/design/ai-native-interaction-spec.md)、[流式接口备注](docs/design/streaming-api-notes.md)；第四章 v0.7；架构与 open_issues 同步。

### 变更
- SSE 不可用或代理缓冲时，前端自动回退同步 `/api/decision`、`/api/chat`，并在 UI 明示「同步回退」。
- 测试：206 → **249 项**（新增 43 项 streaming 测试）。
- 前端构建：`tsc --noEmit && vite build` 通过，`web/dist` 约 1.01 MB / 7 文件（首屏 gzip 168.65 kB）。

### 已知限制
- LIM-11：流式每请求独立编排器 + daemon 线程，无并发上限；300s 超时只保护 SSE 连接，不取消 worker；`artifacts/traces/stream-*` 按 `CBR_STREAM_TRACE_RETENTION`（默认 50）清理。

---

## [v0.6] - 2026-10-18

提交：`e9cf530`（与 v0.5 同一批次，按主题拆分）

### 新增
- DeepSeek 真实接入：`DeepSeekClient`（OpenAI 兼容、JSON mode + Pydantic 校验、重试、token 统计），与 `MockLLM` 同一接口，按 key 自动切换。
- P2/P3 真实 LLM 复跑：18 次运行 / 54 次调用全部成功，0 错误/超时/Schema 失败/重试/降级；实际 tokens 323,431，费用约 ¥0.70–0.88；报告 [pilot_results_real_llm.md](docs/techdoc/pilot_results_real_llm.md)。
- 指标 v2（`scripts/run_experiment.py`）：`task_completion_tool_evidence_gated`、`llm_tokens_actual`/`llm_calls_actual`、`trace_claim_rejected`/`trace_tool_denied`/`trace_budget_exceeded`。
- 决策缓存（30 分钟 TTL，`refresh=true` 强制重算）。

### 变更
- 第四章 v0.6：同步真实 LLM 复跑与指标口径；open_issues 增加 EXP-13/EXP-14、LIM-09/LIM-10。
- 已知限制：终卡 `numeric_error_rate=0` 为自检回填 + 证据过滤后的饱和值（LIM-09）；12,000 token 记账预算低于真实 prompt，报告 tokens 偏低约 33%（LIM-10）。

---

## [v0.5] - 2026-10-18

提交：`e9cf530`（与 v0.6 同一批次）

### 新增
- React 19 + Vite + Tailwind v4 + shadcn/ui 规范驾驶台与对话页（`web/`）：light/dark 双主题、248px 侧栏 + 52px 顶栏、KPI 区、3:2 主网格（信号/归因/模态贡献/三智能体卡 ↔ 证据板/分歧协调/核验/数据卡/导出）、证据 Dialog、对话引用与关联决策卡、Markdown/JSON/JSONL 导出。
- FastAPI 以 `/ui` 静态托管前端构建产物；`/` 307 跳转 `/ui/`。
- 设计规范文档 [web/DESIGN-NOTES.md](web/DESIGN-NOTES.md) 与 [web/README.md](web/README.md)。

### 变更
- 主 UI 从 Streamlit 切到 React；Streamlit 保留为回退入口。
- 架构 v1 更新 L6；第四章 v0.6 增补前端与 `/ui` 托管。

---

## [v0.4] - 2026-10-18

提交：`ef67980`（test: 自建数据接入端到端测试）

### 新增
- 自建数据接入端到端测试（`tests/test_custom_data.py`）：custom 目录 + `configs/data_mapping.yaml` 映射 + PIT 读取。
- 文档更新验证计数（205 项）。

### 变更
- 数据层装配优先级明确：custom → PIT DuckDB → samples → 内存仿真兜底。

---

## [v0.3] - 2026-10-18

提交：`2ab398c`（feat: 完成 CBR-MAW 原型）

### 新增
- 完整原型：数据/特征/模型/工具/知识库/三角色智能体/协同编排/核验/API/Streamlit UI/实验 harness。
- 技术文档第四章 v0.5 + DOCX；架构设计 v1；P1–P3 试点结果；数据源与多智能体框架调研。
- 7 个确定性工具与权限矩阵；R0–R5 协同协议；六类核验 + 审计 trace。

---

## [v0.2] - 2026-10-18

提交：`99fbbfd`（contract: DecisionCard.evidence snapshot + env ready）

### 新增
- `DecisionCard.evidence` 黑板快照字段；环境配置就绪（`.env`、密钥文件约定）。

---

## [v0.1] - 2026-10-18

提交：`5f98d92`（scaffold: shared schemas/contracts/configs + architecture v0）

### 新增
- 项目骨架：共享 `schemas`/`contracts`/`configs`；架构设计 v0；目录与依赖基线。

---

## 版本与发布约定

1. **版本号**：语义化版本；已发布 tag：`v0.8.0`（公开准备版）、`v1.0.0`（正式发布版）；技术文档第四章版本头与发布版本同步（v1.0）。
2. **变更分类**：`新增` / `变更` / `修复` / `移除` / `安全` / `已知限制`。
3. **数据声明**：所有实验结论默认基于 SYNTHETIC 仿真数据，需在对应条目中注明；不显著结论不得写成显著提升。
4. 面向用户的变更必须同步 README / `docs/`；安全相关变更同步 [SECURITY.md](SECURITY.md)。
