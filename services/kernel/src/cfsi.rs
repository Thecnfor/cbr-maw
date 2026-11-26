//! CFSI-CN 压力指数（`stress_pca_q90`）与逐维明细。
//!
//! 对齐旧版 `commorcial/src/cbr/data/labels.py`：
//! 子指标方向统一 → 训练期 winsorize（边界冻结）→ 滚动经验分位 → 维度内等权 →
//! 训练期 PCA 第一主成分（载荷冻结）→ 训练期经验 CDF 映射到 0–1 → ×100。
//!
//! 红线：缺席维度**不参与**计算，不填 0/均值；结果必带 `missing_dims` 与 `limitations`。
//! 缺维时 τ **不冻结**（按可用维度重新估计），并在 provenance 标注。

use crate::error::{KernelError, Result};
use crate::numeric::{mean, quantile, std_ddof1};
use crate::pit::SeriesCatalog;
use crate::workspace::Workspace;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

pub const INDEX_VERSION: &str = "cfsi-v1";
pub const LABEL_VERSION: &str = "stress_pca_q90";
pub const ROLLING_WINDOW: usize = 1250;
pub const MIN_PERIODS: usize = 252;

/// 六个维度（顺序与旧版 `DIMENSION_NAMES` 一致）。
pub const DIMENSIONS: [&str; 6] = ["equity", "bond", "credit", "fx", "crossborder", "global"];

pub fn dimension_name(dim: &str) -> &'static str {
    match dim {
        "equity" => "股票市场压力",
        "bond" => "债券与资金面压力",
        "credit" => "信用风险溢价",
        "fx" => "人民币汇率压力",
        "crossborder" => "跨境资金压力",
        "global" => "全球风险传导",
        _ => "未知维度",
    }
}

/// 一条序列对齐到交易日历后的取值（`None` = 当日无观测，不是 0）。
type Column = Vec<Option<f64>>;

struct Frame {
    calendar: Vec<String>,
    columns: BTreeMap<String, Column>,
}

impl Frame {
    fn get(&self, series_id: &str) -> Option<&Column> {
        self.columns.get(series_id)
    }
}

// --------------------------------------------------------------------------- //
// pandas 等价滚动算子
// --------------------------------------------------------------------------- //
fn pct_change(col: &Column, periods: usize) -> Column {
    (0..col.len())
        .map(|i| {
            if i < periods {
                return None;
            }
            match (col[i], col[i - periods]) {
                (Some(cur), Some(prev)) => Some(cur / prev - 1.0),
                _ => None,
            }
        })
        .collect()
}

fn safe_diff(col: &Column, periods: usize) -> Column {
    (0..col.len())
        .map(|i| {
            if i < periods {
                return None;
            }
            match (col[i], col[i - periods]) {
                (Some(cur), Some(prev)) => Some(cur - prev),
                _ => None,
            }
        })
        .collect()
}

fn window_values(col: &Column, end: usize, window: usize) -> Vec<f64> {
    let start = (end + 1).saturating_sub(window);
    col[start..=end].iter().filter_map(|v| *v).collect()
}

/// pandas `rolling(window, min_periods).std()`（ddof=1）。
///
/// 必须用 pandas 的 Welford 单遍算法（`roll_var` in `_libs/window/aggregations.pyx`），
/// 而不是「先求均值再求离差平方和」：两者差 ~1 ulp，足以让滚动经验分位里
/// 恰好并列的两天翻到不等号另一侧。
fn rolling_std(col: &Column, window: usize, min_periods: usize) -> Column {
    (0..col.len())
        .map(|i| {
            let start = (i + 1).saturating_sub(window);
            let mut nobs = 0usize;
            let mut prev_mean = 0.0f64;
            let mut prev_ssq = 0.0f64;
            for value in col[start..=i].iter().flatten() {
                nobs += 1;
                let delta = *value - prev_mean;
                prev_mean += delta / nobs as f64;
                prev_ssq += delta * (*value - prev_mean);
            }
            if nobs < min_periods.max(2) {
                None
            } else {
                Some((prev_ssq / (nobs - 1) as f64).sqrt())
            }
        })
        .collect()
}

fn rolling_max(col: &Column, window: usize, min_periods: usize) -> Column {
    (0..col.len())
        .map(|i| {
            let values = window_values(col, i, window);
            if values.len() < min_periods {
                None
            } else {
                Some(values.iter().copied().fold(f64::NEG_INFINITY, f64::max))
            }
        })
        .collect()
}

