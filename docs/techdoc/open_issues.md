# 第四章 open issues / TODO 清单（待实验、待实现、待同步）

> 维护：doc-writer（task-6）｜版本：v1.0（2026-10-20 正式发布）｜代码快照：真实数据接入 + 真实数据 P1/P2/P3 + AI-native 交互 + SSE 流式 + 249 项测试
> 对应正文：[chapter4_method.md](chapter4_method.md) v1.0（5 图 / 14 表 / 21 公式；4.1.1 真实数据快照、附录 A.3；4.5.1 React 前端与 `/ui`、SSE 端点）
> 增量：§10 记录真实数据接入（27 序列 / 9,758 文本 / PIT `ds_94c8b84b60cd1248dd57`）与真实数据 P1/P2/P3 结果；历史 §0–§9 保留 synthetic 口径。
> 用途：把正文中所有"待实验/待验证/待实现/待同步"点收敛为可逐条关闭的清单；每关闭一项在文末"关闭记录"追加日期与说明。
> 状态取值：`open` / `in-progress` / `closed` / `accepted`（已知限制，不计划关闭但需在论文中报告）。

## 0. 集成与数据快照（2026-10-18）

**已验证通过（Lead 联调 + 复测）**
- 装配：`cbr.service.build_service()` 成功装配 data / knowledge / tools / llm(MockLLM) / orchestrator；工具 7 个；数据卡 27 条；知识库 29 篇语料 / 32 chunks。
- 数据：`scripts/build_dataset.py` 已重建 `data/pit.duckdb`；`pit_manifest.json`：series_obs **41,367**、documents **2,207**、series_meta **27**；`dataset_snapshot_id=ds_1beab3f3ffd9e31a4c5b`、`corpus_hash=corpus_7ac20be6ce7d622c8308`（2018-01-02～2025-09-30，synthetic=true，built_at 2026-10-18T15:46:49）。provider 统一走 `PitStoreDataProvider`（`PitStore.asof`），不回退样例数据；序列别名由 `SERIES_ALIASES` 归一（`crossborder.*` → `crossborder.flows.*`）。
- 测试：`tests/test_data.py` + `tests/test_models.py` → **25 passed（0 failed）**；文本/标签 PIT 口径已修（同日 15:00 前新闻当日可用；标签训练期参数同一 `train_end`，非泄漏）；series 命名测试通过。
- API 端到端：`GET /api/decision?as_of=2024-08-05&mode=collaborative` → 200（6.4s 含装配），cards=3、evidence=20、conflicts=4（全 resolved）、`verification.passed=true`（numeric_error_rate=0、evidence_accuracy=1.0、leakage=0、permission=0、schema=0）；`coordination.rounds=1、tool_calls=17、tokens=11792、latency_ms=2474、cost_usd=0.0535`；`POST /api/chat` → 200（10 citations 含 decision）；`/api/health`、`/api/scenarios` 正常；Streamlit AppTest 6 tab 正常。
- 三模式 single / independent / collaborative 均产出决策卡；tokens 11355 / 11349 / 11902（预算 12000）；HITL 本轮 1 项 high_risk escalated。
- **DGP（仿真数据）**：2021–2025 每年 1–3 个压力事件；冲击前 8–18 个交易日可观测累积期；文本语料内嵌约 5–8 个交易日领先风险语义（部分因子滞后进入压力过程）→ 设计上文本有增量。详见数据卡与 `data/samples/README.md`。

**P1 pilot（240 日，内部数字指针；正式 6.1 前不得写成"显著提升"）**
- h5 PR-AUC：numeric 0.478 → fusion 0.504（Δ+0.026，p=0.112）
- h10：0.428 → 0.451（Δ+0.023，p=0.088）
- h20：0.351 → 0.354（Δ+0.003，p=0.653）
- Recall@10%：0.429 / 0.333 / 0.143（h5/h10/h20）
- 结论口径：方向为正、均不显著；正文 6.1 需按"不显著/适用边界"如实报告，禁止写成"显著提升"。

## 1. 实验类（EXP）——待第五章/第六章数据

