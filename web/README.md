# CBR-MAW Web 前端

CBR-MAW（跨境金融风险多智能体协同预警系统）的 **React AI-native 协同驾驶台 + 智能对话** 前端。
它以 FastAPI 的 `/api/*` 为唯一后端契约，替换 Streamlit 作为主界面；Streamlit 保持原状，作为回退入口。

- 驾驶台：`#/dashboard` —— 场景 / as_of 回放、**流式运行进度（R0–R5 + 活动流 + 取消）**、共享风险信号、驱动因子归因、模态贡献、三智能体风险卡（**追问该主体**）、证据板（**让 AI 解释这条证据**）、分歧与协调（**请协调者复核**）、核验与**协同过程 R0–R5 时间线**、数据卡、可复核简报导出。
- 对话：`#/chat` —— **流式协同分析进度**、自然语言提问、**打字机/淡入回复**、引用来源、关联决策卡、**追问建议 chips**、上下文 chip 与清除、停止 / 重试；`session_id` 在本次浏览会话内保持。
- 键盘：**⌘K / Ctrl+K 命令面板**（导航 / 场景 / 模式 / 操作 / AI 快捷问）。
- 视觉：Light / Dark 双主题；默认 Light；右上角切换并写入 `localStorage("cbr-theme")`，首屏由内联脚本预置，不闪烁。
- 流式契约：`GET /api/decision/stream`、`POST /api/chat/stream`；后端 `src/cbr/api/streaming.py` 已实现，前端已用临时端口端到端实测（RunProgress / ChatRunProgress / 取消均走真实 SSE）；**旧部署、代理缓冲或端点缺失时自动回退同步 `/api/decision`、`/api/chat`**，并在界面上明确标注「同步回退」。

设计系统、token 映射、与规范的偏离和验收记录见 **[DESIGN-NOTES.md](./DESIGN-NOTES.md)**；AI-native 交互的 SSE 处理 / 回退 / 动效见 **DESIGN-NOTES §15**。

---

## 1. 技术栈

| 能力 | 选型 | 版本 |
|---|---|---|
| 构建 | Vite + `@vitejs/plugin-react` | Vite 8.3 / plugin-react 6.1 |
| UI | React 19 + TypeScript | React 19.3 / TS 7.0 |
| 样式 | Tailwind CSS v4（`@tailwindcss/vite`，无 `tailwind.config.*`） | 4.3 |
| 组件 | shadcn/ui 约定（源码自持）+ Radix 原语 | Radix Tabs / Dialog / Select / Tooltip / ScrollArea / Separator / Slot |
| 流式 | 原生 `fetch` + `ReadableStream`（GET/POST SSE） | 浏览器内置 |
| AI 交互 | Radix Dialog + 自写 listbox / toast / 打字机 / count-up | 无新依赖 |
| 变体 | `class-variance-authority` + `clsx` + `tailwind-merge` | cva 0.7 / tw-merge 3.7 |
| 图标 | `lucide-react`（唯一图标库） | 1.59 |
| 图表 | `recharts`（懒加载，仅信号图表） | 3.10 |
| 字体 | `@fontsource-variable/geist` / `geist-mono`（本地 woff2，仅 latin 子集） | 5.3 |

没有 Next.js，没有第二套图标 / 图表 / 状态管理库；AI-native 升级**未引入任何新依赖**（命令面板、toast、SSE 解析均为源码自持）。
流式请求使用浏览器原生 `fetch + ReadableStream`（不依赖 EventSource，因为 chat 需要 POST + JSON body）。

---

## 2. 目录

