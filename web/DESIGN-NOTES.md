# CBR-MAW Web · DESIGN-NOTES

> 本文是 `web/` 的视觉与交互裁决记录：token 映射、组件清单、页面结构、状态管理、
> 无障碍与双主题验收，以及**与参考规范的每一处偏离及原因**。
> 唯一 token 真源：`src/styles/tokens.css`；组件内不得出现硬编码颜色 / 阴影 / 圆角。

- 版本：v0.1（2026-10-18）
- 技术基线：React 19.3 · Vite 8.3 · TypeScript 7.0 · Tailwind CSS v4.3 · Radix 原语 · Recharts 3.10 · lucide-react 1.59
- 参考：`D:/XRAK/product/cross-dashboard/DESIGN.md`、`app/globals.css`、`D:/XRAK/product/Xra-space/packages/ui/src/styles/tokens.css`、`D:/recently/person/rak-blog/DESIGN.md`、shadcn-conventions / design-reviewer

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
| common | `analysis-progress` | 协同分析阶段轮播（真实已用时，不伪造数据） |
| common | `icon-button` | 图标按钮 + Tooltip + aria-label |
| layout | `app-shell` / `sidebar` / `topbar` / `run-controls` / `theme-toggle` | 248px 侧栏、52px 顶栏、场景 / 时点 / 模式、主题切换 |
| dashboard | `kpi-row` / `sparkline` | 2fr+1fr+1fr KPI、期限结构迷你趋势 |
| dashboard | `signal-panel` | Recharts 概率柱 + 60% 阈值线 + 期限统计（懒加载） |
| dashboard | `attribution` | 驱动因子横向条 + 模态贡献堆叠条 |
| dashboard | `agent-cards` | 三智能体卡：等级、关键指标、建议、claim / evidence 展开 |
| dashboard | `evidence-board` / `evidence-dialog` | kind 过滤 + 搜索 + 列表；来源 / 时点 / 工具版本 / inputs_hash / payload / citations |
| dashboard | `conflicts-panel` | 事实 / 方向 / 偏好徽章 + 解决结果 + 未解决升级提示 |
| dashboard | `verification-panel` / `trace-panel` | 6 指标 + 核验问题 + terminal 风格 trace |
| dashboard | `data-cards-panel` / `export-panel` | 数据口径表 + Markdown / JSON / JSONL 下载与预览 |
| dashboard | `right-panel` / `dashboard-skeleton` / `dashboard-page` | 5 个 Radix Tabs、同尺寸骨架、页面装配 |
| chat | `chat-page` / `chat-message` / `chat-composer` / `chat-empty` | 线程、输入、示例、发送 / 停止 / 清空 |
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
AppShell（248 侧栏 + 52 顶栏 + 可滚动 main）
└─ page-container（max 1200）
   ├─ PageHeader：H1 26 / 描述 13.5 / 场景·模式·生成于 / 右：风险徽章·run_id·获取时间
   ├─ 运行控件（< xl 显示；≥ xl 收进顶栏，避免重复）
   ├─ [刷新中] 紧凑进度条 / [刷新失败] 保留旧数据的错误条
   ├─ KPI：2fr（5 日概率 + 期限结构）+ 1fr（风险等级）+ 1fr（历史分位）+ 跨 2 列（协同成本）
   ├─ 主网格 3:2（≥1180）
   │  ├─ 左：风险信号图 → 驱动因子 + 模态贡献 → 三智能体风险卡
   │  └─ 右：sticky「协同证据与审计」Tabs
   │      证据（20） / 分歧（3） / 核验（含 trace） / 数据卡（27） / 导出
   └─ 页脚：L6 说明 · run_id · 不构成投资建议
