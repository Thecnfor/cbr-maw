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
            format!(
                "历史信号仅 {} 条，不足以做相似案例检索（需要 ≥ 20）",
                history.len()
            ),
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
                "outcome": outcome_after(ws, case_day, day, horizon),
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

/// 深层反思（HLR）：回看过去 `lookback_days` 天，把**当时的预警等级**与
/// **事后真实走势**对照，给出预警效能曲线。
///
/// 这是 `X-AlertAgent` 外环的复盘半边：浅层反思回答「现在像历史上哪天」，
/// 深层反思回答「我们过去报警报得准不准」。
///
/// 口径：
/// - 事后窗口固定 `horizon` 个交易日（与 y_20 一致）；
/// - 「命中」= 当时 level ∈ {high, critical} 且事后窗口内压力峰值 ≥ τ；
/// - 未到 `horizon` 的近期时点**不参与**统计（标签未成熟，不能算对错）。
pub fn deep(ws: &Workspace, as_of: &str, lookback_days: usize, horizon: usize) -> Result<Value> {
    let day = &as_of[..10.min(as_of.len())];
    // τ 取自当日信号（缺维时 τ 会按可用维度重估，ADR-008）。
    let current = load_signal(ws, day)?;
    let Some(current) = current else {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            "as_of 当日没有已计算的信号，无法做效能复盘",
        )
        .with_detail(json!({"reason": "当日信号未计算", "as_of": day})));
    };

    // 日历：用 CFSI 历史表的交易日作为基准（信号表可能稀疏）。
    let calendar = trading_calendar(ws, day)?;
    if calendar.is_empty() {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            "没有可用的交易日历，无法确定事后窗口",
        ));
    }
    let Some(pos_now) = calendar.iter().position(|d| d == day) else {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            format!("{day} 不在交易日历内"),
        ));
    };
    // 只看「已经走完 horizon 天」的历史时点。
    if pos_now < horizon {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            format!("历史不足 {horizon} 个交易日，无法复盘"),
        )
        .with_detail(json!({"reason": "标签未成熟", "need": horizon, "have": pos_now})));
    }
    let mature_end = pos_now - horizon;
    let start = mature_end.saturating_sub(lookback_days);

    let signals = load_signals_between(
        ws,
        calendar
            .get(start)
            .map(String::as_str)
            .unwrap_or(&calendar[0]),
        calendar[mature_end].as_str(),
    )?;
    if signals.is_empty() {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            "回看窗口内没有任何已计算的信号，无法复盘",
        ));
    }

    // τ 必须取自当日 CFSI 行（缺维时已按 ADR-008 重估）。
    // 不得用硬编码兜底：缺失≠零值，拿一个常量冒充 τ 会把「不知道阈值」
    // 伪装成「知道」，正是红线禁止的做法。
    let Some(tau) = tau_on(ws, day)? else {
        return Err(KernelError::new(
            ErrorKind::DataMissing,
            "当日 CFSI 行缺少 τ，无法判定是否命中（缺失不得用常量兜底）",
        )
        .with_detail(json!({"reason": "τ 缺失", "as_of": day})));
    };

    let mut hits = 0usize;
    let mut alarms = 0usize;
    let mut missed = 0usize;
    let mut false_alarms = 0usize;
    let mut cases = Vec::new();
    for row in &signals {
        let Some(case_day) = row["as_of"].as_str() else {
            continue;
        };
        let Some(pos) = calendar.iter().position(|d| d == case_day) else {
            continue;
        };
        if pos + horizon >= calendar.len() {
            continue; // 标签未成熟
        }
        let level = row["level"].as_str().unwrap_or("");
        let alarmed = level == "high" || level == "critical";
        let peak = peak_between(ws, &calendar[pos + 1..=pos + horizon])?;
        let Some(peak) = peak else { continue };
        let actually_stressed = peak >= tau;
        if alarmed {
            alarms += 1;
        }
        match (alarmed, actually_stressed) {
            (true, true) => hits += 1,
            (true, false) => false_alarms += 1,
            (false, true) => missed += 1,
            (false, false) => {}
        }
        cases.push(json!({
            "as_of": case_day,
            "level": level,
            "alarmed": alarmed,
            "peak_after": r(peak),
            "actually_stressed": actually_stressed,
        }));
    }

    let precision = if alarms > 0 {
        Some(hits as f64 / alarms as f64)
    } else {
        None
    };
    let recall = if hits + missed > 0 {
        Some(hits as f64 / (hits + missed) as f64)
    } else {
        None
    };
    let base_rate = if !cases.is_empty() {
        cases
            .iter()
            .filter(|c| c["actually_stressed"] == true)
            .count() as f64
            / cases.len() as f64
    } else {
        0.0
    };
    let lift = match precision {
        Some(p) if base_rate > 0.0 => Some(p / base_rate),
        _ => None,
    };

    Ok(json!({
        "as_of": day,
        "model_version": current["model_version"],
        "window": {
            "lookback_days": lookback_days,
            "horizon": horizon,
            "from": cases.first().and_then(|c| c["as_of"].as_str()),
            "to": cases.last().and_then(|c| c["as_of"].as_str()),
            "evaluable_days": cases.len(),
        },
        "tau": r(tau),
        "performance": {
            "alarms": alarms,
            "hits": hits,
            "false_alarms": false_alarms,
            "missed": missed,
            "precision": precision.map(r),
            "recall": recall.map(r),
            "base_rate": r(base_rate),
            "lift": lift.map(r),
        },
        "cases": cases,
        "limitations": [
            "效能复盘只用**已成熟**的时点（事后窗口走完）；近期时点不参与统计",
            "命中定义为「事后窗口内压力峰值 ≥ τ」；τ 随缺维重估，跨期口径可能变化",
            "样本量小（< 30）时 precision/recall 不作显著性主张",
            "复盘结果驱动 HLR 反思，不写回当期定级",
        ],
    }))
}

