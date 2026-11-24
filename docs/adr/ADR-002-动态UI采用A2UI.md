# ADR-002：动态 UI 采用 A2UI + `genui`，废弃 SDUI

- 日期：2026-11-25 · 状态：✅ 采纳 · 决策人：产品负责人
- 相关：[docs/00-设计基线.md §3](../00-设计基线.md) · [docs/04-动态UI与Agent-Native设计.md](../04-动态UI与Agent-Native设计.md)

## 背景

旧版主 UI（`apps/web`）是自研 SDUI：后端下发 `AppManifest` / `PageSpec`，前端用自研的 `dashboard-kit` 渲染器（5 个包、7000+ 行 Dart/TS）把它渲染成页面。该方案的问题在 [旧系统语义清单](../research/旧系统语义清单-迁移依据.md) 中已记录：

- 协议在 Python pydantic / kit zod / app guard **三处手工维护**，无生成器、无 CI 门禁，已产生 theme / journeys / route-capability 三处字段漂移。
- `dashboard-kit` 半落地：`catalog` 整包零引用、`cn`/`Button`/`nav`/协议解析各存两份、5 个包 tsconfig 全部指向不存在的 `tsconfig.base.json`。
- 页面 spec 由**服务端**生成 → 与 ADR-001 的「无中央服务器」直接矛盾。

2026 年生成式 UI 生态已成熟：A2UI（Google，Apache 2.0，v0.9.1，v1.0 在 RC）定义 Agent→UI 的消息协议；Flutter 官方提供 `genui` 包作为 A2UI 渲染器；`genkit_a2ui` 把 Agent 框架接到 A2UI 上。另有 OpenUI（紧凑行式语言 + catalog 协商握手）、json-render（Vercel，无 Flutter 渲染器）等路线。

## 决策

1. **不使用 SDUI**。`AppManifest` / `PageSpec` / `dashboard-kit` / `apps/web` 全部废弃，不迁移。
2. 动态 UI 采用 **A2UI 协议**：Agent 在对话流中产出 `createSurface` / `updateComponents` / `updateDataModel`，客户端渲染。
3. 渲染器采用 **Flutter 官方 `genui` 包**（`SurfaceController` + `A2uiTransportAdapter` + `Conversation` + catalog）。
4. Agent 侧采用 **`genkit_a2ui`**，把 Genkit 的输出转换为 A2UI 信封。
5. **catalog 是安全边界**：只允许渲染我方登记过的组件；未登记组件一律拒绝（`validate: 'strict'`）。
6. `lib/genui/adapter/` 是**唯一**允许 `import 'package:genui/...'` 的目录，业务代码只依赖我方接口——因为 `genui` 目前仍是 experimental/alpha，API 可能破坏性变更。

## 旧协议如何处置

`AppManifest` / `PageSpec` / `dashboard-kit` **整体废弃**，不迁移、不兼容、不做双轨。原因：

- 二者回答的是不同问题——旧协议是「**这个产品有哪些页面**」，A2UI 是「**这次对话要展示什么**」。在纯客户端架构下，前者是静态路由表能自洽表达的东西，不需要一套线协议。
- 旧协议的三处手工副本已产生字段漂移；保留它等于保留一个已知有 bug 的系统。
- 领域语义（`ActionManifest` 的 kind/target/confirm/risk、角色规格、claim/evidence 模型、时点纪律）**全部继承**，只是载体从「服务端推页面 spec」换成「本地 Agent 产出领域对象」。

迁移对照表见 [docs/04-动态UI与Agent-Native设计.md §11](../04-动态UI与Agent-Native设计.md)。

## 后果

**正面**
- 不用自造渲染器、协议层、组件目录三件套；直接吃官方生态。
- 「新增界面不用发版」的能力保留，且**更彻底**——现在连服务端都不用有。
- catalog 机制天然是安全边界（模型只能渲染登记过的组件），比旧 SDUI 的「服务端推任意 props」更可控。

**负面 / 必须接受**
- `genui` 是 experimental/alpha，`genkit_middleware/agents.dart` 不在语义化版本保证内 → 必须用适配层隔离。
- A2UI v0.9，v1.0 在 RC → 协议版本需在配置中显式声明，升级走 ADR。
- 官方 `PromptBuilder.chat()` 的系统提示可达 3,000–5,000+ tokens → 需自建紧凑提示模板，按 `systemPromptFragments` 只注入所需片段。
- 旧版那些精心设计的**静态研究页面**（风险卡、证据板、情景、来源健康）不再有「服务端 spec」可依赖，必须改为**本地原生 Flutter 页面**；A2UI 主要承载 Agent 现场生成的部分。二者并存是预期形态，不是妥协。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 自研 JSON→Widget 渲染器 | 重新造轮子；且与 ADR-001 的「本地 Agent 生成 UI」相比，服务端 spec 路线本就多余 |
| `schema_build`（0.1.x）/ `sdui`（近两年无发布） | 生态不成熟；且都是「服务端推 spec」范式，与 ADR-001 冲突 |
| `flutter_json_forms` | 只覆盖表单、评分低；设置页表单动态需求低，手写更可控 |
| `flutter_quick_dart`（运行时执行 Dart） | 允许 Agent 执行任意逻辑 → 安全边界不可控 |
| json-render（Vercel） | 无 Flutter 渲染器 |

## 保留观察

**OpenUI**（紧凑行式语言 + catalog 协商握手 + Flutter renderer）作为协议层对照研究，**不实现**。若 A2UI 的 catalog 表达力不足或 v1.0 变更过大，重新评估。

## 关联决策

- ADR-001（无中央服务器 → 决定了必须由本地 Agent 生成 UI）
- ADR-003（Genkit Dart 作为 Agent 运行时）
