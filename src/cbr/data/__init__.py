"""数据与时点层（L1）：确定性仿真数据、PIT 存储、自定义数据适配、风险标签与 DataProvider。

对外主要接口：

.. code-block:: python

    from cbr.data import build_data_provider, SERIES_SPECS, KEY_SERIES
    provider = build_data_provider()                 # settings 省略时读 configs/app.yaml
    provider.risk_signal("2024-08-05")               # schemas.RiskSignal
    provider.history("market.cn_equity.csi300", "2024-08-05", 120)

    from cbr.data.synthetic import generate_dataset  # 确定性仿真数据
    from cbr.data.pit_store import PitStore          # DuckDB point-in-time 存储
    from cbr.data.labels import build_stress_labels  # CFSI-CN 压力指数 + 标签
    from cbr.data.series import SERIES_SPECS, KEY_SERIES, series_domain

约定：样本数据全部为 SYNTHETIC 仿真数据（``source=synthetic-simulation``），
仅用于演示与测试；真实数据接入通过 ``data/custom`` + ``configs/data_mapping.yaml``。
"""

from __future__ import annotations

from cbr.data.catalog import (
    DAILY_SERIES_IDS,
    DERIVED_SERIES,
    DOMAIN_DESCRIPTIONS,
    KEY_SNAPSHOT_SERIES,
    MONTHLY_SERIES_IDS,
    NORTHBOUND_DISCLOSURE_END,
    SERIES_ALIASES,
    SERIES_IDS,
    SERIES_SPECS,
    SYNTHETIC_NOTE,
    SYNTHETIC_SOURCE,
    SeriesSpec,
    build_data_cards,
    canonical_series_id,
    resolve_series_id,
    series_domain,
    series_unit,
)
from cbr.data.dataset import DOC_COLUMNS, OBS_COLUMNS, MarketDataset
from cbr.data.labels import (
    DEFAULT_HORIZONS,
    DEFAULT_LABEL_VERSION,
    DIMENSION_NAMES,
    LabelConfig,
    LabelResult,
    build_stress_labels,
    parse_label_version,
    time_split,
)
from cbr.data.pit_store import PitStore, build_pit_store
from cbr.data.provider import (
    MarketDataProvider,
    PitStoreDataProvider,
    build_data_provider,
)
from cbr.data.synthetic import (
    SAMPLE_END,
    SAMPLE_SEED,
    SAMPLE_START,
    cn_trading_calendar,
    generate_dataset,
    load_sample_dataset,
    write_sample_data,
)

#: 对外常用短名
KEY_SERIES = KEY_SNAPSHOT_SERIES

__all__ = [
    "DAILY_SERIES_IDS",
    "DEFAULT_HORIZONS",
    "DEFAULT_LABEL_VERSION",
    "DERIVED_SERIES",
    "DIMENSION_NAMES",
    "DOC_COLUMNS",
    "DOMAIN_DESCRIPTIONS",
    "KEY_SERIES",
    "KEY_SNAPSHOT_SERIES",
    "LabelConfig",
    "LabelResult",
    "MONTHLY_SERIES_IDS",
    "MarketDataProvider",
    "MarketDataset",
    "NORTHBOUND_DISCLOSURE_END",
    "OBS_COLUMNS",
    "PitStore",
    "PitStoreDataProvider",
    "SAMPLE_END",
    "SAMPLE_SEED",
    "SAMPLE_START",
    "SERIES_ALIASES",
    "SERIES_IDS",
    "SERIES_SPECS",
    "SYNTHETIC_NOTE",
    "SYNTHETIC_SOURCE",
    "SeriesSpec",
    "build_data_cards",
    "build_data_provider",
    "build_pit_store",
    "build_stress_labels",
    "canonical_series_id",
    "cn_trading_calendar",
    "generate_dataset",
    "load_sample_dataset",
    "parse_label_version",
    "resolve_series_id",
    "series_domain",
    "series_unit",
    "time_split",
    "write_sample_data",
]
