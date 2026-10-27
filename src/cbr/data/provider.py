"""DataProvider 实现与工厂：为工具/智能体/编排层提供 Point-in-Time 数据。

装配优先级（``settings.data.dataset``）：

1. ``custom`` / ``auto``：若 ``data/custom`` 下存在可识别的用户数据（CSV/Parquet +
   ``configs/data_mapping.yaml`` 映射），以用户数据为主、缺失序列回退 synthetic；
2. ``auto`` / ``public``：若 ``data/pit.duckdb`` 存在，使用 DuckDB PIT 存储
   （``history/market_snapshot/data_cards`` 直接查库，特征/标签由库内数据重建）；
3. 若 ``data/samples`` 存在，加载确定性仿真样例数据（SYNTHETIC）；
4. 全部缺失时，用固定 seed 在内存中生成 synthetic 数据（保证系统永远可启动）。

所有读取都经过 ``as_of`` 时点过滤；``risk_signal(as_of)`` 返回 ``schemas.RiskSignal``，
``history/snapshot/label/data_cards`` 满足 ``contracts.DataProvider`` 协议。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cbr.config import AppSettings, load_settings, resolve_path
from cbr.data.catalog import KEY_SNAPSHOT_SERIES, SERIES_IDS, canonical_series_id
from cbr.data.custom import CustomDatasetAdapter
from cbr.data.dataset import MarketDataset
from cbr.data.labels import LabelResult, build_stress_labels
from cbr.data.pit_store import PitStore
from cbr.data.synthetic import SAMPLE_SEED, generate_dataset, load_sample_dataset
from cbr.features.alignment import FeatureBundle, build_feature_bundle
from cbr.models.signal import SignalEngine
from cbr.schemas import DataCard, MarketSnapshot, RiskSignal

logger = logging.getLogger(__name__)


def _as_date(value: date | datetime | str | pd.Timestamp) -> date:
    """把输入规范化为 ``datetime.date``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _merge_datasets(primary: MarketDataset, fallback: MarketDataset) -> MarketDataset:
    """合并用户数据与仿真回退数据：用户序列优先，缺失序列由 fallback 补齐。"""
    obs = pd.concat([primary.obs, fallback.obs], ignore_index=True)
    obs = obs.drop_duplicates(subset=["series_id", "obs_date"], keep="first")
    documents = primary.documents if len(primary.documents) else fallback.documents
    source = primary.source if len(primary.obs) else fallback.source
    return MarketDataset(
        obs=obs,
        documents=documents,
        seed=fallback.seed,
        source=source,
        meta={"merged": True, "primary": primary.meta, "fallback": fallback.meta},
    )


def _build_merged_cards(dataset: MarketDataset, fallback_cards: dict[str, DataCard]) -> list[DataCard]:
    """构造合并数据集的数据卡：以实际覆盖期为准，缺失序列标注 synthetic 回退。"""
    coverage = dataset.coverage()
    cards: list[DataCard] = []
    for series_id in SERIES_IDS:
        start, end = coverage.get(series_id, (None, None))
        if series_id in fallback_cards and start is None:
            card = fallback_cards[series_id].model_copy(
                update={"notes": f"{fallback_cards[series_id].notes}；该序列由 SYNTHETIC 仿真数据回退"}
            )
            cards.append(card)
            continue
        base = fallback_cards.get(series_id)
        notes = base.notes if base is not None else ""
        if base is not None and base.source != dataset.source and "synthetic" not in notes.lower():
            notes = f"{notes}；该序列由 SYNTHETIC 仿真数据回退"
        cards.append(
            DataCard(
                series_id=series_id,
                name=base.name if base is not None else series_id,
                source=dataset.source,
                frequency=base.frequency if base is not None else "daily",
                coverage_start=start,
                coverage_end=end,
                release_lag_days=base.release_lag_days if base is not None else 0,
                pit_grade="approximate" if dataset.source != "synthetic-simulation" else "strict",
                unit=base.unit if base is not None else None,
                notes=notes,
            )
        )
    return cards


