# AGENTS · 仓库协作手册（AI agent 与人类共用）

> 读者：后续进入本仓库的 AI agent 与人类协作者。
> 目标：让任何新成员在 10 分钟内知道**仓库怎么组织、任务怎么接、文件能改哪里、命令怎么验、提交谁来做**。
> 面向人的并行协作细节见 [docs/guides/team-collaboration.md](docs/guides/team-collaboration.md)；贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 1. 项目速览

- **CBR-MAW**：跨境金融风险多智能体协同预警系统（论文方向 2 工程原型）。
- **核心公式**：确定性金融工具算数 + LLM 智能体编排 + 证据链核验 + 配置化消融。
- **运行形态**：FastAPI（`/api/*`）+ React 驾驶台（`/ui/`，主 UI）+ Streamlit（回退 UI）+ 实验脚本。
- **数据**：默认 `data/samples/` 的 **SYNTHETIC 仿真数据**（离线测试/复现）；**真实数据快照已接入**（`data/custom/` + `configs/data_mapping.yaml`，2026-10-20：2015–2025、27 序列 / 9,758 篇文本，见 `docs/data/real_data_integration.md`）。
- **当前版本**：技术文档第四章 v0.8；测试基线 249 项（2026-10-18 记录；2026-10-20 真实数据接入后需重新跑全量 pytest 确认）。

---

## 2. 仓库结构与入口

| 路径 | 作用 | 常见改动 |
|---|---|---|
| `src/cbr/schemas.py` / `contracts.py` | 数据契约 / 模块接口协议 | 改结构必须同步全链路与测试 |
| `src/cbr/service.py` | `build_service()` 装配（API/UI/实验共用） | 新增模块后在此挂载 |
| `src/cbr/data/ features/ models/` | L1 数据、L2 特征与融合信号 | 数据口径、特征、训练 |
| `src/cbr/tools/ knowledge/` | L3 确定性工具、时点知识库 | 工具计算、权限、BM25 |
| `src/cbr/llm/ agents/` | L4 DeepSeek/Mock、三角色智能体 | prompt、角色规范 |
| `src/cbr/orchestration/ verification/` | L5 协同编排、核验与 trace | R0–R5、冲突、HITL |
| `src/cbr/api/` | FastAPI 同步 + SSE 端点 | API 契约、缓存、流式 |
| `web/` | React 驾驶台/对话（主 UI） | 前端组件、token、构建 |
| `app/` | Streamlit 回退 UI | 兼容性修复 |
| `configs/` | 应用/角色/情景/工具/实验配置 | 改行为优先改配置 |
| `scripts/` | 数据构建、实验、文档渲染、流式验收 | 新增批处理脚本 |
| `tests/` | pytest（基线 249 项，2026-10-18 记录） | 行为变更必带测试 |
| `docs/` | 架构、第四章、设计契约、调研、指南 | 文档与链接 |
| `artifacts/` | 模型/trace/实验/截图（**忽略，不入库**） | 只读/生成 |

