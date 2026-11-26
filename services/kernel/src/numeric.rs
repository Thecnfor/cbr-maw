#![allow(clippy::needless_range_loop)]
//! 确定性数值原语（对齐旧版 `commorcial/src/cbr/tools/_numeric.py`）。
//!
//! 全部为纯函数：不调用 LLM、不使用随机数；相同输入产生完全相同输出。
//! 浮点输出统一经 [`r`] 四舍五入（10 位），保证证据哈希稳定。
//!
//! 说明：本模块大量按下标同时访问多个数组（QR 分解、分位、bootstrap），
//! 改成迭代器会破坏与数学公式的一一对应且更易越界，故局部 allow。

/// 旧版 `r(value, ndigits=10)`：四舍五入，NaN/inf → None（表示不可得）。
pub fn r(value: f64) -> Option<f64> {
    if !value.is_finite() {
        return None;
    }
    // Rust 的定点格式化与 Python `round` 同为「精确二进制值上的 round-half-even」。
    format!("{value:.10}").parse::<f64>().ok()
}

/// 旧版 `r(value, ndigits)`（可指定位数）。
pub fn r_n(value: f64, ndigits: usize) -> Option<f64> {
    if !value.is_finite() {
        return None;
    }
    format!("{value:.*}", ndigits).parse::<f64>().ok()
}

pub fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

/// 样本标准差（`ddof=1`）。
pub fn std_ddof1(values: &[f64]) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let m = mean(values);
    let var = values.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / (values.len() - 1) as f64;
    var.sqrt()
}

/// 带并列处理的符号：`-1 / 0 / +1`（并列取 0）。
///
/// **不要用 `f64::signum`**：它对 ±0.0 返回 ±1.0（copysign 语义），
/// 而 numpy 的 `np.sign` 对并列返回 0。Kendall tau 的并列对必须记 0，
/// 否则并列数不同会让 tau 整体偏移（例如黄金向量里的 3 个并列对）。
pub fn sign_tie(diff: f64) -> f64 {
    if diff > 0.0 {
        1.0
    } else if diff < 0.0 {
        -1.0
    } else {
        0.0
    }
}

/// numpy `quantile(..., method="linear")`。
pub fn quantile(values: &[f64], q: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted: Vec<f64> = values.iter().copied().filter(|v| v.is_finite()).collect();
    if sorted.is_empty() {
        return 0.0;
    }
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if sorted.len() == 1 {
        return sorted[0];
    }
    let pos = (sorted.len() - 1) as f64 * q;
    let lo = pos.floor();
    let hi = pos.ceil();
    let lo_idx = lo as usize;
    let hi_idx = hi as usize;
    if lo_idx == hi_idx {
        return sorted[lo_idx];
    }
    let frac = pos - lo;
    sorted[lo_idx] + (sorted[hi_idx] - sorted[lo_idx]) * frac
}

pub fn median(values: &[f64]) -> f64 {
    quantile(values, 0.5)
}

/// 旧版 `simple_returns`：价格序列 → 简单收益率。
pub fn simple_returns(values: &[f64]) -> Vec<f64> {
    if values.len() < 2 {
        return Vec::new();
    }
    let mut out = Vec::with_capacity(values.len() - 1);
    for i in 0..values.len() - 1 {
        let prev = values[i];
        if prev.abs() > 1e-12 {
            out.push(values[i + 1] / prev - 1.0);
        } else {
            out.push(0.0);
        }
    }
    out
}

/// 旧版 `annualized_volatility`。
pub fn annualized_volatility(returns: &[f64], periods: i64) -> f64 {
    if returns.len() < 2 {
        return 0.0;
    }
    std_ddof1(returns) * (periods as f64).sqrt()
}

/// 旧版 `historical_tail`：历史模拟法，返回 (VaR, CVaR, 分位阈值)，损失为正。
pub fn historical_tail(returns: &[f64], confidence: f64, horizon_days: i64) -> (f64, f64, f64) {
    let alpha = 1.0 - confidence;
    let q = quantile(returns, alpha);
    let var = q.abs().max(0.0);
    let tail: Vec<f64> = returns
        .iter()
        .copied()
        .filter(|v| *v <= q + 1e-12)
        .collect();
    let cvar = if tail.is_empty() {
        var
    } else {
        (-mean(&tail)).max(0.0)
    };
    let scale = (horizon_days.max(1) as f64).sqrt();
    (var * scale, cvar * scale, q * scale)
}

