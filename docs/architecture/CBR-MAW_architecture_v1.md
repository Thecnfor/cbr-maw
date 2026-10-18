# CBR-MAW 多智能体协同风险预警系统 · 架构设计 v1（实现定稿）

> 论文：跨境金融风险的多智能体协同预警：多模态信息融合视角（方向2）
> 版本：v1.0 ｜ 2026-10-18 ｜ 状态：**已实现并通过端到端集成验证**（Mock LLM 全链路；DeepSeek 真实接口待 key 后切换）
> 交付物：① 可运行原型（Web 驾驶台 + 对话入口 + REST API）② 技术文档第四章 ③ 实验 harness（P1/P2/P3 试点可复现）
> 前版：[CBR-MAW_architecture_v0.md](CBR-MAW_architecture_v0.md)（设计草案）；本文件为实现后定稿，差异见第 8 节。

---

## 1. 一句话定位

**以"跨境金融市场压力高位状态"为唯一共同预警目标，由三类主体智能体在共享证据黑板上分工、互验、协调；所有数值由确定性金融工具计算、所有结论可溯源、所有协同过程可审计、所有模块可开关消融。**

工程配方：**时点数据层 + 多模态融合信号（P1） → 确定性工具/时点知识库（P2） → 三角色智能体 + 协同编排 + 证据核验（P3） → 驾驶台/对话/API + 实验 harness**。

---

## 2. 已实现总览（数字均来自本机实测）

| 项 | 状态 |
|---|---|
| 代码规模 | `src/cbr` 约 55 个 Python 模块（数据/特征/模型/工具/知识库/LLM/智能体/编排/核验/评估/API） |
| 数据 | 27 个序列数据卡（2018–2025 日频）、29 篇知识库语料 / 32 chunks、确定性仿真数据（`data/samples`）+ DuckDB PIT 存储 |
| 工具 | 7 个确定性工具（risk_measure / systemic_risk / capital_flow / funding_cost / scenario / forecast / knowledge_search），权限矩阵 `default_deny` |
| 智能体 | 监管 / 投资 / 融资三角色 + 单智能体基线 + 协调者/核验器逻辑 |
| 协同 | R0 独立分析 → R1 证据共享 → R2 交叉验证 → R3 分歧识别 → R4 冲突协调 → R5 决策卡；三模式（single / independent / collaborative）同一代码路径 |
| 核验 | 数值核验、引文核验、时点泄漏、越权阻断、schema、无依据断言六类；审计 trace 落盘 |
| 交互 | **React 19 + Vite + Tailwind v4 AI-native 驾驶台 + 对话**（shadcn/ui 规范 + Linear 级密度，light/dark，FastAPI `/ui` 托管；SSE 流式运行/对话、⌘K 命令面板、上下文 AI 追问、协同过程时间线）；Streamlit 保留为回退 UI；FastAPI 同步端点 + SSE 端点 + 30 分钟决策缓存 |
| 测试 | 全量 pytest（含 6 项真实装配端到端集成）通过（详见 §7） |
| 实验 | P1 模态消融、P2 工具/知识增强消融、P3 三模式对照的试点运行可复现 |

**一次真实装配的协同决策（as_of=2024-08-05，Mock LLM）**：3 张风险卡、20 条证据、4 个冲突全部解决、核验通过（数值错误率 0、证据准确率 100%、越权 0、泄漏 0）、协调成本 17 次工具调用 / 11,792 tokens / 2.47s / 0.0535 成本单位；对话入口返回 10 条引用 + 决策卡。

---

## 3. 总体架构（六层 + 两条横切，均为已实现模块）

