# CBR-MAW Web · DESIGN-NOTES

> 本文是 `web/` 的视觉与交互裁决记录：token 映射、组件清单、页面结构、状态管理、
> 无障碍与双主题验收，以及**与参考规范的每一处偏离及原因**。
> 唯一 token 真源：`src/styles/tokens.css`；组件内不得出现硬编码颜色 / 阴影 / 圆角。

- 版本：v0.2（2026-10-18，AI-native 流式交互）
- 技术基线：React 19.3 · Vite 8.3 · TypeScript 7.0 · Tailwind CSS v4.3 · Radix 原语 · Recharts 3.10 · lucide-react 1.59
- 参考：`D:/XRAK/product/cross-dashboard/DESIGN.md`、`app/globals.css`、`D:/XRAK/product/Xra-space/packages/ui/src/styles/tokens.css`、`D:/recently/person/rak-blog/DESIGN.md`、shadcn-conventions / design-reviewer、`docs/design/ai-native-interaction-spec.md`

---

## 1. 定位与边界

**是什么**：CBR-MAW 的 L6 决策支持界面。给研究 / 演示场景使用，核心任务是
「在指定 `as_of` 时点回放一次多智能体协同预警，并把结论、证据、分歧、核验与成本摊开可复核」。

**不是什么**：

- 不是交易终端，不提供买卖指令；不构成投资建议。
- 不是 Streamlit 的像素级复刻；信息架构沿用 `app/dashboard.py` / `chat.py`，视觉按 Linear / Vercel / Neon 级重做。
- 不引入第二套后端契约；`src/`、`app/`、`configs/`、`docs/` 零修改。

**两个页面**：

| 路由 | 目的 | 视觉强度 |
|---|---|---|
| `#/dashboard` | 驾驶台：一屏看风险，向下钻证据与审计 | 高密度、主行动「重新生成」 |
| `#/chat` | 对话：自然语言追问、引用溯源、关联决策卡 | 中等密度、主行动「发送」 |

---

## 2. 设计原则（取舍顺序）

1. **层级不靠猜**：任意相邻面用「surface 底色阶差 + 1px hairline」区分，卡片阴影只做几乎不可察的抬起。
2. **状态即颜色**：success / warning / info / destructive 只表达状态；数据系列用 viz-1..8；其余一律中性灰。
3. **一屏一个主行动**：驾驶台是「重新生成」，对话是「发送」；其余按钮为 outline / ghost。
4. **静态也成立**：关闭动画、加载失败、数据为空三种状态下布局不塌、信息不丢。
5. **数字优先**：所有数值等宽 + `tabular-nums` + 负字距；标题负字距；单位与阈值永远可见。
6. **可降级是一等公民**：`prefers-reduced-motion`、390px 移动端、503 中文错误、空态与骨架屏都是设计的一部分。

---

## 3. Token 映射

### 3.1 来源与职责

| 来源 | 本仓落地 | 说明 |
|---|---|---|
| `Xra-space/packages/ui/src/styles/tokens.css` | `:root` / `.dark` 的 `--background`、`--foreground`、`--primary`、`--muted`、`--border`、`--ring`、chart / sidebar / status / ease 等 | 生态基准；全量复制后只做下述可访问性修正 |
| `cross-dashboard/app/globals.css` | `--surface-0/1/2`、`--viz-1..8`、`--elevation-*`、语义 success / warning / info / destructive、字号与动效节奏 | 业务扩展；仪表盘层级与数据色 |
| 本仓补充 | `--success-ink`、`--warning-ink`、`--info-ink`、`--destructive-ink`、`--control-*`、`--terminal-*`、`--text-*`、布局常量 | 见 §3.8 与 §10 偏离说明 |

### 3.2 表面与几何

| Token | Light | Dark | Tailwind | 用途 |
|---|---|---|---|---|
| `--surface-0` | `oklch(0.985 0 0)` | `oklch(0.145 0 0)` | `bg-surface-0` | 页面底 |
| `--surface-1` | `oklch(1 0 0)` | `oklch(0.205 0 0)` | `bg-surface-1` | 卡片 / 侧栏 / 顶栏 |
| `--surface-2` | `oklch(0.97 0 0)` | `oklch(0.235 0 0)` | `bg-surface-2` | 卡内嵌套 / 行底 |
| `--border` | `oklch(0 0 0 / 10%)` | `oklch(1 0 0 / 12%)` | `border-border` | 发丝线 |
| `--input` | `oklch(0 0 0 / 12%)` | `oklch(1 0 0 / 16%)` | `border-input` | 输入框边 |
| `--ring` | `oklch(0 0 0 / 45%)` | `oklch(1 0 0 / 45%)` | `ring-ring` | 焦点环（**偏离：基准 28%**） |
| `--radius` | `0.625rem` | 同 | `rounded-lg` 等 | 10px 基准 |
| `--radius-card` | `1.25rem` | 同 | `rounded-card` | 仅卡片 20px |
| `--control-track` | `oklch(0 0 0 / 6%)` | `oklch(0.13 0 0)` | `bg-control-track` | segmented 轨道 |
| `--control-active` | `oklch(1 0 0)` | `oklch(0.27 0 0)` | `bg-control-active` | segmented 选中 |

卡内元素圆角一律 ≤ `rounded-xl`（14px），不出现「卡中卡同圆角」的套娃。

### 3.3 语义色与可用性

| 语义 | Light 基础 | Dark 基础 | 文字 ink（Light / Dark） | 用途 |
|---|---|---|---|---|
| success | `#16a34a` | `#22c55e` | `#15803d` / `#4ade80` | 核验通过、已解决、低风险、缓解 |
| warning | `#d97706` | `#f59e0b` | `#b45309` / `#fbbf24` | 中风险、待核验、推高风险、HITL |
| info | `#2563eb` | `#3b82f6` | `#1d4ed8` / `#60a5fa` | 偏好差异、说明 |
| destructive | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` | `#b91c1c` / `#f87171` | 高风险、未解决、核验异常、错误 |
| destructive-fg | `#ffffff` | `oklch(0.145 0 0)` | — | 实心危险 / 极高徽章的底色文字（**偏离**） |

- 基础色用于**点、条、描边、图表**；文字 / 小徽章一律用 `*-ink`，保证 11px 小字 ≥ 4.5:1。
- 四档风险不是四种新颜色：`low=success`、`medium=warning`、`high=destructive/10 文字`、`critical=实心 destructive`；等级文字始终存在，不靠颜色单独区分。
- 不使用渐变、毛玻璃、glow；`background` 的纯黑/纯白只留给 shadcn 原语，页面层用 surface。

### 3.4 数据可视化

| Token | Light（oklch） | Dark（oklch） | 用途 |
|---|---|---|---|
| `viz-1` | `0.62 0.19 260` | `0.70 0.16 260` | 概率柱、数值模态、趋势线 |
| `viz-2` | `0.60 0.21 295` | `0.68 0.19 295` | 文本模态 |
| `viz-3..8` | 见 `tokens.css` | 见 `tokens.css` | 备用系列 / 动作分类 |

规则：同一指标同色；图表只允许一种强调色 + 发丝网格；阈值线用 `destructive` 虚线，并在图例和 KPI 文案中重复说明；Recharts `isAnimationActive=false`。

### 3.5 字体与字号

| Token | 值 | Tailwind | 用途 |
|---|---|---|---|
| `--font-sans` | `Geist Variable` → `PingFang SC` → `Noto Sans CJK SC` → `Microsoft YaHei` | `font-sans` | 标题、正文、界面 |
| `--font-mono` | `Geist Mono Variable` → `SF Mono` → `Consolas` | `font-mono` / `.metric-value` | 数值、日期、ID、trace、payload |
| `--text-tiny` | 10px | `text-tiny` | 微型标注 / 坐标轴 / 版本号 |
| `--text-caption` | 11px | `text-caption` | 辅助说明、时间戳、徽章 |
| `--text-body` | 13px | `text-body` | **默认正文**（body 也是 13px） |
| `--text-desc` | 13.5px | `text-desc` | 页头描述、面板标题 |
| `--text-panel` | 15px | `text-panel` | 卡片主标题 |
| `--text-h1` | 26px | `text-h1` | 页面 H1 |
| `--text-metric` | 40px | `text-metric` | 大 KPI 数值 |

