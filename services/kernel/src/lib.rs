//! CBR-MAW 内核 sidecar：NDJSON over stdio 的 JSON-RPC 2.0 服务。
//!
//! 契约：`contracts/README.md`。stdout 只出协议消息，日志一律写 stderr（JSONL）。

pub mod canon;
pub mod cfsi;
pub mod db;
pub mod error;
pub mod features;
pub mod ingest;
pub mod kb;
pub mod numeric;
pub mod pit;
pub mod signal;
pub mod tools;
pub mod workspace;

use error::{ErrorKind, KernelError, Result};
use serde_json::{json, Value};
use std::io::{BufRead, Write};
use workspace::Workspace;

/// 内核版本（随 Cargo.toml）。
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// 支持的契约版本（`contracts/VERSION`）。
pub const CONTRACT_VERSION: &str = "1.0.0";

/// 本内核实现的方法（`initialize.result.capabilities`）。
pub const CAPABILITIES: [&str; 17] = [
    "initialize",
    "shutdown",
    "ping",
    "db.query",
    "db.write",
    "pit.ingest",
    "kb.index",
    "kb.search",
    "workspace.info",
    "workspace.migrate",
    "features.build",
    "signal.compute",
    "cfsi.compute",
    "tools.invoke",
    "kernel.hash",
    "contract.capabilities",
    "tools.describe",
];

/// 运行期上下文。
pub struct Kernel {
    workspace: Option<Workspace>,
    data_home: Option<String>,
    resource_home: Option<String>,
    catalog: pit::SeriesCatalog,
    initialized: bool,
    shutdown_requested: bool,
    log_level: String,
}

impl Default for Kernel {
    fn default() -> Self {
        Self {
            workspace: None,
            data_home: None,
            resource_home: None,
            catalog: pit::SeriesCatalog::builtin(),
            initialized: false,
            shutdown_requested: false,
            log_level: "info".to_string(),
        }
    }
}

impl Kernel {
    pub fn new() -> Self {
        Self::default()
    }

    /// 从命令行参数构造（`--workspace` / `--data-home` / `--resource-home` / `--log-level`）。
    pub fn from_args<I: Iterator<Item = String>>(args: I) -> Result<Self> {
        let mut kernel = Self::default();
        let mut pending: Option<String> = None;
        for arg in args {
            if let Some(flag) = pending.take() {
                kernel.apply_flag(&flag, &arg)?;
                continue;
            }
            if let Some(flag) = arg.strip_prefix("--") {
                match flag.split_once('=') {
                    Some((name, value)) => kernel.apply_flag(name, value)?,
                    None => pending = Some(flag.to_string()),
                }
            }
        }
        if let Some(flag) = pending {
            return Err(KernelError::invalid_params(format!(
                "参数 --{flag} 缺少取值"
            )));
        }
        Ok(kernel)
    }

    fn apply_flag(&mut self, flag: &str, value: &str) -> Result<()> {
        match flag {
            "workspace" => {
                self.workspace = Some(Workspace::open(std::path::Path::new(value))?);
            }
            "data-home" => self.data_home = Some(value.to_string()),
            "resource-home" => {
                self.resource_home = Some(value.to_string());
                self.catalog = pit::SeriesCatalog::load(value);
            }
            "log-level" => self.log_level = value.to_string(),
            other => {
                return Err(KernelError::invalid_params(format!(
                    "未知启动参数 --{other}"
                )));
            }
        }
        Ok(())
    }

    fn log(&self, level: &str, msg: &str, extra: Value) {
        let mut payload = json!({
            "ts": chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string(),
            "level": level,
            "sidecar": "kernel",
            "msg": msg,
        });
        if let (Value::Object(map), Value::Object(extra)) = (&mut payload, extra) {
            for (k, v) in extra {
                map.insert(k, v);
            }
        }
        eprintln!("{payload}");
    }

    pub fn workspace(&mut self) -> Result<&Workspace> {
        self.workspace.as_ref().ok_or_else(|| {
            KernelError::not_initialized("工作区未打开：请先调用 initialize 或带 --workspace 启动")
        })
    }

    /// 处理一行输入，返回待输出的响应（`None` 表示通知，无响应）。
    pub fn handle_line(&mut self, line: &str) -> Option<Value> {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            return None;
        }
        let request: Value = match serde_json::from_str(trimmed) {
            Ok(value) => value,
            Err(err) => {
                return Some(error_response(
                    Value::Null,
                    &KernelError::new(ErrorKind::Parse, format!("行不是合法 JSON: {err}")),
                ))
            }
        };
        let id = request.get("id").cloned();
        let method = request
            .get("method")
            .and_then(|m| m.as_str())
            .map(str::to_string);
        let is_notification = id.is_none();