fn rolling_sum(col: &Column, window: usize, min_periods: usize) -> Column {
    (0..col.len())
        .map(|i| {
            let values = window_values(col, i, window);
            if values.len() < min_periods {
                None
            } else {
                Some(values.iter().sum())
            }
        })
        .collect()
}

/// pandas `clip(lower, upper)`：NaN 保留，±inf 被夹到边界。
fn clip(col: &Column, lower: f64, upper: f64) -> Column {
    col.iter()
        .map(|v| {
            v.map(|x| {
                if x.is_nan() {
                    x
                } else {
                    x.max(lower).min(upper)
                }
            })
        })
        .map(|v| v.filter(|x| !x.is_nan()))
        .collect()
}

/// 旧版 `_rolling_percentile`：`p_t = P(X_t >= X_s, s ∈ [t-w+1, t])`。
fn rolling_percentile(col: &Column, window: usize, min_periods: usize) -> Column {
    let mut out: Column = vec![None; col.len()];
    for t in 0..col.len() {
        let Some(last) = col[t] else { continue };
        if !last.is_finite() {
            continue;
        }
        let start = (t + 1).saturating_sub(window);
        let valid: Vec<f64> = col[start..=t]
            .iter()
            .filter_map(|v| *v)
            .filter(|v| v.is_finite())
            .collect();
        if valid.len() < min_periods {
            continue;
        }
        let hits = valid.iter().filter(|v| **v <= last).count();
        out[t] = Some(hits as f64 / valid.len() as f64);
    }
    out
}

/// numpy `quantile(linear)`，保留 ±inf（与 `dropna()` 后的 numpy 行为一致）。
fn quantile_inclusive(values: &[f64], q: f64) -> Option<f64> {
    let mut sorted: Vec<f64> = values.iter().copied().filter(|v| !v.is_nan()).collect();
    if sorted.is_empty() {
        return None;
    }
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if sorted.len() == 1 {
        return Some(sorted[0]);
    }
    let pos = (sorted.len() - 1) as f64 * q;
    let lo = pos.floor() as usize;
    let hi = pos.ceil() as usize;
    if lo == hi {
        return Some(sorted[lo]);
    }
    let frac = pos - lo as f64;
    Some(sorted[lo] + (sorted[hi] - sorted[lo]) * frac)
}

// --------------------------------------------------------------------------- //
// 维度子指标（方向统一：数值越大越紧张）
// --------------------------------------------------------------------------- //
/// 一个原始子指标：名称 + 所属维度 + 序列。
struct Indicator {
    name: &'static str,
    dimension: &'static str,
    values: Column,
}

fn add(
    indicator_list: &mut Vec<Indicator>,
    name: &'static str,
    dimension: &'static str,
    values: Column,
) {
    indicator_list.push(Indicator {
        name,
        dimension,
        values,
    });
}

