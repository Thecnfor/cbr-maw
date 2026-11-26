//! risk_measure：年化波动率、历史/参数 VaR、CVaR、最大回撤、压力分位。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/risk.py`。单位约定：VaR/CVaR 以「损失为正数」
//! 的比率表示；最大回撤为正幅度。

use super::source::DataSource;
use super::{history, param_f64, param_i64, param_str, param_usize, rv, values_of, ToolOutput};
use crate::error::Result;
use crate::numeric::{
    annualized_volatility, distribution_summary, historical_tail, max_drawdown,
    max_drawdown_from_returns, parametric_tail, quantile, r, returns_percentile, simple_returns,
};
use serde_json::{json, Map, Value};

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let series_id = param_str(params, "series_id")
        .unwrap_or("market.cn_equity.csi300")
        .to_string();
    let lookback = param_usize(params, "lookback", 252);
    let annualization = param_i64(params, "annualization", 252);
    let confidence = param_f64(params, "confidence", 0.95);
    let horizon_days = param_i64(params, "horizon_days", 1);
    let values_are = param_str(params, "values_are").unwrap_or("price");
    let min_observations = param_usize(params, "min_observations", 20);

    let items = history(source, &series_id, as_of, lookback)?;
    let values = values_of(&items);
    if values.len() < 2 {
        return Err(super::tool_error(format!(
            "series {series_id} has <2 observations as of {as_of}"
        )));
    }

    let (mut returns, mdd) = if values_are == "price" {
        (simple_returns(&values), max_drawdown(&values))
    } else {
        (values.clone(), max_drawdown_from_returns(&values))
    };
    returns.retain(|v| v.is_finite());
    if returns.len() < min_observations {
        return Err(super::tool_error(format!(
            "insufficient return observations for {series_id}: {} < min_observations={min_observations}",
            returns.len()
        )));
    }

    let (var_hist, cvar_hist, _) = historical_tail(&returns, confidence, horizon_days);
    let (var_param, cvar_param) = parametric_tail(&returns, confidence, horizon_days);
    let vol_ann = annualized_volatility(&returns, annualization);
    let mut dist = Map::new();
    for (k, v) in distribution_summary(&returns) {
        dist.insert(k, v);
    }

    let mut data = Map::new();
    data.insert("series_id".into(), json!(series_id));
    data.insert("values_are".into(), json!(values_are));
    data.insert("lookback".into(), json!(lookback));
    data.insert("observations".into(), json!(returns.len()));
    data.insert("window_start".into(), json!(items[0].0));
    data.insert("window_end".into(), json!(items[items.len() - 1].0));
    data.insert("annualization".into(), json!(annualization));
    data.insert("confidence".into(), json!(confidence));
    data.insert("horizon_days".into(), json!(horizon_days));
    data.insert("annualized_volatility".into(), rv(vol_ann));
    data.insert("var_hist".into(), rv(var_hist));
    data.insert("cvar_hist".into(), rv(cvar_hist));
    data.insert("var_param".into(), rv(var_param));
    data.insert("cvar_param".into(), rv(cvar_param));
    data.insert("max_drawdown".into(), rv(mdd));
    data.insert(
        "stress_quantiles".into(),
        json!({
            "q01": rv(quantile(&returns, 0.01)),
            "q05": rv(quantile(&returns, 0.05)),
            "q10": rv(quantile(&returns, 0.10)),
        }),
    );
    data.insert("latest_return".into(), rv(returns[returns.len() - 1]));
    data.insert(
        "mean_daily_return".into(),
        rv(crate::numeric::mean(&returns)),
    );
    data.insert(
        "current_return_percentile".into(),
        returns_percentile(&returns).map(rv).unwrap_or(Value::Null),
    );
    data.insert("distribution".into(), Value::Object(dist));
    data.insert(
        "unit_map".into(),
        json!({
            "annualized_volatility": "ratio_annual",
            "var_hist": "loss_ratio",
            "cvar_hist": "loss_ratio",
            "var_param": "loss_ratio",
            "cvar_param": "loss_ratio",
            "max_drawdown": "loss_ratio",
            "stress_quantiles": "return_ratio",
            "latest_return": "return_ratio",
            "mean_daily_return": "return_ratio",
            "current_return_percentile": "quantile_0_1",
        }),
    );

    let summary = format!(
        "{series_id} 近 {} 个收益观测：年化波动率 {:.2}%，{:.0}% {}日历史 VaR {:.2}%、CVaR {:.2}%，最大回撤 {:.2}%。",
        returns.len(),
        r(vol_ann).unwrap_or(0.0) * 100.0,
        confidence * 100.0,
        horizon_days,
        r(var_hist).unwrap_or(0.0) * 100.0,
        r(cvar_hist).unwrap_or(0.0) * 100.0,
        r(mdd).unwrap_or(0.0) * 100.0
    );

    Ok(ToolOutput::new(
        data,
        "loss_ratio",
        r(var_hist),
        format!("风险测度：{series_id} @ {as_of}"),
        summary,
    ))
}
