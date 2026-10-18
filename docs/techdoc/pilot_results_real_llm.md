# CBR-MAW 真实 LLM 试点实验报告（P2 / P3，SYNTHETIC 数据）

> **结论先行**：用真实 DeepSeek 完成 P2（3 个评估日 × 2 个消融变体）与 P3（4 个评估日 × 3 种协同模式），共 **18 次运行 / 54 次 LLM 调用**，全部成功；**0 次 LLM 错误、0 次超时、0 次 JSON Schema 失败、0 次重试、0 次降级**。
> **最终决策卡**上的数值错误率 0.00、证据准确率 1.00、无依据断言率 0.00 与 mock 一致，但这些是**自检回填 + 证据过滤之后**的指标，不能解释为"真实 LLM 本身不产生幻觉"。
> **真实 LLM 的主要变化**：主张数 15 → 18（full / P3）；full/P3 实际 API tokens 约为报告值的 1.55–1.62 倍（no_tools 约 1.08 倍），**18/18 次运行都撞上 12,000 token 的统计预算**；单次运行延迟从 mock 的 0.42–0.52 s 升到 **12.0–12.6 s**；P2 no_tools 变体下真实模型提交的草稿主张有 **46.8% 被自检丢弃**（每次运行的 7 条 numeric 草稿全部因无法绑定工具证据被拒），但最终任务完成率反而从 mock 的 0.00 升到 1.00，说明 `task_completion` 口径需要加证据门槛。
> **成本**：按 DeepSeek `deepseek-chat` 公开价估算，总实际 API 费用约 **$0.096–0.123（¥0.70–0.88）**，远低于 ¥30 预算；但总 token 为 **323,431**，超过"约 20 万 tokens"的软指标约 62%。
> **数据性质**：全部为 **SYNTHETIC 仿真数据**，仅验证 pipeline、真实 LLM 调用链与指标行为，**不代表任何真实市场结论**。

---

## 1. 目的与范围

1. 用真实 DeepSeek 重新执行 P2（金融知识与专业工具增强消融）与 P3（单智能体 / 三独立智能体 / 完整协同对照），检验：
   - 真实 LLM 调用链、JSON Schema 校验、重试与降级路径是否可稳定运行；
   - 真实 LLM 下 P2/P3 指标相对 mock 的变化，尤其是数值错误率、无依据断言率、冲突类型、token 预算与延迟；
   - 真实 API 成本与现有 12,000 token 统计预算、¥30 金额预算的边界。
2. 明确**不**回答的问题：真实市场预警效果、策略收益、跨市场因果结论。数据为仿真 DGP，评估日仅 3–4 个，单次运行，无统计重复。

**运行范围**

| 实验 | run_id | 评估日 | 变体 / 模式 | 运行次数 | LLM 调用 |
|---|---|---|---|---|---|
| P2 | `p2_real` | 2021-01-04、2022-08-04、2024-03-06 | full、no_tools_no_kb | 6 | 18 |
| P3 | `p3_real` | 2021-01-04、2022-03-15、2023-05-23、2024-07-26 | single、independent、collaborative | 12 | 36 |

---

## 2. 环境与配置

| 项目 | 值 |
|---|---|
| 运行时间 | 2026-10-18 16:11–16:18（Asia/Shanghai），P2 约 16:13:22–16:14:20，P3 约 16:15:37–16:17:49 |
| 工作目录 | `D:\recently\commorcial` |
| Python / 环境 | `.venv\Scripts\python.exe`，Python 3.12.14；openai 3.35.1；pydantic 2.14.1 |
| LLM provider / model | `deepseek` / `deepseek-chat` |
| API endpoint | `https://api.deepseek.com`（OpenAI 兼容接口） |
| temperature | **0.0** |
| 生成上限 / 超时 / 重试 | `max_tokens=2000` / `timeout_seconds=60` / `max_retries=2` |
| 客户端校验 | `DeepSeekClient`，`is_mock=False`，`mode=deepseek:deepseek-chat` |
| 连通性测试 | 真实小请求返回 `OK`；usage 19 prompt + 1 completion = 20 tokens |
| API key | 由 `secrets/deepseek.key` 自动加载，**本报告不展示 key 原文** |
| 数据性质 | **SYNTHETIC 仿真数据**（`synthetic-simulation`） |
| 数据快照 | `dataset_snapshot_id=ds_1beab3f3ffd9e31a4c5b`，`corpus_hash=corpus_7ac20be6ce7d622c8308` |
| 数据规模 / 区间 | 27 序列 / 41,367 观测 / 2,207 篇文档；2018-01-02 ~ 2025-09-30 |
| 信号模型 | `fusion-xgb-v1`（P1 融合预测器） |
| 编排预算 | 每角色 `max_tool_calls_per_agent=6`、`max_tokens_per_agent=4000`；3 角色合计 12,000 tokens；`rounds=2`；`human_in_the_loop=true` |
| 消融配置 | P2：`configs/experiments/p2_augment.yaml`；P3：`configs/experiments/p3_collaboration.yaml` |
| 已有 demo | `artifacts/demo/2024-08-05_real_summary.json` 已存在（`backend=real`，verification passed）；抽查其 trace 的 `llm_mode=deepseek:deepseek-chat`，实际每模式 18,683–19,495 tokens。**本次未重跑 demo**，避免额外消耗 |

> 说明：`load_settings()` 检测到 `secrets/deepseek.key` 后自动将 `mock` 置为 `False`；P2/P3 均由 `run_experiment.py` 构建 `DeepSeekClient` 执行。`p2.json` / `p3.json` 自带 `synthetic=true`，但没有 `llm_backend` 字段；**真实后端的权威证据是 trace 中的 `llm_mode=deepseek:deepseek-chat`**（18 次运行、54 条 `llm_call` 均为该值）。

