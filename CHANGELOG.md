# CHANGELOG

本文件记录用户可见变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### docs · 论文定稿版式

- `docs/25-paper/paper.pdf`：21 页，三张 TikZ 图（三进程拓扑、记忆检索流水线、评估窗口），
  6 张表；0 overfull、0 undefined reference，正文无手写结果数字。
- 版式：`ctexart` + `fandol`（SC 字形，可移植）、行距 1.38、首行缩进 2 字符、段距 0、
  页眉短标题 + 页码、图表标题统一小一号。
- 修正两处会误导的表述：`partial` 由「是」改为「仅 1.7% 的记录（与角色降级一致）」；
  记忆消融无不一致对时不再渲染出 `p = --`，改为「无不一致对（检验不适用）」。

### fix · 门禁自身的两个缺陷（E9/E10）

- **端到端冒烟常年 skipped**：该步骤要求先构建 collector，一直显示「sidecar 未构建，跳过」，
  缺陷从未暴露。补齐二进制后又发现它依赖手工留下的 `build/kw` 种子库、且未先算 CFSI。
  现改为**自播种真实 PIT 库 + 前置 `cfsi.compute`**，删掉 `build/kw` 从零可跑通。
- **门禁自我污染**：`validate_contract` 的防漂移检查会重跑生成器，但只备份被比对的那一个
  文件；`tools.dart` 被覆盖成未格式化输出，导致**下一次 `dart format` 检查必失败**。
  改为备份/还原全部生成物，跑完 `git status` 干净。
- 结果：`CBR_FULL_GOLDEN=1 bash packaging/verify_all.sh` → **16 通过 / 0 失败 / 0 跳过**，
  且可重复。

### refactor · A2UI 官方控制器迁移 + 工具链事故恢复

- `surface_bridge` 497→243 行：手写 A2UI 解析/patch 状态机删除，改由 `package:genui`
  的 `SurfaceController` 承载；白名单守卫保留并 fail-closed（净删生产代码 601 行）。
- 环境事故：`/home/xrak/.rustup` 元数据损坏（文件在磁盘上消失，`ls`/`cksum` 报 EIO，
  SMART 仍 PASSED），导致任何 `cargo` 子命令启动即 SIGBUS。工具链重装到 `/home/xrak/rt/tc`
  （rustup 自身静默失败，改用手工 tarball + `install.sh`），registry 换到 `/home/xrak/rt/cargo`；
  kernel 全量重编 17m39s 通过。

### feat · v3 三库记忆（ADR-010）与可复现基准控制台

- **kernel 内嵌 LanceDB**：新增 `memory` 模块（`services/kernel/src/memory.rs`），单表 `memory`
  + `store` 判别列（`mi`/`llr`/`hlr`），JSON `payload` 承载库内差异字段；`memory.upsert/search/stats`
  三个 RPC 与契约（6 个 schema + 样例）同步落地。
- **PIT 硬过滤**：检索前 `only_if(available_at <= as_of)`，实测「未来才可得」的记录被排除；
  写入按 `id` 幂等覆盖（`merge_insert`），写后重建索引（否则 FTS 看不到新片段，已加回归测试）。
- **中文全文检索**：FTS 使用内置 ICU 分词（jieba 需要外部词典文件，实测会静默退化）；
  `memory.stats.fts_tokenizer` 如实暴露实际分词器。
- **MMR**：LanceDB Rust 只提供 RRF，MMR 按公式实现（30 行）+ 单测。
- **本地向量化**：`fastembed` + BGE-small-zh-v1.5（512 维，离线），模型缓存到 `<workspace>/models/`；
  初始化失败不伪造，原因写入 `memory.stats.embedding_error`。
- **agents 层解除 Flutter 依赖**：新增 `AssetSource`（文件/资源包两种实现），
  使同一套 R0–R5 编排可在纯 Dart CLI 下跑。
- **终端基准控制台** `apps/desktop/tool/bench_console.dart`：压力/平静配对抽样 + 固定种子，
  流式打印角色/工具/主张/冲突/核验，产物结构对齐 `score_arms.py`。
- **构建回环**：`[profile.dev] opt-level=1, debug=0, incremental=false`；`packaging/preflight.sh`
  与 `packaging/clean_build_leaks.sh` 接入 `verify_all.sh`（首次 296s，增量 6.6s；已释放 786MB 残留）。

