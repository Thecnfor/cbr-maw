"""确定性数值辅助函数（纯 numpy/stdlib，无随机数、无 LLM）。

所有函数在相同输入下返回完全相同结果；浮点输出统一经 :func:`r` 四舍五入，
避免不同调用路径产生末位差异，保证 Evidence 哈希稳定。
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import numpy as np

EPS = 1e-12


# --------------------------------------------------------------------------- #
# 基础转换
# --------------------------------------------------------------------------- #
def r(value: Any, ndigits: int = 10) -> float | None:
    """四舍五入浮点；NaN/inf 转为 None（JSON 安全，表示不可得）。"""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return round(x, ndigits)


def as_date(value: Any) -> date:
    """解析 date/datetime/ISO 字符串为 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise TypeError(f"cannot parse date from {value!r}")


def normalize_history(
    rows: Sequence[Mapping[str, Any]],
    as_of: date,
    lookback: int | None = None,
) -> list[tuple[date, float]]:
    """把 provider.history 的 [{"date","value"}] 规范为升序 (date, float) 并做 PIT 校验。"""
    out: dict[date, float] = {}
    for row in rows or []:
        try:
            day = as_date(row["date"])
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if day > as_of:
            raise ValueError(f"point-in-time violation: row date {day} > as_of {as_of}")
        if not math.isfinite(value):
            continue
        out[day] = value
    items = sorted(out.items())
    if lookback is not None and lookback > 0:
        items = items[-lookback:]
    return items


def values_of(items: Sequence[tuple[date, float]]) -> np.ndarray:
    return np.asarray([v for _, v in items], dtype=float)


def dates_of(items: Sequence[tuple[date, float]]) -> list[date]:
    return [d for d, _ in items]