```

- 证据 Dialog、来源 Dialog 由页面级单一实例承载，避免每个列表行各挂一个 Dialog。
- 右栏 sticky 高度 `calc(100dvh - 84px)`（52 顶栏 + 上下 16），内部滚动；左栏滚动时证据 / 核验始终可见。
- 加载：同尺寸骨架 + 阶段进度；错误：中文说明 + 重试 + 503 提示；空态：每个区块独立说明。

### 5.2 对话

```
ChatPage（整页 flex，线程内部滚动）
├─ PageHeader：H1 / 描述
├─ 运行控件（< xl）
├─ 会话条：session_id / as_of / 模式 / 消息数 / 清空
├─ 空态卡：3 个示例问题（点击即发送）
├─ 线程：user 右（surface-2 气泡）；assistant 左（surface-1 气泡 + 头像）
│  ├─ 长回复 > 900 字折叠 320px，可展开全文
│  ├─ 引用 chips [n] → 来源 Dialog →（可匹配黑板证据）证据 Dialog
│  └─ 关联决策卡摘要：风险等级 / 三主体等级 / final_advice / 驾驶台跳转 / 下载简报
├─ 发送中：阶段轮播 + 真实已用时 + 停止
└─ Composer：Enter 发送 / Shift+Enter 换行 / IME 保护 / 清空后新 session
```

---

## 6. 状态管理与数据流

| 状态 | 位置 | 理由 |
|---|---|---|
| 场景 / as_of / 模式 / tab | URL hash 查询参数 | 可分享、刷新保留、前进后退；驾驶台与对话共享同一事实 |
| health / scenarios | `RunProvider`（Context + 模块级 Promise 去重） | 一次注入、全树消费；手动重载 |
| 决策卡 | `lib/decision.ts` 模块级 Map，键 `(as_of,mode,scenario)` | 同组合立即出结果、并发去重；手动刷新 `refresh=true` |
| trace / data-cards | `lib/resources.ts` 模块级缓存 | 只请求一次，不轮询 |
| 对话消息 / session | `ChatProvider`（App 根） | 切换页面不丢；sessionStorage 只存 session_id |
| 主题 | `ThemeProvider` + `localStorage` | 双主题；首屏内联脚本防闪烁 |
| 局部 UI（过滤 / 搜索 / 展开 / 选中 trace） | `useState` | 瞬态，留在组件内 |

**为什么不用 SWR / nuqs / zustand**：参考规范面向 Next.js 16 + RSC；本仓是 Vite SPA，只有两个页面、一个决策端点和一个对话端点。引入第二套请求 / URL / 全局状态库会增加体积与心智负担。这里用 `Context + 模块缓存 + hash 查询` 达到同等效果，并在 README / 本文记录。**没有把服务端响应复制进第二数据源**：决策卡只存在一个模块缓存里。

**刷新语义**：
- 顶栏「重新生成」通过 `refresh-bus` 通知当前驾驶台调用 `decision.refresh()`，请求带 `refresh=true` 绕过服务端 30 分钟缓存；请求进行中按钮仍可点但会被去重。
- 切换场景 / 时点 / 模式按新 key 请求；命中前端缓存则立即渲染，并标注「本地缓存 · HH:mm:ss」。
- 不做轮询；健康与场景只在启动和「重新检测」时请求。

---

## 7. 加载 / 错误 / 空态

| 状态 | 表现 |
|---|---|
| 首次加载 | 与真实布局同尺寸的骨架（KPI / 主网格 / 右栏），上方「协同分析中（监管 / 投资 / 融资）」阶段条；预计真实 LLM 12s，mock 2s |
| 手动刷新 | 保留旧决策卡，顶部紧凑进度条；不闪屏 |
| 503 | 原样展示后端中文 `detail`；提示查看 `/api/health`、等待模块装配；重试同时重载 health / scenarios |
| 404（trace / evidence） | 独立说明（黑板未暴露 / artifacts 无文件），不视为界面错误 |
| 空数据 | 每个区块独立空态：无证据、无冲突、无驱动、无 trace、无数据卡、无三主体结果 |
| 长文本 | 证据 payload 可滚动；简报预览 360–420px 滚动；对话长回复折叠 |

骨架屏不用 spinner 代替布局；`aria-busy` 标记；进度条 `role=status` + `aria-live=polite`。

---

## 8. 无障碍

- **对比度**：正文 / muted 在 light/dark 均 ≥ 4.5:1；小徽章使用 `*-ink`；危险实心徽章使用主题对应的 `destructive-foreground`。
- **焦点**：所有可交互元素 `focus-visible:ring-2 ring-ring`；`--ring` 从 28% 提升到 45%，保证 ≥ 3:1 焦点指示；Radix 组件保留键盘导航，未破坏 Esc / 方向键。
- **键盘**：Tab 顺序自然；Tabs 用 Radix roving tabindex；模式 segmented 为 `aria-pressed` 按钮组；证据 / trace 行是原生 button。
- **读屏**：装饰图标 `aria-hidden`；图标按钮有 `aria-label`；Dialog 有 Title + Description；表格有 `caption`；空态 / 错误为文本。
- **输入法**：Enter 发送前检查 `nativeEvent.isComposing`，中文组合输入不会误发。
- **动效**：`prefers-reduced-motion: reduce` 下动画 / 过渡 0.01ms；Recharts 关闭动画；无装饰性常驻循环。
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

---

## 11. 性能预算与实际

| 项 | 预算 | 实际（生产构建） |
|---|---|---|
| 首屏 JS（gzip） | ≤ 180KB | ≈ 156KB（React + Radix + 应用） |
| 首屏 CSS（gzip） | ≤ 15KB | ≈ 9.7KB |
| 字体（woff2） | ≤ 60KB | ≈ 52KB（Geist + Geist Mono latin） |
| 图表 chunk（gzip） | 懒加载 | ≈ 105KB，仅决策卡出现后加载 |
| 对话 chunk（gzip） | 懒加载 | ≈ 7KB |
| dist 总体积 | — | 979KB（0.93 MiB，7 个文件） |
| 决策 JSON | 60–100KB | 实测 52KB（真实 LLM 运行） |
| 轮询 | 0 | 0 |
| 列表规模 | 20 证据 / 94 trace / 27 数据卡 | 无虚拟化；trace 仅打开核验页时才挂载 |

- 决策请求 14.5s（真实 DeepSeek，实测），期间显示阶段进度；mock 模式约 2s。
- 缓存命中时不再请求；trace / data-cards 按 run_id / 进程缓存。
- 图表懒加载 + 关闭动画，避免首屏主线程被 Recharts 占用。

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
| `TraceEvent`（`ts / step / role / action / tool / args_hash / result_hash / detail / latency_ms / tokens`） | terminal trace；点击展开详情 |
| `DataCard`（`series_id / name / source / frequency / coverage / release_lag_days / pit_grade / unit / notes`） | 数据卡表格 + 备注 |
| `ChatResponse`（`reply / citations / decision / trace_id / as_of`） | 对话线程 + 引用 chips + 关联决策卡 |
| `Scenario`（`scenario_id / name / as_of / description / tags`） | 侧栏场景列表 + 顶栏选择器 |

所有数组 / 对象在使用前做空值降级（`?? []` / `?? {}`），字段缺失显示「—」，不抛异常。

---

## 13. 风险与已知限制

| 风险 | 影响 | 缓解 |
|---|---|---|
| 真实 LLM 12–15s，且不可取消（决策请求） | 首屏等待 | 阶段进度 + 骨架；同 key 缓存；手动刷新保留旧数据；不做轮询 |
| 上游回复极长（1800+ 字） | 对话文字墙 | 320px 折叠 + 展开全文；关联决策卡独立摘要 |
| trace / evidence 可能 404 | 核验页 / 证据弹窗空 | 独立中文说明 + 重试 / 回退 GET；不误报为界面错误 |
| 证据引用未暴露在黑板 | 证据列表缺项 | 单独提示缺失 id，点击尝试 `/api/evidence/{id}` |
| 移动端部分图标按钮 32px | 触控偏小 | 主控件 40px；列表 / 示例 ≥44px；后续可加 44px 模式 |
| 原生 date 显示随 locale | 视觉不一致 | 值始终 ISO；文档说明 |
| 后端契约演进 | 字段缺失 / 新增 | 类型可选 + 空值降级；新增字段只需扩展 `types.ts` 与展示 |
| 生产必须挂在 `/ui/` | 改路径会 404 | `vite.config.ts` base 与 FastAPI 挂载一致；README 明示 |
| 缺少自动化 E2E | 回归靠人工 | 本次 headless Edge 冒烟；建议后续加独立 Playwright 工程 |

---

## 14. 后续（不阻塞当前交付）

1. 后端若提供 SSE / 流式阶段事件，用真实事件替换前端阶段轮播（当前无该端点，故不伪造）。
2. 增加独立 E2E（Playwright）覆盖场景切换、证据 Dialog、导出下载。
3. 44px 触控模式与更细的移动端密度切换。
4. 证据 / trace 深链（`#/dashboard?...&evidence=...`）与复制链接。
5. 报告打印样式（A4）与 CSV 导出。
6. 如需复杂编排动画，按规范首选 GSAP，并只在 `lib/ui/gsap.ts` 注册一次。