### fix · 内核派生序列重算性能（真实缺陷）

- `services/kernel/src/ingest.rs` 的 `recompute_derived` 原本**每行一次 SELECT + 每行一次 INSERT**：
  2615 行 × 4 条派生序列 ≈ 1 万次查询 + 1 万次 WAL fsync，在 NTFS 上退化到 **8 分钟以上**。
- 改为**批量读入内存 + 批量多值 INSERT**（每 512 行一批），`derived_recompute_matches_legacy_values`
  从 **480 秒+ 未跑完 → 60 秒通过**，11230 行数值与旧版逐行一致（容差 1e-9）。

### chore · 构建环境收口

- 统一只维护仓库内 `services/kernel/target/`，弃用 `~/.cache/cbr-kernel-target`（曾累积 48G，
  清理后触发 DuckDB 全量 C++ 重编 8–10 分钟；复用仓库 target 时增量编译仅 **11 秒**）。
- `packaging/{verify_all,e2e_smoke}.sh` 的 kernel 路径统一指向 `services/kernel/target/debug/cbr-kernel`。
- `verify_all.sh` 黄金步骤快/慢分离：默认跑 `dispersion_golden` + `linkage_golden`（各约 60s），
  CFSI 逐日 + 派生重算需 `CBR_FULL_GOLDEN=1`。
- `docs/09` 新增「Rust 构建环境陷阱」与「构建目录约定」两节（磁盘满表现为 `ld signal 7 Bus error`，
  不是 OOM；`GOROOT` 必须与 go 二进制匹配；clang 需匹配版本的 C++ 头；勿并发跑同 target 的 cargo test）。


## [0.1.0] · v1 主体落地

### feat · 研究增强：两个新确定性工具（实证驱动）

- **`dimension_dispersion`**（风险来源结构）：六维压力分极差 + 主导维度 + 阶段判读。真实数据实证：样本外 z>1.0 时 precision **0.6514** / lift **1.7084**，**walk-forward 6/7 年有效**（唯一跨期稳健指标）；与黄金向量逐点一致（2358 行、0 偏差）。
- **`capital_linkage`**（双序列联动性）：滚动 Kendall tau，**变化率口径**（水平口径实测失效：3.4412 vs 1.0501）。单一切分 lift 2.0828，但**逐年 walk-forward 平均仅 0.7288**，2024 后因北向数据停更触发 0 次——已按 `docs/23 §4.5` 与 headline 并列披露。
- 工具注册表三语言（`contracts/tools/tools.json` / Dart / Rust）同步至 **9 个**。

### feat · 实验统计与防自欺

- `lib/experiments/`：扩展窗口 OOS R²、Diebold-Mariano、嵌套 F、Holm、置换检验、Kendall tau-b、bootstrap CI、领先期剖面、增量检验。
- **两条防自欺规则内置**：API 层不提供 A−B 差值背离形状；"有预测力"的判定必须过安慰剂。

### feat · 采集器数据新鲜度

- `sources.health` 新增 `freshness`（fresh/stale/dead/unknown）与每依赖序列的 `latest_available` / `nan_rate`。
- **修复 PIT 泄漏**：无时区发布列此前被当 UTC 解析（等于提前 8 小时可用）。

### feat · 契约与内核

- 黄金向量扩至 4 份；CFSI 与黄金表**逐日严格一致**（L2/L3 换序对 0）；`contracts/README §5.1` 明确分位 tie-break 与三层回归判据。

### chore · 门禁清理

- `cargo clippy -D warnings` 归零（数值代码的 `needless_range_loop` 用局部 `#[allow]` 并注明理由，不硬改迭代器）；`cargo fmt --check` 干净；`dart format` 全仓统一（31 个文件）。
- 补写一直缺失的 `docs/adr/ADR-006`（多语言内核分层）、`ADR-007`（新手岛）、`ADR-008`（CFSI 缺维降级）；`ADR-001` 标记为已修订；`docs/11` 状态转「已采纳」。

### docs

- 新增 `docs/13`（真实基准，A/C 组 blocked 如实标注）、`docs/17`（文本维实证含负结果）、`docs/18`（北向联动性，含 walk-forward 推翻 headline）、`docs/20`（角色分歧与风险结构）、`docs/21`（LLM 通道实测）、`docs/22`（五分钟上手）、`docs/23`（基准协议）、`docs/adr/ADR-009`（研究增强准入标准）。

