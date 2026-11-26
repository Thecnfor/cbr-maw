//! `db.query` 具名视图 + 参数化过滤（不接受任意 SQL；`as_of` 由内核强制注入）。

use crate::error::{ErrorKind, KernelError, Result};
use crate::pit::as_of_end_of_day;
use crate::workspace::Workspace;
use duckdb::types::Value as DuckValue;
use serde_json::{json, Map, Value};

/// 视图白名单（contracts/README.md §3）。
pub const VIEWS: [&str; 10] = [
    "market_daily",
    "macro_monthly",
    "documents",
    "series_catalog",
    "pit_observations",
    "data_cards",
    "signals",
    "cfsi_history",
    "ingest_batches",
    "audit_events",
];

struct ViewSpec {
    /// FROM 子句（视图名或底层 SELECT）。
    source: &'static str,
    /// 强制注入的时点过滤列（None = 该视图无时点列，只做版本/白名单约束）。
    as_of_column: Option<&'static str>,
    /// 可用的过滤参数 → 列名（参数化，绝不拼接用户字符串）。
    filters: &'static [(&'static str, &'static str)],
    /// 默认排序列。
    order_by: &'static str,
}

fn spec_for(view: &str) -> Option<ViewSpec> {
    Some(match view {
        "market_daily" => ViewSpec {
            source: "(SELECT series_id, obs_date, value, release_time, source, unit FROM series_obs \
                     WHERE series_id NOT IN (SELECT series_id FROM series_meta WHERE frequency = 'monthly'))",
            as_of_column: Some("release_time"),
            filters: &[("series_id", "series_id"), ("start", "obs_date"), ("end", "obs_date")],
            order_by: "obs_date ASC",
        },
        "pit_observations" => ViewSpec {
            source: "series_obs",
            as_of_column: Some("release_time"),
            filters: &[("series_id", "series_id"), ("start", "obs_date"), ("end", "obs_date")],
            order_by: "obs_date ASC",
        },
        "macro_monthly" => ViewSpec {
            source: "(SELECT o.series_id, o.obs_date, o.value, o.release_time, o.source, o.unit \
                     FROM series_obs o JOIN series_meta m ON m.series_id = o.series_id WHERE m.frequency = 'monthly')",
            as_of_column: Some("release_time"),
            filters: &[("series_id", "series_id"), ("start", "obs_date"), ("end", "obs_date")],
            order_by: "obs_date ASC",
        },
        "documents" => ViewSpec {
            source: "documents",
            as_of_column: Some("publish_time"),
            filters: &[("source", "source"), ("doc_id", "doc_id"), ("start", "publish_time"), ("end", "publish_time")],
            order_by: "publish_time ASC",
        },
        "data_cards" => ViewSpec {
            source: "series_meta",
            as_of_column: None,
            filters: &[("series_id", "series_id"), ("domain", "series_id")],
            order_by: "series_id ASC",
        },
        "series_catalog" => ViewSpec {
            source: "series_meta",
            as_of_column: None,
            filters: &[("series_id", "series_id")],
            order_by: "series_id ASC",
        },
        "signals" => ViewSpec {
            source: "signals",
            as_of_column: Some("as_of"),
            filters: &[("signal_id", "signal_id"), ("level", "level"), ("start", "as_of"), ("end", "as_of")],
            order_by: "as_of ASC",
        },
        "cfsi_history" => ViewSpec {
            source: "cfsi_history",
            as_of_column: Some("as_of"),
            filters: &[("level", "level"), ("start", "as_of"), ("end", "as_of")],
            order_by: "as_of ASC",
        },
        "ingest_batches" => ViewSpec {
            source: "ingest_batches",
            as_of_column: Some("created_at"),
            filters: &[("source", "source"), ("batch_id", "batch_id"), ("start", "created_at"), ("end", "created_at")],
            order_by: "created_at ASC",
        },
        "audit_events" => ViewSpec {
            source: "audit_events",
            as_of_column: Some("ts"),
            filters: &[("event_type", "event_type"), ("role", "role"), ("tool_name", "tool_name"), ("start", "ts"), ("end", "ts")],
            order_by: "ts ASC",
        },
        _ => return None,
    })
}

