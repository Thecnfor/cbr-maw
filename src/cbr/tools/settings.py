"""工具层配置：读取 configs/tools.yaml（工具版本、默认参数、注册表选项）。

配置不提供时使用代码内兜底默认值，保证 ``build_tool_registry`` 可独立运行；
权限矩阵不在此文件配置——权限唯一来源是 ``configs/roles.yaml``。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..config import load_yaml, resolve_path

DEFAULT_TOOLS_CONFIG_PATH = "configs/tools.yaml"

# 数据序列默认映射（configs/tools.yaml 可覆盖；DataProvider 的 series_id 口径以此为准）
DEFAULT_SERIES: dict[str, str] = {
    "equity": "market.cn_equity",
    "bond": "market.cn_bond",
    "global_equity": "market.global.us_equity",
    "fx_usdcny": "market.fx.usdcny",
    "credit_spread": "rates.credit.aa_spread",
    "northbound": "crossborder.northbound_net",
    "southbound": "crossborder.southbound_net",
    "ah_premium": "crossborder.ah_premium",
}

# 系统性风险工具的跨市场序列集合（DY 溢出指数）
DEFAULT_DY_SERIES: list[str] = [
    "market.cn_equity",
    "market.global.us_equity",
    "market.fx.usdcny",
    "rates.credit.aa_spread",
]


class ToolEntry(BaseModel):
    """单个工具的配置项。"""

    version: str = "1.0.0"
    defaults: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ToolsConfig(BaseModel):
    """configs/tools.yaml 的结构。"""

    registry_version: str = "tools-v1"
    default_deny: bool = True
    tools: dict[str, ToolEntry] = Field(default_factory=dict)
    series: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SERIES))
    dy_series: list[str] = Field(default_factory=lambda: list(DEFAULT_DY_SERIES))

    def entry(self, name: str) -> ToolEntry:
        return self.tools.get(name, ToolEntry())

    def resolved_series(self) -> dict[str, str]:
        merged = dict(DEFAULT_SERIES)
        merged.update({k: str(v) for k, v in self.series.items() if v})
        return merged

    def tool_defaults(self, name: str) -> dict[str, Any]:
        """把工具配置中的 series 映射注入到该工具的默认参数（仅当参数名匹配）。"""
        entry = self.entry(name)
        defaults = dict(entry.defaults)
        series = self.resolved_series()
        # 常见参数名 -> 序列映射键
        param_to_series_key = {
            "series_id": "equity",
            "market_series_id": "equity",
            "asset_series_id": "bond",
            "inflow_series_id": "northbound",
            "outflow_series_id": "southbound",
            "ah_premium_series_id": "ah_premium",
            "spread_series_id": "credit_spread",
            "target_series_id": "equity",
            "us_equity_series_id": "global_equity",
            "fx_series_id": "fx_usdcny",
        }
        for param, series_key in param_to_series_key.items():
            if param not in defaults and series_key in series:
                defaults[param] = series[series_key]
        if name == "systemic_risk" and "series_ids" not in defaults:
            defaults["series_ids"] = list(self.dy_series)
        return defaults


def load_tools_config(path: str | os.PathLike[str] | None = None) -> ToolsConfig:
    """读取 configs/tools.yaml；文件缺失时返回内置默认配置。"""
    cfg_path = Path(path) if path is not None else resolve_path(
        os.environ.get("CBR_TOOLS_CONFIG", DEFAULT_TOOLS_CONFIG_PATH)
    )
    raw = load_yaml(cfg_path, default=None)
    if not raw:
        return ToolsConfig()
    if not isinstance(raw, Mapping):
        raise ValueError(f"invalid tools config (expected mapping): {cfg_path}")
    return ToolsConfig(**dict(raw))