```
┌────────────────────────────────────────────────────────────────────────────┐
│ L6 决策支持与演示层                                                          │
│   app/dashboard.py（驾驶台）· app/chat.py（对话）· src/cbr/api/main.py（REST） │
├────────────────────────────────────────────────────────────────────────────┤
│ L5 协同编排层                                                                │
│   orchestration/orchestrator.py（R0–R5 + 三模式）· blackboard.py（证据黑板）  │
│   conflict.py（冲突分类/仲裁）· hitl.py（人工接管）· verification/（核验+trace）│
├────────────────────────────────────────────────────────────────────────────┤
│ L4 智能体层                                                                  │
│   agents/role_agent.py（三角色）· single_agent.py（基线）· prompts.py        │
│   llm/{deepseek,mock}.py（真实/离线两模式，同一接口）                          │
├────────────────────────────────────────────────────────────────────────────┤
│ L3 知识与工具层                                                              │
│   tools/{risk,systemic,capital,funding,scenario,forecast,kb_search}.py       │
│   knowledge/{base,build,_index}.py + data/knowledge/（语料 + BM25 索引）      │
├────────────────────────────────────────────────────────────────────────────┤
│ L2 多模态融合层                                                              │
│   features/（数值/文本特征 + 时点对齐）· models/{fusion,signal,learners}.py    │
│   输出共享 RiskSignal（5/10/20 日概率 + 分位 + 驱动因子 + 模态贡献）            │
├────────────────────────────────────────────────────────────────────────────┤
│ L1 数据与时点层                                                              │
│   data/{synthetic,custom,pit_store,labels,dataset,provider,series}.py        │
│   data/samples（仿真）· data/custom（用户自建）· data/pit.duckdb（PIT）        │
└────────────────────────────────────────────────────────────────────────────┘
  横切 A｜verification/：数值·引文·时点·越权·schema·无依据断言 + trace JSONL
  横切 B｜eval/ + scripts/run_experiment.py：指标·滚动回测·消融·统计检验·运行产物
```

---

## 4. 模块与实现映射（代码即文档）