| ID | 位置（正文） | 待验证内容 | 关闭判定 | 建议责任方 | 状态 |
|----|--------------|------------|----------|------------|------|
| EXP-01 | 4.1.5、表 4-2 第 1 行、6.1 | P1：numeric+text 相对 numeric-only 的样本外增量（PR-AUC、top-decile、Brier、ECE、提前期、配对 bootstrap CI） | pilot 240 日已记录（见第 0 节，方向为正、不显著）；正式 6.1 结果表/图待论文阶段补入（样本区间、置信区间、分期限） | 实验负责人 | **closed（pilot 指针已记录；正式 6.1 若扩样可 reopen）** |
| EXP-02 | 4.2.4、表 4-2 第 2 行、6.2 | P2：知识检索降低无依据断言率、提高证据准确率（E4 vs E3） | 6.2 给出三类 P2 指标对比与置信区间 | 实验负责人 | open（前置 INT-04/EXP-08） |
| EXP-03 | 4.2.4、表 4-2 第 3 行、6.2 | P2：工具调用降低数值错误率、越权被阻断（E5、E6 vs E3） | 6.2 区分检索贡献与专业计算贡献 | 实验负责人 | open（前置 INT-04/EXP-08） |
| EXP-04 | 4.3.1、表 4-2 第 4 行、6.3 | P3：专业化分工价值（E6/E7/E9）与伪分工对照（E8） | 6.3 报告任务完成率与主体决策损失差；伪分工无优势时说明适用边界 | 实验负责人 | open（前置 INT-04/EXP-08） |
| EXP-05 | 4.4.5、表 4-2 第 5 行、6.3 | P3：证据共享贡献（E9 vs E10） | 6.3 给出决策损失、重复证据率与成本差 | 实验负责人 | open（前置 INT-04/EXP-08） |
| EXP-06 | 4.4.5、表 4-2 第 6 行、6.3 | P3：交叉验证与冲突协调贡献（E9 vs E11/E12） | 6.3 给出冲突解决率、数值错误率、决策损失与 J=L+μC | 实验负责人 | open（前置 INT-04/EXP-08） |
| EXP-07 | 4.4.4、表 4-2 第 7 行、5.3/6.3 | P2/P3：人工接管与审计（人工复核触发率、可复现率） | 6.3/6.4 报告 HITL 触发率与 trace 重放验证 | 实验负责人 + ui-api | open |
| EXP-08 | 4.5.2、表 4-9 | 消融矩阵 E0–E12：`scripts/run_experiment.py` 已验证（P1 pilot 由该 runner 产出），但 `configs/experiments/` 仍只有 `p1_modality.yaml`，E3–E12 无配置文件 | 每个 E 编号有 YAML 与 run_id，一键运行产出 `artifacts/runs/<run_id>/` | eval/data-model | in-progress |
| EXP-09 | 4.1.1、4.5.2、4.5.3、6.4 | 稳健性替换：预测期、阈值模式（frozen/rolling）、标签口径（B0/B1/B2）、模型版本、成本权重 μ、多重比较校正 | 6.4 给出敏感性表并说明结论是否稳健 | 实验负责人 | open |
| EXP-10 | 4.4.2、6.4、`configs/scenarios.yaml` | 典型情景回放（5 个情景）：预警产生、工具使用与协调过程复盘 | 6.4 每个情景给出回放图/表与"事前信息集"说明 | 实验负责人 + ui-api | open |
| EXP-11 | 4.1.2、5.1 | 预训练知识泄漏对照：无预训练基线或时间截断提示对照 | 5.1 给出对照设计与结果，正文 4.1.2/4.5.4 同步 | 实验负责人 + agent-core | open |
| EXP-12 | 4.5.3 | 统计检验落地：`metrics.py` 已有 `bootstrap_ci`/`paired_bootstrap_test`，runner 已存在；实验输出是否写入 `MetricResult.ci_low/ci_high` 待验证（pilot 未报告 CI） | `metrics.json` 每项含置信区间，论文表格按 CI 报告 | eval | in-progress |

## 2. 集成/实现类（INT）

