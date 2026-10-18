# CBR-MAW · 跨境金融风险多智能体协同预警系统

> 论文方向2《跨境金融风险的多智能体协同预警：多模态信息融合视角》的工程原型 + 技术文档。
> 核心思想：**确定性金融工具算数 + LLM 智能体编排解释 + 证据链核验 + 配置化消融实验**。

## 1. 这是什么

一个可运行、可审计、可消融的多智能体风险预警系统：

- **一个共同预警目标**：跨境金融市场压力高位状态（未来 5 / 10 / 20 个交易日）；
- **三类主体智能体**：监管（市场压力与外溢）、投资（组合尾部损失）、融资（融资成本与现金流压力）；
- **协同机制**：共享证据黑板 → 交叉验证 → 分歧识别（事实/方向/偏好）→ 协调仲裁 → 汇总决策卡；
- **可信机制**：所有数值由版本化工具计算（LLM 不产数值）、文本结论引用时点过滤的知识库、越权工具调用被阻断、全链路审计 trace；
- **两套入口**：React 驾驶台（时间轴回放 / 三智能体卡片 / 证据板 / 分歧面板 / 核验审计 / 导出）+ 对话入口（自然语言问风险，带证据回答）；Streamlit 保留为回退 UI；
- **可消融实验**：单智能体 / 三个独立智能体 / 完整协同系统，同一代码路径、可比资源预算；
- **设计规范**：React 前端按 `Thecnfor/design-stack` 的 shadcn-conventions + Linear 级规范实现（token 派生自 XRAK `packages/ui`，参考 cross-dashboard `DESIGN.md`），light/dark 双主题、可访问焦点环、reduced-motion 降级；详见 [web/DESIGN-NOTES.md](web/DESIGN-NOTES.md)。
- **AI-native 交互**：SSE 流式运行（R0–R5 阶段 + 三主体状态 + 实时活动流 + 取消）、`⌘K` 命令面板、对话流式阶段与打字机、上下文 AI 追问（智能体卡/证据/冲突一键跳转提问）、协同过程时间线；SSE 不可用时自动回退同步端点并明示。

## 2. 快速开始（Windows / Python 3.12）

```powershell
# 1) 虚拟环境与依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps

# 2) 构建样例数据（仿真数据，明确标注 synthetic）与知识库索引
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py

# 3) 运行测试
.venv\Scripts\python.exe -m pytest -q

# 4) 构建 React 驾驶台（主界面，遵循 shadcn/ui + Linear 设计规范）
cd web
bun install
bun run build
cd ..

# 5) 启动服务：API + React 驾驶台（http://127.0.0.1:8000/ui/）
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
```

- 驾驶台（推荐）：<http://127.0.0.1:8000/ui/>（light/dark 双主题，页面右上角切换；`?theme=dark` 强制深色、`?cmd=1` 自动打开命令面板）
- API 文档：<http://127.0.0.1:8000/docs>；流式接口：`GET /api/decision/stream`、`POST /api/chat/stream`（SSE，见 [streaming-api-notes.md](docs/design/streaming-api-notes.md)）
- 回退 UI（Streamlit）：`.venv\Scripts\python.exe -m streamlit run app\dashboard.py --server.port 8501`
- 前端开发模式：`cd web && bun run dev`（http://127.0.0.1:5173，/api 代理到 8000）

## 3. 接入真实数据（用户自建数据集）

- 将数据放入 `data/custom/`（CSV 或 Parquet）；
- 在 `configs/data_mapping.yaml` 配置：日期列、发布时点列、序列 ID 映射、频率、单位；
- 修改 `configs/app.yaml`：`data.dataset: custom`，并设置样本区间；
- 系统统一通过 point-in-time 接口读取（按发布时点过滤），演示/实验/界面共用同一数据层。

未提供真实数据时，系统自动回退到 `data/samples/` 下的**仿真数据**（仅用于系统演示，不可用于任何真实决策）。

## 4. 接入 DeepSeek

优先读取环境变量，其次读取本地密钥文件：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."          # 方式一
# 或：把 key 写入 secrets/deepseek.key      # 方式二（已被 .gitignore 忽略）
```

- 未提供 key 时自动使用 **Mock LLM**（确定性规则模式），全流程可离线跑通；
- 提供 key 后同一代码路径自动切换真实 DeepSeek（OpenAI 兼容接口，JSON 结构化输出）；
- `configs/app.yaml → llm` 可配置模型、温度、超时、重试；默认 `deepseek-chat`、`temperature=0`。

## 5. 目录结构

```
configs/            角色规范、场景、实验配置、数据映射
data/               samples（仿真）/ custom（用户数据）/ knowledge（知识库语料与索引）/ pit.duckdb
src/cbr/
  schemas.py        跨模块唯一数据契约（Evidence/Claim/RiskCard/DecisionCard/...）
  contracts.py      模块接口协议（DataProvider/Tool/KnowledgeBase/LLMClient/Orchestrator）
  service.py        服务装配（API/UI/实验共用）
  data/ features/ models/   时点数据层、多模态特征、融合风险信号（P1）
  tools/ knowledge/         确定性金融工具、时点知识库/RAG（P2）
  llm/ agents/              DeepSeek/Mock 抽象、三角色智能体（P2/P3）
  orchestration/ verification/  黑板/协同/冲突协调/HITL、核验与审计 trace（P3）
  eval/                     指标与统计检验
  api/                      FastAPI 服务（含 /ui 静态托管）