class MarketDataProvider:
    """基于内存 ``MarketDataset`` 的 DataProvider 实现。

    数据加载后全部留在内存（约数万行，毫秒级）；特征/标签/信号引擎按需惰性构建，
    避免 API/UI 启动时为未使用的能力付出成本。

    Args:
        dataset: 时点数据集。
        settings: 应用配置。
        source_label: 数据源标签（写入日志/健康检查）。
    """

    def __init__(
        self,
        dataset: MarketDataset,
        settings: AppSettings | None = None,
        source_label: str = "synthetic",
    ) -> None:
        self.dataset = dataset
        self.settings = settings or load_settings()
        self.source_label = source_label
        self._labels: LabelResult | None = None
        self._bundle: FeatureBundle | None = None
        self._engine: SignalEngine | None = None
        self._cards: list[DataCard] | None = None

    # ------------------------------------------------------------------ #
    # 惰性组件
    # ------------------------------------------------------------------ #
    def _get_labels(self) -> LabelResult:
        """构造/缓存风险标签（标签构造只使用向后滚动统计）。"""
        if self._labels is None:
            self._labels = build_stress_labels(self.dataset, label_version=self.settings.data.label_version)
        return self._labels

    def _get_bundle(self) -> FeatureBundle:
        """构造/缓存特征包（数值 + 可选文本 + 标签）。"""
        if self._bundle is None:
            self._bundle = build_feature_bundle(
                self.dataset,
                label_version=self.settings.data.label_version,
                text_enabled=bool(self.settings.signal.text_enabled),
                labels=self._get_labels(),
            )
        return self._bundle

    def _artifact_dir(self) -> Path:
        return resolve_path(Path(self.settings.paths.artifacts) / "models")

    def _get_engine(self) -> SignalEngine:
        """构造/缓存信号引擎；优先加载预计算信号（演示快速路径）。"""
        if self._engine is None:
            engine = SignalEngine(
                bundle=self._get_bundle(),
                settings=self.settings.signal,
                seed=42,
                artifact_dir=self._artifact_dir(),
            )
            try:
                engine.load_precomputed()
            except (OSError, ValueError, KeyError) as exc:  # pragma: no cover
                logger.warning("加载预计算信号失败，将按需训练快照模型: %s", exc)
            self._engine = engine
        return self._engine

    # ------------------------------------------------------------------ #
    # DataProvider 协议
    # ------------------------------------------------------------------ #
    def risk_signal(self, as_of: date | datetime | str | pd.Timestamp) -> RiskSignal:
        """返回 ``as_of`` 当日可得的共享多模态风险信号（P1 产物）。"""
        return self._get_engine().predict(as_of)

    def market_snapshot(self, as_of: date | datetime | str | pd.Timestamp) -> MarketSnapshot:
        """返回 ``as_of`` 当日的关键行情/资金快照。"""
        day = _as_date(as_of)
        values, missing = self.dataset.snapshot_values(day)
        return MarketSnapshot(
            as_of=day,
            series=values,
            missing=missing,
            data_cards=self.data_cards(),
        )

    def history(
        self,
        series_id: str,
        as_of: date | datetime | str | pd.Timestamp,
        lookback: int = 120,
    ) -> list[dict[str, Any]]:
        """返回截至 ``as_of`` 的历史序列 ``[{"date": date, "value": float}, ...]``。"""
        canonical = canonical_series_id(series_id)
        return self.dataset.history(canonical, _as_date(as_of), lookback=lookback)

    def label(self, as_of: date | datetime | str | pd.Timestamp, horizon: int) -> int | None:
        """返回 ``as_of`` 之后 ``horizon`` 个交易日是否高压力（仅评估阶段使用）。"""
        return self._get_labels().label(as_of, horizon)

    def data_cards(self) -> list[DataCard]:
        """返回全部数据卡（数据说明）。"""
        if self._cards is None:
            self._cards = self.dataset.data_cards()
        return list(self._cards)

    # ------------------------------------------------------------------ #
    # 热刷新（实时抓取写回后调用）
    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        """重新加载数据并清空惰性缓存（供实时抓取写回后热刷新）。

        基类实现按当前配置重建 provider 并复制数据集/数据卡；``PitStoreDataProvider``
        会覆盖为「直接从 PIT 库重读」，避免重复装配整个数据栈。
        """
        fresh = build_data_provider(self.settings)
        self.dataset = fresh.dataset
        self.source_label = fresh.source_label
        self._cards = fresh.data_cards()
        self._labels = None
        self._bundle = None
        self._engine = None

    # ------------------------------------------------------------------ #
    # 附加信息（健康检查 / UI）
    # ------------------------------------------------------------------ #
    def _data_snapshot_info(self) -> dict[str, Any]:
        """返回数据快照标识（snapshot id / corpus hash），用于健康检查与实验记录。"""
        info = {
            "dataset_snapshot_id": self.dataset.meta.get("dataset_snapshot_id"),
            "corpus_hash": self.dataset.meta.get("corpus_hash"),
        }
        if info["dataset_snapshot_id"]:
            return info
        manifest_path = resolve_path("data/pit_manifest.json")
        if manifest_path.exists():
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                info["dataset_snapshot_id"] = raw.get("dataset_snapshot_id")
                info["corpus_hash"] = raw.get("corpus_hash")
                info["pit_built_at"] = raw.get("built_at")
            except (OSError, ValueError):  # pragma: no cover
                pass
        return info

    def dataset_info(self) -> dict[str, Any]:
        """返回数据集摘要（API ``/api/health`` 等使用）。"""
        start = self.dataset.start
        end = self.dataset.end
        snapshot = self._data_snapshot_info()
        return {
            "source_label": self.source_label,
            "source": self.dataset.source,
            "synthetic": self.dataset.source == "synthetic-simulation",
            "seed": self.dataset.seed,
            "dataset_snapshot_id": snapshot.get("dataset_snapshot_id"),
            "corpus_hash": snapshot.get("corpus_hash"),
            "n_series": int(self.dataset.obs["series_id"].nunique()) if len(self.dataset.obs) else 0,
            "n_obs": int(len(self.dataset.obs)),
            "n_documents": int(len(self.dataset.documents)),
            "start": str(start.date()) if start is not None else None,
            "end": str(end.date()) if end is not None else None,
            "model_version": self._engine.model_version() if self._engine is not None else None,
        }


