//! `signal.compute`：把 CFSI 六维映射为共享风险信号（缺失维度不参与、不填充）。
//!
//! 口径说明：这是**确定性压力分位信号**（由 CFSI 维度直接映射），不是训练出的
//! 多模态模型概率。`model_version` 显式标注 `cfsi-deterministic-v1`，
//! 以免与 P1 的模型产物（`forecast` 工具读取的 `RiskSignal`）混淆。

use crate::cfsi;
use crate::error::{KernelError, Result};
use crate::features;
use crate::numeric::r;
use crate::pit::SeriesCatalog;
use crate::workspace::Workspace;
use serde_json::{json, Map, Value};

pub const MODEL_VERSION: &str = "cfsi-deterministic-v1";

pub fn compute(ws: &Workspace, catalog: &SeriesCatalog, as_of: &str) -> Result<Value> {
    let day = &as_of[..10.min(as_of.len())];

    // 优先复用当日已算好的 CFSI；否则现算（并写历史）
    let cfsi_value = match features::load_cfsi_row(ws, as_of)? {
        Some(row) if row["cfsi"].as_f64().is_some() => row,
        _ => {
            let fresh = cfsi::compute(ws, as_of, catalog)?;
            features::persist_cfsi(ws, as_of, &fresh)?;
            fresh
        }
    };

    let dims_obj = cfsi_value["dims"]
        .as_object()
        .cloned()
        .ok_or_else(|| KernelError::data_missing("CFSI 维度明细缺失，无法构造信号"))?;
    let mut dims = Map::new();
    for (name, detail) in &dims_obj {
        if let Some(value) = detail["value"].as_f64() {
            dims.insert(name.clone(), json!(r(value).unwrap_or(value)));
        }
    }
    let missing_dims: Vec<Value> = cfsi_value["missing_dims"]
        .as_array()
        .cloned()
        .unwrap_or_default();

    if dims.is_empty() {
        return Err(KernelError::data_missing(
            "六个维度在 as_of 均无可用观测，无法计算信号（缺失不得用 0 填充）",
        )
        .with_detail(json!({"reason": "全部维度缺失", "as_of": day})));
    }

    // 压力概率 = 可用维度压力分位的均值（维度内已是 0–1 分位）
    let values: Vec<f64> = dims.values().filter_map(|v| v.as_f64()).collect();
    let value = values.iter().sum::<f64>() / values.len() as f64;

    let mut limitations: Vec<Value> = cfsi_value["limitations"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    limitations.push(json!(format!(
        "本信号为确定性压力分位映射（{MODEL_VERSION}），不是训练出的多模态模型概率；如需模型结论请使用 forecast 工具读取 P1 产物"
    )));

    let signal_id = format!("sig_{}", day.replace('-', ""));
    let evidence_payload = json!({
        "signal_id": signal_id,
        "as_of": day,
        "value": r(value),
        "dims": dims,
        "missing_dims": missing_dims,
        "model_version": MODEL_VERSION,
        "cfsi": cfsi_value["cfsi"],
        "tau": cfsi_value["tau"],
        "level": cfsi_value["level"],
    });
    let evidence_id = format!(
        "ev_{}",
        &crate::canon::sha256_text(&crate::canon::canonical_json(&evidence_payload))[..16]
    );

    let result = json!({
        "signal_id": signal_id,
        "value": r(value),
        "dims": dims,
        "missing_dims": missing_dims,
        "limitations": limitations,
        "level": cfsi_value["level"],
        "cfsi": cfsi_value["cfsi"],
        "tau": cfsi_value["tau"],
        "model_version": MODEL_VERSION,
        "evidence_id": evidence_id,
        "provenance": {
            "source": "cfsi.compute",
            "index_version": cfsi_value["provenance"]["index_version"],
            "label_version": cfsi_value["provenance"]["label_version"],
            "train_end": cfsi_value["provenance"]["train_end"],
        },
    });

    ws.conn
        .execute(
            "INSERT OR REPLACE INTO signals(as_of, signal_id, value, level, dims, missing_dims, limitations, model_version, label_version, evidence_id) \
             VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            duckdb::params![
                day,
                result["signal_id"].as_str(),
                result["value"].as_f64(),
                result["level"].as_str(),
                result["dims"].to_string(),
                result["missing_dims"].to_string(),
                result["limitations"].to_string(),
                MODEL_VERSION,
                result["provenance"]["label_version"].as_str(),
                evidence_id,
            ],
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;

    Ok(result)
}

/// 把 `signal.compute` 的结果转成 `forecast` 工具可读的 RiskSignal 形态。
pub fn as_risk_signal(signal: &Value) -> Value {
    let value = signal["value"].as_f64().unwrap_or(0.0);
    json!({
        "as_of": signal["provenance"]["train_end"].as_str().map(|_| "").unwrap_or(""),
        "model_version": signal["model_version"],
        "horizons": {"5": value, "10": value, "20": value},
        "percentile": value,
        "level": signal["level"],
        "drivers": [],
        "modality_contrib": {"numeric": 1.0, "text": 0.0},
        "label_version": signal["provenance"]["label_version"],
        "evidence_id": signal["evidence_id"],
    })
}
