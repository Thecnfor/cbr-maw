"""模型注册表：把信号模型产物版本化保存到 ``artifacts/models/``。

目录约定::

    artifacts/models/
    ├─ manifest.json                 # 所有模型版本清单（JSON，可被 API/UI/实验读取）
    ├─ fusion-xgb-v1@20240628/      # 单个模型版本目录
    │  ├─ model_info.json            # 版本元数据（特征、快照、标签、训练窗口、指标）
    │  └─ signals.parquet            # 预计算的逐日 RiskSignal 快照（演示/UI 快速读取）
    └─ ...

注册表不依赖数据库，便于复制/复现；``model_version`` 会写入 ``RiskSignal.model_version``，
从而任何一条预警信号都能追溯到具体训练快照与特征集合。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cbr.config import resolve_path

#: 默认产物根目录
DEFAULT_ARTIFACT_DIR = "artifacts/models"


def _json_default(value: Any) -> Any:
    """把 numpy / date / Timestamp 等转为可 JSON 序列化的对象。"""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Series,)):
        return value.to_dict()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"无法序列化类型 {type(value)!r}")


@dataclass
class ModelEntry:
    """模型版本条目（写入 manifest.json）。

    Attributes:
        model_version: 模型版本号（如 ``fusion-xgb-v1@20240628``）。
        label_version: 标签版本号。
        horizons: 预测期限列表。
        learner: 学习器类型。
        text_enabled: 是否启用文本模态。
        fusion: 融合方式（early/late）。
        seed: 随机种子。
        dataset_source: 数据来源标记（synthetic-simulation / user-provided）。
        n_features: 特征数量。
        features: 特征列名。
        snapshots: 滚动训练快照元数据列表。
        metrics: 样本外评估指标 ``{horizon: {...}}``。
        modality_contrib_mean: 全样本平均模态贡献。
        signals_path: 预计算信号 parquet 路径（相对 artifacts root）。
        created_at: 创建时间（ISO 字符串）。
        notes: 备注。
        artifacts_dir: 版本目录（注册后填充）。
    """

    model_version: str
    label_version: str = "stress_pca_q90"
    horizons: list[int] = field(default_factory=lambda: [5, 10, 20])
    learner: str = "xgboost"
    text_enabled: bool = True
    fusion: str = "early"
    seed: int = 42
    dataset_source: str = "synthetic-simulation"
    n_features: int = 0
    features: list[str] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    modality_contrib_mean: dict[str, float] = field(default_factory=dict)
    data_snapshot: dict[str, Any] = field(default_factory=dict)
    signals_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    notes: str = "SYNTHETIC 仿真数据训练的演示模型，不得用于真实投资/监管决策"
    artifacts_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 可序列化字典。"""
        data = dict(self.__dict__)
        return json.loads(json.dumps(data, ensure_ascii=False, default=_json_default))


class ModelRegistry:
    """模型注册表（文件系统实现）。

    Args:
        root: 产物根目录（默认 ``artifacts/models``）。
    """

    def __init__(self, root: str | Path = DEFAULT_ARTIFACT_DIR) -> None:
        self.root = resolve_path(root) if not Path(root).is_absolute() else Path(root)
        self.manifest_path = self.root / "manifest.json"

    # ------------------------------------------------------------------ #
    # manifest
    # ------------------------------------------------------------------ #
    def load(self) -> list[dict[str, Any]]:
        """读取模型清单（文件不存在时返回空列表）。"""
        if not self.manifest_path.exists():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # pragma: no cover
            return []
        return list(data.get("models", []))

    def _save(self, entries: list[dict[str, Any]]) -> None:
        """写回 manifest（保持按创建时间排序）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        entries = sorted(entries, key=lambda item: str(item.get("created_at", "")), reverse=True)
        payload = {
            "registry_version": "cbr-model-registry-v1",
            "synthetic_notice": "本目录模型均由 SYNTHETIC 仿真数据训练，仅用于演示/测试",
            "models": entries,
        }
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # 注册 / 查询
    # ------------------------------------------------------------------ #
    def register(self, entry: ModelEntry, signals: pd.DataFrame | None = None) -> dict[str, Any]:
        """注册一个模型版本，可选保存逐日预计算信号。

        Args:
            entry: 模型版本条目。
            signals: 预计算信号表（列见 ``cbr.models.signal.SIGNAL_COLUMNS``）。

        Returns:
            含 ``artifacts_dir`` / ``signals_path`` 的条目标字典。
        """
        safe_name = entry.model_version.replace("@", "_at_").replace("/", "-").replace("\\", "-")
        version_dir = self.root / safe_name
        version_dir.mkdir(parents=True, exist_ok=True)
        if signals is not None:
            signals_path = version_dir / "signals.parquet"
            signals.to_parquet(signals_path, index=False)
            # 以注册表根目录为基准保存相对路径（便于整体复制/迁移）
            entry.signals_path = str(Path(safe_name) / "signals.parquet")
        entry.artifacts_dir = str(version_dir)
        (version_dir / "model_info.json").write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        entries = [item for item in self.load() if item.get("model_version") != entry.model_version]
        entries.append(entry.to_dict())
        self._save(entries)
        return entry.to_dict()

    def get(self, model_version: str) -> dict[str, Any] | None:
        """按版本号读取条目。"""
        for item in self.load():
            if item.get("model_version") == model_version:
                return item
        return None

    def latest(self) -> dict[str, Any] | None:
        """返回最新注册的模型条目（无模型时 None）。"""
        entries = self.load()
        return entries[0] if entries else None

    def artifacts_dir(self, model_version: str) -> Path | None:
        """返回版本目录（不存在时 None）。"""
        entry = self.get(model_version)
        if not entry or not entry.get("artifacts_dir"):
            return None
        path = Path(str(entry["artifacts_dir"]))
        return path if path.is_absolute() else resolve_path(path)

    def signals_path(self, model_version: str) -> Path | None:
        """返回预计算信号 parquet 路径（不存在时 None）。"""
        entry = self.get(model_version)
        if not entry or not entry.get("signals_path"):
            return None
        raw = Path(str(entry["signals_path"]))
        if raw.is_absolute():
            return raw if raw.exists() else None
        candidate = self.root / raw
        if candidate.exists():
            return candidate
        # 兼容旧版注册表：路径相对项目根目录保存
        legacy = resolve_path(raw)
        return legacy if legacy.exists() else None
