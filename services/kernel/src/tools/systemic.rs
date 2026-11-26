//! systemic_risk：ΔCoVaR（分位数回归近似）、MES、简化 Diebold-Yilmaz 溢出指数。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/systemic.py`。

use super::source::DataSource;
use super::{history, param_f64, param_str, param_usize, rv, values_of, ToolOutput};
use crate::error::Result;
use crate::numeric::{
    fit_var, generalized_fevd, mean, quantile, quantile_regression, r, simple_returns,
    spillover_index, Mat,
};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

/// (date, value) 序列 → {date: return}（价格模式丢弃首日）。
fn returns_map(items: &[(String, f64)], values_are: &str) -> BTreeMap<String, f64> {
    if values_are == "price" {
        let vals = values_of(items);
        if vals.len() < 2 {
            return BTreeMap::new();
        }
        let rets = simple_returns(&vals);
        let mut map = BTreeMap::new();
        for (i, ret) in rets.iter().enumerate() {
            map.insert(items[i + 1].0.clone(), *ret);
        }
        map
    } else {
        items.iter().map(|(d, v)| (d.clone(), *v)).collect()
    }
}

/// 多序列按公共日期对齐，返回 (dates, {series: values})。
fn align(
    series: &BTreeMap<String, BTreeMap<String, f64>>,
) -> (Vec<String>, BTreeMap<String, Vec<f64>>) {
    if series.is_empty() {
        return (Vec::new(), BTreeMap::new());
    }
    let mut common: Vec<String> = series
        .values()
        .next()
        .map(|m| m.keys().cloned().collect())
        .unwrap_or_default();
    for map in series.values() {
        common.retain(|d| map.contains_key(d));
    }
    common.sort();
    let aligned = series
        .iter()
        .map(|(name, map)| (name.clone(), common.iter().map(|d| map[d]).collect()))
        .collect();
    (common, aligned)
}

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let market_id = param_str(params, "market_series_id")
        .unwrap_or("market.cn_equity.csi300")
        .to_string();
    let asset_id = param_str(params, "asset_series_id")
        .unwrap_or("market.cn_bond.cgb_index")
        .to_string();
    let lookback = param_usize(params, "lookback", 252);
    let tail_q = param_f64(params, "tail_q", 0.05);
    let dy_window = param_usize(params, "dy_window", 120);
    let dy_lag = param_usize(params, "dy_lag", 1);
    let dy_horizon = param_usize(params, "dy_horizon", 10);
    let values_are = param_str(params, "values_are").unwrap_or("price");

    let market_items = history(source, &market_id, as_of, lookback)?;
    let asset_items = history(source, &asset_id, as_of, lookback)?;
    let market = returns_map(&market_items, values_are);
    let asset = returns_map(&asset_items, values_are);

    let common: Vec<String> = market
        .keys()
        .filter(|d| asset.contains_key(*d))
        .cloned()
        .collect();
    if common.len() < 30 {
        return Err(super::tool_error(format!(
            "insufficient co-movement observations: {} < 30 ({market_id} vs {asset_id})",
            common.len()
        )));
    }
    let m_ret: Vec<f64> = common.iter().map(|d| market[d]).collect();
    let a_ret: Vec<f64> = common.iter().map(|d| asset[d]).collect();
    if !m_ret.iter().all(|v| v.is_finite()) || !a_ret.iter().all(|v| v.is_finite()) {
        return Err(super::tool_error(
            "non-finite returns encountered after alignment",
        ));
    }

    // ---- ΔCoVaR（分位数回归近似） ----
    let q_market = quantile(&m_ret, tail_q);
    let median_market = quantile(&m_ret, 0.5);
    let (intercept, beta, qr_iters) = quantile_regression(&m_ret, &a_ret, tail_q)
        .ok_or_else(|| super::tool_error("quantile regression failed"))?;
    let covar = intercept + beta * q_market;
    let covar_median = intercept + beta * median_market;
    let delta_covar = covar - covar_median;

    // ---- MES ----
    let tail_values: Vec<f64> = m_ret
        .iter()
        .zip(a_ret.iter())
        .filter(|(m, _)| **m <= q_market + 1e-12)
        .map(|(_, a)| *a)
        .collect();
    if tail_values.is_empty() {
        return Err(super::tool_error(
            "no market observations in the tail for MES",
        ));
    }
    let mes = (-mean(&tail_values)).max(0.0);
    let market_var_loss = (-q_market).max(0.0);

    // ---- DY 溢出指数 ----
    let dy_ids: Vec<String> = params
        .get("series_ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_else(|| {
            vec![
                "market.cn_equity.csi300".into(),
                "market.global.sp500".into(),
                "market.fx.usdcny".into(),
                "market.global.vix".into(),
            ]
        });
    let mut dy_data: BTreeMap<String, BTreeMap<String, f64>> = BTreeMap::new();
    let mut dy_missing: Vec<String> = Vec::new();
    for sid in &dy_ids {
        let rets = match history(source, sid, as_of, lookback) {
            Ok(items) => returns_map(&items, values_are),
            Err(_) => BTreeMap::new(),
        };
        if rets.len() < 40 {
            dy_missing.push(sid.clone());
            continue;
        }
        dy_data.insert(sid.clone(), rets);
    }
    if dy_data.len() < 2 {
        return Err(super::tool_error(format!(
            "DY spillover requires >=2 available series; have {:?} (missing={:?})",
            dy_data.keys().collect::<Vec<_>>(),
            dy_missing
        )));
    }
    let (_, aligned) = align(&dy_data);
    let order: Vec<String> = dy_data.keys().cloned().collect();
    let n_series = order.len();
    let mut rows_count = aligned.values().next().map(|v| v.len()).unwrap_or(0);
    if rows_count < dy_lag + n_series + 10 {
        return Err(super::tool_error(
            "insufficient aligned observations for VAR estimation",
        ));
    }
    if rows_count > dy_window {
        rows_count = dy_window;
    }
    let matrix_rows: Vec<Vec<f64>> = (0..rows_count)
        .map(|i| {
            order
                .iter()
                .map(|sid| {
                    let series = &aligned[sid];
                    series[series.len() - rows_count + i]
                })
                .collect()
        })
        .collect();
    let matrix = Mat::from_rows(matrix_rows);
    let (_, a_list, sigma) = fit_var(&matrix, dy_lag)
        .ok_or_else(|| super::tool_error("VAR/FEVD estimation failed: insufficient samples"))?;
    let fevd = generalized_fevd(&a_list, &sigma, dy_horizon);
    let dy_pct = spillover_index(&fevd);
    let dy_index = dy_pct / 100.0;
    let fevd_json: Vec<Value> = (0..fevd.rows)
        .map(|i| Value::Array((0..fevd.cols).map(|j| rv(fevd.at(i, j))).collect()))
        .collect();

    let mut data = Map::new();
    data.insert("market_series_id".into(), json!(market_id));
    data.insert("asset_series_id".into(), json!(asset_id));
    data.insert("values_are".into(), json!(values_are));
    data.insert("lookback".into(), json!(lookback));
    data.insert("tail_q".into(), json!(tail_q));
    data.insert("observations".into(), json!(m_ret.len()));
    data.insert("window_start".into(), json!(common[0]));
    data.insert("window_end".into(), json!(common[common.len() - 1]));
    data.insert("market_var_loss_q".into(), rv(market_var_loss));
    data.insert("asset_covar".into(), rv(covar));
    data.insert("asset_covar_loss".into(), rv((-covar).max(0.0)));
    data.insert("delta_covar".into(), rv(delta_covar));
    data.insert("delta_covar_abs".into(), rv(delta_covar.abs()));
    data.insert("quantile_beta".into(), rv(beta));
    data.insert("quantile_intercept".into(), rv(intercept));
    data.insert("quantile_regression_iters".into(), json!(qr_iters));
    data.insert("mes_q".into(), rv(mes));
    data.insert("tail_observations".into(), json!(tail_values.len()));
    data.insert("dy_spillover_index".into(), rv(dy_index));
    data.insert("dy_spillover_percent".into(), rv(dy_pct));
    data.insert("dy_series_order".into(), json!(order));
    data.insert("dy_missing_series".into(), json!(dy_missing));
    data.insert("dy_window".into(), json!(rows_count));
    data.insert("dy_lag".into(), json!(dy_lag));
    data.insert("dy_horizon".into(), json!(dy_horizon));
    data.insert("dy_fevd_matrix".into(), Value::Array(fevd_json));
    data.insert(
        "unit_map".into(),
        json!({
            "market_var_loss_q": "loss_ratio",
            "asset_covar": "return_ratio",
            "asset_covar_loss": "loss_ratio",
            "delta_covar": "return_ratio",
            "delta_covar_abs": "return_ratio",
            "quantile_beta": "beta",
            "mes_q": "loss_ratio",
            "dy_spillover_index": "ratio_0_1",
            "dy_spillover_percent": "pct",
            "dy_fevd_matrix": "share_0_1",
        }),
    );

    let summary = format!(
        "{market_id}→{asset_id}：市场 {:.0}% 尾部时 ΔCoVaR {:.2}%、MES {:.2}%；DY 溢出指数 {:.1}%（基于 {} 条序列，{} 个观测）。",
        tail_q * 100.0,
        r(delta_covar).unwrap_or(0.0) * 100.0,
        r(mes).unwrap_or(0.0) * 100.0,
        dy_pct,
        order.len(),
        rows_count
    );

    Ok(ToolOutput::new(
        data,
        "ratio",
        r(dy_index),
        format!("系统性风险连通性 @ {as_of}"),
        summary,
    ))
}
