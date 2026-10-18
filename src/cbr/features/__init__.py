"""多模态特征层（L2）：数值特征 + 文本特征 + 统一时间对齐。

对外接口：

.. code-block:: python

    from cbr.features import build_feature_bundle, NUMERIC_FEATURE_NAMES, TEXT_FEATURE_NAMES
    bundle = build_feature_bundle(dataset)          # 数值 + 文本 + 标签
    bundle = build_feature_bundle(dataset, text_enabled=False)  # 模态消融：仅数值
    bundle.X                                       # 特征宽表（行=交易日）
    bundle.target(5)                               # 未来 5 日高压力标签（训练/评估用）

所有特征均只使用 t 及以前的信息；标签使用未来信息但只用于训练/评估。
"""

from __future__ import annotations

from cbr.features.alignment import (
    FeatureBundle,
    align_features_to_calendar,
    build_feature_bundle,
    feature_description,
    missing_summary,
)
from cbr.features.catalog import (
    FEATURE_MODALITY,
    FEATURE_NAMES,
    FEATURES,
    NUMERIC_FEATURES,
    NUMERIC_FEATURE_NAMES,
    TEXT_FEATURES,
    TEXT_FEATURE_NAMES,
    FeatureMeta,
    feature_meta,
    feature_modality,
    modality_weight,
)
from cbr.features.numeric import build_numeric_features
from cbr.features.text import (
    KEYWORDS,
    effective_trading_day,
    score_documents,
    build_text_features,
)

__all__ = [
    "FEATURE_MODALITY",
    "FEATURE_NAMES",
    "FEATURES",
    "FeatureBundle",
    "FeatureMeta",
    "KEYWORDS",
    "NUMERIC_FEATURES",
    "NUMERIC_FEATURE_NAMES",
    "TEXT_FEATURES",
    "TEXT_FEATURE_NAMES",
    "align_features_to_calendar",
    "build_feature_bundle",
    "build_numeric_features",
    "build_text_features",
    "effective_trading_day",
    "feature_description",
    "feature_meta",
    "feature_modality",
    "missing_summary",
    "modality_weight",
    "score_documents",
]