| ID | 位置（正文） | 现状与关闭判定 | 建议责任方 | 状态 |
|----|--------------|----------------|------------|------|
| INT-01 | 4.5.1、附录 A `DataProvider` | `build_service()` 可装配（OrchestratorImpl + 7 工具 + 27 数据卡） | data-model | closed |
| INT-02 | 4.1、4.5.1 | `risk_signal(2024-08-05)` 返回完整 RiskSignal（horizons / drivers=6 / modality_contrib / evidence_id） | data-model | closed |
| INT-03 | 4.5.1、4.5.2 | `scripts/run_experiment.py` 已存在并跑出 P1 pilot；p1 研究流水线可执行 | eval/data-model | closed |
| INT-04 | 4.5.2、表 4-9 | `configs/experiments/` 仍只有 `p1_modality.yaml`；E3–E12 配置缺失（P2/P3 实验前置） | eval | open |
| INT-05 | 4.2.2、附录 A | `report_export` 由 UI 导出承担（Markdown 简报 / JSON 数据包 / trace JSONL） | ui-api | closed |
| INT-06 | 4.4.4 | `HITLQueue` 提供 enqueue/auto_process/approve/reject/override 且 run() 自动处理留痕；驾驶台目前只显示 escalated/人工介入提示，无交互式审批面板 | ui-api | in-progress |
| INT-07 | 4.0.3、4.4.4、附录 A | API 端到端已通（附录 A.2 列 7 端点）；DecisionCard 四类字段与只读复核接口可用 | ui-api | closed |
| INT-08 | 4.5.1、6.4 | `docs/` 下尚无演示脚本/录屏使用说明；`artifacts/runs/` 尚无正式实验产物（演示任务③） | Lead/kk + ui-api | open |
| INT-09 | 4.1.2、4.1.3 | data-model 修复后 `tests/test_data.py`+`tests/test_models.py` 25 passed / 0 failed；文本/标签 PIT 口径与 series 别名统一 | data-model | closed |
| INT-10 | 4.1.2、4.5.1 | PIT 已由 `scripts/build_dataset.py` 重建（41,367 观测 / 2,207 文档 / 27 序列），manifest 含 snapshot id 与 corpus hash；provider 不再回退 | data-model | closed |

## 3. 文档同步类（DOC）——v0.5 终核完成

| ID | 位置（正文） | 核对/修订内容 | 状态 |
|----|--------------|----------------|------|
| DOC-01 | 4.4.2 R0–R5 | R2 按角色轮转每人复核 1 条（原写"1–2 条"已修正）；HITL 高风险触发为 `critical`（原写"高或极高"已修正）；rounds/cost/escalated 已按实现 | closed |
| DOC-02 | 4.4.4 | DecisionCard 运行时字段填充（evidence/verification/coordination/final_advice/trace_ref）已写入 | closed |
| DOC-03 | 4.4.4、附录 A | trace 路径（`artifacts/traces/<run_id>.jsonl`、`.decision.json`）、trace_ref 与 `/api/trace/{run_id}` 已写入 | closed |
| DOC-04 | 附录 A | A.1 模块接口（含 get_evidence/get_trace）、A.2 七个 HTTP API 端点 | closed |
| DOC-05 | 4.5.1 目录树、表 4-8 | 目录树覆盖实际包（features/models/agents/api/app）；表 4-8 数据行补 `PitStoreDataProvider`；tests/scripts 明细不入正文 | closed |
| DOC-06 | 4.5.2 | p1 配置示例已同步 `agents.enabled: false`；P2/P3 配置新增后需补引用（依赖 INT-04） | closed（p1） |
| DOC-07 | 表 4-2、表 4-9 | E 编号与最终实验 YAML/run_id 对齐（依赖 INT-04） | open |
| DOC-08 | 全章 | v0.5 终检：11,937 汉字（不含表格代码）、5 图、13 表、21 公式，编号/引用/表格校验通过；4.5.1 补 PIT snapshot 与数据卡 27 条、4.5.4 补合成数据限制 | closed |

## 4. 已关闭/已确认（CLS）

