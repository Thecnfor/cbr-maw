# CBR-MAW（`X-AlertAgent` v3.0）

**跨境金融风险多模态多智能体协同预警研究工作台**

> 一个安装包 + 一个默认兼容 API 密钥即可开箱即用。没有中央服务器，没有 BFF，不需要部署任何后端。

---

## 这是什么

CBR-MAW 是一个面向跨境金融风险研究的**纯客户端本地优先**工作台：三大研究主体（**监管智能体 / 机构智能体 / 投资者智能体**）在同一份多模态风险信号与时点知识库上运行 **`X-AlertAgent` 外环认知闭环 × `R0–R5` 内环可审计协同核验**，通过双路径测度、冲突仲裁、JEV 裁判语义核验与全链路审计轨迹，交付可逐条回溯到原文与工具计算结果的研判结论。

界面与动态分析面板采用 **A2UI 协议 + Flutter 官方 `genui`** 渲染，由本地 Agent 在对话流中按白名单组件目录现场生成。

---

## 当前状态与演进路线

- **v1 主体已落地**：24 方法跨语言契约（`contracts/` `1.0.0`）、9 工具注册表、4 份黄金向量、Flutter 桌面端、Go `collector`（12 包测试绿）、Rust `kernel`（43 单测 + 3 黄金向量测试全绿）、真实 `daily_series.csv` 入库与 JEV 裁判通道实测通过（DeepSeek 生成侧待换新密钥复验）。
- **v3.0 / `X-AlertAgent` 架构已升级拍板**：确立外环认知闭环（`MI/LLR/HLR` 记忆 + 浅深双层反思）、Rust 内置 DuckDB + 嵌入式 LanceDB 双引擎、桌面三端收敛（Windows 原生 MSVC 主交付 + Linux 开发验证 + macOS 可编译）、激进现成库路线与计算插件槽。
- **下一步**：先按 [v1 收口清单](docs/12-v1架构与工程收口清单.md) 清零安全/版本/现成库/门禁技术债（v1.5），再推进 v2（`genui` 全量、LanceDB 三库记忆与反思、时空内核、新手岛）与 v3（5 模态完整归并、双边媒体基调三渠道、计算实验沙盒与发布）。

> 实证披露：当前公开数据中唯一跨期稳健指标为 `dimension_dispersion`（6/7 年有效、lift 1.708×），详细边界与 G1–G4 准入标准见 [docs/13](docs/13-基准测试报告.md) 与 [ADR-009](docs/adr/ADR-009-研究增强准入标准与当前裁决.md)。

---

## 三进程架构与技术栈

```
CBR-MAW.exe (Flutter 3.50 / Dart 3.14 · 桌面三端)
   ├─ UI / A2UI / 状态 / 密钥：design_system + a2ui_catalog + genui + flutter_riverpod + flutter_secure_storage
   ├─ 编排 / 门卫 / 槽位路由：Genkit 1.x + X-AlertAgent×R0–R5 + JEV (dio)
   ├─ stdio JSON-RPC 2.0 ──► collector.exe (Go)   ← 35源台账/抓取/Inbox清洗/4条铁律/自更新
   └─ stdio JSON-RPC 2.0 ──► kernel.exe (Rust)    ← DuckDB + 嵌入式 LanceDB + 确定性工具 + 黄金哈希 + [可选计算插件槽]
```

---

## 仓库目录（多语言 Monorepo）

```
apps/desktop/        Flutter 桌面主应用（Dart pub workspace 成员）
packages/            contracts_dart（契约生成） / design_system（唯一UI真源） / a2ui_catalog（A2UI白名单）
services/            collector（Go 采集与清洗 sidecar） / kernel（Rust DuckDB+LanceDB 内核 sidecar）
contracts/           跨语言 JSON Schema、样例、工具注册表、黄金向量与契约版本
configs/             JSON 运行配置、JSON Schema 与唯一 Prompt 真源（configs/prompts/）
data/                samples（测试夹具）/ knowledge / tutorial（v2）/ inbox（运行时可写）
docs/                00–13 设计与基准文档、ADR（001–011）、research/（只读）
tools/               validate_contract / check_layers / check_version / bench
packaging/           verify_all / build / Windows Inno Setup 脚本
ref/                 只读研究材料（不入库、不参与构建）
```

---

## 三条不可让步的线

1. **绝不内嵌来源数据，绝不为任何来源写 mock**：拿不到即显式标注五态，永不出现伪造数值。
2. **零 Mock 严格模式**：模型不可用必须显式失败并引导设置；禁止规则模板冒充模型结论。
3. **结论必须可溯源**：Claim 强制绑定证据，工具重算覆盖 LLM 数值，四级 PIT 强制 `available_at <= as_of`，所有新研究指标须过 G1–G4 检验。

---

## 快速导航与验证

- 产品边界与基线：[docs/00-设计基线.md](docs/00-设计基线.md)
- 架构设计（`X-AlertAgent` v3.0）：[docs/01-架构设计.md](docs/01-架构设计.md)
- 工程化规范与门禁：[docs/09-工程化规范.md](docs/09-工程化规范.md)
- 实施路线与契约：[docs/11-实施设计.md](docs/11-实施设计.md)
- v1 收口整改台账：[docs/12-v1架构与工程收口清单.md](docs/12-v1架构与工程收口清单.md)
- 协作协议与贡献指南：[AGENTS.md](AGENTS.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

运行全量门禁：

```bash
bash packaging/verify_all.sh
```
