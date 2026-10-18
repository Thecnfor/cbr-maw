"""跨模块接口协议（依赖倒置）。

各模块只需实现以下 Protocol，即可被编排层/API 装配；单元测试可用
Mock 实现替代。具体实现位置：
- DataProvider    -> src/cbr/data/（data-model 模块）
- Tool/ToolRegistry -> src/cbr/tools/（tools-knowledge 模块）
- KnowledgeBase   -> src/cbr/knowledge/（tools-knowledge 模块）
- LLMClient       -> src/cbr/llm/（agents-core 模块）
- Orchestrator    -> src/cbr/orchestration/（agents-core 模块）
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from .schemas import (
    ChatRequest,
    ChatResponse,
    DataCard,
    DecisionCard,
    Evidence,
    MarketSnapshot,
    RiskSignal,
    Role,
    RoleSpec,
    ToolResult,
)

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class DataProvider(Protocol):
    """时点数据访问接口：所有读取都必须传入 as_of 并遵守 point-in-time。"""

    def risk_signal(self, as_of: date) -> RiskSignal:
        """返回 as_of 当日可得的共享多模态风险信号（P1 产物）。"""
        ...

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        """返回 as_of 当日的关键行情/资金快照。"""
        ...

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict[str, Any]]:
        """返回截至 as_of 的历史序列 [{"date":..., "value":...}, ...]（长度<=lookback）。"""
        ...

    def label(self, as_of: date, horizon: int) -> int | None:
        """返回 as_of 之后 horizon 个交易日是否处于高压力状态（仅评估阶段使用；
        实现内部仍应通过 PIT 访问，避免实验/演示泄漏）。"""
        ...

    def data_cards(self) -> list[DataCard]:
        """返回全部数据卡（数据说明）。"""
        ...


@runtime_checkable
class Tool(Protocol):
    """确定性金融工具：输入参数 -> ToolResult（含 Evidence，可重算）。"""

    name: str
    version: str
    description: str

    def run(self, as_of: date, **kwargs: Any) -> ToolResult: ...


@runtime_checkable
class ToolRegistry(Protocol):
    def get(self, name: str) -> Tool: ...

    def names(self) -> list[str]: ...

    def allow(self, role: Role, tool_name: str) -> bool:
        """按角色权限矩阵判断是否允许调用；越权返回 False（调用方负责审计）。"""
        ...


@runtime_checkable
class KnowledgeBase(Protocol):
    def search(self, query: str, as_of: date, top_k: int = 5) -> list[Evidence]:
        """时点过滤检索：只返回 publish_time <= as_of 的片段。"""
        ...

    def count(self) -> int: ...


@runtime_checkable
class LLMClient(Protocol):
    """LLM 抽象层：支持真实 API 与 mock 两种实现，接口保持一致。"""

    def structured(self, system: str, user: str, schema: type[T], **kwargs: Any) -> T:
        """要求模型输出符合给定 Pydantic schema 的结构化结果。"""
        ...

    def text(self, system: str, user: str, **kwargs: Any) -> str:
        """自由文本生成（用于对话入口/汇总）。"""
        ...

    @property
    def usage(self) -> dict[str, int]:
        """累计用量 {"prompt_tokens":..., "completion_tokens":..., "calls":...}"""
        ...


@runtime_checkable
class Orchestrator(Protocol):
    """协同编排入口：同步执行一次预警决策 / 一次对话。"""

    def run(
        self,
        as_of: date,
        mode: str = "collaborative",
        scenario: str | None = None,
    ) -> DecisionCard: ...

    def chat(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class RoleRegistry(Protocol):
    def get(self, role: Role | str) -> RoleSpec: ...

    def all(self) -> list[RoleSpec]: ...