---

## 3. 指标口径与读法（重要）

真实 LLM 接入后，以下四个指标的含义与 mock 报告中的"字面值"不同，必须先说明：

1. **数值错误率 = 0.00 不是 LLM 数值准确率。** `RoleAgent._materialize_claim` 对 numeric claim 一律用确定性工具证据的 `value/unit` 覆盖 LLM 给出的数值，再由 verifier 从 `claim.text` 抽数复核。因此 0.00 说明"回填后的卡片与工具证据一致"，不说明模型自己算对。
2. **无依据断言率 = 0.00 是"终卡过滤后"指标。** 没有可用证据的 claim 在物化阶段被直接丢弃（`claim_rejected`），不会进入最终卡片。真实 LLM 的"无依据倾向"要看**草稿阶段被拒数 / 草稿总数**这一补充口径（本报告单独列出）。
3. **任务完成率口径较松。** 定义为每张卡满足 `headline 非空 + recommendation 非空 + claims ≥ 2` 的比例，不要求 numeric claim、工具证据或核验通过。真实 LLM 即使在没有工具/知识库时也能生成多条方向性 claim，因此该指标会"虚高"。
4. **tokens 是预算截断后的统计值。** `max_tokens_per_agent=4000` 是**记账预算**，不是生成上限；实际超出部分在 `_account_usage` 中被裁剪到 4,000/角色，所以 P2/P3 报告里几乎都显示 12,000。**真实 API 用量应取 trace 的 `llm_call.prompt_tokens + completion_tokens`**（本报告第 7 节使用该口径）。`cost_usd` 也不是美元账单，而是项目定义的统一协同成本单位 C（tool_calls + tokens + latency 折算），本报告将其记为"成本 C"。

---

## 4. P2：知识与专业工具增强消融（真实 DeepSeek）

### 4.1 运行信息

- run_id：`p2_real`
- 评估日（3 个）：`2021-01-04`、`2022-08-04`、`2024-03-06`
- 对照：`full`（7 工具 + 知识库） vs `no_tools_no_kb`（角色工具权限清空 + 空知识库）
- 每变体 3 次运行，共 6 次；每次 3 个角色调用，共 18 次 LLM 调用
- 全部调用 `attempts=1`，无重试、无 fallback、无 schema error

### 4.2 指标表（均值，括号内为标准差）

| 指标 | full | no_tools_no_kb |
|---|---|---|
| 评估日数 | 3 | 3 |
| 决策卡数 | 3.0 | 3.0 |
| 主张数 | **18.00** (±0.00) | **8.33** (±0.47) |
| 主张构成（numeric / text / directional） | 11 / 5 / 2 | 0 / 0 / 8.33 |
| 任务完成率 | 1.00 | **1.00** |
| 数值错误率（终卡，回填后） | 0.00 | 0.00 |
| 证据准确率（终卡） | 1.00 | 1.00 |
| 无依据断言率（终卡） | 0.00 | 0.00 |
| 草稿被拒主张数（补充口径） | 0.00 | **7.33 / 次运行**（22 条 / 3 次） |
| 草稿拒绝率（补充口径） | 0.0% | **46.8%** |
| 核验通过（verifier.passed） | 1.00 | **0.00**※ |
| 数值核验 | 31 / 31 通过 | 9 / 9 通过 |
| 引用核验 | 18 / 18 通过 | 8.33 / 8.33 通过 |
| 工具调用 | 17.33 (±0.47) | 0.00 |
| 权限拦截（tool_denied） | 0.00 | **17.00 / 次运行**※ |
| 报告 tokens（预算截断后） | 12,000 | 12,000 |
| **实际 API tokens（trace）** | **18,765.7**（prompt 16,359.3 + completion 2,406.3） | **12,921.3**（prompt 10,769.0 + completion 2,152.3） |
| 延迟（平均） | **12,488.7 ms** (±830.6) | **11,321.3 ms** (±64.0) |
| 冲突数 / 解决数 | 3.67 / 3.67 | 0.33 / 0.33 |
| 冲突类型（fact / preference） | 3.00 / 0.67 | 0.00 / 0.33 |
| 成本 C（统一成本单位） | 0.1542 | 0.1252 |
| 实际 API 成本估算 | **¥0.040 / 次**（$0.0056） | **¥0.028 / 次**（$0.0039） |
| 预算撞顶（budget_exceeded） | 3 次 / 运行（每角色 1 次） | 3 次 / 运行（每角色 1 次） |

※ `no_tools_no_kb` 的 `verification_passed=0.00` **完全由消融设计导致的 permission 违规造成**（17 次/运行：每角色清空工具权限后仍有工具计划，另有 `knowledge_search` 被拒），不是 LLM 输出错误；其数值核验 9/9、引用核验 8.33/8.33 均通过。mock 的同一消融也是 17 次权限拦截、verification=0，因此这是**设计性失败**，不是真实 LLM 新问题。另：该变体下 **numeric 草稿 7 条/次全部被拒（100%）**，text 草稿三次运行合计 1 条被拒，最终只保留 8–9 条 directional claim；`46.8%` 是"全部草稿（numeric + text + directional）"口径的拒绝率，不是 numeric 专属拒绝率。

**逐日实际 tokens / 延迟**

