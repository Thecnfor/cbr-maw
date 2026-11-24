# 贡献指南 · CBR-MAW（Flutter）

> 本仓库当前处于**设计期**。本文说明如何参与，从「提设计」到「写实现」的流程。
> 协作约定见 [AGENTS.md](AGENTS.md)，架构决策见 [docs/adr/](docs/adr/README.md)。

---

## 1. 三条不可让步的线

在提交任何改动前，请确认没有违反：

1. **绝不内嵌来源数据，绝不为任何来源写 mock。** 界面永不出现伪造数值；拿不到就标注「需授权 / 不可达」。
2. **零 Mock 严格模式。** 模型不可用必须失败并引导到设置页，不得用规则模板冒充模型结论。
3. **结论必须可溯源。** claim 绑定证据，证据可重算，所有读取带 `as_of`，四级过滤杜绝未来信息泄漏。

---

## 2. 改动类型与所需流程

| 改动类型 | 需要什么 |
|---|---|
| **设计变更**（架构、功能、交互、文案口径） | 先改 [docs/00-设计基线.md](docs/00-设计基线.md) 或新增 [ADR](docs/adr/README.md) → 再改实现 |
| 新增/修改功能 | 同步更新 [docs/02-功能清单.md](docs/02-功能清单.md)（含验收标准） |
| 行为/命令/配置变更 | 同步 README 与 `docs/` |
| 用户可见变更 | 同步 [CHANGELOG.md](CHANGELOG.md) |
| 依赖新增或升级 | 需说明理由；**引入商业许可组件必须走 ADR** |
| 数据口径变更 | 必须说明是否影响已发布结论（`label_version` 等口径变更 = 换实验结论） |

> **设计期特殊约定**：当前任何「我打算这么实现」的讨论都应先落在文档，再落代码。实现与文档不一致时，以文档为准并补改。

---

## 3. 本地开发

### 前置

- Flutter 3.50 / Dart 3.14（推荐用 **FVM**：`.fvmrc` 已入库）
- Windows 端发布还需：Inno Setup 6；Android 端还需：JDK 17 + Android SDK（cmdline-tools / platform-tools / build-tools / platform 34+）

### 常用命令

```powershell
dart format .
flutter analyze
flutter test
flutter test integration_test -d windows
flutter build windows --release
flutter build apk --release
```

详见 [AGENTS.md §6](AGENTS.md) 与 [docs/09-工程化规范.md](docs/09-工程化规范.md)。

### 凭证

```bash
cp .env.example .env
```

或用应用内设置页填写（Windows 优先 DPAPI 加密落盘）。**不要提交任何密钥。**

---

## 4. 提交规范

- 分支：`feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>`
- 提交信息：Conventional Commits（`feat:` / `fix:` / `docs:` / `test:` / `chore:`），一次提交聚焦一件事
- 由 Lead 统一 `git add` / `commit`；不直接 push 到 `main`
- 不使用 `git add -A`；不夹带无关文件

---

## 5. 实验与结论纪律

这是本项目的**学术红线**，写代码与写报告都适用：

- 默认数据集是 **SYNTHETIC 仿真数据**。任何结论都不得把仿真表述为真实市场结论。
- 不显著不得写成显著；必须给区间与检验结果，不只给点估计。
- pilot 结果与正式结果分开报告。
- 导出物若基于仿真数据，**必须携带 SYNTHETIC 标记**。
- 换标签口径（如 `stress_pca_q90` → 其它）= 换实验结论，必须重跑并标注。

---

## 6. 报告问题

发现问题请附：复现步骤、实际行为、期望行为、环境（Flutter/Dart/平台/版本）。
设计层面的分歧请直接改文档提 PR，或在任务卡里提出——**不要在实现里夹带未讨论的设计变更**。
