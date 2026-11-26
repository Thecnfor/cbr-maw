//! 七工具注册表、参数合并与统一 Evidence 构造。

pub mod capital;
pub mod dispersion;
pub mod forecast;
pub mod funding;
pub mod kb_search;
pub mod linkage;
pub mod risk;
pub mod scenario;
pub mod source;
pub mod systemic;

use crate::canon::{compute_evidence_hash, compute_evidence_id, compute_inputs_hash, to_native};
use crate::error::{ErrorKind, KernelError, Result};
use crate::numeric::r;
use serde_json::{json, Map, Value};
use source::DataSource;

/// 工具失败（数据不足、序列缺失、参数不可计算）：映射到 `E_DATA_MISSING`。
pub fn tool_error(message: impl Into<String>) -> KernelError {
    KernelError::new(ErrorKind::DataMissing, message)
}

/// 工具计算结果（数据与证据由统一出口封装）。
pub struct ToolOutput {
    pub data: Map<String, Value>,
    pub unit: Option<String>,
    pub value: Option<f64>,
    pub title: String,
    pub summary: String,
}

impl ToolOutput {
    pub fn new(
        data: Map<String, Value>,
        unit: &str,
        value: Option<f64>,
        title: String,
        summary: String,
    ) -> Self {
        Self {
            data,
            unit: Some(unit.to_string()),
            value,
            title,
            summary,
        }
    }
}

#[derive(Debug)]
pub struct ToolResult {
    pub evidence: Value,
}

/// 工具元信息（`contracts/tools/tools.json` 的 Rust 镜像）。
pub struct ToolMeta {
    pub name: &'static str,
    pub version: &'static str,
    pub unit: &'static str,
    pub description: &'static str,
}

pub const TOOL_REGISTRY: [ToolMeta; 9] = [
    ToolMeta {
        name: "risk_measure",
        version: "1.0.0",
        unit: "loss_ratio",
        description: "年化波动率、历史/参数 VaR 与 CVaR、最大回撤、压力分位（确定性纯计算）",
    },
    ToolMeta {
        name: "systemic_risk",
        version: "1.0.0",
        unit: "ratio",
        description: "ΔCoVaR、MES、Diebold-Yilmaz 跨市场溢出指数（确定性纯计算）",
    },
    ToolMeta {
        name: "capital_flow",
        version: "1.0.0",
        unit: "z",
        description: "跨境资金异常净流入 z-score、同步撤离、集中度与 AH 溢价（确定性纯计算）",
    },
    ToolMeta {
        name: "funding_cost",
        version: "1.0.0",
        unit: "bp",
        description: "信用利差代理、融资成本变化（bp）、再融资窗口估计（确定性纯计算）",
    },
    ToolMeta {
        name: "scenario",
        version: "1.0.0",
        unit: "ratio",
        description: "汇率/美股/利差冲击的线性与历史类比情景映射及压力传导（确定性纯计算）",
    },
    ToolMeta {
        name: "forecast",
        version: "1.0.0",
        unit: "probability",
        description: "读取共享多模态风险信号（P1 产物，只读）并输出统一 Evidence",
    },
    ToolMeta {
        name: "knowledge_search",
        version: "1.0.0",
        unit: "",
        description: "时点过滤的知识库检索（政策/方法学/事件复盘），返回 chunk_id 可核验引文",
    },
    ToolMeta {
        name: "dimension_dispersion",
        version: "1.0.0",
        unit: "ratio",
        description: "风险来源结构：六维压力分极差、主导维度与阶段判读（确定性纯计算）",
    },
    ToolMeta {
        name: "capital_linkage",
        version: "1.0.0",
        unit: "tau",
        description: "双序列滚动 Kendall tau 联动性（变化率口径，含领先性诊断；确定性纯计算）",
    },
];

pub fn meta(tool: &str) -> Option<&'static ToolMeta> {
    TOOL_REGISTRY.iter().find(|m| m.name == tool)
}