启动与验证命令见 [README 快速开始](README.md#3-快速开始) 与 [quickstart](docs/guides/quickstart.md)。

---

## 3. 角色与写入范围

| 角色 | 默认可写 | 默认只读 |
|---|---|---|
| Lead / 集成者 | 全部（集成收尾） | — |
| 产品/算法 agent | `src/ tests/ app/ configs/ scripts/` | `docs/`、`web/` |
| 前端 agent | `web/` | `src/`、`docs/` |
| 文档 agent | `README.md`、`docs/`、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`CHANGELOG.md`、`AGENTS.md` | `src/`、`tests/`、`configs/`、`.github/` |
| 工程化 agent | `.github/`、`pyproject.toml`、`.gitignore`、`.gitattributes`、`.editorconfig`、`LICENSE`、`requirements*.txt`、`scripts/repo/` | 其它 |

**规则**：以任务卡 `write_scopes` 为准；写集不相交；同一文件同一时间只有一个 owner；越界修改必须先经 Lead 同意。

---

## 4. 任务看板用法（必须遵守）

1. `team_task_list()`：看任务、状态、owner、revision、`blocked_by`、`writeScopeWarnings`。
2. `team_task_get(task_id)`：读全文（目标、必做项、写入范围、验收标准）。
3. `team_task_update(task_id, expected_revision=<当前 revision>, action="claim")`：认领。
   - revision 是 CAS 前置条件，失败就重新 get 再试。
4. 执行（只写自己的范围）。
5. `team_task_update(task_id, expected_revision=<最新>, action="complete")`。
6. `send_message(target="lead", ...)` 发交付摘要（做了什么 / 验证结果 / 未决点 / 产物路径，≤30 行）。

被 `blocked_by` 阻塞时不要开工写共享文件；可先做只读准备。不要自行扩大任务范围。

---

## 5. 文件操作纪律

- 覆盖/编辑已有文件前**先读取**；优先定向 `edit` 而非整文件重写。
- 收到 `FS_STALE_VERSION`：重新读取最新内容，基于新内容重放改动，不要强写。
- 临时脚本放系统临时目录（如 `%TEMP%`），**不要留在仓库根目录**；用完删除。
- 不要用脚本批量改写他人负责的文件；不要执行 `git add/commit/push` 或破坏性 git 命令（由 Lead 统一做）。
- 不提交：`data/raw/`、`data/custom/`、`data/processed/`、`data/pit.duckdb`、`artifacts/`、`secrets/`、`.env`、用户原始数据压缩包、`tmp_*.py`。
- 修改 `web/` 后重新 `bun run build`，保持 `web/dist` 与源码一致（`web/dist` 当前入库用于 `/ui/` 免构建演示）。

---

## 6. 验证命令

```powershell
# 全量测试（提交/合并前）
.venv\Scripts\python.exe -m pytest -q

# 相关子集
.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_orchestration.py -q

# 数据与知识库（新环境）
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py

# API 冒烟（先启动 uvicorn）
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:8000/api/decision?as_of=2024-08-05&mode=collaborative" | Select-Object run_id

# SSE 流式验收
.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8000

# 前端
cd web; bunx tsc --noEmit; bun run build; cd ..

# 文档断链（扫描全部 *.md 相对链接，0 处断链；可用临时脚本）
```

判定标准：pytest 全绿（或明确环境性例外）；API 200 且关键字段完整；SSE 事件顺序 `run → stage/trace → decision`；前端无 TS/构建错误；文档链接全部可解析。

---

## 7. 分支、提交与版本

- 主分支 `main`；仓库已发布（公开）：<https://github.com/Thecnfor/cbr-maw>。个人/agent 工作在 `feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>` 分支。
- 由 Lead 统一 `git add/commit`；提交信息用 Conventional Commits（`feat:`/`fix:`/`docs:`/`test:`/`chore:`），一次提交聚焦一件事。
- 不直接 push 到 `main`、不改写历史、不使用 `git add -A` 夹带无关文件。
- 行为/命令/配置变更 → 同步 README 与 `docs/guides/*`；用户可见变更 → [CHANGELOG.md](CHANGELOG.md)。
- 实验结论：默认 SYNTHETIC；pilot 与正式结果分开；不显著不得写成显著。

---

## 8. 禁止事项

- 伪造数据、结果或测试输出；把仿真结论表述为真实市场结论。
- 提交密钥、原始数据、大文件（含用户原始数据压缩包）、临时脚本。
- 未经许可修改他人范围文件、执行 git 写操作或删除他人产物。
- 在没有证据的情况下引用不存在的文件、截图、命令或数字。

---

## 9. 交付检查清单

- [ ] 任务卡已 claim（revision 正确）并按范围完成
- [ ] 相关测试通过；全量 pytest 结果已知
- [ ] 命令/配置/链接已实测（可复制执行）
- [ ] `git status` 无意外文件；临时脚本已清理
- [ ] 文档/CHANGELOG 同步（如涉及用户可见变更）
- [ ] 已 `complete` 任务并给 Lead 发摘要