```
web/
├─ index.html                  # 主题预置脚本、内联 SVG favicon
├─ vite.config.ts              # base=/ui/（build）、/api 代理、端口
├─ tsconfig.json               # strict、paths @/*、noEmit
├─ components.json             # shadcn 约定（radix-nova / neutral / lucide）
├─ src/
│  ├─ main.tsx                 # Theme → Run → Chat → Tooltip → App
│  ├─ App.tsx                  # hash 路由 + 页面懒加载
│  ├─ styles/
│  │  ├─ index.css             # Tailwind 入口 + Geist @font-face
│  │  └─ tokens.css            # 唯一 token 真源（light/dark 全量 + @theme inline）
│  ├─ lib/
│  │  ├─ api.ts                # fetch 封装 / ApiError / 资源缓存 / trace prime
│  │  ├─ stream.ts            # SSE 解析（GET/POST、AbortController、超时、错误）
│  │  ├─ types.ts              # 与 src/cbr/schemas.py + SSE 契约对应
│  │  ├─ decision.ts           # 决策 hook：stream → 同步回退、运行态、取消、缓存
│  │  ├─ resources.ts          # trace / data-cards 缓存 hook
│  │  ├─ run-context.tsx       # 场景 / as_of / 模式（URL 查询状态）
│  │  ├─ chat-context.tsx      # 对话会话、chat/stream、阶段、停止 / 重试 / 上下文
│  │  ├─ router.ts             # 极简 hash 路由
│  │  ├─ theme.tsx             # 双主题 provider
│  │  ├─ toast.tsx             # Portal toast + aria-live（无新依赖）
│  │  ├─ motion.ts             # reduced-motion / 已用时
│  │  ├─ coordination.ts       # R0–R5 映射、trace 分组、活动流描述
│  │  ├─ suggestions.ts        # 由 decision 确定性生成追问建议
│  │  ├─ ai-actions.ts         # 上下文 AI 动作 → 对话预填信箱
│  │  ├─ clipboard.ts          # 复制 + execCommand 回退
│  │  ├─ export.ts             # Markdown / JSON / JSONL 简报
│  │  ├─ markdown.tsx          # 安全 Markdown 子集渲染（无 dangerouslySetInnerHTML）
│  │  ├─ format.ts / labels.ts # 数值、日期、单位、中文词表
│  │  └─ utils.ts              # cn()（已扩展自定义字号 token）
│  └─ components/
│     ├─ ui/                   # 原子件（零业务、零 fetch）
│     ├─ common/               # Panel / PageHeader / Callout / Meter / TopProgress …
│     ├─ command/              # ⌘K 命令面板（Radix Dialog + 自写列表）
│     ├─ layout/               # AppShell / Sidebar / Topbar / RunControls / ThemeToggle
│     ├─ dashboard/            # KPI、信号、归因、智能体卡、证据、tabs、RunProgress、协同过程
│     └─ chat/                 # 消息、输入、引用、关联决策卡、ChatRunProgress
├─ dist/                       # bun run build 产物（由 FastAPI 挂载到 /ui/）
└─ README.md / DESIGN-NOTES.md
```

---

## 3. 快速开始

### 3.1 安装

```bash
cd web
bun install
```

要求：Bun ≥ 1.2（验证于 1.3.13），Node ≥ 20.19 或 22.12+（验证于 Node 25，Vite 通过 Bun 运行）。

### 3.2 启动后端（仓库根目录，原样，不改后端）