/// 旧版 `parametric_tail`：正态假设下的 (VaR, CVaR)。
pub fn parametric_tail(returns: &[f64], confidence: f64, horizon_days: i64) -> (f64, f64) {
    if returns.len() < 2 {
        return (0.0, 0.0);
    }
    let mu = mean(returns);
    let sigma = std_ddof1(returns);
    let alpha = 1.0 - confidence;
    let z = normal_inv_cdf(alpha);
    let var = -(mu + sigma * z);
    let cvar = -mu + sigma * normal_pdf(z) / alpha;
    let scale = (horizon_days.max(1) as f64).sqrt();
    (var.max(0.0) * scale, cvar.max(0.0) * scale)
}

/// 当前收益在窗口中的分位（0~1）。
pub fn returns_percentile(returns: &[f64]) -> Option<f64> {
    if returns.is_empty() {
        return None;
    }
    let target = returns[returns.len() - 1];
    let hits = returns.iter().filter(|v| **v <= target + 1e-12).count();
    Some(hits as f64 / returns.len() as f64)
}

/// 峰谷最大回撤幅度（正数）。
pub fn max_drawdown(path: &[f64]) -> f64 {
    if path.len() < 2 {
        return 0.0;
    }
    let mut peak = f64::NEG_INFINITY;
    let mut worst: f64 = 0.0;
    for value in path {
        if *value > peak {
            peak = *value;
        }
        if peak.abs() > 1e-12 {
            let dd = (peak - value) / peak;
            if dd > worst {
                worst = dd;
            }
        }
    }
    worst
}

pub fn max_drawdown_from_returns(returns: &[f64]) -> f64 {
    let mut wealth = Vec::with_capacity(returns.len() + 1);
    wealth.push(1.0);
    for r in returns {
        wealth.push(wealth[wealth.len() - 1] * (1.0 + r));
    }
    max_drawdown(&wealth)
}

/// 旧版 `zscore_latest`：最新值相对之前窗口（不含当日）的 z-score。
pub fn zscore_latest(values: &[f64], baseline_window: usize) -> Option<f64> {
    if values.len() < 3 {
        return None;
    }
    let start = values.len().saturating_sub(1 + baseline_window);
    let window = &values[start..values.len() - 1];
    if window.len() < 2 {
        return None;
    }
    let std = std_ddof1(window);
    if std < 1e-12 {
        return Some(0.0);
    }
    Some((values[values.len() - 1] - mean(window)) / std)
}