fn build_indicators(frame: &Frame) -> Vec<Indicator> {
    let mut out: Vec<Indicator> = Vec::new();
    if let Some(equity) = frame.get("market.cn_equity.csi300") {
        add(
            &mut out,
            "equity_ret_5d",
            "equity",
            negate(pct_change(equity, 5)),
        );
        add(
            &mut out,
            "equity_ret_20d",
            "equity",
            negate(pct_change(equity, 20)),
        );
        add(
            &mut out,
            "equity_vol_20d",
            "equity",
            rolling_vol(equity, 20),
        );
        add(
            &mut out,
            "equity_drawdown_20d",
            "equity",
            rolling_drawdown(equity, 20),
        );
    }
    if let Some(term) = frame.get("market.cn_bond.term_spread") {
        add(
            &mut out,
            "bond_term_spread_level",
            "bond",
            negate(term.clone()),
        );
        add(
            &mut out,
            "bond_term_spread_chg_20d",
            "bond",
            negate(safe_diff(term, 20)),
        );
    }
    if let Some(repo) = frame.get("market.cn_bond.repo_7d") {
        add(&mut out, "bond_repo_chg_20d", "bond", safe_diff(repo, 20));
    }
    if let Some(credit) = frame.get("rates.credit.aa_spread") {
        add(&mut out, "credit_spread_level", "credit", credit.clone());
        add(
            &mut out,
            "credit_spread_chg_20d",
            "credit",
            safe_diff(credit, 20),
        );
    }
    if let Some(usdcny) = frame.get("market.fx.usdcny") {
        add(&mut out, "fx_ret_20d", "fx", pct_change(usdcny, 20));
        add(&mut out, "fx_vol_20d", "fx", rolling_vol(usdcny, 20));
    }
    if let Some(gap) = frame.get("market.fx.cnh_cny_gap") {
        add(&mut out, "fx_cnh_cny_gap", "fx", gap.clone());
        add(&mut out, "fx_cnh_cny_gap_chg_20d", "fx", safe_diff(gap, 20));
    }
    if let Some(north) = frame.get("crossborder.flows.northbound_net") {
        add(
            &mut out,
            "crossborder_north_20d",
            "crossborder",
            negate(rolling_sum(north, 20, 10)),
        );
    }
    if let Some(south) = frame.get("crossborder.flows.southbound_net") {
        add(
            &mut out,
            "crossborder_south_20d",
            "crossborder",
            negate(rolling_sum(south, 20, 10)),
        );
    }
    if let Some(ah) = frame.get("crossborder.flows.ah_premium") {
        add(
            &mut out,
            "crossborder_ah_chg_20d",
            "crossborder",
            safe_diff(ah, 20),
        );
    }
    if let Some(hold) = frame.get("crossborder.holdings.northbound_hold") {
        add(
            &mut out,
            "crossborder_hold_ret_20d",
            "crossborder",
            negate(pct_change(hold, 20)),
        );
    }
    if let Some(vix) = frame.get("market.global.vix") {
        add(&mut out, "global_vix_level", "global", vix.clone());
        add(&mut out, "global_vix_chg_5d", "global", safe_diff(vix, 5));
    }
    if let Some(sp500) = frame.get("market.global.sp500") {
        add(
            &mut out,
            "global_sp_ret_20d",
            "global",
            negate(pct_change(sp500, 20)),
        );
    }
    if let Some(dxy) = frame.get("market.global.dxy") {
        add(
            &mut out,
            "global_dxy_ret_20d",
            "global",
            pct_change(dxy, 20),
        );
    }
    if let Some(cn_us) = frame.get("market.global.cn_us_spread") {
        add(
            &mut out,
            "global_cn_us_spread_chg_20d",
            "global",
            negate(safe_diff(cn_us, 20)),
        );
    }
    out
}

fn negate(col: Column) -> Column {
    col.into_iter().map(|v| v.map(|x| -x)).collect()
}

fn rolling_vol(col: &Column, window: usize) -> Column {
    let returns = pct_change(col, 1);
    let std = rolling_std(&returns, window, 5usize.max(window / 4));
    std.into_iter()
        .map(|v| v.map(|x| x * 252.0_f64.sqrt()))
        .collect()
}

fn rolling_drawdown(col: &Column, window: usize) -> Column {
    let max = rolling_max(col, window, 5usize.max(window / 4));
    col.iter()
        .zip(max.iter())
        .map(|(value, peak)| match (value, peak) {
            (Some(v), Some(p)) if *p != 0.0 => Some((1.0 - v / p).max(0.0)),
            (Some(_), Some(_)) => Some(0.0),
            _ => None,
        })
        .collect()
}

/// 旧版 `_dimension_percentile`：维度内子指标分位等权平均；有效子指标不足时 NaN。
fn dimension_percentile(members: &[&Column], n_rows: usize) -> Column {
    let required = (members.len() as f64 * 0.5).ceil() as usize;
    let required = required.max(1);
    (0..n_rows)
        .map(|i| {
            let values: Vec<f64> = members.iter().filter_map(|col| col[i]).collect();
            if values.len() < required {
                None
            } else {
                Some(mean(&values))
            }
        })
        .collect()
}

// --------------------------------------------------------------------------- //
// 合成
// --------------------------------------------------------------------------- //
struct Composition {
    cfsi: Column,
    dims: Vec<(String, Column)>,
    loadings: BTreeMap<String, f64>,
    pca_applied: bool,
}

fn compose_cfsi_equal(dims: &[(String, Column)], n_rows: usize) -> Composition {
    let cols: Vec<&Column> = dims.iter().map(|(_, c)| c).collect();
    let cfsi = (0..n_rows)
        .map(|i| {
            let values: Vec<f64> = cols.iter().filter_map(|c| c[i]).collect();
            if values.len() >= 2 {
                Some(100.0 * mean(&values))
            } else {
                None
            }
        })
        .collect();
    let weight = 1.0 / dims.len() as f64;
    Composition {
        cfsi,
        dims: dims.to_vec(),
        loadings: dims
            .iter()
            .map(|(name, _)| (name.clone(), weight))
            .collect(),
        pca_applied: false,
    }
}