- 标题 / H1 负字距 `-0.02em`；`.metric-value` 额外 `tabular-nums` 与 `-0.02em`。
- 只打包 Geist 的 latin 子集（约 52KB woff2），中文走系统字体栈；不引入全量 CJK Web 字体。
- 没有 `text-[13px]`、`text-[26px]` 这类任意字号；新增字号先加 token。

### 3.6 阴影（只允许三档）

| 原始 token | Tailwind | 用途 |
|---|---|---|
| `--elevation-card` | `shadow-card` | 常态卡片，几乎不可察 |
| `--elevation-raised` | `shadow-raised` | 悬浮卡、下拉、toast、tooltip |
| `--elevation-overlay` | `shadow-overlay` | Dialog / Sheet |

实现说明：原始变量命名为 `--elevation-*`，在 `@theme inline` 里映射到 `--shadow-card/raised/overlay`，避免 `--shadow-card: var(--shadow-card)` 的自引用；**全仓只有这三个阴影工具类**。hover 不换阴影、不写 `box-shadow`。

### 3.7 布局与间距

| 项 | 值 |
|---|---|
| 栅格 | 4px 基准；卡片间 12–16px；面板内边距 16px；卡片内 14px；行内 gap 6–10px |
| 侧栏 | 248px（`--sidebar-width`），折叠 64px 预留；< 1024px 转左侧抽屉 |
| 顶栏 | 52px（`--topbar-height`） |
| 页面容器 | 最大 1200px；水平 `clamp(16px, 3vw, 32px)`；上 24 / 下 40 |
| 对话 | 最大 896px（`max-w-4xl`），输入区固定底部 |
| 主断点 | **1180px**：KPI 与主网格 3:2 切换为单列、右栏 sticky 生效；1280px：顶栏运行控件出现；1024px：侧栏出现 |
| 移动 | 390px 起可用；控件回落到页面内控制条，侧栏抽屉 |

### 3.8 动效 token

| Token | 值 | 用途 |
|---|---|---|
| `--dur-fast` | 150ms | hover / focus / segmented / dialog 入场 |
| `--dur-base` | 250ms | 页面区块入场 |
| `--dur-slow` | 420ms | 预留，仅用于大范围状态切换 |
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | CSS 默认曲线 |
| `--ease-out-quart` | `cubic-bezier(0.25, 1, 0.5, 1)` | 入场减速 |

只动 `transform` / `opacity`；`active:scale-[0.98]` 是唯一按压形变；无弹性 / 3D / 视差。

> v0.2 新增的 count-up（680ms）、打字机（≈1s）、toast 停留（3.2/5s）属于「内容揭示」节奏，
> 不新增 token：仍复用 `--ease-out`，并在 `prefers-reduced-motion` 下直接落位。详见 §15.9。

---

## 4. 组件清单

### 4.1 原子件（`src/components/ui/`，零业务、零 fetch）

| 组件 | 变体 / 能力 | 约定 |
|---|---|---|
| `button` | `default / secondary / outline / ghost / destructive / link` × `sm / default / lg / icon / icon-sm` | forwardRef + cva + cn + `asChild` + `data-slot`，焦点环、disabled、`active:scale` |
| `card` | `Card / Header / Title / Description / Content / Footer`，支持 `asChild` | `rounded-card` + `bg-surface-1` + `border` + `shadow-card` |
| `badge` | `default / secondary / outline / success / warning / info / destructive / critical / muted`，支持 `asChild` | 11px、pill、tabular-nums、语义色只表达状态 |
| `tabs` | Radix Tabs，下划线式 | 11px trigger、`data-[state=inactive]:hidden`（支撑 forceMount） |
| `separator` | Radix Separator | 1px hairline |
| `scroll-area` | Radix ScrollArea + 自定义 2px thumb | 细滚动条 |
| `tooltip` | Radix Tooltip + Portal | `shadow-raised`、11px、200ms delay |
| `input` / `textarea` | 原生控件 + token 样式 | `h-8`（页面内大控件可覆盖 `h-10`）、focus ring、`aria-invalid` |
| `dialog` | Radix Dialog（Overlay / Content / Header / Footer / Title / Description） | `rounded-card`、`shadow-overlay`、`max-h-[85vh]`、关闭按钮 aria-label |
| `select` | Radix Select（Trigger / Content / Item / Label / Separator） | 11px trigger、`shadow-raised`、键盘可达 |
| `skeleton` | `Skeleton` / `SkeletonText` | 仅透明度呼吸，**无 shimmer 渐变** |
| `status-dot` | `success / warning / danger / info / idle` | 纯色点，无 glow；可选 label 才进入无障碍树 |

### 4.2 业务组件

| 层 | 文件 | 职责 |
|---|---|---|
| common | `panel` | 面板标题栏 + hairline + 内容区，统一 20px 卡片 |
| common | `page-header` | mono 面包屑 + H1 26 + 13.5 描述 + 右侧状态 |
| common | `callout` | 语义提示块（success / warning / danger / info / neutral） |
| common | `empty-state` / `error-state` | 空态与中文错误 + 重试 |
| common | `stat` / `meter` / `detail-row` / `micro-label` | 指标、进度、键值行、微标签 |
| common | `top-progress` | 请求期间视口顶部 2px 不确定进度条（只动 transform） |
| common | `animated-number` | KPI count-up；reduced-motion 直接落位 |
| common | `icon-button` | 图标按钮 + Tooltip + aria-label |
| common | `toast`（`lib/toast.tsx`） | Portal toast + aria-live；复制 / 运行完成 / 失败 |
| AI | `command-palette` | ⌘K / Ctrl+K 命令面板（Dialog + 自写 listbox） |
| AI | `run-progress` | R0–R5 时间线 + 三主体 chip + 活动流 + 取消（驾驶台） |
| AI | `chat-run-progress` | 对话阶段进度 + 停止生成（复用 R0–R5 映射） |
| AI | `activity-item` | trace 活动行（RunProgress / 协同过程复用） |
| layout | `app-shell` / `sidebar` / `topbar` / `run-controls` / `theme-toggle` | 248px 侧栏、52px 顶栏、场景 / 时点 / 模式、主题切换、命令入口 |
| dashboard | `kpi-row` / `sparkline` | 2fr+1fr+1fr KPI、期限结构迷你趋势 |
| dashboard | `signal-panel` | Recharts 概率柱 + 60% 阈值线 + 期限统计（懒加载） |
| dashboard | `attribution` | 驱动因子横向条 + 模态贡献堆叠条 |
| dashboard | `agent-cards` | 三智能体卡：等级、关键指标、建议、claim / evidence 展开 |
| dashboard | `evidence-board` / `evidence-dialog` | kind 过滤 + 搜索 + 列表；来源 / 时点 / 工具版本 / inputs_hash / payload / citations |
| dashboard | `conflicts-panel` | 事实 / 方向 / 偏好徽章 + 解决结果 + 未解决升级提示 |
| dashboard | `verification-panel` / `trace-panel` | 6 指标 + 核验问题 + **协同过程 R0–R5 分组时间线**（角色 / 工具 / 跨度 / tokens / 原始 JSON） |
| dashboard | `data-cards-panel` / `export-panel` | 数据口径表 + Markdown / JSON / JSONL 下载与预览 |
| dashboard | `right-panel` / `dashboard-skeleton` / `dashboard-page` | 5 个 Radix Tabs、同尺寸骨架、页面装配 |
| chat | `chat-page` / `chat-message` / `chat-composer` / `chat-empty` | 线程、输入、示例、发送 / 停止 / 清空；流式阶段、打字机、复制 / 引用 / 重试、追问建议、上下文 chip |
| chat | `source-dialog` / `decision-summary` | 引用来源 Dialog、关联决策卡（跳转 / 下载） |

