# 实验指南（P1 / P2 / P3 与消融矩阵）

> 目标：讲清楚三组实验分别验证什么、用哪条命令跑、产物在哪、结果怎么读、哪些结论不能过度解读。
> 实现：`scripts/run_experiment.py`；配置：`configs/experiments/`；指标：`src/cbr/eval/metrics.py`。
> 数据声明：默认全部基于 **SYNTHETIC 仿真数据**，指标只验证 pipeline 与消融机制，不代表真实市场结论。

---

## 1. 三个实验命题

| 命题 | 问题 | 主要对照 | 核心指标 |
|---|---|---|---|
| **P1 多模态** | 文本信息是否带来增量预警能力 | numeric-only vs numeric+text | PR-AUC、Recall@10%、Brier、ECE、提前期（含 bootstrap CI / 配对检验） |
| **P2 知识与工具** | 知识检索与确定性工具是否降低数值错误与无依据断言 | full vs no_tools/no_kb | 数值错误率、证据准确率、无依据断言率、证据门槛任务完成率、tokens |
| **P3 协同** | 专业化分工与协同是否在可比预算下降低决策损失 | single / independent / collaborative | 任务完成率、决策损失、协同成本、冲突数/解决率、核验通过率 |

---

## 2. 运行命令（Windows / PowerShell，仓库根目录）

```powershell
# P1：模态消融（默认 p1_modality.yaml；--p1-max-days 可只回测最近 N 个交易日）
.venv\Scripts\python.exe scripts\run_experiment.py --kind p1
.venv\Scripts\python.exe scripts\run_experiment.py --kind p1 --p1-max-days 240

# P2：工具/知识增强消融（默认评估 4 个日期）
.venv\Scripts\python.exe scripts\run_experiment.py --kind p2 --p2-dates 4

# P3：三模式协同对照（默认 8 个评估日）
.venv\Scripts\python.exe scripts\run_experiment.py --kind p3 --p3-dates 8

# 全部串行
.venv\Scripts\python.exe scripts\run_experiment.py --kind all
```

Linux/macOS 将前缀换成 `python`（激活 venv 后）。

