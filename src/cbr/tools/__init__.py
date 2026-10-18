"""确定性工具层：工厂、注册表与统一证据构造。

对外主入口（service.py 约定）::

    from cbr.tools import build_tool_registry
    registry = build_tool_registry(settings, provider, kb)
    result = registry.run("regulator", "risk_measure", as_of)   # 带权限校验
    result = registry.get("risk_measure").run(as_of)            # 绕过权限校验（测试/核验重算用）

工具清单（7 个，全部确定性纯计算，禁止调用 LLM）：
risk_measure / systemic_risk / capital_flow / funding_cost / scenario /
forecast / knowledge_search。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..config import AppSettings
from ..schemas import Role, RoleSpec
from .base import (
    TOOL_LAYER_VERSION,
    AuditEvent,
    BaseTool,
    ToolError,
    ToolOutput,
    ToolRegistryImpl,
    build_evidence,
    canonical_json,
    compute_inputs_hash,
    normalize_as_of,
    sha256_text,
    to_native,
)
from .capital import CapitalFlowTool
from .forecast import ForecastTool
from .funding import FundingCostTool
from .kb_search import KnowledgeSearchTool
from .risk import RiskMeasureTool
from .scenario import ScenarioTool
from .settings import (
    DEFAULT_DY_SERIES,
    DEFAULT_SERIES,
    ToolEntry,
    ToolsConfig,
    load_tools_config,
)
from .systemic import SystemicRiskTool

TOOL_CLASSES: list[type[BaseTool]] = [
    RiskMeasureTool,
    SystemicRiskTool,
    CapitalFlowTool,
    FundingCostTool,
    ScenarioTool,
    ForecastTool,
    KnowledgeSearchTool,
]


def build_tool_registry(
    settings: AppSettings | None = None,
    provider: Any | None = None,
    kb: Any | None = None,
    *,
    config_path: str | None = None,
    role_specs: Mapping[Role, RoleSpec] | None = None,
    audit_sink: Any | None = None,
) -> ToolRegistryImpl:
    """装配 7 个确定性工具并注入角色权限矩阵。

    参数
    ----
    settings : AppSettings | None
        应用配置（本函数当前只透传，保留 service.py 工厂签名）。
    provider : DataProvider
        时点数据访问实现（data-model 模块）。
    kb : KnowledgeBase
        时点知识库实现（knowledge 模块）。
    config_path, role_specs, audit_sink
        测试/集成注入点：工具配置路径、角色规范、权限审计回调。
    """
    del settings  # 预留：工具配置目前独立于 AppSettings，从 configs/tools.yaml 读取
    cfg = load_tools_config(config_path)
    tools: list[BaseTool] = []
    for tool_cls in TOOL_CLASSES:
        entry = cfg.entry(tool_cls.name)
        if not entry.enabled:
            continue
        tools.append(
            tool_cls(
                provider=provider,
                kb=kb,
                version=entry.version,
                defaults=cfg.tool_defaults(tool_cls.name),
            )
        )
    return ToolRegistryImpl(
        tools,
        role_specs=role_specs,
        default_deny=cfg.default_deny,
        audit_sink=audit_sink,
        registry_version=cfg.registry_version,
    )


__all__ = [
    "TOOL_CLASSES",
    "TOOL_LAYER_VERSION",
    "AuditEvent",
    "BaseTool",
    "CapitalFlowTool",
    "DEFAULT_DY_SERIES",
    "DEFAULT_SERIES",
    "ForecastTool",
    "FundingCostTool",
    "KnowledgeSearchTool",
    "RiskMeasureTool",
    "ScenarioTool",
    "SystemicRiskTool",
    "ToolEntry",
    "ToolError",
    "ToolOutput",
    "ToolRegistryImpl",
    "ToolsConfig",
    "build_evidence",
    "build_tool_registry",
    "canonical_json",
    "compute_inputs_hash",
    "load_tools_config",
    "normalize_as_of",
    "sha256_text",
    "to_native",
]
