//! `pit.ingest`：中间文件 → PIT 表；release_time 推导、派生序列重算、覆盖率守门。

use crate::error::{ErrorKind, KernelError, Result};
use crate::pit::{
    default_rule, derived_inputs, derived_unit, ReleaseRule, SeriesCatalog, DERIVED_SERIES,
};
use crate::workspace::Workspace;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

/// 中间文件支持 CSV 与 NDJSON（Go 采集器输出规范化中间文件）。
pub fn ingest(
    ws: &Workspace,
    catalog: &SeriesCatalog,
    source: &str,
    path: &str,
    declared: Option<&Value>,
    idempotency_key: &str,
) -> Result<Value> {
    if let Some(cached) = ws.idempotent_result(idempotency_key)? {
        return Ok(cached);
    }

    let raw = std::fs::read_to_string(path).map_err(|e| {
        KernelError::new(ErrorKind::SourceUnavailable, "中间文件不可读").with_detail(json!({
            "reason": format!("无法读取中间文件: {e}"),
            "path": path,
        }))
    })?;
    let rows = parse_rows(&raw, path)?;
    if rows.is_empty() {
        return Err(
            KernelError::data_missing("中间文件没有可用观测").with_detail(json!({
                "reason": "中间文件没有可用观测（缺失不得写 0）",
                "path": path,
            })),
        );
    }

    let declared = declared.cloned().unwrap_or(Value::Null);
    let mut by_series: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for row in rows {
        let series_id = row["series_id"].as_str().unwrap_or("").to_string();
        if series_id.is_empty() {
            return Err(
                KernelError::data_missing("中间文件缺少 release_time 推导所需列").with_detail(
                    json!({
                        "reason": "缺少 series_id 列，无法推导 release_time",
                        "file": path,
                    }),
                ),
            );
        }
        if derived_inputs(&series_id).is_some() {
            // 派生序列不可直接抓取（不变量 4）
            return Err(KernelError::invalid_params(format!(
                "派生序列 {series_id} 不可直接入库；请写入其输入序列后由内核重算"
            ))
            .with_detail(json!({"reason": "派生序列不可直接抓取", "series_id": series_id})));
        }
        by_series.entry(series_id).or_default().push(row);
    }

    let mut series_results: Vec<Value> = Vec::new();
    let mut written_series: Vec<String> = Vec::new();
    for (series_id, rows) in &by_series {
        let fallback = default_rule(series_id, catalog);
        let rule = ReleaseRule::from_declared(&declared, fallback);
        let mut inserted = 0usize;
        let mut coverage_start: Option<String> = None;
        let mut coverage_end: Option<String> = None;
        for row in rows {
            let Some(obs_date) = row["obs_date"].as_str() else {
                continue;
            };
            // 缺失 ≠ 零值：无法解析的值不写该行
            let Some(value) = row["value"].as_f64() else {
                continue;
            };
            if !value.is_finite() {
                continue;
            }
            let release_time = match row["release_time"].as_str() {
                Some(explicit) if !explicit.is_empty() => explicit.to_string(),
                _ => rule.apply(obs_date).ok_or_else(|| {
                    KernelError::data_missing("中间文件缺少 release_time 推导所需列").with_detail(
                        json!({
                            "reason": "obs_date 不可解析，无法推导 release_time",
                            "file": path,
                        }),
                    )
                })?,
            };
            let unit = row["unit"]
                .as_str()
                .map(str::to_string)
                .or_else(|| catalog.get(series_id).map(|spec| spec.unit.clone()));
            let source_name = row["source"].as_str().unwrap_or(source).to_string();
            ws.conn
                .execute(
                    "INSERT INTO series_obs(series_id, obs_date, value, release_time, source, unit) \
                     VALUES (?, CAST(? AS DATE), ?, CAST(? AS TIMESTAMP), ?, ?) \
                     ON CONFLICT(series_id, obs_date) DO UPDATE SET value = excluded.value, \
                     release_time = excluded.release_time, source = excluded.source, unit = excluded.unit",
                    duckdb::params![series_id, obs_date, value, release_time, source_name, unit],
                )
                .map_err(|e| KernelError::internal(format!("写入 {series_id} 失败: {e}")))?;
            inserted += 1;
            let day = &obs_date[..10.min(obs_date.len())];
            if coverage_start.as_deref().map(|s| day < s).unwrap_or(true) {
                coverage_start = Some(day.to_string());
            }
            if coverage_end.as_deref().map(|e| day > e).unwrap_or(true) {
                coverage_end = Some(day.to_string());
            }
        }
        if inserted > 0 {
            written_series.push(series_id.clone());
            // 刷新数据卡覆盖期（series_meta）
            if let Some(spec) = catalog.get(series_id) {
                ws.conn
                    .execute(
                        "INSERT INTO series_meta(series_id, name, source, frequency, coverage_start, coverage_end, \
                         release_lag_days, pit_grade, unit, notes) \
                         VALUES (?, ?, ?, ?, CAST(? AS DATE), CAST(? AS DATE), ?, 'strict', ?, '') \
                         ON CONFLICT(series_id) DO UPDATE SET coverage_start = LEAST(series_meta.coverage_start, excluded.coverage_start), \
                         coverage_end = GREATEST(series_meta.coverage_end, excluded.coverage_end)",
                        duckdb::params![
                            series_id,
                            spec.name,
                            source,
                            spec.frequency,
                            coverage_start,
                            coverage_end,
                            spec.release_lag_days,
                            spec.unit,
                        ],
                    )
                    .map_err(|e| KernelError::internal(e.to_string()))?;
            }
        }
        series_results.push(json!({
            "series_id": series_id,
            "rows": inserted,
            "release_time_rule": rule.describe(),
            "coverage": {
                "start": coverage_start.unwrap_or_default(),
                "end": coverage_end.unwrap_or_default(),
            },
        }));
    }

    // 派生序列写后重算（全量，因为 cgb_index 是累积量）
    let mut derived_recomputed: Vec<String> = Vec::new();
    if !written_series.is_empty() {
        derived_recomputed = recompute_derived(ws, catalog)?;
    }

    // 覆盖率守门：覆盖序列数不高于基线则 passed=false
    let (baseline, current) = coverage_ratio(ws, catalog)?;
    let passed = current >= baseline;
    let coverage_gate = json!({
        "passed": passed,
        "baseline": crate::numeric::r(baseline).unwrap_or(0.0),
        "current": crate::numeric::r(current).unwrap_or(0.0),
        "reason": if passed { Value::Null } else { json!("本次写入的覆盖序列少于基线，拒绝切换数据集（保留基线全量 + 新增观测合并视图）") },
    });

    let batch_id =
        crate::canon::sha256_text(&format!("{source}|{path}|{idempotency_key}"))[..16].to_string();
    ws.conn
        .execute(
            "INSERT OR REPLACE INTO ingest_batches(batch_id, source, path, created_at, series_json, rows, coverage_gate) \
             VALUES (?, ?, ?, now(), ?, ?, ?)",
            duckdb::params![
                format!("ingest_{batch_id}"),
                source,
                path,
                serde_json::to_string(&series_results).unwrap_or_default(),
                series_results.iter().filter_map(|s| s["rows"].as_i64()).sum::<i64>(),
                coverage_gate.to_string(),
            ],
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    ws.set_meta(
        "last_ingest_at",
        &chrono::Utc::now()
            .format("%Y-%m-%dT%H:%M:%S%.6fZ")
            .to_string(),
    )?;

    let result = json!({
        "series": series_results,
        "derived_recomputed": derived_recomputed,
        "coverage_gate": coverage_gate,
    });
    ws.remember_idempotent(idempotency_key, "pit.ingest", &result)?;
    Ok(result)
}

fn parse_rows(raw: &str, path: &str) -> Result<Vec<Value>> {
    let trimmed = raw.trim_start();
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        // NDJSON（也接受单行数组）
        if trimmed.starts_with('[') {
            let array: Vec<Value> = serde_json::from_str(trimmed)
                .map_err(|e| KernelError::data_missing(format!("中间文件 JSON 解析失败: {e}")))?;
            return Ok(array);
        }
        let mut rows = Vec::new();
        for (idx, line) in raw.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let value: Value = serde_json::from_str(line).map_err(|e| {
                KernelError::data_missing(format!("{path}:{}: 非法 JSON: {e}", idx + 1))
            })?;
            rows.push(value);
        }
        return Ok(rows);
    }

    // CSV：表头 + 行
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_reader(raw.as_bytes());
    let headers = reader
        .headers()
        .map_err(|e| KernelError::data_missing(format!("CSV 表头不可读: {e}")))?
        .clone();
    let mut rows = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|e| KernelError::data_missing(format!("CSV 行不可读: {e}")))?;
        let mut map = Map::new();
        for (idx, field) in record.iter().enumerate() {
            let Some(name) = headers.get(idx) else {
                continue;
            };
            let name = name.trim();
            if name.is_empty() {
                continue;
            }
            let field = field.trim();
            let value = match name {
                "value" => match field.parse::<f64>() {
                    Ok(v) => json!(v),
                    Err(_) => Value::Null,
                },
                _ => json!(field),
            };
            map.insert(name.to_string(), value);
        }
        rows.push(Value::Object(map));
    }
    Ok(rows)
}