| 日期 | full 实际 tokens | full 延迟 | no_tools 实际 tokens | no_tools 延迟 |
|---|---|---|---|---|
| 2021-01-04 | 18,783（16,382 + 2,401） | 13,604 ms | 12,903（10,803 + 2,100） | 11,404 ms |
| 2022-08-04 | 18,816（16,376 + 2,440） | 12,250 ms | 12,915（10,764 + 2,151） | 11,248 ms |
| 2024-03-06 | 18,698（16,320 + 2,378） | 11,612 ms | 12,946（10,740 + 2,206） | 11,312 ms |

**要点**

- `full` 的 3 次运行均通过核验，无越权、无泄漏、无 schema error；18 条主张中 11 条 numeric、5 条 text、2 条 directional，比 mock 的 6/6/3 更偏数值与工具证据。
- `no_tools_no_kb` 下真实模型仍产出 8–9 条 **directional** 主张（每条绑定共享信号证据），所以 `task_completion=1.0`；但每次运行有 7 条 numeric 草稿因无法绑定工具证据被丢弃（其中一次另有 1 条 text 草稿因无 KB 证据被丢弃）。**这说明真实模型的"补全倾向"会在证据缺失时转向方向性叙述，而不是留空。**
- `full` 的冲突以 `fact` 为主（3.00/次），`preference` 仅 0.67/次；`no_tools` 几乎没有可比较的数值主张，冲突降到 0.33/次（仅 1 个 preference）。

---

## 5. P3：多智能体协同对照（真实 DeepSeek）

### 5.1 运行信息

- run_id：`p3_real`
- 评估日（4 个）：`2021-01-04`、`2022-03-15`、`2023-05-23`、`2024-07-26`
- 模式：`single`（1 个通用 agent 依次完成三主体）、`independent`（3 个独立 RoleAgent）、`collaborative`（R0 独立分析 → R1 证据共享 → R2 交叉验证 → R3 冲突识别 → R4 仲裁）
- 每模式 4 次运行，共 12 次；每次 3 个角色调用，共 36 次 LLM 调用
- 全部调用 `attempts=1`，无重试、无 fallback、无 schema error

### 5.2 指标表（均值，括号内为标准差）

| 指标 | single | independent | collaborative |
|---|---|---|---|
| 评估日数 | 4 | 4 | 4 |
| 决策卡数 | 3.0 | 3.0 | 3.0 |
| 任务完成率 | 1.00 | 1.00 | 1.00 |
| 主张数 | 17.75 (±0.43) | 18.00 | 18.00 |
| 主张构成（numeric / text / directional） | 10.75 / 4.00 / 3.00 | 11.00 / 4.75 / 2.25 | 11.00 / 4.75 / 2.25 |
| 数值错误率（终卡） | 0.00 | 0.00 | 0.00 |
| 证据准确率（终卡） | 1.00 | 1.00 | 1.00 |
| 无依据断言率（终卡） | 0.00 | 0.00 | 0.00 |
| 草稿被拒主张数 | 0.00 | 0.00 | 0.00 |
| 核验通过 | 1.00 | 1.00 | 1.00 |
| 数值核验 | 35.25 / 35.25 | 31 / 31 | 31 / 31 |
| 引用核验 | 17.75 / 17.75 | 18 / 18 | 18 / 18 |
| 权限拦截 / 泄漏 / schema 错误 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| 冲突数 / 解决数 | 0.00 / 0.00 | 0.00 / 0.00 | **4.00 / 4.00** (±0.71) |
| 冲突类型（fact / preference） | 0 / 0 | 0 / 0 | **2.75 / 1.25** |
| 冲突解决方式（tool / consensus / authority） | — | — | 2.25 / 1.25 / 0.50 |
| 冲突升级数 | 0.00 | 0.00 | 0.00 |
| 工具调用 | 18.00 | 14.00 | 17.00 (±1.00) |
| 报告 tokens（预算截断后） | 12,000 | 12,000 | 12,000 |
| **实际 API tokens（trace）** | **19,492.3**（17,167.3 + 2,325.0） | **18,779.8**（16,341.8 + 2,438.0） | **18,820.5**（16,370.3 + 2,450.3） |
| 延迟（平均） | **12,610.3 ms** (±1,248.6) | **12,007.0 ms** (±117.8) | **12,017.5 ms** (±900.1) |
| 成本 C（统一成本单位） | 0.1561 | 0.1461 | 0.1492 |
| 实际 API 成本估算 | **¥0.042 / 次**（$0.0058） | **¥0.040 / 次**（$0.0056） | **¥0.040 / 次**（$0.0056） |
| 预算撞顶（budget_exceeded） | 1 次 / 运行（single 共享池） | 3 次 / 运行 | 3 次 / 运行 |
| decision_loss（三模式相同） | 1.2111 | 1.2111 | 1.2111 |

**要点**

- 三种模式均能产出 3 张完整决策卡，任务完成率、核验通过率均为 1.00；**single/independent 无共享与协调，冲突数按设计为 0；collaborative 检出并解决 4.00 个/次冲突，无升级**。
- 真实模型的 numeric claim 明显多于 mock（11 vs 6），因此 collaborative 的冲突更多落在 `fact`（2.75/次），`preference` 降到 1.25/次；mock 同代码路径的 4 个冲突为 2 fact + 2 preference。真实 P3 还出现了 **authority 裁决**（权威证据质量，0.50/次；2 个日期出现），mock 未出现。
- 三模式 `decision_loss` 完全相同（1.2111），因为 L 由共享信号与角色损失权重决定，协同目前不改变 L；该值也与 mock 的 0.5201 不可直接比较（评估日不同）。**当前 P3 仍未在决策损失维度体现协同增益**，与 mock 试点结论一致。
- `single` 实际 tokens 最高（19,492），因为 single agent 使用三主体工具并集，prompt 更大；但其 12,000 是"3 角色共享池"，所以只触发 1 次截断事件。`independent`/`collaborative` 每角色独立 4,000 预算，各触发 3 次截断。

