"""模型层测试：滚动样本外无泄漏、RiskSignal schema、模态消融、注册表与预计算信号。

测试使用合成样例数据构建轻量模型配置（``roll_window=300``、``retrain_every=120``），
避免完整产物训练耗时；完整产物由 ``scripts/build_dataset.py`` 生成。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbr.config import SignalSettings, load_settings, resolve_path
from cbr.data import MarketDataset, generate_dataset, load_sample_dataset
from cbr.data.synthetic import SAMPLE_SEED
from cbr.features import build_feature_bundle
from cbr.models import (
    SIGNAL_COLUMNS,
    BaselineModel,
    FusionModel,
    ModelEntry,
    ModelRegistry,
    SignalEngine,
)
from cbr.models.metrics import classification_metrics
from cbr.schemas import RiskLevel, RiskSignal


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dataset() -> MarketDataset:
    """样例数据（缺失时内存生成，固定 seed）。"""
    try:
        return load_sample_dataset(resolve_path("data/samples"))
    except FileNotFoundError:
        return generate_dataset(seed=SAMPLE_SEED)


@pytest.fixture(scope="module")
def bundle(dataset):
    """完整特征包（数值 + 文本 + 标签）。"""
    return build_feature_bundle(dataset)


@pytest.fixture(scope="module")
def numeric_bundle(dataset):
    """数值-only 特征包（模态消融用）。"""
    return build_feature_bundle(dataset, text_enabled=False)


@pytest.fixture(scope="module")
def signal_settings() -> SignalSettings:
    """轻量信号配置（测试快、仍保持滚动样本外语义）。"""
    return SignalSettings(
        model_version="test-fusion-v1",
        baseline="xgboost",
        text_enabled=True,
        roll_window=300,
        retrain_every=120,
    )


@pytest.fixture(scope="module")
def engine(bundle, signal_settings, tmp_path_factory) -> SignalEngine:
    """信号引擎（产物目录隔离到临时目录）。"""
    artifact_dir = tmp_path_factory.mktemp("models")
    return SignalEngine(bundle=bundle, settings=signal_settings, seed=42, artifact_dir=artifact_dir)


@pytest.fixture(scope="module")
def eval_dates() -> list[pd.Timestamp]:
    """评估日集合（2024-07 ~ 2024-09 每 10 个交易日）。"""
    return list(pd.bdate_range("2024-07-01", "2024-09-30"))[::10]


# --------------------------------------------------------------------------- #
# 预测接口与 schema
# --------------------------------------------------------------------------- #
def test_risk_signal_schema(engine: SignalEngine) -> None:
    """RiskSignal 输出必须满足共享 schema，且模型版本携带训练快照。"""
    signal = engine.predict(date(2024, 8, 5))
    assert isinstance(signal, RiskSignal)
    assert signal.as_of <= date(2024, 8, 5)
    assert set(signal.horizons) == {5, 10, 20}
    assert all(0.0 <= value <= 1.0 for value in signal.horizons.values())
    assert signal.percentile is not None and 0.0 <= signal.percentile <= 1.0
    assert isinstance(signal.level, RiskLevel)
    assert signal.model_version.startswith("test-fusion-v1")
    assert signal.label_version == engine.bundle.labels.config.label_version
    assert signal.drivers, "应输出驱动因子"
    assert all(0.0 <= driver.contribution <= 1.0 for driver in signal.drivers)
    assert set(signal.modality_contrib) == {"numeric", "text"}
    assert abs(sum(signal.modality_contrib.values()) - 1.0) < 1e-6
    assert signal.evidence_id and signal.evidence_id.startswith("ev_sig_")
    # JSON 可序列化（API/UI 需要）
    payload = json.loads(signal.model_dump_json())
    assert payload["as_of"] and payload["horizons"]


def test_fallback_signal_before_first_snapshot(engine: SignalEngine) -> None:
    """训练快照不可用的早期日期应返回合法回退信号（不崩溃）。"""
    signal = engine.predict(date(2018, 6, 1))
    assert isinstance(signal, RiskSignal)
    assert signal.model_version.endswith("-fallback")
    assert set(signal.horizons) == {5, 10, 20}
    assert signal.modality_contrib == {"numeric": 1.0, "text": 0.0}
    # 压力指数尚不可得时不应伪造驱动因子
    assert signal.percentile is None
    assert signal.drivers == []
    # 压力指数可用但训练快照仍不可用时：回退信号应带维度驱动
    early = engine.predict(date(2019, 3, 1))
    assert early.model_version.endswith("-fallback")
    assert early.percentile is not None
    assert early.drivers, "回退信号应给出压力维度驱动"


# --------------------------------------------------------------------------- #
# 滚动样本外：训练窗口不越界（无未来泄漏）
# --------------------------------------------------------------------------- #
def test_training_windows_no_future_leakage(engine: SignalEngine) -> None:
    """快照 R 的每个期限模型只能使用 t+h<=R 的样本（标签在 R 时点已知）。"""
    as_of_ts = pd.Timestamp("2024-08-05")
    snapshot = engine._get_snapshot(as_of_ts, True)
    assert snapshot is not None and snapshot.models
    calendar = engine.calendar
    snapshot_pos = int(calendar.get_loc(snapshot.snapshot_date))
    assert snapshot.snapshot_date <= as_of_ts
    for horizon, window in snapshot.train_windows.items():
        train_end = pd.Timestamp(window[1])
        train_end_pos = int(calendar.get_loc(train_end))
        assert train_end_pos + int(horizon) <= snapshot_pos + 1, (
            f"h={horizon} 训练使用了对快照时点未来标签: train_end={train_end}, "
            f"snapshot={snapshot.snapshot_date}"
        )
        assert window[2] > 0
    # 特征行无未来信息：as_of 行与截断数据计算的特征一致
    end_ts = as_of_ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    bundle = engine.bundle
    truncated_obs = bundle.dataset.obs[bundle.dataset.obs["release_time"] <= end_ts]
    truncated_docs = bundle.dataset.documents[bundle.dataset.documents["publish_time"] <= end_ts]
    truncated = MarketDataset(
        obs=truncated_obs,
        documents=truncated_docs,
        seed=bundle.dataset.seed,
        source=bundle.dataset.source,
    )
    truncated_bundle = build_feature_bundle(truncated, labels=bundle.labels)
    row_full = bundle.X.loc[as_of_ts]
    row_truncated = truncated_bundle.X.loc[as_of_ts]
    np.testing.assert_allclose(
        row_full.to_numpy(dtype=float),
        row_truncated.to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
        err_msg="模型输入特征包含未来信息",
    )


def test_target_alignment(bundle) -> None:
    """训练目标 y_h 与标签表一致，末尾 h 行不可用（无法构造未来标签）。"""
    labels_frame = bundle.labels.frame
    for horizon in (5, 10, 20):
        target = bundle.target(horizon)
        pd.testing.assert_series_equal(
            target, labels_frame[f"y_{horizon}"].reindex(bundle.X.index), check_names=False
        )
        assert target.iloc[-horizon:].isna().all()
        assert target.dropna().isin([0.0, 1.0]).all()


# --------------------------------------------------------------------------- #
# 基线 vs 融合、模态消融
# --------------------------------------------------------------------------- #
def test_baseline_and_fusion_fit_predict(bundle) -> None:
    """数值-only 基线与多模态融合模型均可拟合/预测，并给出模态归因。"""
    calendar = bundle.X.index
    train_slice = bundle.X.loc[(calendar >= "2020-01-01") & (calendar <= "2022-12-30")]
    y = bundle.target(5).reindex(train_slice.index)
    valid = y.notna()
    X_train = train_slice.loc[valid].iloc[-400:]
    y_train = y.loc[valid].iloc[-400:]
    for kind in ("logit", "lasso", "xgboost"):
        baseline = BaselineModel(numeric_cols=bundle.numeric_cols, learner_kind=kind, seed=42).fit(X_train, y_train)
        fusion = FusionModel(
            numeric_cols=bundle.numeric_cols,
            text_cols=bundle.text_cols,
            learner_kind=kind,
            text_enabled=True,
            seed=42,
        ).fit(X_train, y_train)
        X_test = X_train.iloc[-20:]
        for model in (baseline, fusion):
            proba = model.predict_proba(X_test)
            assert proba.shape == (len(X_test),)
            assert np.all((proba >= 0.0) & (proba <= 1.0)) and np.all(np.isfinite(proba))
        contributions = fusion.feature_contributions(X_train.iloc[-1])
        assert set(contributions) == set(bundle.numeric_cols) | set(bundle.text_cols)
        modality = fusion.modality_contributions(X_train.iloc[-1])
        assert set(modality) == {"numeric", "text"}
        assert abs(sum(modality.values()) - 1.0) < 1e-6
        assert baseline.modality_contributions(X_train.iloc[-1]) == {"numeric": 1.0, "text": 0.0}
        importances = fusion.feature_importances()
        assert importances and abs(sum(importances.values()) - 1.0) < 1e-6


def test_modality_ablation_smoke(engine: SignalEngine, eval_dates) -> None:
    """P1 模态消融 smoke test：数值-only vs 数值+文本，指标结构完整。"""
    result = engine.modality_ablation(dates=eval_dates)
    assert set(result) == {"fusion", "numeric_only", "delta", "summary"}
    for split in ("fusion", "numeric_only"):
        metrics = result[split]
        assert set(metrics) == {5, 10, 20}
        for horizon, item in metrics.items():
            assert item["n"] > 0
            assert 0.0 <= item["pr_auc"] <= 1.0
            assert 0.0 <= item["roc_auc"] <= 1.0
            assert 0.0 <= item["brier"] <= 1.0
    assert set(result["delta"]) == {"5", "10", "20"}
    assert "mean_pr_auc" in result["summary"]["fusion"]
    # 关闭文本模态时模态贡献应为纯数值
    numeric_signal = engine.predict(eval_dates[-1], text_enabled=False)
    assert numeric_signal.modality_contrib == {"numeric": 1.0, "text": 0.0}


def test_numeric_only_engine(numeric_bundle, signal_settings, tmp_path: Path) -> None:
    """数值-only 引擎（文本模态关闭）输出的 modality_contrib 纯数值。"""
    engine = SignalEngine(
        bundle=numeric_bundle,
        settings=signal_settings.model_copy(update={"text_enabled": False}),
        seed=42,
        artifact_dir=tmp_path / "models",
    )
    signal = engine.predict(date(2024, 8, 5))
    assert signal.modality_contrib == {"numeric": 1.0, "text": 0.0}
    assert signal.horizons


# --------------------------------------------------------------------------- #
# 预计算信号（快速路径）与模型注册表
# --------------------------------------------------------------------------- #
def test_precomputed_signal_roundtrip(engine: SignalEngine) -> None:
    """预计算信号表应可回读为等价的 RiskSignal（API/UI 快速路径）。"""
    frame = engine.precompute(start="2024-01-01", end="2024-03-29", include_fallback=True)
    assert set(SIGNAL_COLUMNS) <= set(frame.columns)
    assert len(frame) > 20
    engine.set_precomputed(frame)
    target_day = date(2024, 3, 15)
    signal = engine.predict(target_day)
    row = frame[frame["as_of"] == pd.Timestamp(target_day)].iloc[0]
    assert signal.as_of == target_day
    assert signal.model_version == row["model_version"]
    for horizon in (5, 10, 20):
        assert signal.horizons[horizon] == pytest.approx(float(row[f"p_{horizon}"]))
    assert signal.level.value == row["level"]
    # 非交易日取之前最近交易日的信号
    weekend = engine.predict(date(2024, 3, 16))
    assert weekend.as_of <= date(2024, 3, 16)


def test_model_registry_roundtrip(tmp_path: Path) -> None:
    """模型注册表：保存/读取版本条目与预计算信号文件。"""
    registry = ModelRegistry(tmp_path / "models")
    signals = pd.DataFrame(
        {
            "as_of": pd.to_datetime(["2024-08-05", "2024-08-06"]),
            "p_5": [0.2, 0.3],
            "p_10": [0.3, 0.4],
            "p_20": [0.4, 0.5],
            "percentile": [0.8, 0.9],
            "level": ["high", "critical"],
            "drivers_json": ["[]", "[]"],
            "modality_json": ['{"numeric": 1.0, "text": 0.0}'] * 2,
            "model_version": ["v1", "v1"],
            "label_version": ["stress_pca_q90"] * 2,
            "snapshot_date": pd.to_datetime(["2024-08-01", "2024-08-01"]),
        }
    )
    entry = ModelEntry(
        model_version="fusion-xgb-v1@20240801",
        label_version="stress_pca_q90",
        horizons=[5, 10, 20],
        learner="xgboost",
        features=["ret_csi300_5d", "text_risk_intensity_5d"],
        snapshots=[{"snapshot_date": "2024-08-01", "horizons": [5, 10, 20]}],
        metrics={"5": {"pr_auc": 0.5}, "10": {"pr_auc": 0.4}, "20": {"pr_auc": 0.3}},
        modality_contrib_mean={"numeric": 0.8, "text": 0.2},
    )
    registered = registry.register(entry, signals=signals)
    assert registered["model_version"] == entry.model_version
    loaded = registry.get(entry.model_version)
    assert loaded is not None and loaded["metrics"]["5"]["pr_auc"] == 0.5
    assert registry.latest()["model_version"] == entry.model_version
    signals_path = registry.signals_path(entry.model_version)
    assert signals_path is not None and signals_path.exists()
    roundtrip = pd.read_parquet(signals_path)
    assert len(roundtrip) == len(signals)
    manifest = json.loads((registry.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["models"][0]["model_version"] == entry.model_version


# --------------------------------------------------------------------------- #
# 指标函数
# --------------------------------------------------------------------------- #
def test_classification_metrics_edge_cases() -> None:
    """指标函数在正常/退化输入上都应稳定返回。"""
    y_true = np.array([0, 1, 0, 1, 0, 1, 0, 0])
    y_prob = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.2])
    metrics = classification_metrics(y_true, y_prob)
    assert 0.0 <= metrics["pr_auc"] <= 1.0
    assert 0.0 <= metrics["roc_auc"] <= 1.0
    assert metrics["recall_top10pct"] > 0.3
    assert metrics["n"] == 8 and metrics["n_pos"] == 3
    # 单类输入
    single = classification_metrics(np.zeros(5), np.linspace(0, 1, 5))
    assert single["pr_auc"] == 0.0 and single["n_pos"] == 0
    # 全 NaN 输入
    empty = classification_metrics(np.array([np.nan]), np.array([np.nan]))
    assert empty["n"] == 0


def test_engine_determinism(bundle, signal_settings, tmp_path: Path) -> None:
    """相同配置/种子的两个引擎应给出完全一致的预测（确定性）。"""
    engine_a = SignalEngine(bundle, signal_settings, seed=7, artifact_dir=tmp_path / "a")
    engine_b = SignalEngine(bundle, signal_settings, seed=7, artifact_dir=tmp_path / "b")
    signal_a = engine_a.predict(date(2022, 1, 4))
    signal_b = engine_b.predict(date(2022, 1, 4))
    assert signal_a.horizons == signal_b.horizons
    assert signal_a.level == signal_b.level
    assert signal_a.model_version == signal_b.model_version
    assert [driver.factor for driver in signal_a.drivers] == [driver.factor for driver in signal_b.drivers]
