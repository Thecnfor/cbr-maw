"""数据序列公开口径（下游模块唯一入口）。

“数据与信号”模块对外承诺的序列 ID 规范集中在本文件导出，供工具层、智能体层、
编排层、API/UI 与实验层引用；**下游不应硬编码其他序列 ID**。

与 ``configs/roles.yaml`` 的信息域对应关系：

- ``market.cn_equity.*`` / ``market.cn_bond.*`` / ``market.fx.*`` / ``market.global.*``
- ``crossborder.flows.*`` / ``crossborder.holdings.*``
- ``macro.*`` / ``rates.credit.*``

典型用法::

    from cbr.data.series import SERIES_SPECS, KEY_SERIES, series_domain

    spec = SERIES_SPECS["market.cn_equity.csi300"]
    KEY_SERIES                     # 默认行情快照序列 ID 元组
    series_domain("macro.pmi.manufacturing")  # -> "macro"

兼容别名（历史写法/其他模块早期约定）会通过 :func:`resolve_series_id` 归一化，
例如 ``market.global.us_equity`` -> ``market.global.sp500``、
``crossborder.northbound_net`` -> ``crossborder.flows.northbound_net``。
``DataProvider`` 的 ``history/market_snapshot`` 已内置别名解析，两种写法均可。
"""

from __future__ import annotations

from .catalog import (
    DAILY_SERIES_IDS,
    DERIVED_SERIES,
    DOMAIN_DESCRIPTIONS,
    KEY_SNAPSHOT_SERIES,
    MONTHLY_SERIES_IDS,
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

#: 默认行情/资金快照序列（``KEY_SERIES`` 为对外常用短名）
KEY_SERIES = KEY_SNAPSHOT_SERIES

__all__ = [
    "DAILY_SERIES_IDS",
    "DERIVED_SERIES",
    "DOMAIN_DESCRIPTIONS",
    "KEY_SERIES",
    "KEY_SNAPSHOT_SERIES",
    "MONTHLY_SERIES_IDS",
    "SERIES_ALIASES",
    "SERIES_IDS",
    "SERIES_SPECS",
    "SYNTHETIC_NOTE",
    "SYNTHETIC_SOURCE",
    "SeriesSpec",
    "build_data_cards",
    "canonical_series_id",
    "resolve_series_id",
    "series_domain",
    "series_unit",
]