/// 训练期 PCA 第一主成分（载荷与标准化参数冻结）。
fn compose_cfsi_pca(dims: &[(String, Column)], train_mask: &[bool], n_rows: usize) -> Composition {
    let k = dims.len();
    // train_valid = 训练期内所有维度都非 NaN 的行
    let train_rows: Vec<usize> = (0..n_rows)
        .filter(|i| train_mask[*i] && dims.iter().all(|(_, c)| c[*i].is_some()))
        .collect();
    if train_rows.len() < 30 || k < 2 {
        return compose_cfsi_equal(dims, n_rows);
    }
    let means: Vec<f64> = dims
        .iter()
        .map(|(_, c)| mean(&train_rows.iter().filter_map(|i| c[*i]).collect::<Vec<_>>()))
        .collect();
    let stds: Vec<f64> = dims
        .iter()
        .map(|(_, c)| {
            let values: Vec<f64> = train_rows.iter().filter_map(|i| c[*i]).collect();
            let s = std_ddof1(&values);
            if s == 0.0 || s.is_nan() {
                1.0
            } else {
                s
            }
        })
        .collect();

    // z = (dim - mean) / std，NaN → 0
    let z: Vec<Vec<f64>> = (0..n_rows)
        .map(|i| {
            (0..k)
                .map(|j| match dims[j].1[i] {
                    Some(v) => (v - means[j]) / stds[j],
                    None => 0.0,
                })
                .collect()
        })
        .collect();

    // 注意：SVD 的输入是「训练期全部行」（z 已把 NaN 填 0），
    // 不是「训练期内全维度都有效的行」——后者只用于估计均值/标准差。
    let mut train_z: Vec<Vec<f64>> = (0..n_rows)
        .filter(|i| train_mask[*i])
        .map(|i| z[i].clone())
        .collect();
    let mut col_means = vec![0.0; k];
    for row in &train_z {
        for j in 0..k {
            col_means[j] += row[j];
        }
    }
    for value in col_means.iter_mut() {
        *value /= train_z.len() as f64;
    }
    for row in train_z.iter_mut() {
        for j in 0..k {
            row[j] -= col_means[j];
        }
    }
    // 一侧 Jacobi SVD（Hestenes）：直接对训练矩阵做列正交化，
    // 精度与 LAPACK gesdd 同级（不像 AᵀA 那样平方条件数），
    // 否则近并列的得分会让经验 CDF 的排名错位一格。
    let Some(mut loading) = first_right_singular_vector(&train_z) else {
        return compose_cfsi_equal(dims, n_rows);
    };
    let equity_pos = dims
        .iter()
        .position(|(name, _)| name == "equity")
        .unwrap_or(0);
    if loading[equity_pos] < 0.0 {
        for value in loading.iter_mut() {
            *value = -*value;
        }
    }
    let loadings: BTreeMap<String, f64> = dims
        .iter()
        .enumerate()
        .map(|(i, (name, _))| (name.clone(), loading[i]))
        .collect();

    let score: Vec<f64> = z
        .iter()
        .map(|row| row.iter().zip(loading.iter()).map(|(a, b)| a * b).sum())
        .collect();
    let mut train_scores: Vec<f64> = (0..n_rows)
        .filter(|i| train_mask[*i])
        .map(|i| score[i])
        .collect();
    train_scores.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let cfsi: Column = (0..n_rows)
        .map(|i| {
            let available = dims.iter().filter(|(_, c)| c[i].is_some()).count();
            if available < 2 {
                return None;
            }
            let pos = train_scores.partition_point(|v| *v <= score[i]);
            Some((pos as f64 / train_scores.len() as f64).clamp(0.0, 1.0) * 100.0)
        })
        .collect();

    Composition {
        cfsi,
        dims: dims.to_vec(),
        loadings,
        pca_applied: true,
    }
}