/// 重算全部派生序列并写回（只写新行或值变化 >1e-9 的行）。
pub fn recompute_derived(ws: &Workspace, catalog: &SeriesCatalog) -> Result<Vec<String>> {
    let mut written = Vec::new();
    for series_id in DERIVED_SERIES {
        let Some((left, right)) = derived_inputs(series_id) else {
            continue;
        };
        match compute_derived(ws, series_id, left, right) {
            Ok(rows) if !rows.is_empty() => {
                let mut count = 0usize;
                // 先一次性把该序列的既有值读进内存：逐行 SELECT 在 NTFS 上是 O(n) 次往返，
                // 2615 行 × 4 条派生序列会退化成分钟级（实测 >7 分钟）。
                let mut existing: BTreeMap<String, f64> = BTreeMap::new();
                {
                    let mut stmt = ws
                        .conn
                        .prepare("SELECT obs_date, value FROM series_obs WHERE series_id = ?")
                        .map_err(|e| KernelError::internal(e.to_string()))?;
                    let mut q = stmt
                        .query(duckdb::params![series_id])
                        .map_err(|e| KernelError::internal(e.to_string()))?;
                    while let Some(row) =
                        q.next().map_err(|e| KernelError::internal(e.to_string()))?
                    {
                        let day: chrono::NaiveDate = row
                            .get(0)
                            .map_err(|e| KernelError::internal(e.to_string()))?;
                        let value: f64 = row
                            .get(1)
                            .map_err(|e| KernelError::internal(e.to_string()))?;
                        existing.insert(day.format("%Y-%m-%d").to_string(), value);
                    }
                }
                // 批量写入：逐行 INSERT 在 NTFS 上每行一次 WAL fsync，2615 行会退化到分钟级。
                // 值用 f64 字面量内联（与 seed 的存储值一致），字符串做最小转义。
                let esc = |s: &str| s.replace('\'', "''");
                let unit = derived_unit(series_id);
                let mut batch: Vec<String> = Vec::with_capacity(512);
                let flush = |ws: &Workspace, batch: &mut Vec<String>| -> Result<()> {
                    if batch.is_empty() {
                        return Ok(());
                    }
                    let sql = format!(
                        "INSERT INTO series_obs(series_id, obs_date, value, release_time, source, unit) \
                         VALUES {} \
                         ON CONFLICT(series_id, obs_date) DO UPDATE SET value = excluded.value, \
                         release_time = excluded.release_time",
                        batch.join(",")
                    );
                    ws.conn
                        .execute_batch(&sql)
                        .map_err(|e| KernelError::internal(e.to_string()))?;
                    batch.clear();
                    Ok(())
                };
                for (obs_date, value, release_time) in rows {
                    if let Some(old) = existing.get(&obs_date) {
                        if (old - value).abs() <= 1e-9 {
                            continue;
                        }
                    }
                    batch.push(format!(
                        "('{}', CAST('{}' AS DATE), {:?}, CAST('{}' AS TIMESTAMP), 'derived:realtime', '{}')",
                        esc(series_id),
                        esc(&obs_date),
                        value,
                        esc(&release_time),
                        esc(unit),
                    ));
                    count += 1;
                    if batch.len() >= 512 {
                        flush(ws, &mut batch)?;
                    }
                }
                flush(ws, &mut batch)?;
                if count > 0 {
                    written.push(series_id.to_string());
                }
            }
            Ok(_) => {}
            Err(err) => {
                // 单个派生序列失败不影响基础写入（记 warning 由调用方日志承担）
                eprintln!(
                    "{}",
                    json!({"level": "warn", "sidecar": "kernel", "msg": format!("派生序列 {series_id} 重算失败: {err}")})
                );
            }
        }
    }
    let _ = catalog;
    Ok(written)
}