常用参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--kind p1\|p2\|p3\|all` | `all` | 跑哪组实验 |
| `--config` | `configs/experiments/p1_modality.yaml` | 实验配置；P2/P3 建议显式指定对应 YAML |
| `--p1-max-days` | 全样本 | P1 只回测最近 N 个交易日（快速验证用） |
| `--p2-dates` / `--p3-dates` | 4 / 8 | 评估日期数（真实 LLM 会产生对应费用） |
| `--run-id` | 自动 | 自定义运行目录名 |

P2/P3 建议显式指定配置，避免默认路径歧义：

```powershell
.venv\Scripts\python.exe scripts\run_experiment.py --kind p2 --config configs\experiments\p2_augment.yaml --p2-dates 4
.venv\Scripts\python.exe scripts\run_experiment.py --kind p3 --config configs\experiments\p3_collaboration.yaml --p3-dates 8
```

---

## 3. 产物在哪

```text
artifacts/runs/<run_id>/
├─ p1.json / p1.md        # P1 指标与表格（若跑了 p1）
├─ p2.json / p2.md        # P2 指标与表格
├─ p3.json / p3.md        # P3 指标与表格
├─ summary.md             # 跨实验摘要
└─ （按配置可能另有逐案例明细）
```

- `artifacts/` 已被 `.gitignore` 忽略，不入库；需要归档时把 `*.md` 摘要复制到 `docs/techdoc/` 或论文附录。
- 真实 LLM 运行的 trace 在 `artifacts/traces/<run_id>.jsonl`，决策卡快照 `<run_id>.decision.json`；可通过 `GET /api/trace/{run_id}` 复核。
- 流式接口的 trace 目录独立（`artifacts/traces/stream-*`），按 `CBR_STREAM_TRACE_RETENTION`（默认 50）清理。

---

## 4. 配置怎么改

以 [`configs/experiments/p1_modality.yaml`](../../configs/experiments/p1_modality.yaml) 为例：

```yaml
run_id: p1_modality_v1
data:    {sample_start: "2018-01-01", sample_end: "2025-09-30", pit_snapshot: auto}
target:  {label_version: stress_pca_q90, horizons: [5, 10, 20], eval_start: "2021-01-01"}
modality: {numeric: true, text: true}      # text: false 即 numeric-only 对照
augment:  {rag: false, tools: false}
agents:   {enabled: false}                 # P1 不启用 LLM 智能体
budget:   {equal_across_configs: true}
llm:      {provider: none}
eval:     {bootstrap: 1000, metrics: [pr_auc, recall_at_top_decile, brier, ece, lead_time_days]}
```

- **P2**（`p2_augment.yaml`）：`augment.rag/tools` 控制知识库与工具开关，`agents.enabled: true`，`llm.provider: deepseek` + `mock_when_no_key: true`；
- **P3**（`p3_collaboration.yaml`）：`agents.modes: [single, independent, collaborative]`，三模式预算对齐（`max_tool_calls_per_agent`、`max_tokens_per_agent`）；
- 改完配置后建议换一个 `run_id`，避免覆盖历史产物。

---

## 5. 消融矩阵 E0–E12

[`configs/experiments/ablation_matrix.yaml`](../../configs/experiments/ablation_matrix.yaml) 是论文表 4-8 的 E 编号到 `kind + config + overrides` 的对照表：

| E | 组合 | 对应 kind |
|---|---|---|
| E0 | 仅数值预测基线（无 LLM） | p1 |
| E1 | 数值 + 文本融合预测器 | p1 |
| E2 | 单智能体（无工具/无知识库） | p3 |
| E3 | 单智能体 + 工具 | p3 |
| E4 | 单智能体 + 工具 + 知识库 | p3 |
| E5 | 三个独立智能体（无共享/无协调） | p3 |
| E6 | 协同 · 仅证据共享 | p3 |
| E7 | 协同 · 证据共享 + 交叉验证 | p3 |
| E8 | 伪分工对照（三角色同 prompt/同工具权限） | p3 |
| E9 | 完整协同（证据共享 + 交叉验证 + 冲突协调） | p3 |
| E10 | 协同去交叉验证 | p3 |
| E11 | 协同去冲突协调 | p3 |
| E12 | 协同 + 工具/知识库消融 | p2 |

> **现状**：runner 直接支持 `--kind p1|p2|p3` 与 `--config`，**尚未自动读取 `ablation_matrix.yaml` 批量跑 E 编号**（属 open issue EXP-08/INT-04 的收尾项）。要跑某个 E 组合，当前做法是复制对应 YAML、按 `overrides` 修改字段后执行；或扩展 runner 读取矩阵（见 [open_issues](../techdoc/open_issues.md)）。

---

## 6. 结果怎么读（含已有 pilot 指针）

**P1 pilot（SYNTHETIC，240 日，Mock/规则后端；旧指针，正式论文需扩样）**：

- h5 PR-AUC：numeric 0.478 → fusion 0.504（Δ+0.026，p=0.112）
- h10：0.428 → 0.451（Δ+0.023，p=0.088）
- h20：0.351 → 0.354（Δ+0.003，p=0.653）
- Recall@10%：0.429 / 0.333 / 0.143（h5/h10/h20）

**口径要求**：方向为正但**均不显著**；正文与 README 只能写「方向为正、不显著 / 适用边界」，禁止写成「显著提升」。详见 [open_issues §0](../techdoc/open_issues.md) 与 [pilot_results_synthetic.md](../techdoc/pilot_results_synthetic.md)。

**P2/P3 真实 LLM pilot**：[pilot_results_real_llm.md](../techdoc/pilot_results_real_llm.md) 记录 18 次运行 / 54 次调用全部成功、0 Schema 失败；实际 tokens 323,431、费用约 ¥0.70–0.88；单次延迟 12–13 秒。注意：

- 12,000 token 记账预算低于真实 prompt（LIM-10），报告 tokens 比实际少约 33%；
- 终卡 `numeric_error_rate=0` 是「自检回填 + 证据过滤后」的饱和值，不能解释为模型事实性（LIM-09）；
- 真实 LLM 的成本/延迟随日期数与模式线性增长，跑批前先估算。

---

## 7. 复现注意

1. **同一数据快照**：记录 `data/pit_manifest.json` 的 `dataset_snapshot_id` 与 `corpus_hash`，换数据后结果不可直接比较。
2. **同一预算**：P3 三模式必须保持每角色预算一致（`equal_across_configs: true`）。
3. **Mock 与真实 LLM 分开报告**：mock 可复现、零成本；真实 LLM 有非确定性（温度 0 + 固定模型版本 + 记录 run_id）。
4. **不要把仿真结论写进真实市场表述**：所有 `data/samples` 运行都必须标注 SYNTHETIC。
5. 实验脚本改动后先跑 `pytest tests/test_eval.py tests/test_backtest.py -q`。