/// 一侧 Jacobi SVD：返回矩阵第一右奇异向量（确定性，无随机初值）。
///
/// 算法：反复对列对做正交旋转（Hestenes），收敛后每列范数即奇异值，
/// 取最大范数列对应的旋转后右向量。
fn first_right_singular_vector(matrix: &[Vec<f64>]) -> Option<Vec<f64>> {
    let rows = matrix.len();
    let cols = matrix.first().map(|r| r.len()).unwrap_or(0);
    if rows == 0 || cols == 0 {
        return None;
    }
    // 工作矩阵按列存储（一侧 Jacobi 的天然布局）
    let mut u: Vec<Vec<f64>> = (0..cols)
        .map(|c| (0..rows).map(|r| matrix[r][c]).collect())
        .collect();
    let mut v: Vec<Vec<f64>> = (0..cols)
        .map(|i| (0..cols).map(|j| if i == j { 1.0 } else { 0.0 }).collect())
        .collect();

    for _sweep in 0..60 {
        let mut rotated = false;
        for p in 0..cols {
            for q in (p + 1)..cols {
                let mut alpha = 0.0;
                let mut beta = 0.0;
                let mut gamma = 0.0;
                for r in 0..rows {
                    alpha += u[p][r] * u[p][r];
                    beta += u[q][r] * u[q][r];
                    gamma += u[p][r] * u[q][r];
                }
                if gamma.abs() <= 1e-18 * (alpha * beta).sqrt().max(1e-300) {
                    continue;
                }
                rotated = true;
                let zeta = (beta - alpha) / (2.0 * gamma);
                let t = if zeta >= 0.0 {
                    1.0 / (zeta + (1.0 + zeta * zeta).sqrt())
                } else {
                    -1.0 / (-zeta + (1.0 + zeta * zeta).sqrt())
                };
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = c * t;
                for r in 0..rows {
                    let up = u[p][r];
                    let uq = u[q][r];
                    u[p][r] = c * up - s * uq;
                    u[q][r] = s * up + c * uq;
                }
                for r in 0..cols {
                    let vp = v[p][r];
                    let vq = v[q][r];
                    v[p][r] = c * vp - s * vq;
                    v[q][r] = s * vp + c * vq;
                }
            }
        }
        if !rotated {
            break;
        }
    }

    let mut best = 0usize;
    let mut best_norm = -1.0;
    #[allow(clippy::needless_range_loop)] // 一侧 Jacobi：按列下标同时访问 u 与 v
    for c in 0..cols {
        let norm: f64 = u[c].iter().map(|x| x * x).sum::<f64>().sqrt();
        if norm > best_norm {
            best_norm = norm;
            best = c;
        }
    }
    if best_norm <= 0.0 {
        return None;
    }
    // v 的行是右奇异向量
    Some(v[best].clone())
}

// --------------------------------------------------------------------------- //
// 对外入口
// --------------------------------------------------------------------------- //
/// 完整序列计算结果（供 `cfsi.compute` 与黄金向量回归测试共用）。
pub struct CfsiSeries {
    pub calendar: Vec<String>,
    pub cfsi: Column,
    pub dims: Vec<(String, Column)>,
    pub loadings: BTreeMap<String, f64>,
    pub tau: f64,
    pub q75: f64,
    pub q99: f64,
    pub train_end: String,
    pub pca_applied: bool,
}

impl CfsiSeries {
    pub fn dim_value(&self, dim: &str, idx: usize) -> Option<f64> {
        self.dims
            .iter()
            .find(|(name, _)| name == dim)
            .and_then(|(_, col)| col[idx])
    }
}

/// 读取截至 `as_of` 的日频宽表（只含日频序列；月频不参与 CFSI）。
fn load_daily_frame(ws: &Workspace, as_of: &str, catalog: &SeriesCatalog) -> Result<Frame> {
    let daily_ids: Vec<String> = catalog
        .all()
        .filter(|spec| spec.frequency == "daily")
        .map(|spec| spec.series_id.clone())
        .collect();
    if daily_ids.is_empty() {
        return Err(KernelError::data_missing("序列目录为空，无法计算 CFSI"));
    }
    let placeholders = vec!["?"; daily_ids.len()].join(",");
    let sql = format!(
        "SELECT series_id, obs_date, value FROM series_obs \
         WHERE series_id IN ({placeholders}) AND release_time <= CAST(? AS TIMESTAMP) AND value IS NOT NULL \
         ORDER BY obs_date, series_id"
    );
    let mut stmt = ws
        .conn
        .prepare(&sql)
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let end = crate::pit::as_of_end_of_day(as_of);
    let mut params: Vec<&dyn duckdb::ToSql> =
        daily_ids.iter().map(|s| s as &dyn duckdb::ToSql).collect();
    params.push(&end);
    let mut rows = stmt
        .query(params.as_slice())
        .map_err(|e| KernelError::internal(e.to_string()))?;

    let mut calendar: Vec<String> = Vec::new();
    let mut seen_days: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut raw: Vec<(String, String, f64)> = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        let series_id: String = row
            .get(0)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let day: chrono::NaiveDate = row
            .get(1)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let value: f64 = row
            .get(2)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let day = day.format("%Y-%m-%d").to_string();
        if seen_days.insert(day.clone()) {
            calendar.push(day.clone());
        }
        raw.push((series_id, day, value));
    }
    calendar.sort();

    let index_of: BTreeMap<&str, usize> = calendar
        .iter()
        .enumerate()
        .map(|(i, d)| (d.as_str(), i))
        .collect();
    let mut columns: BTreeMap<String, Column> = BTreeMap::new();
    for series_id in &daily_ids {
        if raw.iter().any(|(sid, _, _)| sid == series_id) {
            columns.insert(series_id.clone(), vec![None; calendar.len()]);
        }
    }
    for (series_id, day, value) in raw {
        if let (Some(col), Some(idx)) = (columns.get_mut(&series_id), index_of.get(day.as_str())) {
            col[*idx] = Some(value);
        }
    }
    Ok(Frame { calendar, columns })
}

