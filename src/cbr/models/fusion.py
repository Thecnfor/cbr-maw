"""多模态融合预测器：数值 + 文本（早期/晚期融合），含模态贡献归因。

- **基线**（``BaselineModel``）：仅数值特征（LASSO / Logit / XGBoost），对应论文 P1
  的“传统金融预测基线”；
- **融合模型**（``FusionModel``）：数值特征 + 文本特征。
  - ``early``：拼接全部特征后训练单一模型（默认，简单稳健）；
  - ``late``：数值/文本分别训练，按固定权重（0.7 / 0.3）加权平均概率；
- **模态贡献**：由单样本特征归因按模态汇总（``|贡献|`` 归一化），
  写入 ``RiskSignal.modality_contrib``，并支持模态消融（仅数值 vs 数值+文本）。

模型只消费 ``FeatureBundle`` 中已对齐的特征；训练/预测的时点由 ``SignalEngine``
负责（滚动快照 + 训练标签截止），本模块不直接访问原始数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cbr.models.learners import Learner


@dataclass
class FusionModel:
    """数值 + 文本多模态融合二分类模型。

    Args:
        numeric_cols: 数值特征列。
        text_cols: 文本特征列。
        learner_kind: 底层学习器（xgboost / logit / lasso / hist）。
        text_enabled: 是否启用文本模态（False 等价于数值-only 基线）。
        fusion: ``early``（早期拼接）或 ``late``（晚期概率平均）。
        seed: 随机种子。
        params: 学习器参数。
        horizon: 预测期限（仅记录在模型中，便于注册表/评估）。
    """

    numeric_cols: list[str]
    text_cols: list[str] = field(default_factory=list)
    learner_kind: str = "xgboost"
    text_enabled: bool = True
    fusion: str = "early"
    seed: int = 42
    params: dict[str, Any] = field(default_factory=dict)
    horizon: int = 5
    numeric_model: Learner | None = field(default=None, init=False, repr=False)
    text_model: Learner | None = field(default=None, init=False, repr=False)
    fused_model: Learner | None = field(default=None, init=False, repr=False)
    numeric_weight: float = field(default=0.7, init=False)
    feature_names_: list[str] = field(default_factory=list, init=False)

    # ------------------------------------------------------------------ #
    # 训练 / 预测
    # ------------------------------------------------------------------ #
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "FusionModel":
        """拟合模型。

        Args:
            X: 特征宽表（至少包含 ``numeric_cols`` 与（启用时）``text_cols``）。
            y: 0/1 标签（含 NaN 的行自动剔除）。

        Returns:
            self。
        """
        target = pd.Series(y).astype(float)
        valid = target.notna()
        X = X.loc[valid]
        y_clean = target[valid].astype(int)
        numeric = [col for col in self.numeric_cols if col in X.columns]
        text = [col for col in self.text_cols if col in X.columns] if self.text_enabled else []
        self.numeric_cols = numeric
        self.text_cols = text
        self.feature_names_ = numeric + text
        if self.fusion == "late" and text:
            self.numeric_model = Learner(kind=self.learner_kind, seed=self.seed, params=dict(self.params)).fit(
                X.loc[:, numeric], y_clean, feature_names=numeric
            )
            self.text_model = Learner(kind=self.learner_kind, seed=self.seed + 1, params=dict(self.params)).fit(
                X.loc[:, text], y_clean, feature_names=text
            )
            self.numeric_weight = 0.7
            return self
        self.fused_model = Learner(kind=self.learner_kind, seed=self.seed, params=dict(self.params)).fit(
            X.loc[:, self.feature_names_], y_clean, feature_names=self.feature_names_
        )
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """返回正类（未来高压力）概率。"""
        if self.fusion == "late" and self.numeric_model is not None and self.text_model is not None:
            numeric_prob = self.numeric_model.predict_proba(X.loc[:, self.numeric_cols]) if self.numeric_cols else 0.5
            text_prob = self.text_model.predict_proba(X.loc[:, self.text_cols]) if self.text_cols else 0.5
            numeric_arr = np.asarray(numeric_prob, dtype=float)
            text_arr = np.asarray(text_prob, dtype=float)
            if self.numeric_cols and not self.text_cols:
                return numeric_arr
            if self.text_cols and not self.numeric_cols:
                return text_arr
            return self.numeric_weight * numeric_arr + (1.0 - self.numeric_weight) * text_arr
        if self.fused_model is None:
            return np.full(X.shape[0], 0.5, dtype=float)
        return self.fused_model.predict_proba(X)

    def predict_one(self, x: pd.Series) -> float:
        """单样本概率（便捷接口）。"""
        return float(self.predict_proba(pd.DataFrame([x.reindex(self.feature_names_)]))[0])

    # ------------------------------------------------------------------ #
    # 归因
    # ------------------------------------------------------------------ #
    def feature_contributions(self, x: pd.Series) -> dict[str, float]:
        """单样本特征贡献 ``{feature: signed_contribution}``（正值推高风险）。"""
        contributions: dict[str, float] = {}
        if self.fusion == "late" and self.numeric_model is not None and self.text_model is not None:
            if self.numeric_cols:
                num = self.numeric_model.feature_contributions(x)
                for name, value in zip(self.numeric_cols, num):
                    contributions[name] = float(value) * self.numeric_weight
            if self.text_cols:
                text = self.text_model.feature_contributions(x)
                for name, value in zip(self.text_cols, text):
                    contributions[name] = float(value) * (1.0 - self.numeric_weight)
            return contributions
        if self.fused_model is None:
            return {name: 0.0 for name in self.feature_names_}
        values = self.fused_model.feature_contributions(x)
        for name, value in zip(self.feature_names_, values):
            contributions[name] = float(value)
        return contributions

    def modality_contributions(self, x: pd.Series) -> dict[str, float]:
        """按模态汇总的单样本贡献（``|贡献|`` 归一化，和为 1）。"""
        contributions = self.feature_contributions(x)
        numeric = sum(abs(value) for name, value in contributions.items() if name in self.numeric_cols)
        text = sum(abs(value) for name, value in contributions.items() if name in self.text_cols)
        total = numeric + text
        if total <= 1e-12:
            return {"numeric": 1.0, "text": 0.0} if not self.text_cols else {"numeric": 0.5, "text": 0.5}
        return {
            "numeric": float(numeric / total),
            "text": float(text / total),
        }

    def feature_importances(self) -> dict[str, float]:
        """全局特征重要性 ``{feature: importance}``（归一化到和为 1）。"""
        if self.fusion == "late" and self.numeric_model is not None and self.text_model is not None:
            importances: dict[str, float] = {}
            num = self.numeric_model.feature_importances()
            if num is not None:
                importances.update({name: float(v) for name, v in zip(self.numeric_cols, num)})
            text = self.text_model.feature_importances()
            if text is not None:
                importances.update({name: float(v) for name, v in zip(self.text_cols, text)})
            total = sum(abs(v) for v in importances.values())
            return {k: abs(v) / total for k, v in importances.items()} if total > 0 else importances
        if self.fused_model is None:
            return {}
        importances_arr = self.fused_model.feature_importances()
        if importances_arr is None:
            return {}
        total = float(np.sum(np.abs(importances_arr)))
        if total <= 1e-12:
            return {name: 0.0 for name in self.feature_names_}
        return {
            name: float(abs(value) / total)
            for name, value in zip(self.feature_names_, importances_arr)
        }

    # ------------------------------------------------------------------ #
    # 摘要
    # ------------------------------------------------------------------ #
    @property
    def features_used(self) -> list[str]:
        """模型实际使用的特征列。"""
        return list(self.feature_names_)

    def summary(self) -> dict[str, Any]:
        """模型摘要（写入模型注册表）。"""
        return {
            "learner_kind": self.learner_kind,
            "text_enabled": self.text_enabled,
            "fusion": self.fusion,
            "horizon": self.horizon,
            "n_numeric": len(self.numeric_cols),
            "n_text": len(self.text_cols),
            "features": list(self.feature_names_),
            "seed": self.seed,
        }


@dataclass
class BaselineModel:
    """仅数值特征的传统预测基线（P1 对照）。

    Args:
        numeric_cols: 数值特征列。
        learner_kind: ``xgboost`` / ``logit`` / ``lasso`` / ``hist``。
        seed: 随机种子。
        params: 学习器参数。
        horizon: 预测期限。
    """

    numeric_cols: list[str]
    learner_kind: str = "xgboost"
    seed: int = 42
    params: dict[str, Any] = field(default_factory=dict)
    horizon: int = 5
    _model: FusionModel = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._model = FusionModel(
            numeric_cols=list(self.numeric_cols),
            text_cols=[],
            learner_kind=self.learner_kind,
            text_enabled=False,
            fusion="early",
            seed=self.seed,
            params=dict(self.params),
            horizon=self.horizon,
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaselineModel":
        """拟合数值-only 基线模型。"""
        self._model.fit(X, y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """返回正类概率。"""
        return self._model.predict_proba(X)

    def predict_one(self, x: pd.Series) -> float:
        """单样本概率。"""
        return self._model.predict_one(x)

    def feature_contributions(self, x: pd.Series) -> dict[str, float]:
        """单样本特征贡献。"""
        return self._model.feature_contributions(x)

    def modality_contributions(self, x: pd.Series) -> dict[str, float]:
        """模态贡献（基线恒为 numeric=1, text=0）。"""
        return {"numeric": 1.0, "text": 0.0}

    def feature_importances(self) -> dict[str, float]:
        """全局特征重要性。"""
        return self._model.feature_importances()

    def summary(self) -> dict[str, Any]:
        """模型摘要。"""
        summary = self._model.summary()
        summary["baseline"] = True
        return summary