        let Some(method) = method else {
            return Some(error_response(
                id.unwrap_or(Value::Null),
                &KernelError::new(ErrorKind::InvalidRequest, "请求缺少 method"),
            ));
        };

        if !self.initialized
            && !matches!(
                method.as_str(),
                "initialize" | "ping" | "shutdown" | "contract.capabilities"
            )
        {
            let err = KernelError::not_initialized(format!("{method} 需在 initialize 之后调用"));
            return if is_notification {
                None
            } else {
                Some(error_response(id.unwrap_or(Value::Null), &err))
            };
        }

        let params = request.get("params").cloned().unwrap_or(Value::Null);
        let outcome = self.dispatch(&method, &params);
        if is_notification {
            return None;
        }
        let id = id.unwrap_or(Value::Null);
        Some(match outcome {
            Ok(result) => json!({"jsonrpc": "2.0", "id": id, "result": result}),
            Err(err) => error_response(id, &err),
        })
    }

    fn dispatch(&mut self, method: &str, params: &Value) -> Result<Value> {
        match method {
            "initialize" => self.initialize(params),
            "shutdown" => {
                self.shutdown_requested = true;
                Ok(json!({"stopped": true}))
            }
            "ping" => Ok(json!({
                "pong": true,
                "server_time": chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string(),
            })),
            "contract.capabilities" => Ok(json!({
                "sidecar": "kernel",
                "version": VERSION,
                "contract_version": CONTRACT_VERSION,
                "schema_version": workspace::SCHEMA_VERSION,
                "capabilities": CAPABILITIES,
            })),
            "tools.describe" => Ok(json!({
                "registry_version": "tools-v1",
                "default_deny": true,
                "tools": tools::TOOL_REGISTRY.iter().map(|meta| json!({
                    "tool": meta.name,
                    "version": meta.version,
                    "unit": meta.unit,
                    "description": meta.description,
                    "deterministic": true,
                    "default_params": tools::default_params(meta.name),
                })).collect::<Vec<_>>(),
            })),
            "db.query" => self.db_query(params),
            "db.write" => self.db_write(params),
            "pit.ingest" => self.pit_ingest(params),
            "kb.index" => self.kb_index(params),
            "kb.search" => self.kb_search(params),
            "workspace.info" => {
                let info = self.workspace()?.info()?;
                Ok(info)
            }
            "workspace.migrate" => {
                let target = require_i64(params, "target_version")?;
                self.workspace()?.migrate(target)
            }
            "features.build" => self.features_build(params),
            "signal.compute" => self.signal_compute(params),
            "cfsi.compute" => self.cfsi_compute(params),
            "tools.invoke" => self.tools_invoke(params),
            "kernel.hash" => kernel_hash(params),
            other => Err(KernelError::method_not_found(other)),
        }
    }

    fn initialize(&mut self, params: &Value) -> Result<Value> {
        let contract_version = require_str(params, "contract_version")?;
        if contract_version != CONTRACT_VERSION {
            return Err(KernelError::contract_mismatch(format!(
                "契约版本不匹配：客户端 {contract_version}，内核 {CONTRACT_VERSION}"
            ))
            .with_detail(json!({
                "client_contract_version": contract_version,
                "kernel_contract_version": CONTRACT_VERSION,
            })));
        }
        if let Some(resource_home) = params.get("resource_home").and_then(|v| v.as_str()) {
            self.resource_home = Some(resource_home.to_string());
            self.catalog = pit::SeriesCatalog::load(resource_home);
        }
        if let Some(data_home) = params.get("data_home").and_then(|v| v.as_str()) {
            self.data_home = Some(data_home.to_string());
        }
        if let Some(workspace) = params.get("workspace").and_then(|v| v.as_str()) {
            if !workspace.is_empty() {
                self.workspace = Some(Workspace::open(std::path::Path::new(workspace))?);
            }
        }
        self.initialized = true;
        self.log(
            "info",
            "initialize 完成",
            json!({"contract_version": contract_version}),
        );
        Ok(json!({
            "sidecar": "kernel",
            "version": VERSION,
            "contract_version": CONTRACT_VERSION,
            "schema_version": workspace::SCHEMA_VERSION,
            "capabilities": CAPABILITIES,
        }))
    }

    fn db_query(&mut self, params: &Value) -> Result<Value> {
        let view = require_str(params, "view")?;
        let as_of = require_str(params, "as_of")?;
        let limit = params
            .get("limit")
            .and_then(|v| v.as_i64())
            .unwrap_or(1000)
            .max(1) as usize;
        let filters = params.get("filters");
        db::query(self.workspace()?, view, filters, as_of, limit)
    }

    fn db_write(&mut self, params: &Value) -> Result<Value> {
        let table = require_str(params, "table")?;
        let idempotency_key = require_str(params, "idempotency_key")?;
        let rows = params
            .get("rows")
            .and_then(|v| v.as_array())
            .cloned()
            .ok_or_else(|| KernelError::invalid_params("缺少 rows"))?;
        db::write(self.workspace()?, table, &rows, idempotency_key)
    }

    fn pit_ingest(&mut self, params: &Value) -> Result<Value> {
        let source = require_str(params, "source")?;
        let path = require_str(params, "path")?;
        let idempotency_key = require_str(params, "idempotency_key")?;
        let declared = params.get("declared");
        let catalog = self.catalog.clone();
        ingest::ingest(
            self.workspace()?,
            &catalog,
            source,
            path,
            declared,
            idempotency_key,
        )
    }

    fn kb_index(&mut self, params: &Value) -> Result<Value> {
        let corpus_dir = require_str(params, "corpus_dir")?;
        let force = params
            .get("force")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        kb::index(self.workspace()?, corpus_dir, force)
    }

    fn kb_search(&mut self, params: &Value) -> Result<Value> {
        let query = require_str(params, "query")?;
        let top_k = params
            .get("top_k")
            .and_then(|v| v.as_i64())
            .unwrap_or(5)
            .clamp(1, 50) as usize;
        let filters = params.get("filters");
        // 时点：kb.search 请求无 as_of 字段时按「当前」处理（查询由 Dart 传入 filters.as_of 或顶层）
        let as_of = params
            .get("as_of")
            .and_then(|v| v.as_str())
            .or_else(|| {
                filters
                    .and_then(|f| f.get("as_of"))
                    .and_then(|v| v.as_str())
            })
            .unwrap_or("9999-12-31");
        let hits = kb::search(self.workspace()?, query, as_of, top_k, filters)?;
        Ok(json!({
            "hits": hits.into_iter().map(|hit| tools::kb_search::to_kb_hit(&hit)).collect::<Vec<_>>()
        }))
    }

    fn features_build(&mut self, params: &Value) -> Result<Value> {
        let as_of = require_str(params, "as_of")?;
        let series_ids: Vec<String> = params
            .get("series_ids")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|s| s.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        let catalog = self.catalog.clone();
        features::build(self.workspace()?, &catalog, &series_ids, as_of)
    }

    fn cfsi_compute(&mut self, params: &Value) -> Result<Value> {
        let as_of = require_str(params, "as_of")?;
        let catalog = self.catalog.clone();
        let result = cfsi::compute(self.workspace()?, as_of, &catalog)?;
        features::persist_cfsi(self.workspace()?, as_of, &result)?;
        Ok(result)
    }

    fn signal_compute(&mut self, params: &Value) -> Result<Value> {
        let as_of = require_str(params, "as_of")?;
        let catalog = self.catalog.clone();
        signal::compute(self.workspace()?, &catalog, as_of)
    }

    fn tools_invoke(&mut self, params: &Value) -> Result<Value> {
        let tool = require_str(params, "tool")?;
        let tool_params = params
            .get("params")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        let as_of = tool_params
            .get("as_of")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| {
                params
                    .get("as_of")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
            })
            .unwrap_or_else(|| chrono::Utc::now().format("%Y-%m-%d").to_string());

        let catalog = self.catalog.clone();
        let ws = self.workspace()?;
        let source = WorkspaceSource {
            ws,
            catalog: &catalog,
        };
        let result = tools::invoke(tool, &as_of, &tool_params, &source)?;
        Ok(json!({"evidence": result.evidence}))
    }

    pub fn shutdown_requested(&self) -> bool {
        self.shutdown_requested
    }
}