### 4.3 shadcn 约定落地

- 源码自持，不 import 组件库；`components.json` 固定 `radix-nova` / `neutral` / `lucide`。
- 交互原语全部 Radix：Tabs / Dialog / Select / Tooltip / ScrollArea / Separator / Slot；未手写弹层、下拉、焦点管理。
- 原子件 `forwardRef` + `displayName`；变体用 `cva`；类名一律 `cn()`；按钮 / 卡片 / 徽章支持 `asChild`；保留 `data-slot`。
- 图标只用 `lucide-react`，常规 14 / 16px；没有 emoji 作为功能图标。
- `cn()` 对 `tailwind-merge` 做了扩展：把 `text-tiny/caption/body/desc/panel/h1/metric` 归入 `font-size` 组。
  默认配置不认识这些自定义字号，会把 `text-body` 当颜色，与 `text-primary-foreground` 冲突并**丢掉后者**（实际导致过主按钮黑底黑字）。这是实现层修复，不改变视觉规范。

---

## 5. 页面信息架构

### 5.1 驾驶台

```
AppShell（248 侧栏 + 52 顶栏 + 可滚动 main；⌘K 命令面板 + Toast）
└─ TopProgress（请求期间视口顶部 2px）
└─ page-container（max 1200）
   ├─ PageHeader：H1 26 / 描述 13.5 / 场景·模式·生成于 / 右：风险徽章·run_id·获取时间
   ├─ 运行控件（< xl 显示；≥ xl 收进顶栏，避免重复）
   ├─ [运行中] RunProgress：R0–R5 时间线 + 三主体 chip + 最近活动 + 已用时 + 取消
   ├─ [刷新失败] 保留旧数据的错误条 + 中文说明 + 重试
   ├─ KPI：2fr（5 日概率 + 期限结构）+ 1fr（风险等级）+ 1fr（历史分位）+ 跨 2 列（协同成本）· 数值 count-up
   ├─ 主网格 3:2（≥1180）
   │  ├─ 左：风险信号图 → 驱动因子 + 模态贡献 → 三智能体风险卡（追问该主体）
   │  └─ 右：sticky「协同证据与审计」Tabs（淡入）
   │      证据（20，AI 解释证据） / 分歧（3，协调者复核） / 核验（含 R0–R5 协同过程） / 数据卡（27） / 导出
   └─ 页脚：L6 说明 · run_id · 不构成投资建议
```

- 证据 Dialog、来源 Dialog 由页面级单一实例承载，避免每个列表行各挂一个 Dialog。
- 右栏 sticky 高度 `calc(100dvh - 84px)`（52 顶栏 + 上下 16），内部滚动；左栏滚动时证据 / 核验始终可见。
- 加载：同尺寸骨架 + 阶段进度；错误：中文说明 + 重试 + 503 提示；空态：每个区块独立说明。

### 5.2 对话

```
ChatPage（整页 flex，线程内部滚动）
├─ TopProgress（发送期间视口顶部 2px）
├─ PageHeader：H1 / 描述
├─ 运行控件（< xl）
├─ 会话条：session_id / 消息数 / 生成中 / 清空 + 上下文 chips（scenario/as_of/mode）+ 清除 / 恢复
├─ 空态卡：3 个示例问题（点击即发送）；预填提示
├─ 线程：user 右（surface-2 气泡）；assistant 左（surface-1 气泡 + 头像）
│  ├─ 最新回复打字机 / 淡入（reduced-motion 直接显示）
│  ├─ 长回复 > 900 字折叠 320px，可展开全文
│  ├─ 引用 chips [n] → 来源 Dialog →（可匹配黑板证据）证据 Dialog → 让 AI 解释
│  ├─ 消息操作：复制 / 复制引用 / 重试（失败或停止）
│  ├─ 追问建议 chips（由 decision 确定性生成，点击只预填）
│  └─ 关联决策卡摘要：风险等级 / 三主体等级 / final_advice / 驾驶台跳转 / 下载简报
├─ 发送中：ChatRunProgress（R0–R5 + 最近活动 + 真实已用时 + 停止生成）
└─ Composer：Enter 发送 / Shift+Enter 换行 / IME 保护 / 预填后自动聚焦 / 清空后新 session
```

---

## 6. 状态管理与数据流

| 状态 | 位置 | 理由 |
|---|---|---|
| 场景 / as_of / 模式 / tab | URL hash 查询参数 | 可分享、刷新保留、前进后退；驾驶台与对话共享同一事实 |
| health / scenarios | `RunProvider`（Context + 模块级 Promise 去重） | 一次注入、全树消费；手动重载 |
| 决策卡 | `lib/decision.ts` 模块级 Map，键 `(as_of,mode,scenario)` + 版本号订阅 | 同组合立即出结果、并发去重；手动刷新 `refresh=true`；命令面板订阅版本号读取最新决策 |
| 决策运行态（stage/trace/run_id/取消） | `useDecision` 局部 state | 只在驾驶台生命周期内需要；卸载即 abort |
| trace / data-cards | `lib/resources.ts` 模块级缓存；流式 trace 由 `primeTraceCache` 预热 | 完成后「协同过程」立即渲染，不重复请求 |
| 对话消息 / session / 阶段 / 上下文清除 | `ChatProvider`（App 根） | 切换页面不丢；sessionStorage 只存 session_id；运行态含 stage/trace/transport |
| 命令面板 / toast | `AppShell` 局部 state + `ToastProvider` | 全局壳层；URL `?cmd=1` 仅首屏消费一次 |
| 主题 | `ThemeProvider` + `localStorage` | 双主题；首屏内联脚本防闪烁；`?theme=` 不写回偏好 |
| 局部 UI（过滤 / 搜索 / 展开 / 选中 trace） | `useState` | 瞬态，留在组件内 |

**为什么不用 SWR / nuqs / zustand**：参考规范面向 Next.js 16 + RSC；本仓是 Vite SPA，只有两个页面、一个决策端点和一个对话端点。引入第二套请求 / URL / 全局状态库会增加体积与心智负担。这里用 `Context + 模块缓存 + hash 查询` 达到同等效果，并在 README / 本文记录。**没有把服务端响应复制进第二数据源**：决策卡只存在一个模块缓存里。

**刷新语义**：
- 顶栏「重新生成」/ 命令面板「重新生成决策卡」通过 `refresh-bus` 通知当前驾驶台调用 `decision.refresh()`；请求带 `refresh=true` 绕过服务端 30 分钟缓存，并优先走 `/api/decision/stream`。
- 首次加载（本地无缓存）同样走流式；SSE 不可用时自动回退同步 `/api/decision`，运行面板明确标注「同步回退」。
- 切换场景 / 时点 / 模式按新 key 请求；命中前端缓存则立即渲染，并标注「本地缓存 · HH:mm:ss」。手动刷新意图只对当前 key 生效，切走再回来不会重复强制刷新。
- 不做轮询；健康与场景只在启动和「重新检测」时请求；SSE 为单条连接，完成后关闭。
- 对话发送优先 `/api/chat/stream`，回退 `/api/chat`；`session_id` 不变，阶段 / trace 只保存在内存运行态。

---

## 7. 加载 / 错误 / 空态

