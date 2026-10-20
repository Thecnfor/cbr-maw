# CONTRIBUTING · 贡献指南

感谢你参与 CBR-MAW（跨境金融风险多智能体协同预警系统）。本指南说明如何搭环境、改代码、写测试、提 PR，以及与文档/实验保持一致。

> 先读：[README](README.md)（项目定位与总体架构）、[docs/INDEX.md](docs/INDEX.md)（文档导航）、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)（行为准则）。
> 使用 AI agent 协作时，另见 [AGENTS.md](AGENTS.md)（仓库结构、写入范围、任务看板、验证命令）。

---

## 1. 环境准备

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 开发工具：ruff / pytest-cov / pre-commit
.venv\Scripts\python.exe -m pip install -e . --no-deps
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py
.venv\Scripts\python.exe -m pytest -q
```

前端（可选）：

```powershell
cd web
bun install
bun run build
```

更细步骤见 [快速开始](docs/guides/quickstart.md)；无 key 时系统自动使用 Mock LLM，不需要真实 API 即可开发。

---

## 2. 分支与提交

- 主分支为 `master`；仓库当前无 remote，发布前由维护者统一推送。
- 分支命名：`feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>`。
- 提交信息采用 Conventional Commits，**一次提交只做一件事**：

```text
feat(tools): 新增 liquidity_gap 确定性工具与权限矩阵
fix(api): 修复 as_of 越界时的 500
docs(readme): 重写 GitHub 主页视角
test(streaming): 补充 SSE 超时与取消用例
chore(ci): 增加 pre-commit 与断链检查
```

- 提交前 `git status` 确认没有数据/密钥/临时文件；`artifacts/`、`data/raw/`、`data/custom/`、`secrets/`、`.env` 不得入库。
- 子任务/多人并行时，由集成者（Lead）统一 `git add/commit`，避免交叉提交。

---

## 3. 代码规范

| 项 | 约定 |
|---|---|
| Python | ≥ 3.11（验证于 3.12），全量类型注解，`from __future__ import annotations` |
| 风格 | `ruff`（`line-length = 110`，规则见 `pyproject.toml` 的 `[tool.ruff]`）；`pip install -r requirements-dev.txt` 已包含，然后 `ruff check .` |
| 数据契约 | 跨模块结构只放 `src/cbr/schemas.py`；接口协议只放 `src/cbr/contracts.py`，不要另造平行结构 |
| 确定性 | 金融数值必须由 `src/cbr/tools/` 的确定性工具计算；**LLM 不产数值**，文本结论必须绑定知识库引文 |
| 时点 | 数据/知识库读取一律走 `as_of` 过滤（`release_time <= as_of`），禁止使用未来信息 |
| 配置 | 新增可调参数放 `configs/*.yaml` + `src/cbr/config.py` 设置类，不要硬编码 |
| 前端 | React 19 + TS strict；token 只改 `web/src/styles/tokens.css`；不新增图标/图表/状态管理库 |
| 日志 | 不打印密钥；错误信息面向用户用中文（API 统一 503 + 中文 `detail`） |

### 代码导览（改哪里）

| 需求 | 位置 |
|---|---|
| 新增确定性金融工具 | `src/cbr/tools/` + `configs/tools.yaml` + `configs/roles.yaml` 权限 + `tests/test_tools.py` |
| 新增风险信号/特征 | `src/cbr/features/`、`src/cbr/models/` + `tests/test_models.py` |
| 修改智能体行为/prompt | `src/cbr/agents/` + `configs/prompts/` + `configs/roles.yaml` + `tests/test_agents.py` |
| 修改协同/仲裁/HITL | `src/cbr/orchestration/` + `tests/test_orchestration.py` |
| 修改核验/审计 | `src/cbr/verification/` + `tests/test_verification.py` |
| 新增/改 API | `src/cbr/api/` + `tests/test_api.py` / `tests/test_streaming.py` |
| 改实验指标 | `src/cbr/eval/`、`scripts/run_experiment.py` + `tests/test_eval.py` |
| 改前端 | `web/src/` + `web/DESIGN-NOTES.md`（规范） + `bun run build` 更新 `web/dist` |

---

## 4. 测试要求

- 行为变更必须带测试；修 bug 先写复现用例。
- 提交前至少跑相关测试，PR 前跑全量：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests\test_orchestration.py -q   # 相关子集
```

- 当前基线：**249 项通过**（2026-10-18 记录）；新增测试后同步更新 README/文档中的计数（写日期）。
- 测试必须离线可跑：涉及真实 DeepSeek 的用例应可跳过或默认 Mock；不得依赖外网与密钥。
- 涉及随机性时固定 seed，并在测试/文档中注明。

---

## 5. 文档与实验一致性

- 改命令、配置项、API、目录结构时，同步更新 README 与相关 `docs/guides/*`；版本头（`docs/techdoc/*`）实质修改需递增。
- 新增文档：更新 [docs/INDEX.md](docs/INDEX.md) 与 README 文档索引；截图放 `docs/assets/screenshots/`。
- 相对链接必须有效（提交前做断链检查，见 [团队协作指南 §6](docs/guides/team-collaboration.md#6-验证命令)）。
- 实验结论遵守口径：pilot 与正式结果分开；不显著不得写成显著；默认数据为 SYNTHETIC 必须标注。
- 版本变更在 [CHANGELOG.md](CHANGELOG.md) 追加条目（Unreleased → 版本号）。

---

## 6. PR 流程

1. 从 `master` 切分支，完成改动与测试。
2. 提交前自检（见 §7）。
3. 发起 PR：说明动机、改动点、验证命令与结果、影响范围（API/配置/数据口径）、截图（UI 变更）。
4. Review 关注：数据契约是否破坏、是否引入未来信息、数值是否来自工具、测试是否覆盖、文档是否同步。
5. CI 合入后以 `.github/workflows/` 的实际检查项为准（pytest、ruff、web build 等）。
6. 合并后由维护者打版本/更新 CHANGELOG。

---

## 7. 提交前检查清单

- [ ] `pytest -q` 通过（或说明环境性失败）
- [ ] `ruff check .` 无新增问题
- [ ] 无数据/密钥/临时文件（`git status` 干净）
- [ ] 新命令已在 README/指南中更新并实测可复制
- [ ] 文档链接有效、`docs/INDEX.md` 已更新（如新增文档）
- [ ] UI 变更已 `bun run build` 并更新说明/截图
- [ ] CHANGELOG 已记录（面向用户的变更）

---

## 8. 安全问题

漏洞、密钥泄露、权限绕过等问题**不要**公开提 Issue，按 [SECURITY.md](SECURITY.md) 的私下报告流程处理。