def simple_returns(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """价格序列 -> 简单收益率序列（长度 n-1）。"""
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        return np.zeros(0)
    prev = arr[:-1]
    out = np.zeros(arr.size - 1)
    mask = np.abs(prev) > EPS
    out[mask] = arr[1:][mask] / prev[mask] - 1.0
    return out


# --------------------------------------------------------------------------- #
# 风险测度
# --------------------------------------------------------------------------- #
def annualized_volatility(returns: Sequence[float] | np.ndarray, periods: int = 252) -> float:
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        return 0.0
    return float(np.std(arr, ddof=1) * math.sqrt(periods))


def quantile(values: Sequence[float] | np.ndarray, q: float) -> float:
    """线性插值分位数（numpy 默认 method="linear"，结果可复现）。"""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    return float(np.quantile(arr, float(q), method="linear"))


def historical_tail(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> tuple[float, float, float]:
    """历史模拟法：返回 (VaR, CVaR, 分位阈值)，均以"损失"为正数、按 sqrt(h) 缩放。"""
    arr = np.asarray(returns, dtype=float)
    alpha = 1.0 - confidence
    q = quantile(arr, alpha)
    var = max(0.0, -q)
    tail = arr[arr <= q + EPS]
    cvar = max(0.0, -float(np.mean(tail))) if tail.size else var
    scale = math.sqrt(max(1, horizon_days))
    return var * scale, cvar * scale, q * scale


def parametric_tail(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> tuple[float, float]:
    """参数法（正态假设）：返回 (VaR, CVaR)，以损失为正数、按 sqrt(h) 缩放。"""
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        return 0.0, 0.0
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    alpha = 1.0 - confidence
    dist = statistics.NormalDist()
    z = dist.inv_cdf(alpha)  # 负值
    var = -(mu + sigma * z)
    cvar = -mu + sigma * dist.pdf(z) / alpha
    scale = math.sqrt(max(1, horizon_days))
    return max(0.0, var) * scale, max(0.0, cvar) * scale


def returns_percentile(returns: Sequence[float] | np.ndarray, value: float | None = None) -> float | None:
    """当前收益在窗口中的分位（0~1）；默认取最后一个观测。"""
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return None
    target = arr[-1] if value is None else float(value)
    return float(np.mean(arr <= target + EPS))


def max_drawdown(path_values: Sequence[float] | np.ndarray) -> float:
    """峰谷最大回撤幅度（正数，如 0.35 表示 35%）。"""
    arr = np.asarray(path_values, dtype=float)
    if arr.size < 2:
        return 0.0
    peak = np.maximum.accumulate(arr)
    denom = np.where(np.abs(peak) > EPS, peak, np.nan)
    drawdown = np.where(np.isfinite(denom), (peak - arr) / denom, 0.0)
    return float(np.nanmax(drawdown))


def max_drawdown_from_returns(returns: Sequence[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + arr)])
    return max_drawdown(wealth)


# --------------------------------------------------------------------------- #
# 时间序列对齐
# --------------------------------------------------------------------------- #
def series_map(items: Sequence[tuple[date, float]]) -> dict[date, float]:
    return {d: float(v) for d, v in items}


def align_series(
    series: Mapping[str, Sequence[tuple[date, float]]]
) -> tuple[list[date], dict[str, np.ndarray]]:
    """多序列按公共日期对齐（升序）。

    返回 ``(dates, {series_id: ndarray})``；若公共日期不足则返回空数组。
    """
    maps = {name: series_map(items) for name, items in series.items()}
    if not maps:
        return [], {}
    common = set(next(iter(maps.values())))
    for m in maps.values():
        common &= set(m)
    dates = sorted(common)
    return dates, {name: np.asarray([m[d] for d in dates], dtype=float) for name, m in maps.items()}


def first_differences(values: np.ndarray) -> np.ndarray:
    return np.diff(np.asarray(values, dtype=float))


def pct_changes(values: np.ndarray) -> np.ndarray:
    return simple_returns(values)


# --------------------------------------------------------------------------- #
# 回归与分位数回归
# --------------------------------------------------------------------------- #
def ols(y: np.ndarray, x: np.ndarray) -> tuple[float, np.ndarray, float]:
    """带截距的 OLS：返回 (intercept, coefs, r2)。``x`` 形状 (n, k)。"""
    yy = np.asarray(y, dtype=float)
    xx = np.asarray(x, dtype=float)
    if xx.ndim == 1:
        xx = xx[:, None]
    n = yy.size
    X = np.column_stack([np.ones(n), xx])
    beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
    fitted = X @ beta
    resid = yy - fitted
    ss_tot = float(np.sum((yy - yy.mean()) ** 2))
    ss_res = float(np.sum(resid**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > EPS else 0.0
    return float(beta[0]), np.asarray(beta[1:], dtype=float), float(r2)


def quantile_regression(
    x: np.ndarray,
    y: np.ndarray,
    tau: float,
    max_iter: int = 400,
    tol: float = 1e-12,
) -> tuple[float, float, int]:
    """单变量分位数回归（IRLS 近似，确定性无随机初值）。

    返回 ``(intercept, slope, iterations)``；用于 ΔCoVaR 的尾部依赖斜率估计。
    """
    xx = np.asarray(x, dtype=float)
    yy = np.asarray(y, dtype=float)
    n = yy.size
    X = np.column_stack([np.ones(n), xx])
    beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
    iters = 0
    for iters in range(1, max_iter + 1):
        resid = yy - X @ beta
        weights = np.where(resid >= 0.0, float(tau), 1.0 - float(tau)) / np.maximum(
            np.abs(resid), 1e-8
        )
        XtW = X.T * weights
        hessian = XtW @ X + np.eye(2) * 1e-12
        new_beta = np.linalg.solve(hessian, XtW @ yy)
        delta = float(np.max(np.abs(new_beta - beta)))
        beta = new_beta
        if delta < tol:
            break
    return float(beta[0]), float(beta[1]), iters


# --------------------------------------------------------------------------- #
# 简化 VAR 与 Diebold-Yilmaz 溢出指数
# --------------------------------------------------------------------------- #
def fit_var(
    returns: np.ndarray, lag: int = 1
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    """OLS 估计 VAR(lag)。

    输入 ``returns`` 形状 (T, N)；返回 ``(intercept, [A_1..A_lag], sigma)``，
    其中 ``Y_t = c + Σ_j A_j Y_{t-j} + e_t``，``sigma`` 为残差协方差矩阵。
    """
    data = np.asarray(returns, dtype=float)
    T, N = data.shape
    if T <= lag + N + 2:
        raise ValueError(f"VAR 样本不足: T={T}, lag={lag}, N={N}")
    rows = T - lag
    Y = data[lag:]
    X = np.ones((rows, 1 + lag * N))
    for j in range(1, lag + 1):
        X[:, 1 + (j - 1) * N : 1 + j * N] = data[lag - j : T - j]
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ coef
    sigma = resid.T @ resid / float(rows)
    intercept = np.asarray(coef[0], dtype=float)
    a_list = [
        np.asarray(coef[1 + j * N : 1 + (j + 1) * N].T, dtype=float) for j in range(lag)
    ]
    return intercept, a_list, sigma


def generalized_fevd(
    a_list: Sequence[np.ndarray], sigma: np.ndarray, horizon: int = 10
) -> np.ndarray:
    """广义预测误差方差分解（GFEVD，顺序无关），返回行归一化矩阵 (N, N)。"""
    sig = np.asarray(sigma, dtype=float) + np.eye(np.shape(sigma)[0]) * 1e-12
    N = sig.shape[0]
    thetas = [np.eye(N)]
    for h in range(1, horizon + 1):
        theta_h = np.zeros((N, N))
        for j, a_mat in enumerate(a_list, start=1):
            if h - j >= 0:
                theta_h = theta_h + a_mat @ thetas[h - j]
        thetas.append(theta_h)

    var_shock = np.diag(sig).copy()
    var_shock = np.where(var_shock > EPS, var_shock, EPS)
    numerator = np.zeros((N, N))
    denominator = np.zeros(N)
    for theta in thetas:
        m = theta @ sig
        numerator += (m * m) / var_shock[None, :]
        denominator += np.sum(m * theta, axis=1)
    denominator = np.where(np.abs(denominator) > EPS, denominator, EPS)
    fevd = numerator / denominator[:, None]
    row_sums = fevd.sum(axis=1, keepdims=True)
    row_sums = np.where(np.abs(row_sums) > EPS, row_sums, EPS)
    return fevd / row_sums


def spillover_index(fevd: np.ndarray) -> float:
    """Diebold-Yilmaz 总溢出指数（%）：100 × 非对角份额均值。"""
    N = fevd.shape[0]
    if N < 2:
        return 0.0
    off_diag = float(fevd.sum() - np.trace(fevd))
    return 100.0 * off_diag / N


# --------------------------------------------------------------------------- #
# 资金流辅助
# --------------------------------------------------------------------------- #
def zscore_latest(values: Sequence[float] | np.ndarray, baseline_window: int) -> float | None:
    """最新值相对过去 baseline_window 个观测（不含当日）的 z-score。"""
    arr = np.asarray(values, dtype=float)
    if arr.size < 3:
        return None
    window = arr[max(0, arr.size - 1 - baseline_window) : arr.size - 1]
    if window.size < 2:
        return None
    std = float(np.std(window, ddof=1))
    if std < EPS:
        return 0.0
    return (float(arr[-1]) - float(np.mean(window))) / std


def percentile_rank(values: Sequence[float] | np.ndarray, value: float | None = None) -> float | None:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return None
    target = arr[-1] if value is None else float(value)
    return float(np.mean(arr <= target + EPS))


def concentration_metrics(
    flows: Sequence[float] | np.ndarray, top_n: int = 5
) -> tuple[float, float]:
    """资金流集中度：返回 (前 top_n 大额流向占比, HHI)。以绝对值计算。"""
    arr = np.abs(np.asarray(flows, dtype=float))
    total = float(arr.sum())
    if total <= EPS or arr.size == 0:
        return 0.0, 0.0
    k = min(max(1, int(top_n)), arr.size)
    top_share = float(np.sort(arr)[-k:].sum() / total)
    shares = arr / total
    hhi = float(np.sum(shares**2))
    return top_share, hhi


def distribution_summary(returns: Sequence[float] | np.ndarray) -> dict[str, float | None]:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return {}
    return {
        "mean": r(np.mean(arr)),
        "std": r(np.std(arr, ddof=1) if arr.size > 1 else 0.0),
        "min": r(np.min(arr)),
        "max": r(np.max(arr)),
        "q01": r(quantile(arr, 0.01)),
        "q05": r(quantile(arr, 0.05)),
        "q10": r(quantile(arr, 0.10)),
        "q50": r(quantile(arr, 0.50)),
        "q90": r(quantile(arr, 0.90)),
        "q95": r(quantile(arr, 0.95)),
        "q99": r(quantile(arr, 0.99)),
    }