| 状态 | 表现 |
|---|---|
| 首次加载 | 与真实布局同尺寸的骨架（KPI / 主网格 / 右栏）+ **RunProgress**（R0–R5 / 三主体 / 最近活动 / 已用时 / 取消）；流式端点缺失时标注「同步回退」，阶段为本地估算 |
| 手动刷新 | 保留旧决策卡；顶部 2px 进度条 + RunProgress；完成后结果淡入 + toast；不闪屏 |
| SSE 不可用 | 自动回退同步端点；运行面板显示「同步回退」并说明阶段为本地估算，不影响结果 |
| SSE 协议错误 / 超时 | 中文错误（含「流式响应未收到最终决策 / 对话」或「300 秒超时」）+ 重试；不静默使用半截数据 |
| 用户取消 | AbortController 中止；保留上一次结果；toast「已取消本次生成」；无结果时显示可重试的取消空态 |
| 503 | 原样展示后端中文 `detail`；提示查看 `/api/health`、等待模块装配；重试同时重载 health / scenarios |
| 404（trace / evidence） | 独立说明（黑板未暴露 / artifacts 无文件），不视为界面错误 |
| 空数据 | 每个区块独立空态：无证据、无冲突、无驱动、无 trace、无数据卡、无三主体结果 |
| 长文本 | 证据 payload 可滚动；简报预览 360–420px 滚动；对话长回复折叠 |

骨架屏不用 spinner 代替布局；`aria-busy` 标记；`TopProgress` 为 `role=progressbar`；RunProgress / ChatRunProgress 用独立 `aria-live="polite"` 只播报阶段文案，避免整块内容反复朗读。

---

## 8. 无障碍

- **对比度**：正文 / muted 在 light/dark 均 ≥ 4.5:1；小徽章使用 `*-ink`；危险实心徽章使用主题对应的 `destructive-foreground`。
- **焦点**：所有可交互元素 `focus-visible:ring-2 ring-ring`；`--ring` 从 28% 提升到 45%，保证 ≥ 3:1 焦点指示；Radix 组件保留键盘导航，未破坏 Esc / 方向键。
- **键盘**：Tab 顺序自然；Tabs 用 Radix roving tabindex；模式 segmented 为 `aria-pressed` 按钮组；证据 / trace 行是原生 button。
- **命令面板**：Radix Dialog 焦点陷阱 + `Esc`；输入框 `role=combobox` + `aria-activedescendant`，列表 `role=listbox` / 选项 `role=option`；`↑↓ / Home / End / Enter`；无结果态；关闭后焦点归还触发元素。
- **读屏**：装饰图标 `aria-hidden`；图标按钮有 `aria-label`（新按钮同时有 `title`）；Dialog 有 Title + Description；表格有 `caption`；空态 / 错误为文本；运行中阶段变化通过独立 `sr-only aria-live="polite"` 播报，不朗读计时器。
- **输入法**：Enter 发送前检查 `nativeEvent.isComposing`，中文组合输入不会误发。
- **动效**：`prefers-reduced-motion: reduce` 下动画 / 过渡 0.01ms；Recharts 关闭动画；无装饰性常驻循环；JS 驱动的打字机与 KPI count-up 读取同一媒体查询并直接落位。
- **触控**：移动端主控件（场景 / 日期 / 模式 / 顶栏主行动 / 主题）为 40px；列表行与示例问题 ≥ 44px；图标密度按钮保持 32px（见风险）。
- **跳转**：「跳到主要内容」按钮聚焦 `main`，不使用 `href="#..."`（避免与 hash 路由冲突）。

---

## 9. Light / Dark 验收

在 headless Edge（Chromium 155）实际渲染并逐屏截图检查；**两套主题都单独验收**。

### 9.1 实测值

| 检查项 | Light | Dark |
|---|---|---|
| `body` 背景 | `oklch(0.985 0 0)` | `oklch(0.145 0 0)` |
| 卡片背景 | `oklch(1 0 0)` | `oklch(0.205 0 0)` |
| 卡片边框 | `oklch(0 0 0 / 10%)` | `oklch(1 0 0 / 12%)` |
| 卡片圆角 | 20px | 20px |
| H1 颜色 / 字号 | 黑 / 26px | 白 / 26px |
| 正文字号 | 13px | 13px |
| 侧栏 / 顶栏 | 248px / 52px | 248px / 52px |
| 主题存储 | `localStorage("cbr-theme") = light` | `= dark` |
| 首屏闪烁 | 无（内联脚本预置） | 无 |
| 阴影 | card 双层 1px/4px + 12px | 更低透明度 + 更深 overlay |
| 主按钮 | 黑底白字 | 白底黑字 |

### 9.2 断点与溢出

同一页面依次设置 390 / 768 / 1024 / 1180 / 1280 / 1440：

- `document.documentElement.scrollWidth === innerWidth`（全部）；
- `main.scrollWidth === main.clientWidth`（全部）；
- 768：无侧栏，主网格 / KPI 单列，控件在页面内；
- 1024：侧栏出现，主网格单列，右栏全宽；
- 1180：KPI 2fr+1fr+1fr、主网格 3:2、右栏 sticky 生效；
- 1280：顶栏运行控件出现，页面内控制条隐藏；
- 390：侧栏抽屉，顶栏只剩菜单 / 品牌 / 主行动 / 主题；无横向滚动。

### 9.3 验收清单

- [x] Light：页面 / 卡片 / 嵌套面三层可辨；文字对比度达标。
- [x] Dark：不是简单反色；surface 反向提亮、边框改白透明、语义色提亮、主按钮反相。
- [x] 卡片阴影只有三档；无 glow / 渐变 / 毛玻璃。
- [x] 标题负字距；数值 tabular-nums；无任意字号。
- [x] 焦点环在浅 / 深色下都可见（tab、composer、按钮）。
- [x] 骨架屏 / 进度 / 错误 / 空态在双主题下均检查。
- [x] 主题切换后刷新仍保持；切换按钮 aria-label 随主题变化。
- [x] `prefers-reduced-motion` 降级（CSS 全局 + 图表关闭动画）。
- [x] 390px 无横向滚动；抽屉可达全部导航与场景。
- [x] AI-native（v0.2）：RunProgress / 2px 进度条 / 命令面板 / 对话流式 + 打字机 / 三种上下文 AI 动作 / 协同过程 R0–R5 / 追问建议 / toast / count-up，light & dark 均实测；详见 §15。

---

## 10. 与规范的偏离及原因

