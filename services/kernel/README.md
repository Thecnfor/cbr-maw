# services/kernel · Rust 内核 sidecar

CBR-MAW 的数值与本地库内核。**单文件可执行体 + NDJSON over stdio**，无本地端口、
无外部服务依赖（DuckDB 静态链接 bundled）。契约唯一真源见 [`contracts/README.md`](../../contracts/README.md)。

- 传输：stdin/stdout，每行一个 JSON-RPC 2.0 消息；**stdout 只出协议消息**，日志写 stderr（JSONL）。
- 数据库：DuckDB（`duckdb` crate 的 `bundled` 特性，静态链接）。
- 红线：不伪造数据；缺失 → 显式失败（`E_DATA_MISSING`），**绝不填 0 或均值**。

---

## 1. 启动

```bash
cd services/kernel
cargo build --release
./target/release/cbr-kernel \
  --workspace   /path/to/workspaces/default.duckdb \
  --data-home   /path/to/LOCALAPPDATA/CBR-MAW \
  --resource-home /path/to/install-dir \
  --log-level   info
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--workspace` | 否 | DuckDB 文件路径；目录不存在会自动创建。未给时需由 `initialize` 提供 |
| `--data-home` | 否 | 可写根（日志、traces、用户配置覆盖） |
| `--resource-home` | 否 | 只读资源根；用于读取 `data/samples/series_catalog.json` |
| `--log-level` | 否 | `error` / `warn` / `info` / `debug`（默认 `info`） |

也支持 `--flag=value` 写法。所有参数均可由 `initialize` 的 `params` 覆盖。

### 手工试跑

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"contract_version":"1.0.0","client_version":"0.1.0","workspace":"/tmp/ws.duckdb","data_home":"/tmp","resource_home":"'$PWD'/../.."}}' \
  '{"jsonrpc":"2.0","id":"2","method":"ping","params":{}}' \
  | ./target/release/cbr-kernel --workspace /tmp/ws.duckdb
