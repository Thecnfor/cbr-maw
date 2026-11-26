//! `features.build`：数值特征构造（仅使用 t 及以前信息），写入 `features` 表。
//!
//! 特征口径对齐旧版 `commorcial/src/cbr/features/numeric.py` 的子集（收益率、已实现波动、
//! 回撤、z-score、利差变动等）。缺失序列**不参与**该日特征计算（标为数据不足而非置 0）。

use crate::error::{KernelError, Result};
use crate::pit::SeriesCatalog;
use crate::workspace::Workspace;
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// 单个序列可产出的特征名（与旧版特征目录对齐的稳定子集）。
const SERIES_FEATURES: [&str; 7] = [
    "ret_5d",
    "ret_20d",
    "vol_20d",
    "maxdd_20d",
    "z_60",
    "chg_5d",
    "chg_20d",
];

fn history(
    ws: &Workspace,
    series_id: &str,
    as_of: &str,
    lookback: usize,
) -> Result<Vec<(String, f64)>> {
    let end = crate::pit::as_of_end_of_day(as_of);
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT obs_date, value FROM series_obs \
             WHERE series_id = ? AND release_time <= CAST(? AS TIMESTAMP) AND value IS NOT NULL \
             ORDER BY obs_date ASC",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![series_id, end])
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
        out.push((day.format("%Y-%m-%d").to_string(), value));
    }
    if out.len() > lookback {
        out = out.split_off(out.len() - lookback);
    }
    Ok(out)
}

fn rolling_std(values: &[f64], window: usize) -> Option<f64> {
    if values.len() < window.max(2) {
        return None;
    }
    let slice = &values[values.len() - window..];
    let mean = slice.iter().sum::<f64>() / slice.len() as f64;
    let var = slice.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / (slice.len() - 1) as f64;
    Some(var.sqrt())
}

fn build_for_series(
    series_id: &str,
    values: &[f64],
    as_of: &str,
    domain: &str,
    unit: &str,
) -> Vec<Value> {
    let n = values.len();
    let mut out = Vec::new();
    let mut push = |name: &str, value: Option<f64>, feature_unit: &str| {
        let Some(value) = value.filter(|v| v.is_finite()) else {
            return; // 数据不足 → 不产出行（不写 0）
        };
        out.push(json!({
            "feature_id": format!("feat_{}_{}", sanitize(series_id), name),
            "series_id": series_id,
            "as_of": as_of,
            "name": name,
            "value": crate::numeric::r(value),
            "unit": feature_unit,
            "domain": domain,
        }));
    };

    let ret = |periods: usize| -> Option<f64> {
        if n <= periods {
            return None;
        }
        let prev = values[n - 1 - periods];
        if prev.abs() <= 1e-12 {
            None
        } else {
            Some(values[n - 1] / prev - 1.0)
        }
    };
    push("ret_5d", ret(5), "ratio");
    push("ret_20d", ret(20), "ratio");

    let returns: Vec<f64> = (1..n)
        .filter_map(|i| {
            if values[i - 1].abs() > 1e-12 {
                Some(values[i] / values[i - 1] - 1.0)
            } else {
                None
            }
        })
        .collect();
    push(
        "vol_20d",
        rolling_std(&returns, 20).map(|s| s * 252.0_f64.sqrt()),
        "ratio_annual",
    );

    if n >= 5 {
        let window = &values[n.saturating_sub(20)..];
        let peak = window.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let drawdown = if peak.abs() > 1e-12 {
            Some((1.0 - values[n - 1] / peak).max(0.0))
        } else {
            None
        };
        push("maxdd_20d", drawdown, "ratio");
    } else {
        push("maxdd_20d", None, "ratio");
    }

    if n >= 60 {
        let window = &values[n - 60..];
        let mean = window.iter().sum::<f64>() / window.len() as f64;
        let var =
            window.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / (window.len() - 1) as f64;
        let std = var.sqrt();
        push(
            "z_60",
            if std > 1e-12 {
                Some((values[n - 1] - mean) / std)
            } else {
                Some(0.0)
            },
            "z",
        );
    } else {
        push("z_60", None, "z");
    }

    let chg = |periods: usize| -> Option<f64> {
        if n <= periods {
            return None;
        }
        Some(values[n - 1] - values[n - periods - 1])
    };
    push("chg_5d", chg(5), unit);
    push("chg_20d", chg(20), unit);
    out
}