| # | 偏离 | 原因 |
|---|---|---|
| 1 | `--ring` 从基准 28% 提升到 45% | 28% 黑在白色上只有约 1.9:1，不满足 WCAG 2.2 焦点可见性；45% 约 3.4:1 |
| 2 | 新增 `success-ink / warning-ink / info-ink / destructive-ink` | 基础语义色用于图形；11px 文字直接使用 `#d97706` 只有约 3.4:1，ink 变体保证 ≥ 4.5:1 |
| 3 | Dark 的 `destructive-foreground` 用近黑而非白色 | 深色主题 destructive 被提亮到 `oklch(0.704…)`，白字对比不足；近黑字在亮红上可读 |
| 4 | `surface-0/1/2` 不复用 Xra 的纯黑 / 纯白 | 需要「底 → 卡 → 卡内」三层阶差；light 用 0.985/1/0.97，dark 用 0.145/0.205/0.235（取自 cross-dashboard） |
| 5 | 新增 `control-track/active`、`terminal-bg/fg/muted` | 参考规范没有 segmented 控件与「内嵌终端」的语义 token；硬编码会破坏双主题与约束 |
| 6 | 原始阴影 token 命名 `--elevation-*`，再映射 `--shadow-*` | 避免 `@theme inline` 自引用；对外仍只有 `shadow-card/raised/overlay` 三个工具类 |
| 7 | 新增 `text-desc 13.5 / text-panel 15 / text-metric 40` | 规范要求 13.5 描述与 40px 大 KPI；用 token 替代任意值，避免 `text-[13.5px]` |
| 8 | 断点用 `min-[1180px]`；顶栏运行控件在 `xl（1280）` 才出现，1280 以下用页面内控制条 | 1180 来自规范主断点；若顶栏在 1024–1279 仍塞入场景 / 日期 / 模式会挤压面包屑与主行动，因此下放到页面控制条，**同一断点不重复出现** |
| 9 | 右栏 sticky + 固定 `calc(100dvh-84px)`，内部滚动 | 左栏有 3 张智能体卡与归因，明显长于右栏；sticky 让证据 / 核验在阅读卡片时保持可见，避免半屏空白。1180 以下取消 sticky |
| 10 | 对话长回复折叠 320px | 真实 LLM 回复可达 1800+ 字，且已包含完整 decision 摘要；不折叠会形成整屏文字墙。折叠不删除内容，显式「展开全文」 |
| 11 | 驾驶台没有单独的 `final_advice` 面板 | 三主体建议已在智能体卡；完整综合建议在对话摘要与导出简报中；再加一块长文本会与「一屏一个主行动」冲突。最终裁决保留在导出物中可复核 |
| 12 | 不引入 GSAP / SWR / nuqs / zustand | 这是 Vite SPA（非 Next/RSC），动效只有 hover / dialog / 骨架；引入动画引擎或第二套数据 / 状态库会增加体积与复杂度。所有动效仍在规范的时长 / 缓动 / transform-only 边界内 |
| 13 | 未内置 Playwright / E2E 依赖 | 交付不夹带测试浏览器；本次用 headless Edge 做了冒烟（截图与计算样式），脚本在交付前移除。后续可加独立 E2E 工程 |
| 14 | 日期输入显示随浏览器 locale（可能 `08/05/2024`） | 使用原生 `<input type="date">` 换取无障碍与键盘体验；提交值始终是 ISO，中文浏览器显示为 `YYYY/MM/DD` |
| 15 | 侧栏底部外链 Streamlit 回退（8501） | 明确保留回退入口；不影响主界面，不修改 Streamlit 代码 |
| 16 | 证据 Tabs 使用 `forceMount` + `data-[state=inactive]:hidden` | 保留过滤 / 搜索状态；Radix forceMount 不会自动隐藏，需显式 CSS；已加在 TabsContent 原语上 |
| 17 | 顶栏图标按钮 40px（移动）/ 32px（桌面），未全部 44px | 52px 顶栏 + 高密度约束；主控件已提升到 40px，列表行 / 示例按钮 ≥ 44px。44px 全量触控模式列入后续 |
| 18 | `cn()` 扩展 tailwind-merge 字号组 | 自定义 `text-body` 等被误判为颜色，导致主按钮丢 `text-primary-foreground`；扩展后自定义字号与颜色可共存 |
| 19 | 命令面板自写（不引入 cmdk / kbar） | 现有依赖里没有命令面板库；用 Radix Dialog + 受控 listbox 约 200 行即可覆盖分组、过滤、键盘与焦点陷阱，避免为单一交互增加依赖 |
| 20 | Toast 自写（不引入 `@radix-ui/react-toast`） | 同一原因；Portal + `role=status/alert` + `aria-live` 已满足语义，样式完全 token 化 |
| 21 | SSE 端点缺失时允许浏览器记录一次 404 | `fetch` 无法静默处理网络 404；前端捕获后立即回退同步端点，UI 标注「同步回退」。后端 SSE 就绪后该 404 自动消失，无需前端改动 |
| 22 | Tab 切换只有淡入 + 2px 位移，没有高度过渡 | 右栏在 ≥1180px 为固定高度 sticky 面板，内容高度不变；硬做高度动画会违反「只动 opacity/transform」并引发布局抖动。移动端高度由内容自然决定，同样不做高度动画 |
| 23 | 骨架屏保留透明度呼吸，不做 shimmer 渐变 | 视觉规范明确禁止渐变 / 毛玻璃；现有 `.skeleton` 只动 opacity，且与真实布局同尺寸。spec 的「shimmer」按规范降级为 pulse |
| 24 | 打字机只作用于「最新一条」助手消息，约 1s | 历史消息重放打字机会造成重复噪音；`lastCompletedTurnId` 2.6s 后清空，刷新 / 重挂载不重播；reduced-motion 直接显示 |
| 25 | 回退同步端点时 R0–R5 推进为本地估算 | 没有 `stage` 事件可用；面板与 footer 明确写「同步回退 · 阶段为本地估算，不代表后端真实事件」，结果仍来自同一次真实运行 |
| 26 | 「清除上下文」只清 `as_of`（场景仅展示） | `ChatRequest` 契约只有 `message / as_of / session_id / mode`，没有 scenario 字段；场景 chip 仍展示，清除后请求发送 `as_of: null`，模式仍按 URL 发送 |
| 27 | 开发 / 预览服务器额外代理 `/docs`、`/openapi.json` | 命令面板「打开 API 文档」在 Vite 下需要同源访问 Swagger；生产同源本就可达，代理只影响 dev / preview，不硬编码后端 host |
| 28 | KPI count-up 680ms，toast 3.2s / 错误 5s | 在 `--dur-base` 250ms 与 `--dur-slow` 420ms 之外需要一个可读的数字滚动与 toast 停留；均使用 token 缓动 `--ease-out`，reduced-motion 直接落位 |
| 29 | `?cmd=1` 消费后从 URL 移除 | 否则刷新 / 分享链接会反复弹面板；截图脚本在首屏即可拿到打开状态，不影响验收 |

---

## 11. 性能预算与实际

| 项 | 预算 | 实际（生产构建 v0.2） |
|---|---|---|
| 首屏 JS（gzip） | ≤ 180KB | ≈ 168.65KB（React + Radix + 应用 + 命令面板） |
| 首屏 CSS（gzip） | ≤ 15KB | ≈ 10.03KB |
| 字体（woff2） | ≤ 60KB | ≈ 52KB（Geist + Geist Mono latin） |
| 图表 chunk（gzip） | 懒加载 | ≈ 105.39KB，仅决策卡出现后加载 |
| 对话 chunk（gzip） | 懒加载 | ≈ 10.08KB（含流式进度 / 消息操作） |
| dist 总体积 | — | 1,031,670 B（0.98 MiB，7 个文件） |
| 决策 JSON | 60–100KB | 实测 52–57KB（真实 LLM 运行） |
| 轮询 | 0 | 0（SSE 单连接，完成后关闭） |
| 列表规模 | 20 证据 / 94–97 trace / 27 数据卡 | 无虚拟化；协同过程仅在核验页展开时挂载 |
| 流式解析开销 | — | 单 TextDecoder + 行缓冲；trace 只保留最近 8 条运行活动，完成后按 run_id 缓存全部事件 |

- 决策请求 12–24s（真实 DeepSeek，实测），期间显示 RunProgress / 2px 进度条；mock 模式约 2s。
- 30 分钟缓存命中时通常 < 50ms；前端跳过「0s 完成」toast。
- 图表懒加载 + 关闭动画，避免首屏主线程被 Recharts 占用；协同过程列表 97 行在固定 340px ScrollArea 内，无横向溢出。
- 命令面板 / toast / 打字机 / count-up 均无新增依赖；首屏 gzip 仍低于 180KB 预算。

---

## 12. 内容模型与字段映射

