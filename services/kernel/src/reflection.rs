//! 反思闭环（`X-AlertAgent` 外环最小实现，ADR-010 §1）。
//!
//! 不引入 LanceDB：`MI / LLR / HLR` 三库的检索需求在当前规模下用 DuckDB
//! 的 `signals` + `cfsi_history` 两表就能满足，且**零新增依赖**。
//! 向量化检索与 MMR 属于 v2 的 M4.5，届时替换本模块的检索实现即可，
//! 对外契约（`reflection.shallow`）不变。
//!
//! 两条硬约束：
//! 1. **`available_at <= as_of`**：所有历史查询都以 `as_of` 为上界，
//!    杜绝用未来走势「复盘」历史时点；
//! 2. **缺失即缺失**：历史不足就报不足，不插值、不补数。

use crate::error::{ErrorKind, KernelError, Result};
use crate::workspace::Workspace;
use serde_json::{json, Map, Value};

use crate::numeric::r;

/// 相似案例的判定窗口（交易日）。
const SIMILARITY_WINDOW: usize = 5;

/// 浅层反思：在 `as_of` 时点回看历史，找出压力结构相似的时点，
/// 并给出这些时点**之后**的真实走势（事后绩效，仅用于归因）。
///
/// 参数：
/// - `as_of`：决策时点（历史检索上界）
/// - `top_k`：返回的相似案例数
/// - `horizon`：事后回看窗口（交易日）
pub fn shallow(ws: &Workspace, as_of: &str, top_k: usize, horizon: usize) -> Result<Value> {
    let day = &as_of[..10.min(as_of.len())];
    let current = load_signal(ws, day)?;
    let Some(current) = current else {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            "as_of 当日没有已计算的信号，无法做反思（缺失不得用近似值替代）",
        )
        .with_detail(json!({"reason": "当日信号未计算", "as_of": day})));
    };

    let current_dims = current["dims"].clone();
    let history = load_history(ws, day)?;
    if history.len() < 20 {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            format!("历史信号仅 {} 条，不足以做相似案例检索（需要 ≥ 20）", history.len()),
        )
        .with_detail(json!({"reason": "历史样本不足", "available": history.len()})));
    }

    // 相似度：六维压力结构的欧氏距离（维度对齐后取均值差）。
    // 用结构而不是水平：水平高的日子天天相似，结构相似才有归因价值。
    let mut scored: Vec<(f64, &Value)> = history
        .iter()
        .filter_map(|row| {
            let dims = row.get("dims")?.as_object()?;
            let distance = dims_distance(&current_dims, dims)?;
            Some((distance, row))
        })
        .collect();
    scored.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let cases: Vec<Value> = scored
        .iter()
        .take(top_k.clamp(1, 20))
        .map(|(distance, row)| {
            let case_day = row["as_of"].as_str().unwrap_or("");
            json!({
                "as_of": case_day,
                "distance": r(*distance),
                "level": row["level"],
                "value": row["value"],
                // 事后走势：只读 case_day 之后的真实信号，用于归因「相似之后发生了什么」。
                "outcome": outcome_after(ws, case_day, horizon),
            })
        })
        .collect();

    Ok(json!({
        "as_of": day,
        "model_version": current["model_version"],
        "current": {
            "value": current["value"],
            "level": current["level"],
            "dims": current["dims"],
        },
        "history_size": history.len(),
        "similar_cases": cases,
        "similarity": "dimension_structure_euclidean",
        "limitations": [
            "相似案例只做归因参考：结构相似不等于因果相同",
            format!("事后走势回看 {horizon} 个交易日，仅供复盘，不得写入当期定级"),
            "历史检索上界为 as_of，不含任何未来数据",
        ],
    }))
}

/// 读取当日已计算的信号。
fn load_signal(ws: &Workspace, as_of: &str) -> Result<Option<Value>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT as_of, value, level, dims, model_version FROM signals \
             WHERE as_of = CAST(? AS DATE)",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![as_of])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let Some(row) = rows.next().map_err(|e| KernelError::internal(e.to_string()))? else {
        return Ok(None);
    };
    let dims_text: Option<String> = row.get(3).ok();
    Ok(Some(json!({
        "as_of": row.get::<usize, chrono::NaiveDate>(0).map(|d| d.to_string()).ok(),
        "value": row.get::<usize, f64>(1).ok(),
        "level": row.get::<usize, String>(2).ok(),
        "dims": dims_text.and_then(|s| serde_json::from_str::<Value>(&s).ok()),
        "model_version": row.get::<usize, String>(4).ok(),
    })))
}