/// 把工作区包装成工具的数据源（PIT 过滤在 `Workspace::history` 内强制）。
struct WorkspaceSource<'a> {
    ws: &'a Workspace,
    catalog: &'a pit::SeriesCatalog,
}

impl tools::source::DataSource for WorkspaceSource<'_> {
    fn history(
        &self,
        series_id: &str,
        as_of: &str,
        lookback: Option<usize>,
    ) -> Vec<tools::source::ObsRow> {
        let end = pit::as_of_end_of_day(as_of);
        self.ws
            .history(series_id, &end, lookback)
            .unwrap_or_default()
    }

    fn risk_signal(&self, as_of: &str) -> Option<Value> {
        // 只读已入库的信号；不在此处临时计算（避免工具静默改库）
        let mut stmt = self
            .ws
            .conn
            .prepare(
                "SELECT as_of, signal_id, value, level, dims, missing_dims, limitations, model_version, label_version, evidence_id \
                 FROM signals WHERE as_of <= CAST(? AS DATE) ORDER BY as_of DESC LIMIT 1",
            )
            .ok()?;
        let mut rows = stmt
            .query(duckdb::params![&as_of[..10.min(as_of.len())]])
            .ok()?;
        let row = rows.next().ok()??;
        let day: chrono::NaiveDate = row.get(0).ok()?;
        let value: f64 = row.get(2).ok()?;
        Some(json!({
            "as_of": day.format("%Y-%m-%d").to_string(),
            "signal_id": row.get::<usize, String>(1).ok(),
            "model_version": row.get::<usize, String>(7).ok(),
            "horizons": {"5": value, "10": value, "20": value},
            "percentile": value,
            "level": row.get::<usize, String>(3).ok(),
            "drivers": [],
            "modality_contrib": {"numeric": 1.0, "text": 0.0},
            "label_version": row.get::<usize, String>(8).ok(),
            "evidence_id": row.get::<usize, String>(9).ok(),
        }))
    }

    fn cfsi_series(&self, as_of: &str) -> Option<cfsi::CfsiSeries> {
        cfsi::series(self.ws, as_of, self.catalog).ok()
    }

    fn daily_calendar(&self, as_of: &str) -> Option<Vec<String>> {
        cfsi::daily_calendar(self.ws, as_of, self.catalog).ok()
    }

    fn kb_search(
        &self,
        query: &str,
        as_of: &str,
        top_k: usize,
        tags: Option<&[String]>,
    ) -> Option<Vec<Value>> {
        let filters = tags.map(|tags| json!({"tags": tags}));
        kb::search(self.ws, query, as_of, top_k, filters.as_ref()).ok()
    }
}