| ID | 事项 | 关闭依据 |
|----|------|----------|
| CLS-01 | `RoleRegistry` 实现与装配 | `RoleRegistryImpl`/`load_role_registry()`；正文 4.3.1、附录 A |
| CLS-02 | P1 配置 `agents.mode: offline` | 改为 `agents.enabled: false`；4.1.5、4.5.2 |
| CLS-03 | 指标命名不一致 | `recall_at_top_decile`/`precision_at_top_decile` + `METRIC_ALIASES`；4.5.3 |
| CLS-04 | 协同成本配置缺失 | 4 个成本参数入 app.yaml/OrchestrationSettings；4.4.5、附录 B |
| CLS-05 | 标签口径 B0/B1/B2 | 4.1.1：B1 主分析、B0/B2 稳健性 |
| CLS-06 | 阈值模式（frozen/rolling） | 4.1.1 可配置、主分析 frozen；(4-3) 与符号表 $W_\tau$ |
| CLS-07 | `configs/tools.yaml` 缺失 | 已落地；4.5.2、附录 B |
| CLS-08 | `report_export` 口径 | 维持协调层能力单列；UI 导出已承担 |
| CLS-09 | `DecisionCard.evidence` | schemas 已增加；4.4.4 已写 |
| CLS-10 | 装配路径 | 4.5.1 改为 `build_service()` + `get_service()` |
| CLS-11 | rounds/cost/escalated 语义 | 4.4.2/4.4.5 已按实现 |
| CLS-12 | API 与只读复核接口 | 附录 A.1/A.2 |
| CLS-13 | 决策卡运行时字段 | 4.4.4 已写 |
| CLS-14 | trace 落盘路径 | 4.4.4 已写 |
| CLS-15 | 数据快照与数据卡口径 | 4.5.1 写入 snapshot id / corpus hash / 41,367 观测 / 2,207 文档 / 27 序列 / 27 数据卡；表 4-8 数据行补 `PitStoreDataProvider` |
| CLS-16 | 合成数据限制 | 4.5.4 增第九条：DGP 内嵌文本领先语义，真实数据文本增量可能有限 |
| CLS-17 | R2 复核条数与 HITL 触发等级 | 4.4.2 改"每人 1 条、按角色轮转"；4.4.4 改"极高（critical）" |

## 5. 已接受限制（LIM，不设关闭条件，需在 6.4/7.2 报告）

| ID | 正文位置 | 限制 | 处理方式 |
|----|----------|------|----------|
| LIM-01 | 4.5.4 第二 | 模型预训练知识泄漏无法完全消除 | 5.1 对照（EXP-11）+ 7.2 局限 |
| LIM-02 | 4.5.4 第三 | 风险标签构造主观性 | 6.4 稳健性（EXP-09） |
| LIM-03 | 4.5.4 第四 | 公开数据覆盖差异、缺失与修订 | 数据卡 + 敏感性分析 |
| LIM-04 | 4.5.4 第五 | LLM 版本漂移与非确定性 | 温度 0、固定版本、mock 复现、记录种子 |
| LIM-05 | 4.5.4 第六 | 决策损失权重为情景假设 | 限情景内相对比较 |
| LIM-06 | 4.5.4 第七 | 协同成本未计组织协调与人工复核 | 7.2 说明成本估计偏乐观 |
| LIM-07 | 4.5.4 第八 | 单市场/单币种情境的外部有效性 | 6.4/7.2 说明边界 |
| LIM-08 | 4.5.4 第九 | 合成数据 DGP 的文本领先语义为设计内嵌，真实数据增量可能有限 | 6.1/6.4/7.2 如实说明 |

## 6. 当前优先级（建议）

1. **EXP-02/03 + INT-04/EXP-08**（P2 实验与 E3–E6 配置）→ eval/实验负责人；P2 需同预算对照。
2. **EXP-05/06 + E7–E12 配置**（P3 协同实验）→ 实验负责人；E8 伪分工对照需单独配置。
3. **EXP-01 正式化**（P1 扩样/分期限/CI 写入 6.1）→ 实验负责人；pilot 不显著，按边界如实报告。
4. **EXP-07/INT-06/INT-08**（HITL 交互面板、演示脚本与录屏）→ ui-api/Lead；与任务③并行。
5. **EXP-09/10/11**（稳健性、典型情景回放、泄漏对照）→ 论文 6.4 与 5.1 阶段。

## 7. 关闭流程

1. 每项关闭时：在对应行改 `closed`，并在"关闭记录"追加 `日期 | ID | 变更说明 | commit/产物`。
2. EXP 项关闭只向正文 5.x/6.x 与表 4-2 填"结果指针"（表格/图/章节位置与方向性结论），不编造数字；结果不显著时按"适用边界/不显著"如实报告。
3. DOC 项关闭需同步更新 `chapter4_method.md` 版本头（v0.6…）并复检字数/图表/公式编号。

### 关闭记录（追加式）

