# contracts/ · 跨语言契约总纲（唯一真源）

> 契约版本见 `VERSION`（语义化）。**任何方法、字段、错误码的变更必须先改这里，再改 schema，再改三语言实现。**
> 契约清单与职责归属见 [docs/11-实施设计.md §10](../docs/11-实施设计.md)。
> 旧版 Python 参考实现：`/mnt/shared/recently/commorcial/src/cbr/`（**只读语义参考，不迁代码**）。

## 1. 传输

- **NDJSON over stdio**：每个子进程一条 stdin/stdout，**一行一个 JSON-RPC 2.0 消息**，UTF-8，不换行内嵌。
- **stdout 严格只出协议消息**；日志一律写 **stderr**，每行一个 JSONL：`{"ts":"...","level":"info","sidecar":"kernel","msg":"..."}`。
- **不使用本地端口**（避免端口冲突与防火墙弹窗）。
- `id` 由客户端生成，单调递增字符串；请求超时后仍可能收到迟到响应，客户端按 `id` 丢弃。

### 启动参数

```
sidecar.exe --workspace <path> --data-home <path> --resource-home <path> --log-level <lvl>
```

- 只读资源根 `--resource-home`：安装目录（`configs/`、`contracts/`、`data/knowledge/corpus`）。
- 可写根 `--data-home`：`workspaces/`、`inbox/`、`traces/`、`logs/`、`secrets/`、`configs/`（用户覆盖）。
- 配置读取顺序：`--data-home/configs/*.json` **覆盖** `--resource-home/configs/*.json`。
- **业务配置不走环境变量**；仅保留 `CBR_HOME` / `CBR_DATA_HOME` 两个路径变量供人工调试。

### 握手

```jsonc
// → collector / kernel
{"jsonrpc":"2.0","id":"1","method":"initialize","params":{
  "contract_version":"1.0.0","client_version":"0.1.0",
  "workspace":"<path>","data_home":"<path>","resource_home":"<path>",
  "capabilities":["sources.list","collect.run", "..."]}}
// ←
{"jsonrpc":"2.0","id":"1","result":{
  "sidecar":"kernel","version":"0.1.0","contract_version":"1.0.0","schema_version":3,
  "capabilities":["db.query","tools.invoke", "..."]}}
```

- 契约版本或 schema 版本不匹配 → **显式失败**（`E_CONTRACT_MISMATCH`），不静默降级。
- 握手后才有业务调用；未握手就收到业务方法 → `E_NOT_INITIALIZED`。

### 生命周期

1. 心跳 `ping` 每 5s；请求默认超时 30s，长计算显式带 `timeout_ms`（默认 120s）。
2. 每个 sidecar 独立 supervisor；同会话内最多重启 3 次（退避 1s/2s/4s），超出标记「内核不可用」并在 UI 明示。
3. 重启后未完成的请求**明确失败**；写操作**不自动重放**（幂等键由用户重试）。
4. 退出：`shutdown` → 等 2s → 强杀。
5. **懒启动**：sidecar 按需拉起（首次用到该能力时），保证冷启动 ≤3s。

## 2. 错误

```jsonc
{"jsonrpc":"2.0","id":"7","error":{"code":-32001,"message":"平台不支持本地计算",
  "data":{"kind":"E_PLATFORM_UNSUPPORTED","retryable":false,"detail":{...}}}}
```

| code | kind | 含义 |
|---:|---|---|
| -32700 | `E_PARSE` | 行不是合法 JSON |
| -32600 | `E_INVALID_REQUEST` | 缺 method/id 等 |
| -32601 | `E_METHOD_NOT_FOUND` | 未知方法 |
| -32602 | `E_INVALID_PARAMS` | 参数不合法（**不重试**） |
| -32603 | `E_INTERNAL` | 内部异常（带 stack 摘要） |
| -32001 | `E_PLATFORM_UNSUPPORTED` | 该平台不支持（如 Android 无 sidecar） |
| -32002 | `E_NOT_AUTHORIZED` | 来源需授权/需登录 |
| -32003 | `E_SOURCE_UNAVAILABLE` | 不可达/反爬受限/已过期 |
| -32004 | `E_DATA_MISSING` | 必需数据缺失（**缺失 ≠ 零值**） |
| -32005 | `E_CONTRACT_MISMATCH` | 契约或 schema 版本不匹配 |
| -32006 | `E_RATE_LIMITED` | 被限流，带 `retry_after_seconds` |
| -32007 | `E_TIMEOUT` | 超时 |
| -32008 | `E_NOT_INITIALIZED` | 未握手 |
| -32009 | `E_PERMISSION_DENIED` | 角色越权（**工具未执行**） |

`data.detail` 至少含：`reason`（中文短句）、`source_id`（如有）、`retryable`（bool）。

## 3. 方法清单（v1，17 个）

