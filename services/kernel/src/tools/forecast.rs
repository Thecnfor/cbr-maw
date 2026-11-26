//! forecast：只读共享多模态风险信号（P1 产物）并输出统一 Evidence。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/forecast.py`。信号不可用时**显式失败**，
//! 不用规则模板冒充模型结论。

use super::source::DataSource;
use super::{param_bool, param_i64, rv, ToolOutput};
use crate::error::Result;
use crate::numeric::r;
use serde_json::{json, Map, Value};

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let horizon = param_i64(params, "horizon", 5);
    let include_drivers = param_bool(params, "include_drivers", true);

    let signal = source
        .risk_signal(as_of)
        .ok_or_else(|| super::tool_error(format!("risk_signal unavailable at as_of={as_of}")))?;

    let signal_day = signal["as_of"].as_str().unwrap_or(as_of);
    if signal_day[..10.min(signal_day.len())] > as_of[..10.min(as_of.len())] {
        return Err(super::tool_error(format!(
            "point-in-time violation: risk signal as_of {signal_day} > requested {as_of}"
        )));
    }

    let horizons_obj = signal["horizons"]
        .as_object()
        .ok_or_else(|| super::tool_error("risk signal has empty horizons"))?;
    let mut horizons: Vec<(i64, f64)> = horizons_obj
        .iter()
        .filter_map(|(k, v)| k.parse::<i64>().ok().zip(v.as_f64()))
        .collect();
    horizons.sort_by_key(|(h, _)| *h);
    if horizons.is_empty() {
        return Err(super::tool_error("risk signal has empty horizons"));
    }
    let probability = horizons
        .iter()
        .find(|(h, _)| *h == horizon)
        .map(|(_, p)| *p)
        .ok_or_else(|| {
            super::tool_error(format!(
                "horizon {horizon} not provided by risk signal; available={:?}",
                horizons.iter().map(|(h, _)| *h).collect::<Vec<_>>()
            ))
        })?;

    let level = signal["level"].as_str().unwrap_or("low").to_string();
    let drivers: Vec<Value> = if include_drivers {
        signal["drivers"].as_array().cloned().unwrap_or_default()
    } else {
        Vec::new()
    };
    let horizons_json: Map<String, Value> = horizons
        .iter()
        .map(|(h, p)| (h.to_string(), rv(*p)))
        .collect();

    let mut data = Map::new();
    data.insert("model_version".into(), signal["model_version"].clone());
    data.insert(
        "signal_as_of".into(),
        json!(&signal_day[..10.min(signal_day.len())]),
    );
    data.insert("horizon".into(), json!(horizon));
    data.insert("probability".into(), rv(probability));
    data.insert("horizons".into(), Value::Object(horizons_json));
    data.insert(
        "percentile".into(),
        signal["percentile"].as_f64().map(rv).unwrap_or(Value::Null),
    );
    data.insert("level".into(), json!(level));
    data.insert("drivers".into(), Value::Array(drivers));
    data.insert(
        "modality_contrib".into(),
        signal
            .get("modality_contrib")
            .cloned()
            .unwrap_or_else(|| json!({"numeric": 1.0, "text": 0.0})),
    );
    data.insert("label_version".into(), signal["label_version"].clone());
    data.insert("signal_evidence_id".into(), signal["evidence_id"].clone());
    data.insert(
        "unit_map".into(),
        json!({
            "probability": "probability",
            "horizons": "probability",
            "percentile": "quantile_0_1",
            "modality_contrib": "share_0_1",
        }),
    );

    let percentile_txt = signal["percentile"]
        .as_f64()
        .map(|p| format!("{:.0}%", p * 100.0))
        .unwrap_or_else(|| "NA".to_string());
    let summary = format!(
        "共享风险信号 {}（as_of {signal_day}）：{horizon} 日高压力概率 {:.2}%，历史分位 {percentile_txt}，等级 {level}。",
        signal["model_version"].as_str().unwrap_or("unknown"),
        probability * 100.0
    );

    Ok(ToolOutput::new(
        data,
        "probability",
        r(probability),
        format!("共享风险信号（{horizon}日）@ {as_of}"),
        summary,
    ))
}
