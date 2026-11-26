# ADR-003：多智能体运行时采用 Genkit Dart

- 日期：2026-11-25（2026-11-27 修订） · 状态：✅ 采纳 · 决策人：产品负责人
- 相关：[docs/00-设计基线.md §3](../00-设计基线.md) · [docs/03-多智能体架构.md](../03-多智能体架构.md) · [ADR-010](ADR-010-X-AlertAgent双核嵌套与LanceDB三库记忆架构.md) · [ADR-011](ADR-011-三主体升维与异构模型槽位路由及计算插件边界.md) · [docs/12-v1架构与工程收口清单.md](../12-v1架构与工程收口清单.md)

## 背景

旧版的多智能体体系在 Python 侧自研：`agents/role_agent.py`（7 步 Agent Loop）、`orchestration/`（R0–R5 六阶段编排 + 黑板 + 冲突分类 + 仲裁 + HITL）、`verification/`（六类核验）、`judgment/`（JEV 门卫）。

自研的部分其实只是「编排」，而**价值密度在语义**（Claim→Evidence 绑定、PIT 纪律、工具可重算哈希、冲突三分类、JEV 诚实降级），不在编排框架本身。用户明确要求「使用现成库优先！避免自己造轮子」。

Dart 侧可选的 Agent 框架在 2026 年已成熟：**Google Genkit for Dart**（`package:genkit`，v0.17，2026-09 发布，正走向 1.0），提供可恢复的 `generate()`、Agent 快照、后台子代理、可插拔遥测（`genkit_otel`）、OpenAI 兼容插件（`genkit_openai`），以及 `genkit_middleware/agents.dart` 的**子代理委派中间件**。

## 决策

1. **多智能体运行时采用 `package:genkit`**，不自研 Agent Loop。
2. DeepSeek 通道用 **`genkit_openai`**（DeepSeek 是 OpenAI 兼容，只需改 `base_url`），**不自研 HTTP 客户端**。
3. JEV（TypeSafe System One）**不是** OpenAI 格式，用 `dio` + 一层薄适配；JEV 是**裁判**不是生成者，保留其 `noul`/`choice`/`score` 三种问题类型语义。
4. 多智能体**委派**用 `genkit_middleware/agents.dart` 的 `agents()` 中间件；编排的领域语义（R0–R5、冲突三分类、仲裁优先级、HITL）由我方代码实现，不交给框架。
5. `lib/agents/` 是**唯一**允许 `import 'package:genkit/...'` 的目录。
6. 角色提示词与角色规格（数据域权限、工具权限、阈值、决策损失权重、禁止行为）**保留在配置文件里**，不硬编码进 Dart。

## 后果

**正面**
- 「Agent Loop」「流式」「工具调用」「重试」「快照恢复」「委派」这些最容易写错的部分不用自己写。
- DeepSeek 接入零 HTTP 层；只改 base_url 与模型名。
- 遥测（`genkit_otel`）可直接接 OpenTelemetry，比自研埋点标准。

**负面 / 必须接受**
- `genkit_middleware/agents.dart` 官方明示「不在语义化版本稳定性保证内，可能在任意 MINOR 版本变更」→ **委派能力必须封装在我方接口后**（`lib/agents/delegation/`）。
- Genkit 的抽象与本项目的领域模型（Claim / Evidence / RiskCard / ConflictType）**不是一一对应** → 需要一层领域适配（`lib/agents/domain/`），否则领域语义会被框架概念污染。
- 旧版「LLM 只产草稿、数值由证据回填、等级由确定性规则判定」这一信任根基**与主流 Agent 框架的默认心智模型相反**（框架默认 LLM 决定一切）→ 必须在提示词与编排中显式约束，并在核验层兜底。
- 旧版 DeepSeek 调用**无流式**，全是一次性 `chat.completions.create`；改 Genkit 后可流式，但流式会改变「JSON 一次性解析 + 修复重试」的容错路径 → 需要新的解析策略与回归测试。

## 关键约束（实现时必须遵守）

1. **LLM 不得直接产出最终结论**。它只产草稿；数值由工具证据回填，风险等级由确定性规则判定。
2. **LLM 不得直接调用工具**。工具调用由我方代码发起，受权限矩阵约束（`default_deny=true`），越权只记审计不执行。
3. **LLM 输出必须过 schema 校验**（`validate: 'strict'`），失败重试并记录 `schema_errors`。
4. **禁止静默降级为 Mock**（旧项目 `allow_mock=false` 语义）。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 继续自研 Agent Loop（照搬 Python 实现） | 违背「现成库优先」；且编排不是价值所在 |
| `flutter_quick_dart` + 运行时 Dart 脚本 | 安全边界不可控 |
| 直接用 OpenAI/DeepSeek 原生 SDK 拼装 | 放弃了 Agent 生态（委派、快照、遥测、流式管理） |
| LangChain Dart | 与 Genkit 相比，A2UI 桥接与 Dart 原生支持都更弱 |

## 2026-11-27 修订：激进现成库路线与红线钩子

1. **版本与全面接入**：Genkit Dart 已进入 `1.x`（当前锁 `1.0.3`）。除基础模型调用外，编排委派（含 `X-AlertAgent` 外环记忆/反思调度与 `R0–R5` 内环多主体委派）均应优先采用 `package:genkit` 及其 `agents` 中间件与多厂商插件实现；**v1 手写 HTTP/重试与状态机属过渡实现**，收口计划登记于 [docs/12-v1架构与工程收口清单.md](../12-v1架构与工程收口清单.md)。
2. **能力槽位路由**：按 [ADR-011](ADR-011-三主体升维与异构模型槽位路由及计算插件边界.md) 通过 Genkit 插件抽象能力槽位（默认全部回落单一默认密钥，支持高级多模型路由与实验锁单模型）。
3. **三条红线由确定性钩子硬守**：为消除框架「LLM 自由调用工具/直接拍板」与本项目红线的冲突，必须在 Genkit 中间件/工具包装钩子层强制执行：`default_deny` 权限门卫（先鉴权再发 RPC）、工具数值覆盖回填、以及无密钥/超时时的零 Mock 显式失败（`LlmFailure`）。

## 关联决策

- ADR-001 / ADR-006（无中央服务器 → 本地多进程架构下编排留在 Dart 壳）
- ADR-002（A2UI 通过 `genkit_a2ui` / `genui` 衔接）
- ADR-010（`X-AlertAgent` 双核嵌套与三库记忆）
- ADR-011（三主体升维与异构模型槽位路由）