---

## 6. 与 mock 的对比

### 6.1 P2：真实 vs mock（`p2_final`）

> 日期口径：真实 P2 为 3 个日期（2021-01-04、2022-08-04、2024-03-06）；`p2_final` mock 为 4 个日期（2021-01-04、2022-03-15、2023-05-23、2024-07-26）。两者仅 2021-01-04 重合，**不是配对比较**。后文给出同日期子集稳健性检查。

| 指标 | full（real / mock） | no_tools_no_kb（real / mock） |
|---|---|---|
| 主张数 | **18.00 / 15.00** | **8.33 / 3.00** |
| 主张构成（numeric / text / directional） | **11 / 5 / 2** vs 6 / 6 / 3 | **0 / 0 / 8.33** vs 0 / 0 / 3 |
| 任务完成率 | 1.00 / 1.00 | **1.00 / 0.00** |
| 数值错误率 | 0.00 / 0.00 | 0.00 / 0.00 |
| 证据准确率 | 1.00 / 1.00 | 1.00 / 1.00 |
| 无依据断言率（终卡） | 0.00 / 0.00 | 0.00 / 0.00 |
| 草稿被拒主张数（补充） | 0.00 / — | **7.33 / —**（46.8%） |
| 核验通过 | 1.00 / 1.00 | 0.00 / 0.00（均为 permission 17） |
| 工具调用 | 17.33 / 17.00 | 0.00 / 0.00 |
| 报告 tokens | 12,000 / 11,799 | 12,000 / 7,469 |
| 实际 API tokens | **18,766 / —** | **12,921 / —** |
| 延迟 | **12,489 ms / 421 ms** | **11,321 ms / 39 ms** |
| 冲突数 / 解决数 | **3.67 / 3.67** vs 4.00 / 4.00 | **0.33 / 0.33** vs 1.00 / 1.00 |
| 冲突类型（fact / preference） | **3.00 / 0.67** vs 2.00 / 2.00 | **0.00 / 0.33** vs 0.00 / 1.00 |
| 成本 C | **0.154 / 0.033** | **0.125 / 0.008** |
| 实际 API 成本 | **¥0.040 / —** | **¥0.028 / —** |

**同日期稳健性检查**

- P2 `full` 的 3 个真实日期都包含在 `p3_final` 的 6 个 mock 日期中；取 `p3_final` collaborative 在这 3 天的 mock 行：主张数 15、tokens 11,795.3、延迟 457.0 ms、冲突 4.00/4.00、verification 1.00。与上表"真实 18 / 18,766 / 12,489 ms / 3.67"同向，说明**主张数增加、延迟上升、冲突略降不是日期抽样造成的**。
- P2 `no_tools` 仅 2021-01-04 与 `p2_final` 重合：真实 9 条主张、task=1.00、12,903 tokens、11,404 ms、1 个 preference 冲突；mock 3 条主张、task=0.00、7,494 tokens、38 ms、1 个 preference 冲突；两者 verification 均为 0（permission 17）。**"真实模型把 no_tools 的任务完成率抬高"在单个同日样本上成立。**

### 6.2 P3：真实 vs mock（`p3_final`）

> 日期口径：真实 P3 为 4 个日期（2021-01-04、2022-03-15、2023-05-23、2024-07-26）；`p3_final` mock 为 6 个日期（2021-01-04、2021-10-22、2022-08-04、2023-05-23、2024-03-06、2024-12-18）。仅 2021-01-04 与 2023-05-23 重合，**不是配对比较**。但真实 P3 的 4 个日期恰好等于 `p2_final` 的 4 个日期，而 `p2_final/full` 与 `p3_final/collaborative` 是同一 collaborative 代码路径——因此 **collaborative 可以做严格同日对照**（见下）。

| 指标 | single（real / mock） | independent（real / mock） | collaborative（real / mock） |
|---|---|---|---|
| 任务完成率 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 主张数 | **17.75 / 15.00** | **18.00 / 15.00** | **18.00 / 15.00** |
| 数值错误率 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| 证据准确率 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 无依据断言率（终卡） | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| 核验通过 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 冲突数 / 解决数 | 0 / 0 vs 0 / 0 | 0 / 0 vs 0 / 0 | **4.00 / 4.00** vs 4.00 / 4.00 |
| 冲突类型（fact / preference） | — | — | **2.75 / 1.25** vs 2.00 / 2.00 |
| 工具调用 | 18 / 18 | 14 / 14 | 17 / 17 |
| 报告 tokens | 12,000 / 12,000 | 12,000 / 11,799 | 12,000 / 11,801 |
| 实际 API tokens | **19,492 / —** | **18,780 / —** | **18,821 / —** |
| 延迟 | **12,610 ms / 517 ms** | **12,007 ms / 428 ms** | **12,018 ms / 481 ms** |
| 成本 C | **0.156 / 0.035** | **0.146 / 0.030** | **0.149 / 0.034** |
| 实际 API 成本 | **¥0.042 / —** | **¥0.040 / —** | **¥0.040 / —** |

**同日 collaborative 对照（真实 4 天 vs `p2_final/full` mock 同 4 天）**