fn duck_to_json(value: &DuckValue) -> Value {
    match value {
        DuckValue::Null => Value::Null,
        DuckValue::Boolean(b) => json!(b),
        DuckValue::TinyInt(v) => json!(v),
        DuckValue::SmallInt(v) => json!(v),
        DuckValue::Int(v) => json!(v),
        DuckValue::BigInt(v) => json!(v),
        DuckValue::HugeInt(v) => json!(v.to_string()),
        DuckValue::UTinyInt(v) => json!(v),
        DuckValue::USmallInt(v) => json!(v),
        DuckValue::UInt(v) => json!(v),
        DuckValue::UBigInt(v) => json!(v),
        DuckValue::Float(v) => num_or_null(*v as f64),
        DuckValue::Double(v) => num_or_null(*v),
        DuckValue::Decimal(v) => v
            .to_string()
            .parse::<f64>()
            .map(num_or_null)
            .unwrap_or(Value::Null),
        DuckValue::Timestamp(unit, raw) => timestamp_to_string(*unit, *raw),
        DuckValue::Date32(days) => date32_to_string(*days),
        DuckValue::Text(s) => Value::String(s.clone()),
        DuckValue::Blob(bytes) => Value::String(String::from_utf8_lossy(bytes).to_string()),
        other => Value::String(format!("{other:?}")),
    }
}

fn num_or_null(value: f64) -> Value {
    if value.is_finite() {
        serde_json::Number::from_f64(value)
            .map(Value::Number)
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    }
}

fn date32_to_string(days: i32) -> Value {
    let epoch = chrono::NaiveDate::from_ymd_opt(1970, 1, 1).expect("valid epoch");
    match epoch.checked_add_signed(chrono::Duration::days(days as i64)) {
        Some(date) => Value::String(date.format("%Y-%m-%d").to_string()),
        None => Value::Null,
    }
}

fn timestamp_to_string(unit: duckdb::types::TimeUnit, raw: i64) -> Value {
    use duckdb::types::TimeUnit;
    let micros = match unit {
        TimeUnit::Second => raw.saturating_mul(1_000_000),
        TimeUnit::Millisecond => raw.saturating_mul(1_000),
        TimeUnit::Microsecond => raw,
        TimeUnit::Nanosecond => raw / 1_000,
    };
    let secs = micros.div_euclid(1_000_000);
    let nanos = (micros.rem_euclid(1_000_000) * 1_000) as u32;
    match chrono::DateTime::from_timestamp(secs, nanos) {
        Some(dt) => Value::String(dt.format("%Y-%m-%dT%H:%M:%S%.6f").to_string()),
        None => Value::Null,
    }
}

/// 执行具名视图查询。
pub fn query(
    ws: &Workspace,
    view: &str,
    filters: Option<&Value>,
    as_of: &str,
    limit: usize,
) -> Result<Value> {
    let spec = spec_for(view).ok_or_else(|| {
        KernelError::new(ErrorKind::InvalidParams, "参数不合法").with_detail(json!({
            "reason": "view 不在白名单内",
            "field": "view",
            "allowed": VIEWS,
        }))
    })?;

    let filters = filters.and_then(|v| v.as_object());
    let mut clauses: Vec<String> = Vec::new();
    let mut params: Vec<Box<dyn duckdb::ToSql>> = Vec::new();

    // 强制注入 as_of（Dart 无法绕过）
    if let Some(column) = spec.as_of_column {
        clauses.push(format!("{column} <= CAST(? AS TIMESTAMP)"));
        params.push(Box::new(as_of_end_of_day(as_of)));
    }

    let mut applied_as_of = as_of.to_string();
    if let Some(map) = filters {
        for (key, value) in map {
            let Some((_, column)) = spec.filters.iter().find(|(name, _)| name == key) else {
                return Err(
                    KernelError::new(ErrorKind::InvalidParams, "参数不合法").with_detail(json!({
                        "reason": format!("视图 {view} 不支持过滤字段 {key}"),
                        "field": key,
                        "allowed": spec.filters.iter().map(|(name, _)| *name).collect::<Vec<_>>(),
                    })),
                );
            };
            if value.is_null() {
                continue;
            }
            // 区间参数是包含边界的：start → >=，end → <=
            let (op, raw) = if *key == "start" {
                (">=", value_to_string(value))
            } else if *key == "end" {
                ("<=", value_to_string(value))
            } else {
                ("=", value_to_string(value))
            };
            if *key == "end" && spec.as_of_column == Some(*column) {
                // end 不能晚于 as_of（继续收紧，不放宽）
                applied_as_of = raw.clone();
            }
            clauses.push(format!("{column} {op} CAST(? AS VARCHAR)"));
            params.push(Box::new(raw));
        }
    }

    let where_clause = if clauses.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", clauses.join(" AND "))
    };
    let effective_limit = limit.clamp(1, 100_000);
    // 多取一行用于判断 truncated
    let sql = format!(
        "SELECT * FROM {} {} ORDER BY {} LIMIT {}",
        spec.source,
        where_clause,
        spec.order_by,
        effective_limit + 1
    );

    let mut stmt = ws
        .conn
        .prepare(&sql)
        .map_err(|e| KernelError::internal(format!("准备查询失败: {e}")))?;
    let param_refs: Vec<&dyn duckdb::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let mut rows = stmt
        .query(param_refs.as_slice())
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let column_names: Vec<String> = rows.as_ref().map(|s| s.column_names()).unwrap_or_default();

    let mut out_rows: Vec<Value> = Vec::new();
    let mut truncated = false;
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        if out_rows.len() >= effective_limit {
            truncated = true;
            break;
        }
        let mut values = Vec::with_capacity(column_names.len());
        for idx in 0..column_names.len() {
            let value: DuckValue = row
                .get(idx)
                .map_err(|e| KernelError::internal(e.to_string()))?;
            values.push(duck_to_json(&value));
        }
        out_rows.push(Value::Array(values));
    }

    Ok(json!({
        "columns": column_names,
        "rows": out_rows,
        "as_of": applied_as_of,
        "truncated": truncated,
    }))
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// `db.write` 允许的表白名单 → 列顺序。
pub const WRITE_TABLES: [&str; 3] = ["pit_observations", "documents", "audit_events"];