| 日期 | ID | 变更说明 | commit/产物 |
|------|----|----------|-------------|
| 2026-10-18 | CLS-01～CLS-09 | v0.3 同步实现细节 | chapter4_method.md v0.3 |
| 2026-10-18 | CLS-10～CLS-14、DOC-02/03/04/08 | v0.4 集成后同步（装配、API、决策卡字段、rounds/cost/escalated、trace） | chapter4_method.md v0.4 |
| 2026-10-18 | INT-01/02/05/07 | 集成验证：build_service、risk_signal、UI 导出、API 端到端 | 联调快照 |
| 2026-10-18 | INT-09/INT-10/INT-03/EXP-01、CLS-15～17、DOC-01/05 | data-model 修复与 PIT 重建后终核；P1 pilot 指针入清单；R2/HITL 口径修正；正文 v0.5 | chapter4_method.md v0.5、data/pit_manifest.json |
| 2026-10-18 | INT-11/INT-12/INT-13、DOC-09 | React 驾驶台重构（`web/`，light/dark，FastAPI `/ui` 托管 + 30 分钟决策缓存）；真实 DeepSeek 复跑（p2_real/p3_real，18 runs/54 calls，0 失败）；正文 v0.6 同步 4.5.1 目录与模块表 | `web/`、`docs/architecture/CBR-MAW_architecture_v1.md`、`pilot_results_real_llm.md`、chapter4_method.md v0.6 |

---

## 8. v0.6 增量（React 前端 / 真实 LLM / 指标 v2）

### 8.1 新增集成事实

- **React 驾驶台（主 UI）**：`web/` 使用 React 19 + Vite + Tailwind v4，token 派生自 Xra-space `packages/ui/src/styles/tokens.css`，组件与信息密度遵循 `Thecnfor/design-stack` 的 shadcn-conventions 与 cross-dashboard `DESIGN.md`（Linear/Vercel 级）；light/dark 双主题、证据 Dialog、对话页、导出、skeleton/空/错状态；FastAPI 以 `/ui` 静态托管，`/` 307 跳转，`/api/decision` 增加 30 分钟缓存（`refresh=true` 强制重算）；Streamlit 保留为回退 UI。
- **真实 DeepSeek 复跑**：P2（3 日 × full/no_tools）+ P3（4 日 × 三模式），18 次运行 / 54 次 LLM 调用全部成功，0 错误/超时/Schema 失败/重试/降级；实际 API tokens 323,431，费用约 ¥0.70（上限 ¥0.88）；报告 [pilot_results_real_llm.md](pilot_results_real_llm.md)。
- **指标 v2（scripts/run_experiment.py）**：新增 `task_completion_tool_evidence_gated`（工具/KB 证据门槛）、`llm_tokens_actual`/`llm_calls_actual`（真实 API 用量）、`trace_claim_rejected`/`trace_tool_denied`/`trace_budget_exceeded`（草稿级核验），P2/P3 表头动态标注 LLM 后端；P2 单日复测：full `n_numeric_claims=11 / tool_gated=1.0`，no_tools `n_numeric_claims=0 / tool_gated=0.0 / claim_rejected=8 / tool_denied=17`。

### 8.2 新增/更新的 issue 行

| ID | 位置（正文） | 内容 | 关闭判定 | 状态 |
|----|--------------|------|----------|------|
| INT-11 | 4.4.4、4.5.1、附录 A | React 19 + Vite + Tailwind v4 驾驶台/对话，FastAPI `/ui` 托管 + 决策缓存 | `/ui/` 可访问、light/dark 截图、构建通过、API 联调 | **closed** |
| INT-12 | 4.4.4 | 设计规范落地（shadcn-conventions + Linear；token 化；a11y；reduced-motion） | token 映射表 + 截图 + DESIGN-NOTES | **closed** |
| INT-13 | 4.3、4.5.1 | DeepSeek 真实接入与 P2/P3 复跑 | 18 次运行全成功 + 报告 | **closed** |
| INT-14 | 4.4.4 | HITL 交互式审批面板（承接 INT-06）；新前端当前只读展示 escalated/待复核 | 面板可 approve/reject/override 并写 trace | open |
| EXP-13 | 4.2.4、4.4.5、6.2/6.3 | P2/P3 真实 LLM 试点（p2_real/p3_real）已完成；正式实验需扩评估日、多次重复与置信区间 | 6.2/6.3 结果表 + CI | in-progress（pilot 已有） |
| EXP-14 | 4.2.3、4.5.3 | 草稿级幻觉指标（回填前数值差异、被拒 claim 比例）与证据门槛任务完成率需正式化 | 指标定义 + 结果表 | open |
| LIM-09 | 4.2.3、4.5.4 | 真实 LLM 下终卡 `numeric_error_rate=0` / `unsupported_claim_rate=0` 是"自检回填 + 证据过滤后"的饱和值，不能解释为模型事实性 | 6.2/7.2 如实说明并用草稿级指标补充 | accepted |
| LIM-10 | 4.5.2、4.5.3 | 12,000 token 记账预算低于真实 prompt（约 18k/次，18/18 次撞上限），报告 tokens 比实际少约 33% | 正式实验校准 `max_tokens_per_agent` 或外置 Schema，并在 5.2 说明预算口径 | accepted |
| DOC-09 | 4.5.1、表 4-8 | React 前端与 `/ui` 托管、决策缓存写入正文；DOCX 需按 v0.6 重新生成 | 正文 v0.6 + DOCX 重生成 | in-progress（正文已改，DOCX 待重生成） |