/// `kernel.hash`：三种哈希种类。
fn kernel_hash(params: &Value) -> Result<Value> {
    let payload = params
        .get("payload")
        .ok_or_else(|| KernelError::invalid_params("缺少 payload"))?;
    let kind = require_str(params, "kind")?;
    let hash = match kind {
        "inputs_hash" => {
            let tool = payload.get("tool").and_then(|v| v.as_str()).unwrap_or("");
            let version = payload
                .get("version")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let as_of = payload.get("as_of").and_then(|v| v.as_str()).unwrap_or("");
            let params = payload.get("params").cloned().unwrap_or(json!({}));
            canon::compute_inputs_hash(tool, version, as_of, &params)
        }
        "evidence_id" => {
            let tool = payload.get("tool").and_then(|v| v.as_str()).unwrap_or("");
            let version = payload
                .get("version")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let inputs_hash = payload
                .get("inputs_hash")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            canon::compute_evidence_id(tool, version, inputs_hash)
        }
        "evidence_hash" => canon::compute_evidence_hash(payload),
        other => {
            return Err(
                KernelError::invalid_params("参数不合法").with_detail(json!({
                    "reason": "kind 必须是 inputs_hash / evidence_id / evidence_hash",
                    "field": "kind",
                    "received": other,
                })),
            )
        }
    };
    Ok(json!({"hash": hash}))
}

fn error_response(id: Value, err: &KernelError) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": err.to_error_object()})
}

fn require_str<'a>(params: &'a Value, key: &str) -> Result<&'a str> {
    params.get(key).and_then(|v| v.as_str()).ok_or_else(|| {
        KernelError::invalid_params(format!("缺少必填参数 {key}")).with_detail(json!({
            "reason": format!("缺少必填参数 {key}"),
            "field": key,
        }))
    })
}

fn require_i64(params: &Value, key: &str) -> Result<i64> {
    params.get(key).and_then(|v| v.as_i64()).ok_or_else(|| {
        KernelError::invalid_params(format!("缺少必填参数 {key}")).with_detail(json!({
            "reason": format!("缺少必填参数 {key}"),
            "field": key,
        }))
    })
}