| 域 | 方法 | 归属 | 请求要点 | 响应要点 |
|---|---|---|---|---|
| 核心 | `initialize` / `shutdown` / `ping` | 两者 | 见 §1 | `sidecar/version/contract_version/schema_version/capabilities` |
| 采集 | `sources.list` | Go | `{"include_disabled":false}` | `{"sources":[SourceLedgerEntry]}` |
| 采集 | `sources.probe` | Go | `{"source_id":"em_csi300","timeout_s":20}` | `{"state":"reachable|need_auth|need_login|restricted|unreachable","detail":...}` |
| 采集 | `sources.health` | Go | `{}` | `{"entries":[{source_id,last_success_at,stale,coverage_start,coverage_end,failure_reason,state}]}` |
| 采集 | `collect.run` | Go | `{"source_id":"...","range":{...},"dry_run":false}` | `{"job_id":"...","status":"ok","written_files":[...],"evidence":[...]}` |
| 采集 | `inbox.ingest` | Go | `{"path":"<绝对路径>","declared_source":"optional","as_of":"optional"}` | `{"batch_id":"...","accepted":[{file,series_id,rows,release_time_rule,evidence}],"rejected":[{file,reason,error_file}]}` |
| 采集 | `events.poll` | Go | `{"job_id":"optional"}` | `{"events":[{ts,type,job_id,payload}]}` |
| 内核 | `db.query` | Rust | `{"view":"market_daily","filters":{"series_id":"...","start":"...","end":"..."},"as_of":"...","limit":1000}` | `{"columns":[...],"rows":[...],"as_of":"...","truncated":false}` |
| 内核 | `db.write` | Rust | `{"table":"pit_observations","rows":[...],"idempotency_key":"..."}` | `{"written":n,"idempotency_key":"..."}` |
| 内核 | `pit.ingest` | Rust | `{"source":"intermediate-file","path":"...","declared":{...},"idempotency_key":"..."}` | `{"series":[{"series_id","rows","release_time_rule","coverage"}],"derived_recomputed":[...],"coverage_gate":{"passed":true,"baseline":...,"current":...}}` |
| 内核 | `kb.index` | Rust | `{"corpus_dir":"...","force":false}` | `{"documents":n,"chunks":n,"index_version":"kb-bm25-v1"}` |
| 内核 | `kb.search` | Rust | `{"query":"...","top_k":5,"filters":{...}}` | `{"hits":[{"chunk_id","score","text","document_id","locator","published_at","source_id"}]}` |
| 内核 | `workspace.info` | Rust | `{}` | `{"path","size_bytes","schema_version","series_count","obs_count","last_ingest_at"}` |
| 内核 | `workspace.migrate` | Rust | `{"target_version":n}` | `{"from":n,"to":n}` |
| 内核 | `features.build` | Rust | `{"series_ids":[...],"as_of":"..."}` | `{"built":n,"feature_ids":[...]}` |
| 内核 | `signal.compute` | Rust | `{"as_of":"..."}` | `{"signal_id","value","dims":{...},"missing_dims":[...],"limitations":[...]}` |
| 内核 | `cfsi.compute` | Rust | `{"as_of":"..."}` | `{"cfsi","level","tau","dims":{"equity":{...}},"missing_dims":[...],"limitations":[...],"provenance":{...}}` |
| 内核 | `tools.invoke` | Rust | `{"tool":"risk_measure","params":{...},"idempotency_key":"..."}` | `{"evidence":{"evidence_id","tool","version","inputs_hash","hash","value","unit","as_of","params"}}` |
| 内核 | `kernel.hash` | Rust | `{"payload":{...},"kind":"inputs_hash\|evidence_id\|evidence_hash"}` | `{"hash":"..."}` |

> **v2 追加**（本轮不实现，schema 先留位）：`hmm.fit`、`dtw.neighbors`、`crps`、`dm.test`、`pit.calibrate`、`awlp`、`pca`。

### `db.query` 安全约束

**不接受任意 SQL 字符串。** kernel 暴露**具名视图 + 参数化查询**：

```jsonc
{"view":"market_daily","filters":{"series_id":"market.cn_equity.csi300","start":"2024-01-01","end":"2024-06-30"},"as_of":"2024-06-30T18:00:00+08:00","limit":1000}
```

- `as_of` 由 kernel **强制注入**过滤，Dart 无法绕过时点过滤。
- 视图白名单：`market_daily`、`macro_monthly`、`pit_observations`、`data_cards`、`documents`、`signals`、`cfsi_history`、`series_catalog`、`ingest_batches`、`audit_events`。

## 4. 工具注册表（真源：`contracts/tools/tools.json`）

由 `contracts/tools/tools.json` **生成**成 Dart 常量与 Rust 常量（同一真源，不手抄两遍）。每条含：

```jsonc
{
  "tool": "risk_measure",
  "version": "1.0.0",
  "risk_level": "L0",            // L0 只读 / L1 写本地 / L2 触发外部动作需 HITL
  "allowed_roles": ["regulator","investor","financier","cross_validator"],
  "params_schema_ref": "contracts/tools/risk_measure.params.schema.json",
  "returns": {"value":"number","unit":"string","as_of":"datetime"},
  "deterministic": true,          // 工具绝不调用 LLM
  "legacy_ref": "commorcial/src/cbr/tools/risk.py"
}
```