```

### 生命周期与错误

- 握手前只接受 `initialize` / `ping` / `shutdown` / `contract.capabilities`，其余返回 `E_NOT_INITIALIZED`（-32008）。
- 契约版本不匹配 → `E_CONTRACT_MISMATCH`（-32005），**不静默降级**。
- 错误对象结构：`{"code", "message", "data": {"kind", "retryable", "detail": {"reason", ...}}}`。
- `shutdown` 返回 `{"stopped": true}` 后进程退出。

---

## 2. 方法一览

17 个方法（`initialize.result.capabilities` 会原样列出）。

| 方法 | 参数 | 返回 |
|---|---|---|
| `initialize` | `contract_version` `client_version` `workspace` `data_home` `resource_home` `capabilities?` | `sidecar` `version` `contract_version` `schema_version` `capabilities` |
| `shutdown` | `{}` | `{stopped}` |
| `ping` | `{}` | `{pong, server_time}` |
| `db.query` | `view` `filters?` `as_of` `limit?` | `{columns, rows, as_of, truncated}` |
| `db.write` | `table` `rows` `idempotency_key` | `{written, idempotency_key}` |
| `pit.ingest` | `source` `path` `declared?` `idempotency_key` | `{series[], derived_recomputed[], coverage_gate}` |
| `kb.index` | `corpus_dir` `force?` | `{documents, chunks, index_version}` |
| `kb.search` | `query` `top_k?` `filters?` | `{hits[]}` |
| `workspace.info` | `{}` | `{path, size_bytes, schema_version, series_count, obs_count, last_ingest_at}` |
| `workspace.migrate` | `target_version` | `{from, to}` |
| `features.build` | `series_ids[]` `as_of` | `{built, feature_ids[], missing_series[]}` |
| `signal.compute` | `as_of` | `{signal_id, value, dims, missing_dims, limitations, ...}` |
| `cfsi.compute` | `as_of` | `{cfsi, level, tau, dims, missing_dims, limitations, provenance}` |
| `tools.invoke` | `tool` `params` `idempotency_key` | `{evidence}` |
| `kernel.hash` | `payload` `kind` | `{hash}` |
| `contract.capabilities`（扩展） | `{}` | 同 `initialize.result`（无需握手） |
| `tools.describe`（扩展） | `{}` | 七工具元信息与默认参数 |

### 2.1 `db.query` — 具名视图 + 参数化（**不接受任意 SQL**）

白名单视图（`db.query` 的 `view` 只能取这些值）：

| 视图 | 时点列（内核强制注入） | 可用过滤字段 |
|---|---|---|
| `market_daily` | `release_time` | `series_id` `start` `end` |
| `pit_observations` | `release_time` | `series_id` `start` `end` |
| `macro_monthly` | `release_time` | `series_id` `start` `end` |
| `documents` | `publish_time` | `source` `doc_id` `start` `end` |
| `data_cards` / `series_catalog` | — | `series_id` `domain`（`series_catalog` 仅 `series_id`） |
| `signals` | `as_of` | `signal_id` `level` `start` `end` |
| `cfsi_history` | `as_of` | `level` `start` `end` |
| `ingest_batches` | `created_at` | `source` `batch_id` `start` `end` |
| `audit_events` | `ts` | `event_type` `role` `tool_name` `start` `end` |

- `as_of` 一律由内核拼进 `WHERE`（`release_time <= as_of 23:59:59`），**Dart 无法绕过**。
- 未知视图或未知过滤字段 → `E_INVALID_PARAMS`，附 `allowed` 清单。
- `limit` 上限 100000；多取一行判定 `truncated`。

### 2.2 `db.write` — 只允许三张表

`pit_observations`、`documents`、`audit_events`。其余表 → `E_PERMISSION_DENIED`（工具未执行）。
`pit_observations` 行缺 `value` 时**跳过该行**（缺失 ≠ 零值），不写 0。
同一 `idempotency_key` 重放返回首次结果，不重复写。

### 2.3 `pit.ingest` — 中间文件入库

- 输入：CSV（带表头）或 NDJSON（每行一个对象），字段 `series_id, obs_date, value, release_time?, source?, unit?`。
- `release_time` 推导（`docs/05-数据抓取与时点设计.md` §6.1/6.2）：
  - 有显式 `release_time` 列 → 逐行采用；
  - 否则按序列目录保守推导：境内日频 `obs_date 18:00 +08:00`；隔夜海外（VIX/SP500/US10Y/DXY）`obs_date+1 09:00`；月频 `obs_date+max(lag,10) 10:00`。
  - `declared` 可覆盖 `release_lag_days` / `publish_hour` / `publish_minute` / `tz_offset`。
- 派生序列（`term_spread` / `cn_us_spread` / `cnh_cny_gap` / `cgb_index`）**拒绝直接入库**（`E_INVALID_PARAMS`），只能写输入序列。
- 写入后**全量重算**四条派生序列，`release_time` 取两输入的较大者；只写新行或值变化 >1e-9 的行。
- 覆盖率守门：`coverage_gate.passed=false` 时**拒绝切换数据集**，`reason` 说明原因。

### 2.4 `cfsi.compute` — 六维压力指数

口径对齐旧版 `data/labels.py::build_stress_labels('stress_pca_q90')`：

1. 子指标方向统一 → 训练期 winsorize（1%/99%，边界冻结）→ 滚动经验分位（窗口 1250，min 252）；
2. 维度分位 = 维度内子指标分位等权（有效成员 ≥ `ceil(n/2)`）；
3. 训练期 PCA 第一主成分（载荷冻结，方向对齐 equity 为正）→ 训练期经验 CDF → ×100；
4. τ = 训练期 CFSI 的 q90；等级：`critical`≥q99、`high`≥τ、`medium`≥q75、否则 `low`。

**缺维纪律**：缺席维度不参与计算、不填 0/均值；`missing_dims` 与 `limitations` 必填；
缺维时 τ **不冻结**（按可用维度重新估计），`provenance.tau_source` 标注
`reestimated_available_dims`。可用维度 <2 → `E_DATA_MISSING`。

黄金向量：`contracts/golden-vectors/cfsi_stress_pca_q90_reference.json`（2902 行 × 7 字段，容差 1e-8），
由 `tests/golden.rs` 逐点比对。

### 2.5 `signal.compute`

把 CFSI 六维映射为共享风险信号（`model_version = cfsi-deterministic-v1`）。
**这是确定性压力分位映射，不是训练出的多模态模型概率** —— `limitations` 里明写，
需要模型结论请用 `forecast` 工具读取 P1 产物。结果写入 `signals` 表并附 `evidence_id`。

### 2.6 `kernel.hash` — 与旧版 Python 逐字节一致

```jsonc
{"payload": {"tool":"risk_measure","version":"1.0.0","as_of":"2026-06-30","params":{"lookback":252}},
 "kind": "inputs_hash"}