fn sanitize(series_id: &str) -> String {
    series_id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches('_')
        .to_string()
}

pub fn build(
    ws: &Workspace,
    catalog: &SeriesCatalog,
    series_ids: &[String],
    as_of: &str,
) -> Result<Value> {
    if series_ids.is_empty() {
        return Err(
            KernelError::invalid_params("series_ids 不能为空").with_detail(json!({
                "reason": "series_ids 不能为空",
                "field": "series_ids",
            })),
        );
    }
    let day = &as_of[..10.min(as_of.len())];
    let mut built: Vec<Value> = Vec::new();
    let mut missing: Vec<&str> = Vec::new();

    for series_id in series_ids {
        let items = history(ws, series_id, as_of, 2000)?;
        if items.is_empty() {
            missing.push(series_id.as_str());
            continue;
        }
        let values: Vec<f64> = items.iter().map(|(_, v)| *v).collect();
        let (domain, unit) = catalog
            .get(series_id)
            .map(|spec| (spec.domain.clone(), spec.unit.clone()))
            .unwrap_or_else(|| (String::new(), String::new()));
        let features = build_for_series(series_id, &values, day, &domain, &unit);
        for feature in &features {
            ws.conn
                .execute(
                    "INSERT OR REPLACE INTO features(feature_id, series_id, as_of, name, value, unit, domain) \
                     VALUES (?, ?, CAST(? AS DATE), ?, ?, ?, ?)",
                    duckdb::params![
                        feature["feature_id"].as_str(),
                        feature["series_id"].as_str(),
                        day,
                        feature["name"].as_str(),
                        feature["value"].as_f64(),
                        feature["unit"].as_str(),
                        feature["domain"].as_str(),
                    ],
                )
                .map_err(|e| KernelError::internal(e.to_string()))?;
        }
        built.extend(features);
    }

    if built.is_empty() {
        return Err(KernelError::data_missing(format!(
            "所有请求序列在 {day} 均无可用观测（缺失 ≠ 零值）"
        ))
        .with_detail(json!({"reason": "序列在该时点无观测", "missing_series": missing})));
    }

    let feature_ids: Vec<Value> = built.iter().map(|f| f["feature_id"].clone()).collect();
    Ok(json!({
        "built": feature_ids.len(),
        "feature_ids": feature_ids,
        "missing_series": missing,
        "available_features": SERIES_FEATURES,
    }))
}

/// 供 `signal.compute` 读取特征宽表（按 feature_id 聚合）。
pub fn load_feature_row(ws: &Workspace, as_of: &str) -> Result<BTreeMap<String, f64>> {
    let mut stmt = ws
        .conn
        .prepare("SELECT feature_id, value FROM features WHERE as_of = CAST(? AS DATE) AND value IS NOT NULL")
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![&as_of[..10.min(as_of.len())]])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut out = BTreeMap::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        let key: String = row
            .get(0)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let value: f64 = row
            .get(1)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        out.insert(key, value);
    }
    Ok(out)
}

/// 便捷：从库读取 CFSI 维度值（供 signal 的 dims 归因，避免重复实现）。
///
/// **必须精确匹配 as_of**：这里只用于「复用当日已算好的 CFSI」。
/// 用 `as_of <= ?` 取最近一行会让某日算出的值被之后所有日期复用，
/// 并把陈旧值写进新日期的历史行——信号在整段时间里恒定，判别力归零。
pub fn load_cfsi_row(ws: &Workspace, as_of: &str) -> Result<Option<Value>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT cfsi, level, tau, dims, missing_dims, limitations FROM cfsi_history \
             WHERE as_of = CAST(? AS DATE)",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query(duckdb::params![&as_of[..10.min(as_of.len())]])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    if let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        return Ok(Some(json!({
            "cfsi": row.get::<usize, f64>(0).ok(),
            "level": row.get::<usize, String>(1).ok(),
            "tau": row.get::<usize, f64>(2).ok(),
            "dims": row.get::<usize, String>(3).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
            "missing_dims": row.get::<usize, String>(4).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
            "limitations": row.get::<usize, String>(5).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
        })));
    }
    Ok(None)
}

