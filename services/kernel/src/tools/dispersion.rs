//! `dimension_dispersion` 工具：风险来源结构（六维压力分的极差与结构判读）。
//!
//! 为什么有用（docs/20 §2）：综合指数（CFSI 单一数字）会把「压力来自哪一维」抹平。
//! 真实数据实测（`contracts/golden-vectors/dimension_dispersion_reference.json`）：
//! - 样本外 z>1.0 时 precision 0.6514 / recall 0.3114 / lift **1.708×**；
//! - 压力窗前 40 日各维度变化：跨境 +0.1388 / 股票 +0.1116 / 全球 +0.0971 /
//!   汇率 +0.0658 / 债券 −0.0651 / **信用 −0.1912**（信用在恶化期反而缓解 →
//!   「尚未传导到信用端」的阶段信号）。
//!
//! 口径：dispersion = max(dim) − min(dim)，只用**可用**维度（缺失维度不参与、
//! **不填 0**）；可用维度 <4 → 对外报 `insufficient_data`。
//!
//! 估计量（[`series`]）与黄金向量逐点一致（容差 1e-8，见 `tests/golden.rs`）：
//! - dispersion：可用维度的极差（pandas `max(axis=1)-min(axis=1)`，跳过缺失）；
//!   六维全缺时为 None（不是 0）。
//! - z：相对**训练期**（train_end 之前）极差的均值/标准差（ddof=1）冻结，样本外只评估。

use crate::cfsi::{self, CfsiSeries, DIMENSIONS};
use crate::error::Result;
use crate::numeric::r;
use crate::tools::{tool_error, DataSource, ToolOutput};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

/// 最少可用维度数（低于此值结构判读不可靠，对外报 insufficient_data）。
const MIN_DIMS: usize = 4;

/// `r()` 返回 Option<f64>，转成 JSON（None → null，缺失≠零值）。
fn opt(v: Option<f64>) -> Value {
    v.map(|x| serde_json::to_value(x).unwrap_or(Value::Null))
        .unwrap_or(Value::Null)
}

/// 逐日结构指标（与黄金向量同口径）。
pub struct DispersionSeries {
    /// 每日极差（六维全缺时 None）。
    pub dispersion: Vec<Option<f64>>,
    /// 每日 z 分数（训练期冻结）。
    pub z: Vec<Option<f64>>,
    /// 每日主导维度（可用维度中取值最高者；并列取维度序靠前者）。
    /// 键名与黄金向量一致（`dim_equity` 等）。
    pub dominant: Vec<Option<String>>,
    /// 每日可用维度数。
    pub available: Vec<usize>,
    pub train_mean: f64,
    pub train_std: f64,
    pub train_end: String,
}

/// 维度键名（与黄金向量一致：`dim_equity` 等）。
fn dim_key(dim: &str) -> String {
    format!("dim_{dim}")
}

/// 维度短名（`credit`）→ CFSI 目录里的显示名。
fn dim_display(key: &str) -> String {
    cfsi::dimension_name(key.strip_prefix("dim_").unwrap_or(key)).to_string()
}

/// 逐日结构指标（纯函数，供工具与黄金向量回归共用）。
pub fn series(computed: &CfsiSeries) -> DispersionSeries {
    let n = computed.calendar.len();
    let mut dispersion = Vec::with_capacity(n);
    let mut dominant = Vec::with_capacity(n);
    let mut available = Vec::with_capacity(n);

    for idx in 0..n {
        let mut max_v = f64::NEG_INFINITY;
        let mut min_v = f64::INFINITY;
        let mut best: Option<&str> = None;
        let mut count = 0usize;
        for dim in DIMENSIONS {
            // 维度序即并列时的优先级（与 pandas `idxmax` 一致：取第一个最大值）。
            if let Some(value) = computed.dim_value(dim, idx) {
                count += 1;
                if value > max_v {
                    max_v = value;
                    best = Some(dim);
                }
                if value < min_v {
                    min_v = value;
                }
            }
        }
        available.push(count);
        if count == 0 {
            dispersion.push(None);
            dominant.push(None);
        } else {
            dispersion.push(Some(max_v - min_v));
            dominant.push(best.map(dim_key));
        }
    }

    // 训练期统计：极差可得的行（缺失维度不参与，不用 0 填充）。
    let train_end = computed.train_end.clone();
    let train_disp: Vec<f64> = computed
        .calendar
        .iter()
        .enumerate()
        .filter(|(_, day)| day.as_str() <= train_end.as_str())
        .filter_map(|(idx, _)| dispersion[idx])
        .collect();
    let (train_mean, train_std) = if train_disp.len() >= 2 {
        let n = train_disp.len() as f64;
        let mean = train_disp.iter().sum::<f64>() / n;
        let var = train_disp
            .iter()
            .map(|v| (v - mean) * (v - mean))
            .sum::<f64>()
            / (n - 1.0);
        (mean, var.sqrt())
    } else {
        (0.0, 0.0)
    };
    let std = if train_std > 0.0 { train_std } else { 1.0 };
    let z = dispersion
        .iter()
        .map(|d| d.map(|v| (v - train_mean) / std))
        .collect();

    DispersionSeries {
        dispersion,
        z,
        dominant,
        available,
        train_mean,
        train_std,
        train_end,
    }
}

