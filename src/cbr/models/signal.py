"""共享多模态风险信号引擎（P1 核心产物）。

职责：把 ``FeatureBundle``（数值 + 文本特征 + 标签）转换为逐日 ``RiskSignal``：

- **滚动样本外预测**：按 ``signal.retrain_every`` 个交易日设训练快照；快照 R
  对期限 h 的模型只用满足 ``t + h <= R`` 的样本训练（标签在 R 时点已知），
  因此对 ``as_of >= R`` 的预测严格样本外、且模型在 ``as_of`` 时点可得；
- **无未来信息**：特征本身只使用 ≤t 信息（见 features 层）；模型训练截止由
  标签可得性决定；``as_of`` 不是交易日时取之前最近交易日并在信号中如实标注；
- **可解释**：``drivers`` = 单样本特征归因（SHAP/系数）Top-N，``modality_contrib``
  = 数值/文本模态贡献，``model_version`` 携带训练快照日期；
- **可消融**：``text_enabled=False`` 等价于数值-only 基线，支持模态消融对比；
- **产物**：``precompute()`` 逐日信号写入 ``artifacts/models/<version>/signals.parquet``，
  并登记到模型注册表，供 API/UI 快速读取。

``label``/``evaluate`` 使用未来标签（标签不是特征），仅供训练与实验评估。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from cbr.config import SignalSettings, load_settings
from cbr.data.labels import LabelResult, time_split
from cbr.features.alignment import FeatureBundle
from cbr.models.fusion import FusionModel
from cbr.models.metrics import classification_metrics, summarize_by_horizon
from cbr.models.registry import (
    DEFAULT_ARTIFACT_DIR,
    ModelEntry,
    ModelRegistry,
)
from cbr.schemas import RiskDriver, RiskLevel, RiskSignal

#: 预计算信号表列
SIGNAL_COLUMNS: tuple[str, ...] = (
    "as_of",
    "p_5",
    "p_10",
    "p_20",
    "percentile",
    "level",
    "drivers_json",
    "modality_json",
    "model_version",
    "label_version",
    "snapshot_date",
)

#: 风险等级阈值（基于 10 日期限概率与压力分位，固定规则、可解释）
LEVEL_PROB_HIGH = 0.40
LEVEL_PROB_MEDIUM = 0.20
LEVEL_PCT_HIGH = 0.90
LEVEL_PCT_CRITICAL = 0.95
LEVEL_PROB_CRITICAL = 0.60

#: 回退信号（训练快照尚未可用时）的基准发生率与斜率（按 5/10/20 日）
_FALLBACK_BASE_RATE = {5: 0.12, 10: 0.17, 20: 0.25}
_FALLBACK_SLOPE = {5: 1.2, 10: 1.0, 20: 0.85}


def _sigmoid(value: float) -> float:
    """数值稳定的 sigmoid。"""
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _normalize(sorted_items: list[tuple[str, float]], total: float) -> list[tuple[str, float]]:
    """把 (名称, 有符号贡献) 归一化为绝对值和为 1。"""
    if total <= 1e-12:
        return []
    return [(name, value / total) for name, value in sorted_items]


@dataclass
class SnapshotModel:
    """单个训练快照（某交易日 R 可得的模型集合）。

    Attributes:
        snapshot_date: 训练快照日（模型在此日收盘后可训练完成）。
        models: ``{horizon: FusionModel}``。
        train_windows: ``{horizon: (train_start, train_end, n_samples)}``。
        text_enabled: 该快照模型是否使用文本模态。
    """

    snapshot_date: pd.Timestamp
    models: dict[int, FusionModel] = field(default_factory=dict)
    train_windows: dict[int, tuple[pd.Timestamp, pd.Timestamp, int]] = field(default_factory=dict)
    text_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """快照元数据（写入注册表）。"""
        return {
            "snapshot_date": self.snapshot_date.strftime("%Y-%m-%d"),
            "text_enabled": self.text_enabled,
            "horizons": sorted(self.models),
            "train_windows": {
                str(h): {
                    "start": str(window[0].date()),
                    "end": str(window[1].date()),
                    "n_samples": int(window[2]),
                }
                for h, window in self.train_windows.items()
            },
        }


class SignalEngine:
    """共享风险信号引擎（滚动样本外预测 + 归因 + 模态消融）。

    Args:
        bundle: 建模特征包（``cbr.features.build_feature_bundle`` 输出）。
        settings: 信号配置（模型版本、滚动窗口、重训间隔、文本模态开关）。
        seed: 随机种子。
        artifact_dir: 模型注册表根目录。
        min_train_rows: 训练快照最少训练样本数。
    """

    def __init__(
        self,
        bundle: FeatureBundle,
        settings: SignalSettings | None = None,
        seed: int = 42,
        artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR,
        min_train_rows: int = 80,
        fusion: str = "early",
    ) -> None:
        self.bundle = bundle
        self.settings = settings or SignalSettings()
        self.seed = int(seed)
        self.artifact_dir = artifact_dir
        self.min_train_rows = max(20, int(min_train_rows))
        if fusion not in ("early", "late"):
            raise ValueError(f"不支持的融合方式 {fusion!r}（可选 early/late）")
        self.fusion = fusion
        self.horizons: tuple[int, ...] = tuple(int(h) for h in bundle.labels.config.horizons)
        self.retrain_every = max(1, int(self.settings.retrain_every))
        self.roll_window = max(60, int(self.settings.roll_window))
        self.text_enabled = bool(self.settings.text_enabled) and bool(bundle.text_cols)
        self.registry = ModelRegistry(artifact_dir)
        self._snapshot_cache: dict[tuple[pd.Timestamp, bool], SnapshotModel] = {}
        self._snapshot_dates: list[pd.Timestamp] | None = None
        self._precomputed: pd.DataFrame | None = None
        self._precomputed_version: str | None = None

    # ------------------------------------------------------------------ #
    # 基础属性
    # ------------------------------------------------------------------ #
    @property
    def calendar(self) -> pd.DatetimeIndex:
        """特征/标签共用的交易日历。"""
        return self.bundle.calendar

    @property
    def base_version(self) -> str:
        """配置中的基础模型版本号（不含快照后缀）。"""
        return self.settings.model_version

    def snapshot_dates(self) -> list[pd.Timestamp]:
        """返回滚动训练快照日期列表（按交易日间隔 ``retrain_every``）。"""
        if self._snapshot_dates is not None:
            return self._snapshot_dates
        calendar = self.calendar
        if len(calendar) == 0:
            self._snapshot_dates = []
            return self._snapshot_dates
        horizon_max = max(self.horizons) if self.horizons else 1
        target = self.bundle.target(horizon_max)
        first_valid = target.first_valid_index()
        if first_valid is None:
            self._snapshot_dates = []
            return self._snapshot_dates
        first_pos = int(calendar.get_loc(first_valid))
        start_pos = first_pos + self.min_train_rows
        dates: list[pd.Timestamp] = []
        pos = start_pos
        while pos < len(calendar):
            dates.append(pd.Timestamp(calendar[pos]))
            pos += self.retrain_every
        self._snapshot_dates = dates
        return dates

    # ------------------------------------------------------------------ #
    # 训练快照
    # ------------------------------------------------------------------ #
    def _train_snapshot(self, snapshot_date: pd.Timestamp, text_enabled: bool) -> SnapshotModel:
        """训练某快照日的各期限模型（严格只用到 R 时点已知标签的样本）。"""
        calendar = self.calendar
        position = int(calendar.get_loc(snapshot_date))
        text_cols = self.bundle.text_cols if text_enabled else []
        snapshot = SnapshotModel(snapshot_date=snapshot_date, text_enabled=text_enabled)
        for horizon in self.horizons:
            cutoff = position - int(horizon)  # 只用 t + h <= R 的样本
            if cutoff < 0:
                continue
            X = self.bundle.X.iloc[: cutoff + 1]
            y = self.bundle.target(horizon).iloc[: cutoff + 1]
            mask = y.notna()
            X_train = X.loc[mask]
            y_train = y.loc[mask]
            if len(X_train) > self.roll_window:
                X_train = X_train.iloc[-self.roll_window :]
                y_train = y_train.iloc[-self.roll_window :]
            model = FusionModel(
                numeric_cols=list(self.bundle.numeric_cols),
                text_cols=list(text_cols),
                learner_kind=self.settings.baseline if self.settings.baseline in ("xgboost", "logit", "lasso") else "xgboost",
                text_enabled=bool(text_enabled and text_cols),
                fusion=self.fusion,
                seed=self.seed,
                horizon=int(horizon),
            ).fit(X_train, y_train)
            snapshot.models[int(horizon)] = model
            start = X_train.index[0] if len(X_train) else snapshot_date
            end = X_train.index[-1] if len(X_train) else snapshot_date
            snapshot.train_windows[int(horizon)] = (pd.Timestamp(start), pd.Timestamp(end), int(len(X_train)))
        return snapshot

    def _get_snapshot(self, as_of_ts: pd.Timestamp, text_enabled: bool) -> SnapshotModel | None:
        """获取 as_of 时点可用的最新快照模型（按需训练并缓存）。"""
        dates = [item for item in self.snapshot_dates() if item <= as_of_ts]
        if not dates:
            return None
        snapshot_date = dates[-1]
        key = (snapshot_date, bool(text_enabled))
        if key not in self._snapshot_cache:
            self._snapshot_cache[key] = self._train_snapshot(snapshot_date, bool(text_enabled))
        return self._snapshot_cache[key]

    # ------------------------------------------------------------------ #
    # 信号构造
    # ------------------------------------------------------------------ #
    @staticmethod
    def _risk_level(prob_10: float, percentile: float | None) -> RiskLevel:
        """按 10 日概率与压力分位映射风险等级（固定、可解释的规则）。"""
        pct = percentile if percentile is not None else 0.0
        if prob_10 >= LEVEL_PROB_CRITICAL or pct >= LEVEL_PCT_CRITICAL:
            return RiskLevel.CRITICAL
        if prob_10 >= LEVEL_PROB_HIGH or pct >= LEVEL_PCT_HIGH:
            return RiskLevel.HIGH
        if prob_10 >= LEVEL_PROB_MEDIUM or pct >= 0.75:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _model_version_for(self, snapshot_date: pd.Timestamp | None) -> str:
        """模型版本号（基础版本 + 训练快照日期）。"""
        if snapshot_date is None:
            return f"{self.base_version}-fallback"
        return f"{self.base_version}@{snapshot_date.strftime('%Y%m%d')}"

    def _evidence_id(self, as_of_ts: pd.Timestamp, model_version: str) -> str:
        """信号证据 ID（可复现：日期 + 模型版本短哈希）。"""
        digest = hashlib.sha1(model_version.encode("utf-8")).hexdigest()[:6]
        return f"ev_sig_{as_of_ts.strftime('%Y%m%d')}_{digest}"

    def _drivers(self, model: FusionModel, row: pd.Series, top_n: int = 6) -> tuple[list[RiskDriver], dict[str, float]]:
        """由单样本归因构造驱动因子与模态贡献。"""
        contributions = model.feature_contributions(row)
        from cbr.features.catalog import feature_meta  # 延迟导入避免循环

        ranked = sorted(
            ((name, float(value)) for name, value in contributions.items() if abs(value) > 1e-12),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:top_n]
        total = float(sum(abs(value) for _, value in ranked))
        drivers: list[RiskDriver] = []
        for name, value in _normalize(ranked, total):
            meta = feature_meta(name)
            drivers.append(
                RiskDriver(
                    factor=name,
                    contribution=round(abs(value), 4),
                    direction="up" if value >= 0 else "down",
                    description=f"{meta.name_cn}（{meta.unit or '无量纲'}）：{meta.description or meta.name_cn}",
                )
            )
        modality = model.modality_contributions(row)
        modality = {key: round(float(value), 4) for key, value in modality.items()}
        return drivers, modality

    def _risk_signal_from_components(
        self,
        as_of_ts: pd.Timestamp,
        horizons: dict[int, float],
        percentile: float | None,
        drivers: list[RiskDriver],
        modality_contrib: dict[str, float],
        model_version: str,
        snapshot_date: pd.Timestamp | None = None,
    ) -> RiskSignal:
        """组装 ``RiskSignal``（统一出口，保证字段完整）。"""
        level = self._risk_level(float(horizons.get(10, max(horizons.values()) if horizons else 0.0)), percentile)
        return RiskSignal(
            as_of=as_of_ts.date(),
            model_version=model_version,
            horizons={int(h): round(float(p), 4) for h, p in sorted(horizons.items())},
            percentile=None if percentile is None else round(float(percentile), 4),
            level=level,
            drivers=drivers,
            modality_contrib=modality_contrib,
            label_version=self.bundle.labels.config.label_version,
            evidence_id=self._evidence_id(as_of_ts, model_version),
        )

    def _fallback_signal(self, as_of_ts: pd.Timestamp) -> RiskSignal:
        """训练快照尚不可用时的回退信号：仅用压力指数水平（无未来信息）。"""
        percentile = self.bundle.labels.percentile(as_of_ts)
        cfsi = self.bundle.labels.stress_index(as_of_ts)
        if cfsi is None:
            z = 0.0
        else:
            z = (float(cfsi) - 50.0) / 25.0
        horizons: dict[int, float] = {}
        for horizon in self.horizons:
            base = _FALLBACK_BASE_RATE.get(int(horizon), 0.2)
            slope = _FALLBACK_SLOPE.get(int(horizon), 1.0)
            logit = math.log(base / (1.0 - base)) + slope * z
            horizons[int(horizon)] = _sigmoid(logit)
        drivers: list[RiskDriver] = []
        frame = self.bundle.labels.frame
        if as_of_ts in frame.index:
            row = frame.loc[as_of_ts]
            dim_values: list[tuple[str, float]] = []
            for dim in ("equity", "bond", "credit", "fx", "crossborder", "global"):
                column = f"dim_{dim}"
                if column in row.index and pd.notna(row[column]):
                    value = float(row[column]) - 0.5
                    dim_values.append((dim, value))
            ranked = sorted(dim_values, key=lambda item: abs(item[1]), reverse=True)[:6]
            total = float(sum(abs(value) for _, value in ranked))
            for dim, value in _normalize(ranked, total):
                from cbr.data.labels import DIMENSION_NAMES

                drivers.append(
                    RiskDriver(
                        factor=f"dim_{dim}",
                        contribution=round(abs(value), 4),
                        direction="up" if value >= 0 else "down",
                        description=DIMENSION_NAMES.get(dim, dim),
                    )
                )
        model_version = self._model_version_for(None)
        return self._risk_signal_from_components(
            as_of_ts,
            horizons,
            percentile,
            drivers,
            {"numeric": 1.0, "text": 0.0},
            model_version,
        )

    def _signal_from_snapshot(
        self,
        as_of_ts: pd.Timestamp,
        snapshot: SnapshotModel,
    ) -> RiskSignal:
        """用快照模型对 as_of 特征行预测并构造信号。"""
        row = self.bundle.X.loc[as_of_ts]
        horizons: dict[int, float] = {}
        for horizon, model in snapshot.models.items():
            horizons[int(horizon)] = float(model.predict_one(row))
        driver_horizon = 10 if 10 in snapshot.models else (max(snapshot.models) if snapshot.models else 10)
        driver_model = snapshot.models.get(driver_horizon)
        if driver_model is None:
            return self._fallback_signal(as_of_ts)
        drivers, modality = self._drivers(driver_model, row)
        percentile = self.bundle.labels.percentile(as_of_ts)
        model_version = self._model_version_for(snapshot.snapshot_date)
        return self._risk_signal_from_components(
            as_of_ts, horizons, percentile, drivers, modality, model_version, snapshot.snapshot_date
        )

    # ------------------------------------------------------------------ #
    # 对外预测接口
    # ------------------------------------------------------------------ #
    def latest_trading_day(self, as_of: date | str | pd.Timestamp) -> pd.Timestamp | None:
        """返回 ≤as_of 的最近交易日（as_of 早于样本起点时返回 None）。"""
        ts = pd.Timestamp(as_of)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts = ts.normalize()
        calendar = self.calendar
        if len(calendar) == 0:
            return None
        position = int(calendar.searchsorted(ts, side="right")) - 1
        return pd.Timestamp(calendar[position]) if position >= 0 else None

    def predict(self, as_of: date | str | pd.Timestamp, text_enabled: bool | None = None) -> RiskSignal:
        """返回 ``as_of`` 当日可得的共享风险信号（``RiskSignal``）。

        Args:
            as_of: 任意日期；非交易日自动取之前最近交易日（信号 as_of 为实际数据日）。
            text_enabled: 覆盖模态开关（None=使用配置；False 用于模态消融）。

        Returns:
            ``RiskSignal``（含 5/10/20 日概率、分位、等级、驱动与模态贡献）。
        """
        requested = pd.Timestamp(as_of)
        if requested.tzinfo is not None:
            requested = requested.tz_localize(None)
        requested = requested.normalize()
        ts = self.latest_trading_day(requested)
        if ts is None:
            # 早于样本起点：返回最小可用的回退信号（as_of=请求日）
            return self._risk_signal_from_components(
                requested,
                {int(h): _FALLBACK_BASE_RATE.get(int(h), 0.2) for h in self.horizons},
                None,
                [],
                {"numeric": 1.0, "text": 0.0},
                self._model_version_for(None),
            )
        # 预计算信号优先（快速路径；由 build_dataset 生成）
        precomputed = self._precomputed_signal(ts)
        if precomputed is not None and (text_enabled is None or text_enabled == self.text_enabled):
            return precomputed
        use_text = self.text_enabled if text_enabled is None else bool(text_enabled and self.bundle.text_cols)
        snapshot = self._get_snapshot(ts, use_text)
        if snapshot is None or not snapshot.models:
            return self._fallback_signal(ts)
        return self._signal_from_snapshot(ts, snapshot)

    def predict_proba(self, dates: Iterable[date | str | pd.Timestamp], horizon: int, text_enabled: bool | None = None) -> pd.Series:
        """批量预测某期限的高压力概率（索引为交易日）。"""
        records: dict[pd.Timestamp, float] = {}
        for item in dates:
            ts = self.latest_trading_day(item)
            if ts is None:
                continue
            signal = self.predict(ts, text_enabled=text_enabled)
            if int(horizon) in signal.horizons:
                records[ts] = float(signal.horizons[int(horizon)])
        return pd.Series(records, name=f"p_{int(horizon)}").sort_index()

    # ------------------------------------------------------------------ #
    # 预计算信号（产物快速路径）
    # ------------------------------------------------------------------ #
    def load_precomputed(self, path: str | Path | None = None, model_version: str | None = None) -> pd.DataFrame | None:
        """加载预计算信号表（默认读取注册表最新版本的 ``signals.parquet``）。"""
        candidate = Path(path) if path is not None else None
        if candidate is None:
            if model_version is not None:
                candidate = self.registry.signals_path(model_version)
            else:
                entry = self.registry.latest()
                if entry and entry.get("model_version"):
                    candidate = self.registry.signals_path(str(entry["model_version"]))
        if candidate is None or not candidate.exists():
            return None
        frame = pd.read_parquet(candidate)
        frame["as_of"] = pd.to_datetime(frame["as_of"]).dt.normalize().astype("datetime64[ns]")
        frame = frame.sort_values("as_of").reset_index(drop=True)
        self._precomputed = frame
        self._precomputed_version = model_version or (frame["model_version"].iloc[-1] if len(frame) else None)
        return frame

    def set_precomputed(self, frame: pd.DataFrame) -> None:
        """注入预计算信号表（Provider 已读取时避免重复 IO）。"""
        frame = frame.copy()
        frame["as_of"] = pd.to_datetime(frame["as_of"]).dt.normalize().astype("datetime64[ns]")
        self._precomputed = frame.sort_values("as_of").reset_index(drop=True)
        self._precomputed_version = str(frame["model_version"].iloc[-1]) if len(frame) else None

    def _precomputed_signal(self, as_of_ts: pd.Timestamp) -> RiskSignal | None:
        """从预计算表构造 RiskSignal（若存在 ≤as_of 的最新一行）。"""
        frame = self._precomputed
        if frame is None or frame.empty:
            return None
        position = int(frame["as_of"].searchsorted(as_of_ts, side="right")) - 1
        if position < 0:
            return None
        row = frame.iloc[position]
        horizons = {
            int(h): float(row[f"p_{int(h)}"])
            for h in self.horizons
            if f"p_{int(h)}" in row.index and pd.notna(row[f"p_{int(h)}"])
        }
        if not horizons:
            return None
        drivers: list[RiskDriver] = []
        try:
            raw_drivers = json.loads(row.get("drivers_json") or "[]")
            drivers = [RiskDriver(**item) for item in raw_drivers]
        except (json.JSONDecodeError, TypeError, ValueError):  # pragma: no cover
            drivers = []
        try:
            modality = json.loads(row.get("modality_json") or "{}")
        except (json.JSONDecodeError, TypeError):  # pragma: no cover
            modality = {"numeric": 1.0, "text": 0.0}
        percentile = None if pd.isna(row.get("percentile")) else float(row["percentile"])
        level = str(row.get("level") or "low")
        return RiskSignal(
            as_of=pd.Timestamp(row["as_of"]).date(),
            model_version=str(row.get("model_version") or self._model_version_for(None)),
            horizons=horizons,
            percentile=percentile,
            level=RiskLevel(level),
            drivers=drivers,
            modality_contrib={str(k): float(v) for k, v in modality.items()},
            label_version=str(row.get("label_version") or self.bundle.labels.config.label_version),
            evidence_id=self._evidence_id(pd.Timestamp(row["as_of"]), str(row.get("model_version") or "")),
        )

    def precompute(
        self,
        start: date | str | pd.Timestamp | None = None,
        end: date | str | pd.Timestamp | None = None,
        include_fallback: bool = True,
    ) -> pd.DataFrame:
        """逐日生成 RiskSignal 快照表（写入注册表供 API/UI 快速读取）。

        Args:
            start: 起始日期（默认样本起点）。
            end: 结束日期（默认样本终点）。
            include_fallback: 快照不可用的早期日期是否用回退信号补齐。

        Returns:
            列见 ``SIGNAL_COLUMNS`` 的 DataFrame。
        """
        calendar = self.calendar
        start_ts = pd.Timestamp(start) if start is not None else pd.Timestamp(calendar[0])
        end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp(calendar[-1])
        records: list[dict[str, Any]] = []
        for ts in calendar[(calendar >= start_ts) & (calendar <= end_ts)]:
            signal = self.predict(ts)
            snapshot = self._get_snapshot(pd.Timestamp(ts), self.text_enabled)
            if snapshot is None and not include_fallback:
                continue
            records.append(
                {
                    "as_of": pd.Timestamp(ts),
                    "p_5": signal.horizons.get(5),
                    "p_10": signal.horizons.get(10),
                    "p_20": signal.horizons.get(20),
                    "percentile": signal.percentile,
                    "level": signal.level.value,
                    "drivers_json": json.dumps(
                        [driver.model_dump(mode="json") for driver in signal.drivers], ensure_ascii=False
                    ),
                    "modality_json": json.dumps(signal.modality_contrib, ensure_ascii=False),
                    "model_version": signal.model_version,
                    "label_version": signal.label_version,
                    "snapshot_date": (
                        snapshot.snapshot_date if snapshot is not None else pd.NaT
                    ),
                }
            )
        frame = pd.DataFrame(records)
        if frame.empty:
            return pd.DataFrame(columns=list(SIGNAL_COLUMNS))
        return frame.loc[:, list(SIGNAL_COLUMNS)].reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # 评估 / 消融
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        dates: Iterable[date | str | pd.Timestamp] | None = None,
        text_enabled: bool | None = None,
        threshold: float = 0.5,
    ) -> dict[int, dict[str, Any]]:
        """在给定评估日集合上计算各期限样本外指标（PR-AUC、召回、校准等）。"""
        if dates is None:
            split = time_split(self.calendar)
            eval_dates: list[pd.Timestamp] = list(split["test"])
        else:
            eval_dates = [pd.Timestamp(item) for item in dates]
        predictions: dict[int, list[float]] = {h: [] for h in self.horizons}
        truths: dict[int, list[float]] = {h: [] for h in self.horizons}
        for item in eval_dates:
            ts = self.latest_trading_day(item)
            if ts is None:
                continue
            signal = self.predict(ts, text_enabled=text_enabled)
            row = self.bundle.labels.frame.loc[ts]
            for horizon in self.horizons:
                column = f"y_{horizon}"
                if column not in row.index or pd.isna(row[column]):
                    continue
                if horizon not in signal.horizons:
                    continue
                predictions[horizon].append(float(signal.horizons[horizon]))
                truths[horizon].append(float(row[column]))
        metrics: dict[int, dict[str, Any]] = {}
        for horizon in self.horizons:
            metrics[horizon] = classification_metrics(truths[horizon], predictions[horizon], threshold=threshold)
        return metrics

    def modality_ablation(
        self,
        dates: Iterable[date | str | pd.Timestamp] | None = None,
        threshold: float = 0.5,
    ) -> dict[str, Any]:
        """P1 模态消融：数值-only 基线 vs 数值+文本融合的样本外指标对比。"""
        fusion_metrics = self.evaluate(dates, text_enabled=True, threshold=threshold)
        numeric_metrics = self.evaluate(dates, text_enabled=False, threshold=threshold)
        delta: dict[str, Any] = {}
        for horizon in self.horizons:
            fusion = fusion_metrics.get(horizon, {})
            numeric = numeric_metrics.get(horizon, {})
            delta[str(horizon)] = {
                "pr_auc": float(fusion.get("pr_auc", 0.0) - numeric.get("pr_auc", 0.0)),
                "recall_top10pct": float(
                    fusion.get("recall_top10pct", 0.0) - numeric.get("recall_top10pct", 0.0)
                ),
                "brier": float(fusion.get("brier", 0.0) - numeric.get("brier", 0.0)),
            }
        return {
            "fusion": fusion_metrics,
            "numeric_only": numeric_metrics,
            "delta": delta,
            "summary": {
                "fusion": summarize_by_horizon(fusion_metrics),
                "numeric_only": summarize_by_horizon(numeric_metrics),
            },
        }

    # ------------------------------------------------------------------ #
    # 产物保存
    # ------------------------------------------------------------------ #
    def _latest_snapshot(self) -> pd.Timestamp | None:
        """最新可训练快照日（用于模型版本号）。"""
        dates = [item for item in self.snapshot_dates() if item <= self.calendar[-1]]
        return dates[-1] if dates else None

    def model_version(self) -> str:
        """当前引擎产出的模型版本号。"""
        return self._model_version_for(self._latest_snapshot())

    def average_modality_contrib(self, sample_dates: Iterable[date | str | pd.Timestamp] | None = None) -> dict[str, float]:
        """计算一段日期上的平均模态贡献（写入注册表，便于报告展示）。"""
        if sample_dates is None:
            split = time_split(self.calendar)
            sample_dates = list(split["test"])[:: max(1, len(split["test"]) // 60)]
        numeric: list[float] = []
        text: list[float] = []
        for item in sample_dates:
            signal = self.predict(item)
            numeric.append(float(signal.modality_contrib.get("numeric", 0.0)))
            text.append(float(signal.modality_contrib.get("text", 0.0)))
        if not numeric:
            return {"numeric": 1.0, "text": 0.0}
        return {"numeric": float(np.mean(numeric)), "text": float(np.mean(text))}

    def save_artifacts(
        self,
        metrics: dict[int, dict[str, Any]] | None = None,
        notes: str = "",
        include_fallback: bool = True,
        data_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把预计算信号与模型元数据写入模型注册表，返回注册表条目。

        Args:
            metrics: 样本外指标（None 时使用测试期快速评估）。
            notes: 备注。
            include_fallback: 早期无快照日期是否用回退信号补齐。
            data_snapshot: 数据快照信息（snapshot id / corpus hash 等，写入注册表）。

        Returns:
            注册表条目字典（含 ``model_version`` / ``artifacts_dir`` / ``signals_path``）。
        """
        version = self.model_version()
        signals = self.precompute(include_fallback=include_fallback)
        if metrics is None:
            split = time_split(self.calendar)
            metrics = self.evaluate(dates=list(split["test"]))
        snapshots = [
            self._get_snapshot(item, self.text_enabled).to_dict()
            for item in self.snapshot_dates()
            if self._get_snapshot(item, self.text_enabled) is not None
        ]
        entry = ModelEntry(
            model_version=version,
            label_version=self.bundle.labels.config.label_version,
            horizons=list(self.horizons),
            learner=self.settings.baseline,
            text_enabled=self.text_enabled,
            fusion=self.fusion,
            seed=self.seed,
            dataset_source=(self.bundle.dataset.source if self.bundle.dataset is not None else "unknown"),
            n_features=len(self.bundle.X.columns),
            features=list(self.bundle.X.columns),
            snapshots=snapshots,
            metrics={str(h): value for h, value in metrics.items()},
            modality_contrib_mean=self.average_modality_contrib(),
            data_snapshot=dict(data_snapshot or {}),
            notes=notes or "SYNTHETIC 仿真数据训练的演示模型；滚动样本外预测，禁止用于真实投资/监管决策",
        )
        return self.registry.register(entry, signals=signals)

    # ------------------------------------------------------------------ #
    # 文件系统辅助
    # ------------------------------------------------------------------ #
    def discover_precomputed(self) -> pd.DataFrame | None:
        """自动发现并加载注册表中最新模型的预计算信号（Provider 使用）。"""
        try:
            return self.load_precomputed()
        except (OSError, ValueError, KeyError):  # pragma: no cover
            return None


def build_signal_engine(
    bundle: FeatureBundle,
    settings: SignalSettings | None = None,
    seed: int = 42,
    artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR,
) -> SignalEngine:
    """工厂函数：构造 ``SignalEngine``（供 Provider 与实验脚本使用）。"""
    return SignalEngine(bundle=bundle, settings=settings, seed=seed, artifact_dir=artifact_dir)


def build_signal_engine_from_settings(
    bundle: FeatureBundle,
    app_settings: Any | None = None,
    seed: int = 42,
) -> SignalEngine:
    """由 ``AppSettings`` 构造 ``SignalEngine``（``cbr.service`` 装配路径）。"""
    app_settings = app_settings or load_settings()
    return SignalEngine(
        bundle=bundle,
        settings=app_settings.signal,
        seed=seed,
        artifact_dir=str(Path(app_settings.paths.artifacts) / "models"),
    )
