# ADR-2026-10-27 · 智能体执行 Harness 选型

- 状态：**提议（Proposed）** — 已落地进程内默认实现与远程适配器契约；外部执行器待接入
- 决策者：Lead / 架构
- 相关：`src/cbr/harness/`、`configs/harness.yaml`、`src/cbr/orchestration/`

## 1. 背景

系统已具备多智能体协同编排（`cbr.orchestration`），但「**在哪执行**任务」与「**怎么思考**」
耦合在同一进程内。随着实时抓取与 RAG 引入，执行侧出现新需求：

- 长时/有副作用任务（数据抓取、代码执行、多步工具调用）需要隔离、超时、可观测、可恢复；
- 希望在需要时接入成熟的外部执行器，而非重造整套沙箱与权限体系；
- 执行层要对上层暴露**稳定契约**，替换实现不影响 orchestration / API。

候选方向（来自需求方）：**OpenHands 二开** 或 **Python+TS 二开**。

## 2. 决策

**采用「契约先行 + 可替换后端」的 harness 设计：**

1. 定义稳定契约 `AgentHarness` / `TaskSpec` / `RunResult`（`src/cbr/harness/contracts.py`）。
2. 默认后端 `InProcessHarness`：同进程按 `task.kind` 分派，零外部依赖，覆盖单机/演示/测试。
3. 远程后端 `RemoteHarness`：HTTP 适配器，对接外部执行器网关（`POST {base_url}{submit_path}`），
   服务不可达时返回 `ok=false` 而非抛出，保证降级。
4. 通过 `configs/harness.yaml` 切换 `backend`；上层只依赖契约。

**外部执行器选型建议（待定，本 ADR 不锁定）：**

| 方向 | 适配方式 | 优点 | 风险 |
|---|---|---|---|
| OpenHands 二开 | 以 OpenHands 作为运行时，暴露网关；`RemoteHarness` 转发 | 沙箱/工具/多步执行成熟，社区活跃 | 依赖较重；需维护二开分支与版本节奏 |
| Python + TypeScript 二开 | 自建轻量执行器（Python 执行 + TS 前端控制台），按契约暴露 | 可控、贴合本仓库栈（FastAPI + Next.js） | 需自行实现沙箱、超时、权限、可观测 |

> 建议：**先按契约接入，不急于锁定**。当单机任务确需隔离/长时执行时，优先评估 OpenHands 二开；
> 若更看重与现有 `apps/web` + FastAPI 的一致性与可控性，则走 Python+TS 二开。

## 3. 后果

- 正面：执行层可替换、可测试、可降级；orchestration 与执行解耦；接入外部框架不改上层。
- 负面：`RemoteHarness` 的契约需与外部实现对齐（路径、鉴权、错误语义），目前仅为适配器骨架，
  尚未与任何具体外部框架联调。
- 未决：外部执行器的**沙箱与权限模型**、任务级鉴权、结果回写与审计链（与 `verification` 的衔接）。

## 4. 现状

- 已实现：契约、`InProcessHarness`、`RemoteHarness`（含探活与降级）、配置、`build_harness` 工厂、测试。
- 未实现：与 OpenHands / 自建执行器的真实联调；这是后续独立工作项。