class PitStoreDataProvider(MarketDataProvider):
    """基于 DuckDB PIT 存储的 DataProvider：读取接口直接查库，保证时点语义。

    Args:
        store: 已打开的 ``PitStore``（只读）。
        settings: 应用配置。
    """

    def __init__(self, store: PitStore, settings: AppSettings | None = None) -> None:
        self.store = store
        dataset = store.load_market_dataset()
        super().__init__(dataset, settings, source_label="pit-store")

    def market_snapshot(self, as_of: date | datetime | str | pd.Timestamp) -> MarketSnapshot:
        """从 PIT 存储读取 ``as_of`` 当日可得的最新关键序列值。"""
        day = _as_date(as_of)
        values = self.store.asof_values(day, KEY_SNAPSHOT_SERIES)
        missing = [series_id for series_id in KEY_SNAPSHOT_SERIES if series_id not in values]
        return MarketSnapshot(as_of=day, series=values, missing=missing, data_cards=self.data_cards())

    def history(
        self,
        series_id: str,
        as_of: date | datetime | str | pd.Timestamp,
        lookback: int = 120,
    ) -> list[dict[str, Any]]:
        """从 PIT 存储读取历史序列（``release_time <= as_of``）。"""
        canonical = canonical_series_id(series_id)
        return self.store.history(canonical, _as_date(as_of), lookback=lookback)

    def label(self, as_of: date | datetime | str | pd.Timestamp, horizon: int) -> int | None:
        """评估标签（由库内全量数据计算，仅评估阶段使用）。"""
        return self._get_labels().label(as_of, horizon)

    def data_cards(self) -> list[DataCard]:
        """返回 PIT 库中持久化的数据卡。"""
        if self._cards is None:
            self._cards = self.store.data_cards()
        return list(self._cards)

    def detach(self) -> None:
        """释放 PIT 只读连接（数据集仍在内存中可读）。

        实时抓取需要写入同一 DuckDB 文件时先调用本方法释放只读连接，避免同进程
        读写连接冲突；写入完成后由 :meth:`reload` 重新打开只读连接。
        """
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 - 释放失败不影响后续重连
            pass

    def reload(self) -> None:
        """从 PIT 存储重读数据集并清空惰性缓存（实时抓取写回后热刷新）。"""
        self.store.close()
        self.dataset = self.store.load_market_dataset()
        self._cards = None
        self._labels = None
        self._bundle = None
        self._engine = None


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #
def _load_synthetic(settings: AppSettings) -> MarketDataset:
    """加载样例仿真数据；缺失时用固定 seed 在内存生成（系统仍然可用）。"""
    sample_dir = resolve_path(settings.data.sample_dir)
    try:
        return load_sample_dataset(sample_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("样例数据不可用（%s），回退为内存生成的 SYNTHETIC 数据", exc)
        return generate_dataset(seed=SAMPLE_SEED, start=settings.data.sample_start, end=settings.data.sample_end)


def _load_custom(settings: AppSettings) -> tuple[MarketDataset, list[DataCard]] | None:
    """尝试加载用户自建数据；无数据时返回 None。"""
    adapter = CustomDatasetAdapter(
        custom_data_dir=resolve_path(settings.data.custom_data_dir),
    )
    if not adapter.has_custom:
        return None
    dataset, cards = adapter.load()
    if len(dataset.obs) == 0 and len(dataset.documents) == 0:
        logger.warning("检测到自建数据目录但未解析出有效数据: %s", adapter.warnings)
        return None
    logger.info("已加载用户自建数据：%d 条观测、%d 篇文档", len(dataset.obs), len(dataset.documents))
    return dataset, cards


def _pit_is_fresh(pit_path: Path, settings: AppSettings) -> bool:
    """判断 PIT 数据库是否不早于样例数据文件（避免使用过期数据库）。

    ``scripts/build_sample_data.py`` 重新生成样例后，PIT 库需要重新构建；
    若库文件比样例文件旧，则本轮回退到样例数据加载路径，保证数据一致。
    """
    sample_file = resolve_path(settings.data.sample_dir) / "market_daily.parquet"
    try:
        pit_mtime = pit_path.stat().st_mtime
        sample_mtime = sample_file.stat().st_mtime
    except OSError:
        return True
    return pit_mtime >= sample_mtime


def build_data_provider(settings: AppSettings | None = None) -> MarketDataProvider:
    """构造 DataProvider 工厂（按 custom → pit → samples → 内存 synthetic 回退）。

    Args:
        settings: 应用配置（默认 ``load_settings()``）。

    Returns:
        ``MarketDataProvider``（或 ``PitStoreDataProvider`` 子类）。
    """
    settings = settings or load_settings()
    mode = (settings.data.dataset or "auto").strip().lower()

    # 1) 用户自建数据（custom / auto）
    if mode in ("auto", "custom", "public"):
        custom = _load_custom(settings)
        if custom is not None:
            custom_dataset, custom_cards = custom
            if not settings.data.synthetic_fallback:
                logger.info(
                    "使用用户自建数据（仅真实数据，不回退 synthetic）：%s ~ %s",
                    custom_dataset.start,
                    custom_dataset.end,
                )
                return MarketDataProvider(custom_dataset, settings, source_label="custom")
            fallback = _load_synthetic(settings)
            merged = _merge_datasets(custom_dataset, fallback)
            provider = MarketDataProvider(merged, settings, source_label="custom+synthetic")
            fallback_cards = {card.series_id: card for card in fallback.data_cards()}
            provider._cards = _build_merged_cards(merged, fallback_cards)
            return provider

    # 2) PIT 存储（auto / public / pit；pit 显式强制 PIT，用于实时抓取场景）
    if mode in ("auto", "public", "pit"):
        pit_path = resolve_path(settings.data.pit_db)
        if pit_path.exists() and _pit_is_fresh(pit_path, settings):
            try:
                store = PitStore.open(pit_path)
                logger.info("使用 PIT 存储: %s", pit_path)
                return PitStoreDataProvider(store, settings)
            except (FileNotFoundError, ValueError, OSError) as exc:  # pragma: no cover
                logger.warning("打开 PIT 存储失败（%s），回退到样例数据", exc)
        elif pit_path.exists():
            logger.warning("PIT 数据库早于样例数据文件，回退到样例数据加载（请运行 scripts/build_dataset.py）")

    # 3) 样例数据（synthetic）
    if mode != "public":
        dataset = _load_synthetic(settings)
        logger.info(
            "使用 SYNTHETIC 样例数据：seed=%s, %s ~ %s", dataset.seed, dataset.start, dataset.end
        )
        return MarketDataProvider(dataset, settings, source_label="synthetic")

    # 4) public 模式但无真实数据：回退 synthetic
    logger.warning("public 数据源未就绪，自动回退到 SYNTHETIC 仿真数据")
    return MarketDataProvider(_load_synthetic(settings), settings, source_label="synthetic-fallback")
