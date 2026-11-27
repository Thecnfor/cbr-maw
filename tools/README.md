# tools/ · 仓库级校验与基准脚本

全部脚本从**仓库根**用 `dart run tools/<script>.dart` 运行。`tools/` 是一个独立的
Dart 包（`tools/pubspec.yaml`），依赖 `crypto`、`json_schema`、`path`，以及
workspace 内的 `packages/contracts_dart`（走相对 path 依赖，不发布）。

> 所有脚本只读仓库内容；唯一的写操作是 `gen_golden_vectors.dart --write` 与
> `bench/run.dart --out <path>`，两者都必须显式传参。

## 退出码约定

| 码 | 含义 |
|---:|---|
| `0` | 通过（允许带 WARN 的降级，例如单一真源缺失但各实现一致） |
| `1` | **有违规**：契约不一致、依赖方向越界、版本不一致、黄金向量偏差 |
| `2` | **环境/前置缺失**：找不到仓库根、缺少 `contracts/`、旧 Python 不可用等 |
| `3` | 基准 harness 自检失败（检测器本身失效） |

CI 只认 `0`；`1` 与 `2` 都必须修复后重跑，不允许跳过。

## 脚本

### `validate_contract.dart`

校验 `contracts/` 自身一致性，四件事：

1. **schema 元校验**：每个 `contracts/**/*.schema.json` 必须是合法 draft 2020-12
   schema（`$schema` 必须是 2020-12 URI，`$id` 必须等于仓库相对路径）；
   外部 `$ref` 一律判失败（契约内只允许 `#/` 本地引用，CI 不依赖网络）。
2. **样例一致**：`contracts/examples/<method>/*.json` 必须与对应 request/response
   schema 一致；每个方法必须同时有 `request` / `response` / `error` 三类样例，
   且样例里的 `method` 与目录名一致。
3. **注册表同源**：`contracts/tools/tools.json` 与 Dart 生成的 `toolRegistry`
   逐条一致（工具名/版本/风险级/角色/参数 schema 引用），且 `params_schema_ref`
   指向的文件真实存在；
4. **版本一致**：`contracts/VERSION` 与 Rust `CONTRACT_VERSION`、Go
   `ContractVersion`、Dart 握手 `contract_version` 三处声明一致。

```bash
dart run tools/validate_contract.dart
```

### `check_layers.dart`

依赖方向检查（docs/09 §3）：

- `lib/core` 不得依赖任何其它 `lib/` 子目录；
- `lib/data` 不得依赖 `agents` / `ui` / `app` / `features`；
- `lib/ui` 不得依赖 `data` / `agents` / `features`；
- `lib/agents` 不得依赖 `features` / `app`；
- 只有 `lib/genui/adapter/` 允许 `import 'package:genui/...'`；
- 只有 `lib/agents/` 允许 `import 'package:genkit/...'`。

```bash
dart run tools/check_layers.dart
```

### `check_version.dart`

单一真源版本一致性（docs/11 §7.3）。真源解析顺序：

1. 根 `VERSION`（docs/11 约定的单一真源）；
2. 缺失时退回 `apps/desktop/pubspec.yaml` 的 `version`，并打印 WARN
   （注意：`packaging/build.sh` 注入的是 `contracts/VERSION`，那是**契约版本**，
   与应用版本是两个概念，本脚本不混用）。

比对：Dart `pubspec.yaml` / Go `service.Version` / Rust `Cargo.toml`；
安装器必须由 `/DAppVersion` 注入，不得把版本写死在 `.iss` 里。

```bash
dart run tools/check_version.dart
```

### `gen_golden_vectors.dart`

黄金向量（`contracts/golden-vectors/hash_vectors.json`）的生成与校验。
**默认是校验，不是覆盖。**

```bash
dart run tools/gen_golden_vectors.dart            # 校验（推荐，CI 用这个）
dart run tools/gen_golden_vectors.dart --write    # 调旧 Python 重新生成，再校验
```

校验三件事：

1. Dart `EvidenceHash` 对每条向量重算 `canonical_json` / `inputs_hash` /
   `evidence_id` / `evidence_hash`，必须与文件逐字节一致；
2. 旧 Python（`cbr.tools.base`，`CBR_LEGACY_SRC` 指向旧项目 `src/`）重算，
   必须与文件一致 —— 这是"与旧版逐字节一致"的真正判据；
3. `contract_version` 与 `contracts/VERSION` 一致。

旧 Python 不可用时脚本**不会**假装通过：它打印环境缺失并以 `2` 退出前，
会先做完 Dart 侧校验（`finish` 按 `1` 报不一致）。若你只想做 Dart 侧回归，
直接看 `packages/contracts_dart/test/` 里的契约测试。

### `bench/run.dart` —— 真实基准 harness

