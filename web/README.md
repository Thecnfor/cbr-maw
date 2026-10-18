# CBR-MAW Web 前端

CBR-MAW（跨境金融风险多智能体协同预警系统）的 **React 驾驶台 + 智能对话** 前端。
它以 FastAPI 的 `/api/*` 为唯一后端契约，替换 Streamlit 作为主界面；Streamlit 保持原状，作为回退入口。

- 驾驶台：`#/dashboard` —— 场景 / as_of 回放、共享风险信号、驱动因子归因、模态贡献、三智能体风险卡、证据板、分歧与协调、核验与审计 trace、数据卡、可复核简报导出。
- 对话：`#/chat` —— 自然语言提问、引用来源、关联决策卡、下载简报；`session_id` 在本次浏览会话内保持。
- 视觉：Light / Dark 双主题；默认 Light；右上角切换并写入 `localStorage("cbr-theme")`，首屏由内联脚本预置，不闪烁。

设计系统、token 映射、与规范的偏离和验收记录见 **[DESIGN-NOTES.md](./DESIGN-NOTES.md)**。

---

## 1. 技术栈

| 能力 | 选型 | 版本 |
|---|---|---|
| 构建 | Vite + `@vitejs/plugin-react` | Vite 8.3 / plugin-react 6.1 |
| UI | React 19 + TypeScript | React 19.3 / TS 7.0 |
| 样式 | Tailwind CSS v4（`@tailwindcss/vite`，无 `tailwind.config.*`） | 4.3 |
| 组件 | shadcn/ui 约定（源码自持）+ Radix 原语 | Radix Tabs / Dialog / Select / Tooltip / ScrollArea / Separator / Slot |
| 变体 | `class-variance-authority` + `clsx` + `tailwind-merge` | cva 0.7 / tw-merge 3.7 |
| 图标 | `lucide-react`（唯一图标库） | 1.59 |
| 图表 | `recharts`（懒加载，仅信号图表） | 3.10 |
| 字体 | `@fontsource-variable/geist` / `geist-mono`（本地 woff2，仅 latin 子集） | 5.3 |

没有 Next.js，没有第二套图标 / 图表 / 状态管理库。

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
│  │  ├─ api.ts                # fetch 封装 / ApiError / 资源缓存
│  │  ├─ types.ts              # 与 src/cbr/schemas.py 对应
│  │  ├─ decision.ts           # 决策请求 hook + (as_of,mode,scenario) 内存缓存
│  │  ├─ resources.ts          # trace / data-cards 缓存 hook
│  │  ├─ run-context.tsx       # 场景 / as_of / 模式（URL 查询状态）
│  │  ├─ chat-context.tsx      # 对话会话、session_id、停止 / 清空
│  │  ├─ router.ts             # 极简 hash 路由
│  │  ├─ theme.tsx             # 双主题 provider
│  │  ├─ export.ts             # Markdown / JSON / JSONL 简报
│  │  ├─ markdown.tsx          # 安全 Markdown 子集渲染（无 dangerouslySetInnerHTML）
│  │  ├─ format.ts / labels.ts # 数值、日期、单位、中文词表
│  │  └─ utils.ts              # cn()（已扩展自定义字号 token）
│  └─ components/
│     ├─ ui/                   # 原子件（零业务、零 fetch）
│     ├─ common/               # Panel / PageHeader / Callout / Meter / Progress …
│     ├─ layout/               # AppShell / Sidebar / Topbar / RunControls / ThemeToggle
│     ├─ dashboard/            # KPI、信号、归因、智能体卡、证据板、tabs、导出
│     └─ chat/                 # 消息、输入、引用、关联决策卡、来源 Dialog
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
| Vite dev | `127.0.0.1:5173` | `/api` → `:8000`，`strictPort` |
| Vite preview | `127.0.0.1:4173` | 产物预览，路径 `/ui/`，`/api` 同样代理 |
| Streamlit 回退 | `127.0.0.1:8501` | 侧栏底部「Streamlit 回退」链接指向这里 |

代理配置在 `vite.config.ts` 的 `server.proxy` / `preview.proxy`；没有修改后端 CORS。

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

控件变化用 `history.replaceState`（不制造大量历史项），页面切换用 `pushState`；切换页面会回到内容顶部。

---

## 6. 数据请求与缓存

| 端点 | 时机 | 缓存 |
|---|---|---|
| `GET /api/health` | 启动、侧栏「重新检测」 | 模块级 Promise；手动重载 |
| `GET /api/scenarios` | 启动 | 同上 |
| `GET /api/decision?as_of&scenario&mode` | 条件变化 / 顶栏「重新生成」 | 前端 Map，键 `(as_of,mode,scenario)`；并发去重；手动刷新带 `refresh=true` 绕过服务端缓存 |
| `GET /api/trace/{run_id}` | 决策成功后一次 | 按 `run_id` 缓存 |
| `GET /api/data-cards` | 决策成功后一次 | 模块级缓存 |
| `GET /api/evidence/{id}` | 打开黑板快照中不存在的证据时 | 无（按需） |
| `POST /api/chat` | 用户发送 | 无（会话保存在内存） |