| 架构层 | 关键实现 | 说明 |
|---|---|---|
| L1 数据与时点 | `cbr.data.build_data_provider(settings)`；`MarketDataProvider` / `PitStoreDataProvider` | 装配优先级：用户自建数据（`data/custom` + `configs/data_mapping.yaml`）→ `data/pit.duckdb` → 样例仿真数据 → 内存仿真兜底。所有读取按 `as_of` 过滤（`release_time <= as_of`），数据卡 27 条含时点评级 |
| L1 标签 | `cbr.data.labels.build_stress_labels` | CFSI-CN 压力指数（股/债/汇/跨境/全球/文本六维，PCA/分位复合）；高压力=训练期 q90 冻结阈值（`threshold_mode=frozen`，滚动分位仅稳健性）；标签 `y_{t,h}` 主分析 B1（未来 h 日内 max），支持 B0(point)/B2(persistence)；h∈{5,10,20} |
| L2 多模态融合 | `cbr.features.build_feature_bundle`；`cbr.models.signal.SignalEngine` | 48 个数值特征 + 11 个文本特征；滚动样本外快照训练（`roll_window=500`、`retrain_every=20`、严格 `t+h<=R` 样本截断）；输出 `RiskSignal{horizons, percentile, level, drivers, modality_contrib, model_version}`；`predict(as_of, text_enabled=False)` 即 P1 数值-only 消融 |
| L3 工具 | `cbr.tools.build_tool_registry(settings, provider, kb)`；`registry.run(role, tool, as_of, **kwargs)` | 7 工具全部纯计算；`Evidence` 含 `evidence_id / tool_version / inputs_hash / as_of / elapsed_ms / citations`；角色权限来自 `configs/roles.yaml`，越权 `ok=False + data.disallowed` 并记审计；工具默认参数/序列映射在 `configs/tools.yaml` |
| L3 知识库 | `cbr.knowledge.build_knowledge_base(settings)` | 29 篇自有改写语料（2018-01~2025-04），BM25 索引（`data/knowledge/index`，corpus_hash 校验）；**双重时点过滤**：KB 层 + 工具层均强制 `publish_time <= as_of`；返回 chunk 级引文 |
| L4 LLM 抽象 | `cbr.llm.build_llm_client(settings)` | `MockLLM`（无 key，确定性、数值全部抄自证据）↔ `DeepSeekClient`（OpenAI 兼容、JSON mode + Pydantic 校验、重试、token 统计）；key 来源：环境变量/`.env`/`secrets/deepseek.key`，自动切换并打日志 |
| L4 角色智能体 | `cbr.agents.build_role_agents(...)`；`RoleAgent.analyze(AgentContext) -> AgentOutput` | 角色规范 `configs/roles.yaml`（目标/信息权限/工具权限/阈值/决策损失/禁止行为/输出风格）；流程：读共享信号→按权限选工具→证据→Claim（数值必须绑定工具证据、文本必须绑定 KB 引用）→数值自检回填→RiskCard；越权仅记 `tool_denied` 不执行 |
| L4 单智能体基线 | `cbr.agents.build_single_agent(...)`；`SingleAgent.analyze(...)` | P3 对照：一个通用 agent 顺序完成三主体任务，工具权限为并集，预算对齐 |
| L5 协同编排 | `cbr.orchestration.build_orchestrator(settings, provider, registry, kb, llm, ...)` | 三模式同一代码路径（`MODE_FLAGS`）；R0 独立分析→R1 黑板去重→R2 角色互查关键数值 claim（工具重算）→R3 分歧识别→R4 仲裁（工具重算 > 权威证据 > 证据质量；fact 采纳/驳回、directional 补证、preference 保留不判错、未解决升级 HITL）→R5 决策卡；每次 AgentContext 预算三模式一致，超支截断记账 |
| L5 黑板/冲突/HITL | `blackboard.py` / `conflict.py` / `hitl.py` | Evidence 去重；冲突三分类（fact/directional/preference）；仲裁规则可配置；HITL 队列支持 approve/reject/override 并写 trace；无人工时自动升级标记 |
| 横切 A 核验 | `cbr.verification.verify(...)`；`TraceWriter` | 六类核验 + 比率（`numeric_error_rate`、`evidence_accuracy`、`unsupported_claim_rate`、`permission_violations`、`leakage_events`、`schema_errors`）；trace `artifacts/traces/<run_id>.jsonl` + `<run_id>.decision.json`，run_id=`{mode}_{as_of}_{uuid8}` |
| 横切 B 评估 | `cbr.eval.metrics` / `backtest.py`；`scripts/run_experiment.py` | 指标（PR-AUC/ROC-AUC/Recall@10%/Brier/ECE/提前期）+ bootstrap CI + 配对自助法检验；滚动回测；三实验 kind（p1/p2/p3）产 `artifacts/runs/<run_id>/`（json+md） |
| L6 API | `src/cbr/api/main.py` + `streaming.py` | 同步：`/api/health`、`/api/scenarios`、`/api/decision`（30 分钟缓存，`refresh=true` 强制重算）、`/api/chat`、`/api/evidence/{id}`、`/api/data-cards`、`/api/trace/{run_id}`；SSE：`/api/decision/stream`、`/api/chat/stream`（`run/stage/trace/decision|chat/error` + 心跳，独立 trace 目录 tail 真实 trace）；`/ui` 静态托管 React 构建产物；未就绪 503/SSE error 中文 |
| L6 UI（主） | `web/`（React 19 + Vite + Tailwind v4；tokens 派生自 Xra-space `packages/ui`，规范参考 `Thecnfor/design-stack` shadcn-conventions 与 cross-dashboard `DESIGN.md`） | 248px 侧栏（场景/系统状态）+ 52px 顶栏（as_of/场景/三模式/重新生成/主题/⌘K）+ 页面头；SSE **RunProgress**（R0–R5 时间线 + 三主体状态 + 实时活动流 + 取消）、KPI 区（2fr 1fr 1fr）、3:2 主网格（信号图/驱动归因/模态贡献/三智能体卡 ↔ 证据黑板/分歧协调/核验-协同过程/数据卡/导出）、上下文 AI 追问（智能体卡/证据/冲突 → 对话预填）、流式对话（阶段 + 打字机 + 追问建议）、双主题与 reduced-motion |
| L6 UI（回退） | `app/dashboard.py` + `app/chat.py` + `app/components.py` | Streamlit 驾驶台（6 页签 + 对话页），保留原信息架构用于兼容与对照 |