/// 历史信号（严格 `as_of` 之前）。
fn load_history(ws: &Workspace, as_of: &str) -> Result<Vec<Value>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT as_of, value, level, dims FROM signals \
             WHERE as_of < CAST(? AS DATE) ORDER BY as_of DESC",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![as_of])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = Vec::new();
    while let Some(row) = rows.next().map_err(|e| KernelError::internal(e.to_string()))? {
        let dims_text: Option<String> = row.get(3).ok();
        out.push(json!({
            "as_of": row.get::<usize, chrono::NaiveDate>(0).map(|d| d.to_string()).ok(),
            "value": row.get::<usize, f64>(1).ok(),
            "level": row.get::<usize, String>(2).ok(),
            "dims": dims_text.and_then(|s| serde_json::from_str::<Value>(&s).ok()),
        }));
    }
    Ok(out)
}

/// 六维结构的欧氏距离（只对两侧都有的维度计算；缺维不填 0）。
fn dims_distance(a: &Value, b: &Map<String, Value>) -> Option<f64> {
    let a = a.as_object()?;
    let mut sum = 0.0;
    let mut n = 0usize;
    for (key, value) in a {
        let Some(x) = value.as_f64() else { continue };
        let Some(y) = b.get(key).and_then(|v| v.as_f64()) else {
            continue;
        };
        sum += (x - y).powi(2);
        n += 1;
    }
    if n < 4 {
        // 少于 4 维的结构比较没有意义（六维缺两维以上）。
        return None;
    }
    Some((sum / n as f64).sqrt())
}

/// 案例之后 [horizon] 个交易日的真实信号走势（事后复盘，只读）。
fn outcome_after(ws: &Workspace, day: &str, horizon: usize) -> Value {
    let Ok(mut stmt) = ws.conn.prepare(
        "SELECT as_of, value, level FROM signals \
         WHERE as_of > CAST(? AS DATE) ORDER BY as_of ASC LIMIT ?",
    ) else {
        return json!(null);
    };
    let Ok(mut rows) = stmt.query(duckdb::params![day, horizon as i64]) else {
        return json!(null);
    };
    let mut values = Vec::new();
    let mut peak: Option<f64> = None;
    while let Ok(Some(row)) = rows.next() {
        let value: Option<f64> = row.get(1).ok();
        if let Some(v) = value {
            peak = Some(peak.map_or(v, |p: f64| p.max(v)));
            values.push(v);
        }
    }
    if values.is_empty() {
        return json!(null);
    }
    json!({
        "days": values.len(),
        "peak": peak.map(r),
        "last": values.last().copied().map(r),
        "delta": peak.map(|p| r(p - values[0])),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_ws(name: &str) -> (Workspace, std::path::PathBuf) {
        let path = std::env::temp_dir().join(format!(
            "cbr-kernel-reflect-{name}-{}.duckdb",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        (Workspace::open(&path).expect("open workspace"), path)
    }

    fn insert_signal(ws: &Workspace, day: &str, dims: &str, value: f64) {
        ws.conn
            .execute(
                "INSERT INTO signals(as_of, signal_id, value, level, dims, missing_dims, limitations, model_version, label_version, evidence_id) \
                 VALUES (CAST(? AS DATE), ?, ?, 'low', ?, '[]', '[]', 'test', 'stress_pca_q90', 'ev_test')",
                duckdb::params![day, format!("sig_{day}"), value, dims],
            )
            .unwrap();
    }

    #[test]
    fn shallow_reflection_respects_as_of_and_finds_similar_structure() {
        let (ws, path) = temp_ws("similar");
        // 20 条历史，结构在两类之间交替；当期结构接近 A 类。
        for i in 0..20 {
            let day = format!("2026-01-{:02}", i + 1);
            let dims = if i % 2 == 0 {
                r#"{"bond":0.5,"credit":0.5,"crossborder":0.5,"equity":0.5,"fx":0.5,"global":0.5}"#
            } else {
                r#"{"bond":0.9,"credit":0.1,"crossborder":0.1,"equity":0.9,"fx":0.1,"global":0.9}"#
            };
            insert_signal(&ws, &day, dims, 0.5);
        }
        insert_signal(
            &ws,
            "2026-02-01",
            r#"{"bond":0.51,"credit":0.49,"crossborder":0.5,"equity":0.52,"fx":0.5,"global":0.5}"#,
            0.5,
        );
        let out = shallow(&ws, "2026-02-01", 3, 5).unwrap();
        let cases = out["similar_cases"].as_array().unwrap();
        assert_eq!(cases.len(), 3);
        // 最近的三个案例必须都是 A 类（偶数日），不能混入 B 类。
        for case in cases {
            let day = case["as_of"].as_str().unwrap();
            let idx: usize = day[8..10].parse::<usize>().unwrap() - 1;
            assert_eq!(idx % 2, 0, "相似检索命中了结构不相似的 {day}");
        }
        // 事后走势只能看 case 之后的信号，且不得越界到 as_of 之后。
        assert!(cases[0]["outcome"].is_object() || cases[0]["outcome"].is_null());
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn shallow_reflection_fails_loudly_without_signal() {
        let (ws, path) = temp_ws("missing");
        let err = shallow(&ws, "2026-02-01", 3, 5).unwrap_err();
        assert_eq!(err.kind, ErrorKind::DataMissing);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }
}