web/                React 19 + Vite + Tailwind v4 驾驶台/对话（shadcn/ui + Linear 规范）
app/                Streamlit 风险驾驶台 + 对话入口（回退 UI）
artifacts/          模型、trace、实验运行结果、导出报告、UI 截图（运行时生成）
docs/
  architecture/     架构设计文档
  techdoc/          技术文档（第四章方法论）
  research/         框架调研、数据源实测报告
```

## 6. 文档

- 架构设计（实现定稿）：[docs/architecture/CBR-MAW_architecture_v1.md](docs/architecture/CBR-MAW_architecture_v1.md)
- 技术文档第四章（Markdown）：[docs/techdoc/chapter4_method.md](docs/techdoc/chapter4_method.md)
- 技术文档第四章（Word）：[docs/techdoc/第四章_多模态多智能体协同预警方法.docx](docs/techdoc/第四章_多模态多智能体协同预警方法.docx)
- 前端设计与规范：[web/DESIGN-NOTES.md](web/DESIGN-NOTES.md)、[web/README.md](web/README.md)
- AI-native 交互契约：[docs/design/ai-native-interaction-spec.md](docs/design/ai-native-interaction-spec.md)；流式接口说明：[docs/design/streaming-api-notes.md](docs/design/streaming-api-notes.md)
- 待办与集成核对清单：[docs/techdoc/open_issues.md](docs/techdoc/open_issues.md)
- 试点实验：[pilot_results_synthetic.md](docs/techdoc/pilot_results_synthetic.md)（Mock/规则后端）、[pilot_results_real_llm.md](docs/techdoc/pilot_results_real_llm.md)（真实 DeepSeek P2/P3）
- 调研报告：[docs/research/multi_agent_frameworks.md](docs/research/multi_agent_frameworks.md)、[docs/research/data_sources.md](docs/research/data_sources.md)

### 重新生成 Word 文档

```powershell
# 1) 渲染 Mermaid 图为 PNG（依赖 mermaid.ink 在线渲染，需联网）
.venv\Scripts\python.exe scripts\render_mermaid.py docs\techdoc\chapter4_method.md docs\techdoc\figures
# 2) Markdown -> DOCX
.venv\Scripts\python.exe scripts\md_to_docx.py docs\techdoc\chapter4_method.md "docs\techdoc\第四章_多模态多智能体协同预警方法.docx" docs\techdoc\figures
```

## 7. 当前实现状态（2026-10-18，本机实测）

- 全量 pytest：**249 项全部通过**（206 基线 + 43 项 SSE streaming 测试；含 DeepSeek 真实调用、端到端集成、自建数据接入测试）。
- React 驾驶台（`web/`）：AI-native 交互——SSE RunProgress、⌘K 命令面板、上下文 AI 追问、协同过程时间线、对话流式/打字机；light/dark 双主题；`bun run build` 通过（dist ~1.01MB / 7 文件，首屏 gzip 168.65kB），由 FastAPI `/ui` 托管；截图见 `artifacts/ui-ai/`（`final_dashboard_light/dark.png`、`sse_run_progress_light.png`、`final_palette_light/dark.png`、`sse_chat_done_light.png`）。
- SSE 流式（真实 DeepSeek）：`/api/decision/stream` 事件 `run=1 / trace=97 / stage=35 / decision=1`（14.5s）；`/api/chat/stream` 以 `chat` 收尾；缓存命中 0.01s 仅返回 `decision`；心跳 10s；`web` 不可用自动回退同步端点。
- 数据快照：27 个序列 / 41,367 条观测 / 2,207 篇文档；`dataset_snapshot_id=ds_1beab3f3ffd9e31a4c5b`（`data/pit_manifest.json`）。
- `/api/decision` 真实 DeepSeek 端到端：3 张风险卡、20 条证据、冲突全部解决、核验通过（数值错误率 0、证据准确率 100%、越权/泄漏/schema 错误 0），首次约 15s、缓存后 <50ms（30 分钟 TTL）。
- 真实 LLM 复跑：P2（3 日 × 2 变体）+ P3（4 日 × 3 模式）= 18 次运行 / 54 次调用全部成功，0 错误/超时/Schema 失败；实际 tokens 323,431、费用约 ¥0.70；详见 [pilot_results_real_llm.md](docs/techdoc/pilot_results_real_llm.md)。
- 实验脚本：`scripts/run_experiment.py --kind p1|p2|p3|all`（v2 指标：证据门槛任务完成率、真实 API tokens、草稿级 trace 指标），产物在 `artifacts/runs/<run_id>/`。
- 样例数据为 **SYNTHETIC 仿真数据**，实验指标仅用于流程验证；正式论文实验需接入真实数据后重跑。

## 8. 说明


- 样例数据为**仿真数据**（synthetic），仅用于系统演示与流程验证，不代表真实市场；
- 系统输出为研究性风险提示，不构成投资建议或监管决定。
