# 团队协作指南（多 agent / 多人并行）

> 适用：多个开发者或多个 AI agent 在**同一工作目录**并行推进 CBR-MAW（代码 / 实验 / 文档 / 工程化）。
> 核心原则：**任务看板驱动、写入范围互斥、依赖显式化、验证命令化、由 Lead 统一提交**。
> 面向 AI agent 的仓库操作手册见 [AGENTS.md](../../AGENTS.md)；贡献流程见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

---

## 1. 协作模型

- 所有并行工作以**共享任务看板**为唯一事实源；没有任务卡的工作不应开工（临时调研除外，且不写文件）。
- 默认 5 类角色（可按项目规模合并）：

| 角色 | 典型职责 | 默认写入范围 |
|---|---|---|
| Lead / 集成者 | 拆分任务、仲裁冲突、最终验收、统一 `git add/commit` | 全部（只做集成与收尾，不长期占用子任务范围） |
| 产品/算法工程师 | `src/`、`configs/`、`scripts/`、`tests/` | 代码与实验脚本 |
| 前端/UI 工程师 | `web/`、`app/`（回退 UI） | 前端源码与构建产物 |
| 文档负责人 | `README.md`、`docs/`、根目录社区文件 | 文档与截图 |
| 仓库工程化 | `.github/`、`pyproject.toml`、`.gitignore`、`LICENSE`、`scripts/repo/` | 工程化与 CI |

> 角色只是默认值；**以任务卡的 `write_scopes` 为准**。同一文件同一时间只能有一个负责人。

---

## 2. 任务看板使用流程

1. **列表**：`team_task_list()` 查看任务、状态、owner、revision、blocked_by、writeScopeWarnings。
2. **读全文**：`team_task_get(task_id)`；不要只凭标题开工。
3. **认领**：`team_task_update(task_id, expected_revision=<当前>, action="claim")`。
   - `expected_revision` 是 CAS 前置条件：看板被他人改过会失败，重新 `team_task_get` 再试。
4. **执行**：只改自己任务 `write_scopes` 内的文件；需要越界时先在任务描述里补充范围并获得 Lead 同意。
5. **完成**：`team_task_update(task_id, expected_revision=<最新>, action="complete")`，并用 `send_message` 给 Lead 发交付摘要。
6. 需要拆分时由 Lead `team_task_create`（可带 `blocked_by` 与 `write_scopes`）；执行者不要自行改任务范围。

**依赖**：用 `blocked_by` 表达「必须等 A 完成才能开始 B」。典型顺序：

```text
产品可运行（测试全绿/入口实测）
        └─> 文档中的实测数字与命令（README/指南）
仓库工程化（CI/忽略规则/LICENSE）
        └─> 文档中的许可证/CI 章节
```

被阻塞任务不要提前开工；可以先把不依赖的部分（资料阅读、草稿）准备好，但**不写共享文件**。

---

## 3. 写入范围与冲突避免

### 3.1 默认边界

- 严格按任务卡 `write_scopes` 写入；范围外文件只读。
- 多个任务都需要改同一文件时：**由 Lead 指定唯一 owner**，其他人只提交建议（issue/消息），不直接改。
- 生成物（`artifacts/`、`data/processed/`、`web/dist`）由各自任务负责；`web/dist` 当前入库并随前端构建更新，改前端后需重新构建并确认产物一致。
- 数据/密钥/产物一律不入库：`data/raw/`、`data/custom/`、`secrets/`、`.env`、`artifacts/`、用户原始数据压缩包。

### 3.2 文件写入纪律

1. 覆盖已有文件前先读取；优先用定向编辑而不是整文件重写。
2. 遇到 `FS_STALE_VERSION`：重新读取最新内容，基于新内容重放改动，不要强行覆盖。
3. 不要用脚本批量重写别人负责的文件；跨范围修改必须先沟通。
4. 不执行 `git add/commit/push`（统一由 Lead 做），也不执行破坏性 git 命令。

### 3.3 任务卡写法建议

- 标题：动词 + 对象 + 范围（例：「文档体系完善（README/指南/协作规范）」）。
- 描述包含：目标、必做项（可勾选）、写入范围、不要改的文件、验收标准、需要 Lead 决策的点。
- 写清依赖产物：例如「等待产品任务给出实测测试数后再写 README 状态段」。

---

## 4. 分工示例（本仓库实际任务）

