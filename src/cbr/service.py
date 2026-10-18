"""服务装配层：把各模块实现组装成可被 API/UI/实验调用的单例。

各模块必须提供以下工厂函数（约定见 contracts.py）：
- cbr.data.build_data_provider(settings) -> DataProvider
- cbr.knowledge.build_knowledge_base(settings) -> KnowledgeBase
- cbr.tools.build_tool_registry(settings, provider, kb) -> ToolRegistry
- cbr.llm.build_llm_client(settings) -> LLMClient
- cbr.orchestration.build_orchestrator(settings, provider, registry, kb, llm) -> Orchestrator
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import AppSettings, load_scenarios, load_settings
from .contracts import (
    DataProvider,
    KnowledgeBase,
    LLMClient,
    Orchestrator,
    ToolRegistry,
)
from .schemas import Scenario


class Service:
    """应用服务容器（数据/知识/工具/LLM/编排）。"""

    def __init__(
        self,
        settings: AppSettings,
        provider: DataProvider,
        kb: KnowledgeBase,
        registry: ToolRegistry,
        llm: LLMClient,
        orchestrator: Orchestrator,
        scenarios: list[Scenario],
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.kb = kb
        self.registry = registry
        self.llm = llm
        self.orchestrator = orchestrator
        self.scenarios = scenarios

    # -- 便捷访问 ---------------------------------------------------------
    def available_scenarios(self) -> list[Scenario]:
        return self.scenarios

    def artifacts_dir(self) -> Path:
        path = Path(self.settings.paths.artifacts)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        path.mkdir(parents=True, exist_ok=True)
        return path


def build_service(settings: AppSettings | None = None) -> Service:
    """按约定装配全部模块；任一模块未就绪时抛出带说明的 ImportError。"""
    settings = settings or load_settings()

    from .data import build_data_provider
    from .knowledge import build_knowledge_base
    from .llm import build_llm_client
    from .orchestration import build_orchestrator
    from .tools import build_tool_registry

    provider = build_data_provider(settings)
    kb = build_knowledge_base(settings)
    registry = build_tool_registry(settings, provider, kb)
    llm = build_llm_client(settings)
    orchestrator = build_orchestrator(settings, provider, registry, kb, llm)
    scenarios = load_scenarios()
    return Service(settings, provider, kb, registry, llm, orchestrator, scenarios)


@lru_cache(maxsize=1)
def get_service() -> Service:
    """进程内单例（Streamlit / FastAPI / 脚本共用）。"""
    return build_service()


def reset_service() -> None:
    get_service.cache_clear()