| 指标 | real collaborative | mock full（同 4 天） |
|---|---|---|
| 主张数 | 18.00 | 15.00 |
| 报告 / 实际 tokens | 12,000 / 18,821 | 11,799 / — |
| 延迟 | 12,018 ms | 421 ms |
| 冲突数 / 解决数 | 4.00 / 4.00 | 4.00 / 4.00 |
| 核验通过 | 1.00 | 1.00 |
| 数值错误率 / 证据准确率 | 0.00 / 1.00 | 0.00 / 1.00 |

→ **主张数 +20%、延迟约 29 倍、tokens 约 1.6 倍，是真实 LLM 的稳定变化；冲突总数与核验结论不变。**

### 6.3 变化解读

1. **主张数增加，且结构从"文本/方向"转向"数值"。** full/P3 从 mock 的 15 条（6 numeric / 6 text / 3 directional）变为 18 条（11 numeric / 5 text / 2 directional）。真实模型更愿意引用工具数值，mock 更依赖 KB 文本。
2. **冲突类型随之从 preference 转向 fact。** P2 full 由 mock 的 2 fact + 2 preference 变为 3.00 fact + 0.67 preference；P3 collaborative 为 2.75 fact + 1.25 preference。原因不是"真实模型更爱吵架"，而是 numeric claim 从 6 条增到 11 条，跨角色同一指标的分歧更容易被检测为 fact；directional claim 减少后 preference 冲突减少。所有冲突均解决、无升级。
3. **no_tools 的 task_completion 从 0.00 变 1.00，是本次最重要的"指标失真"信号。** 真实模型用 signal evidence 生成 8–9 条方向性 claim，满足"每卡 ≥2 条 claim"；mock 的规则模板在无工具/无 KB 时只生成 1 条/卡，故为 0。**不能把 1.00 解读为"真实 LLM 在无证据条件下完成了任务"**，恰恰相反，7 条/次的 numeric 草稿全部被拒、text 草稿三次合计仅 1 条被拒，22/47 = 46.8% 的草稿因无依据被丢弃。
4. **无依据断言率、数值错误率没有变化（都是 0/1/0），但这不是"真实模型更可靠"。** 终卡指标被自检回填与证据过滤"饱和"；真实模型的无依据倾向体现在 `claim_rejected`（P2 no_tools 22 条 / 3 次运行）。若要比较模型幻觉率，应新增"草稿阶段无依据率 / 数值草稿拒绝率"。
5. **tokens 全部撞 12,000 预算，报告值系统性低估。** 18/18 次运行报告 12,000；实际 18,766（full）、19,492（single）、12,921（no_tools）等。full/P3 低估约 36–39%，no_tools 低估约 7%。逐角色看，full/P3 的 **prompt 本身就达 5.2–5.7k tokens/角色**，已超过 4,000 预算；no_tools prompt 约 3.5–3.6k，加 completion 后 4.26–4.37k 也超。主要原因是 `DeepSeekClient.structured` 把完整 JSON Schema 注入 system prompt，相比同模式 mock prompt 多约 **1.3–2.1k tokens/调用**。
6. **延迟与成本 C 上升约 25–30 倍 / 4.4–4.9 倍。** 单次 LLM 调用平均 3,907 ms（中位 3,808 ms，最大 6,763 ms）。成本 C 从 0.030–0.035 升到 0.146–0.156；但 C 由延迟主导（12 s × 1e-5 = 0.12），**不是 API 账单**。

---

## 7. 成本与预算

### 7.1 实际 API 用量与费用

> 计费口径：从每次运行 trace 的 `llm_call.prompt_tokens` 与 `completion_tokens` 汇总；按 DeepSeek `deepseek-chat` 公开价 **输入 $0.28 / 百万 tokens、输出 $0.42 / 百万 tokens** 估算（2025-09 起的 V3.2 价格口径），汇率按 1 USD = 7.2 CNY。实际账单以 DeepSeek 控制台为准；若沿用早期 V3 的 $0.27 输入 / $1.10 输出，估算上限约 $0.123（¥0.88）。

| 实验 | 运行数 | LLM 调用 | prompt tokens | completion tokens | 总 tokens | 实际成本 USD | 实际成本 CNY | 成本 C 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P2 | 6 | 18 | 81,385 | 13,676 | **95,061** | $0.0285 | ¥0.205 | 0.8382 |
| P3 | 12 | 36 | 199,517 | 28,853 | **228,370** | $0.0680 | ¥0.490 | 1.8056 |
| **合计** | **18** | **54** | **280,902** | **42,529** | **323,431** | **$0.0965** | **¥0.695** | **2.6438** |

- 每次运行平均：约 17,968 tokens（全模式平均）、¥0.039；每次 LLM 调用平均 5,989 tokens（prompt 5,202 + completion 788），平均延迟 3,907 ms。
- 连通性测试另用 20 tokens；计入后总实际 tokens 约 **323,451**，对费用影响可忽略。
- 单次运行实际 API 成本：P2 full ¥0.040、no_tools ¥0.028；P3 single ¥0.042、independent ¥0.040、collaborative ¥0.040。
- 已有 demo 的 `cost_usd=0.145–0.176` 也是**成本 C**，不是账单；按同样 token 口径其实际 API 费用约 $0.006/次。

### 7.2 预算执行

| 预算口径 | 限额 | 本次使用 | 使用率 | 结论 |
|---|---:|---:|---:|---|
| 金额预算 | ¥30 | ¥0.695（上限 ¥0.883） | **2.3%–2.9%** | **远未触及** |
| Token 软指标 | 约 200,000 | **323,431** | **161.7%** | **超出约 62%** |
| 报告 tokens（预算截断后） | — | 216,000（18 × 12,000） | — | 比实际少 107,431（**33.2%**） |

