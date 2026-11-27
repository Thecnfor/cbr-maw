# CLAUDE.md

This file provides concise guidance to Claude Code when working in this repository.

## 1. 仓库状态与当前阶段

- **v1 主体已落地**（可编译、可测试、真实数据端到端跑通）：24 方法契约（`contracts/` `1.0.0`）、9 工具注册表、4 份黄金向量、Flutter 桌面端、Go `collector`（12 包测试绿）、Rust `kernel`（43 单测 + 3 黄金向量测试全绿）、JEV 裁判联网实测通过。
- **当前架构基线已升级为 CBR-MAW v3.0 / `X-AlertAgent`**（2026-11-27 拍板）：外环 `X-AlertAgent` 跨时点认知闭环 × 内环 `R0–R5` 协同核验、Rust 双嵌入式引擎（DuckDB + LanceDB）、三主体升维与能力槽位路由、桌面三端收敛、激进现成库路线。
- **已知缺口与下一步**：
  - 生成侧改走本地 OpenAI 兼容中继后已跑通（`ANTHROPIC_BASE_URL` + `reasoning_effort: low`）；部分公开序列停更按 [ADR-008](docs/adr/ADR-008-CFSI缺维降级口径.md) 披露 `limitations`；
  - **实测结论（[docs/13 §3.5.1](docs/13-基准测试报告.md)）**：12 配对时点 × 4 臂实跑，`single`/`independent`/`collaborative` 三臂预测向量**逐点一致**——改造前的 R0–R5 协同**没有带来可测量的判别增量**（根因：定级由确定性规则给出、LLM 自评只记录不参与）。**已按此改造**：`decideLevel` 新增「LLM 自评高于确定性定级时上调一级、低于一律不采纳」，并新增 `assessmentSpread`（三主体自评跨度，单模型恒为 0）；ADR-011 三主体离散行动已落地。改造后的复测见 `artifacts/bench/arms_live3.json`；
  - 现行 v1 代码与最新架构/工程规范之间的整改任务已全部立账在 [docs/12-v1架构与工程收口清单.md](docs/12-v1架构与工程收口清单.md)，其中「四维审计确认项」记录了 2026-11-27 审计的已修 10 项 / 待办 10 项。

## 2. 权威文档地图（唯一真源）

| 你要查/改什么 | 去哪 |
|---|---|
| 产品边界、三条不可让步红线、研究域口径、已定/待决总表 | [docs/00-设计基线.md](docs/00-设计基线.md) |
| `X-AlertAgent` × `R0–R5` 架构、三进程/双引擎、能力槽位、Monorepo 分层 | [docs/01-架构设计.md](docs/01-架构设计.md) |
| 功能清单与验收标准（F1–F11） | [docs/02-功能清单.md](docs/02-功能清单.md) |
| 多智能体细节、动态 UI、数据抓取与 PIT、视觉/交互/文案 | [docs/03](docs/03-多智能体架构.md) / [04](docs/04-动态UI与Agent-Native设计.md) / [05](docs/05-数据抓取与时点设计.md) / [06](docs/06-设计系统与美学规范.md) / [07](docs/07-交互与响应式规范.md) / [08](docs/08-文案标准与术语表.md) |
| 多语言工具链、双版本分离、门禁、Windows 原生 MSVC 与 CI 规范 | [docs/09-工程化规范.md](docs/09-工程化规范.md) |
| 里程碑（v1 / v1.5 / v2 / v3）、契约清单、出口标准 | [docs/11-实施设计.md](docs/11-实施设计.md) |
| v1 架构与工程收口整改台账（P0/P1/P2 锚点与验收命令） | [docs/12-v1架构与工程收口清单.md](docs/12-v1架构与工程收口清单.md) |
| 架构决策记录（ADR-001 ~ ADR-011） | [docs/adr/README.md](docs/adr/README.md) |
| 只读研究材料（**严禁修改**） | `ref/`、[docs/research/](docs/research/)、[docs/10-研究域设计/](docs/10-研究域设计/) |

任何架构或技术栈变更**必须先改 ADR / 基线**，再动代码。

## 3. 三条不可让步红线 & 继承口径

1. **绝不内嵌来源数据，绝不为任何来源写 mock**：拿不到即显式标注五态；产品代码禁硬编码行情/新闻/遥感数值；1 组 1028 四条数据清洗铁律（删周六复制行 / 港股通去重 / 停牌禁 `fillna(0)` / `SecurityID` 主键与北向不混频）不可破。
2. **零 Mock 严格模式**：模型不可用必须显式失败并引导到设置页；降级必须同时写入审计 + UI 明示 + 说明原因；禁止规则模板冒充模型结论。
3. **结论必须可溯源**：Claim 强制绑定证据，工具数值重算覆盖 LLM 草稿，四级 PIT 强制 `available_at <= as_of`，三级哈希与旧 Python 浮点序列化逐字节一致；所有新增指标/增强准入产品定级必须过 [ADR-009](docs/adr/ADR-009-研究增强准入标准与当前裁决.md) 的 G1–G4 门槛；仿真与 `SIMULATION` 沙盒必须物理隔离并带水印。

## 4. 常用验证命令（详情见 [docs/09 §7](docs/09-工程化规范.md)）

```bash
# 全量门禁（Linux/macOS；Windows 用对等 PowerShell）
bash packaging/verify_all.sh
```

```powershell
# 分项常用命令
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
```

- 编码与分层规则：严格遵守 [docs/09 §3 & §5](docs/09-工程化规范.md)（零 `dynamic`、外部边界解析即校验、`packages/design_system` 与 `a2ui_catalog` 与 `configs/prompts/` 单一真源、门卫归属 `lib/agents/gate/`、`genui`/`genkit` 边界隔离）。
- 协作纪律（角色写集、任务看板 CAS、由 Lead 统一提交）：遵守 [AGENTS.md](AGENTS.md)。
- `.agents/skills/` 已装 Flutter/Dart/Rust 最佳实践，写对应语言代码前先读 skill。