---

## 9. v0.7 增量（AI-native 交互 / SSE 流式）

### 9.1 新增集成事实（2026-10-18）

- **SSE 流式端点**：`GET /api/decision/stream`、`POST /api/chat/stream`（`src/cbr/api/streaming.py`，独立 trace 目录 + 后台线程 tail + 心跳/超时/error 事件；缓存命中直接 `decision`）。真实 DeepSeek 验收：HTTP 200、`run=1 / trace=97 / stage=35 / decision=1`（14.5s）；缓存命中 0.01s 仅 `decision`；chat 流以 `chat` 收尾。
- **前端 AI-native 升级**（`web/`）：流式运行 RunProgress（R0–R5 时间线 + 三主体状态 + 实时活动流 + 取消/回退）、⌘K 命令面板（导航/场景/模式/操作/AI 快捷问、`?cmd=1`）、对话流式阶段 + 打字机 + 上下文 chip + 追问建议、上下文 AI 动作（智能体卡/证据 Dialog/冲突行 → 对话预填）、协同过程 R0–R5 时间线、toast/tooltip/键盘/a11y/reduced-motion。SSE 不可用时自动回退同步端点并在 UI 明示。
- **测试**：`249 passed`（206 基线 + 43 streaming）；`web` 构建 `tsc --noEmit && vite build` 通过（dist 约 1.01MB / 7 文件；首屏 gzip 168.65kB）。
- **截图**：`artifacts/ui-ai/`（`sse_run_progress_light.png`、`final_dashboard_light/dark.png`、`final_palette_light/dark.png`、`sse_chat_done_light.png`、`coordination_timeline_light.png` 等）。
- **契约与实现说明**：`docs/design/ai-native-interaction-spec.md`、`docs/design/streaming-api-notes.md`；前端 `web/DESIGN-NOTES.md` §15、`web/README.md`。

### 9.2 新增 issue 行

| ID | 位置（正文） | 内容 | 关闭判定 | 状态 |
|----|--------------|------|----------|------|
| INT-15 | 4.4.4、附录 A.2 | SSE 流式接口（decision/chat）与前端流式交互 | 端点 + 真实事件验收 + 43 测试 | **closed** |
| INT-16 | 4.4.4、4.5.1 | AI-native 交互（RunProgress/⌘K/上下文追问/协同过程/打字机/动效/a11y） | 功能清单 + 截图 + 构建通过 | **closed** |
| INT-14 | 4.4.4 | HITL 交互式审批面板（approve/reject/override 并写 trace）；当前 UI 只读展示 escalated | 面板可操作并写 trace | open |
| LIM-11 | 4.4.4、4.5.1 | 流式每请求独立编排器 + daemon 线程，无并发上限；300s 超时只保护 SSE 连接、不取消 worker；`artifacts/traces/stream-*` 按 `CBR_STREAM_TRACE_RETENTION`（默认 50）清理 | 在 5.2/6.4/7.2 说明资源与成本边界；正式部署加上限/队列 | accepted |
| DOC-10 | 4.5.1、附录 A.2 | 正文 v0.7 已补 SSE 端点与 AI-native 前端；DOCX 按 v0.7 重生成 | 正文 v0.7 + DOCX | **closed**（DOCX 随提交重生成） |

### 9.3 关闭记录追加

| 日期 | ID | 变更说明 | commit/产物 |
|------|----|----------|-------------|
| 2026-10-18 | INT-15/INT-16/DOC-10、LIM-11 | AI-native 交互 + SSE 流式；正文 v0.7；249 项测试；web dist 与截图 | `src/cbr/api/streaming.py`、`web/`、`docs/design/*`、`artifacts/ui-ai/` |

