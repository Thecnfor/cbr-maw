//! funding_cost：信用利差代理、融资成本变化（bp）、再融资窗口估计。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/funding.py`。

use super::source::DataSource;
use super::{history, param_f64, param_i64, param_str, param_usize, rv, values_of, ToolOutput};
use crate::error::Result;
use crate::numeric::{median, percentile_rank, r};
use serde_json::{json, Map, Value};

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let spread_id = param_str(params, "spread_series_id")
        .unwrap_or("rates.credit.aa_spread")
        .to_string();
    let lookback = param_usize(params, "lookback", 252);
    let momentum_window = param_usize(params, "momentum_window", 20);
    let spread_unit = param_str(params, "spread_unit").unwrap_or("bp");
    let cost_jump_bp = param_f64(params, "cost_jump_bp", 50.0);
    let cost_medium_bp = param_f64(params, "cost_medium_bp", 25.0);
    let refinancing_horizon_days = param_i64(params, "refinancing_horizon_days", 90);

    let items = history(source, &spread_id, as_of, lookback)?;
    let levels = values_of(&items);
    if levels.len() < 20usize.max(momentum_window + 5) {
        return Err(super::tool_error(format!(
            "insufficient credit spread observations for {spread_id}: {}",
            levels.len()
        )));
    }

    let (spread_pct, spread_bp): (Vec<f64>, Vec<f64>) = if spread_unit == "pct" {
        (levels.clone(), levels.iter().map(|v| v * 100.0).collect())
    } else {
        (levels.iter().map(|v| v / 100.0).collect(), levels.clone())
    };

    let latest_bp = spread_bp[spread_bp.len() - 1];
    let latest_pct = spread_pct[spread_pct.len() - 1];
    let base_idx = levels.len().saturating_sub(1 + momentum_window);
    let change_bp = spread_bp[spread_bp.len() - 1] - spread_bp[base_idx];
    let momentum_bp_per_day = change_bp / (levels.len() - 1 - base_idx).max(1) as f64;
    let median_bp = median(&spread_bp);
    let pct_rank = percentile_rank(&spread_bp);

    // ---- 再融资窗口估计（确定性规则） ----
    let (window_days, window_status) = if latest_bp <= median_bp {
        let gap_bp = median_bp - latest_bp;
        if momentum_bp_per_day > 0.0 {
            let estimate_days = (gap_bp / momentum_bp_per_day).ceil();
            (
                (refinancing_horizon_days as f64).min(estimate_days) as i64,
                "closing",
            )
        } else {
            (refinancing_horizon_days, "open")
        }
    } else {
        (0, "closed")
    };

    let stress_level = if change_bp >= cost_jump_bp {
        "high"
    } else if change_bp >= cost_medium_bp {
        "medium"
    } else {
        "low"
    };

    let mut data = Map::new();
    data.insert("spread_series_id".into(), json!(spread_id));
    data.insert("lookback".into(), json!(lookback));
    data.insert("momentum_window".into(), json!(momentum_window));
    data.insert("spread_unit".into(), json!(spread_unit));
    data.insert("observations".into(), json!(levels.len()));
    data.insert("window_start".into(), json!(items[0].0));
    data.insert("window_end".into(), json!(items[items.len() - 1].0));
    data.insert("credit_spread_pct".into(), rv(latest_pct));
    data.insert("credit_spread_bp".into(), rv(latest_bp));
    data.insert(
        "credit_spread_min_bp".into(),
        rv(spread_bp.iter().copied().fold(f64::INFINITY, f64::min)),
    );
    data.insert(
        "credit_spread_max_bp".into(),
        rv(spread_bp.iter().copied().fold(f64::NEG_INFINITY, f64::max)),
    );
    data.insert("credit_spread_median_bp".into(), rv(median_bp));
    data.insert(
        "spread_percentile".into(),
        pct_rank.map(rv).unwrap_or(serde_json::Value::Null),
    );
    data.insert("funding_cost_change_bp".into(), rv(change_bp));
    data.insert("momentum_bp_per_day".into(), rv(momentum_bp_per_day));
    data.insert("refinancing_window_days".into(), json!(window_days));
    data.insert("refinancing_window_status".into(), json!(window_status));
    data.insert(
        "refinancing_horizon_days".into(),
        json!(refinancing_horizon_days),
    );
    data.insert("stress_level".into(), json!(stress_level));
    data.insert(
        "thresholds".into(),
        json!({
            "cost_jump_bp": cost_jump_bp,
            "cost_medium_bp": cost_medium_bp,
            "refinancing_horizon_days": refinancing_horizon_days,
        }),
    );
    data.insert(
        "unit_map".into(),
        json!({
            "credit_spread_pct": "pct",
            "credit_spread_bp": "bp",
            "credit_spread_min_bp": "bp",
            "credit_spread_max_bp": "bp",
            "credit_spread_median_bp": "bp",
            "spread_percentile": "quantile_0_1",
            "funding_cost_change_bp": "bp",
            "momentum_bp_per_day": "bp_per_day",
            "refinancing_window_days": "trading_days",
        }),
    );

    let summary = format!(
        "{spread_id} 最新信用利差 {latest_bp:.1}bp（近 {} 期分位 {:.0}%），{momentum_window} 期变化 {change_bp:+.1}bp，融资压力档位={stress_level}；再融资窗口 {window_status}（约 {window_days} 个交易日）。",
        levels.len(),
        r(pct_rank.unwrap_or(0.0)).unwrap_or(0.0) * 100.0
    );

    Ok(ToolOutput::new(
        data,
        "bp",
        r(change_bp),
        format!("融资成本与再融资窗口 @ {as_of}"),
        summary,
    ))
}
