//! `capital_linkage` 工具：双序列滚动 Kendall tau 联动性（变化率口径）。
//!
//! 为什么用**变化率**而不是水平（docs/18 §3.4）：水平口径实测 lift 1.10、p=0.115（无效）；
//! 压力前是「同步变化」抬升而非「同步水平」。防退化测试见
//! `tests/golden.rs::capital_linkage_level_mode_would_fail_golden`。
//!
//! 口径（与 `contracts/golden-vectors/capital_linkage_reference.json` 逐点一致）：
//! - 交易日历取**全部日频序列的并集**（不是两条序列的并集：两者在 2025-10 之后会错位，
//!   实测 tau 差到 2e-2 量级，会让点对点回归失败）；
//! - pct_change（不填充），窗口 90 个日历行，窗口内有效配对 < max(15, 50%) → null；
//! - tau = 配对 sign 乘积的均值（Kendall tau 的无并列修正形式）；
//! - z = (tau − 训练期均值) / 训练期标准差，训练期 = 2021-12-31 之前（冻结，样本外只评估）。

use super::source::DataSource;
use super::{history, param_f64, param_str, param_usize, rv, tool_error, ToolOutput};
use crate::error::Result;
use crate::numeric::{mean, r, sign_tie, std_ddof1};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

/// 训练期截止（与 CFSI 一致，冻结后不再改）。
pub const TRAIN_END: &str = "2021-12-31";
pub const DEFAULT_WINDOW: usize = 90;
/// 窗口内最少配对样本（硬下限）。
const MIN_PAIRS: usize = 15;
/// 领先性诊断的前瞻期（交易日）。
pub const HORIZONS: [usize; 6] = [0, 5, 10, 20, 40, 60];
/// 峰值 h ≥ 此值判为 leading。
const LEADING_H: usize = 20;

/// 内置三组预设（docs/18 §3.7：默认展示哪几对，以及各自是领先型还是同期型）。
///
/// 领先型与否由数据算出（见 [`lead_profile`]），此处只登记配对关系。
pub const PRESETS: [(&str, &str, &str); 3] = [
    (
        "csi300_x_northbound",
        "market.cn_equity.csi300",
        "crossborder.flows.northbound_net",
    ),
    ("usdcny_x_vix", "market.fx.usdcny", "market.global.vix"),
    (
        "csi300_x_sp500",
        "market.cn_equity.csi300",
        "market.global.sp500",
    ),
];

/// 预设名 → (series_a, series_b)。
pub fn preset_pair(name: &str) -> Option<(&'static str, &'static str)> {
    PRESETS
        .iter()
        .find(|(preset, _, _)| *preset == name)
        .map(|(_, a, b)| (*a, *b))
}

/// 逐日联动性结果（tau / z 均为 None 表示不可计算，**不是 0**）。
pub struct LinkageSeries {
    pub calendar: Vec<String>,
    pub tau: Vec<Option<f64>>,
    pub z: Vec<Option<f64>>,
    /// 每个窗口的有效配对数（缺失率 = 1 − n_obs/window）。
    pub n_obs: Vec<usize>,
    pub train_mean: f64,
    pub train_std: f64,
}

fn pct_change(calendar: &[String], values: &BTreeMap<String, f64>) -> Vec<Option<f64>> {
    (0..calendar.len())
        .map(|i| {
            if i == 0 {
                return None;
            }
            match (values.get(&calendar[i]), values.get(&calendar[i - 1])) {
                (Some(cur), Some(prev)) if *prev != 0.0 && cur.is_finite() && prev.is_finite() => {
                    Some(cur / prev - 1.0)
                }
                _ => None,
            }
        })
        .collect()
}

/// 滚动 Kendall tau：窗口内两序列都有效的配对才参与（缺失 ≠ 零值，不补 0）。
fn rolling_tau(
    a: &[Option<f64>],
    b: &[Option<f64>],
    window: usize,
) -> (Vec<Option<f64>>, Vec<usize>) {
    let n = a.len();
    let min_pairs = MIN_PAIRS.max((window as f64 * 0.5) as usize);
    let mut tau = vec![None; n];
    let mut n_obs = vec![0usize; n];
    for i in 0..n {
        if i + 1 < window {
            continue;
        }
        let start = i + 1 - window;
        let pairs: Vec<(f64, f64)> = (start..=i)
            .filter_map(|j| match (a[j], b[j]) {
                (Some(x), Some(y)) => Some((x, y)),
                _ => None,
            })
            .collect();
        let k = pairs.len();
        n_obs[i] = k;
        if k < min_pairs {
            continue;
        }
        let mut acc = 0.0f64;
        for p in 0..k {
            for q in (p + 1)..k {
                acc += sign_tie(pairs[p].0 - pairs[q].0) * sign_tie(pairs[p].1 - pairs[q].1);
            }
        }
        let pairs_count = (k * (k - 1)) as f64 / 2.0;
        tau[i] = Some(acc / pairs_count);
    }
    (tau, n_obs)
}