/// 默认参数（与 `contracts/tools/*.params.schema.json` 的 default 一致）。
pub fn default_params(tool: &str) -> Map<String, Value> {
    let raw = match tool {
        "risk_measure" => json!({
            "series_id": "market.cn_equity.csi300", "lookback": 252, "annualization": 252,
            "confidence": 0.95, "horizon_days": 1, "values_are": "price", "min_observations": 20
        }),
        "systemic_risk" => json!({
            "market_series_id": "market.cn_equity.csi300", "asset_series_id": "market.cn_bond.cgb_index",
            "series_ids": ["market.cn_equity.csi300", "market.global.sp500", "market.fx.usdcny", "market.global.vix"],
            "lookback": 252, "tail_q": 0.05, "dy_window": 120, "dy_lag": 1, "dy_horizon": 10, "values_are": "price"
        }),
        "capital_flow" => json!({
            "inflow_series_id": "crossborder.flows.northbound_net",
            "outflow_series_id": "crossborder.flows.southbound_net",
            "ah_premium_series_id": "crossborder.flows.ah_premium",
            "lookback": 60, "z_window": 60, "anomaly_z": 1.5, "top_n": 5, "flow_unit": "亿元"
        }),
        "funding_cost" => json!({
            "spread_series_id": "rates.credit.aa_spread", "lookback": 252, "momentum_window": 20,
            "spread_unit": "bp", "cost_jump_bp": 50.0, "cost_medium_bp": 25.0, "refinancing_horizon_days": 90
        }),
        "scenario" => json!({
            "target_series_id": "market.cn_equity.csi300", "us_equity_series_id": "market.global.sp500",
            "fx_series_id": "market.fx.usdcny", "spread_series_id": "rates.credit.aa_spread",
            "lookback": 252, "us_equity_drop_pct": 10.0, "fx_depreciation_pct": 5.0,
            "spread_widening_bp": 100.0, "method": "both", "analog_k": 10, "spread_unit": "bp",
            "min_observations": 60, "values_are": "price"
        }),
        "forecast" => json!({"horizon": 5, "include_drivers": true}),
        "knowledge_search" => json!({"top_k": 5}),
        "dimension_dispersion" => json!({}),
        "capital_linkage" => json!({
            "preset": "csi300_x_northbound",
            "window": 90, "threshold_z": 0.5
        }),
        _ => json!({}),
    };
    raw.as_object().cloned().unwrap_or_default()
}

/// 合并参数：显式参数 > 默认值；`null` 视为未提供（对齐旧版 `kwargs if v is not None`）。
pub fn merge_params(tool: &str, explicit: &Map<String, Value>) -> Result<Map<String, Value>> {
    let defaults = default_params(tool);
    let mut merged = defaults;
    for (key, value) in explicit {
        if !value.is_null() {
            merged.insert(key.clone(), value.clone());
        }
    }
    Ok(merged)
}

pub fn param_str<'a>(params: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    params.get(key).and_then(|v| v.as_str())
}

pub fn param_f64(params: &Map<String, Value>, key: &str, default: f64) -> f64 {
    params.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
}

pub fn param_i64(params: &Map<String, Value>, key: &str, default: i64) -> i64 {
    params.get(key).and_then(|v| v.as_i64()).unwrap_or(default)
}

pub fn param_usize(params: &Map<String, Value>, key: &str, default: usize) -> usize {
    params
        .get(key)
        .and_then(|v| v.as_i64())
        .map(|v| v.max(0) as usize)
        .unwrap_or(default)
}

pub fn param_bool(params: &Map<String, Value>, key: &str, default: bool) -> bool {
    params.get(key).and_then(|v| v.as_bool()).unwrap_or(default)
}

