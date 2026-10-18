"""模型层（L2 融合预测器 / 共享风险信号）。

对外接口：

.. code-block:: python

    from cbr.models import SignalEngine, build_signal_engine, FusionModel, BaselineModel
    engine = build_signal_engine(bundle)          # bundle 来自 cbr.features
    signal = engine.predict("2024-08-05")         # schemas.RiskSignal
    ablation = engine.modality_ablation()         # P1 数值-only vs 数值+文本
    engine.save_artifacts()                       # 写入 artifacts/models/ + 注册表
"""

from __future__ import annotations

from cbr.models.fusion import BaselineModel, FusionModel
from cbr.models.learners import HAS_XGBOOST, LEARNER_KINDS, Learner
from cbr.models.metrics import (
    classification_metrics,
    expected_calibration_error,
    recall_at_top_fraction,
    summarize_by_horizon,
)
from cbr.models.registry import DEFAULT_ARTIFACT_DIR, ModelEntry, ModelRegistry
from cbr.models.signal import (
    SIGNAL_COLUMNS,
    SignalEngine,
    SnapshotModel,
    build_signal_engine,
    build_signal_engine_from_settings,
)

__all__ = [
    "DEFAULT_ARTIFACT_DIR",
    "HAS_XGBOOST",
    "LEARNER_KINDS",
    "SIGNAL_COLUMNS",
    "BaselineModel",
    "FusionModel",
    "Learner",
    "ModelEntry",
    "ModelRegistry",
    "SignalEngine",
    "SnapshotModel",
    "build_signal_engine",
    "build_signal_engine_from_settings",
    "classification_metrics",
    "expected_calibration_error",
    "recall_at_top_fraction",
    "summarize_by_horizon",
]