/// 把 CFSI 结果写入 `cfsi_history`（供 `db.query` 的 `cfsi_history` 视图）。
pub fn persist_cfsi(ws: &Workspace, as_of: &str, cfsi: &Value) -> Result<()> {
    ws.conn
        .execute(
            "INSERT OR REPLACE INTO cfsi_history(as_of, cfsi, level, tau, dims, missing_dims, limitations, index_version, label_version) \
             VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?)",
            duckdb::params![
                &as_of[..10.min(as_of.len())],
                cfsi["cfsi"].as_f64(),
                cfsi["level"].as_str(),
                cfsi["tau"].as_f64(),
                cfsi["dims"].to_string(),
                cfsi["missing_dims"].to_string(),
                cfsi["limitations"].to_string(),
                cfsi["provenance"]["index_version"].as_str(),
                cfsi["provenance"]["label_version"].as_str(),
            ],
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::ErrorKind;
    use crate::workspace::Workspace;

    fn temp_ws(name: &str) -> (Workspace, std::path::PathBuf) {
        let path = std::env::temp_dir().join(format!(
            "cbr-kernel-features-{name}-{}.duckdb",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        (Workspace::open(&path).expect("open workspace"), path)
    }

    #[test]
    fn cfsi_row_lookup_is_exact_not_latest_at_or_before() {
        // 回归：曾用 `as_of <= ?` 取最近一行，导致某日算出的 CFSI 被之后
        // 所有日期复用（信号恒定 → 判别力归零）。必须精确匹配。
        let (ws, path) = temp_ws("cfsi-exact");
        for (day, value) in [("2026-01-05", 61.5_f64), ("2026-01-06", 72.25)] {
            persist_cfsi(
                &ws,
                day,
                &json!({
                    "cfsi": value,
                    "level": "low",
                    "tau": 91.5,
                    "dims": {"dim_equity": {"value": 0.4}},
                    "missing_dims": [],
                    "limitations": [],
                    "provenance": {"index_version": "cfsi-v1", "label_version": "stress_pca_q90"},
                }),
            )
            .unwrap();
        }
        let first = load_cfsi_row(&ws, "2026-01-05").unwrap().unwrap();
        assert_eq!(first["cfsi"].as_f64(), Some(61.5));
        // 更晚的日期不得复用前一日的值。
        let later = load_cfsi_row(&ws, "2026-01-07").unwrap();
        assert!(later.is_none(), "未计算的日期不得复用历史行");
        let exact = load_cfsi_row(&ws, "2026-01-06").unwrap().unwrap();
        assert_eq!(exact["cfsi"].as_f64(), Some(72.25));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn builds_features_and_skips_insufficient_history() {
        let (ws, path) = temp_ws("build");
        let base = chrono::NaiveDate::from_ymd_opt(2026, 1, 1).unwrap();
        for i in 0..80 {
            let day = base + chrono::Duration::days(i);
            ws.conn
                .execute(
                    "INSERT INTO series_obs VALUES ('market.cn_equity.csi300', CAST(? AS DATE), ?, CAST(? AS TIMESTAMP), 't', '点')",
                    duckdb::params![day.format("%Y-%m-%d").to_string(), 3000.0 + i as f64, format!("{} 10:00:00", day.format("%Y-%m-%d"))],
                )
                .unwrap();
        }
        let catalog = SeriesCatalog::builtin();
        let result = build(
            &ws,
            &catalog,
            &["market.cn_equity.csi300".to_string()],
            "2026-03-21",
        )
        .unwrap();
        assert!(result["built"].as_u64().unwrap() >= 6);
        let features = result["feature_ids"].as_array().unwrap();
        assert!(features
            .iter()
            .any(|f| f.as_str().unwrap().ends_with("ret_5d")));
        assert!(features
            .iter()
            .any(|f| f.as_str().unwrap().ends_with("z_60")));
        drop(ws);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn missing_series_fails_explicitly() {
        let (ws, path) = temp_ws("missing");
        let catalog = SeriesCatalog::builtin();
        let err = build(
            &ws,
            &catalog,
            &["market.fx.usdcny".to_string()],
            "2026-03-21",
        )
        .unwrap_err();
        assert_eq!(err.kind, ErrorKind::DataMissing);
        drop(ws);
        let _ = std::fs::remove_file(path);
    }
}