- **不轮询**。健康 / 场景 / 决策 / trace / 数据卡都只在需要时请求。
- 真实 LLM 约 12–15 秒。前端显示 **协同分析中（监管 / 投资 / 融资）** 阶段轮播 + 真实已用时；只展示阶段，不伪造中间数据。对话同理（共享信号 → 工具 → 证据核验）。
- 503 会原样展示后端中文 `detail`，并给出「重试 / 查看 /api/health / 等待核心装配」提示；404（如 trace / evidence）有独立说明，不白屏。
- 决策卡、trace、数据卡均有空态与骨架屏；骨架与真实布局同尺寸。

---

## 7. 交互要点

- **键盘**：Enter 发送、Shift+Enter 换行；中文输入法组合期间 Enter 不会误发送（`isComposing`）。
- **主题**：Light / Dark 双主题完整；右上角切换；`localStorage("cbr-theme")`；首屏内联脚本避免闪烁；默认 Light。
- **停止**：对话发送中可点「停止」中止请求；清空对话会中止并生成新的 `session_id`。
- **焦点**：所有可交互元素有可见 focus ring（Radix 组件保留键盘导航）；提供「跳到主要内容」。
- **动效降级**：`prefers-reduced-motion: reduce` 下所有动画 / 过渡近乎瞬时；图表关闭 animation；无装饰性常驻动画。
- **移动端**：< 1024px 侧栏转为左侧抽屉（Radix Dialog）；390px 无横向滚动；控件在页面内完整可达。
- **长回复**：assistant 回复超过约 900 字时折叠为 320px，可「展开全文」；引用与关联决策卡始终可见。

---

## 8. 对话与证据

- 引用 chips（`[1] 来源名`）打开 **来源 Dialog**：名称 / URL / `doc_id` / `chunk_id` / `release_time`；若能在关联决策卡黑板中匹配到完整 Evidence，可继续打开 **证据 Dialog**。
- 证据 Dialog：类型、时点、产出方、来源、文档 / 片段、发布时间、工具名 + 版本、`inputs_hash`、证据哈希、payload（JSON）、citations。
- 证据板支持 kind 过滤 + 搜索；引用但未暴露在黑板中的 `evidence_id` 单独提示，点击会尝试 `GET /api/evidence/{id}`。
- 导出：Markdown 简报、JSON 数据包（decision + evidence + trace）、审计 JSONL；均为浏览器本地 Blob 下载，不写服务端。

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
- 无构建错误；`dist/index.html` 由 FastAPI `/ui/` 正常返回，资源路径 `/ui/assets/*` 正确。
- 生产分块（实测）：
  - `index-*.js` ≈ 494 kB（gzip 156 kB）
  - `signal-panel-*.js` ≈ 363 kB（gzip 105 kB，recharts 懒加载）
  - `chat-page-*.js` ≈ 21 kB（gzip 7 kB，懒加载）
  - `index-*.css` ≈ 46 kB（gzip 9.7 kB）
  - 字体 woff2 ≈ 52 kB
  - `web/dist` 合计 **979 kB（0.93 MiB）**，共 7 个文件（含全部懒加载 chunk 与字体）
- 无 Playwright / E2E 依赖随交付；浏览器冒烟（headless Edge）覆盖 390 / 768 / 1024 / 1180 / 1280 / 1440，控制台无错误、无请求失败、无横向溢出。详见 DESIGN-NOTES §9。

---

## 10. 常见问题

**Q：打开页面一直骨架屏 / 提示无法连接后端？**
确认 FastAPI 在 `127.0.0.1:8000`；开发模式使用 5173，代理在 Vite 侧。生产 `/ui/` 与 API 同源。

**Q：业务端点 503？**
核心模块未装配完成，或真实 LLM 凭据 / 网络失败。打开 `/api/health` 查看 `pending_modules` 与 `llm`；侧栏「重新检测」会重新探测。界面会原样展示后端中文说明。

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
- 不在前端保存任何模型 key / token；不向 localStorage 写业务数据（只写主题与 `session_id` 到 sessionStorage）。
- 决策卡与证据是只读展示；导出在浏览器完成，不新增写入端点。
- 视觉与 token 的增减只改 `src/styles/tokens.css`，组件内不造平行变量。
- 设计规范、验收记录与偏离说明见 [DESIGN-NOTES.md](./DESIGN-NOTES.md)。