pub fn compute(
    _params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    // 结构指标读 CFSI 六维（依赖 DuckDB 宽表；内存数据源返回 None → 显式失败）。
    let computed = source.cfsi_series(as_of).ok_or_else(|| {
        tool_error("dimension_dispersion 需要工作区数据源（六维 CFSI 依赖 DuckDB 宽表）")
    })?;
    let idx = computed.calendar.len().saturating_sub(1);
    let day = computed
        .calendar
        .get(idx)
        .cloned()
        .unwrap_or_else(|| as_of.to_string());
    let structure = series(&computed);
    let available = structure.available[idx];
    let dispersion = structure.dispersion[idx];
    let z = structure.z[idx];
    let dominant = structure.dominant[idx].clone();

    let mut limitations: Vec<String> = vec![
        "极差是**结构**指标而非水平指标：它说明压力是否集中，不说明压力大小；相关非因果"
            .to_string(),
        format!(
            "训练期截止 {}；z 分数相对该训练期冻结，样本外只评估不改阈值",
            structure.train_end
        ),
    ];

    let mut data = Map::new();
    if available < MIN_DIMS {
        limitations.push(format!(
            "可用维度仅 {available} 个（<{MIN_DIMS}），结构判读不可靠；缺失维度不得以 0 或均值填充"
        ));
        data.insert("dispersion".into(), Value::Null);
        data.insert("z_score".into(), Value::Null);
        data.insert("level".into(), json!("insufficient_data"));
        data.insert("dominant_dim".into(), Value::Null);
        data.insert("available_dims".into(), json!(available));
        data.insert("missing_dims".into(), json!(missing_dims(&computed, idx)));
        data.insert("limitations".into(), json!(limitations));
        return Ok(ToolOutput::new(
            data,
            "ratio",
            None,
            format!("风险来源结构（数据不足）@ {day}"),
            format!("可用维度仅 {available} 个，未计算结构指标（缺失 ≠ 零值）"),
        ));
    }

    // 维度分解 + 结构判读（哪些维度显著高于/低于其训练期水平）。
    let mut dim_stats: Map<String, Value> = Map::new();
    let mut deteriorating: Vec<String> = Vec::new();
    let mut easing_dims: Vec<String> = Vec::new();
    for dim in DIMENSIONS {
        let Some(value) = computed.dim_value(dim, idx) else {
            continue;
        };
        let train: Vec<f64> = computed
            .calendar
            .iter()
            .enumerate()
            .filter(|(_, day)| day.as_str() <= structure.train_end.as_str())
            .filter_map(|(i, _)| computed.dim_value(dim, i))
            .collect();
        let (mean, sd) = if train.len() >= 2 {
            let n = train.len() as f64;
            let mu = train.iter().sum::<f64>() / n;
            let sd = (train.iter().map(|x| (x - mu) * (x - mu)).sum::<f64>() / (n - 1.0)).sqrt();
            (mu, sd)
        } else {
            (0.0, 1.0)
        };
        let dz = (value - mean) / sd;
        dim_stats.insert(
            dim_key(dim),
            json!({
                "value": opt(r(value)), "train_mean": opt(r(mean)), "z": opt(r(dz)),
                "name": cfsi::dimension_name(dim),
            }),
        );
        if dz > 0.5 {
            deteriorating.push(dim_key(dim));
        }
        if dz < -0.5 {
            easing_dims.push(dim_key(dim));
        }
    }

    for dim in missing_dims(&computed, idx) {
        limitations.push(format!(
            "{}维度在 {day} 无可用观测（缺失 ≠ 零值），未参与结构计算",
            dim_display(&dim)
        ));
    }

    let level = match z {
        Some(v) if v > 1.0 => "elevated",
        Some(v) if v > 0.5 => "moderate",
        Some(_) => "normal",
        None => "unknown",
    };
    let dominant_name = dominant
        .as_deref()
        .map(dim_display)
        .unwrap_or_else(|| "未知".to_string());
    let dominant_label = dominant.clone().unwrap_or_default();

    data.insert("dispersion".into(), opt(dispersion.and_then(r)));
    data.insert("z_score".into(), opt(z.and_then(r)));
    data.insert("level".into(), json!(level));
    data.insert("dominant_dim".into(), json!(dominant_label));
    data.insert(
        "easing_dim".into(),
        json!(easing_dims.first().cloned().unwrap_or_default()),
    );
    data.insert("deteriorating_dims".into(), json!(deteriorating));
    data.insert("easing_dims".into(), json!(easing_dims));
    data.insert("dims".into(), Value::Object(dim_stats));
    data.insert("available_dims".into(), json!(available));
    data.insert("missing_dims".into(), json!(missing_dims(&computed, idx)));
    data.insert("train_mean".into(), opt(r(structure.train_mean)));
    data.insert("train_std".into(), opt(r(structure.train_std)));
    data.insert("train_end".into(), json!(structure.train_end));
    data.insert("limitations".into(), json!(limitations));
    data.insert(
        "unit_map".into(),
        json!({
            "dispersion": "ratio_0_1",
            "z_score": "z",
            "train_mean": "ratio_0_1",
            "train_std": "ratio_0_1",
        }),
    );

    let summary = format!(
        "压力来源集中在 {}（{dominant_label}），最缓解的是 {}；六维极差 {:.3}（z={:.2}，{level}）",
        dominant_name,
        easing_dims
            .first()
            .map(|d| dim_display(d))
            .unwrap_or_else(|| "无".to_string()),
        dispersion.unwrap_or(0.0),
        z.unwrap_or(0.0)
    );

    Ok(ToolOutput::new(
        data,
        "ratio",
        dispersion.and_then(r),
        format!("风险来源结构（六维极差）@ {day}"),
        summary,
    ))
}