/// 纯计算核心：给定日历与两条序列的取值，算出逐日 tau / z（供工具与黄金回归共用）。
pub fn compute_series(
    calendar: &[String],
    values_a: &BTreeMap<String, f64>,
    values_b: &BTreeMap<String, f64>,
    window: usize,
) -> LinkageSeries {
    let ca = pct_change(calendar, values_a);
    let cb = pct_change(calendar, values_b);
    let (tau, n_obs) = rolling_tau(&ca, &cb, window);
    let train: Vec<f64> = calendar
        .iter()
        .enumerate()
        .filter(|(_, d)| d.as_str() <= TRAIN_END)
        .filter_map(|(i, _)| tau[i])
        .collect();
    let (train_mean, train_std) = if train.is_empty() {
        (0.0, 0.0)
    } else {
        (mean(&train), std_ddof1(&train))
    };
    let z = tau
        .iter()
        .map(|t| match t {
            Some(v) if train_std > 0.0 => Some((v - train_mean) / train_std),
            Some(_) => Some(0.0),
            None => None,
        })
        .collect();
    LinkageSeries {
        calendar: calendar.to_vec(),
        tau,
        z,
        n_obs,
        train_mean,
        train_std,
    }
}

/// 从数据源取截至 `as_of` 的历史与日历，再算序列（PIT 由数据源强制）。
pub fn series(
    source: &dyn DataSource,
    series_a: &str,
    series_b: &str,
    window: usize,
    as_of: &str,
) -> Result<LinkageSeries> {
    if window < 10 {
        return Err(
            crate::error::KernelError::invalid_params("window 不得小于 10").with_detail(json!({
                "reason": "滚动 Kendall tau 需要足够窗口",
                "field": "window",
            })),
        );
    }
    let day = &as_of[..10.min(as_of.len())];
    let hist_a = history(source, series_a, day, 0)?;
    let hist_b = history(source, series_b, day, 0)?;
    let values_a: BTreeMap<String, f64> = hist_a.into_iter().collect();
    let values_b: BTreeMap<String, f64> = hist_b.into_iter().collect();

    // 日历：优先用工作区的全量日频并集（与黄金向量一致），否则退化为两序列并集。
    let calendar: Vec<String> = match source.daily_calendar(day) {
        Some(days) if !days.is_empty() => days,
        _ => {
            let mut days: Vec<String> = values_a.keys().chain(values_b.keys()).cloned().collect();
            days.sort();
            days.dedup();
            days
        }
    };
    if calendar.is_empty() {
        return Err(tool_error("as_of 之前没有任何日频观测"));
    }
    Ok(compute_series(&calendar, &values_a, &values_b, window))
}

fn pearson(pairs: &[(f64, f64)]) -> Option<f64> {
    let n = pairs.len();
    if n < 3 {
        return None;
    }
    let mx = pairs.iter().map(|p| p.0).sum::<f64>() / n as f64;
    let my = pairs.iter().map(|p| p.1).sum::<f64>() / n as f64;
    let mut sxy = 0.0;
    let mut sxx = 0.0;
    let mut syy = 0.0;
    for (x, y) in pairs {
        let dx = x - mx;
        let dy = y - my;
        sxy += dx * dy;
        sxx += dx * dx;
        syy += dy * dy;
    }
    if sxx <= 0.0 || syy <= 0.0 {
        return None;
    }
    Some(sxy / (sxx * syy).sqrt())
}