/// 主循环：逐行读 stdin，响应写 stdout。
pub fn serve<R: BufRead, W: Write>(
    kernel: &mut Kernel,
    mut input: R,
    mut output: W,
) -> std::io::Result<()> {
    let mut line = String::new();
    loop {
        line.clear();
        let read = input.read_line(&mut line)?;
        if read == 0 {
            break;
        }
        if let Some(response) = kernel.handle_line(&line) {
            let encoded = serde_json::to_string(&response).unwrap_or_else(|_| "{}".to_string());
            writeln!(output, "{encoded}")?;
            output.flush()?;
        }
        if kernel.shutdown_requested() {
            break;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(kernel: &mut Kernel, line: &str) -> Value {
        kernel.handle_line(line).expect("request expects response")
    }

    fn init_request(id: &str) -> String {
        json!({
            "jsonrpc": "2.0", "id": id, "method": "initialize",
            "params": {
                "contract_version": "1.0.0", "client_version": "0.1.0",
                "workspace": "", "data_home": "/tmp", "resource_home": "/tmp"
            }
        })
        .to_string()
    }

    #[test]
    fn parse_error_on_garbage_line() {
        let mut kernel = Kernel::new();
        let response = run(&mut kernel, "not json");
        assert_eq!(response["error"]["data"]["kind"], "E_PARSE");
        assert_eq!(response["error"]["code"], -32700);
    }

    #[test]
    fn business_method_before_initialize_is_rejected() {
        let mut kernel = Kernel::new();
        let response = run(
            &mut kernel,
            &json!({"jsonrpc":"2.0","id":"2","method":"workspace.info","params":{}}).to_string(),
        );
        assert_eq!(response["error"]["data"]["kind"], "E_NOT_INITIALIZED");
        assert_eq!(response["error"]["code"], -32008);
    }

    #[test]
    fn initialize_reports_capabilities() {
        let mut kernel = Kernel::new();
        let response = run(&mut kernel, &init_request("1"));
        assert_eq!(response["result"]["sidecar"], "kernel");
        assert_eq!(response["result"]["contract_version"], "1.0.0");
        assert_eq!(response["result"]["schema_version"], 3);
        let caps = response["result"]["capabilities"].as_array().unwrap();
        assert!(caps.iter().any(|c| c == "tools.invoke"));
        assert!(caps.iter().any(|c| c == "cfsi.compute"));
    }

    #[test]
    fn contract_version_mismatch_fails_explicitly() {
        let mut kernel = Kernel::new();
        let request = json!({
            "jsonrpc": "2.0", "id": "1", "method": "initialize",
            "params": {"contract_version": "9.9.9", "client_version": "0.1.0",
                       "workspace": "", "data_home": "/tmp", "resource_home": "/tmp"}
        });
        let response = run(&mut kernel, &request.to_string());
        assert_eq!(response["error"]["data"]["kind"], "E_CONTRACT_MISMATCH");
        assert_eq!(response["error"]["code"], -32005);
    }

    #[test]
    fn unknown_method_is_method_not_found() {
        let mut kernel = Kernel::new();
        run(&mut kernel, &init_request("1"));
        let response = run(
            &mut kernel,
            &json!({"jsonrpc":"2.0","id":"2","method":"nope","params":{}}).to_string(),
        );
        assert_eq!(response["error"]["code"], -32601);
    }

    #[test]
    fn kernel_hash_matches_golden_vector() {
        let raw = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../contracts/golden-vectors/hash_vectors.json"
        ))
        .unwrap();
        let doc: Value = serde_json::from_str(&raw).unwrap();
        let vector = &doc["vectors"][0];
        let request = json!({
            "jsonrpc": "2.0", "id": "41", "method": "kernel.hash",
            "params": {
                "payload": {"tool": vector["tool"], "version": vector["version"],
                            "as_of": vector["as_of"], "params": vector["params"]},
                "kind": "inputs_hash"
            }
        });
        let mut kernel = Kernel::new();
        run(&mut kernel, &init_request("1"));
        let response = run(&mut kernel, &request.to_string());
        assert_eq!(response["result"]["hash"], vector["inputs_hash"]);
    }

    #[test]
    fn shutdown_sets_flag() {
        let mut kernel = Kernel::new();
        run(&mut kernel, &init_request("1"));
        let response = run(
            &mut kernel,
            &json!({"jsonrpc":"2.0","id":"2","method":"shutdown","params":{}}).to_string(),
        );
        assert_eq!(response["result"]["stopped"], true);
        assert!(kernel.shutdown_requested());
    }
}
