"""统一学习器封装：Logit / LASSO / XGBoost（缺失依赖时自动降级）。

设计目标：

- **确定性**：固定 ``random_state``、``n_jobs=1``，相同输入产生相同概率；
- **缺失值鲁棒**：树模型（XGBoost）原生支持 NaN；线性模型用训练期中位数插补
  （插补器只在训练数据上 fit，不引入未来信息）；
- **可解释归因**：提供 ``feature_contributions`` 单样本归因：
  XGBoost 用 ``pred_contribs``（精确 SHAP 值），线性模型用 ``coef × 标准化特征``，
  其他模型退化为 ``全局重要性 × 标准化特征``，用于 ``RiskSignal.drivers`` 与
  模态贡献计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

try:  # pragma: no cover - 依赖可能缺失
    import xgboost as _xgboost

    HAS_XGBOOST = True
except ImportError:  # pragma: no cover
    _xgboost = None  # type: ignore[assignment]
    HAS_XGBOOST = False

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


#: 支持的学习器类型
LEARNER_KINDS: tuple[str, ...] = ("xgboost", "logit", "lasso", "hist")


@dataclass
class Learner:
    """统一分类学习器（二分类：高压力状态）。

    Args:
        kind: ``xgboost`` / ``logit`` / ``lasso`` / ``hist``。
        seed: 随机种子（确定性）。
        params: 透传给底层估计器的参数（可覆盖默认值）。
    """

    kind: str = "xgboost"
    seed: int = 42
    params: dict[str, Any] = field(default_factory=dict)
    feature_names_: list[str] = field(default_factory=list, init=False, repr=False)
    _estimator: Any = field(default=None, init=False, repr=False)
    _constant: float | None = field(default=None, init=False, repr=False)
    _mean: np.ndarray | None = field(default=None, init=False, repr=False)
    _std: np.ndarray | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in LEARNER_KINDS:
            raise ValueError(f"不支持的学习器类型 {self.kind!r}，可选 {LEARNER_KINDS}")
        if self.kind == "xgboost" and not HAS_XGBOOST:
            # 缺少 xgboost 时自动降级为 HistGradientBoosting，保证契约可用
            self.kind = "hist"

    # ------------------------------------------------------------------ #
    # 训练 / 预测
    # ------------------------------------------------------------------ #
    def fit(self, X: pd.DataFrame, y: pd.Series, feature_names: list[str] | None = None) -> "Learner":
        """拟合二分类模型。

        Args:
            X: 特征矩阵（行=样本，列=特征）。
            y: 0/1 标签（缺失样本应事先剔除）。
            feature_names: 特征列顺序（默认取 ``X.columns``）。

        Returns:
            self（便于链式调用）。
        """
        self.feature_names_ = list(feature_names or X.columns)
        frame = X.loc[:, self.feature_names_]
        target = pd.Series(y).astype(float).to_numpy()
        valid = np.isfinite(target)
        frame = frame.loc[valid]
        target = target[valid]
        if target.size < 10:
            self._constant = float(np.clip(np.nanmean(target) if target.size else 0.5, 0.05, 0.95))
            self._mean, self._std = self._nan_scaler(frame)
            return self
        if np.unique(target).size < 2:
            self._constant = float(np.clip(np.mean(target), 0.02, 0.98))
            self._mean, self._std = self._nan_scaler(frame)
            return self
        self._mean, self._std = self._nan_scaler(frame)
        self._estimator = self._build_estimator(target)
        self._estimator.fit(frame, target)
        return self

    @staticmethod
    def _nan_scaler(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """训练期标准化参数：全 NaN 列以 mean=0/std=1 占位，并抑制 numpy 空切片告警。"""
        import warnings

        array = frame.to_numpy(dtype=float)
        if array.size == 0:
            return np.zeros(array.shape[1]), np.ones(array.shape[1])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(array, axis=0)
            std = np.nanstd(array, axis=0)
        mean = np.where(np.isfinite(mean), mean, 0.0)
        std = np.where((std == 0) | ~np.isfinite(std), 1.0, std)
        return mean, std

    def _build_estimator(self, y: np.ndarray) -> Any:
        """按学习器类型构造 sklearn 兼容估计器。"""
        if self.kind == "xgboost":
            defaults: dict[str, Any] = {
                "n_estimators": 120,
                "max_depth": 3,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 3,
                "reg_lambda": 1.0,
                "random_state": self.seed,
                "n_jobs": 1,
                "eval_metric": "logloss",
                "tree_method": "hist",
                "verbosity": 0,
            }
            defaults.update(self.params)
            return _xgboost.XGBClassifier(**defaults)
        if self.kind == "hist":
            defaults = {
                "max_iter": 120,
                "max_depth": 3,
                "learning_rate": 0.06,
                "l2_regularization": 1.0,
                "random_state": self.seed,
            }
            defaults.update(self.params)
            return Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    ("clf", HistGradientBoostingClassifier(**defaults)),
                ]
            )
        # 线性模型：logit / lasso（sklearn>=1.8 使用 l1_ratio 替代已弃用的 penalty）
        is_lasso = self.kind == "lasso"
        solver = "liblinear" if is_lasso else "lbfgs"
        defaults = {
            "C": 0.5,
            "solver": solver,
            "max_iter": 2000,
            "class_weight": "balanced",
            "random_state": self.seed,
        }
        try:  # pragma: no cover - 依 sklearn 版本分支
            from sklearn import __version__ as sklearn_version

            major, minor = (int(part) for part in sklearn_version.split(".")[:2])
            if (major, minor) >= (1, 8):
                defaults["l1_ratio"] = 1.0 if is_lasso else 0.0
            else:
                defaults["penalty"] = "l1" if is_lasso else "l2"
        except (ImportError, ValueError):  # pragma: no cover
            defaults["penalty"] = "l1" if is_lasso else "l2"
        defaults.update(self.params)
        return Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(**defaults)),
            ]
        )

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """返回正类（高压力）概率数组；模型不可用时返回常数概率。"""
        frame = X.loc[:, self.feature_names_] if self.feature_names_ else X
        if self._constant is not None or self._estimator is None:
            constant = 0.5 if self._constant is None else self._constant
            return np.full(frame.shape[0], constant, dtype=float)
        proba = self._estimator.predict_proba(frame)
        if proba.ndim == 2 and proba.shape[1] >= 2:
            return proba[:, 1].astype(float)
        return np.asarray(proba, dtype=float).ravel()

    # ------------------------------------------------------------------ #
    # 归因
    # ------------------------------------------------------------------ #
    def feature_contributions(self, x: pd.Series) -> np.ndarray:
        """单样本特征贡献（有符号，正值推高风险概率）。

        Args:
            x: 单行特征（列名须与训练时一致）。

        Returns:
            与 ``feature_names_`` 对齐的贡献数组；无法归因时返回全 0。
        """
        n = len(self.feature_names_)
        if self._estimator is None:
            return np.zeros(n, dtype=float)
        frame = pd.DataFrame([x.reindex(self.feature_names_).to_numpy(dtype=float)], columns=self.feature_names_)
        # 1) XGBoost：精确 SHAP 值（pred_contribs，最后一列为 bias）
        if self.kind == "xgboost" and HAS_XGBOOST:
            try:  # pragma: no cover - 依赖运行环境
                booster = self._estimator.get_booster()
                matrix = _xgboost.DMatrix(frame, feature_names=self.feature_names_)
                contrib = np.asarray(booster.predict(matrix, pred_contribs=True))[0]
                return contrib[:n].astype(float)
            except Exception:  # noqa: BLE001 - 降级到通用归因
                pass
        # 2) 线性模型：系数 × 标准化特征
        inner = self._inner_estimator()
        if inner is not None and hasattr(inner, "coef_"):
            transformed = self._transform(frame)
            coef = np.asarray(inner.coef_).ravel()
            if transformed.shape[1] == coef.size:
                return (coef * transformed).ravel().astype(float)
        # 3) 通用降级：全局重要性 × 标准化特征偏离
        importances = self.feature_importances()
        if importances is None:
            return np.zeros(n, dtype=float)
        values = frame.to_numpy(dtype=float).ravel()
        z = (values - self._mean) / self._std if self._mean is not None else np.zeros(n)
        z = np.where(np.isfinite(z), z, 0.0)
        return (importances * z).astype(float)

    def feature_importances(self) -> np.ndarray | None:
        """全局特征重要性（若估计器不提供则返回 None）。"""
        if self._estimator is None:
            return None
        estimator = self._estimator
        if hasattr(estimator, "feature_importances_"):
            try:
                return np.asarray(estimator.feature_importances_, dtype=float)
            except Exception:  # noqa: BLE001  # pragma: no cover
                return None
        inner = self._inner_estimator()
        if inner is not None and hasattr(inner, "coef_"):
            return np.abs(np.asarray(inner.coef_).ravel()).astype(float)
        return None

    def _inner_estimator(self) -> Any:
        """取出 Pipeline 的最终估计器（非 Pipeline 直接返回）。"""
        return self._estimator.steps[-1][1] if isinstance(self._estimator, Pipeline) else self._estimator

    def _transform(self, frame: pd.DataFrame) -> np.ndarray:
        """应用 Pipeline 中的预处理步骤（插补 + 标准化）。"""
        if not isinstance(self._estimator, Pipeline):
            return frame.to_numpy(dtype=float)
        values: Any = frame
        for name, step in self._estimator.steps[:-1]:
            values = step.transform(values)
        return np.asarray(values, dtype=float)

    def summary(self) -> dict[str, Any]:
        """返回学习器摘要（写入模型注册表）。"""
        return {
            "kind": self.kind,
            "seed": self.seed,
            "n_features": len(self.feature_names_),
            "params": dict(self.params),
            "constant_model": self._constant is not None,
            "has_xgboost": HAS_XGBOOST,
        }
