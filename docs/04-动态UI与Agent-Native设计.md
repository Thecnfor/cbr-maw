# 04 · 动态 UI 与 Agent-Native 设计

> 决策依据：[docs/00-设计基线.md §3](00-设计基线.md) · [ADR-002](adr/ADR-002-动态UI采用A2UI.md)
> 视觉与 catalog 契约：[docs/06-设计系统与美学规范.md §9](06-设计系统与美学规范.md)（VC-1~VC-8）｜文案约束：[docs/08-文案标准与术语表.md §9](08-文案标准与术语表.md)（T-1~T-10）
> 编排侧接口：[docs/03-多智能体架构.md §10](03-多智能体架构.md)

---

## 1. 从「服务端推页面」到「Agent 生成界面」

### 1.1 旧模式的问题

旧版 SDUI 的数据流是：

```
后端 manifest/page-spec  →  前端 dashboard-kit 渲染器  →  固定页面
```

它的问题不是「服务端驱动」本身，而是**这套机制在纯客户端架构下失去了存在理由**，并且连带引入了大量自造轮子：

| 问题 | 后果 |
|---|---|
| 协议三处手工维护（pydantic / kit zod / app guard） | 已产生 theme / journeys / capability 三处漂移 |
| 自研渲染器 + 自研 kit（5 包 7000+ 行） | 5 个包的 tsconfig 全部断链、10 个测试零执行入口 |
| 组件映射无编译期约束 | schema 与 props 漂移只在运行时暴露为「区块参数校验失败」 |
| 组件重复 | `Button`/`cn`/`nav`/协议解析/app-chrome 各存两份 |
| 页面是固定的 | Agent 只能吐文本，界面形态由前端预先决定 |

### 1.2 新模式

```
用户提问 → 本地 Agent 编排 → 领域对象（RiskCard/Claim/Evidence/Conflict…）
                                       │
                                       ▼
                              SurfaceBridge（我方唯一渲染入口）
                                       │ 领域对象 → catalog 组件 + 视觉/文案校验
                                       ▼
                    A2UI: createSurface / updateComponents / updateDataModel
                                       │
                                       ▼
                    genui SurfaceController → 原生 Flutter 组件树
```

**关键差异**：Agent 产出的是**领域对象**，由我方映射成受控的 catalog 组件；Agent **不直接写 UI 指令**。这比「让模型自由生成 UI」安全得多，也让界面始终服从同一套设计系统。

---

## 2. Agent-Native 的五条设计原则