/// 读取时点历史并做 PIT 双保险（`day <= as_of`、跳过非有限值）。
pub fn history(
    source: &dyn DataSource,
    series_id: &str,
    as_of: &str,
    lookback: usize,
) -> Result<Vec<(String, f64)>> {
    if series_id.is_empty() {
        return Err(tool_error("series_id 不能为空"));
    }
    let as_of_day = &as_of[..10.min(as_of.len())];
    let rows = source.history(series_id, as_of_day, Some(lookback));
    let mut out: Vec<(String, f64)> = Vec::new();
    for (day, value) in rows {
        if day.as_str() > as_of_day {
            return Err(tool_error(format!(
                "point-in-time violation: series {series_id} rows contain {day} > as_of {as_of_day}"
            )));
        }
        if !value.is_finite() {
            continue;
        }
        out.push((day, value));
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    if out.is_empty() {
        return Err(tool_error(format!(
            "no available history for series {series_id} as of {as_of_day}"
        )));
    }
    Ok(out)
}

pub fn values_of(items: &[(String, f64)]) -> Vec<f64> {
    items.iter().map(|(_, v)| *v).collect()
}

/// 工具统一入口：参数校验 → 纯计算 → 统一 Evidence。
pub fn invoke(
    tool: &str,
    as_of: &str,
    params: &Map<String, Value>,
    source: &dyn DataSource,
) -> Result<ToolResult> {
    let meta = meta(tool).ok_or_else(|| {
        KernelError::invalid_params(format!("unknown tool: {tool}")).with_detail(json!({
            "reason": format!("未知工具 {tool}"),
            "field": "tool",
            "available": TOOL_REGISTRY.iter().map(|m| m.name).collect::<Vec<_>>(),
        }))
    })?;
    let merged = merge_params(tool, params)?;
    let day = as_of.get(..10).unwrap_or(as_of).to_string();

    let output = match tool {
        "risk_measure" => risk::compute(&merged, &day, source)?,
        "systemic_risk" => systemic::compute(&merged, &day, source)?,
        "capital_flow" => capital::compute(&merged, &day, source)?,
        "funding_cost" => funding::compute(&merged, &day, source)?,
        "scenario" => scenario::compute(&merged, &day, source)?,
        "forecast" => forecast::compute(&merged, &day, source)?,
        "knowledge_search" => kb_search::compute(&merged, &day, source)?,
        "dimension_dispersion" => dispersion::compute(&merged, &day, source)?,
        "capital_linkage" => linkage::compute(&merged, &day, source)?,
        _ => return Err(KernelError::method_not_found(tool)),
    };

    let data = to_native(&Value::Object(output.data.clone()));
    let params_norm = to_native(&Value::Object(merged));
    let inputs_hash = compute_inputs_hash(meta.name, meta.version, &day, &params_norm);
    let evidence_id = compute_evidence_id(meta.name, meta.version, &inputs_hash);
    let hash = compute_evidence_hash(&data);
    let unit = output.unit.clone().filter(|u| !u.is_empty());

    let evidence = json!({
        "evidence_id": evidence_id,
        "tool": meta.name,
        "version": meta.version,
        "inputs_hash": inputs_hash,
        "hash": hash,
        "value": output.value.map(|v| serde_json::to_value(v).unwrap_or(Value::Null)).unwrap_or(Value::Null),
        "unit": unit,
        "as_of": day,
        "params": params_norm,
        "title": output.title,
        "summary": output.summary,
        "data": data,
    });
    Ok(ToolResult { evidence })
}

/// 便捷：把 f64 转为可空 JSON 数值（经 `r` 四舍五入）。
pub fn rv(value: f64) -> Value {
    match r(value) {
        Some(v) => json!(v),
        None => Value::Null,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use source::MemorySource;

    fn synthetic_series(days: usize, start: f64, step: f64) -> Vec<(String, f64)> {
        let base = chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();
        (0..days)
            .map(|i| {
                let day = base + chrono::Duration::days(i as i64);
                (day.format("%Y-%m-%d").to_string(), start + step * i as f64)
            })
            .collect()
    }

    #[test]
    fn risk_measure_returns_evidence_with_hashes() {
        let source = MemorySource::default().with_series(
            "market.cn_equity.csi300",
            synthetic_series(300, 3000.0, 1.5),
        );
        let params = merge_params("risk_measure", &Map::new()).unwrap();
        let out = invoke("risk_measure", "2025-10-27", &params, &source).unwrap();
        let ev = &out.evidence;
        assert_eq!(ev["tool"], "risk_measure");
        assert_eq!(ev["version"], "1.0.0");
        assert_eq!(ev["inputs_hash"].as_str().unwrap().len(), 64);
        assert!(ev["evidence_id"].as_str().unwrap().starts_with("ev_"));
        assert!(ev["data"]["annualized_volatility"].as_f64().is_some());
        assert_eq!(ev["as_of"], "2025-10-27");
    }

    #[test]
    fn same_params_same_evidence_id() {
        let source = MemorySource::default().with_series(
            "market.cn_equity.csi300",
            synthetic_series(300, 3000.0, 1.5),
        );
        let params = merge_params("risk_measure", &Map::new()).unwrap();
        let a = invoke("risk_measure", "2025-10-27", &params, &source).unwrap();
        let b = invoke("risk_measure", "2025-10-27", &params, &source).unwrap();
        assert_eq!(a.evidence["evidence_id"], b.evidence["evidence_id"]);
        assert_eq!(a.evidence["hash"], b.evidence["hash"]);
    }

    #[test]
    fn missing_data_fails_explicitly() {
        let source = MemorySource::default();
        let params = merge_params("risk_measure", &Map::new()).unwrap();
        let err = invoke("risk_measure", "2025-10-27", &params, &source).unwrap_err();
        assert_eq!(err.kind, ErrorKind::DataMissing);
    }

    #[test]
    fn unknown_tool_is_invalid_params() {
        let source = MemorySource::default();
        let err = invoke("nope", "2025-10-27", &Map::new(), &source).unwrap_err();
        assert_eq!(err.kind, ErrorKind::InvalidParams);
    }

    /// 回归：preset 必须生效。默认参数曾注入 series_a/series_b，覆盖了 preset，
    /// 导致三组内置配对全部退回 csi300×northbound。
    #[test]
    fn capital_linkage_preset_selects_distinct_pairs() {
        let source = MemorySource::default()
            .with_series(
                "market.cn_equity.csi300",
                synthetic_series(400, 3000.0, 1.5),
            )
            .with_series(
                "crossborder.flows.northbound_net",
                synthetic_series(400, 20.0, -0.05),
            )
            .with_series("market.fx.usdcny", synthetic_series(400, 6.2, 0.001))
            .with_series("market.global.vix", synthetic_series(400, 18.0, 0.02))
            .with_series("market.global.sp500", synthetic_series(400, 4000.0, 2.0));
        let mut seen = std::collections::BTreeSet::new();
        for preset in ["csi300_x_northbound", "usdcny_x_vix", "csi300_x_sp500"] {
            let mut explicit = Map::new();
            explicit.insert("preset".into(), Value::String(preset.to_string()));
            let merged = merge_params("capital_linkage", &explicit).unwrap();
            assert_eq!(merged.get("series_a"), None, "默认参数不得注入 series_a");
            let out = invoke("capital_linkage", "2025-12-31", &merged, &source).unwrap();
            let (a, b) = (
                out.evidence["data"]["series_a"]
                    .as_str()
                    .unwrap()
                    .to_string(),
                out.evidence["data"]["series_b"]
                    .as_str()
                    .unwrap()
                    .to_string(),
            );
            seen.insert((preset.to_string(), a, b));
        }
        // 三组预设必须映射到三组不同配对。
        let pairs: std::collections::BTreeSet<_> = seen
            .iter()
            .map(|(_, a, b)| (a.clone(), b.clone()))
            .collect();
        assert_eq!(pairs.len(), 3, "preset 未生效：{seen:?}");
    }
}