```

| kind | 输入 | 输出 |
|---|---|---|
| `inputs_hash` | `payload = {tool, version, as_of, params}` | `sha256(canonical_json(payload))` |
| `evidence_id` | `payload = {tool, version, inputs_hash}` | `"ev_" + sha256(canonical_json(payload))[:16]` |
| `evidence_hash` | 任意证据载荷 | `sha256(canonical_json(payload))` |

规范化序列化复刻 Python：
`json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)` +
`repr(float)` 兼容浮点字面量（`1e16 → 1e+16`、`1e-5 → 1e-05`、`-0.0 → -0.0`），
NaN/Inf → `null`。实现见 `src/canon.rs`，黄金向量见 `contracts/golden-vectors/hash_vectors.json`。

---

## 3. 七工具（`tools.invoke`）

纯函数、确定性、**不调用 LLM**。数据不足时显式失败（`E_DATA_MISSING`），不返回编造数值。
参数默认值见 `contracts/tools/*.params.schema.json`（`null` 视为未提供）。

| 工具 | 主要参数 | 主值 `unit` |
|---|---|---|
| `risk_measure` | `series_id` `lookback` `annualization` `confidence` `horizon_days` `values_are` `min_observations` | `loss_ratio`（历史 VaR） |
| `systemic_risk` | `market_series_id` `asset_series_id` `series_ids[]` `tail_q` `dy_window` `dy_lag` `dy_horizon` | `ratio`（DY 溢出指数 0–1） |
| `capital_flow` | `inflow/outflow/ah_premium_series_id` `lookback` `z_window` `anomaly_z` `top_n` `flow_unit` | `z` |
| `funding_cost` | `spread_series_id` `lookback` `momentum_window` `spread_unit` `cost_jump_bp` `cost_medium_bp` `refinancing_horizon_days` | `bp`（成本变化） |
| `scenario` | `target/us_equity/fx/spread_series_id` `us_equity_drop_pct` `fx_depreciation_pct` `spread_widening_bp` `method` `analog_k` | `ratio` |
| `forecast` | `horizon` `include_drivers` | `probability` |
| `knowledge_search` | `query` `top_k` `tags[]` | 无主值（返回引文） |

返回统一 Evidence：

```jsonc
{"evidence": {"evidence_id":"ev_…","tool":"risk_measure","version":"1.0.0",
  "inputs_hash":"<64 hex>","hash":"<64 hex>","value":0.0231,"unit":"loss_ratio",
  "as_of":"2026-11-25","params":{…},   // 合并默认值后的规范化参数
  "title":"…","summary":"…","data":{…}}}
```

- 相同 `(tool, version, as_of, params)` → 相同 `inputs_hash` / `evidence_id`。
- 相同输入数据 → 相同 `hash`（证据载荷哈希）。
- 权限与审计在 Dart 门卫层（见 `docs/11-实施设计.md` §5.5）；越权调用**不会**到达内核。

### 知识库（`kb.index` / `kb.search` / `knowledge_search`）

- 语料：`corpus_dir` 下 `.md`（YAML front matter）与 `.jsonl`（每行一篇，正文键 `text`/`content`）。
  必需元数据：`title` `source` `publish_time`；可选 `doc_id` `url` `tags` `section`。
- 切块：按句子边界，目标 240 字符、重叠 48；`index_text = title\nsection\ntags\n正文`。
- 检索：BM25（k1=1.5, b=0.75）+ 256 维哈希向量（signed hashing，L2 归一化）+ 加权 RRF（k=60，权重 0.5/0.5）。
- 时点：`published_at <= as_of`；`knowledge_search` 工具再校验一次（双保险）。
- 索引持久化在 workspace 的 `kb_chunks` / `kb_meta` 表；语料哈希未变且 `force=false` 时跳过重建。

---

## 4. 如何新增一个工具

1. **先改契约**（唯一真源，顺序不能反）：
   - `contracts/tools/tools.json` 增加条目（`tool` / `version` / `risk_level` / `allowed_roles` / `deterministic: true` / `legacy_ref`）；
   - 新增 `contracts/tools/<tool>.params.schema.json`（默认值写进 `default`）；
   - 在 `contracts/examples/<tool>/` 补 request/response/error 三组样例。
2. **Rust 侧实现**：
   - 新建 `src/tools/<tool>.rs`，实现
     `pub fn compute(params: &Map<String, Value>, as_of: &str, source: &dyn DataSource) -> Result<ToolOutput>`；
     只用 `super::history(...)` 读数据（它已做 PIT 双保险），数值走 `crate::numeric`，
     浮点输出用 `rv(...)`（`r` 四舍五入到 10 位）。
   - 数据不足一律 `Err(super::tool_error(...))`，**不要返回 0**。
3. **注册**：
   - `src/tools/mod.rs` 的 `TOOL_REGISTRY` 加 `ToolMeta`；
   - `default_params()` 加该工具的默认参数（与 schema 逐项一致）；
   - `invoke()` 的 `match tool` 加分支。
4. **测试**：在 `src/tools/<tool>.rs` 或 `mod.rs` 加单测——同参数两次调用 `evidence_id` 相同；
   缺数据时返回 `E_DATA_MISSING`；关键数值与旧版 Python 对拍（用 `tests/` 里的黄金向量模式）。
5. **门禁**：`cargo fmt --check && cargo clippy -- -D warnings && cargo test`。
6. Dart 门卫的权限矩阵由 `contracts/tools/tools.json` **生成**，不需要手抄。

> 工具**绝不调用 LLM**。需要模型判断的能力属于 Agent 层（Dart），不属于内核。

---

## 5. 代码地图

| 文件 | 职责 |
|---|---|
| `src/main.rs` | 进程入口：解析启动参数，跑 stdio 循环 |
| `src/lib.rs` | JSON-RPC 分发、`initialize`、`kernel.hash`、工作区数据源适配 |
| `src/canon.rs` | 规范化 JSON + Python `repr(float)` 兼容 + 三级哈希 |
| `src/numeric.rs` | 数值原语（分位、VaR/CVaR、OLS、分位数回归、VAR/GFEVD、正态分位） |
| `src/workspace.rs` | DuckDB schema（v3）、迁移、幂等表、PIT 历史读取 |
| `src/pit.rs` | 序列目录 + `release_time` 推导规则 |
| `src/ingest.rs` | CSV/NDJSON 入库、派生重算、覆盖率守门 |
| `src/db.rs` | 具名视图 + 参数化查询、白名单写入 |
| `src/cfsi.rs` | CFSI 六维引擎（滚动分位 + 训练期 PCA） |
| `src/signal.rs` | CFSI → 共享风险信号 |
| `src/features.rs` | 数值特征构造与持久化 |
| `src/kb.rs` | 语料加载、切块、BM25 + 哈希向量 + RRF |
| `src/tools/` | 七工具实现（`mod.rs` 为注册表与统一 Evidence） |
| `tests/golden.rs` | 黄金向量回归（CFSI 逐日 + 派生序列逐行） |

## 6. 验证

```bash
cd services/kernel
cargo fmt --check
cargo clippy -- -D warnings
cargo test
```

黄金向量测试需要 `data/seed/pit_real_obs.jsonl`（真实 PIT 库导出）。缺失时该测试**跳过**并打印提示，
不会伪造数据通过。