/// 计算单个派生序列的全部观测行：(obs_date, value, release_time)。
fn compute_derived(
    ws: &Workspace,
    series_id: &str,
    left: &str,
    right: Option<&str>,
) -> Result<Vec<(String, f64, String)>> {
    let left_rows = load_with_release(ws, left)?;
    if left_rows.is_empty() {
        return Ok(Vec::new());
    }
    if let Some(right) = right {
        let right_rows = load_with_release(ws, right)?;
        if right_rows.is_empty() {
            return Ok(Vec::new());
        }
        let right_map: BTreeMap<String, (f64, String)> = right_rows
            .into_iter()
            .map(|(day, value, release)| (day, (value, release)))
            .collect();
        let scale = if series_id == "market.fx.cnh_cny_gap" {
            1.0e4
        } else {
            100.0
        };
        let mut out = Vec::new();
        for (day, value, release) in left_rows {
            if let Some((right_value, right_release)) = right_map.get(&day) {
                // release_time 取两输入的较大者
                let merged = if release > *right_release {
                    release
                } else {
                    right_release.clone()
                };
                out.push((day, (value - right_value) * scale, merged));
            }
        }
        Ok(out)
    } else {
        // cgb_index：100 × exp(cumsum(-7.5 × Δy / 100))
        let mut out = Vec::new();
        let mut cumulative = 0.0;
        let mut previous: Option<f64> = None;
        for (day, value, release) in left_rows {
            let delta = match previous {
                Some(prev) => (value - prev) / 100.0,
                None => 0.0,
            };
            cumulative += -7.5 * delta;
            out.push((day, 100.0 * cumulative.exp(), release));
            previous = Some(value);
        }
        Ok(out)
    }
}

