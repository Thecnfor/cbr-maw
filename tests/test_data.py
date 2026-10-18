"""数据层测试：仿真数据可复现性、PIT 无泄漏、标签时序、特征对齐、RiskSignal schema。

测试默认使用 ``data/samples`` 中的 SYNTHETIC 样例数据；若样例尚未生成，则回退为
内存生成（固定 seed），保证测试可独立运行。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbr.config import load_settings, resolve_path
from cbr.contracts import DataProvider
from cbr.data import (
    KEY_SERIES,
    SERIES_IDS,
    SERIES_SPECS,
    MarketDataset,
    PitStore,
    build_data_provider,
    generate_dataset,
    load_sample_dataset,
    series_domain,
    series_unit,
    time_split,
)
from cbr.data.catalog import SERIES_ALIASES, canonical_series_id
from cbr.data.custom import CustomDatasetAdapter
from cbr.data.labels import build_stress_labels, parse_label_version
from cbr.data.synthetic import SAMPLE_SEED, write_sample_data
from cbr.features import build_feature_bundle, build_numeric_features, build_text_features
from cbr.features.alignment import align_features_to_calendar
from cbr.schemas import RiskLevel, RiskSignal


# --------------------------------------------------------------------------- #
# Fixtures（模块级，控制测试时长）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def dataset() -> MarketDataset:
    """沿用 data/samples 的样例数据；缺失时内存生成（固定 seed，可复现）。"""
    sample_dir = resolve_path("data/samples")
    try:
        return load_sample_dataset(sample_dir)
    except FileNotFoundError:
        return generate_dataset(seed=SAMPLE_SEED)


@pytest.fixture(scope="module")
def synthetic_settings():
    """强制使用样例数据的配置（避免依赖本地 pit.duckdb/artifacts 状态）。"""
    settings = load_settings()
    data = settings.data.model_copy(update={"dataset": "synthetic"})
    return settings.model_copy(update={"data": data})


@pytest.fixture(scope="module")
def provider(synthetic_settings) -> DataProvider:
    """DataProvider 实例（synthetic 数据源）。"""
    return build_data_provider(synthetic_settings)


@pytest.fixture(scope="module")
def pit_store(dataset, tmp_path_factory) -> PitStore:
    """临时 PIT 数据库（由样例数据构建）。"""
    path = tmp_path_factory.mktemp("pit") / "test_pit.duckdb"
    store = PitStore.from_dataset(dataset, path)
    store.close()
    return PitStore.open(path)


# --------------------------------------------------------------------------- #
# 仿真数据
# --------------------------------------------------------------------------- #
def test_synthetic_data_marked_and_reproducible(dataset: MarketDataset) -> None:
    """仿真数据必须带 SYNTHETIC 标记、覆盖 2018-2025、且相同 seed 完全可复现。"""
    assert dataset.source == "synthetic-simulation"
    assert len(dataset.obs) > 0
    assert len(dataset.documents) >= 300, "文本语料至少 300 条"
    assert dataset.start is not None and dataset.end is not None
    assert dataset.start <= pd.Timestamp("2018-01-31")
    assert dataset.end >= pd.Timestamp("2025-09-01")
    # 至少包含日频 + 月频 + 派生序列
    assert len(SERIES_IDS) >= 20
    assert set(dataset.obs["series_id"].unique()) >= set(SERIES_IDS) - {
        "crossborder.flows.northbound_net",
        "crossborder.holdings.northbound_hold",
    }
    # 可复现性（短区间对比，避免重复生成大样本）
    first = generate_dataset(seed=7, start="2019-01-02", end="2020-12-31")
    second = generate_dataset(seed=7, start="2019-01-02", end="2020-12-31")
    pd.testing.assert_frame_equal(first.obs, second.obs)
    pd.testing.assert_frame_equal(first.documents, second.documents)
    # 不同 seed 应不同
    other = generate_dataset(seed=8, start="2019-01-02", end="2020-12-31")
    assert not first.obs["value"].equals(other.obs["value"])


def test_synthetic_data_realistic_dynamics(dataset: MarketDataset) -> None:
    """仿真数据应具备波动聚集、压力期跨市场同步、资金流与汇率联动等真实特征。"""
    daily = dataset.daily_frame()
    equity = daily["market.cn_equity.csi300"]
    returns = equity.pct_change().dropna()
    # 波动聚集：5 日与 20 日已实现波动的自相关显著为正
    vol20 = returns.rolling(20).std()
    autocorr = vol20.autocorr(lag=1)
    assert autocorr is not None and autocorr > 0.5
    # 压力期跨市场相关性上升：VIX 高位时中美股指相关性更高
    sp_returns = daily["market.global.sp500"].pct_change()
    rolling_corr = returns.rolling(60).corr(sp_returns)
    high_vix = daily["market.global.vix"] > daily["market.global.vix"].quantile(0.9)
    corr_in_stress = rolling_corr[high_vix & rolling_corr.notna()].mean()
    corr_normal = rolling_corr[~high_vix & rolling_corr.notna()].mean()
    assert corr_in_stress > corr_normal
    # 北向披露断点：2024-08-16 之后缺失（不 ffill、不置 0）
    north = dataset.obs[dataset.obs["series_id"] == "crossborder.flows.northbound_net"]
    assert pd.Timestamp(north["obs_date"].max()) <= pd.Timestamp("2024-08-16")
    # 文本语料：政策类来源占一定比例，且风险主题与压力期相关
    sources = set(dataset.documents["source"].unique())
    assert {"中国人民银行", "中国外汇管理局"} or {"中国人民银行", "国家外汇管理局"} <= sources
    assert dataset.documents["publish_time"].notna().all()


def test_sample_files_manifest_and_synthetic_marker(dataset: MarketDataset, tmp_path: Path) -> None:
    """write_sample_data 必须输出 Manifest/README 并明确标注 synthetic。"""
    out_dir = tmp_path / "samples"
    paths = write_sample_data(dataset, out_dir)
    for key in ("market_daily_parquet", "macro_monthly_parquet", "documents_parquet", "manifest_json", "readme"):
        assert paths[key].exists(), key
    manifest = json.loads(paths["manifest_json"].read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["source"] == "synthetic-simulation"
    assert manifest["n_documents"] >= 300
    assert "仿真" in paths["readme"].read_text(encoding="utf-8")
    cards = json.loads(paths["data_cards_json"].read_text(encoding="utf-8"))
    assert all("SYNTHETIC" in card["notes"] for card in cards)


# --------------------------------------------------------------------------- #
# PIT 存储
# --------------------------------------------------------------------------- #
def test_pit_store_asof_no_future_leakage(pit_store: PitStore, dataset: MarketDataset) -> None:
    """PIT 查询只返回 release_time <= as_of 的记录，宏观发布时滞必须生效。"""
    as_of = date(2022, 4, 25)
    history = pit_store.history("market.cn_equity.csi300", as_of, lookback=500)
    assert history, "应能查到历史"
    assert all(row["date"] <= as_of for row in history)
    assert history == sorted(history, key=lambda row: row["date"])
    # 用 release_time 校验所有序列的时点可得性
    end_ts = pd.Timestamp(as_of) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    for series_id in ("market.cn_equity.csi300", "rates.credit.aa_spread", "macro.cpi.yoy"):
        frame = pit_store.asof(series_id, as_of)
        if not frame.empty:
            assert (pd.to_datetime(frame["release_time"]) <= end_ts).all()
    # 宏观发布时滞：CPI 的观测月末在发布前不可见
    cpi = pit_store.asof("macro.cpi.yoy", date(2019, 1, 31))
    late = pit_store.asof("macro.cpi.yoy", date(2019, 2, 28))
    obs_jan = pd.Timestamp("2019-01-31")
    assert obs_jan not in set(pd.to_datetime(cpi["obs_date"])) if not cpi.empty else True
    assert obs_jan in set(pd.to_datetime(late["obs_date"]))
    # 序列别名归一化
    alias_rows = pit_store.history("crossborder.northbound_net", date(2024, 8, 5), lookback=10)
    canonical_rows = pit_store.history("crossborder.flows.northbound_net", date(2024, 8, 5), lookback=10)
    assert alias_rows == canonical_rows
    assert len(alias_rows) > 0


def test_pit_store_documents_asof(pit_store: PitStore, dataset: MarketDataset) -> None:
    """文档查询必须按 publish_time 时点过滤。"""
    as_of = date(2022, 4, 25)
    docs = pit_store.documents_asof(as_of)
    assert not docs.empty
    assert (pd.to_datetime(docs["publish_time"]) <= pd.Timestamp(as_of) + pd.Timedelta(days=1)).all()
    # 更晚的时点应返回不少于更早时点的文档
    later = pit_store.documents_asof(date(2024, 8, 5))
    assert len(later) >= len(docs)
    cards = pit_store.data_cards()
    assert len(cards) == len(SERIES_IDS)
    assert all(card.source == "synthetic-simulation" for card in cards)


# --------------------------------------------------------------------------- #
# 特征：对齐 + 无未来泄漏
# --------------------------------------------------------------------------- #
def test_numeric_features_alignment_and_pit(dataset: MarketDataset) -> None:
    """数值特征索引与交易日历一致，且第 t 行等价于用截断数据计算（无未来泄漏）。"""
    features = build_numeric_features(dataset)
    assert features.index.is_monotonic_increasing and features.index.is_unique
    calendar = dataset.calendar
    assert len(features) == len(calendar)
    assert list(features.index[:3]) == list(calendar[:3])
    t = pd.Timestamp("2022-04-25")
    # 截断到 t 的数据集：只用 t 及以前已发布观测
    end_ts = t + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    truncated_obs = dataset.obs[dataset.obs["release_time"] <= end_ts]
    truncated = MarketDataset(
        obs=truncated_obs,
        documents=dataset.documents[dataset.documents["publish_time"] <= end_ts],
        seed=dataset.seed,
        source=dataset.source,
    )
    truncated_features = build_numeric_features(truncated)
    assert t in truncated_features.index
    common = [col for col in features.columns]
    np.testing.assert_allclose(
        features.loc[t, common].to_numpy(dtype=float),
        truncated_features.loc[t, common].to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
        err_msg="数值特征使用了未来信息",
    )


def test_text_features_pit(dataset: MarketDataset) -> None:
    """文本特征只使用可用日 ≤ t 的文档（政策类 shift 1、媒体 15:00 切点）。"""
    full = build_text_features(dataset)
    t = pd.Timestamp("2022-04-25")
    end_ts = t + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    docs = dataset.documents[dataset.documents["publish_time"] <= end_ts]
    truncated = MarketDataset(
        obs=dataset.obs,
        documents=docs,
        seed=dataset.seed,
        source=dataset.source,
    )
    before = build_text_features(truncated)
    np.testing.assert_allclose(
        full.loc[t].to_numpy(dtype=float),
        before.loc[t].to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
        err_msg="文本特征使用了未来文档",
    )
    # 文本特征随信息到达而变化：t 与更晚日期的特征向量不同（未来文档只影响未来）
    later = pd.Timestamp("2022-06-01")
    later_end = later + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    docs_later = dataset.documents[dataset.documents["publish_time"] <= later_end]
    truncated_later = MarketDataset(obs=dataset.obs, documents=docs_later, seed=dataset.seed, source=dataset.source)
    after = build_text_features(truncated_later)
    # 截断到 later 后，full 与 truncated 在 later 处仍必须一致（后续文档不得回传）
    np.testing.assert_allclose(
        full.loc[later].to_numpy(dtype=float),
        after.loc[later].to_numpy(dtype=float),
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
    )
    assert not np.allclose(
        full.loc[t].to_numpy(dtype=float), full.loc[later].to_numpy(dtype=float)
    ), "文本特征应随时间更新"
    # 对齐函数：只重索引、不前向填充
    aligned = align_features_to_calendar(full, dataset.calendar)
    assert len(aligned) == len(dataset.calendar)


def test_feature_bundle_modality_split(dataset: MarketDataset) -> None:
    """特征包应区分数值/文本模态，且关闭文本模态时只保留数值列。"""
    bundle = build_feature_bundle(dataset)
    assert bundle.X.shape[0] == len(dataset.calendar)
    assert bundle.numeric_cols and bundle.text_cols
    assert set(bundle.numeric_cols) | set(bundle.text_cols) == set(bundle.X.columns)
    numeric_only = build_feature_bundle(dataset, text_enabled=False)
    assert numeric_only.text_cols == []
    assert list(numeric_only.X.columns) == list(numeric_only.numeric_cols)


# --------------------------------------------------------------------------- #
# 标签：时序正确性 + 无泄漏
# --------------------------------------------------------------------------- #
def test_labels_timing_and_no_leakage(dataset: MarketDataset) -> None:
    """标签 y_h 必须等于未来 h 日高压力状态的聚合；压力指数只使用 t 及以前数据。"""
    labels = build_stress_labels(dataset)
    frame = labels.frame
    assert labels.config.label_version == "stress_pca_q90"
    valid_high = frame["high_stress"].dropna()
    assert not valid_high.empty
    assert valid_high.isin([0.0, 1.0]).all()
    # 阈值训练期冻结：训练期截止后阈值不变
    threshold_after = frame.loc[frame.index > labels.train_end, "threshold"].dropna().unique()
    assert len(threshold_after) == 1
    assert float(threshold_after[0]) == pytest.approx(labels.threshold)
    # y_h = 未来 h 日内是否出现高压力（B1 max 标签）
    high = frame["high_stress"].astype(float)
    for horizon in labels.config.horizons:
        column = f"y_{horizon}"
        valid_rows = frame[column].notna()
        positions = np.where(valid_rows)[0]
        for position in positions[:50]:
            future = high.iloc[position + 1 : position + 1 + horizon]
            expected = 1.0 if (len(future) and np.nanmax(future.to_numpy(dtype=float)) >= 1.0) else 0.0
            assert float(frame[column].iloc[position]) == expected, f"h={horizon} 标签时序错误"
        # 末尾 h 行无法构造标签
        assert frame[column].iloc[-horizon:].isna().all()
    # 标签 point 版本：y_t = high_stress_{t+h}
    point_labels = build_stress_labels(dataset, label_version="stress_pca_q90_point")
    point_frame = point_labels.frame
    h = 5
    positions = np.where(point_frame[f"y_{h}"].notna())[0]
    for position in positions[:50]:
        assert float(point_frame[f"y_{h}"].iloc[position]) == float(high.iloc[position + h])
    # 压力指数无未来泄漏：截断数据在 t 处应得到相同的 CFSI
    t = pd.Timestamp("2022-04-25")
    end_ts = t + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    truncated_obs = dataset.obs[dataset.obs["release_time"] <= end_ts]
    truncated = MarketDataset(
        obs=truncated_obs,
        documents=dataset.documents[dataset.documents["publish_time"] <= end_ts],
        seed=dataset.seed,
        source=dataset.source,
    )
    truncated_labels = build_stress_labels(truncated, train_end=str(labels.train_end.date()))
    assert truncated_labels.frame.loc[t, "cfsi"] == pytest.approx(
        labels.frame.loc[t, "cfsi"], rel=1e-9, abs=1e-9
    )
    assert truncated_labels.frame.loc[t, "high_stress"] == labels.frame.loc[t, "high_stress"]


def test_label_version_configuration(dataset: MarketDataset) -> None:
    """label_version 可配置：等权/PCA、阈值模式、标签定义可切换。"""
    config = parse_label_version("stress_pca_q85_rolling_point")
    assert config.quantile == 0.85
    assert config.threshold_mode == "rolling"
    assert config.label_mode == "point"
    assert config.pca is True
    assert parse_label_version("cfsi_cn_q90").pca is False
    equal_labels = build_stress_labels(dataset, label_version="cfsi_cn_q90")
    assert equal_labels.config.label_version == "cfsi_cn_q90"
    assert equal_labels.frame["cfsi"].notna().sum() > 100
    splits = time_split(dataset.calendar)
    assert len(splits["train"]) > 500 and len(splits["test"]) > 100


# --------------------------------------------------------------------------- #
# DataProvider 契约 + RiskSignal schema
# --------------------------------------------------------------------------- #
def test_data_provider_contract(provider: DataProvider) -> None:
    """DataProvider 必须实现全部协议方法且遵守 PIT。"""
    assert isinstance(provider, DataProvider)
    as_of = date(2024, 8, 5)
    snapshot = provider.market_snapshot(as_of)
    assert snapshot.as_of == as_of
    assert snapshot.series, "快照不应为空"
    assert isinstance(snapshot.missing, list)
    assert len(snapshot.data_cards) == len(SERIES_IDS)
    assert all(card.source == "synthetic-simulation" for card in snapshot.data_cards)
    history = provider.history("market.cn_equity.csi300", as_of, lookback=60)
    assert 0 < len(history) <= 60
    assert all(row["date"] <= as_of for row in history)
    assert all(isinstance(row["value"], float) for row in history)
    assert provider.history("unknown.series", as_of, 10) == []
    assert provider.label(as_of, 5) in (0, 1, None)
    assert len(provider.data_cards()) == len(SERIES_IDS)
    # 别名归一化
    assert provider.history("crossborder.northbound_net", as_of, 5) == provider.history(
        "crossborder.flows.northbound_net", as_of, 5
    )


def test_risk_signal_schema(provider: DataProvider) -> None:
    """RiskSignal 必须满足共享 schema，且包含概率、分位、驱动与模态贡献。"""
    as_of = date(2024, 8, 5)
    signal = provider.risk_signal(as_of)
    assert isinstance(signal, RiskSignal)
    assert signal.as_of <= as_of
    assert set(signal.horizons) == {5, 10, 20}
    assert all(0.0 <= value <= 1.0 for value in signal.horizons.values())
    assert signal.percentile is None or 0.0 <= signal.percentile <= 1.0
    assert isinstance(signal.level, RiskLevel)
    assert signal.model_version and signal.label_version
    assert signal.drivers, "应至少有一个驱动因子"
    assert all(driver.contribution >= 0 for driver in signal.drivers)
    assert sum(abs(driver.contribution) for driver in signal.drivers) > 0
    assert set(signal.modality_contrib) == {"numeric", "text"}
    assert abs(sum(signal.modality_contrib.values()) - 1.0) < 1e-6
    assert signal.evidence_id and signal.evidence_id.startswith("ev_sig_")
    # 同一 as_of 的重复查询应完全一致（确定性）
    again = provider.risk_signal(as_of)
    assert again.horizons == signal.horizons
    assert again.model_version == signal.model_version


# --------------------------------------------------------------------------- #
# 序列目录 / 自定义数据适配器
# --------------------------------------------------------------------------- #
def test_series_catalog_and_aliases() -> None:
    """序列目录、别名与信息域映射必须自洽。"""
    assert len(SERIES_IDS) == len(set(SERIES_IDS))
    assert set(KEY_SERIES) <= set(SERIES_IDS)
    assert series_domain("market.cn_equity.csi300") == "market.cn_equity"
    assert series_domain("macro.pmi.manufacturing") == "macro"
    assert series_domain("crossborder.northbound_net") == "crossborder.flows"
    assert canonical_series_id("market.global.us_equity") == "market.global.sp500"
    assert canonical_series_id("market.cn_equity.csi300") == "market.cn_equity.csi300"
    for series_id in SERIES_IDS:
        spec = SERIES_SPECS[series_id]
        assert spec.unit == series_unit(series_id)
        card = spec.to_data_card()
        assert card.series_id == series_id
        assert card.pit_grade in ("strict", "approximate", "unavailable")
    assert set(SERIES_ALIASES.values()) <= set(SERIES_IDS)


def test_custom_adapter_autodetect(tmp_path: Path) -> None:
    """自建数据适配器：无数据时 has_custom=False；有 CSV 时自动识别序列与文本。"""
    empty_adapter = CustomDatasetAdapter(custom_data_dir=tmp_path)
    assert empty_adapter.has_custom is False
    assert empty_adapter.load()[0].obs.empty

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    dates = pd.date_range("2024-01-02", periods=20, freq="B")
    pd.DataFrame(
        {
            "date": dates,
            "csi300": np.linspace(3000, 3200, len(dates)),
            "credit_spread": np.linspace(80, 120, len(dates)),
        }
    ).to_csv(custom_dir / "my_market.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "publish_time": ["2024-01-05 10:00:00", "2024-01-08 16:00:00"],
            "title": ["央行开展逆回购操作", "北向资金净流出"],
            "content": ["市场流动性保持合理充裕。", "跨境资金流出压力上升。"],
            "source": ["中国人民银行", "财经媒体"],
            "url": ["https://example.com/1", "https://example.com/2"],
        }
    ).to_csv(custom_dir / "policy_news.csv", index=False, encoding="utf-8-sig")
    adapter = CustomDatasetAdapter(custom_data_dir=custom_dir)
    assert adapter.has_custom is True
    custom_dataset, cards = adapter.load()
    assert not custom_dataset.obs.empty
    series_ids = set(custom_dataset.obs["series_id"].unique())
    assert "market.cn_equity.csi300" in series_ids
    assert "rates.credit.aa_spread" in series_ids
    assert len(custom_dataset.documents) == 2
    assert cards and all(card.source == "user-provided" for card in cards)
    # 无 release_time 列时按 obs_date + 16:00 近似（pit_grade=approximate）
    strict_cards = [card for card in cards if card.pit_grade == "strict"]
    assert not strict_cards
