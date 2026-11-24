# AGENTS · CBR-MAW Flutter 仓库协作手册（AI agent 与人类共用）

> 读者：进入本仓库的 AI agent 与人类协作者。
> 目标：任何新成员在 10 分钟内知道**仓库怎么组织、任务怎么接、文件能改哪里、命令怎么验、提交谁来做**。
> 面向人的并行协作细节见 [docs/guides/team-collaboration.md](docs/guides/team-collaboration.md)；贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
>
> **本文档是设计文档，不是实现文档。** 当前阶段只做设计与脚手架，尚未开始功能实现。设计基线见 [docs/00-设计基线.md](docs/00-设计基线.md)，任何与基线冲突的改动必须先改基线并记 ADR。

---

## 1. 项目速览

- **CBR-MAW**：跨境金融风险多智能体协同预警研究工作台（论文方向 2 的 Flutter 重写版）。
- **产品形态**：**纯客户端单进程**。一个安装包 + 配置一个 API 密钥即可使用，**没有中央服务器、没有 BFF、不需要部署任何后端**。
- **技术栈**：Flutter 3.50 / Dart 3.14（Windows 桌面为主，兼顾 macOS / Linux / Android）· Genkit Dart（Agent 运行时）· A2UI + `genui`（动态 UI）· Riverpod · go_router · drift/duckdb · fl_chart · dio。
- **AI 通道**：DeepSeek（OpenAI 兼容，主模型，`deepseek-chat`）＋ JEV / TypeSafe System One（**裁判**，非生成者，`jev-1.14.0`）。
- **数据**：默认 `data/samples/` 的 **SYNTHETIC 仿真数据**（**仅供测试与离线回归，任何界面不得将其呈现为真实数据**）；桌面端内置可写增量投递箱 `data/inbox/`；真实抓取数据落本地 PIT 时点库。
- **红线**：**绝对禁止内嵌来源数据、禁止为任何来源写 mock/假数据**。拿不到就显式标注「需授权 / 不可达」，界面永不出现伪造数值。详见 [docs/00-设计基线.md §4](docs/00-设计基线.md)。
- **当前阶段**：**设计期**。本文档描述的目录与命令中，带 🧪 的部分尚未落地。

---

## 2. 仓库结构与入口

| 路径 | 作用 | 常见改动 |
|---|---|---|
| `lib/app/` | 应用骨架：路由、主题、启动流程、窗口/托盘 | 路由、主题、启动策略 |
| `lib/core/` | 基础设施：配置、密钥、错误、日志、结果类型 | 加基础设施能力 |
| `lib/features/` | 按业务能力分包（决策 / 研判 / 探索 / 数据源 / 设置 / 时间线…） | 新业务能力 |
| `lib/agents/` | 多智能体：角色定义、编排、工具、证据黑板、核验、门卫 | prompt、角色、编排 |
| `lib/data/` | 数据层：PIT 存储、采集器、Inbox 清洗、特征、信号、知识库 | 数据口径、采集策略 |
| `lib/ui/` | 设计系统：token、主题、共享组件、A2UI catalog | 视觉、组件 |
| `lib/genui/` | A2UI 协议适配：消息解析、catalog 注册、渲染适配、动作回传 | 动态 UI 能力 |
| `lib/experiments/` | 实验：消融矩阵、回测、评估指标、报告生成 | 论文实验 |
| `test/` | 单元测试（镜像 `lib/` 结构） | 行为变更必带测试 |
| `integration_test/` | 集成/端到端测试（Windows 桌面 + Android） | 关键链路 |
| `assets/` | 静态资源（字体、图标、示例 schema） | 资源 |
| `configs/` | 运行配置（**JSON**，非 YAML） | 改行为优先改配置 |
| `docs/` | 设计文档、ADR、研究笔记 | 文档与链接 |
| `data/` | 数据集：samples（SYNTHETIC）/ knowledge / inbox（运行时可写） | 数据口径 |
| `ref/` | **研究参考材料**（论文、原始材料、旧项目语义清单）——只读，不参与构建 | 查阅 |
| `secrets/` | 凭证（**gitignored**，DPAPI 优先） | 换密钥 |
| `tools/` | Dart 工具脚本、数据准备、报告渲染 | 批处理 |
| `packaging/` | Windows 安装器（Inno Setup）、Android 签名与构建脚本 | 打包 |
| `.references/` `.superpowers/` | 工具产物，**不入库** | — |

> **注意**：`ref/` 与 `docs/research/` 是**只读研究材料**，不得在实现过程中修改其内容；需要补充结论时写进 `docs/`。

---

## 3. 角色与写入范围