---

## 10. v0.8 增量（真实数据接入与真实数据实验）

### 10.1 集成事实（2026-10-20）

- **真实数据快照**：2015-01-05 ~ 2025-09-30、2,615 交易日、27 条规范序列、57,421 条观测、9,758 篇文本；`dataset_snapshot_id=ds_94c8b84b60cd1248dd57`、`corpus_hash=corpus_a7e87cba9e85e67525ae`；PIT 数据库 `data/pit_real.duckdb`，模型产物 `artifacts_real/`。
- **数据来源**：用户 `docs/金融数据.zip`（B1/B2/B3/B4/B6）+ 飞书 Base「07 沪深港通资金流」（14,459 行）+ 飞书「文本数据8.2」（9,758 篇）+ 公开接口补齐 14 条序列；脚本 `scripts/build_real_custom_data.py`、`fetch_public_gaps.py`、`fetch_public_extra.py`、`build_text_corpus.py`。
- **配置**：`configs/app.real.yaml`（`dataset: custom`、`synthetic_fallback: false`、`paths.artifacts: artifacts_real`）；默认 `configs/app.yaml` 保持 synthetic/auto，测试与离线复现不受影响。
- **真实数据 P1**（2021-01~2025-09，1,152 交易日）：数值-only PR-AUC 0.695/0.632/0.612；融合 0.684/0.639/0.617；Δ=-0.011/+0.007/+0.005，p=0.172/0.342/0.214 → **文本增益不显著**。
- **真实数据 P2**（4 个评估日，真实 DeepSeek）：full 18 claims / 17.25 工具调用 / 4.75 冲突全解决 / task_completion_tool_evidence_gated=1；no_tools_no_kb 7.5 claims / 0 工具 / 17 次越权尝试被阻断 / tool_evidence_gated=0 / claim_rejected=7.5；decision_loss 1.325 vs 1.360。
- **真实数据 P3**：见 pilot_results_real_data.md（4 个评估日 × 三模式，真实 DeepSeek）。
- 文档：`docs/data/real_data_integration.md`、`text_corpus.md`、`public_gap_fill.md`；第四章 v0.8、架构 v1 §7、README、pilot 报告同步。

### 10.2 新增 issue 行

| ID | 位置（正文） | 内容 | 关闭判定 | 状态 |
|----|--------------|------|----------|------|
| INT-17 | 4.1.1、附录 A.3 | 用户真实数据接入（27 序列 / 9,758 文本 / PIT / 真实数据 profile） | 快照构建 + provider 真实数据端到端 + 文档 | **closed** |
| EXP-15 | 4.1.5、4.5.2 | 真实数据 P1（数值 vs 融合） | 1,152 个评估日 + 配对自助法 | **closed**（文本增益不显著） |
| EXP-16 | 4.2.4、4.5.2 | 真实数据 P2（工具/知识消融，真实 DeepSeek） | 4 个评估日 × 2 变体 | **closed** |
| EXP-17 | 4.4.5、4.5.2 | 真实数据 P3（三模式协同，真实 DeepSeek） | 4 个评估日 × 3 模式 | closed（随 P3 完成） |
| LIM-12 | 4.1.1、4.5.4 | 真实数据代理口径（SHIBOR 1W→7 天回购、AAA→AA 利差、累计净流入→北向持仓、滚动增量→社融存量同比）；北向 2024-08-16 停披露；CPI 2015–2020 缺失 | 在数据卡/偏差表/正文标注，不伪装原口径 | accepted |
| LIM-13 | 4.1.5 | 真实数据文本模态增益不显著（h5 略负），语料时段不均衡（2017–2020 偏少） | 在 P1 报告与限制中如实披露；后续补语料/表征再检验 | accepted |
| DOC-11 | 4.1.1、附录 A.3、README | 真实数据章节、数据文档与 DOCX 同步 | 正文 v0.8 + 文档 + DOCX | **closed** |

### 10.3 关闭记录追加

| 日期 | ID | 变更说明 | commit/产物 |
|------|----|----------|-------------|
| 2026-10-20 | INT-17/EXP-15/16/17/DOC-11、LIM-12/13 | 真实数据接入、PIT 与真实数据 P1/P2/P3；正文 v0.8 | `data/custom`（不入库）、`scripts/build_real_custom_data.py`、`configs/app.real.yaml`、`docs/data/*`、`pilot_results_real_data.md` |