fn load_with_release(ws: &Workspace, series_id: &str) -> Result<Vec<(String, f64, String)>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT obs_date, value, release_time FROM series_obs \
             WHERE series_id = ? AND value IS NOT NULL ORDER BY obs_date ASC",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![series_id])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        let day: chrono::NaiveDate = row
            .get(0)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let value: f64 = row
            .get(1)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let release: chrono::NaiveDateTime = row
            .get(2)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        out.push((
            day.format("%Y-%m-%d").to_string(),
            value,
            release.format("%Y-%m-%d %H:%M:%S").to_string(),
        ));
    }
    Ok(out)
}

/// 覆盖率 = 已有观测的序列数 / 目录内序列数。
fn coverage_ratio(ws: &Workspace, catalog: &SeriesCatalog) -> Result<(f64, f64)> {
    let total = catalog.all().count().max(1) as f64;
    let covered = ws.scalar_i64("SELECT count(DISTINCT series_id) FROM series_obs")? as f64;
    // baseline 取上一次入库时的覆盖数（meta），首次为 0
    let baseline_series = ws
        .get_meta("coverage_baseline")?
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(0.0);
    ws.set_meta("coverage_baseline", &covered.to_string())?;
    Ok((baseline_series / total, covered / total))
}

/// `workspace.info` 的辅助：从库读取的信号/CFSI 最近时点。
pub fn latest_signal_as_of(ws: &Workspace) -> Result<Option<String>> {
    let mut stmt = ws
        .conn
        .prepare("SELECT max(as_of) FROM signals")
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query([])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    if let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        let value: Option<chrono::NaiveDate> = row.get(0).ok();
        return Ok(value.map(|d| d.format("%Y-%m-%d").to_string()));
    }
    Ok(None)
}

/// `features.build` 与 `signal.compute` 共用的时间窗辅助。
pub fn series_ids_in_workspace(ws: &Workspace) -> Result<Vec<String>> {
    let mut stmt = ws
        .conn
        .prepare("SELECT DISTINCT series_id FROM series_obs ORDER BY series_id")
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query([])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        out.push(
            row.get::<usize, String>(0)
                .map_err(|e| KernelError::internal(e.to_string()))?,
        );
    }
    Ok(out)
}