| 角色 | 默认可写 | 默认只读 |
|---|---|---|
| Lead / 集成者 | 全部（集成收尾） | — |
| 产品/研究 agent | `docs/`、`configs/`、`tools/` | `lib/`、`ref/` |
| 前端/UI agent | `lib/app/`、`lib/features/`、`lib/ui/`、`lib/genui/`、`assets/` | `lib/agents/`、`lib/data/` |
| Agent/编排 agent | `lib/agents/`、`lib/genui/` | `lib/ui/`、`lib/data/` |
| 数据/抓取 agent | `lib/data/`、`lib/experiments/` | `lib/ui/`、`ref/` |
| 工程化 agent | `.github/`、`pubspec.yaml`、`.gitignore`、`.editorconfig`、`.metadata`、`packaging/`、`tools/` | 其它 |
| 文档 agent | `README.md`、`docs/`、`CONTRIBUTING.md`、`CHANGELOG.md`、`AGENTS.md` | `lib/`、`test/` |

**规则**：以任务卡 `write_scopes` 为准；写集不相交；同一文件同一时间只有一个 owner；越界修改必须先经 Lead 同意。

---

## 4. 任务看板用法（必须遵守）

1. `team_task_list()`：看任务、状态、owner、revision、`blocked_by`、`writeScopeWarnings`。
2. `team_task_get(task_id)`：读全文（目标、必做项、写入范围、验收标准）。
3. `team_task_update(task_id, expected_revision=<当前 revision>, action="claim")`：认领。revision 是 CAS 前置条件，失败就重新 get 再试。
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
- **不提交**：`data/inbox/`、`data/raw/`、`data/custom/`、`data/processed/`、本地 PIT 库、`artifacts/`、`secrets/`、`.env`、`ref/` 中的原始材料副本、临时脚本。
- **不得在 `lib/` 任何位置出现硬编码的示例来源数值**（行情点位、新闻正文、遥感像元、情绪分）。测试夹具必须显式标注 `synthetic` 且不得被产品代码读取。
- 修改 `lib/` 后运行 `dart format` + `flutter analyze` + 相关 `flutter test`。

---

## 6. 验证命令

```powershell
# 格式化
dart format lib test integration_test

# 静态分析（零容忍：error 与 warning 都要清零）
flutter analyze

# 单元测试
flutter test

# 集成测试（需要桌面设备）
flutter test integration_test -d windows

# 构建验证
flutter build windows --release
flutter build apk --release          # Android

# 数据与配置校验（工具脚本）
dart run tools/validate_sources.dart   # 来源台账与可达性配置自检
dart run tools/validate_contract.dart  # 前后端契约/Schema 一致性自检

# 文档断链（扫描全部 *.md 相对链接，0 处断链）
```

判定标准：`flutter analyze` 零 error 零 warning；`flutter test` 全绿；构建通过；无新增运行时异常。

---

## 7. 分支、提交与版本

- 主分支 `main`；工作在 `feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>` 分支。
- 由 Lead 统一 `git add/commit`；提交信息用 Conventional Commits（`feat:`/`fix:`/`docs:`/`test:`/`chore:`），一次提交聚焦一件事。
- 不直接 push 到 `main`、不改写历史、不使用 `git add -A` 夹带无关文件。
- 行为/命令/配置变更 → 同步 README 与 `docs/`；用户可见变更 → [CHANGELOG.md](CHANGELOG.md)。
- 实验结论：默认 SYNTHETIC；pilot 与正式结果分开；**不显著不得写成显著**；**仿真结论不得表述为真实市场结论**。

---

## 8. 禁止事项

- 伪造数据、结果或测试输出；把仿真结论表述为真实市场结论。
- **为任何数据来源写 mock/假数据**；在无真实来源时用占位数值填充界面。
- 提交密钥、原始数据、大文件、临时脚本。
- 未经许可修改他人范围文件、执行 git 写操作或删除他人产物。
- 在没有证据的情况下引用不存在的文件、截图、命令或数字。
- **在未与 Lead 确认的情况下擅自决定产品设计、交互形态或架构选型**——设计决策一律先落 ADR 或在任务卡里问。

---

## 9. 交付检查清单

- [ ] 任务卡已 claim（revision 正确）并按范围完成
- [ ] 相关测试通过；`flutter analyze` 零告警
- [ ] 命令/配置/链接已实测（可复制执行）
- [ ] `git status` 无意外文件；临时脚本已清理
- [ ] 文档/CHANGELOG 同步（如涉及用户可见变更）
- [ ] 若涉及设计变更：已更新 `docs/00-设计基线.md` 或新增 ADR
- [ ] 已 `complete` 任务并给 Lead 发摘要