/// 旧版 `percentile_rank`。
pub fn percentile_rank(values: &[f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let target = values[values.len() - 1];
    let hits = values.iter().filter(|v| **v <= target + 1e-12).count();
    Some(hits as f64 / values.len() as f64)
}

/// 旧版 `concentration_metrics`：返回 (前 top_n 大额占比, HHI)。
pub fn concentration_metrics(flows: &[f64], top_n: usize) -> (f64, f64) {
    if flows.is_empty() {
        return (0.0, 0.0);
    }
    let abs: Vec<f64> = flows.iter().map(|v| v.abs()).collect();
    let total: f64 = abs.iter().sum();
    if total <= 1e-12 {
        return (0.0, 0.0);
    }
    let mut sorted = abs.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let k = top_n.max(1).min(sorted.len());
    let top_share: f64 = sorted[sorted.len() - k..].iter().sum::<f64>() / total;
    let hhi: f64 = abs.iter().map(|v| (v / total) * (v / total)).sum();
    (top_share, hhi)
}

/// 旧版 `distribution_summary`。
pub fn distribution_summary(returns: &[f64]) -> serde_json::Map<String, serde_json::Value> {
    let mut map = serde_json::Map::new();
    if returns.is_empty() {
        return map;
    }
    let mut min = f64::INFINITY;
    let mut max = f64::NEG_INFINITY;
    for value in returns {
        min = min.min(*value);
        max = max.max(*value);
    }
    let insert =
        |map: &mut serde_json::Map<String, serde_json::Value>, key: &str, v: Option<f64>| {
            map.insert(
                key.to_string(),
                match v {
                    Some(x) => serde_json::json!(x),
                    None => serde_json::Value::Null,
                },
            );
        };
    insert(&mut map, "mean", r(mean(returns)));
    insert(&mut map, "std", r(std_ddof1(returns)));
    insert(&mut map, "min", r(min));
    insert(&mut map, "max", r(max));
    insert(&mut map, "q01", r(quantile(returns, 0.01)));
    insert(&mut map, "q05", r(quantile(returns, 0.05)));
    insert(&mut map, "q10", r(quantile(returns, 0.10)));
    insert(&mut map, "q50", r(quantile(returns, 0.50)));
    insert(&mut map, "q90", r(quantile(returns, 0.90)));
    insert(&mut map, "q95", r(quantile(returns, 0.95)));
    insert(&mut map, "q99", r(quantile(returns, 0.99)));
    map
}

// --------------------------------------------------------------------------- //
// 小型稠密矩阵（维度 ≤ 数十，纯循环即可）
// --------------------------------------------------------------------------- //
/// 行主序稠密矩阵。
#[derive(Clone, Debug)]
pub struct Mat {
    pub rows: usize,
    pub cols: usize,
    pub data: Vec<f64>,
}

impl Mat {
    pub fn zeros(rows: usize, cols: usize) -> Self {
        Self {
            rows,
            cols,
            data: vec![0.0; rows * cols],
        }
    }

    pub fn from_rows(rows: Vec<Vec<f64>>) -> Self {
        let n_rows = rows.len();
        let n_cols = rows.first().map(|r| r.len()).unwrap_or(0);
        let mut data = Vec::with_capacity(n_rows * n_cols);
        for row in rows {
            data.extend_from_slice(&row);
        }
        Self {
            rows: n_rows,
            cols: n_cols,
            data,
        }
    }

    pub fn at(&self, r: usize, c: usize) -> f64 {
        self.data[r * self.cols + c]
    }

    pub fn set(&mut self, r: usize, c: usize, v: f64) {
        self.data[r * self.cols + c] = v;
    }

    pub fn row(&self, r: usize) -> Vec<f64> {
        (0..self.cols).map(|c| self.at(r, c)).collect()
    }

    pub fn col(&self, c: usize) -> Vec<f64> {
        (0..self.rows).map(|r| self.at(r, c)).collect()
    }

    pub fn matmul(&self, other: &Mat) -> Mat {
        let mut out = Mat::zeros(self.rows, other.cols);
        for i in 0..self.rows {
            for k in 0..self.cols {
                let a = self.at(i, k);
                if a == 0.0 {
                    continue;
                }
                for j in 0..other.cols {
                    let v = out.at(i, j) + a * other.at(k, j);
                    out.set(i, j, v);
                }
            }
        }
        out
    }

    pub fn transpose(&self) -> Mat {
        let mut out = Mat::zeros(self.cols, self.rows);
        for i in 0..self.rows {
            for j in 0..self.cols {
                out.set(j, i, self.at(i, j));
            }
        }
        out
    }

    pub fn identity(n: usize) -> Mat {
        let mut out = Mat::zeros(n, n);
        for i in 0..n {
            out.set(i, i, 1.0);
        }
        out
    }
}

/// 最小二乘（Householder QR），返回 `X` 使 `A·X ≈ B`。
pub fn lstsq(a: &Mat, b: &Mat) -> Option<Mat> {
    let n = a.rows;
    let k = a.cols;
    if n < k || b.rows != n {
        return None;
    }
    let mut r = a.clone();
    let mut qt = Mat::identity(n);
    for j in 0..k {
        let mut norm = 0.0;
        for i in j..n {
            norm += r.at(i, j) * r.at(i, j);
        }
        norm = norm.sqrt();
        if norm <= 1e-14 {
            continue;
        }
        let alpha = if r.at(j, j) > 0.0 { -norm } else { norm };
        let mut v = vec![0.0; n];
        for i in j..n {
            v[i] = r.at(i, j);
        }
        v[j] -= alpha;
        let v_norm2: f64 = v[j..].iter().map(|x| x * x).sum();
        if v_norm2 <= 1e-300 {
            continue;
        }
        for c in j..k {
            let mut dot = 0.0;
            for i in j..n {
                dot += v[i] * r.at(i, c);
            }
            let factor = 2.0 * dot / v_norm2;
            for i in j..n {
                let value = r.at(i, c) - factor * v[i];
                r.set(i, c, value);
            }
        }
        for c in 0..n {
            let mut dot = 0.0;
            for i in j..n {
                dot += v[i] * qt.at(i, c);
            }
            let factor = 2.0 * dot / v_norm2;
            for i in j..n {
                let value = qt.at(i, c) - factor * v[i];
                qt.set(i, c, value);
            }
        }
    }
    // 回代：R·X = (QᵀB) 的前 k 行
    let mut coef = Mat::zeros(k, b.cols);
    for i in 0..k {
        for j in 0..b.cols {
            let mut acc = 0.0;
            for r in 0..n {
                acc += qt.at(i, r) * b.at(r, j);
            }
            coef.set(i, j, acc);
        }
    }
    for row in (0..k).rev() {
        let pivot = r.at(row, row);
        if pivot.abs() < 1e-300 {
            return None;
        }
        for j in 0..b.cols {
            let value = coef.at(row, j) / pivot;
            coef.set(row, j, value);
        }
        for i in 0..row {
            let factor = r.at(i, row);
            if factor == 0.0 {
                continue;
            }
            for j in 0..b.cols {
                let value = coef.at(i, j) - factor * coef.at(row, j);
                coef.set(i, j, value);
            }
        }
    }
    Some(coef)
}

/// 旧版 `ols`：带截距的普通最小二乘，返回 (截距, 系数, R²)。
pub fn ols(y: &[f64], x: &Mat) -> Option<(f64, Vec<f64>, f64)> {
    let n = y.len();
    if n == 0 || x.rows != n {
        return None;
    }
    let k = x.cols;
    let mut design = Mat::zeros(n, k + 1);
    for i in 0..n {
        design.set(i, 0, 1.0);
        for j in 0..k {
            design.set(i, j + 1, x.at(i, j));
        }
    }
    let y_mat = Mat::from_rows(y.iter().map(|v| vec![*v]).collect());
    let coef = lstsq(&design, &y_mat)?;
    let intercept = coef.at(0, 0);
    let betas: Vec<f64> = (0..k).map(|j| coef.at(j + 1, 0)).collect();

    let y_mean = mean(y);
    let mut ss_tot = 0.0;
    let mut ss_res = 0.0;
    for i in 0..n {
        let mut fitted = intercept;
        for j in 0..k {
            fitted += betas[j] * x.at(i, j);
        }
        ss_res += (y[i] - fitted) * (y[i] - fitted);
        ss_tot += (y[i] - y_mean) * (y[i] - y_mean);
    }
    let r2 = if ss_tot > 1e-12 {
        1.0 - ss_res / ss_tot
    } else {
        0.0
    };
    Some((intercept, betas, r2))
}

/// 旧版 `quantile_regression`：单变量分位数回归（IRLS 近似）。
pub fn quantile_regression(x: &[f64], y: &[f64], tau: f64) -> Option<(f64, f64, usize)> {
    let n = x.len();
    if n < 3 || y.len() != n {
        return None;
    }
    let design = Mat::from_rows(x.iter().map(|v| vec![*v]).collect());
    let (mut intercept, betas, _) = ols(y, &design)?;
    let mut slope = betas[0];
    let mut iterations = 0;
    for iter in 1..=400 {
        iterations = iter;
        let mut a11 = 0.0;
        let mut a12 = 0.0;
        let mut a22 = 0.0;
        let mut b1 = 0.0;
        let mut b2 = 0.0;
        for i in 0..n {
            let resid = y[i] - (intercept + slope * x[i]);
            let w = if resid >= 0.0 { tau } else { 1.0 - tau } / resid.abs().max(1e-8);
            a11 += w;
            a12 += w * x[i];
            a22 += w * x[i] * x[i];
            b1 += w * y[i];
            b2 += w * x[i] * y[i];
        }
        a11 += 1e-12;
        a22 += 1e-12;
        let det = a11 * a22 - a12 * a12;
        if det.abs() < 1e-300 {
            break;
        }
        let new_intercept = (b1 * a22 - b2 * a12) / det;
        let new_slope = (a11 * b2 - a12 * b1) / det;
        let delta = (new_intercept - intercept)
            .abs()
            .max((new_slope - slope).abs());
        intercept = new_intercept;
        slope = new_slope;
        if delta < 1e-12 {
            break;
        }
    }
    Some((intercept, slope, iterations))
}

/// 旧版 `fit_var`：OLS 估计 VAR(lag)，返回 (截距, [A_1..A_lag], 残差协方差)。
pub fn fit_var(returns: &Mat, lag: usize) -> Option<(Vec<f64>, Vec<Mat>, Mat)> {
    let t = returns.rows;
    let n = returns.cols;
    if t <= lag + n + 2 {
        return None;
    }
    let rows = t - lag;
    let p = 1 + lag * n;
    let mut design = Mat::zeros(rows, p);
    let mut y_mat = Mat::zeros(rows, n);
    for r in 0..rows {
        design.set(r, 0, 1.0);
        for j in 1..=lag {
            let col = 1 + (j - 1) * n;
            for c in 0..n {
                design.set(r, col + c, returns.at(lag - j + r, c));
            }
        }
        for c in 0..n {
            y_mat.set(r, c, returns.at(lag + r, c));
        }
    }
    let coef = lstsq(&design, &y_mat)?;
    let intercept: Vec<f64> = (0..n).map(|c| coef.at(0, c)).collect();
    let mut a_list = Vec::with_capacity(lag);
    for j in 0..lag {
        let mut a = Mat::zeros(n, n);
        for c in 0..n {
            for r in 0..n {
                a.set(r, c, coef.at(1 + j * n + c, r));
            }
        }
        a_list.push(a);
    }
    // 残差 = Y - X·coef
    let mut resid = Mat::zeros(rows, n);
    for r in 0..rows {
        for c in 0..n {
            let mut fitted = 0.0;
            for p in 0..(1 + lag * n) {
                fitted += design.at(r, p) * coef.at(p, c);
            }
            resid.set(r, c, y_mat.at(r, c) - fitted);
        }
    }
    let mut sigma = Mat::zeros(n, n);
    for i in 0..n {
        for j in 0..n {
            let mut acc = 0.0;
            for r in 0..rows {
                acc += resid.at(r, i) * resid.at(r, j);
            }
            sigma.set(i, j, acc / rows as f64);
        }
    }
    Some((intercept, a_list, sigma))
}

/// 旧版 `generalized_fevd`：广义预测误差方差分解（顺序无关），返回行归一化矩阵。
pub fn generalized_fevd(a_list: &[Mat], sigma: &Mat, horizon: usize) -> Mat {
    let n = sigma.rows;
    let mut sig = sigma.clone();
    for i in 0..n {
        sig.set(i, i, sig.at(i, i) + 1e-12);
    }
    let mut thetas: Vec<Mat> = vec![Mat::identity(n)];
    for h in 1..=horizon {
        let mut theta = Mat::zeros(n, n);
        for (j, a_mat) in a_list.iter().enumerate() {
            if h > j {
                let prev = &thetas[h - j - 1];
                let term = a_mat.matmul(prev);
                for i in 0..n {
                    for c in 0..n {
                        theta.set(i, c, theta.at(i, c) + term.at(i, c));
                    }
                }
            }
        }
        thetas.push(theta);
    }
    let mut var_shock = vec![0.0; n];
    for i in 0..n {
        var_shock[i] = sig.at(i, i);
        if var_shock[i] <= 1e-12 {
            var_shock[i] = 1e-12;
        }
    }
    let mut numerator = Mat::zeros(n, n);
    let mut denominator = vec![0.0; n];
    for theta in &thetas {
        let m = theta.matmul(&sig);
        for i in 0..n {
            for j in 0..n {
                numerator.set(
                    i,
                    j,
                    numerator.at(i, j) + m.at(i, j) * m.at(i, j) / var_shock[j],
                );
            }
            let mut acc = 0.0;
            for j in 0..n {
                acc += m.at(i, j) * theta.at(i, j);
            }
            denominator[i] += acc;
        }
    }
    for value in denominator.iter_mut() {
        if value.abs() <= 1e-12 {
            *value = 1e-12;
        }
    }
    let mut fevd = Mat::zeros(n, n);
    for i in 0..n {
        for j in 0..n {
            fevd.set(i, j, numerator.at(i, j) / denominator[i]);
        }
    }
    for i in 0..n {
        let mut sum = 0.0;
        for j in 0..n {
            sum += fevd.at(i, j);
        }
        if sum.abs() <= 1e-12 {
            sum = 1e-12;
        }
        for j in 0..n {
            fevd.set(i, j, fevd.at(i, j) / sum);
        }
    }
    fevd
}

/// 旧版 `spillover_index`：Diebold-Yilmaz 总溢出指数（百分数）。
pub fn spillover_index(fevd: &Mat) -> f64 {
    let n = fevd.rows;
    if n < 2 {
        return 0.0;
    }
    let mut off_diagonal = 0.0;
    for i in 0..n {
        for j in 0..n {
            if i != j {
                off_diagonal += fevd.at(i, j);
            }
        }
    }
    100.0 * off_diagonal / n as f64
}

/// 标准正态密度。
pub fn normal_pdf(z: f64) -> f64 {
    (-0.5 * z * z).exp() / (2.0 * std::f64::consts::PI).sqrt()
}

/// 标准正态分位函数（Wichura AS241 / PPND16，精度约 1e-15）。
pub fn normal_inv_cdf(p: f64) -> f64 {
    if p <= 0.0 {
        return f64::NEG_INFINITY;
    }
    if p >= 1.0 {
        return f64::INFINITY;
    }
    // Horner 求值（系数按 x^7 .. x^0 排列）。
    fn horner(coeffs: &[f64], x: f64) -> f64 {
        let mut acc = 0.0;
        for c in coeffs {
            acc = acc * x + c;
        }
        acc
    }

    let q = p - 0.5;
    if q.abs() <= 0.425 {
        let r = 0.180625 - q * q;
        let num = [
            2509.0809287301227,
            33_430.575_583_588_13,
            67_265.770_927_008_7,
            45_921.953_931_549_87,
            13_731.693_765_509_46,
            1_971.590_950_306_551_4,
            133.14166789178438,
            3.3871328727963665,
        ];
        let den = [
            5226.495278852546,
            28_729.085_735_721_943,
            39_307.895_800_092_71,
            21_213.794_301_586_596,
            5394.196021424751,
            687.1870074920579,
            42.31333070160091,
            1.0,
        ];
        return q * horner(&num, r) / horner(&den, r);
    }

    let mut r = (-(p.min(1.0 - p)).ln()).sqrt();
    let value = if r <= 5.0 {
        r -= 1.6;
        let num = [
            7.745_450_142_783_414e-4,
            0.022723844989269185,
            0.2417807251774506,
            1.2704582524523684,
            3.6478483247632046,
            5.769497221460691,
            4.630337846156545,
            1.4234371107496836,
        ];
        let den = [
            1.050_750_071_644_416_8e-9,
            5.475_938_084_995_345e-4,
            0.015198666563616457,
            0.14810397642748008,
            0.6897673349851,
            1.6763848301838038,
            2.053191626637759,
            1.0,
        ];
        horner(&num, r) / horner(&den, r)
    } else {
        r -= 5.0;
        let num = [
            2.010_334_399_292_288e-7,
            2.711_555_568_743_487_6e-5,
            0.0012426609473880784,
            0.026532189526576123,
            0.2965605718285049,
            1.7848265399172913,
            5.463784911164114,
            6.657904643501104,
        ];
        let den = [
            2.044_263_103_389_94e-15,
            1.421_511_758_316_446e-7,
            1.846_318_317_510_054_7e-5,
            7.868_691_311_456_133e-4,
            0.014875361290850615,
            0.1369298809227358,
            0.5998322065558879,
            1.0,
        ];
        horner(&num, r) / horner(&den, r)
    };
    if q < 0.0 {
        -value
    } else {
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantile_matches_numpy_linear() {
        let values = vec![1.0, 2.0, 3.0, 4.0];
        assert!((quantile(&values, 0.5) - 2.5).abs() < 1e-12);
        assert!((quantile(&values, 0.05) - 1.15).abs() < 1e-12);
    }

    #[test]
    fn normal_inv_cdf_matches_known_values() {
        assert!((normal_inv_cdf(0.05) - -1.6448536269514727).abs() < 1e-9);
        assert!((normal_inv_cdf(0.975) - 1.959963984540054).abs() < 1e-9);
        assert!((normal_inv_cdf(0.5) - 0.0).abs() < 1e-12);
    }

    #[test]
    fn ols_recovers_exact_line() {
        let x = Mat::from_rows(vec![vec![1.0], vec![2.0], vec![3.0], vec![4.0]]);
        let y = vec![3.0, 5.0, 7.0, 9.0];
        let (intercept, betas, r2) = ols(&y, &x).unwrap();
        assert!((intercept - 1.0).abs() < 1e-9);
        assert!((betas[0] - 2.0).abs() < 1e-9);
        assert!((r2 - 1.0).abs() < 1e-12);
    }

    #[test]
    fn round_matches_python_bankers_rounding() {
        assert_eq!(r(2.5), Some(2.5));
        assert_eq!(r(0.1 + 0.2), Some(0.3));
    }
}