---

## 5. 关键机制实现细节

### 5.1 证据与主张（可核验的最小单元）

- `Evidence`：`evidence_id`、`kind`（signal/tool/kb/market/policy）、`as_of`、`payload`、`source`（含 `publish_time`）、`tool{name,version,inputs_hash}`、`hash`。
- `Claim`：`claim_type`（numeric/text/directional）、`subject`、`value/unit`、`evidence_ids`、`confidence`、`status`（unverified/verified/conflicted/rejected/preference）。
- 硬约束：numeric claim 的 `value/unit` 必须与绑定工具证据逐字一致（agent 自检回填 + 核验器复算）；text claim 必须绑定 KB chunk 引用；无证据断言单独计数。
- 决策卡：`DecisionCard{signal, cards×3, evidence（黑板快照）, conflicts, verification, coordination, final_advice, trace_ref}`。

### 5.2 协同协议（R0–R5，已实现）

```
R0 三角色独立分析（互不可见）→ 各自 RiskCard + Evidence
R1 证据共享：Evidence 入黑板，hash 去重
R2 交叉验证：每角色复核他人 1 条关键数值 claim，用确定性工具重算；不一致生成 recheck 权威 claim
R3 分歧识别：同 subject 比对 → fact / directional / preference
R4 协调：fact→工具重算采纳/驳回；directional→补证；preference→保留（不判错）；未解决→HITL
R5 汇总：DecisionCard（evidence 快照 + conflicts + verification + coordination + final_advice）
```
- 三模式：`single`（一个通用 agent 完成三任务）、`independent`（三角色无共享无协调）、`collaborative`（完整 R0–R5）；
- 预算：每角色 ≤6 次工具调用 / ≤4000 tokens，三模式一致；协作轮次 ≤2（`orchestration.rounds`），无冲突/预算耗尽提前终止；
- 成本：`cost_usd = c_tool·n_tool + c_tok·tokens/1000 + c_lat·latency_ms`，配置于 `configs/app.yaml`，最终建议给出 J=L+μ·C 口径。

### 5.3 核验规则（论文 P2 的评价口径）

| 核验 | 规则 | 指标 |
|---|---|---|
| 数值 | 抽取 claim/建议中的数字与 claim.value、工具证据比对（绝对 1e-6 / 相对 1e-3；忽略年份、期限链、ID 内数字，百分数归一） | `numeric_error_rate` |
| 引文 | claim.evidence_ids 必须存在；KB 证据 `publish_time <= as_of`；返回原文片段 | `evidence_accuracy` |
| 无依据 | 文本 claim 无 evidence_ids | `unsupported_claim_rate` |
| 时点 | 任何证据/数据 `publish_time > as_of` | `leakage_events`（应 0） |
| 越权 | trace 中 `tool_denied` / disallowed | `permission_violations` |
| Schema | RiskCard/Claim Pydantic 校验 | `schema_errors` |

### 5.4 防泄漏与可复现

- PIT：所有数据读取走 `as_of` 过滤；训练快照严格截断 `t+h<=R`；文本检索双重时点过滤；标签只用训练期冻结阈值。
- 可复现：固定 seed（42）；模型快照/注册表 `artifacts/models/`；trace JSONL；实验 run 目录含 config+json+md；数据快照标识记录在数据卡/manifest。

---

## 6. 运行方式

```powershell
# 环境（已就绪）
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps

# 数据/知识库（首次）
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py

# React 驾驶台（主 UI）：构建后由 FastAPI 以 /ui 托管
cd web; bun install; bun run build; cd ..
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/ui/（light/dark，右上角切换）

# 前端开发模式（热更新，/api 代理到 8000）
cd web; bun run dev; cd ..

# 回退 UI（Streamlit）
set PYTHONPATH=src
.venv\Scripts\python.exe -m streamlit run app\dashboard.py --server.port 8501

# 实验（P1 模态 / P2 增强 / P3 协同 / 全部）
.venv\Scripts\python.exe scripts\run_experiment.py --kind all --run-id demo_run

# 测试
.venv\Scripts\python.exe -m pytest -q
```

