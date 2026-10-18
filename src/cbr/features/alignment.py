"""特征统一对齐：把数值特征、文本特征与标签拼装为建模所需的特征包。

``FeatureBundle`` 是模型层的唯一输入：

- ``X``：行=交易日、列=特征（数值 + 文本，列顺序固定）；
- ``numeric_cols`` / ``text_cols``：模态列划分（用于模态消融与贡献归因）；
- ``calendar``：特征与标签共用的交易日历；
- ``text_enabled``：文本模态是否启用（关闭时 ``X`` 只含数值列）。

所有特征在第 t 行只使用 ≤t 的信息（数值滚动统计向后看、文本按可用交易日过滤、
宏观按发布时点对齐），标签则单独由 ``cbr.data.labels`` 构造（标签允许使用未来信息）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cbr.data.dataset import MarketDataset
from cbr.data.labels import LabelResult, build_stress_labels
from cbr.features.catalog import (
    FEATURE_MODALITY,
    NUMERIC_FEATURE_NAMES,
    TEXT_FEATURE_NAMES,
    feature_meta,
)
from cbr.features.numeric import build_numeric_features
from cbr.features.text import build_text_features


@dataclass
class FeatureBundle:
    """建模特征包（数值 + 文本 + 标签）。

    Attributes:
        X: 特征宽表（行=交易日）。
        labels: 标签结果（``LabelResult``）。
        numeric_cols: 数值特征列。
        text_cols: 文本特征列。
        text_enabled: 文本模态是否启用。
        dataset: 特征来源数据集（便于模型记录数据版本）。
        notes: 构造说明/告警。
    """

    X: pd.DataFrame
    labels: LabelResult
    numeric_cols: list[str] = field(default_factory=list)
    text_cols: list[str] = field(default_factory=list)
    text_enabled: bool = True
    dataset: MarketDataset | None = field(default=None, repr=False)
    notes: list[str] = field(default_factory=list)

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.X.index)

    @property
    def columns(self) -> list[str]:
        return list(self.X.columns)

    def target(self, horizon: int) -> pd.Series:
        """返回与 ``X`` 对齐的预测标签 ``y_h``（未来标签，仅用于训练/评估）。"""
        column = f"y_{int(horizon)}"
        if column not in self.labels.frame.columns:
            raise KeyError(f"标签结果缺少列 {column}")
        return self.labels.frame[column].reindex(self.X.index)

    def subset(self, start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None) -> "FeatureBundle":
        """按日期区间裁剪特征与标签（返回新的特征包，用于训练/评估切分）。"""
        mask = pd.Series(True, index=self.X.index)
        if start is not None:
            mask &= self.X.index >= pd.Timestamp(start)
        if end is not None:
            mask &= self.X.index <= pd.Timestamp(end)
        index = self.X.index[mask]
        labels_frame = self.labels.frame.reindex(index)
        labels = LabelResult(
            frame=labels_frame,
            config=self.labels.config,
            train_end=self.labels.train_end,
            threshold=self.labels.threshold,
            loadings=dict(self.labels.loadings),
        )
        return FeatureBundle(
            X=self.X.loc[index],
            labels=labels,
            numeric_cols=list(self.numeric_cols),
            text_cols=list(self.text_cols),
            text_enabled=self.text_enabled,
            dataset=self.dataset,
            notes=list(self.notes),
        )

    def feature_names(self, modality: str | None = None) -> list[str]:
        """返回特征名；``modality`` 为 ``numeric``/``text`` 时只返回该模态列。"""
        if modality == "numeric":
            return list(self.numeric_cols)
        if modality == "text":
            return list(self.text_cols)
        return list(self.X.columns)

    def as_of_row(self, as_of: str | pd.Timestamp) -> pd.Series | None:
        """返回 ``as_of`` 当日特征行（若为非交易日返回 None）。"""
        ts = pd.Timestamp(as_of).normalize()
        if ts not in self.X.index:
            return None
        return self.X.loc[ts]


def build_feature_bundle(
    dataset: MarketDataset,
    label_version: str | None = None,
    text_enabled: bool = True,
    horizons: tuple[int, ...] | None = None,
    labels: LabelResult | None = None,
) -> FeatureBundle:
    """构造统一建模特征包（数值特征 + 可选文本特征 + 标签）。

    Args:
        dataset: 时点数据集。
        label_version: 标签版本（默认由 ``LabelConfig`` 决定）。
        text_enabled: 是否拼接文本模态。
        horizons: 预测期限（默认 {5,10,20}）。
        labels: 可选的已构造标签结果（避免重复计算）。

    Returns:
        ``FeatureBundle``。
    """
    calendar = dataset.calendar
    notes: list[str] = []
    numeric = build_numeric_features(dataset)
    numeric = numeric.reindex(calendar)
    text_frame = build_text_features(dataset, calendar) if text_enabled else pd.DataFrame(index=calendar)
    if text_enabled and text_frame.empty:
        notes.append("文本特征为空（无文档数据），文本列置 0")
        text_frame = pd.DataFrame(0.0, index=calendar, columns=list(TEXT_FEATURE_NAMES))
    numeric_cols = [name for name in NUMERIC_FEATURE_NAMES if name in numeric.columns]
    text_cols = [name for name in TEXT_FEATURE_NAMES if name in text_frame.columns] if text_enabled else []
    X = pd.concat(
        [numeric.loc[:, numeric_cols], text_frame.loc[:, text_cols] if text_cols else pd.DataFrame(index=calendar)],
        axis=1,
    )
    # 防御：特征列必须唯一，索引必须单调
    if not X.index.is_monotonic_increasing:
        X = X.sort_index()
    labels = labels or build_stress_labels(dataset, label_version=label_version, horizons=horizons)
    # 特征元数据自检：允许出现未登记列（打印说明），但已登记列顺序必须稳定
    unknown = [col for col in X.columns if col not in FEATURE_MODALITY]
    if unknown:
        notes.append(f"未登记特征列（按数值模态处理）: {unknown}")
    return FeatureBundle(
        X=X,
        labels=labels,
        numeric_cols=numeric_cols,
        text_cols=text_cols,
        text_enabled=text_enabled,
        dataset=dataset,
        notes=notes,
    )


def align_features_to_calendar(features: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """把特征表精确对齐到目标交易日历（只做重索引，不做前向填充）。

    Args:
        features: 特征宽表。
        calendar: 目标交易日历。

    Returns:
        对齐后的特征表（缺失行为 NaN）。
    """
    return features.reindex(pd.DatetimeIndex(calendar).sort_values())


def missing_summary(features: pd.DataFrame) -> pd.DataFrame:
    """特征缺失率摘要（调试/报告用）。"""
    frame = pd.DataFrame(
        {
            "missing_ratio": features.isna().mean(),
            "n_missing": features.isna().sum(),
            "first_valid": [features[col].first_valid_index() for col in features.columns],
        }
    )
    return frame.sort_values("missing_ratio", ascending=False)


def feature_description(name: str) -> dict[str, Any]:
    """返回特征的中文说明（用于 UI/报告/归因）。"""
    meta = feature_meta(name)
    return {
        "feature": name,
        "name_cn": meta.name_cn,
        "modality": meta.modality,
        "domain": meta.domain,
        "unit": meta.unit,
        "direction": meta.direction,
        "description": meta.description,
    }