- 七个工具：`risk_measure`、`systemic_risk`、`capital_flow`、`funding_cost`、`scenario`、`forecast`、`knowledge_search`。
- **权限与审计在 Dart，执行在 Rust**（见 docs/11 §5.5）：Dart 门卫先鉴权（`default_deny=true`），越权 → 只产 `permission_denied` 审计事件，**不发 RPC**。

## 5. PIT 时点纪律

- `release_time ≠ obs_date`。**四要素**：`release_lag_days` + `publish_hour`/`publish_minute` + `tz_offset` → `release_time`。
  - A 股 / 中债 / 港股：观测日当日 **18:00 (+08:00)**
  - 隔夜海外因子（VIX / SP500 / US10Y）：观测日**次日 09:00 (+08:00)**（`release_lag_days: 1`）
  - 月频：按发布日
  - 无发布列 → **保守规则**推导，依据必须可查（写进 `release_time_rule`）
- 派生序列（`cgb_index`/`term_spread`/`cnh_cny_gap`/`cn_us_spread`）**不可直接抓取**；`release_time` 取两输入的**最大值**；写回后必须重算。
- 四级过滤（知识库层 / 工具层 / Agent 层 / 核验层）各自注入 `as_of`。
- **缺失 ≠ 零值**：缺席维度不参与计算，结果必须追加 `limitations`，**禁止用 0 或均值填充**。

## 5.1 滚动经验分位的 tie-break（必须逐字复刻）

CFSI 六维的"压力分"是**滚动经验分位**，其并列处理直接决定 2902 行里少数日期的取值。旧版实现（`commorcial/src/cbr/data/labels.py::_rolling_percentile`）的口径是：

```
p_t = count(valid <= x_t) / n_valid        # 窗口 [t-1249, t] 内，min_periods=252
```

**关键点**：
1. **弱不等号 `<=`**：与当前值相等的历史值**计入**分子（并列偏向高分位），不是平均秩、不是 `<`。
2. 窗口**含当日**（`[t-window+1, t]`），只用 t 及以前 → 无未来信息。
3. 有效样本 < `min_periods` 或当前值非有限 → `NaN`（**不是 0**）。
4. 训练期 winsorize（1%/99%）在分位之前做，边界只用训练期数据。

**为什么必须写死**：真实数据里并列极多（`dim_credit` 有 323 个并列值、涉及 743 天）。tie-break 差一格就会让极少数日期的分位偏移，进而让 CFSI 出现 ~0.06 的差异。

**回归判据（三层）**：

| 层 | 判据 | 依据 |
|---|---|---|
| L1 维度分位 | 严格 1e-8 | `<=` 口径已写死，无歧义 |
| L2 CFSI 主值 | 严格 1e-8 **或** 落在「经验 CDF 的相邻秩」上 | SVD 实现不同（LAPACK gesdd vs 手写 Jacobi）会让近并列得分换序 |
| L3 换序对 | 允许**成对互换**：若 A、B 两日的 CFSI 互换了对方的值，且 `|CFSI_A − CFSI_B| ≤ 1/n_train`，判为通过（记录但不失败） | 这两日的主成分得分差值小于 CDF 分辨率，排名本就不可辨 |

**已知的 4 行换序对**（2026-11-25 实测）：`2018-09-04 ↔ 2018-11-15`（差 0.0586）、`2024-02-28 ↔ 2025-12-18`（差 0.0586）。二者都属 L3：得分差值在 CDF 分辨率以下。

**任何超出 L3 的偏差 = 实现错误**，必须修实现而不是放宽判据。

## 6. 哈希规范（与旧版逐字节一致）

旧实现：`sha256(json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False))`，浮点先过 `to_native`（NaN/Inf→null、date→isoformat）。

**Rust 侧必须实现 Python `repr(float)` 兼容的序列化器**（`1e16` vs `1e+16`、`1e-05` vs `1e-5` 都要对齐），而不是改验收标准。

| kind | 输入 | 输出 |
|---|---|---|
| `inputs_hash` | 工具入参（含 series/参数/时点） | 64 位小写 hex |
| `evidence_id` | `{tool, version, inputs_hash}` | `"ev_" + 前 16 位 hex` |
| `evidence_hash` | 证据载荷（value/unit/as_of/来源证据） | 64 位小写 hex |

黄金向量：由旧 Python 项目生成，入库 `contracts/golden-vectors/*.json`；Rust 测试与 Dart 契约测试读**同一批**向量。

## 7. 目录约定

```
contracts/
  VERSION                  # 语义化版本
  README.md                # 本文件
  tools/tools.json         # 工具注册表（真源）
  tools/<tool>.params.schema.json
  golden-vectors/*.json
  <domain>/<method>.request.schema.json
  <domain>/<method>.response.schema.json
  examples/<method>/*.json   # ≥2 组样例，含错误样例
```

- schema 用 **JSON Schema draft 2020-12**。
- 运行时**不做 schema 校验**（性能不划算）；靠 ①各语言原生类型 + 构造期断言 ②CI 校验样例与 schema 一致 ③跨语言黄金向量测试。