DeepSeek 接入：`$env:DEEPSEEK_API_KEY="sk-..."`（或 `.env` / `secrets/deepseek.key`）→ `load_settings()` 自动关闭 mock，同一代码路径切换真实模型；无 key 时 Mock LLM 全链路可跑。

---

## 7. 验证结果（本机实测，2026-10-18）

| 验证项 | 结果 |
|---|---|
| 全量单元/集成测试 | **206 项全部通过（含 DeepSeek 真实调用测试）**，覆盖 tests/test_integration.py 6 项端到端集成与 tests/test_custom_data.py 自建数据接入测试；`pytest -q` 退出码 0 |
| 真实 DeepSeek 复跑 | P2（3 日 × full/no_tools）+ P3（4 日 × 三模式）= 18 次运行 / 54 次 LLM 调用全部成功；0 错误/超时/Schema 失败；实际 API tokens 323,431、费用约 ¥0.70；详见 [pilot_results_real_llm.md](../techdoc/pilot_results_real_llm.md) |
| 自建数据接入 | `data.dataset=custom` 时 provider 自动并入 `data/custom`（CSV/Parquet），缺失序列回退 SYNTHETIC；实测数据卡标记 `user-provided`、风险信号与历史序列接口可用（`tests/test_custom_data.py`） |
| 数据快照 | `dataset_snapshot_id=ds_1beab3f3ffd9e31a4c5b`、`corpus_hash=corpus_7ac20be6ce7d622c8308`；PIT 41,367 观测 / 2,207 文档 / 27 序列元数据；provider 走 `PitStoreDataProvider` |
| API 端到端 | `/api/decision` 200（3 卡/20 证据/冲突全解决/核验通过）、`/api/chat` 200（10 引用）、health/scenarios/evidence/data-cards/trace 均 200 |
| Streamlit（回退） | AppTest 无异常（5.8s）；6 页签 + 对话页；真实数据渲染 5 个 Plotly 图 |
| React 驾驶台（主 UI） | Vite 构建产物由 FastAPI `/ui` 托管（`/` 307 → `/ui/`）；light/dark 双主题、证据 Dialog、对话页、导出；AI-native 交互升级（SSE RunProgress/⌘K 命令面板/上下文追问/协同过程/打字机）；截图见 `artifacts/ui-ai/` |
| SSE 流式（真实 DeepSeek） | `/api/decision/stream`：HTTP 200 `text/event-stream`；`run=1 / trace=97 / stage=35 / decision=1`，首个 trace 与最终决策均在真实运行中即时推送（本次 14.5s）；`/api/chat/stream` 以 `chat` 收尾；缓存命中 0.01s 仅 `decision`；`: ping` 心跳 10s；254 项 pytest 全绿（含 43 项 streaming 测试） |
| 三模式预算 | single 12,000 / independent 11,799 / collaborative 11,801 tokens（6 个评估日均值），接近对齐 |
| 协同机制 | collaborative 平均 4.0 个冲突、全部解决；single/independent 无共享冲突（机制对照成立） |
| P1 试点（240 个交易日） | PR-AUC：数值-only 0.478/0.428/0.351，融合 0.504/0.451/0.354（h=5/10/20）；Δ = +0.026/+0.023/+0.003，p=0.112/0.088/0.653（**方向为正但不显著**）；Recall@10% 0.429/0.333/0.143；详见 [pilot_results_synthetic.md](../techdoc/pilot_results_synthetic.md) |
| P2 试点（4 个评估日） | full：15 条主张/17 次工具调用/核验通过/任务完成率 1.0；no_tools_no_kb：3 条主张/0 次工具/核验不通过/任务完成率 0（能力消融方向符合预期；Mock 模式下数值错误率恒为 0，真实 LLM 下才具备幻觉风险） |
| P3 试点（6 个评估日） | 三模式任务完成率 1.0、证据覆盖率 1.0、核验通过；collaborative 平均 4.0 个冲突且全部解决，single/independent 为 0；tokens 12,000/11,799/11,801 对齐 |