```bat
set PYTHONPATH=src
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>（核心未就绪时仍返回 200，业务端点返 503 中文）。

### 3.3 开发模式

```bash
cd web
bun run dev
```

打开 <http://127.0.0.1:5173/>。Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，浏览器同源，无 CORS 问题。

### 3.4 生产构建

```bash
cd web
bun run build        # tsc --noEmit && vite build → web/dist
bun run preview      # 本地预览：http://127.0.0.1:4173/ui/（/api 同样代理）
```

> 流式端点未实现时无需改前端：客户端先请求 `/api/decision/stream`、`/api/chat/stream`，
> 404 / 非 `text/event-stream` / 网络不可达时自动回退同步端点，并在运行面板标注「同步回退」。

构建的 `base` 固定为 `/ui/`，与 `src/cbr/api/main.py` 的静态挂载一致：

- `GET /` → 307 跳转 `/ui/`
- `GET /ui/` → `web/dist/index.html`
- 资源：`/ui/assets/*`

只要 `web/dist/index.html` 存在，重启 FastAPI 后即可通过 <http://127.0.0.1:8000/ui/> 访问 React 驾驶台。

### 3.5 类型检查

```bash
bunx tsc --noEmit
```

> 本仓使用 TypeScript 7（原生编译器）。TS 7 已移除 `baseUrl`，因此 `tsconfig.json` 只用 `paths`（相对 tsconfig 解析）。若降级到 TS 5.x，需要恢复 `"baseUrl": "."`。

---

## 4. 端口与代理

| 进程 | 地址 | 说明 |
|---|---|---|
| FastAPI | `127.0.0.1:8000` | `/api/*`；有 dist 时 `/ui/` 托管前端 |
| Vite dev | `127.0.0.1:5173` | `/api`、`/docs`、`/openapi.json` → `:8000`，`strictPort` |
| Vite preview | `127.0.0.1:4173` | 产物预览，路径 `/ui/`，同一组代理 |
| Streamlit 回退 | `127.0.0.1:8501` | 侧栏底部「Streamlit 回退」链接指向这里 |

代理配置在 `vite.config.ts` 的 `server.proxy` / `preview.proxy`；没有修改后端 CORS。`/docs` 与 `/openapi.json` 仅用于命令面板「打开 API 文档」的开发 / 预览可达性。

---

## 5. 路由与 URL 状态

hash 路由，静态托管不需要 history fallback，链接可分享、刷新保留：

```
#/dashboard?as_of=2024-08-05&scenario=yen_carry_2024&mode=collaborative&tab=evidence
#/chat?as_of=2024-08-05&scenario=yen_carry_2024&mode=collaborative
```

| 参数 | 取值 | 缺省 |
|---|---|---|
| `as_of` | `YYYY-MM-DD` | 场景日期；无场景时当天 |
| `scenario` | `/api/scenarios` 的 `scenario_id` | 最近一个情景（列表末项） |
| `mode` | `collaborative` / `independent` / `single` | `collaborative` |
| `tab` | `evidence` / `conflicts` / `verification` / `data` / `export` | `evidence` |

页面级查询参数（`window.location.search`，位于 hash 之前，便于截图/分享）：

| 参数 | 取值 | 说明 |
|---|---|---|
| `theme` | `light` / `dark` | 强制主题，不写回 `localStorage`（验收/截图） |
| `cmd` | `1` | 首屏自动打开命令面板；消费后从 URL 移除，避免刷新重复弹出 |

示例：

```text
/ui/?theme=dark&cmd=1#/dashboard?as_of=2024-08-05&scenario=yen_carry_2024&mode=collaborative&tab=verification
```

控件变化用 `history.replaceState`（不制造大量历史项），页面切换用 `pushState`；切换页面会回到内容顶部。

---

## 6. 数据请求与缓存

| 端点 | 时机 | 缓存 |
|---|---|---|
| `GET /api/health` | 启动、侧栏「重新检测」 | 模块级 Promise；手动重载 |
| `GET /api/scenarios` | 启动 | 同上 |
| `GET /api/decision/stream` | 首次加载 / 重新生成（优先） | 前端 Map，键 `(as_of,mode,scenario)`；并发去重；手动刷新带 `refresh=true` 绕过服务端缓存 |
| `GET /api/decision` | SSE 不可用时的自动回退 | 与上同一份前端缓存 / 服务端 30 分钟缓存 |
| `GET /api/trace/{run_id}` | 决策完成且未由 SSE 提供 trace 时一次 | 按 `run_id` 缓存；流式 trace 会直接 prime，避免二次请求 |
| `GET /api/data-cards` | 决策成功后一次 | 模块级缓存 |
| `GET /api/evidence/{id}` | 打开黑板快照中不存在的证据时 | 无（按需） |
| `POST /api/chat/stream` | 用户发送（优先） | 无；阶段 / trace 只进内存运行态 |
| `POST /api/chat` | SSE 不可用时的自动回退 | 无（会话保存在内存） |

**SSE 契约**（详见 `docs/design/ai-native-interaction-spec.md` §1）：

- `GET /api/decision/stream?as_of&scenario&mode&refresh`：事件 `run → stage* → trace* → decision`，失败 `error`；`: ping` 心跳。
- `POST /api/chat/stream`（body 同 `ChatRequest`）：事件 `run → stage* → trace* → chat`，失败 `error`。
- 客户端解析：`fetch` + `ReadableStream` + `TextDecoder`；支持 GET / POST、`AbortController`、300s 超时、CRLF、跨 chunk 行、多行 `data:`、心跳注释、EOF 无最终事件 → 协议错误。
- 回退分层：`StreamUnavailableError`（404 / 非 event-stream / 网络不可达）→ 同步端点；`StreamProtocolError`（连上但无最终事件 / 超时）→ 中文错误 + 重试；`error` 事件 → 后端中文说明。
- 运行中顶栏下方显示 **2px 不确定进度条**；RunProgress / ChatRunProgress 显示 R0–R5、三主体 chip、最近 4–6 条 trace 活动、真实已用时与取消。
- 回退没有 `stage/trace` 事件可用时，会在面板中明确标注「同步回退 · 阶段为本地估算」，不把计时伪装成后端事件。
- **不轮询**。健康 / 场景 / 决策 / trace / 数据卡都只在需要时请求；SSE 仅维持单条连接。
- 真实 LLM 约 12–18 秒；命中服务端 30 分钟缓存时通常 < 50ms（不弹「0s 完成」toast）。
- 503 会原样展示后端中文 `detail`，并给出「重试 / 查看 /api/health / 等待核心装配」提示；404（如 trace / evidence）有独立说明，不白屏。
- 决策卡、trace、数据卡均有空态与骨架屏；骨架与真实布局同尺寸。

---

## 7. 交互要点

- **命令面板**：`⌘K` / `Ctrl+K` 或顶栏「命令」按钮打开。分组：导航 / 场景 / 模式 / 操作 / AI 快捷问；`↑↓` 选择、`Enter` 执行、`Esc` 关闭、焦点自动落在搜索框；支持 URL `?cmd=1` 自动打开（截图验收）。
- **流式运行**：首次加载 / 重新生成走 `/api/decision/stream`；RunProgress 显示 R0–R5 时间线、监管 / 投资 / 融资状态 chip、最近 4–6 条活动、已用时与「取消运行」；完成后结果淡入并 toast。
- **上下文 AI 动作**：智能体卡「追问该主体」、证据 Dialog「让 AI 解释这条证据」、冲突行「请协调者复核该分歧」会跳转对话、预填 prompt、自动聚焦输入框，并携带当前 `as_of / scenario / mode`；会话消息保留。
- **对话流式**：发送后显示 stage 进度与「协同分析中」，收到 `chat` 后助手消息打字机/淡入（reduced-motion 直接显示）；可停止、失败重试；回复底部有复制 / 引用 / 重试与「追问建议」chips。
- **上下文 chip**：对话页显示场景 / `as_of` / 模式；「清除上下文」后请求发送 `as_of: null`，仅使用会话历史，可恢复。
- **键盘**：Enter 发送、Shift+Enter 换行；中文输入法组合期间 Enter 不会误发送（`isComposing`）。
- **主题**：Light / Dark 双主题完整；右上角切换；`localStorage("cbr-theme")`；首屏内联脚本避免闪烁；默认 Light；`?theme=` 可强制且不写回偏好。
- **停止 / 取消**：对话「停止生成」与驾驶台「取消运行」都通过 `AbortController` 中止请求；取消后保留上一次结果，并显示 toast。
- **动效**：只动 `opacity / transform`；Tab 淡入、卡片 hover、按钮 `active:scale-[0.98]`、KPI count-up（680ms）、toast 3.2–5s；`prefers-reduced-motion: reduce` 下全部近乎瞬时（含打字机与 count-up）。
- **焦点**：所有可交互元素有可见 focus ring（Radix 组件保留键盘导航）；提供「跳到主要内容」。
- **移动端**：< 1024px 侧栏转为左侧抽屉（Radix Dialog）；390px 无横向滚动；控件在页面内完整可达。
- **长回复**：assistant 回复超过约 900 字时折叠为 320px，可「展开全文」；引用、追问建议与关联决策卡始终可见。

---

## 8. 对话与证据

- 引用 chips（`[1] 来源名`）打开 **来源 Dialog**：名称 / URL / `doc_id` / `chunk_id` / `release_time`；若能在关联决策卡黑板中匹配到完整 Evidence，可继续打开 **证据 Dialog**。
- 证据 Dialog：类型、时点、产出方、来源、文档 / 片段、发布时间、工具名 + 版本、`inputs_hash`、证据哈希、payload（JSON）、citations；底部「让 AI 解释这条证据」会带着证据标题跳转对话并预填 prompt。
- 证据板支持 kind 过滤 + 搜索；引用但未暴露在黑板中的 `evidence_id` 单独提示，点击会尝试 `GET /api/evidence/{id}`。
- 追问建议由当前决策卡**确定性生成**（驱动因子 / 未解决或已协调冲突 / 证据清单 / 三主体等级差异 / 情景），点击只预填输入框，不自动发送、不编造数据。
- 导出：Markdown 简报、JSON 数据包（decision + evidence + trace）、审计 JSONL；均为浏览器本地 Blob 下载，不写服务端。命令面板也可直接导出 Markdown 简报或复制当前 `run_id`。

---

## 9. 验证结果

在提交前执行并通过：

```bash
cd web
bun install
bunx tsc --noEmit
bun run build
```

- 无 TypeScript 错误（strict、noUnusedLocals、noUnusedParameters）。
- 无构建错误；`dist/index.html` 由 FastAPI `/ui/` 正常返回，资源路径 `/ui/assets/*` 正确；`?cmd=1` 在生产构建中可自动打开命令面板并从 URL 移除参数。
- 生产分块（实测，2026-10-18）：
  - `index-*.js` ≈ 534.5 kB（gzip 168.65 kB，首屏预算 ≤180 kB 内）
  - `signal-panel-*.js` ≈ 363 kB（gzip 105.39 kB，recharts 懒加载）
  - `chat-page-*.js` ≈ 31.1 kB（gzip 10.08 kB，懒加载）
  - `index-*.css` ≈ 48.4 kB（gzip 10.03 kB）
  - 字体 woff2 ≈ 52 kB
  - `web/dist` 合计 **1,031,670 B（0.98 MiB）**，共 7 个文件（含全部懒加载 chunk 与字体）
- 无 Playwright / E2E 依赖随交付；浏览器冒烟（Edge headless + CDP）覆盖 390 / 768 / 1024 / 1180 / 1280 / 1440，控制台无未捕获异常、无横向溢出。详见 DESIGN-NOTES §15.10。
- **真实 SSE 端到端**：用当前 `src/cbr/api/streaming.py` 在临时端口 8011 启动 uvicorn（不占用 8000），加载生产构建实测：
  - 驾驶台「重新生成」→ `SSE 流式` + 真实 R0 阶段 / trace 活动 → 完成 toast；
  - 对话发送 → 真实 `stage` / `trace` → `chat` → 打字机 + 引用 + 追问建议；
  - 运行中取消 → 连接中止、保留旧结果、无未捕获异常；
  - 控制台事件 0（无 404、无 exception）。截图：`sse_run_progress_light.png`、`sse_chat_progress_light.png`、`sse_chat_done_light.png`、`sse_cancelled_light.png`。
  - 验证截图产物（本地）：`artifacts/ui-ai/dashboard_light.png`、`dashboard_dark.png`、`palette_light.png`、`palette_dark.png`、`run_progress_light.png`、`coordination_timeline_light.png`、`chat_prefill_light.png`、`chat_progress_light.png`、`chat_done_light.png`。
  - 推荐验收 URL：`/ui/?theme=light`、`/ui/?theme=dark&cmd=1`、`/ui/?theme=light#/chat`。

---

## 10. 常见问题

**Q：打开页面一直骨架屏 / 提示无法连接后端？**
确认 FastAPI 在 `127.0.0.1:8000`；开发模式使用 5173，代理在 Vite 侧。生产 `/ui/` 与 API 同源。

**Q：业务端点 503？**
核心模块未装配完成，或真实 LLM 凭据 / 网络失败。打开 `/api/health` 查看 `pending_modules` 与 `llm`；侧栏「重新检测」会重新探测。界面会原样展示后端中文说明。

**Q：控制台出现 `/api/decision/stream` 或 `/api/chat/stream` 404？**
说明当前部署的后端仍是旧版本（未包含 `streaming.py`）或反向代理未放行 SSE。前端会**自动回退同步端点**并在运行面板标注「同步回退」，功能不受影响；浏览器仍会记录一次网络 404。升级后端后刷新即可，前端无需改动。

**Q：命令面板怎么截图 / 直接演示？**
打开 `/ui/?theme=light&cmd=1`（或 dark），首屏会自动打开面板并从 URL 移除 `cmd=1`；也可任意页面按 `⌘K` / `Ctrl+K` 或点顶栏「命令」。`?theme=` 只影响当前加载，不写回主题偏好。

**Q：日期输入显示 `08/05/2024`？**
原生 `<input type="date">` 按浏览器区域设置显示，值始终是 ISO `2024-08-05`；请求参数使用 ISO。选择中文区域浏览器会显示 `2024/08/05`。

**Q：端口被占用？**
Vite 配置 `strictPort`，5173/4173 被占用会直接失败而不是换端口；先释放端口，或临时用 `bunx vite --port 5174`。

**Q：改了后端地址？**
修改 `vite.config.ts` 中 `server.proxy` / `preview.proxy` 的 `target`，不要在前端硬编码 host。

**Q：Streamlit 还能用吗？**
可以，未修改 `app/`。仓库根目录：

```bat
.venv\Scripts\python.exe -m streamlit run app/dashboard.py --server.port 8501
```

侧栏底部「Streamlit 回退」链接指向 8501。

---

## 11. 边界与约定

- 本目录是唯一交付范围；未修改 `src/`、`app/`、`configs/`、`docs/`。
- AI-native 升级只使用现有依赖；SSE / 命令面板 / toast / 打字机 / count-up 均为源码自持，未引入 cmdk、framer-motion、GSAP 或第二套图标 / 图表库。
- 不在前端保存任何模型 key / token；不向 localStorage 写业务数据（只写主题与 `session_id` 到 sessionStorage）。
- 决策卡与证据是只读展示；导出在浏览器完成，不新增写入端点。
- 视觉与 token 的增减只改 `src/styles/tokens.css`，组件内不造平行变量。
- 设计规范、验收记录、SSE / 回退 / 动效说明与偏离见 [DESIGN-NOTES.md](./DESIGN-NOTES.md)（§15）。