/// 计算到 `as_of` 为止的完整 CFSI 序列（供 `db.query` / 黄金向量回归使用）。
/// 截至 `as_of` 的日频交易日历（全部日频序列 obs_date 的并集，升序）。
///
/// 工具层用它对齐双序列：两条序列各自的并集会漏掉第三方序列独有的交易日，
/// 导致滚动窗口错位（2025-10 之后实测差 1e-2 量级）。
pub fn daily_calendar(ws: &Workspace, as_of: &str, catalog: &SeriesCatalog) -> Result<Vec<String>> {
    Ok(load_daily_frame(ws, as_of, catalog)?.calendar)
}

pub fn series(ws: &Workspace, as_of: &str, catalog: &SeriesCatalog) -> Result<CfsiSeries> {
    let frame = load_daily_frame(ws, as_of, catalog)?;
    let n_rows = frame.calendar.len();
    if n_rows == 0 {
        return Err(KernelError::data_missing(
            "六个维度在 as_of 均无可用观测，无法计算（缺失不得用 0 填充）",
        )
        .with_detail(
            json!({"reason": "as_of 之前没有任何日频观测", "as_of": &as_of[..10.min(as_of.len())]}),
        ));
    }

    let indicators = build_indicators(&frame);
    if indicators.is_empty() {
        return Err(KernelError::data_missing(
            "无法从数据中计算任何压力子指标（检查序列 ID）",
        ));
    }

    // 训练期截止日（固定 2021-12-31；短样本按 55% 切分）——继承旧版 `_resolve_train_end`
    let first_day = &frame.calendar[0];
    let last_day = &frame.calendar[n_rows - 1];
    let train_end = if last_day.as_str() > "2022-06-30" && first_day.as_str() <= "2021-12-31" {
        "2021-12-31".to_string()
    } else {
        let pos = ((n_rows as f64 * 0.55).round() as usize)
            .saturating_sub(1)
            .min(n_rows - 1);
        frame.calendar[pos].clone()
    };
    let train_mask: Vec<bool> = frame
        .calendar
        .iter()
        .map(|d| d.as_str() <= train_end.as_str())
        .collect();

    // 训练期 winsorize 边界（1%/99%）后滚动分位
    let mut indicator_pcts: Vec<(&'static str, &'static str, Column)> = Vec::new();
    for indicator in &indicators {
        let train_values: Vec<f64> = (0..n_rows)
            .filter(|i| train_mask[*i])
            .filter_map(|i| indicator.values[i])
            .collect();
        let clipped = if train_values.len() >= 30 {
            let lower = quantile_inclusive(&train_values, 0.01).unwrap_or(f64::NEG_INFINITY);
            let upper = quantile_inclusive(&train_values, 0.99).unwrap_or(f64::INFINITY);
            clip(&indicator.values, lower, upper)
        } else {
            indicator.values.clone()
        };
        let pct = rolling_percentile(&clipped, ROLLING_WINDOW, MIN_PERIODS);
        indicator_pcts.push((indicator.name, indicator.dimension, pct));
    }

    // 维度分位 = 维度内子指标分位等权平均
    let mut dims: Vec<(String, Column)> = Vec::new();
    for dimension in DIMENSIONS {
        let members: Vec<&Column> = indicator_pcts
            .iter()
            .filter(|(_, dim, _)| *dim == dimension)
            .map(|(_, _, col)| col)
            .collect();
        if members.is_empty() {
            continue;
        }
        dims.push((
            dimension.to_string(),
            dimension_percentile(&members, n_rows),
        ));
    }
    if dims.is_empty() {
        return Err(KernelError::data_missing("维度分位计算结果为空"));
    }

    let composition = if dims.len() >= 2 {
        compose_cfsi_pca(&dims, &train_mask, n_rows)
    } else {
        compose_cfsi_equal(&dims, n_rows)
    };

    // τ：训练期 CFSI 的 q90（缺维时按可用维度重新估计，不冻结）
    let train_cfsi: Vec<f64> = (0..n_rows)
        .filter(|i| train_mask[*i])
        .filter_map(|i| composition.cfsi[i])
        .collect();
    if train_cfsi.is_empty() {
        return Err(KernelError::data_missing(
            "训练期没有可用 CFSI 值，无法估计阈值 τ",
        ));
    }
    Ok(CfsiSeries {
        calendar: frame.calendar.clone(),
        cfsi: composition.cfsi.clone(),
        dims: composition.dims.clone(),
        loadings: composition.loadings.clone(),
        tau: quantile(&train_cfsi, 0.90),
        q75: quantile(&train_cfsi, 0.75),
        q99: quantile(&train_cfsi, 0.99),
        train_end,
        pca_applied: composition.pca_applied,
    })
}

