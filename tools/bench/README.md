# tools/bench · 真实数据基准 harness

**目的**：让"这套东西能洞察到别人洞察不到的"这句话可被证伪。
协议见 [docs/23-基准测试协议.md](../../docs/23-基准测试协议.md)；报告见
[docs/13-基准测试报告.md](../../docs/13-基准测试报告.md)。

**铁律：不编造任何数字。** 跑不通的指标一律标 `BLOCKED` 并写原因；缺真实数据时
显式降级并在 `provenance` 里写明。

## 架构

```
run.dart                     入口：解析参数 → 调 Python → 汇总 → 自检 → 打印
  └─ analysis/arms.py        四组对照 + 强制项（真实 PIT 库）
       ├─ analysis/common.py 数据加载 / 指标 / 显著性 / 安慰剂 / 哈希
       └─ analysis/verify.py 回归断言复核（31 项）
self_check.dart              指标自检（显式 SYNTHETIC 小序列，CI 必跑）
```

Dart 负责编排与自检；统计用现成库（pandas / scikit-learn / scipy），不自己造。

## 运行

```bash
# 全量（含 JEV 裁判；约 1–2 分钟）
dart run tools/bench/run.dart --out artifacts/bench/run.json

# 只跑确定性臂（无网络、无模型）
dart run tools/bench/run.dart --skip-jev --skip-b

# 指定时点与滚动窗口
dart run tools/bench/run.dart --as-of 2023-12-31 --windows 40,60,90

# 回归断言复核（31 项，1e-6 / 1e-3）
~/.cache/cbr-venv/bin/python tools/bench/analysis/verify.py artifacts/bench/run.json

# 指标自检（CI 必跑）
dart run tools/bench/self_check.dart
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--as-of` | 数据末日（2026-10-28） | 样本外评估截止日；超出末日按末日 |
| `--windows` | `40,60,90` | `capital_linkage` 滚动窗口扫描 |
| `--out` | 系统临时文件 | 落盘 JSON（不入库，`artifacts/` 已 gitignore） |
| `--jev-days` | `60` | JEV 裁判抽样天数（无放回随机，种子固定 11） |
| `--skip-jev` / `--skip-b` | 否 | 跳过网络 / 跳过数值模型臂 |

环境变量：`CBR_PYTHON`（默认 `~/.cache/cbr-venv/bin/python`）、
`CBR_PIT_DB`（默认 `/mnt/shared/recently/commorcial/data/pit_real.duckdb`）。

退出码：`0` 跑通且自检通过；`2` 数据/解释器缺失；`3` 自检失败
（安慰剂未回落到 1.0±0.2，或确定性臂缺 walk-forward）。

## 数据

| 用途 | 来源 | 入库 |
|---|---|---|
| 原始观测 | `pit_real.duckdb → series_obs`（60313 行 / 27 序列 / 2015-01-05→2026-10-28） | 否 |
| 压力标签 / CFSI | `contracts/golden-vectors/cfsi_stress_pca_q90_reference.json` | 是 |
| 联动参考 | `contracts/golden-vectors/capital_linkage_reference.json` | 是 |
| 离散度参考 | `contracts/golden-vectors/dimension_dispersion_reference.json` | 是 |

`pit_real_obs.jsonl` 是 duckdb 的导出副本；两者都在时优先用 duckdb。

## 四组对照

| 组 | 实现 | 状态 |
|---|---|---|
| A 纯 LLM 直答 | DeepSeek `/chat/completions` | **blocked**：密钥 401 |
| A′ JEV 裁判 | TypeSafe `POST /v1/systemone`，`choice` 类型 | ok（**不是 A 组**） |
| B 纯数值模型 | 22 个 `pct_*` 滚动分位 + HistGradientBoosting（原生 NaN） | ok |
| C 全流程 | CFSI + `capital_linkage` + `dimension_dispersion` 等权 z 均值 | ok（确定性臂） |
| D 消融 | C 去掉两个新工具 | ok |

**C 不是完整 CBR-MAW**：LLM 生成侧不可用 → 四角色与冲突三分类 BLOCKED。
报告里明写这一点，不允许把确定性臂包装成"多智能体"。

## 指标口径（与 docs/23 一致）

- 正例 `y_20 = max(high_stress[t..t+19])`，**含当日**、尾部 19 行按 0
  （黄金向量定义，不是我们的选择）。
- 单工具阈值用协议冻结值（`capital_linkage` z>0.5、`dimension_dispersion`
  z>1.0），这样 walk-forward 能与 docs/18 §7.1、docs/20 §4 逐位对齐。
- 组合臂（C/D）的阈值在每年之前的数据上按 F1 重选（严格 walk-forward）。
- 缺失 ≠ 零值：组合只对可用分量取均值，覆盖率单独报。
- 安慰剂：打乱评估期信号 500 次，必须回落到 1.0±0.2。

## 本轮发现的方法学问题

`high_stress := (cfsi > τ)`，而 `y_20` 含当日 → `P(y=1 | hs_t=1) = 1.000`。
任何 CFSI 派生信号的高 lift 都含"当日在压力区"的同义成分。`arms.py`
的 `label_circularity` 用严格未来标签（不含当日）做对照，报告 §5.5 有量化。