| # | 原则 | 落地 |
|---|---|---|
| **AN-1** | **界面是结论的函数，不是页面的函数** | 同一份 RiskCard，在不同上下文（概览 / 对话 / 时间线 / 导出）由不同 catalog 组件组合呈现，不做「每个场景一套页面」 |
| **AN-2** | **Agent 只输出领域对象** | 模型产出 RiskCard / Claim / Evidence / Conflict / Cost 等领域类型；UI 由 SurfaceBridge 映射 |
| **AN-3** | **catalog 即安全边界** | 组件白名单 + 参数白名单 + 视觉白名单（06 §9 VC-1~VC-8） |
| **AN-4** | **动作必须回到受控通道** | 组件触发的任何动作走 [§6](#6-动作模型)，不直接调工具、不直接写库 |
| **AN-5** | **生成过程可见** | Agent 活动流实时展示「在做什么」，与审计流同源；用户永远知道结论从哪来 |

---

## 3. A2UI 协议模型与我们的映射

### 3.1 三件套

| A2UI 消息 | 语义 | 我们的用法 |
|---|---|---|
| `createSurface` | 创建一个渲染表面（`surfaceId` + `rootId`） | 一次研判 = 一个 surface；多轮对话可并存多个 surface |
| `updateComponents` | 更新组件树（邻接表结构，`{id, kind, children[], props}`） | 组件增删改；**组件 kind 必须在 catalog 白名单内** |
| `updateDataModel` | 更新数据模型（JSON Patch / RFC 6902） | 数值、状态、时间等数据与组件树**解耦**，流式更新不重绘整棵树 |

### 3.2 结构与数据分离的意义

组件树描述「长什么样」，数据模型描述「是什么值」。二者独立更新带来三个直接收益：

1. **流式友好**：数值先到 → 先出骨架与占位；数据到 → 只 patch 数据，不动结构。
2. **可复算**：数据模型里存的是领域对象引用（`evidenceId` / `claimId`），UI 只是投影；结论与界面解耦，界面可重建。
3. **可审计**：渲染前的领域对象就是审计记录的内容，不需要从 UI 反推。

### 3.3 版本

- A2UI 协议版本在 `configs/` 中**显式声明**（当前 `v0.9`，v1.0 在 RC）。
- `catalog_version` 独立于协议版本（VC-6）。
- 协议版本不匹配 → 明确报错并给出「请升级/降级」指引，**不做静默兼容猜测**。

---

## 4. 接线

### 4.1 组件

| 角色 | 选型 | 职责 |
|---|---|---|
| Agent 运行时 | `package:genkit` | 生成流、工具调用、委派、快照 |
| 协议桥 | `package:genkit_a2ui` | 把 Genkit 输出转成 A2UI 信封；`validate: 'strict'` |
| 领域映射 | **`SurfaceBridge`（我方）** | 领域对象 → catalog 组件 + 校验 |
| 渲染 | `package:genui` | `SurfaceController` + `A2uiTransportAdapter` + `Conversation` |

### 4.2 目录与隔离

```
lib/genui/
├── adapter/          # 唯一允许 import 'package:genui/...' 的目录
│   ├── surface_controller.dart
│   ├── transport_adapter.dart
│   └── conversation.dart
├── catalog/          # catalog 注册表 + props 契约 + 版本
│   ├── catalog_registry.dart
│   ├── components/   # 每个 catalog 组件一个文件，复用 lib/ui 的实现
│   └── catalog_components.json   # 真源（对齐 genui 实际标识）
├── bridge/
│   ├── surface_bridge.dart       # 领域对象 → A2UI 消息（唯一渲染入口）
│   └── visual_guard.dart         # CbrVisualGuard：视觉/参数白名单校验
├── actions/          # 组件动作 → 动作模型
└── model/            # A2UI 消息的数据模型（解码 + 校验）
```

**隔离原则**：`package:genui` 目前是 experimental/alpha，API 可能破坏性变更。业务代码只依赖我方 `SurfaceBridge` / `SurfaceController` 抽象，升级 `genui` 时只改 `lib/genui/adapter/`。

> 注：[06 §9.3](06-设计系统与美学规范.md) 建议的路径为 `lib/ui/a2ui/`；本设计统一归到 `lib/genui/`（与 [01-架构设计.md §4](01-架构设计.md) 的分层一致），以免 `lib/ui` 反向依赖 `lib/genui`。

### 4.3 数据流

```
用户输入
  → InvestigationService（对话入口）
  → Genkit generate()（流式）
      ├ 工具调用（受权限矩阵约束）
      ├ 领域对象产出（RiskCard / Claim / Evidence / Conflict / Cost / Gate）
      └ 每个领域对象 → SurfaceBridge.map()
                        ├ 组件映射（领域对象 → catalog 组件）
                        ├ CbrVisualGuard（组件名/参数名/颜色/图标白名单）
                        ├ 文案校验（08 §9 T-1~T-10）
                        └ → A2UI createSurface / updateComponents / updateDataModel
  → genui SurfaceController → 原生组件树
  → 用户交互 → 组件动作 → ActionDispatcher（白名单 + 风险级）→ 执行 → 回写数据模型
```

---

## 5. Catalog 体系

### 5.1 组成

| 部分 | 内容 | 真源 |
|---|---|---|
| 组件集 | `basic`（通用）+ `cbr.basic`（CBR 领域） | `lib/genui/catalog/catalog_components.json` |
| 组件实现 | 与 `lib/ui/components/` **同一份 widget**，不另写皮肤 | VC-1 |
| 可传参数 | 每个组件一份白名单（`label`/`value`/`variant`/`state`/`items`…） | 06 §9.2 |
| 拒绝参数 | 颜色/字号/字重/间距/圆角/阴影/字体/图标字形/透明度/z-index/任意 style | VC-2 |
| 图标 | 仅 Lucide 子集白名单（编译期枚举），只给图标**名** | VC-7 |
| 禁用元素 | Emoji、渐变、自定义 SVG、外链图片、Markdown 表格、代码块 | VC-8 |
| 状态集合 | loading / empty / error / disabled / 无权限 全集 | VC-3 |

完整组件表见 [06 §9.2](06-设计系统与美学规范.md)。

### 5.2 三个特有组件

| 组件 | 为什么必须有 |
|---|---|
| `ConfirmCard` | 高风险动作的确认界面。**动作风险级（L0/L1/L2）与风险等级（low/medium/high/critical）是两件事**，界面措辞必须分离（见 [08](08-文案标准与术语表.md)） |
| `AccessRequiredState` → `AccessRequired` | **本产品最特殊的 UI 状态**：数据不可得（需授权/需登录/反爬受限）。**绝不出现 0 / `--` / `N/A`**，只写来源 + 原因 + 单一主动作 |
| `CostMeter` | 成本与预算透明化：`J = L + μ·C` 的实时读数，让用户理解多智能体的代价 |

### 5.3 版本策略

- `catalog_version` 独立于 A2UI 协议版本。
- 升级 catalog 必须**同步更新 Agent 系统提示中的组件清单**，并记录变更日志。
- 组件被移除时：Agent 仍可能引用旧组件 → `CbrVisualGuard` 拒绝 → `renderError` → 降级为纯文本摘要（见 [§8](#8-错误与降级)）。

---

## 6. 动作模型

### 6.1 流程

```
组件 onAction(actionRef)
  → ActionDispatcher
      ├ 1. 白名单校验：actionRef.action 是否在 manifest/配置登记的具名动作中？
      │      否 → 拒绝 + console/audit 告警（不执行）
      ├ 2. 风险分级：L0 / L1 / L2
      ├ 3. 确认：L1/L2 渲染 ConfirmCard，用户确认/拒绝
      ├ 4. 幂等：生成 Idempotency-Key
      ├ 5. 执行：本地动作（导航/写入/刷新/导出）或 Agent 动作（继续研判）
      ├ 6. 回写：结果写入数据模型（updateDataModel），组件自动刷新
      └ 7. 审计：写 TraceEvent（action / args_hash / result_hash / latency_ms）
```

### 6.2 动作种类

| 种类 | 例子 | 副作用 | 风险级 |
|---|---|---|---|
| `navigate` | 跳转到某角色视角 / 某证据 | 无 | L0 |
| `refresh` | 重新抓取某来源 / 重算 | 触发本地写 | L0（本地只读刷新）或 L1（触发抓取） |
| `submit` | 提交一次研判、切换情景/模式 | 触发 Agent 编排 | L1 |
| `confirm` | 批准高风险操作 | 不可逆本地写 | L2 |
| `export` | 导出结论/证据链/图表 | 写文件到磁盘 | L1（内容含敏感数据时 L2） |
| `delete` | 清空投递箱 / 删除本地数据 | 不可逆 | L2（必须走回收站） |

> **[已定·重要]** 导航与刷新类动作**必须**是 L0。旧版因协议层把缺失的 risk 兜底成 L1，导致「刷新」「切换情景」每次都弹原生确认框——这是必须避免的回归。

### 6.3 不可越界

- 组件动作**不得**直接调用工具或写库，必须经过 ActionDispatcher。
- 动作参数不得携带可执行代码/表达式；只允许声明式参数。
- 所有写操作带幂等键；L2 操作先落操作日志，失败回滚；删除走回收站。

---

## 7. 流式与增量

| 场景 | 行为 |
|---|---|
| 生成中 | 对话流逐块追加消息；Agent 活动流实时刷新；**不**先渲染半成品 surface |
| 首个 surface | 领域对象齐备后一次性 `createSurface`，避免结构抖动 |
| 数值更新 | 走 `updateDataModel`，只 patch 数值 → 图表/表格增量刷新，不重绘树 |
| 用户中断 | 停止生成；已产出内容保留并标注「已中断」；未完成 surface 不下发 |
| 重连/断流 | 保留已有 surface 与消息；标记「连接中断」并提供重试 |

**骨架与流式的切换**：骨架屏只用于「等待首个 surface」；surface 一旦创建，**立刻替换骨架**，不允许骨架与内容同时出现（避免闪烁）。

---

## 8. 错误与降级

| 情形 | 处理 | 用户看到 |
|---|---|---|
| 组件未登记 | `CbrVisualGuard` 拒绝该 surface | `renderError{surfaceId}` + **纯文本摘要**（不含任何未经核验的数值） |
| 参数越界（颜色/字号等） | 丢弃该参数 + 记 trace | 正常渲染，参数取默认值 |
| 图标不在白名单 | 替换为默认图标 + 记 trace | 正常渲染 |
| `strict` 校验失败 | 拒绝该 surface | 同「组件未登记」 |
| 协议版本不匹配 | 明确报错 | 「前端与后端协议版本不匹配」+ 版本号 |
| 渲染期异常 | 块级错误边界兜底 | 该区块错误态，其余区块不受影响 |
| Agent 生成中断 | 停止并标注 | 「已中断」+ 已产出内容 |

**硬规则**：
1. **不得**用未校验内容渲染。
2. **不得**抛异常中断整个会话。
3. **不得**在降级文本里出现未经核验的数值。

---

## 9. 静态页面与 Agent Surface 的共存

两者并存是**预期形态**，不是妥协。边界规则：

| 内容 | 归属 | 理由 |
|---|---|---|
| 概览仪表盘、来源台账、设置页、数据卡列表、审计时间线 | **静态原生页面** | 结构稳定、需要高信息密度与精确布局；不适合交给模型 |
| 研判结论、角色视角对照、冲突与分歧、证据链、情景推演、探索式追问 | **Agent surface** | 形态随结论变化；模型能据此选择合适的表达 |
| 图表 | 静态页面用固定组件；Agent surface 用 `ChartCard` | 同一 widget，静态侧走本地数据，Agent 侧走数据模型 |

**判据**：**内容形态是否由结论决定**。是 → Agent surface；否 → 静态页面。

---

## 10. 调试与开发工具

| 工具 | 用途 |
|---|---|
| `genui` 官方 **Composer**（桌面 App） | 描述一段界面 → Gemini 生成 A2UI surface；浏览内置 catalog 组件；**编辑 A2UI JSONL 与数据模型并实时预览** |
| 自研 surface 检查器 | 在应用内查看当前 surface 的 A2UI 消息流、数据模型 patch 记录、guard 拒绝日志 |
| trace 面板 | 见 [03](03-多智能体架构.md) 的审计时间线；含 `renderError` 与 guard 拒绝事件 |

---

## 11. 与旧 SDUI 的迁移对照

| 旧 | 新 | 处理 |
|---|---|---|
| `AppManifest` / `PageSpec` 协议 | **废弃** | — |
| `dashboard-kit` 5 个包（7000+ 行） | **废弃** | 改用 `genui` 官方 SDK |
| `apps/web` 12 个 catalog 视图 | 部分保留为**静态页面**（概览/来源/设置/时间线），部分转为 Agent surface | 逐个判定，按 §9 判据 |
| `apps/web/components/ui/` 自建组件 | **保留并升格**为 `lib/ui/components/`，成为 catalog 的唯一实现（VC-1） | 语义继承 + 补状态与 a11y |
| 旧 `ActionManifest`（kind/target/confirm/risk L0/L1/L2） | **保留语义**，作为我方动作模型 | 语义继承 |
| 旧 `requiredCapability` 路由能力 | 转为**静态页面的路由守卫** | 语义继承 |
| `manifest.snapshot.json` 构建期路由枚举 | **废弃** | 静态导出不再需要路由快照（静态路由由 Flutter 路由表定义） |
| `global-error.tsx` 的 ProtocolError 分支 | **废弃** | 无服务端协议协商；改为 catalog 版本与 A2UI 协议版本校验 |

---

## 12. 待决事项

| 编号 | 事项 | 倾向 | 影响 |
|---|---|---|---|
| U1 | `genui` 实际 catalog 组件标识与参数签名（06 §9.4 T-1） | 落地时逐一对齐 | catalog 真源 |
| U2 | `genui` 是否支持组件参数的**运行时白名单**（T-2） | 若不支持，前置自研校验层 | 安全边界实现位置 |
| U3 | `updateDataModel` 能否绑定到 `KpiCard.value` 等字段（T-3） | 需要；否则退化为重建组件 | 流式体验 |
| U4 | catalog 版本号策略（VC-6 / T-4） | 语义化版本 + 变更日志 | 升级与兼容 |
| U5 | 静态路由是否也需要由 catalog 驱动 | 否 | — |
| U6 | 是否允许 Agent 生成**多 surface** 并排显示 | 首版允许单个 surface | 对话区布局 |