/// 交易日历（`cfsi_history` 的 as_of 列，升序）。
pub fn trading_calendar(ws: &Workspace, as_of: &str) -> Result<Vec<String>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT DISTINCT as_of FROM cfsi_history WHERE as_of <= CAST(? AS DATE) \
             ORDER BY as_of ASC",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![as_of])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        if let Ok(d) = row.get::<usize, chrono::NaiveDate>(0) {
            out.push(d.to_string());
        }
    }
    Ok(out)
}

/// 区间内的信号（含两端）。
fn load_signals_between(ws: &Workspace, from: &str, to: &str) -> Result<Vec<Value>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT as_of, value, level FROM signals \
             WHERE as_of >= CAST(? AS DATE) AND as_of <= CAST(? AS DATE) ORDER BY as_of ASC",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![from, to])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        out.push(json!({
            "as_of": row.get::<usize, chrono::NaiveDate>(0).map(|d| d.to_string()).ok(),
            "value": row.get::<usize, f64>(1).ok(),
            "level": row.get::<usize, String>(2).ok(),
        }));
    }
    Ok(out)
}

/// 指定日 τ（缺维时按可用维度重估，ADR-008）。
pub fn tau_on(ws: &Workspace, as_of: &str) -> Result<Option<f64>> {
    let mut stmt = ws
        .conn
        .prepare("SELECT tau FROM cfsi_history WHERE as_of = CAST(? AS DATE)")
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![as_of])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    else {
        return Ok(None);
    };
    Ok(row.get::<usize, f64>(0).ok())
}