**为什么 token 超软指标但金额仍很低？**

1. 200,000 tokens 的软指标是按"约 12k tokens/次 × 18 次"估算的；真实模式每次 prompt 因 JSON Schema 注入增加约 1.3–2.1k/调用，使单次运行从 12k 升到 18.8k 左右。
2. DeepSeek `deepseek-chat` 的单价远低于"¥30 / 20 万 tokens ≈ ¥150/百万 tokens"的保守折算；实际约 ¥2.1/百万 tokens（混合输入输出），所以 32 万 tokens 仅约 ¥0.7。
3. 18 次运行是任务要求的 P2 3 日 × 2 变体 + P3 4 日 × 3 模式，不能再少；若要同时满足 20 万 tokens，需把每次 prompt 压到约 11k 以内（例如外置 JSON Schema、精简证据包），这属于后续代码/配置优化，本次未改动。

**结论**：金额预算（≤¥30）**大幅满足**；token 软指标**未满足**，但这是"预算记账口径 + Schema 注入"造成的，不是模型失控。**不应把 `cost_usd` 当作美元账单对外汇报。**

---

## 8. 失败与异常记录

### 8.1 失败/重试

| 项目 | 次数 | 说明 |
|---|---:|---|
| LLM 调用失败（`llm_error`） | **0 / 54** | 无超时、无 5xx、无 429 |
| 重试（`attempts > 1`） | **0 / 54** | 全部首次通过 JSON Schema |
| fallback 到 MockLLM（`llm_fallback`） | **0** | 无降级 |
| 角色 agent 异常（`agent_error`） | **0** | 无降级卡片 |
| 工具调用失败（`tool_call.ok=false`） | **0** | 17–18 次工具调用全部成功 |
| 知识库检索失败（`kb_search.ok=false`） | **0** | 无 KB 异常 |
| schema 错误 / 时点泄漏 | **0 / 0** | verifier 全部通过（P2 full、P3 全部） |
| 权限违规（`tool_denied`） | **51** | 仅 P2 `no_tools_no_kb`：17 次/运行 × 3，消融设计导致 |
| 草稿主张被拒（`claim_rejected`） | **22** | 仅 P2 `no_tools_no_kb`：7 / 7 / 7 条 numeric（第三次另 1 条 text），共 21 + 1 条，占草稿 46.8% |
| 预算撞顶（`budget_exceeded`） | **46** | P2 18 次 + P3 28 次；只是记账截断，不影响已生成内容 |

### 8.2 需要说明的异常/瑕疵

1. **`no_tools_no_kb` 的 verification=0 是设计性失败**：该变体把角色 `tool_permissions` 清空并禁用 KB，但角色仍按工具计划尝试调用，产生 17 次/运行的 `tool_denied`，verifier 将其计为 permission issue。mock 同样是 17 次、verification=0。**不要把它当成真实 LLM 的核验失败。**
2. **`p3_real/p3.md` 的自动生成文字仍写着"Mock LLM（无 API key 的确定性模式）"**。这是 `scripts/run_experiment.py` 中 P3 markdown 的硬编码文案，对本次真实运行不成立；本报告与 trace 为准。`p2.json` / `p3.json` 也没有 `llm_backend` 字段，建议后续在 run 元数据中补 `llm_mode`。
3. **`report tokens=12,000` 是截断值，不是实际用量**：见第 3、7 节；不要用它做成本核算。
4. **demo 未重跑**：`artifacts/demo/2024-08-05_real_summary.json` 已存在且 `backend=real`、verification passed；抽查 trace 为 `deepseek:deepseek-chat`，实际 tokens 18,683–19,495/模式。为节省预算未重复执行。
5. **未发现 key 泄漏**：报告中不包含 key 原文；key 仅由 `secrets/deepseek.key` 加载。

---

## 9. 解读与限制

### 9.1 可以支持的结论

1. **真实 DeepSeek 调用链在 P2/P3 全流程稳定**：54/54 调用首次通过结构化输出校验，18/18 运行产出完整 3 卡决策，无超时/重试/降级；真实模式与 mock 共用同一 RoleAgent/Orchestrator 代码路径，仅替换 LLMClient。
2. **真实 LLM 会改变"主张供给"结构**：在证据充足时更偏向 numeric（11 vs 6），在证据缺失时转向 directional（8–9 条/运行），而不是留空。这解释了 no_tools 下 task_completion 从 0 到 1、以及 fact/preference 冲突比例的变化。
3. **现有"终卡指标"对真实 LLM 已饱和**：数值错误率 0、证据准确率 1、无依据断言率 0 在 full/P3 全部出现，主要由自检回填与证据过滤保证；它们适合做**安全/一致性回归**，不适合作为"真实 LLM 事实性"的主指标。
4. **协同机制本身仍成立**：collaborative 稳定检出并解决 4.0 个/次冲突，single/independent 为 0；冲突解决方式包含 tool 重算、consensus 与 authority；无升级。三模式决策损失相同，说明当前协同收益尚未在 L 维度体现。
5. **成本结构需要区分"钱"与"协同成本 C"**：实际 API 费用 ¥0.70 左右，远低于 ¥30；`cost_usd` 0.15/次主要由 12 s 延迟折算，不能当账单。真实 LLM 的延迟是 mock 的约 25–30 倍，是部署时的主要体验成本。

### 9.2 限制（必须与结论一起读）

