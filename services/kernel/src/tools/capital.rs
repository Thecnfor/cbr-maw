//! capital_flow：北向/南向异常净流入 z-score、同步撤离、集中度、AH 溢价。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/capital.py`。南向与 AH 溢价缺失时降级为 None，
//! 并在 `missing_series` 显式标注（不编造数值）。

use super::source::DataSource;
use super::{history, param_f64, param_str, param_usize, rv, values_of, ToolOutput};
use crate::error::Result;
use crate::numeric::{concentration_metrics, mean, percentile_rank, r, std_ddof1, zscore_latest};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

const AH_CHANGE_WINDOW: usize = 20;

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let inflow_id = param_str(params, "inflow_series_id")
        .unwrap_or("crossborder.flows.northbound_net")
        .to_string();
    let outflow_id = param_str(params, "outflow_series_id")
        .unwrap_or("crossborder.flows.southbound_net")
        .to_string();
    let ah_id = param_str(params, "ah_premium_series_id")
        .unwrap_or("crossborder.flows.ah_premium")
        .to_string();
    let lookback = param_usize(params, "lookback", 60);
    let z_window = param_usize(params, "z_window", 60);
    let anomaly_z = param_f64(params, "anomaly_z", 1.5);
    let top_n = param_usize(params, "top_n", 5);
    let flow_unit = param_str(params, "flow_unit").unwrap_or("亿元").to_string();

    let inflow = history(source, &inflow_id, as_of, lookback)?;
    let inflow_vals = values_of(&inflow);
    let z_inflow = zscore_latest(&inflow_vals, z_window).ok_or_else(|| {
        super::tool_error(format!(
            "insufficient observations for z-score on {inflow_id}: {}",
            inflow_vals.len()
        ))
    })?;
    let anomaly_direction = if z_inflow <= -anomaly_z {
        "outflow"
    } else if z_inflow >= anomaly_z {
        "inflow"
    } else {
        "none"
    };
    let (top_share, hhi) = concentration_metrics(&inflow_vals, top_n);

    let mut missing: Vec<String> = Vec::new();
    let mut data = Map::new();
    data.insert("inflow_series_id".into(), json!(inflow_id));
    data.insert("lookback".into(), json!(lookback));
    data.insert("z_window".into(), json!(z_window));
    data.insert("anomaly_z".into(), json!(anomaly_z));
    data.insert("flow_unit".into(), json!(flow_unit));
    data.insert("observations".into(), json!(inflow_vals.len()));
    data.insert("window_start".into(), json!(inflow[0].0));
    data.insert("window_end".into(), json!(inflow[inflow.len() - 1].0));
    data.insert(
        "net_inflow_latest".into(),
        rv(inflow_vals[inflow_vals.len() - 1]),
    );
    data.insert("net_inflow_mean".into(), rv(mean(&inflow_vals)));
    data.insert("net_inflow_std".into(), rv(std_ddof1(&inflow_vals)));
    data.insert("net_inflow_z".into(), rv(z_inflow));
    data.insert("anomaly_direction".into(), json!(anomaly_direction));
    data.insert("is_anomaly".into(), json!(anomaly_direction != "none"));
    data.insert("concentration_top_share".into(), rv(top_share));
    data.insert("flow_hhi".into(), rv(hhi));
    data.insert("concentration_top_n".into(), json!(top_n));

    // ---- 南向资金：同步撤离指标 ----
    let north_map: BTreeMap<String, f64> = inflow.iter().cloned().collect();
    match history(source, &outflow_id, as_of, lookback) {
        Ok(outflow) => {
            let south_map: BTreeMap<String, f64> = outflow.into_iter().collect();
            let mut joint: Vec<String> = north_map
                .keys()
                .filter(|d| south_map.contains_key(*d))
                .cloned()
                .collect();
            joint.sort();
            if joint.len() > lookback {
                joint = joint.split_off(joint.len() - lookback);
            }
            if joint.len() >= 10 {
                let both_out = joint
                    .iter()
                    .filter(|d| north_map[*d] < 0.0 && south_map[*d] < 0.0)
                    .count() as f64;
                let sync_share = both_out / joint.len() as f64;
                let joint_values: Vec<f64> =
                    joint.iter().map(|d| north_map[d] + south_map[d]).collect();
                let last = joint[joint.len() - 1].clone();
                data.insert("outflow_series_id".into(), json!(outflow_id));
                data.insert("southbound_net_latest".into(), rv(south_map[&last]));
                data.insert("synchronized_outflow_share".into(), rv(sync_share));
                data.insert(
                    "synchronized_outflow_flag".into(),
                    json!(north_map[&last] < 0.0 && south_map[&last] < 0.0),
                );
                data.insert(
                    "joint_net_flow_latest".into(),
                    rv(joint_values[joint_values.len() - 1]),
                );
                data.insert(
                    "joint_flow_z".into(),
                    zscore_latest(&joint_values, z_window)
                        .map(rv)
                        .unwrap_or(Value::Null),
                );
                data.insert("joint_observations".into(), json!(joint.len()));
            } else {
                missing.push(outflow_id.clone());
            }
        }
        Err(_) => missing.push(outflow_id.clone()),
    }

    // ---- AH 溢价（可选序列） ----
    match history(source, &ah_id, as_of, lookback) {
        Ok(ah) => {
            let ah_vals = values_of(&ah);
            let change_idx = ah_vals
                .len()
                .saturating_sub(1 + AH_CHANGE_WINDOW.min(ah_vals.len() - 1));
            data.insert("ah_premium_series_id".into(), json!(ah_id));
            data.insert("ah_premium_latest".into(), rv(ah_vals[ah_vals.len() - 1]));
            data.insert(
                "ah_premium_z".into(),
                zscore_latest(&ah_vals, z_window)
                    .map(rv)
                    .unwrap_or(Value::Null),
            );
            data.insert(
                "ah_premium_percentile".into(),
                percentile_rank(&ah_vals).map(rv).unwrap_or(Value::Null),
            );
            data.insert(
                "ah_premium_change_20d".into(),
                rv(ah_vals[ah_vals.len() - 1] - ah_vals[change_idx]),
            );
            data.insert("ah_premium_observations".into(), json!(ah_vals.len()));
        }
        Err(_) => {
            data.insert("ah_premium_series_id".into(), json!(ah_id));
            for key in [
                "ah_premium_latest",
                "ah_premium_z",
                "ah_premium_percentile",
                "ah_premium_change_20d",
            ] {
                data.insert(key.into(), Value::Null);
            }
            missing.push(ah_id.clone());
        }
    }

    data.insert("missing_series".into(), json!(missing));
    data.insert(
        "unit_map".into(),
        json!({
            "net_inflow_latest": flow_unit,
            "net_inflow_mean": flow_unit,
            "net_inflow_std": flow_unit,
            "net_inflow_z": "z",
            "concentration_top_share": "ratio_0_1",
            "flow_hhi": "index_0_1",
            "southbound_net_latest": flow_unit,
            "synchronized_outflow_share": "ratio_0_1",
            "joint_net_flow_latest": flow_unit,
            "joint_flow_z": "z",
            "ah_premium_latest": "点",
            "ah_premium_z": "z",
            "ah_premium_percentile": "quantile_0_1",
            "ah_premium_change_20d": "点_变化",
        }),
    );

    let mut summary = format!(
        "{inflow_id} 最新净流入 {:.2}{flow_unit}，z={z_inflow:.2}（{}，阈值 ±{anomaly_z}）；资金流前 {top_n} 日集中度 {:.2}",
        r(inflow_vals[inflow_vals.len() - 1]).unwrap_or(0.0),
        if anomaly_direction != "none" { format!("异常{anomaly_direction}") } else { "正常".to_string() },
        r(top_share).unwrap_or(0.0)
    );
    if let Some(share) = data
        .get("synchronized_outflow_share")
        .and_then(|v| v.as_f64())
    {
        summary.push_str(&format!(
            "；北向/南向同时净流出日占比 {:.0}%",
            share * 100.0
        ));
    }
    if let Some(ah) = data.get("ah_premium_latest").and_then(|v| v.as_f64()) {
        summary.push_str(&format!("；AH 溢价指数 {ah:.2} 点"));
    }
    summary.push('。');

    Ok(ToolOutput::new(
        data,
        "z",
        r(z_inflow),
        format!("跨境资金流状态 @ {as_of}"),
        summary,
    ))
}