| 契约 | 界面 |
|---|---|
| `RiskSignal.level / horizons / percentile / drivers / modality_contrib / model_version / label_version / evidence_id` | KPI、风险信号图、驱动因子、模态贡献、页脚证据 id |
| `DecisionCard.cards[role]`（`risk_level / headline / key_metrics / recommendation / claims / limitations / tool_calls / tokens / latency_ms / round`） | 三智能体卡；claims 内 evidence_id chips；局限在展开区 |
| `Evidence`（`kind / as_of / title / summary / value / unit / source / tool / produced_by / citations / verified / hash / payload`） | 证据板 + 证据 Dialog |
| `Conflict`（`type / severity / resolved / resolution / resolved_by / roles / claims / evidence_ids`） | 分歧与协调面板 |
| `VerificationReport`（6 类计数 + issues + passed） | 核验 6 指标 + 问题列表 |
| `CoordinationStats`（rounds / evidence_shared / duplicate / conflicts / tool_calls / tokens / latency / cost） | 协同成本 KPI + 页脚 |
| `TraceEvent`（`ts / step / role / action / tool / args_hash / result_hash / detail / latency_ms / tokens`） | 运行中活动流（最近 4–6 条）+ 协同过程 R0–R5 时间线 + 原始 JSON 展开 |
| `DataCard`（`series_id / name / source / frequency / coverage / release_lag_days / pit_grade / unit / notes`） | 数据卡表格 + 备注 |
| `ChatResponse`（`reply / citations / decision / trace_id / as_of`） | 对话线程 + 打字机 + 引用 chips + 关联决策卡 + 追问建议 |
| `StageEvent`（`stage / label / role / status / action / ts`，SSE §1.3） | RunProgress / ChatRunProgress 的 R0–R5 时间线与三主体 chip；映射集中在 `lib/coordination.ts` |
| `Scenario`（`scenario_id / name / as_of / description / tags`） | 侧栏场景列表 + 顶栏选择器 |

所有数组 / 对象在使用前做空值降级（`?? []` / `?? {}`），字段缺失显示「—」，不抛异常。

---

## 13. 风险与已知限制

| 风险 | 影响 | 缓解 |
|---|---|---|
| 真实 LLM 12–24s（决策 / 对话） | 等待 | RunProgress + 2px 进度条 + 真实已用时；可取消（AbortController）；同 key 缓存；手动刷新保留旧数据；不做轮询 |
| 部署环境未启用 SSE 或代理缓冲 | 浏览器记录 404 / 流迟迟不结束 | 自动回退同步端点；UI 明示「同步回退」；后端 `streaming.py` 已实测，端点上线 / 代理放行后无需前端改动 |
| SSE 心跳 / 代理超时 | 长请求被中间层断开 | 客户端 300s 超时 + 中文协议错误；后端每 10s `: ping`，响应头 `X-Accel-Buffering: no` |
| 回退时没有真实阶段事件 | 阶段为本地估算，可能不精确 | 面板与 footer 明确标注「本地估算 / 不代表真实事件」；结果本身仍来自真实运行 |
| 97 条 trace 的分组展开 | 核验页信息密度高 | 默认只展开第一个非空阶段 + 「展开全部 / 收起全部」；固定 340px ScrollArea；点击单条才渲染原始 JSON |
| 超长回复（1800+ 字）打字机 | 1s 内多次 Markdown 重解析 | 分 24–64 步、最多 ~1s；仅在最新一条消息执行；reduced-motion 直接显示；自动贴底避免结尾被推出视口 |
| 上游回复极长（1800+ 字） | 对话文字墙 | 320px 折叠 + 展开全文；关联决策卡独立摘要 |
| trace / evidence 可能 404 | 核验页 / 证据弹窗空 | 独立中文说明 + 重试 / 回退 GET；不误报为界面错误 |
| 证据引用未暴露在黑板 | 证据列表缺项 | 单独提示缺失 id，点击尝试 `/api/evidence/{id}` |
| 移动端部分图标按钮 32px | 触控偏小 | 主控件 40px；列表 / 示例 ≥44px；后续可加 44px 模式 |
| 原生 date 显示随 locale | 视觉不一致 | 值始终 ISO；文档说明 |
| 后端契约演进 | 字段缺失 / 新增 | 类型可选 + 空值降级；新增字段只需扩展 `types.ts` 与展示 |
| 生产必须挂在 `/ui/` | 改路径会 404 | `vite.config.ts` base 与 FastAPI 挂载一致；README 明示 |
| 缺少自动化 E2E | 回归靠人工 | 本次用 headless Edge + CDP 冒烟（控制台 / 交互路径 / 6 档宽度）；建议后续加独立 Playwright 工程 |

---

## 14. 后续（不阻塞当前交付）

1. 后端 SSE 端点已在临时端口 8011 + 生产构建实测通过（decision / chat / 取消）；后续部署时复核真实 `run / stage / trace` 序列与代理不缓冲即可。
2. 增加独立 E2E（Playwright）覆盖命令面板键盘、流式进度、取消、对话打字机、上下文 AI 动作。
3. 44px 触控模式与更细的移动端密度切换。
4. 证据 / trace 深链（`#/dashboard?...&evidence=...`）与复制链接。
5. 报告打印样式（A4）与 CSV 导出。
6. 如需复杂编排动画，按规范首选 GSAP，并只在 `lib/ui/gsap.ts` 注册一次；当前动效仍保持 CSS / rAF 轻量实现。

---

## 15. AI-native 交互（v0.2）

> 权威需求与 SSE 契约：`docs/design/ai-native-interaction-spec.md`。本节记录前端如何落地、回退、
> 动效参数与验收结果；不改后端 `src/`、Streamlit 与 token 真源。

### 15.1 目标

从「结果展示页」升级为「可观察、可打断、可追问、可键盘驱动」的协同工作台：

1. 用户能看到多智能体正在做什么（R0–R5、三主体状态、trace 活动），而不是盯着骨架屏；
2. 能在运行中取消，失败能重试；
3. 结果出来后能就地追问（主体 / 证据 / 分歧），问题自动带到对话并预填；
4. 不新增依赖、不破坏 light/dark、token、a11y 与 reduced-motion。

### 15.2 新增 / 修改的文件

**新增（lib）**

| 文件 | 职责 |
|---|---|
| `src/lib/stream.ts` | SSE 解析与 `streamDecision` / `streamChat`；`StreamUnavailableError` / `StreamProtocolError` / `ApiError` 分层 |
| `src/lib/coordination.ts` | `TraceEvent.action` → R0–R5 映射；`groupTraceEvents`；`buildStageTimeline`；`buildRoleStates`；活动描述 |
| `src/lib/suggestions.ts` | 从 DecisionCard 确定性生成 4 条以内追问建议 |
| `src/lib/ai-actions.ts` | 上下文 AI 动作 → 对话预填的单次信箱 + 订阅 |
| `src/lib/toast.tsx` | ToastProvider / useToast / Portal 渲染（无新依赖） |
| `src/lib/motion.ts` | `usePrefersReducedMotion`、`useElapsedSeconds`、`fmtElapsed` |
| `src/lib/clipboard.ts` | Clipboard API + `execCommand` 回退 |

**新增（components）**

| 文件 | 职责 |
|---|---|
| `src/components/command/command-palette.tsx` | ⌘K / Ctrl+K；Radix Dialog + 自写 listbox；`?cmd=1` |
| `src/components/dashboard/run-progress.tsx` | 驾驶台运行面板：R0–R5 + 三主体 + 最近活动 + 取消 |
| `src/components/dashboard/activity-item.tsx` | 活动行；RunProgress 与协同过程共用 |
| `src/components/chat/chat-run-progress.tsx` | 对话阶段进度 + 停止生成 |
| `src/components/common/top-progress.tsx` | 视口顶部 2px 不确定进度条 |
| `src/components/common/animated-number.tsx` | KPI count-up |

**修改：** `lib/types.ts`（StageEvent / RunEvent / StreamErrorPayload）、`lib/api.ts`（`primeTraceCache`）、
`lib/decision.ts`（流式 + 回退 + 取消 + 运行态 + 缓存版本订阅）、`lib/chat-context.tsx`（chat/stream + 阶段 + 重试 + 上下文清除）、
`lib/refresh-bus.ts`（跨页 pending refresh）、`dashboard-page` / `agent-cards` / `evidence-dialog` / `conflicts-panel` /
`right-panel` / `kpi-row` / `trace-panel` / `chat-page` / `chat-message` / `chat-composer` / `topbar` / `app-shell` /
`main.tsx` / `vite.config.ts` / `styles/tokens.css`；删除已无引用的 `common/analysis-progress.tsx`（由真实事件驱动的 RunProgress 取代）。

