# AGENTS · CBR-MAW 多语言仓库协作手册

> 读者：进入本仓库的 AI agent 与人类协作者。
> 协作细节见 [docs/guides/team-collaboration.md](docs/guides/team-collaboration.md)；贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 1. 权威文档地图（唯一真源，互不复写）

| 主题 | 权威文档 |
|---|---|
| 产品边界、三条不可让步红线、研究域口径、已决/待决总表 | [docs/00-设计基线.md](docs/00-设计基线.md) |
| 现行与 v3.0 / `X-AlertAgent` 架构（双核嵌套、三进程、包边界、技术栈） | [docs/01-架构设计.md](docs/01-架构设计.md) |
| 工程基线、双版本分离、三语言门禁、Windows 原生构建与 CI 规范 | [docs/09-工程化规范.md](docs/09-工程化规范.md) |
| 阶段决策、v1/v1.5/v2/v3 里程碑、契约清单与出口标准 | [docs/11-实施设计.md](docs/11-实施设计.md) |
| 新规范 vs 现有 v1 代码整改台账（P0/P1/P2 收口任务） | [docs/12-v1架构与工程收口清单.md](docs/12-v1架构与工程收口清单.md) |
| 架构决策记录（ADR-001 ~ ADR-011） | [docs/adr/README.md](docs/adr/README.md) |

> **只读研究材料**：`ref/`、[docs/research/](docs/research/)、[docs/10-研究域设计/](docs/10-研究域设计/) 在任何实现过程中均不得修改。

---

## 2. 角色与写入范围（Monorepo）

| 角色 | 默认可写 | 默认只读 |
|---|---|---|
| Lead / 集成者 | 全部（集成收尾与 git 提交） | — |
| 契约 agent | `contracts/`、`packages/contracts_dart/` | 其它 |
| Rust 内核 agent | `services/kernel/` | `contracts/`、`apps/` |
| Go 采集器 agent | `services/collector/`、`configs/sources.json` | `contracts/`、`apps/` |
| 设计系统 agent | `packages/design_system/`、`packages/a2ui_catalog/` | `apps/` |
| 应用/UX agent | `apps/desktop/lib/app/`、`apps/desktop/lib/features/` | `apps/desktop/lib/agents/`、`apps/desktop/lib/genui/` |
| Agent 编排 agent | `apps/desktop/lib/agents/`、`apps/desktop/lib/genui/`、`configs/prompts/` | `apps/desktop/lib/features/` |
| 工程化 agent | `tools/`、`packaging/`、`VERSION`、`analysis_options.yaml`、`pubspec.yaml` | 其它 |
| 文档 agent | `docs/`、`README.md`、`CHANGELOG.md`、`AGENTS.md`、`CLAUDE.md` | 代码 |

**规则**：以任务卡 `write_scopes` 为准；写集不相交；同一文件同一时间只有一个 owner；越界修改必须先经 Lead 同意。

---

## 3. 任务看板用法（必须遵守）

1. `team_task_list()`：查看任务、状态、owner、revision、`blocked_by`、`writeScopeWarnings`。
2. `team_task_get(task_id)`：阅读目标、必做项、写入范围与验收标准。
3. `team_task_update(task_id, expected_revision=<当前>, action="claim")`：认领（revision 是 CAS 前置条件）。
4. 在自身 `write_scopes` 内执行并跑通验证命令。
5. `team_task_update(task_id, expected_revision=<最新>, action="complete")`：完成。
6. `send_message(target="lead", ...)` 发送交付摘要（做了什么 / 验证结果 / 未决点 / 产物路径，≤30 行）。

被 `blocked_by` 阻塞时不要开工写共享文件；不要自行扩大任务范围。

---

## 4. 文件操作纪律

- 修改已有文件前**先读取**；优先定向 `edit` 而非整文件重写。
- 收到 `FS_STALE_VERSION`：重新读取最新内容并基于新内容重放改动，不要强写。
- 临时脚本放系统临时目录（如 `%TEMP%` 或 `/tmp`），**禁止留在仓库内**；用完清理。
- 不执行 `git add / commit / push` 或破坏性 git 命令（由 Lead 统一操作）。
- **不提交**：`data/inbox/`、`data/raw/`、`data/custom/`、`data/processed/`、本地 DuckDB/LanceDB 库、`artifacts/`、`secrets/`、`.env`、`ref/`。
- **单一真源纪律**：不得在 `apps/desktop` 内复制 `packages/design_system`、`packages/a2ui_catalog` 或 `configs/prompts/` 的副本。
- **零硬编码示例数值**：`apps/` 与 `services/` 产品代码不得出现伪造行情点位、新闻正文、遥感像元或情绪分；测试夹具须显式标注 `synthetic`。

---

## 5. 验证命令入口（详情见 [docs/09 §7](docs/09-工程化规范.md)）

```bash
# 一条命令跑通全门禁（Linux/macOS；Windows 使用对等 PowerShell 脚本）
bash packaging/verify_all.sh
```

分项命令：`dart format --set-exit-if-changed .` · `flutter analyze` · `(cd apps/desktop && flutter test)` · `flutter test packages/design_system packages/a2ui_catalog` · `dart test packages/contracts_dart` · `(cd services/kernel && cargo fmt --check && cargo clippy -- -D warnings && cargo test)` · `(cd services/collector && go vet ./... && go test ./...)` · `dart run tools/validate_contract.dart` · `dart run tools/check_layers.dart` · `dart run tools/check_version.dart`。

判定标准：全部 PASS，`flutter analyze` 与 `cargo clippy` 零告警，无未授权新增文件。

---

## 6. 分支、提交与红线

- 主分支 `main`；工作分支 `feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>`；由 Lead 统一使用 Conventional Commits 提交，不用 `git add -A`。
- **绝对禁止**：伪造数据或测试输出；为任何数据来源写 mock/假数据；把仿真或 `SIMULATION` 沙盒结论表述为真实市场结论；不显著写成显著；未走 ADR 擅自改变架构边界或设计口径。
- **交付前确认**：按范围完成 + 门禁全绿 + `git status` 干净 + 文档与 [CHANGELOG.md](CHANGELOG.md) 同步 + 涉及设计变更先改基线/ADR。
