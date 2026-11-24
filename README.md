# CBR-MAW

**跨境金融风险多智能体协同预警研究工作台** · Flutter 重写版

> 一个安装包 + 一个 API 密钥即可使用。没有中央服务器，没有 BFF，不需要部署任何后端。

---

## 这是什么

CBR-MAW 是一个面向跨境金融风险研究的**本地优先**工作台：四个研究角色（融资方 / 投资方 / 监管方）在同一份风险信号上给出各自视角的判断，系统负责交叉验证、识别分歧、仲裁冲突、核验证据链，并把整个过程记录成可回看的审计轨迹。

界面上的一切——图表、结论、证据卡、交互面板——由 **Agent 在对话流中现场生成**（A2UI 协议），而不是由服务端推送页面描述。

---

## 当前状态：**设计期**

本仓库目前**只有设计与参考材料，没有可运行的应用**。

| 已完成 | 内容 |
|---|---|
| ✅ 决策基线 | [docs/00-设计基线.md](docs/00-设计基线.md) —— 所有已拍板的技术与产品决策 |
| ✅ 架构设计 | [docs/01-架构设计.md](docs/01-架构设计.md) |
| ✅ 功能清单 | [docs/02-功能清单.md](docs/02-功能清单.md) —— F1–F10 共 100+ 条功能，含优先级与验收标准 |
| ✅ 多智能体架构 | [docs/03-多智能体架构.md](docs/03-多智能体架构.md) |
| ✅ 动态 UI 与 Agent-Native | [docs/04-动态UI与Agent-Native设计.md](docs/04-动态UI与Agent-Native设计.md) |
| ✅ 数据抓取与时点 | [docs/05-数据抓取与时点设计.md](docs/05-数据抓取与时点设计.md) |
| ✅ 设计系统与美学 | [docs/06-设计系统与美学规范.md](docs/06-设计系统与美学规范.md) |
| ✅ 交互与响应式 | [docs/07-交互与响应式规范.md](docs/07-交互与响应式规范.md) |
| ✅ 文案标准与术语表 | [docs/08-文案标准与术语表.md](docs/08-文案标准与术语表.md) |
| ✅ 工程化规范 | [docs/09-工程化规范.md](docs/09-工程化规范.md) |
| ✅ 研究域设计 | [docs/10-研究域设计/](docs/10-研究域设计/) —— R1 MediaTone / R2 多模态 / R3 时空 / R4 Agent-Native |
| ✅ 架构决策记录 | [docs/adr/](docs/adr/) —— 5 条 ADR |
| ✅ 旧系统语义清单 | [docs/research/旧系统语义清单-迁移依据.md](docs/research/旧系统语义清单-迁移依据.md) —— 62 项迁移合同 |
| ⬜ 工具链安装 | Flutter SDK / Android SDK / JDK / Inno Setup 尚未安装 |
| ⬜ 工程骨架 | `flutter create` 与 CI 尚未建立 |
| ⬜ 功能实现 | 见 [功能清单附录 B](docs/02-功能清单.md#附录-b--里程碑) 的 M0–M7 |

---

## 技术栈

| 领域 | 选型 |
|---|---|
| 框架 | Flutter 3.50 / Dart 3.14（Windows 桌面为主，兼顾 macOS / Linux / Android） |
| Agent 运行时 | Google Genkit for Dart（`genkit`） |
| 动态 UI | A2UI 协议 + Flutter 官方 `genui` SDK |
| 状态 / 路由 / 网络 | Riverpod · go_router · dio |
| 本地库 / 图表 | DuckDB（或 drift）· fl_chart |
| LLM | DeepSeek（OpenAI 兼容）· JEV / TypeSafe System One（裁判） |

**原则：现成库优先，不自造轮子。** 只有真正没有现成方案的部分（领域证据链语义、PIT 时点纪律、来源台账与清洗规则）才自己实现。

---

## 目录

```
docs/        设计文档、ADR、研究笔记
ref/         只读研究材料（论文、原始材料）—— 不入库
data/        数据集（samples 为 SYNTHETIC 夹具 / knowledge 语料 / inbox 运行时可写）
configs/     运行配置（JSON）
secrets/     凭证（不入库）
tools/       Dart 工具脚本
packaging/   Inno Setup / Android 构建
lib/ test/ integration_test/   ← 待建立
```

---

## 三条不可让步的线

1. **绝不内嵌来源数据，绝不为任何来源写 mock。** 35 个登记来源里有很多是持牌付费终端，拿不到就**显式标注「需授权 / 不可达」**，界面永不出现伪造数值。
2. **零 Mock 严格模式。** 模型不可用时必须失败并引导到设置页，不得用规则模板冒充模型结论。
3. **结论必须可溯源。** 每条 claim 绑定证据，证据可重算（`inputs_hash` / `evidence.hash`），所有读取带 `as_of` 时点，四级过滤杜绝未来信息泄漏。

---

## 凭证配置

```bash
cp .env.example .env      # 填入 DEEPSEEK_API_KEY（必填）与 TYPESAFE_API_KEY（可选）
```

或使用应用内设置页填写（Windows 优先 DPAPI 加密落盘）。

---

## 参与协作

见 [AGENTS.md](AGENTS.md) —— 仓库结构、写入范围、任务看板用法、验证命令、禁止事项。

设计变更请先更新 [设计基线](docs/00-设计基线.md) 或新增 [ADR](docs/adr/README.md)。

---

## 与旧版的关系

旧版（CBR-MAW v2.0.0，Python FastAPI + Next.js/SDUI）保留在 `D:\recently\commorcial`，作为**语义参考**而非迁移源。Flutter 版**不迁移 Python 代码**，只迁移其领域语义——完整清单见 [旧系统语义清单](docs/research/旧系统语义清单-迁移依据.md)。

旧版中最容易被「重写成通用 Agent 框架」时丢掉的六件事：

1. Claim→Evidence 的强制绑定与确定性回填
2. 三级 PIT 时点纪律
3. 工具可重算哈希
4. 偏好差异不算错误的善意冲突分类
5. JEV 门卫的诚实降级
6. 时空四视图类比 + 扩展窗口样本外评估