### 15.3 SSE 客户端

`lib/stream.ts` 使用 `fetch` + `response.body.getReader()`（不依赖 EventSource：chat 需要 POST + JSON body）：

- 事件：`run / stage / trace / decision|chat / error`；注释 `: ping` 忽略。
- 解析：`TextDecoder` 增量解码；按 `\n` 拆行并去 `\r`；支持跨 chunk、多行 `data:`、`event:` / `id:`；
  空行 dispatch；EOF 处理残留 buffer；坏 JSON 单行跳过但不中断流。
- 连接：`Accept: text/event-stream`，`cache: no-store`；POST 自动加 `Content-Type: application/json`。
- 控制：外部 `AbortSignal` 与 300s 超时通过内部 controller 合并；用户取消保持 `AbortError`，超时转为中文
  `StreamProtocolError`。
- 结束：最后一个业务事件必须是 `decision` / `chat`；否则报「流式响应已结束，但未收到最终…」。
- 失败：
  - 非 2xx / 非 `text/event-stream` / 无 body / 网络不可达 → `StreamUnavailableError`（调用方回退同步）；
  - 已连上但无任何可解析事件 / 无最终事件 / 超时 → `StreamProtocolError`（中文错误 + 重试，不静默回退）；
  - `error` 事件 → `ApiError(status, 后端中文 message)`。

### 15.4 回退策略与状态机

`useDecision`：

```text
本地缓存命中（且非 refresh） → 直接渲染
否则：
  phase=streaming → GET /api/decision/stream
    ├─ decision → cache + primeTraceCache → 淡入结果 + toast
    ├─ StreamUnavailableError → phase=fallback（同步回退）→ GET /api/decision
    │     ├─ 成功 → 结果 + toast（transport=sync）
    │     └─ 失败 → 中文错误 + 重试
    ├─ StreamProtocolError / ApiError → 中文错误 + 重试
    └─ AbortError（用户取消） → 保留旧结果 / 取消空态
```

- 首次加载与「重新生成」都优先流式；`refresh=true` 绕过服务端 30 分钟缓存。
- 回退时没有 `stage/trace` 事件，RunProgress 用真实已用时做本地阶段估算，但显式标注
  「同步回退 · 阶段为本地估算，不代表后端真实事件」；结果仍来自同一次真实运行。
- `useDecision.cancel` 只 abort 当前控制器；节点卸载自动 abort，不会继续烧 token。
- 手动刷新意图只对当前 `(as_of, mode, scenario)` 生效，切走再回来不会重复强制刷新。
- `decision` 模块缓存新增版本号 + `useSyncExternalStore` 订阅：命令面板在决策完成后会把
  「为什么监管判定为未知？」更新为真实等级，并显示 `run_id` 操作提示。

`ChatProvider` 同理：`/api/chat/stream` 失败回退 `POST /api/chat`；`run` 保存 `startedAt / transport / runId /
stageEvents / activities`；`lastCompletedTurnId` 驱动一次打字机；会话、上下文清除状态在页面切换时保留。

### 15.5 运行中 UI

- **TopProgress**：`position: fixed; top: 0; height: 2px`，子条宽 1/3 + `transform` 平移动画；`role=progressbar`
  仅表达「有请求进行中」，不伪造百分比。已从带 `animate-rise` transform 的页面容器中移出，避免 fixed 相对容器定位。
- **RunProgress**（驾驶台）：
  - 头部：旋转图标 + 「协同运行中」+ `SSE 流式` / `同步回退` 徽章 + `run_id` + 真实已用时 + 取消；
  - 左列：R0–R5 时间线（阶段标题、`started/finished`、角色、最新 label、完成数）；
  - 右列：监管 / 投资 / 融资状态 chip（等待 / 分析中 / 已完成）+ 最近 4–6 条 trace 活动（`ActivityItem` 复用）；
  - 回退时：三主体 chip 显示「分析中」，活动区给出「同步请求进行中…」与占位骨架，不伪造 trace；
  - 独立 `sr-only aria-live=polite` 只播报阶段文案；整块 `aria-busy`。
- 完成后按 `run_id` 作为 key 触发 `animate-rise` 淡入替换；完成 toast 跳过 <600ms 的缓存命中。
- 46xx 失败 / 协议错误用既有 `ErrorState`（中文 + 重试）；刷新失败保留旧数据并在顶部显示错误条。

### 15.6 命令面板

- 入口：任意页面 `⌘K` / `Ctrl+K`、顶栏「命令」按钮、URL `?cmd=1`（消费后从 search 移除，不污染分享链接）。
- Radix Dialog 提供焦点陷阱、Esc、`onOpenAutoFocus` 把焦点交给输入框；关闭后焦点归还。
- 自写受控 listbox：`role=combobox` + `aria-activedescendant` + `role=listbox/option`；`↑↓`（循环）、`Home/End`、
  `Enter`、`Esc`；鼠标 `onMouseMove` 同步 active；active 项 `scrollIntoView({block:nearest})`。
- 分组与动作：
  - 导航：驾驶台 / 对话（携带当前 as_of / scenario / mode）；
  - 场景：5 个（来自 `/api/scenarios`）；
  - 模式：协同 / 独立 / 单智能体；
  - 操作：重新生成（跨页 pending）、切换主题、导出 Markdown 简报、复制当前 run_id、打开 `/docs`；
  - AI 快捷问：总结当前预警、为什么监管判定为「{真实等级}」（无决策时回退「极高」）、三条关键证据、当前分歧如何协调。
- 过滤匹配 label / hint / keywords / 分组；无结果态给出可执行建议；底部显示 `⌘K` 提示与「当前命中 / 全部」计数。
- AI 快捷问只**预填**，不自动发送；带当前上下文跳转 `/chat`。

### 15.7 对话流式与消息操作

- 发送：立即追加 user bubble；`ChatRunProgress` 展示阶段 chip（由 `stage` 事件驱动）与最近一条 trace 活动；
  composer 的「停止」与进度面板的「停止生成」都调用同一 `AbortController`。
- 收到 `chat`：追加 assistant bubble，`lastCompletedTurnId` 触发一次打字机：
  - 24–64 步、最慢约 1s、每约 16ms 更新；`aria-busy=true`；reduced-motion 或历史消息直接显示全文；
  - 打字期间自动贴底（仅当用户仍在底部），避免结尾 / 追问 chips 被推出视口；
  - 2.6s 后清空 `lastCompletedTurnId`，重挂载不重播。
- 失败 / 停止：追加错误 / 停止消息；失败消息带「重试这个问题」；`retryLast` 移除最后一条 assistant（与紧邻 user）
  后重发，避免重复气泡。
- 引用 chips 打开来源 Dialog；消息操作提供复制回复、复制引用来源（Markdown 列表）、停止后重试。
- 追问建议：`buildFollowUps(decision)` 确定性生成驱动因子 / 冲突 / 证据 / 三主体差异 / 情景问题，最多 4 条；
  点击只预填输入框，不自动消耗 token；仅在最新一条成功回复后展示。
- 上下文 chip：场景 / `as_of` / 模式；「清除上下文」后请求发送 `as_of: null`（`ChatRequest` 无 scenario 字段），
  显示「已清除 · 仅使用会话历史」，可恢复；清除不影响已有会话消息。

### 15.8 上下文 AI 动作

| 触发点 | 预填 prompt | 跳转 |
|---|---|---|
| 智能体卡「追问该主体」 | `解释{监管主体/投资主体/融资主体}为什么给出「{风险等级}」判断，并列出关键证据。` | `/chat` + 当前上下文 |
| 证据 Dialog「让 AI 解释这条证据」 | `请解释证据「{title}」的含义、来源可靠性与它对当前判断的影响。` | 关闭 Dialog → `/chat` |
| 冲突行「请协调者复核该分歧」 | `请协调者复核分歧「{subject}」：双方主张分别是什么，当前解决状态如何，还需要哪些证据才能收敛？` | `/chat` + 当前上下文 |

