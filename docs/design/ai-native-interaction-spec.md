# CBR-MAW AI-native 交互升级 · 实现契约（v1）

> 目标：把现有 React 驾驶台从"结果展示页"升级为**AI-native 协同工作台**——用户能实时看到多智能体在做什么、可以随时追问、能用键盘驱动、界面有克制的动效反馈。
> 范围：`src/cbr/api/`（流式接口）+ `web/`（前端交互）。不改数据/智能体/编排逻辑，不改 Streamlit 回退。
> 设计规范仍以 [web/DESIGN-NOTES.md](../../web/DESIGN-NOTES.md) 与 `Thecnfor/design-stack` 为准。

---

## 1. 后端 SSE 契约（流式接口）

新增两个 Server-Sent Events 端点；**保留现有同步端点** `/api/decision`、`/api/chat` 不变。

### 1.1 `GET /api/decision/stream`

查询参数与 `/api/decision` 相同：`as_of`、`scenario`、`mode`、`refresh`；额外 `refresh` 行为一致。
响应：`text/event-stream`（`Content-Type: text/event-stream; charset=utf-8`，`Cache-Control: no-cache`，`X-Accel-Buffering: no`）。

事件序列（事件名 `event:`，数据为单行 JSON `data:`）：

| 事件 | data | 说明 |
|---|---|---|
| `run` | `{ "run_id": "collaborative_2024-08-05_ab12cd34" }` | 发现 trace 文件后尽早发送 |
| `stage` | `{ "stage": "R0", "label": "监管主体分析中", "role": "regulator"或null, "status": "started"或"finished", "action": "analysis_start", "ts": "ISO" }` | 阶段推进（由 trace 事件映射，见 §1.3） |
| `trace` | 完整 `TraceEvent` JSON（字段同 `/api/trace/{run_id}` 单条） | 每产生一条 trace 立即推送（前端做活动流） |
| `decision` | 完整 `DecisionCard` JSON（同 `/api/decision` 响应） | 最终结果，事件流最后一个业务事件 |
| `error` | `{ "status": 503, "message": "中文错误说明" }` | 失败时发送并终止 |
| `: ping` | — | 每 10s 心跳注释，防止代理超时 |

- 命中 30 分钟决策缓存（且 `refresh=false`）：立即发送 `decision`（可附 `stage` `{stage:"cache",...}`），不重建编排器。
- 真实请求：为本次请求创建**独立 trace 目录**（如 `artifacts/traces/stream-{uuid}/`），用 `build_orchestrator(..., trace_dir=该目录)` 构建新编排器，在后台线程执行 `run`；主生成器 tail 该目录最新 `*.jsonl`，按行解析并推送。
- 浏览器断开：生成器结束时停止 tail；后台线程允许自然结束（不阻塞）。
- 总超时保护建议 300s；线程异常 → `error` 事件。

### 1.2 `POST /api/chat/stream`

Body 同 `ChatRequest`（`message`, `as_of`, `session_id`, `mode`）。事件序列同 §1.1，最终业务事件为：

| 事件 | data | 说明 |
|---|---|---|
| `chat` | 完整 `ChatResponse` JSON（同 `/api/chat` 响应） | 最终答复（含 reply/citations/decision/trace_id） |

实现方式：独立 trace 目录 + 后台线程执行 `Orchestrator.chat(request)`；tail 该目录 trace 做 `stage`/`trace` 推送；完成后推送 `chat`。

### 1.3 trace → stage 映射（后端实现时务必一致）

| TraceEvent.action | stage | label 示例 | status |
|---|---|---|---|
| `run_start` | R0 | 初始化协同分析 | started |
| `analysis_start` | R0 | 监管主体分析中 / 投资主体分析中 / 融资主体分析中（按 role） | started |
| `analysis_done` | R0 | 监管主体分析完成 | finished |
| `evidence_share` | R1 | 证据共享与去重 | started |
| `evidence_share_summary` | R1 | 证据共享完成 | finished |
| `cross_check` / `cross_check_summary` | R2 | 交叉验证关键数值 | started/finished |
| `conflict_detection` | R3 | 分歧识别 | started |
| `conflict_resolution` / `coordination_round` | R4 | 冲突协调 | started |
| `finalize` | R5 | 汇总决策卡 | finished |

`role` 映射：`regulator`→监管主体、`investor`→投资主体、`financing`→融资主体、`coordinator`→协调者、`verifier`→核验器。
前端可自行再从 `trace` 事件做补充展示；`stage` 事件只用于轻量进度条/阶段标签。

### 1.4 测试要求（后端）

- 单元：`map_trace_to_stage`/SSE 序列化函数。
- 端点：用 FakeService + monkeypatch 的流式编排器（写若干 TraceEvent 到临时 trace 目录后返回 DecisionCard/ChatResponse），断言事件顺序包含 `run/stage/trace/decision`（或 `chat`），且以 `decision`/`chat` 结束；缓存命中直接 `decision`。
- 现有 206 项 pytest 不得回归。