| 任务 | 负责人 | 写入范围 | 依赖 |
|---|---|---|---|
| 产品完整性与可运行性 | 产品/算法 | `src/ tests/ app/ configs/ scripts/`、删除根目录 `tmp_*.py` | 无 |
| 文档体系 | 文档负责人 | `README.md docs/ CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md AGENTS.md` | 弱依赖产品任务（数字以 Lead 转发或保守表述） |
| 仓库工程化与 CI | 工程化 | `.github/ .gitignore .gitattributes .editorconfig pyproject.toml requirements*.txt .pre-commit-config.yaml LICENSE scripts/repo/` | 无（与文档任务并行） |

并行的关键：**三方写集不相交**；产品任务测出的数字通过 Lead 转发给文档任务；工程化任务的 `LICENSE` 存在后，README 许可证链接才可落地（否则先写文字说明）。

---

## 5. 沟通协议

- **进度**：任务开始/阻塞/完成各发一条，不刷屏；阻塞要写「卡在哪、需要谁、期望时间」。
- **交付消息格式**（≤30 行）：做了什么 → 验证结果（命令 + 关键输出）→ 未决/需确认点 → 产物路径。
- **冲突**：由 Lead 仲裁；不要直接改他人的文件或任务卡。
- **知识沉淀**：影响他人的结论写入文档或任务描述，不要只留在对话里。

任务卡状态约定：`pending`（未开始）→ `in_progress`（已认领并执行）→ `completed`（验收通过）。被阻塞任务保持 `pending` + `blocked_by`，不要用 `in_progress` 假装开工。

---

## 6. 验证命令

任何任务完成前，至少跑与本任务相关的验证；Lead 合并前跑全量。

| 范围 | 命令 | 通过标准 |
|---|---|---|
| 全量测试 | `.venv\Scripts\python.exe -m pytest -q` | 全绿（基线 249 项，2026-10-18 记录；以实际为准） |
| 数据构建 | `.venv\Scripts\python.exe scripts\build_sample_data.py`、`scripts\build_knowledge.py` | 无异常，产物生成 |
| 实验 | `.venv\Scripts\python.exe scripts\run_experiment.py --kind p1 --p1-max-days 60` | 产出 `artifacts/runs/<run_id>/` |
| API | 启动 uvicorn 后 `GET /api/health`、`GET /api/decision?as_of=2024-08-05` | 200，决策卡字段完整 |
| SSE | `.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8000` | `run → stage/trace → decision` 顺序正确 |
| 前端 | `cd web; bun install; bunx tsc --noEmit; bun run build` | 无 TS/构建错误，`web/dist` 更新 |
| 文档 | 断链检查（扫描全部 `*.md` 相对链接）+ 命令逐条可复制 | 断链 0 处；命令与仓库一致 |

> 断链检查可使用仓库工程化任务提供的脚本（若已合入 `scripts/repo/`），或写临时脚本放系统临时目录（不留在仓库）。检查范围应包含 `README.md`、`docs/**/*.md`、`web/*.md` 与根目录社区文件。

---

## 7. 提交与收尾

- Lead 统一执行 `git add/commit`；子任务不直接提交。提交信息建议 Conventional Commits（`feat:` / `fix:` / `docs:` / `test:` / `chore:`），一次提交聚焦一件事。
- 每轮收尾检查：
  1. `git status` 无意外文件（尤其数据/密钥/临时脚本）；
  2. 全量测试通过或明确记录环境性失败；
  3. 文档与代码一致（命令、配置项、测试数、版本头）；
  4. 任务卡已 `complete` 且给 Lead 发了摘要；
  5. 未决事项在任务描述或 `docs/techdoc/open_issues.md` 留痕。

---

## 8. 常见协作反模式

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 未认领就改文件 | 与并行任务冲突、返工 | 先 `team_task_get` + `claim` |
| 顺手改别人的范围 | 覆盖他人改动 | 只读；把建议发给 Lead/owner |
| 直接 `git commit` | 与 Lead 集成冲突 | 交给 Lead 统一提交 |
| 把未验证数字写进 README | 文档失真 | 标注日期与来源，或写「以实测为准」 |
| 忽略 `blocked_by` | 基于过期事实开工 | 等依赖完成或先做只读准备 |
| 本地临时脚本留在仓库根 | 污染仓库 | 放系统临时目录，用完删除 |