- 跳转参数显式写入 `as_of / scenario / mode`（即使首屏 URL 没有查询参数），`tab` 等页面参数会被清掉；
- 通过模块级 `ai-actions` 信箱传递一次 prompt；ChatPage 挂载或已挂载时消费、填入 Composer、`requestAnimationFrame`
  聚焦并把光标放到末尾；
- ChatProvider 在 App 根，导航不丢历史消息；对话页从证据 Dialog 触发时不再跳转，只预填当前 Composer。

### 15.9 动效参数与降级

| 动效 | 参数 | 说明 |
|---|---|---|
| 页面 / 结果淡入 | `animate-rise` = `--dur-base` 250ms + `--ease-out` + opacity/translateY(6px) | 完成后按 run_id 触发 |
| Tab 切换 | `animate-tab-in` = `--dur-fast` 150ms + opacity + translateY(2px) | 右栏固定高度，不做高度动画（见偏离 #22） |
| 按钮按压 | `active:scale-[0.98]` | 既有规范，唯一按压缩放 |
| 卡片 hover | `transition-colors 150ms` + 边框 `foreground/15–20` | 不换阴影、不位移 |
| 顶部进度条 | 1.15s 线性循环，只动 `transform` | 2px；reduced-motion 时静止 |
| KPI count-up | 680ms rAF + ease-out cubic；从上一显示值过渡 | reduced-motion 直接落位 |
| 打字机 | 24–64 步、≈16ms/步、约 1s；光标 `opacity` 1s steps | reduced-motion 直接显示 |
| Toast | 入场 `animate-rise`；默认 3.2s、错误 5s | 最多 3 条；`role=status/alert` |
| 骨架 | 1.8s opacity pulse（沿用 `.skeleton`） | 规范禁止 shimmer 渐变；与真实布局同尺寸 |
| 全局降级 | `prefers-reduced-motion: reduce` 动画/过渡 0.01ms | CSS 全局 + JS 媒体查询双保险 |

所有动效只写 `opacity / transform`（打字机写文本、count-up 写数字，不触发布局）；无弹性、3D、视差。

### 15.10 验收记录（headless Edge + CDP）

> 验收时 8000 的 uvicorn 已重启并确认返回 `event: run` / `event: trace` / `event: stage`；
> 若打开页面仍看到「同步回退」，说明该进程仍是旧版本或代理未放行 SSE，重启后端即可。

在本机 `bun run dev`（5173）+ 真实后端（8000，核心模块就绪）实际渲染：

| 检查项 | 结果 |
|---|---|
| 驾驶台 light / dark | 通过；RunProgress、KPI、证据、协同过程、toast 均正常 |
| 真实 SSE 驾驶台（临时 8011 + 生产构建） | 通过；`SSE 流式` 徽章、R0「监管主体分析中」、最近活动 8 条（展示 6）、完成 toast；无回退 |
| 真实 SSE 对话（临时 8011 + 生产构建） | 通过；真实 `stage` / `trace` → `chat` → 打字机 → 引用 / 消息操作 / 追问建议；无回退 |
| 真实 SSE 取消 | 通过；连接中止、进度消失、保留旧结果、toast「已取消本次生成」；无未捕获异常 |
| 回退同步端点（旧部署 / 无 SSE） | 通过；`同步回退` 徽章 + 本地估算标注；功能与结果一致 |
| `?cmd=1`（dev 与 FastAPI `/ui/` 生产构建） | 通过；首屏打开面板，`cmd=1` 自动移除；生产资源 `/ui/assets/*` 正确 |
| 运行中 RunProgress | 通过；真实请求 2s 时截取，SSE 阶段、三主体分析中、取消可用 |
| 取消（回退路径） | 通过；2px 进度条消失、保留旧数据、toast「已取消本次生成」 |
| 对话流式（回退路径） | 通过；发送 → 同步回退阶段进度 → 真实回复（约 19s）→ 打字机结束 → 引用 / 操作 / 追问建议可见 |
| 上下文 AI 动作 | 通过；智能体卡、证据 Dialog、冲突行三种入口均跳转对话并预填正确 prompt，URL 携带 `as_of/scenario/mode` |
| 协同过程 | 通过；R0 默认展开，工具 / 角色 / 跨度 / tokens / 原始 JSON 正常；总计 97 事件 |
| 命令面板（缓存后） | 通过；监管等级由「未知」更新为真实「极高」，run_id 提示出现 |
| 控制台 | 真实 SSE 路径 0 事件；旧部署回退路径仅有预期 SSE 404（dev 下另有 Vite HMR debug 日志），无未捕获异常 |
| 横向溢出 | 390 / 768 / 1024 / 1180 / 1280 / 1440 全部 `scrollWidth === innerWidth`，`main` 无横向溢出 |
| `bun run build` | 通过（`tsc --noEmit && vite build`）；dist 1,031,670 B / 7 文件 |

截图产物（本地 `artifacts/ui-ai/`，不随仓库交付）：

- `dashboard_light.png` / `dashboard_dark.png`
- `palette_light.png` / `palette_dark.png` / `palette_after_cache_light.png`
- `run_progress_light.png` / `run_progress_390.png` / `cancelled_light.png`
- `sse_run_progress_light.png` / `sse_dashboard_light.png` / `sse_cancelled_light.png`
- `coordination_timeline_light.png`
- `chat_prefill_light.png` / `chat_progress_light.png` / `chat_done_light.png`
- `sse_chat_progress_light.png` / `sse_chat_done_light.png`
- `context_agent_light.png` / `context_evidence_light.png` / `context_conflict_light.png`
- `prod_palette_dark.png` / `prod_dashboard_dark.png`

推荐手工验收路径：

1. `/ui/?theme=light` → 观察 RunProgress → 完成后 toast + KPI count-up；
2. `/ui/?theme=dark&cmd=1` → 命令面板（↑↓ / Enter / Esc）→ 选「重新生成决策卡」；
3. 驾驶台三智能体卡「追问该主体」→ 对话预填并聚焦 → Enter 发送 → 观察阶段进度 → 打字机 → 追问建议；
4. 证据 Dialog「让 AI 解释这条证据」、冲突行「请协调者复核该分歧」；
5. 核验页 → 协同过程 R0–R5，展开 R0、点击事件看原始 JSON；
6. 对话页「清除上下文 / 恢复」、停止生成、失败重试。

### 15.11 与后端联调建议

> 已用当前 `src/cbr/api/streaming.py` 在临时端口 8011 + 生产构建完成实测（decision / chat / 取消，控制台 0 事件）；
> 以下保留为后续回归 / 新部署检查清单。

1. 后端按 spec §1.1/§1.2 实现后，直接用浏览器打开驾驶台：`run / stage / trace / decision` 应依次到达；
   RunProgress 的「同步回退」徽章与本地估算自动消失，改为真实阶段。
2. 校验缓存命中：`refresh=false` 时后端立即发 `decision`（可附 `stage:"cache"`）；前端 <600ms 完成不弹 toast。
3. 校验取消：点击取消后服务端生成器应停止 tail；后台线程允许自然结束。前端只 abort 连接，不发送额外取消请求。
4. 校验 `error` 事件：返回 `{status, message}`，前端展示中文 message 并允许重试；不要返回半截 decision。
5. 若反向代理会缓冲 SSE，请确保响应头 `X-Accel-Buffering: no` 与 `Cache-Control: no-cache`，否则前端会 300s 超时。
6. Dev / 预览通过 Vite 代理 `/api`、`/docs`、`/openapi.json`；生产由 FastAPI 同源提供，无需 CORS 变更。