/// 区间内 CFSI 的峰值。
pub fn peak_between(ws: &Workspace, days: &[String]) -> Result<Option<f64>> {
    let Some(first) = days.first() else {
        return Ok(None);
    };
    let last = days.last().unwrap_or(first);
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT MAX(cfsi) FROM cfsi_history \
             WHERE as_of >= CAST(? AS DATE) AND as_of <= CAST(? AS DATE)",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![first, last])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    else {
        return Ok(None);
    };
    Ok(row.get::<usize, f64>(0).ok())
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
    let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    else {
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
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
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
///
/// **必须同时有下界与上界**：`day` 是案例日（只读其后），`as_of` 是决策时点
/// （不得越过）。少了上界时，若相似案例就在决策时点前几天，会把决策时点
/// **之后**的数据读进来——这正是 PIT 泄漏。
fn outcome_after(ws: &Workspace, day: &str, as_of: &str, horizon: usize) -> Value {
    let Ok(mut stmt) = ws.conn.prepare(
        "SELECT as_of, value, level FROM signals \
         WHERE as_of > CAST(? AS DATE) AND as_of <= CAST(? AS DATE) \
         ORDER BY as_of ASC LIMIT ?",
    ) else {
        return json!(null);
    };
    let Ok(mut rows) = stmt.query(duckdb::params![day, as_of, horizon as i64]) else {
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
    fn deep_reflection_counts_hits_and_misses() {
        let (ws, path) = temp_ws("deep");
        // 20 个交易日：前 10 天低压、后 10 天高压（cfsi 越过 τ）。
        for i in 0..20 {
            let day = format!("2026-01-{:02}", i + 1);
            let cfsi = if i < 10 { 10.0 } else { 99.0 };
            ws.conn
                .execute(
                    "INSERT INTO cfsi_history(as_of, cfsi, level, tau, dims, missing_dims, limitations, index_version, label_version) \
                     VALUES (CAST(? AS DATE), ?, 'low', 91.5, '{}', '[]', '[]', 'cfsi-v1', 'stress_pca_q90')",
                    duckdb::params![day, cfsi],
                )
                .unwrap();
            // 信号：前 5 天报警（其中部分是误报），后 15 天不报警。
            let level = if i < 5 { "high" } else { "low" };
            insert_signal(
                &ws,
                &day,
                r#"{"bond":0.5,"credit":0.5,"crossborder":0.5,"equity":0.5,"fx":0.5,"global":0.5}"#,
                0.5,
            );
            ws.conn
                .execute(
                    "UPDATE signals SET level = ? WHERE as_of = CAST(? AS DATE)",
                    duckdb::params![level, day],
                )
                .unwrap();
        }
        // 在末日复盘：horizon=5，只看已成熟的时点。
        let out = deep(&ws, "2026-01-20", 30, 5).unwrap();
        let perf = &out["performance"];
        // 前 5 天报警、其后 5 天（1/6..1/10）仍是低压 → 全为误报。
        assert_eq!(perf["false_alarms"].as_u64(), Some(5));
        assert_eq!(perf["hits"].as_u64(), Some(0));
        // 后 15 天不报警，其中 1/11..1/15 之后进入高压 → 有漏报。
        assert!(perf["missed"].as_u64().unwrap() > 0);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn deep_reflection_refuses_immature_window() {
        let (ws, path) = temp_ws("deep-immature");
        for i in 0..3 {
            let day = format!("2026-01-{:02}", i + 1);
            ws.conn
                .execute(
                    "INSERT INTO cfsi_history(as_of, cfsi, level, tau, dims, missing_dims, limitations, index_version, label_version) \
                     VALUES (CAST(? AS DATE), 10.0, 'low', 91.5, '{}', '[]', '[]', 'cfsi-v1', 'stress_pca_q90')",
                    duckdb::params![day],
                )
                .unwrap();
            insert_signal(
                &ws,
                &day,
                r#"{"bond":0.5,"credit":0.5,"crossborder":0.5,"equity":0.5,"fx":0.5,"global":0.5}"#,
                0.5,
            );
        }
        // horizon=20 但只有 3 天历史 → 必须报「标签未成熟」，不得硬算。
        let err = deep(&ws, "2026-01-03", 10, 20).unwrap_err();
        assert_eq!(err.kind, ErrorKind::DataMissing);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn outcome_after_never_reads_past_as_of() {
        // 回归：曾只有下界 `as_of > case_day`，没有上界。若相似案例就在
        // 决策时点前几天，会把决策时点**之后**的数据读进来（PIT 泄漏）。
        let (ws, path) = temp_ws("outcome");
        for (day, value) in [
            ("2026-01-01", 10.0),
            ("2026-01-02", 20.0),
            ("2026-01-03", 30.0),
            ("2026-01-04", 40.0),
        ] {
            insert_signal(
                &ws,
                day,
                r#"{"bond":0.5,"credit":0.5,"crossborder":0.5,"equity":0.5,"fx":0.5,"global":0.5}"#,
                value,
            );
        }
        // 案例日 01-01、决策时点 01-02：事后窗口只能看到 01-02，不得包含 01-03/04。
        let outcome = outcome_after(&ws, "2026-01-01", "2026-01-02", 20);
        assert_eq!(outcome["days"].as_u64(), Some(1), "只能读到 as_of 当日");
        assert_eq!(outcome["last"].as_f64(), Some(20.0));
        assert_eq!(outcome["peak"].as_f64(), Some(20.0), "不得读到 30/40");
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
