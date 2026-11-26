# 贡献指南 · CBR-MAW（多语言 Monorepo）

> 协作约定与写入范围见 [AGENTS.md](AGENTS.md)，工程标准与门禁细节见 [docs/09-工程化规范.md](docs/09-工程化规范.md)，架构决策见 [docs/adr/](docs/adr/README.md)。

---

## 1. 三条不可让步的线

提交任何改动前，请确认没有违反：

1. **绝不内嵌来源数据，绝不为任何来源写 mock**：界面永不出现伪造数值；拿不到即标注「需授权 / 需登录 / 反爬受限 / 不可达 / 已过期」。
2. **零 Mock 严格模式**：模型不可用必须显式失败并引导到设置页，不得用规则模板冒充模型结论。
3. **结论必须可溯源**：Claim 强制绑定证据，数值由工具重算覆盖，所有读取带 `as_of`，四级 PIT 过滤杜绝未来信息泄漏。

---

## 2. 改动类型与所需流程

| 改动类型 | 需要什么 |
|---|---|
| **设计/架构变更**（拓扑、选型、口径、功能边界） | 先改 [docs/00-设计基线.md](docs/00-设计基线.md) 或新增/修订 [ADR](docs/adr/README.md) → 再改代码 |
| 新增/修改功能 | 同步更新 [docs/02-功能清单.md](docs/02-功能清单.md)（含验收标准） |
| 行为/命令/配置变更 | 同步 [README.md](README.md) 与对应 `docs/` 文档 |
| 用户可见变更 | 同步 [CHANGELOG.md](CHANGELOG.md) |
| 依赖新增或升级 | 需说明理由；**引入商业许可组件必须走 ADR** |
| 数据与指标口径变更 | 遵循 [ADR-008](docs/adr/ADR-008-CFSI缺维降级口径.md) 与 [ADR-009](docs/adr/ADR-009-研究增强准入标准与当前裁决.md)，标注 `label_version` 并重跑验证 |

---

## 3. 本地开发与验证

### 前置工具链（桌面三端）

- **Flutter 3.50.x / Dart 3.14.x**（用 **FVM** 固定，`.fvmrc` 已入库）
- **Go 1.27+**（`services/collector`）
- **Rust stable**（`services/kernel`；Windows 主交付面必须使用原生 **MSVC** 工具链）
- **Windows 发布打包还需**：VS2022 Build Tools（C++ 桌面工作负载）+ Inno Setup 6（本代不含 Android/iOS，无需 JDK/Android SDK）

### 常用验证命令（详见 [docs/09 §7](docs/09-工程化规范.md)）

```bash
# 一键全门禁（Linux/macOS；Windows 使用对等 PowerShell 脚本）
bash packaging/verify_all.sh

# 分项检查
dart format --set-exit-if-changed .
flutter analyze
(cd apps/desktop && flutter test)
flutter test packages/design_system packages/a2ui_catalog
dart test packages/contracts_dart
(cd services/kernel && cargo fmt --check && cargo clippy -- -D warnings && cargo test)
(cd services/collector && go vet ./... && go test ./...)
dart run tools/validate_contract.dart
dart run tools/check_layers.dart
dart run tools/check_version.dart

# 桌面端构建（Windows 必须原生 MSVC，禁止 Linux 交叉编译发布包）
(cd apps/desktop && flutter build linux --release)
```

### 凭证配置

```bash
cp .env.example .env
```

或在应用设置页填写（由 `flutter_secure_storage` 走 OS 原生安全存储：Windows DPAPI / macOS Keychain / Linux libsecret）。**严禁提交任何密钥。**

---

## 4. 提交与实验红线

- 分支：`feat/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>`；由 Lead 统一 `git add/commit`（Conventional Commits），不使用 `git add -A`，不直接 push `main`。
- 实验与结论纪律：区分真实工作区外生回放与 `SIMULATION` 沙盒；默认测试/教程合成数据集不得表述为真实市场结论；不显著不得写成显著；所有导出物若含仿真或合成数据**必须携带 `SYNTHETIC` / `SIMULATION` 标记**。