---

## 2. 前端 AI-native 交互需求（`web/`）

### P0（必须完成）

1. **流式运行体验**
   - 「重新生成」与首次加载都走 `decision/stream`；运行中显示 **RunProgress 面板/卡片**：阶段 R0–R5 时间线 + 三个主体状态 chip + 最近 4–6 条活动（从 `trace` 事件生成，示例如"监管主体调用 risk_measure"）+ 已用时长 + 取消按钮（AbortController）。
   - 完成后淡入替换结果；失败显示中文错误 + 重试；保留缓存说明（首次约 12–18s，缓存 <50ms）。
   - 顶部细进度条（2px，token 主色）在请求期间显示。
2. **⌘K 命令面板**（Ctrl+K 同效）
   - Dialog + 输入过滤 + 分组：导航（驾驶台/对话）、场景（5 个）、模式（协同/独立/单智能体）、操作（重新生成、切换主题、导出简报、复制当前 run_id、打开 API 文档）、AI 快捷问（"总结当前预警"、"为什么监管判定为极高？"、"三条关键证据是什么？" → 跳转对话并预填）。
   - 键盘 ↑↓ 选择、Enter 执行、Esc 关闭；焦点管理；输入框 placeholder "搜索或输入命令…"；无结果态。
   - 为截图验收支持 URL `?cmd=1` 自动打开面板。
3. **对话页流式 AI 体验**
   - 发送走 `chat/stream`：发送后立即显示"协同分析中"阶段（R0 主体分析 → 证据共享 → 交叉验证 → 冲突协调），阶段来自 SSE `stage` 事件；收到 `chat` 后助手消息以**打字机/淡入**方式呈现（尊重 reduced-motion：直接显示）。
   - 支持停止生成（AbortController）、失败重试；引用 chips 在消息后出现；关联决策卡摘要保留。
   - 当前上下文 chip（scenario/as_of/mode）+ "清除上下文"。
4. **上下文 AI 动作（AI-native 关键）**
   - 三张智能体卡：每张卡加"追问该主体"按钮 → 打开对话并预填：`解释{role}主体为什么给出「{risk_level}」判断，并列出关键证据。`（携带当前 as_of/scenario/mode）。
   - 证据 Dialog：加"让 AI 解释这条证据"按钮 → 预填 `请解释证据「{title}」的含义、来源可靠性与它对当前判断的影响。`
   - 冲突行：加"请协调者复核该分歧"按钮 → 预填对应冲突 subject。
   - 跳转后自动聚焦输入框、保留会话。
5. **交互手感（克制、token 化）**
   - Tab 切换内容淡入 + 高度过渡（≤250ms，`power`/ease-out，只动 opacity/transform）；卡片 hover 边框/底色反馈；按钮 active scale 0.98；数字 KPI 首次加载 count-up（reduced-motion 时直接落位）；骨架 shimmer 与真实布局同尺寸；toast（复制成功、重新生成完成/失败）；tooltip 覆盖图标按钮。
   - `prefers-reduced-motion: reduce` 时全部动效降级为直接切换。
6. **可访问性/键盘**
   - 所有新交互可键盘操作、焦点环可见；⌘K 面板焦点陷阱与 Esc；SSE 运行中状态用 `aria-live="polite"` 播报阶段变化（不过度打扰）。

### P1（时间允许）

7. **协同过程可视化**：把现有"核验与审计"里的 trace 升级为「协同过程」视图：R0–R5 分组时间线（角色、工具调用、耗时、token），支持展开原始事件；与运行中的活动流复用组件。
8. **追问建议 chips**：根据当前 decision 生成 3–4 条确定性追问建议（驱动因子、冲突、证据清单、情景冲击），无编造数据。
9. **消息操作**：助手消息支持复制、引用来源、继续追问；失败消息可重试。

### 约束

- 只用现有依赖（Radix/lucide/recharts 等）；不引入新的重型库；不引第二套图标/图表库。
- 视觉不破坏既有 token/规范；light/dark 双主题都要成立。
- 不改后端同步契约；`web/dist` 需重新构建通过（`bun run build` 含 `tsc --noEmit`）。
- 完成后更新 `web/DESIGN-NOTES.md`（新增 AI-native/interaction 章节）与 `web/README.md`（如有新命令/调试参数）。

---

## 3. 验收

1. `python -m pytest -q` 全绿（含新增 streaming 测试）。
2. `cd web && bun run build` 通过，`web/dist` 更新。
3. 浏览器验收（Lead 用 Edge headless 截图）：
   - `?theme=light` / `?theme=dark` 驾驶台；
   - `?cmd=1` 命令面板；
   - 运行中 RunProgress（可通过真实请求或缓存前状态截取）；
   - 对话页与追问路径。
4. 无 console/page 错误；390–1440 无横向滚动。