1. **单次运行、无统计重复**：每个变体 3 次、每个模式 4 次运行，均为单 seed、单 temperature=0；没有置信区间、没有配对检验。表中均值只能说明"这几次运行的行为"，不能外推为稳定期望。
2. **SYNTHETIC 数据**：DGP、文档、信号均为仿真；评估日仅 3–4 个；**不得据此得出真实市场预警结论**。真实结论需要真实 PIT 数据、更多评估日、多次重复（不同 seed/温度/模型版本）与人工复核。
3. **mock 对比多数不是同日配对**：P2 真实 3 日 vs `p2_final` 4 日仅 1 日重合；P3 真实 4 日 vs `p3_final` 6 日仅 2 日重合。本报告用同日子集（P2 full、P3 collaborative、P2 no_tools 单日）做了稳健性检查，方向一致，但**不能把均值差当作严格的 treatment effect**。
4. **指标被 guardrail 饱和**：终卡数值错误率/证据准确率/无依据断言率不能反映 LLM 原始输出的幻觉率；本次补充的 `claim_rejected` 只是代理指标，且只覆盖"无法绑定证据"的草稿，不覆盖"数值抄错但证据 ID 合法"等情况（后者已被回填覆盖）。后续应增加**草稿级**指标：原始数值与工具值的差异率、无证据 claim 比例、schema 修复次数等。
5. **task_completion 口径不适合跨后端比较**：它只数 claim 条数，不要求 numeric/工具证据或核验通过。真实 LLM 在 no_tools 下可轻易达到 1.0；建议改为"至少 1 条 numeric + 至少 1 条 text/directional 且有证据 + verification passed"的复合口径，或同时报告 `n_numeric_claims` 与 `evidence_coverage`。
6. **token 预算与真实 prompt 不匹配**：4,000/角色的记账预算对 mock 够用，对真实模式不够；JSON Schema 注入使 prompt 增加约 1.3–2.1k/调用，full/P3 仅 prompt 就 5.2–5.7k/角色。建议将 `max_tokens_per_agent` 提到 8,000（或把 Schema 从 prompt 移到工具/约束层），否则 `tokens` 永远显示 12,000、成本核算失真。
7. **成本估算依赖价格假设**：本报告按 $0.28/$0.42 估算；若实际价格不同，金额会变，但 32 万 tokens 的量级仍远低于 ¥30。`cost_usd` 的延迟权重（1e-5/ms）使 12 s 延迟贡献 0.12，主导了 C；若用于论文的 J=L+μC，需要明确 C 的量纲与权重敏感性。
8. **单一模型/供应商**：只测了 DeepSeek `deepseek-chat`（非 reasoning 模型）；其他模型、其他版本、流式/非流式、不同 `max_tokens` 可能改变 JSON 合规率、延迟与主张结构。demo 的 2024-08-05 结果也只代表一个日期/场景。
9. **并发/环境噪声**：运行期间工作区有其它 demo 进程写 trace（2024-08-05），本报告已按 run_id/日期/模式严格筛选，未混入统计；但共享磁盘/网络仍可能影响延迟的绝对值。

---

## 10. 复现命令

在 `D:\recently\commorcial` 下执行（Windows PowerShell）：

```powershell
# 0) 确认真实模式与 key 可用（不打印 key）
.venv\Scripts\python.exe -c "from cbr.config import load_settings; from cbr.llm import build_llm_client; s=load_settings(); c=build_llm_client(s); print(type(c).__name__, c.is_mock, c.mode, s.llm.temperature)"

# 1) P2：3 个评估日 × 2 个消融变体
.venv\Scripts\python.exe scripts\run_experiment.py --kind p2 --p2-dates 3 --run-id p2_real --config configs/experiments/p2_augment.yaml

# 2) P3：4 个评估日 × 3 种模式
.venv\Scripts\python.exe scripts\run_experiment.py --kind p3 --p3-dates 4 --run-id p3_real --config configs/experiments/p3_collaboration.yaml
```

可选（本次未重跑，已有产物）：

```powershell
# 2024-08-05 真实三模式 demo；若重跑会新增 trace/覆盖 demo summary
.venv\Scripts\python.exe -m cbr.orchestration.demo --real --as-of 2024-08-05
```

实际 token/成本提取：读取每次运行 `artifacts/traces/<run_id>.jsonl` 中 `action=llm_call` 的 `prompt_tokens`、`completion_tokens` 求和；汇总结果已写入 `artifacts/runs/p2_real/real_analysis.json` 与 `artifacts/runs/p3_real/real_analysis.json`。

> 注意：`run_experiment.py` 的 P3 markdown 模板硬编码了"Mock LLM"文案；真实运行时以 trace 的 `llm_mode` 为准。本次未修改 `scripts/`、`src/`、`configs/`。

---

## 11. 产物路径

| 类型 | 路径 | 说明 |
|---|---|---|
| 报告 | `docs/techdoc/pilot_results_real_llm.md` | 本文件 |
| P2 结果 | `artifacts/runs/p2_real/p2.json`、`p2.md`、`summary.json`、`SUMMARY.md` | 实验运行器生成的报告口径（tokens 为截断值） |
| P2 日志/汇总 | `artifacts/runs/p2_real/run.log`、`real_analysis.json` | 运行日志；trace 汇总（实际 tokens、拒绝数、冲突类型等） |
| P3 结果 | `artifacts/runs/p3_real/p3.json`、`p3.md`、`summary.json`、`SUMMARY.md` | 同上；`p3.md` 的 "Mock LLM" 文案为脚本陈旧文案 |
| P3 日志/汇总 | `artifacts/runs/p3_real/run.log`、`real_analysis.json` | 同上 |
| 审计 trace | `artifacts/traces/<run_id>.jsonl`、`artifacts/traces/<run_id>.decision.json` | 18 次运行的完整 LLM/工具/claim/冲突/核验轨迹 |
| 已有 demo | `artifacts/demo/2024-08-05_real_summary.json` | 本次未重跑；`backend=real`，verification passed |