### 设计期基线（尚未发布任何可运行产物）

#### 新增

- **设计基线**：`docs/00-设计基线.md` —— 记录全部已拍板的技术与产品决策、待定事项与继承语义清单。
- **架构设计**：`docs/01-架构设计.md` —— 纯客户端单进程架构、依赖方向、关键横切机制、风险登记册。
- **功能清单**：`docs/02-功能清单.md` —— F1–F10 共 100+ 条功能，含优先级、验收标准与 M0–M7 里程碑。
- **多智能体架构**：`docs/03-多智能体架构.md` —— 四角色、R0–R5 编排、证据链、冲突三分类、HITL、成本预算。
- **动态 UI 与 Agent-Native**：`docs/04-动态UI与Agent-Native设计.md` —— A2UI 接入、catalog 安全边界、动作模型。
- **数据抓取与时点设计**：`docs/05-数据抓取与时点设计.md` —— 来源台账、可达性探测、采集器、Inbox 清洗、PIT 纪律。
- **设计系统与美学规范**：`docs/06-设计系统与美学规范.md` —— 语义色板、排版尺度、组件清单、动效与深色模式。
- **交互与响应式规范**：`docs/07-交互与响应式规范.md` —— 断点矩阵、自适应、触控、键盘无障碍、状态完备性。
- **文案标准与术语表**：`docs/08-文案标准与术语表.md` —— 跨境金融风险研究的术语真源与文案模板。
- **工程化规范**：`docs/09-工程化规范.md` —— 目录、依赖分层、测试、CI、发布、配置与安全。
- **研究域设计**：`docs/10-研究域设计/` —— R1 MediaTone（媒体基调→价格）、R2 多模态情感与跨模态对齐、R3 时空分析（夜光/遥感）、R4 多智能体与 Agent-Native。
- **架构决策记录**：`docs/adr/` —— ADR-001 纯客户端单进程 / ADR-002 A2UI 替代 SDUI / ADR-003 Genkit Dart / ADR-004 数据抓取原则 / ADR-005 目标平台与分发。
- **旧系统语义清单**：`docs/research/旧系统语义清单-迁移依据.md` —— 62 项迁移合同，标注每项的旧实现锚点与处理方式（继承 / 重写 / 废弃）。

#### 迁移进来的材料（本地，不入库）

- `ref/` —— 三份研究材料（MediaTone / 技术工具 / 团队科研资源）+ 数据来源汇总表 Excel + 参考文献库。
  - **2026-11-25：三份材料与 Excel 已从桌面迁入本仓库，桌面原件删除。** 迁移前逐文件 SHA256 校验（60/60 一致，缺失 0），确认 `ref/` 为严格超集后才删除。
  - **去重**：22 组 / 25 份内容完全相同的文件改为硬链接，逻辑 670.72 MB → 实际 594.04 MB（释放 76.68 MB），**目录与文件名零变化**（`文献指标整理.xlsx` 的 M038/M039 是同一篇论文的两个编号条目，删文件会断索引）。明细见 `ref/_去重清单.md`。
- `data/samples/`、`data/knowledge/`、`data/judgment/` —— 旧项目的 SYNTHETIC 夹具、知识语料与 JEV 判定种子集。`data/samples` **入库**（保证新克隆即有测试夹具；待生成器就位后可改）。
- `configs/` —— 旧项目的 23 份 YAML 配置（来源台账、角色、工具、情景、提示词、消融矩阵），作为新 JSON 配置的对照参考。
- `ref/contracts/` —— 旧项目的 `schemas.py` 与 `contracts.py`，作为领域契约的参考。

### 决策要点

- 采用 **Flutter 3.50 / Dart 3.14**，目标 **Windows 桌面（主）+ macOS + Linux + Android**，不含 iOS。
- 采用 **纯客户端单进程**：无中央服务器、无 BFF、无 Python，一个安装包 + 一个 API 密钥即用。
- 动态 UI 采用 **A2UI + Flutter 官方 `genui`**，**废弃**旧版 SDUI 与自研 `dashboard-kit`。
- 多智能体运行时采用 **Google Genkit for Dart**。
- 数据抓取遵循 **来源台账驱动、绝不内嵌、绝不 mock**：35 个登记来源按「公开可取 / 持牌需授权 / 不可达显式标注」三档处理。
- 界面**纯中文**；产品名沿用 **CBR-MAW**。