pub fn compute(ws: &Workspace, as_of: &str, catalog: &SeriesCatalog) -> Result<Value> {
    let computed = series(ws, as_of, catalog)?;
    let n_rows = computed.calendar.len();
    let last_idx = n_rows - 1;
    let Some(cfsi_now) = computed.cfsi[last_idx] else {
        let missing_now: Vec<&str> = computed
            .dims
            .iter()
            .filter(|(_, col)| col[last_idx].is_none())
            .map(|(name, _)| name.as_str())
            .collect();
        return Err(KernelError::data_missing(format!(
            "as_of 的 CFSI 不可计算（可用维度不足 2 个；缺席维度: {missing_now:?}）"
        ))
        .with_detail(json!({
            "reason": "可用维度不足 2 个，CFSI 不可计算（缺失不得用 0 填充）",
            "missing_dims": missing_now,
            "as_of": &as_of[..10.min(as_of.len())],
        })));
    };

    let level = if cfsi_now >= computed.q99 {
        "critical"
    } else if cfsi_now >= computed.tau {
        "high"
    } else if cfsi_now >= computed.q75 {
        "medium"
    } else {
        "low"
    };

    // 缺席维度（as_of 当日无值）与原因
    let mut dims_json = Map::new();
    let mut missing_dims: Vec<String> = Vec::new();
    let mut limitations: Vec<String> = Vec::new();
    for (name, col) in &computed.dims {
        match col[last_idx] {
            Some(value) => {
                dims_json.insert(
                    name.clone(),
                    json!({
                        "value": crate::numeric::r(value),
                        "weight": computed.loadings.get(name).copied().and_then(crate::numeric::r),
                        "name": dimension_name(name),
                    }),
                );
            }
            None => missing_dims.push(name.clone()),
        }
    }
    // 目录里存在但当前完全没有子指标的维度（连列都没有）
    for dimension in DIMENSIONS {
        if !computed.dims.iter().any(|(name, _)| name == dimension)
            && !missing_dims.iter().any(|d| d == dimension)
        {
            missing_dims.push(dimension.to_string());
            limitations.push(format!(
                "{}维度缺少可用输入序列（需授权/不可达），未参与计算，禁止以 0 或均值填充",
                dimension_name(dimension)
            ));
        }
    }
    for dim in &missing_dims {
        if limitations.iter().any(|l| l.contains(dimension_name(dim))) {
            continue;
        }
        limitations.push(format!(
            "{}维度在 {} 无可用观测（缺失 ≠ 零值），未参与本次计算",
            dimension_name(dim),
            &as_of[..10.min(as_of.len())]
        ));
    }
    if !missing_dims.is_empty() {
        limitations.push(
            "缺维情况下 stress_pca_q90 的 τ 按实际可用维度重新估计、未冻结（ADR-008），六维齐备后口径会变化"
                .to_string(),
        );
    }
    if !computed.pca_applied {
        limitations.push(
            "可用维度不足或训练期有效样本 <30，本次使用分位等权合成而非 PCA 第一主成分".to_string(),
        );
    }
    limitations.push(format!(
        "指数为训练期经验 CDF 映射的压力分位（0–100），非绝对风险度量；训练期截止 {}",
        computed.train_end
    ));

    let provenance = json!({
        "index_version": INDEX_VERSION,
        "label_version": LABEL_VERSION,
        "train_end": computed.train_end,
        "tau_source": if missing_dims.is_empty() { "frozen_train_q90" } else { "reestimated_available_dims" },
        "tau_quantile": 0.90,
        "level_rule": "train_quantile_band",
        "level_bands": {"medium": computed.q75, "high": computed.tau, "critical": computed.q99},
        "pca_applied": computed.pca_applied,
        "loadings": computed.loadings,
        "observations": n_rows,
        "dimensions_used": computed.dims.iter().map(|(name, _)| name.clone()).collect::<Vec<_>>(),
        "as_of": &as_of[..10.min(as_of.len())],
    });

    Ok(json!({
        "cfsi": crate::numeric::r(cfsi_now),
        "level": level,
        "tau": crate::numeric::r(computed.tau),
        "dims": dims_json,
        "missing_dims": missing_dims,
        "limitations": limitations,
        "provenance": provenance,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn col(values: &[Option<f64>]) -> Column {
        values.to_vec()
    }

    #[test]
    fn pct_change_matches_pandas_ratio() {
        let c = col(&[Some(100.0), Some(110.0), None, Some(121.0)]);
        let out = pct_change(&c, 1);
        assert_eq!(out[0], None);
        assert!((out[1].unwrap() - 0.1).abs() < 1e-12);
        assert_eq!(out[2], None);
        assert_eq!(out[3], None); // 前值是 NaN，pct_change 不填充
    }

    #[test]
    fn rolling_percentile_counts_le() {
        let c = col(&[Some(1.0), Some(2.0), Some(3.0), Some(2.0)]);
        let out = rolling_percentile(&c, 10, 2);
        assert_eq!(out[0], None);
        assert!((out[1].unwrap() - 1.0).abs() < 1e-12);
        assert!((out[2].unwrap() - 1.0).abs() < 1e-12);
        // valid=[1,2,3,2]，<=2 的有 3 个 → 3/4
        assert!((out[3].unwrap() - 3.0 / 4.0).abs() < 1e-12);
    }

    #[test]
    fn rolling_std_uses_welford_like_pandas() {
        // pandas rolling.std 用 Welford 单遍；与两遍法差 1 ulp，足以翻转分位并列。
        let c = col(&[
            Some(0.025_254_505_004_477_564),
            Some(0.025_254_505_004_477_564),
        ]);
        let out = rolling_std(&c, 20, 2);
        assert_eq!(out[1], Some(0.0));
        // 与两遍法在一般数据上一致到 1e-15
        let d = col(&[Some(1.0), Some(2.0), Some(4.0), Some(8.0)]);
        let got = rolling_std(&d, 4, 2)[3].unwrap();
        let two_pass = std_ddof1(&[1.0, 2.0, 4.0, 8.0]);
        assert!((got - two_pass).abs() < 1e-15);
    }

    #[test]
    fn dimension_percentile_requires_half_members() {
        // 旧版 `required = max(1, ceil(len * 0.5))`：两个成员时 1 个有效即可
        let a = col(&[Some(0.2), Some(0.4), None]);
        let b = col(&[Some(0.6), None, Some(0.8)]);
        let out = dimension_percentile(&[&a, &b], 3);
        assert!((out[0].unwrap() - 0.4).abs() < 1e-12);
        assert!((out[1].unwrap() - 0.4).abs() < 1e-12);
        assert!((out[2].unwrap() - 0.8).abs() < 1e-12);

        // 四个成员时需要 2 个有效；只有 1 个 → None
        let c = col(&[Some(0.9), None, Some(0.5)]);
        let d = col(&[Some(0.1), None, None]);
        let four = dimension_percentile(&[&a, &b, &c, &d], 3);
        assert!(four[0].is_some()); // 4 个有效
        assert!(four[1].is_none()); // 仅 1/4 有效
        assert!(four[2].is_some()); // 2/4 有效
    }

    #[test]
    fn equal_composition_needs_two_dims() {
        let dims = vec![
            ("equity".to_string(), col(&[Some(0.5), Some(0.2)])),
            ("fx".to_string(), col(&[Some(0.3), None])),
        ];
        let comp = compose_cfsi_equal(&dims, 2);
        assert!((comp.cfsi[0].unwrap() - 40.0).abs() < 1e-12);
        assert!(comp.cfsi[1].is_none());
        assert!(!comp.pca_applied);
    }

    #[test]
    fn first_right_singular_vector_recovers_known_direction() {
        // 列 [2,0,0] 与 [0,1,0]：第一右奇异向量是 [1,0]
        let matrix = vec![vec![2.0, 0.0], vec![0.0, 1.0], vec![0.0, 0.0]];
        let v = first_right_singular_vector(&matrix).unwrap();
        assert!((v[0].abs() - 1.0).abs() < 1e-9);
        assert!(v[1].abs() < 1e-9);
    }
}