/// 供测试：把一个 NDJSON 文件直接写入（不经过 release_time 推导）。
#[cfg(test)]
pub fn seed_observations(ws: &Workspace, rows: &[(String, f64)]) {
    for (day, value) in rows {
        ws.conn
            .execute(
                "INSERT OR REPLACE INTO series_obs(series_id, obs_date, value, release_time, source, unit) \
                 VALUES ('market.cn_equity.csi300', CAST(? AS DATE), ?, CAST(? AS TIMESTAMP), 'test', '点')",
                duckdb::params![day, value, format!("{day} 10:00:00")],
            )
            .unwrap();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workspace::Workspace;

    fn temp_ws(name: &str) -> (Workspace, std::path::PathBuf) {
        let path = std::env::temp_dir().join(format!(
            "cbr-kernel-ingest-{name}-{}.duckdb",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        (Workspace::open(&path).expect("open workspace"), path)
    }

    #[test]
    fn derived_term_spread_uses_max_release_time() {
        let (ws, path) = temp_ws("derive");
        ws.conn
            .execute_batch(
                "INSERT INTO series_obs VALUES \
                 ('market.cn_bond.cgb_10y', '2026-06-30', 2.5, '2026-06-30 10:00:00', 't', '%'), \
                 ('market.cn_bond.cgb_2y', '2026-06-30', 1.8, '2026-06-30 12:00:00', 't', '%');",
            )
            .unwrap();
        let catalog = SeriesCatalog::builtin();
        let written = recompute_derived(&ws, &catalog).unwrap();
        assert!(written.contains(&"market.cn_bond.term_spread".to_string()));
        let mut stmt = ws
            .conn
            .prepare("SELECT value, release_time FROM series_obs WHERE series_id = 'market.cn_bond.term_spread'")
            .unwrap();
        let mut rows = stmt.query([]).unwrap();
        let row = rows.next().unwrap().unwrap();
        let value: f64 = row.get(0).unwrap();
        let release: chrono::NaiveDateTime = row.get(1).unwrap();
        assert!((value - 70.0).abs() < 1e-9, "term_spread = (2.5-1.8)*100");
        assert_eq!(release.format("%H:%M:%S").to_string(), "12:00:00");
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn cgb_index_is_cumulative() {
        let (ws, path) = temp_ws("cgbindex");
        ws.conn
            .execute_batch(
                "INSERT INTO series_obs VALUES \
                 ('market.cn_bond.cgb_10y', '2026-06-29', 2.50, '2026-06-29 10:00:00', 't', '%'), \
                 ('market.cn_bond.cgb_10y', '2026-06-30', 2.60, '2026-06-30 10:00:00', 't', '%');",
            )
            .unwrap();
        let catalog = SeriesCatalog::builtin();
        recompute_derived(&ws, &catalog).unwrap();
        let mut stmt = ws
            .conn
            .prepare("SELECT value FROM series_obs WHERE series_id = 'market.cn_bond.cgb_index' ORDER BY obs_date")
            .unwrap();
        let mut rows = stmt.query([]).unwrap();
        let first: f64 = rows.next().unwrap().unwrap().get(0).unwrap();
        let second: f64 = rows.next().unwrap().unwrap().get(0).unwrap();
        assert!((first - 100.0).abs() < 1e-9);
        // -7.5 * (0.1/100) = -0.0075 → exp(-0.0075) * 100
        assert!((second - 100.0 * (-0.0075f64).exp()).abs() < 1e-9);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn csv_ingest_derives_release_time() {
        let (ws, path) = temp_ws("csv");
        let csv_path =
            std::env::temp_dir().join(format!("cbr-kernel-ingest-{}.csv", std::process::id()));
        std::fs::write(
            &csv_path,
            "series_id,obs_date,value\nmarket.cn_equity.csi300,2026-06-30,4025.11\nmarket.cn_equity.csi300,2026-07-01,\n",
        )
        .unwrap();
        let catalog = SeriesCatalog::builtin();
        let result = ingest(
            &ws,
            &catalog,
            "test-source",
            csv_path.to_str().unwrap(),
            Some(&json!({"release_lag_days": 0, "publish_hour": 18, "tz_offset": "+08:00"})),
            "idem-csv-1",
        )
        .unwrap();
        assert_eq!(
            result["series"][0]["rows"], 1,
            "空值行必须被跳过（缺失 ≠ 零值）"
        );
        assert_eq!(
            result["series"][0]["release_time_rule"],
            "obs_date+0 18:00 +08:00"
        );
        let mut stmt = ws
            .conn
            .prepare(
                "SELECT release_time FROM series_obs WHERE series_id = 'market.cn_equity.csi300'",
            )
            .unwrap();
        let mut rows = stmt.query([]).unwrap();
        let release: chrono::NaiveDateTime = rows.next().unwrap().unwrap().get(0).unwrap();
        assert_eq!(
            release.format("%Y-%m-%d %H:%M:%S").to_string(),
            "2026-06-30 10:00:00"
        );
        drop(ws);
        let _ = std::fs::remove_file(path);
        let _ = std::fs::remove_file(csv_path);
    }

    #[test]
    fn derived_series_cannot_be_ingested_directly() {
        let (ws, path) = temp_ws("derivedreject");
        let csv_path =
            std::env::temp_dir().join(format!("cbr-kernel-derived-{}.csv", std::process::id()));
        std::fs::write(
            &csv_path,
            "series_id,obs_date,value\nmarket.cn_bond.term_spread,2026-06-30,70\n",
        )
        .unwrap();
        let catalog = SeriesCatalog::builtin();
        let err = ingest(&ws, &catalog, "t", csv_path.to_str().unwrap(), None, "k").unwrap_err();
        assert_eq!(err.kind, ErrorKind::InvalidParams);
        drop(ws);
        let _ = std::fs::remove_file(path);
        let _ = std::fs::remove_file(csv_path);
    }
}