/// 当日缺失的维度（六维中无观测者）。
fn missing_dims(computed: &CfsiSeries, idx: usize) -> Vec<String> {
    DIMENSIONS
        .iter()
        .filter(|dim| computed.dim_value(dim, idx).is_none())
        .map(|dim| dim_key(dim))
        .collect()
}

/// 训练期各维度均值（供外部复算结构表）。
pub fn dim_train_means(computed: &CfsiSeries) -> BTreeMap<String, f64> {
    let mut out = BTreeMap::new();
    for dim in DIMENSIONS {
        let train: Vec<f64> = computed
            .calendar
            .iter()
            .enumerate()
            .filter(|(_, day)| day.as_str() <= computed.train_end.as_str())
            .filter_map(|(i, _)| computed.dim_value(dim, i))
            .collect();
        if train.is_empty() {
            continue;
        }
        let mean = train.iter().sum::<f64>() / train.len() as f64;
        out.insert(dim.to_string(), mean);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn insufficient_dims_returns_explicit_state() {
        // 内存数据源没有 CFSI 宽表 → 必须显式失败，不得返回 0 或空结构
        let src = crate::tools::source::MemorySource::default();
        match compute(&Map::new(), "2025-06-30", &src) {
            Err(err) => assert!(
                err.to_string().contains("工作区") || err.to_string().contains("六维"),
                "错误信息应说明需要工作区数据源: {err}"
            ),
            Ok(_) => panic!("内存数据源不应能算结构指标"),
        }
    }

    #[test]
    fn registered_in_registry() {
        let meta = crate::tools::meta("dimension_dispersion").expect("应已注册");
        assert_eq!(meta.version, "1.0.0");
        assert_eq!(meta.unit, "ratio");
    }
}