/// 前瞻相关剖面 corr(tau(t), cfsi(t+h)) 与 lead_type 判定。
pub fn lead_profile(
    calendar: &[String],
    tau: &[Option<f64>],
    cfsi: &BTreeMap<String, f64>,
) -> (Vec<(usize, Option<f64>)>, String) {
    let mut profile: Vec<(usize, Option<f64>)> = Vec::with_capacity(HORIZONS.len());
    for h in HORIZONS {
        let pairs: Vec<(f64, f64)> = calendar
            .iter()
            .enumerate()
            .filter_map(|(i, _)| {
                let t = tau[i]?;
                let target = calendar.get(i + h)?;
                let c = cfsi.get(target)?;
                Some((t, *c))
            })
            .collect();
        profile.push((h, pearson(&pairs)));
    }
    // 峰值 h：并列取较小的 h。
    let mut best: Option<(usize, f64)> = None;
    for (h, corr) in &profile {
        let Some(c) = corr else { continue };
        if best.map(|(_, bc)| *c > bc).unwrap_or(true) {
            best = Some((*h, *c));
        }
    }
    let lead_type = match best {
        Some((h, _)) if h >= LEADING_H => "leading",
        Some(_) => "contemporaneous",
        None => "unknown",
    };
    (profile, lead_type.to_string())
}

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    // 预设：三组内置配对（docs/18 §3.7）。显式 series_a/series_b 优先于 preset。
    let preset = param_str(params, "preset").map(str::to_string);
    let (default_a, default_b) = match preset.as_deref() {
        Some(name) => preset_pair(name).ok_or_else(|| {
            crate::error::KernelError::invalid_params(format!("未知 preset: {name}")).with_detail(
                json!({
                    "reason": format!("未知 preset: {name}"),
                    "field": "preset",
                    "available": PRESETS.iter().map(|(p, _, _)| *p).collect::<Vec<_>>(),
                }),
            )
        })?,
        None => (PRESETS[0].1, PRESETS[0].2),
    };
    let series_a = param_str(params, "series_a")
        .unwrap_or(default_a)
        .to_string();
    let series_b = param_str(params, "series_b")
        .unwrap_or(default_b)
        .to_string();
    let window = param_usize(params, "window", DEFAULT_WINDOW);
    let threshold_z = param_f64(params, "threshold_z", 0.5);

    let computed = series(source, &series_a, &series_b, window, as_of)?;
    let idx = computed.calendar.len() - 1;
    let day = computed.calendar[idx].clone();
    let tau_now = computed.tau[idx];
    let z_now = computed.z[idx];
    let n_obs = computed.n_obs[idx];
    let missing_ratio = 1.0 - (n_obs as f64 / window as f64).min(1.0);

    let mut limitations: Vec<String> = vec![
        "联动性（秩相关）不是因果：不得表述为「外资导致」".to_string(),
        format!("阈值按训练期冻结（{TRAIN_END} 之前），样本外只评估不改"),
    ];

    // 领先性：需要 CFSI 主值序列；缺失时如实标注 unknown，不猜。
    let mut lead_profile_json: Vec<Value> = Vec::new();
    let lead_type = match source.cfsi_series(as_of) {
        Some(cfsi) => {
            let map: BTreeMap<String, f64> = cfsi
                .calendar
                .iter()
                .enumerate()
                .filter_map(|(i, d)| cfsi.cfsi[i].map(|v| (d.clone(), v)))
                .collect();
            let (profile, lead_type) = lead_profile(&computed.calendar, &computed.tau, &map);
            lead_profile_json = profile
                .iter()
                .map(|(h, c)| json!({"h": h, "corr": rv(c.unwrap_or(f64::NAN))}))
                .collect();
            if lead_type == "unknown" {
                limitations.push("CFSI 样本不足，无法估计前瞻相关剖面".to_string());
            }
            lead_type
        }
        None => {
            limitations
                .push("未取得 CFSI 序列，lead_type 无法判定（返回 unknown，不臆测）".to_string());
            "unknown".to_string()
        }
    };

    let (level, value) = match tau_now {
        Some(t) => {
            let lvl = if z_now.map(|z| z > threshold_z).unwrap_or(false) {
                "elevated"
            } else {
                "normal"
            };
            (lvl, Some(t))
        }
        None => {
            limitations.push(format!(
                "窗口内有效配对仅 {n_obs}/{window}（<50%），联动性不可计算；缺失 ≠ 零值，不返回 0"
            ));
            ("insufficient_data", None)
        }
    };

    let mut data = Map::new();
    data.insert("series_a".into(), json!(series_a));
    data.insert("series_b".into(), json!(series_b));
    data.insert(
        "preset".into(),
        json!(preset.unwrap_or_else(|| "custom".to_string())),
    );
    data.insert("window".into(), json!(window));
    data.insert("mode".into(), json!("returns(pct_change)"));
    data.insert("kendall_tau".into(), rv(tau_now.unwrap_or(f64::NAN)));
    data.insert("z_score".into(), rv(z_now.unwrap_or(f64::NAN)));
    data.insert("level".into(), json!(level));
    data.insert("threshold_z".into(), json!(threshold_z));
    data.insert("n_obs".into(), json!(n_obs));
    data.insert("missing_ratio".into(), rv(missing_ratio));
    data.insert("lead_type".into(), json!(lead_type));
    data.insert("lead_profile".into(), Value::Array(lead_profile_json));
    data.insert("train_mean".into(), rv(computed.train_mean));
    data.insert("train_std".into(), rv(computed.train_std));
    data.insert("train_end".into(), json!(TRAIN_END));
    data.insert("observations".into(), json!(computed.calendar.len()));
    data.insert("window_end".into(), json!(day));
    data.insert("limitations".into(), json!(limitations));
    data.insert(
        "unit_map".into(),
        json!({
            "kendall_tau": "tau",
            "z_score": "z",
            "missing_ratio": "ratio_0_1",
            "train_mean": "tau",
            "train_std": "tau",
        }),
    );

    let summary = match (tau_now, z_now) {
        (Some(t), Some(z)) => format!(
            "{series_a} × {series_b}：{window} 日滚动 Kendall τ = {:.4}（z = {:.2}，{}；{}；有效配对 {}/{}）",
            r(t).unwrap_or(0.0),
            r(z).unwrap_or(0.0),
            level,
            lead_type,
            n_obs,
            window
        ),
        (Some(t), None) => format!(
            "{series_a} × {series_b}：{window} 日滚动 Kendall τ = {:.4}（训练期不足，无 z；{lead_type}）",
            r(t).unwrap_or(0.0)
        ),
        _ => format!(
            "{series_a} × {series_b}：窗口内有效配对仅 {n_obs}/{window}，联动性不可计算（数据不足）"
        ),
    };

    Ok(ToolOutput::new(
        data,
        "tau",
        value.and_then(r),
        format!("序列联动性：{series_a} × {series_b} @ {day}"),
        summary,
    ))
}