```bash
dart run tools/bench/run.dart                       # 全量（含 JEV 裁判，约 1–2 分钟）
dart run tools/bench/run.dart --skip-jev --skip-b   # 只跑确定性臂（无网络）
dart run tools/bench/run.dart --as-of 2023-12-31 --windows 40,60,90
dart run tools/bench/run.dart --out artifacts/bench/run.json
```

Dart 负责编排与自检，统计在 `bench/analysis/` 的 Python 层（pandas /
scikit-learn / scipy）。参数：`--as-of`（评估截止日）、`--windows`（滚动窗口扫描）、
`--jev-days`（JEV 抽样天数）、`--out`、`--skip-jev`、`--skip-b`。
环境变量：`CBR_PYTHON`、`CBR_PIT_DB`。

数据来源（**全部真实，禁止编造**）：

| 用途 | 来源 | 是否入库 |
|---|---|---|
| 原始观测 | `pit_real.duckdb → series_obs`（60313 行 / 27 序列） | 否 |
| 压力标签 / CFSI | `contracts/golden-vectors/cfsi_stress_pca_q90_reference.json` | 是 |
| 联动参考 / 阈值 | `contracts/golden-vectors/capital_linkage_reference.json` | 是 |
| 离散度参考 | `contracts/golden-vectors/dimension_dispersion_reference.json` | 是 |

DuckDB 不可用时退回 `data/seed/pit_real_obs.jsonl`（同一批观测的导出副本）。

指标（能算的才算，算不了的标 `BLOCKED` 并写原因）：

- `arms.B`：22 个 `pct_*` 滚动经验分位 + HistGradientBoosting（原生 NaN、不插补），
  阈值训练期按 F1 冻结；
- `arms.C` / `arms.D`：确定性工具组合与消融，含 `ablation`（McNemar）与
  `leave_one_out`；
- `singles`：三个工具单测（`capital_linkage` / `dimension_dispersion` / `cfsi_level`），
  含 `walk_forward`、`lead_time`（附零假设期望）、`lead_profile`、`placebo`、`evidence`；
- `label_circularity`：`high_stress := (cfsi>τ)` 与标签同源造成的循环性诊断（含严格未来标签对照）；
- `structure`：`dominant_dim` 命中率（对照随机 1/6）与阶段信号（对照无条件率）；
- `level_vs_returns`：水平 vs 变化率（含置换 p）；
- `freshness`：每个依赖序列最新可用日与 NaN 率。

对照组（`arms`）：

| 臂 | 状态 |
|---|---|
| `A` 纯 LLM 直答 | **blocked**：DeepSeek 401（不得用桩输出冒充） |
| `A_prime_jev` | ok：JEV `choice` 裁判，**不是 A 组** |
| `B` 纯数值模型 | ok |
| `C` 全流程（确定性臂） | ok（不含 LLM 与四角色） |
| `D` 消融 | ok |

`traceability_rate` / `numeric_consistency` / `cross_role_disagreement` 在模型与
编排跑通前一律 `blocked`，**不输出任何占位数字**。

### `bench/analysis/verify.py` —— 回归断言复核

```bash
~/.cache/cbr-venv/bin/python tools/bench/analysis/verify.py artifacts/bench/run.json
```

复核 docs/23 §5 锁定的 31 项断言（工具 precision/recall/lift、逐年 walk-forward、
峰值 h、水平口径失效、数据新鲜度）。退出码 `1` = 实现偏离口径。

### `bench/self_check.dart` —— 指标自检

用**显式 SYNTHETIC** 的小序列证明指标不是空转：

```bash
dart run tools/bench/self_check.dart
```

覆盖：滚动 Kendall tau 与手算一致（并列对计入分母）、时点泄漏检测器能识别
越界窗口且不误报合法窗口、提前量统计对"无信号/全触发/定点触发"给出可区分结果、
precision/recall/lift 在构造数据上等于手算值。退出码 `3` 表示检测器失效。

## 与 CI 的关系

`docs/09 §7` 的门禁对应关系：

| 门禁 | 命令 |
|---|---|
| 契约 | `dart run tools/validate_contract.dart` |
| 层级 | `dart run tools/check_layers.dart` |
| 版本 | `dart run tools/check_version.dart` |
| 黄金向量 | `dart run tools/gen_golden_vectors.dart` |
| 基准自检 | `dart run tools/bench/self_check.dart` |
| 基准回归断言 | `python tools/bench/analysis/verify.py <run.json>` |

一行跑完（CI 可直接用；基准回归需先跑一次 `bench/run.dart --out`）：

```bash
dart run tools/validate_contract.dart \
  && dart run tools/check_layers.dart \
  && dart run tools/check_version.dart \
  && dart run tools/gen_golden_vectors.dart \
  && dart run tools/bench/self_check.dart
```