---

## 附录 A：18 次运行明细（实际 token 来自 trace）

| 实验 | 变体/模式 | 日期 | run_id | 实际 tokens（prompt + completion） | 延迟 ms | 冲突/解决 | 核验 |
|---|---|---|---:|---|---:|---:|---|
| P2 | full | 2021-01-04 | `collaborative_2021-01-04_8a031054` | 18,783（16,382 + 2,401） | 13,604 | 4 / 4 | 通过 |
| P2 | full | 2022-08-04 | `collaborative_2022-08-04_60e2a4c5` | 18,816（16,376 + 2,440） | 12,250 | 3 / 3 | 通过 |
| P2 | full | 2024-03-06 | `collaborative_2024-03-06_6ba1df31` | 18,698（16,320 + 2,378） | 11,612 | 4 / 4 | 通过 |
| P2 | no_tools_no_kb | 2021-01-04 | `collaborative_2021-01-04_3c9e1051` | 12,903（10,803 + 2,100） | 11,404 | 1 / 1 | 未通过（permission 17） |
| P2 | no_tools_no_kb | 2022-08-04 | `collaborative_2022-08-04_3efa5f30` | 12,915（10,764 + 2,151） | 11,248 | 0 / 0 | 未通过（permission 17） |
| P2 | no_tools_no_kb | 2024-03-06 | `collaborative_2024-03-06_7792374b` | 12,946（10,740 + 2,206） | 11,312 | 0 / 0 | 未通过（permission 17） |
| P3 | single | 2021-01-04 | `single_2021-01-04_9615cd06` | 19,583（17,174 + 2,409） | 14,690 | 0 / 0 | 通过 |
| P3 | single | 2022-03-15 | `single_2022-03-15_d17bc43e` | 19,424（17,144 + 2,280） | 11,747 | 0 / 0 | 通过 |
| P3 | single | 2023-05-23 | `single_2023-05-23_932a9532` | 19,448（17,204 + 2,244） | 11,541 | 0 / 0 | 通过 |
| P3 | single | 2024-07-26 | `single_2024-07-26_eabe563c` | 19,514（17,147 + 2,367） | 12,463 | 0 / 0 | 通过 |
| P3 | independent | 2021-01-04 | `independent_2021-01-04_459cbb55` | 18,785（16,352 + 2,433） | 12,114 | 0 / 0 | 通过 |
| P3 | independent | 2022-03-15 | `independent_2022-03-15_04ff9851` | 18,756（16,350 + 2,406） | 11,839 | 0 / 0 | 通过 |
| P3 | independent | 2023-05-23 | `independent_2023-05-23_d7cc0e3b` | 18,858（16,364 + 2,494） | 12,121 | 0 / 0 | 通过 |
| P3 | independent | 2024-07-26 | `independent_2024-07-26_fbec56c2` | 18,720（16,301 + 2,419） | 11,954 | 0 / 0 | 通过 |
| P3 | collaborative | 2021-01-04 | `collaborative_2021-01-04_c810f9f4` | 18,916（16,385 + 2,531） | 12,298 | 4 / 4 | 通过 |
| P3 | collaborative | 2022-03-15 | `collaborative_2022-03-15_d13ae224` | 18,786（16,377 + 2,409） | 11,700 | 3 / 3 | 通过 |
| P3 | collaborative | 2023-05-23 | `collaborative_2023-05-23_e9135681` | 18,901（16,385 + 2,516） | 13,273 | 4 / 4 | 通过 |
| P3 | collaborative | 2024-07-26 | `collaborative_2024-07-26_4c603f28` | 18,679（16,334 + 2,345） | 10,799 | 5 / 5 | 通过 |

## 附录 B：每角色实际 tokens 与 4,000 预算（均值）

| 实验/模式 | regulator | investor | financing | 4,000/角色 |
|---|---:|---:|---:|---|
| P2 full | 6,403 | 6,369 | 5,993 | 全部超出（prompt 单独 5,196–5,611） |
| P2 no_tools_no_kb | 4,372 | 4,293 | 4,256 | 全部超出（prompt 3,542–3,645） |
| P3 single | 6,528 | 6,480 | 6,485 | 全部超出（prompt 5,719–5,725） |
| P3 independent | 6,388 | 6,422 | 5,970 | 全部超出（prompt 5,184–5,594） |
| P3 collaborative | 6,403 | 6,423 | 5,995 | 全部超出（prompt 5,194–5,603） |

> 上表说明：真实模式下即使不计 completion，full/single/independent/collaborative 的 prompt 已经超过 4,000/角色；`no_tools` 的 prompt 未超，但加 completion 后仍超。**12,000 的"撞顶"是系统性口径问题，不是个别日期异常。**

---

## 附录 C：一句话给决策者

> 真实 DeepSeek 跑通了 P2/P3，安全指标与 mock 同向，但"0 错误/0 无依据"是自检回填的结果，不是模型事实性证明；真实模型的成本很低（约 ¥0.7）、延迟很高（约 12 s/次）、token 记账严重低估（实际 32.3 万 vs 报告 21.6 万）。下一步应优先修 **token 预算口径 + task_completion 证据门槛 + 草稿级幻觉指标**，再用真实数据、多日期、多次重复验证。