pub fn write(ws: &Workspace, table: &str, rows: &[Value], idempotency_key: &str) -> Result<Value> {
    if !WRITE_TABLES.contains(&table) {
        return Err(
            KernelError::new(ErrorKind::PermissionDenied, "角色越权").with_detail(json!({
                "reason": format!("表 {table} 不允许通过 db.write 直接写入"),
                "field": "table",
                "allowed": WRITE_TABLES,
            })),
        );
    }
    if let Some(cached) = ws.idempotent_result(idempotency_key)? {
        return Ok(cached);
    }
    if rows.is_empty() {
        return Ok(json!({"written": 0, "idempotency_key": idempotency_key}));
    }

    let written = match table {
        "pit_observations" => write_observations(ws, rows)?,
        "documents" => write_documents(ws, rows)?,
        "audit_events" => write_audit(ws, rows)?,
        _ => 0,
    };
    let result = json!({"written": written, "idempotency_key": idempotency_key});
    ws.remember_idempotent(idempotency_key, "db.write", &result)?;
    Ok(result)
}

fn write_observations(ws: &Workspace, rows: &[Value]) -> Result<usize> {
    let mut written = 0;
    for row in rows {
        let series_id = row["series_id"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("pit_observations 行缺少 series_id"))?;
        let obs_date = row["obs_date"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("pit_observations 行缺少 obs_date"))?;
        let Some(value) = row["value"].as_f64() else {
            // 缺失 ≠ 零值：跳过该行而不是写 0
            continue;
        };
        let release_time = row["release_time"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("pit_observations 行缺少 release_time"))?;
        ws.conn
            .execute(
                "INSERT INTO series_obs(series_id, obs_date, value, release_time, source, unit) \
                 VALUES (?, CAST(? AS DATE), ?, CAST(? AS TIMESTAMP), ?, ?) \
                 ON CONFLICT(series_id, obs_date) DO UPDATE SET value = excluded.value, \
                 release_time = excluded.release_time, source = excluded.source, unit = excluded.unit",
                duckdb::params![
                    series_id,
                    obs_date,
                    value,
                    release_time,
                    row["source"].as_str(),
                    row["unit"].as_str(),
                ],
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        written += 1;
    }
    Ok(written)
}

fn write_documents(ws: &Workspace, rows: &[Value]) -> Result<usize> {
    let mut written = 0;
    for row in rows {
        let doc_id = row["doc_id"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("documents 行缺少 doc_id"))?;
        let publish_time = row["publish_time"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("documents 行缺少 publish_time"))?;
        ws.conn
            .execute(
                "INSERT OR REPLACE INTO documents(doc_id, publish_time, source, title, body, url, hash) \
                 VALUES (?, CAST(? AS TIMESTAMP), ?, ?, ?, ?, ?)",
                duckdb::params![
                    doc_id,
                    publish_time,
                    row["source"].as_str(),
                    row["title"].as_str(),
                    row["body"].as_str(),
                    row["url"].as_str(),
                    row["hash"].as_str(),
                ],
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        written += 1;
    }
    Ok(written)
}

fn write_audit(ws: &Workspace, rows: &[Value]) -> Result<usize> {
    let mut written = 0;
    for row in rows {
        let event_id = row["event_id"]
            .as_str()
            .ok_or_else(|| KernelError::invalid_params("audit_events 行缺少 event_id"))?;
        let detail = row.get("detail").map(|v| v.to_string()).unwrap_or_default();
        ws.conn
            .execute(
                "INSERT OR REPLACE INTO audit_events(event_id, ts, event_type, role, tool_name, detail) \
                 VALUES (?, CAST(? AS TIMESTAMP), ?, ?, ?, ?)",
                duckdb::params![
                    event_id,
                    row["ts"].as_str().unwrap_or("1970-01-01 00:00:00"),
                    row["event_type"].as_str(),
                    row["role"].as_str(),
                    row["tool_name"].as_str(),
                    detail,
                ],
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        written += 1;
    }
    Ok(written)
}

/// 视图的列清单（供 README 与诊断面板）。
pub fn describe_views() -> Value {
    let mut map = Map::new();
    for view in VIEWS {
        if let Some(spec) = spec_for(view) {
            map.insert(
                view.to_string(),
                json!({
                    "as_of_column": spec.as_of_column,
                    "filters": spec.filters.iter().map(|(name, _)| *name).collect::<Vec<_>>(),
                }),
            );
        }
    }
    Value::Object(map)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workspace::Workspace;

    fn temp_ws(name: &str) -> (Workspace, std::path::PathBuf) {
        let path = std::env::temp_dir().join(format!(
            "cbr-kernel-test-{name}-{}.duckdb",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        (Workspace::open(&path).expect("open workspace"), path)
    }

    #[test]
    fn query_rejects_unknown_view() {
        let (ws, path) = temp_ws("view");
        let err = query(&ws, "arbitrary_sql", None, "2026-06-30", 10).unwrap_err();
        assert_eq!(err.kind, ErrorKind::InvalidParams);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn query_injects_as_of_filter() {
        let (ws, path) = temp_ws("asof");
        ws.conn
            .execute_batch(
                "INSERT INTO series_obs VALUES \
                 ('market.cn_equity.csi300', '2026-06-29', 4000.0, '2026-06-29 10:00:00', 't', '点'), \
                 ('market.cn_equity.csi300', '2026-06-30', 4025.0, '2026-06-30 10:00:00', 't', '点'), \
                 ('market.cn_equity.csi300', '2026-07-01', 9999.0, '2026-07-01 10:00:00', 't', '点');",
            )
            .unwrap();
        let result = query(&ws, "pit_observations", None, "2026-06-30", 100).unwrap();
        let rows = result["rows"].as_array().unwrap();
        assert_eq!(rows.len(), 2, "as_of 之后的行必须被过滤");
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn query_rejects_unknown_filter_field() {
        let (ws, path) = temp_ws("filter");
        let filters = json!({"sql": "DROP TABLE series_obs"});
        let err = query(&ws, "pit_observations", Some(&filters), "2026-06-30", 10).unwrap_err();
        assert_eq!(err.kind, ErrorKind::InvalidParams);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn write_skips_rows_without_value_instead_of_zero() {
        let (ws, path) = temp_ws("write");
        let rows = vec![
            json!({"series_id": "x", "obs_date": "2026-06-30", "value": 1.0, "release_time": "2026-06-30 10:00:00"}),
            json!({"series_id": "x", "obs_date": "2026-07-01", "value": null, "release_time": "2026-07-01 10:00:00"}),
        ];
        let result = write(&ws, "pit_observations", &rows, "idem-1").unwrap();
        assert_eq!(result["written"], 1);
        let count = ws.scalar_i64("SELECT count(*) FROM series_obs").unwrap();
        assert_eq!(count, 1);
        // 幂等：同键重放不重复写
        let again = write(&ws, "pit_observations", &rows, "idem-1").unwrap();
        assert_eq!(again["written"], 1);
        assert_eq!(ws.scalar_i64("SELECT count(*) FROM series_obs").unwrap(), 1);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }
}
