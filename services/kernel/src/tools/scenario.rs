//! scenario：给定冲击的情景映射与压力传导（线性 + 历史类比）。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/scenario.py`。

use super::source::DataSource;
use super::{history, param_f64, param_i64, param_str, param_usize, rv, ToolOutput};
use crate::error::Result;
use crate::numeric::{mean, ols, quantile, r, simple_returns, std_ddof1, Mat};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

fn return_map(items: &[(String, f64)], values_are: &str) -> BTreeMap<String, f64> {
    if values_are == "price" {
        let vals: Vec<f64> = items.iter().map(|(_, v)| *v).collect();
        if vals.len() < 2 {
            return BTreeMap::new();
        }
        let rets = simple_returns(&vals);
        rets.iter()
            .enumerate()
            .map(|(i, ret)| (items[i + 1].0.clone(), *ret))
            .collect()
    } else {
        items.iter().map(|(d, v)| (d.clone(), *v)).collect()
    }
}

/// 利差水平序列 → 利差变化（bp）。
fn spread_change_map(items: &[(String, f64)], spread_unit: &str) -> BTreeMap<String, f64> {
    let vals: Vec<f64> = items.iter().map(|(_, v)| *v).collect();
    if vals.len() < 2 {
        return BTreeMap::new();
    }
    let factor = if spread_unit == "pct" { 100.0 } else { 1.0 };
    (0..vals.len() - 1)
        .map(|i| (items[i + 1].0.clone(), (vals[i + 1] - vals[i]) * factor))
        .collect()
}

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let target_id = param_str(params, "target_series_id")
        .unwrap_or("market.cn_equity.csi300")
        .to_string();
    let us_id = param_str(params, "us_equity_series_id")
        .unwrap_or("market.global.sp500")
        .to_string();
    let fx_id = param_str(params, "fx_series_id")
        .unwrap_or("market.fx.usdcny")
        .to_string();
    let spread_id = param_str(params, "spread_series_id")
        .unwrap_or("rates.credit.aa_spread")
        .to_string();
    let lookback = param_usize(params, "lookback", 252);
    let us_equity_drop_pct = param_f64(params, "us_equity_drop_pct", 10.0);
    let fx_depreciation_pct = param_f64(params, "fx_depreciation_pct", 5.0);
    let spread_widening_bp = param_f64(params, "spread_widening_bp", 100.0);
    let method = param_str(params, "method").unwrap_or("both");
    let analog_k = param_usize(params, "analog_k", 10);
    let spread_unit = param_str(params, "spread_unit").unwrap_or("bp");
    let min_observations = param_usize(params, "min_observations", 60);
    let values_are = param_str(params, "values_are").unwrap_or("price");
    let _ = param_i64(params, "unused", 0);

    let target_items = history(source, &target_id, as_of, lookback)?;
    let us_items = history(source, &us_id, as_of, lookback)?;
    let fx_items = history(source, &fx_id, as_of, lookback)?;
    let spread_items = history(source, &spread_id, as_of, lookback)?;

    let target_map = return_map(&target_items, values_are);
    let us_map = return_map(&us_items, values_are);
    let fx_map = return_map(&fx_items, "price");
    let spread_map = spread_change_map(&spread_items, spread_unit);

    let mut common: Vec<String> = target_map.keys().cloned().collect();
    common
        .retain(|d| us_map.contains_key(d) && fx_map.contains_key(d) && spread_map.contains_key(d));
    common.sort();
    if common.len() < min_observations {
        return Err(super::tool_error(format!(
            "insufficient aligned scenario observations: {} < min_observations={min_observations}",
            common.len()
        )));
    }

    let y: Vec<f64> = common.iter().map(|d| target_map[d]).collect();
    let factors = Mat::from_rows(
        common
            .iter()
            .map(|d| vec![us_map[d], fx_map[d], spread_map[d]])
            .collect(),
    );
    let factor_names = ["us_equity_return", "fx_change", "spread_change_bp"];
    let shocks = json!({
        "us_equity_drop_pct": us_equity_drop_pct,
        "fx_depreciation_pct": fx_depreciation_pct,
        "spread_widening_bp": spread_widening_bp,
    });
    let shock_vector = [
        -us_equity_drop_pct / 100.0,
        fx_depreciation_pct / 100.0,
        spread_widening_bp,
    ];
    if !y.iter().all(|v| v.is_finite()) || !factors.data.iter().all(|v| v.is_finite()) {
        return Err(super::tool_error(
            "non-finite values encountered in aligned scenario data",
        ));
    }

    // ---- 线性映射 ----
    let (intercept, betas, r2) =
        ols(&y, &factors).ok_or_else(|| super::tool_error("linear scenario regression failed"))?;
    let mut contributions = Map::new();
    for (i, name) in factor_names.iter().enumerate() {
        contributions.insert((*name).to_string(), rv(betas[i] * shock_vector[i]));
    }
    let expected_target_return: f64 = (0..factor_names.len())
        .map(|i| betas[i] * shock_vector[i])
        .sum();
    let mut beta_map = Map::new();
    for (i, name) in factor_names.iter().enumerate() {
        beta_map.insert((*name).to_string(), rv(betas[i]));
    }
    let linear_payload = json!({
        "expected_target_return": rv(expected_target_return),
        "contributions": Value::Object(contributions),
        "betas": Value::Object(beta_map),
        "intercept": rv(intercept),
        "r2": rv(r2),
        "shock_vector": {
            "us_equity_return": rv(shock_vector[0]),
            "fx_change": rv(shock_vector[1]),
            "spread_change_bp": rv(shock_vector[2]),
        },
    });

    // ---- 历史类比情景 ----
    let cols: Vec<Vec<f64>> = (0..3).map(|c| factors.col(c)).collect();
    let means: Vec<f64> = cols.iter().map(|c| mean(c)).collect();
    let stds: Vec<f64> = cols.iter().map(|c| std_ddof1(c)).collect();
    let safe_stds: Vec<f64> = stds
        .iter()
        .map(|s| if *s > 1e-12 { *s } else { 1.0 })
        .collect();
    let z_shock: Vec<f64> = (0..3)
        .map(|i| (shock_vector[i] - means[i]) / safe_stds[i])
        .collect();
    let mut distances: Vec<(f64, usize)> = Vec::with_capacity(common.len());
    for row in 0..common.len() {
        let mut acc = 0.0;
        for c in 0..3 {
            let z = (factors.at(row, c) - means[c]) / safe_stds[c];
            acc += (z - z_shock[c]) * (z - z_shock[c]);
        }
        distances.push((acc.sqrt(), row));
    }
    distances.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.1.cmp(&b.1))
    });
    let k = analog_k.min(common.len()).max(1);
    let analog_idx: Vec<usize> = distances.iter().take(k).map(|(_, idx)| *idx).collect();
    let analog_returns: Vec<f64> = analog_idx.iter().map(|i| y[*i]).collect();
    let mut analog_factors = Map::new();
    for (i, name) in factor_names.iter().enumerate() {
        let mean_z = mean(
            &analog_idx
                .iter()
                .map(|row| (factors.at(*row, i) - means[i]) / safe_stds[i])
                .collect::<Vec<_>>(),
        );
        analog_factors.insert((*name).to_string(), rv(means[i] + mean_z * safe_stds[i]));
    }
    let historical_payload = json!({
        "analog_count": k,
        "analog_mean_return": rv(mean(&analog_returns)),
        "analog_median_return": rv(quantile(&analog_returns, 0.5)),
        "analog_worst_return": rv(analog_returns.iter().copied().fold(f64::INFINITY, f64::min)),
        "analog_best_return": rv(analog_returns.iter().copied().fold(f64::NEG_INFINITY, f64::max)),
        "analog_dates": analog_idx.iter().map(|i| common[*i].clone()).collect::<Vec<_>>(),
        "analog_mean_factors": Value::Object(analog_factors),
        "shock_distance_min": rv(distances[0].0),
    });

    let linear = if method == "linear" || method == "both" {
        Some(linear_payload.clone())
    } else {
        None
    };
    let historical = if method == "historical" || method == "both" {
        Some(historical_payload.clone())
    } else {
        None
    };
    let primary_return = if linear.is_some() {
        expected_target_return
    } else {
        historical_payload["analog_mean_return"]
            .as_f64()
            .unwrap_or(0.0)
    };
    let stress_transmission = json!({
        "target_return_linear": if linear.is_some() { rv(expected_target_return) } else { Value::Null },
        "target_return_analog_mean": if historical.is_some() { historical_payload["analog_mean_return"].clone() } else { Value::Null },
        "target_return_analog_worst": if historical.is_some() { historical_payload["analog_worst_return"].clone() } else { Value::Null },
        "primary_method": if method == "linear" { "linear" } else if method == "historical" { "historical" } else { "linear" },
    });

    let mut data = Map::new();
    data.insert("target_series_id".into(), json!(target_id));
    data.insert("us_equity_series_id".into(), json!(us_id));
    data.insert("fx_series_id".into(), json!(fx_id));
    data.insert("spread_series_id".into(), json!(spread_id));
    data.insert("lookback".into(), json!(lookback));
    data.insert("observations".into(), json!(common.len()));
    data.insert("window_start".into(), json!(common[0]));
    data.insert("window_end".into(), json!(common[common.len() - 1]));
    data.insert("method".into(), json!(method));
    data.insert("values_are".into(), json!(values_are));
    data.insert("spread_unit".into(), json!(spread_unit));
    data.insert("analog_k".into(), json!(analog_k));
    data.insert("shocks".into(), shocks);
    data.insert("linear".into(), linear.unwrap_or(Value::Null));
    data.insert(
        "historical".into(),
        historical.clone().unwrap_or(Value::Null),
    );
    data.insert("stress_transmission".into(), stress_transmission);
    data.insert(
        "unit_map".into(),
        json!({
            "expected_target_return": "ratio",
            "contributions": "ratio",
            "analog_mean_return": "ratio",
            "analog_worst_return": "ratio",
            "spread_change_bp": "bp",
        }),
    );

    let mut summary = format!(
        "情景冲击（美股 -{us_equity_drop_pct:.1}%、人民币贬值 {fx_depreciation_pct:.1}%、利差 +{spread_widening_bp:.0}bp）→ {target_id} 线性映射收益 {:+.2}%",
        expected_target_return * 100.0
    );
    if historical.is_some() {
        summary.push_str(&format!(
            "；历史近邻 {k} 日平均 {:+.2}%、最差 {:+.2}%",
            historical_payload["analog_mean_return"]
                .as_f64()
                .unwrap_or(0.0)
                * 100.0,
            historical_payload["analog_worst_return"]
                .as_f64()
                .unwrap_or(0.0)
                * 100.0
        ));
    }
    summary.push('。');

    Ok(ToolOutput::new(
        data,
        "ratio",
        r(primary_return),
        format!("情景压力测试 @ {as_of}"),
        summary,
    ))
}
