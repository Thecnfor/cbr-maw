# lib/agents · 多智能体编排

> 设计真源：`docs/03-多智能体架构.md`；旧版语义参考：`commorcial/src/cbr/{orchestration,verification,agents,judgment,models}`（只读）。
> 本目录是**唯一**允许 import `package:genkit/...` 的位置（ADR-003）。当前实现用注入的
> `TextGenerator` 抽象隔离模型通道，未绑定 Genkit 具体 API；装配层可把 Genkit 适配器注入。

## 1. 编排时序（R0–R5）

```
R0.1 确定性检索 ──► 共享信号(kind=signal) + 角色工具调用计划内的工具证据(kind=tool)
R0.2 角色分析 ────► 三角色各自 LLM 草稿 → 自检回填 → 确定性定级（single 模式由一个通用 agent 依次做三主体）
R1  证据共享 ─────► 黑板三级去重 + 别名（single/independent 跳过）
R2  交叉验证 ─────► 双轨：工具重算 + LLM 互评（仅 collaborative/demo）
R3  分歧识别 ─────► subject 归一化 → fact / directional / preference
R4  协调仲裁 ─────► 工具重算 > 证据等级 > HITL；preference 保留差异不判错
R5  汇总核验 ─────► 六类核验 → 合成（finalLevel = 取更强，降级角色不参与）→ 事件流
```

事件流是**冷流**：`InvestigationController.run()` 每次监听都重新执行一次研判。

## 2. 四角色差异

| 维度 | regulator | investor | financing | crossValidator |
|---|---|---|---|---|
| horizon | 10 | 5 | 20 | 沿用被复核角色 |
| 工具白名单 | systemic_risk / capital_flow / … | risk_measure / capital_flow / … | funding_cost / … | 同被复核角色 |
| 升级阈值键 | `dy_spillover` | `max_drawdown` | `funding_cost_jump_bp` | 无 |
| 输出 | 风险等级 + 监管建议 | 风险等级 + 仓位/对冲 | 风险等级 + 融资安排 | 只出 confirmed/refuted/uncertain |

角色配置唯一真源：`roles/roles.json`（由 `docs/legacy-configs/roles.yaml` 迁移）。
**不要**在代码里硬编码角色阈值。

## 3. 事件流字段

| 事件 | 何时 | 关键字段 |
|---|---|---|
| `RunStarted` | 开始 | `runId, mode` |
| `AgentActivity` | 角色开始/结束、证据共享、复核、核验 | `agentRole, action, detail` |
| `ToolInvoked` | 工具调用（含被拒） | `tool, params, result, denied` |
| `ClaimProduced` | 一条 claim 通过回填 | `claimId, text, kind, evidenceIds, confidence` |
| `ConflictFound` | 检出/仲裁冲突 | `conflictId, category, details, escalated` |
| `RunFailed` | 显式失败（零 Mock） | `code, message, degraded, limitations` |
| `RunFinished` | 结束 | `summary{riskLevel, claimIds, evidenceIds, conflictIds, degradedRoles, limitations, tokensUsed, costUsd, partial}` |

**零 Mock 严格模式**：模型不可用 → `RunFailed`，不产出任何规则模板结论；
预算/时间耗尽 → `RunFinished.summary.partial = true` + limitations，绝不降级为 Mock。

## 4. 如何加一个新角色

1. 在 `roles/roles.json` 的 `roles` 下新增一项（`display_name / horizon_days / objective /
   focus / info_permissions / tool_permissions / thresholds / decision_loss_weights /
   escalation_keywords / escalation_threshold_key / forbidden_actions / output_style`）。
2. 在 `models/domain.dart` 的 `RoleId` 加枚举值（`producesCard` 决定是否出卡）。
3. 在 `roles/prompts/` 加 `<role>.md`，并在 `PromptBuilder.load` 的 `names` 列表登记。
4. 在 `tools/tool_registry.dart` 的 `ToolSpec.allowed_roles`（真源
   `contracts/tools/tools.json`）里授权工具——**先改契约再改实现**。
5. 补一条测试：该角色的 `tool_permissions` 与契约一致、越权被拒。

## 5. 目录

```
agents/
├── investigation_controller.dart  # 对外固定接口 + R0–R5 编排
├── run_events.dart                # 事件契约（外壳唯一依赖）
├── models/domain.dart             # 领域模型（Role/RiskLevel/Evidence/Claim/Conflict/…）
├── roles/                         # RoleSpec + roles.json + prompts + 角色智能体
├── claims/                        # 自检回填 + 确定性定级
├── blackboard/                    # 三级去重黑板
├── conflict/                      # 分歧识别 + 仲裁
├── verification/                  # 六类核验
├── budget/                        # J = L + μ·C 与硬预算
├── llm/                           # DeepSeek 生成 + JEV 裁判（零 Mock）
└── tools/                         # 权限矩阵 + 工具证据构造
```