> 说明：以上为 **SYNTHETIC 仿真数据**下的流程验证结果（Mock LLM 与真实 DeepSeek 两种后端均已实测），不代表真实市场结论。论文正式实验需接入用户真实数据，按 `configs/experiments/` 与 `ablation_matrix.yaml` 重新执行；P1（按规则模型）与 P2/P3（按 LLM 后端）试点的指标表与解读分别见 [pilot_results_synthetic.md](../techdoc/pilot_results_synthetic.md) 与 [pilot_results_real_llm.md](../techdoc/pilot_results_real_llm.md)。

---

## 8. 与 v0 设计的差异（实现后修正）

1. **工具契约**：v0 列 8 个工具；实现为 7 个角色可调用工具，`report_export` 归协调层/UI 输出能力，不占角色工具表。
2. **冲突协调**：v0 写"R0–R5"，实现将 R4 定位为"仲裁重试轮"（`rounds` 为仲裁轮次上限，默认 2），R2 的交叉验证由编排器代表被分配角色执行确定性工具重算（不二次调用 LLM 同行评议），避免与 P3 预算对齐冲突。
3. **核验 `passed` 口径**：`VerificationReport.passed` 仅由 numeric/permission/leakage/schema 派生；citation/unsupported 以 `evidence_accuracy`/`unsupported_claim_rate` 单独度量（不改共享 schema）。
4. **成本**：v0 仅提"成本度量"；实现给出 `cost_per_tool_call / cost_per_1k_tokens / cost_per_latency_ms / coordination_weight_mu` 配置与 `CoordinationStats.cost_usd` 折算。
5. **标签**：v0 写"滚动分位阈值"；实现主分析采用训练期冻结阈值（`threshold_mode=frozen`），滚动分位作为稳健性设定。
6. **UI**：v0 计划"Streamlit 首发、API 分离"；实现为 React 19 AI-native 驾驶台（SSE 流式/命令面板/上下文追问/协同过程）+ FastAPI `/ui` 托管，Streamlit 保留回退；同步端点与 SSE 端点并存，决策结果 30 分钟缓存。

---

## 9. 已知限制与下一步

**限制**：仿真数据仅用于流程验证；BM25 检索无 embedding/reranker；ΔCoVaR/DY 为简化近似（参数已在 Evidence 中披露）；真实 LLM 下终卡数值错误率/无依据断言率是"自检回填 + 证据过滤后"的饱和值，不能直接解释为模型事实性（草稿级指标见真实 LLM 试验报告）；R2 交叉验证为工具重算而非 LLM 同行评议；P1 试点在仿真 DGP 上判别力存在但不显著，需真实数据与全窗口实验；真实 LLM 单次运行的 prompt 约 5.2–5.7k tokens/角色，会撞 12k 统计预算上限，正式实验需校准预算或外置 JSON Schema；P3 的决策损失暂由共享信号主导，协同增益尚未在决策损失维度体现。

**下一步（按优先级）**：
1. 接入用户自建数据集（`data/custom` + `configs/data_mapping.yaml`）并重建 PIT 快照；
2. 按真实 LLM 试验报告建议增加**草稿级幻觉指标**（回填前数值差异、被拒 claim 比例）与**证据门槛版任务完成率**，并校准 token 预算（`max_tokens_per_agent` 或外置 Schema）；
3. 跑全窗口 P1（2021–2025）与 E0–E12 消融矩阵，产出论文 5.x/6.x 结果表；
4. HITL 交互式审批面板（approve/reject/override 写 trace）与流式并发上限/成本护栏；如需录屏材料，使用 `web/README.md` 的验收路径与 `artifacts/ui-ai/` 截图。
