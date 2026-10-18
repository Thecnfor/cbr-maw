"""单智能体基线（P3 对照实验）：一个通用 agent 依次完成三主体任务。

与三角色协同/独立模式的差异（也是 P3 消融的自变量）：

- **无专业化分工**：同一个通用 system prompt + 三主体工具权限并集；
- **顺序执行**：监管 → 投资 → 融资依次分析，后一个任务可以看到前一个任务产生的
  证据（同一 agent 的上下文），但没有交叉验证/分歧协调流程；
- **统一预算**：每个子任务与单角色智能体使用相同的工具/token 预算配置，
  因此单智能体的总预算 ≈ 三个角色智能体预算之和（编排层可按需要传 budget 覆盖）。

实现上复用 :class:`cbr.agents.role_agent.RoleAgent` 的完整 Agent Loop（同一代码
路径），只替换 RoleSpec 与 system prompt，保证单智能体与协同模式的差异仅来自
"分工与协同机制"，而不是实现差异 —— 这正是 P3 实验需要的可比性。
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Sequence

from pydantic import BaseModel, Field

from ..config import AppSettings, load_role_specs
from ..contracts import DataProvider, KnowledgeBase, LLMClient, ToolRegistry
from ..schemas import (
    AgentContext,
    AgentOutput,
    ExperimentMode,
    Role,
    RoleSpec,
    TraceEvent,
)
from .prompts import single_agent_system_prompt
from .role_agent import RoleAgent

logger = logging.getLogger("cbr.agents.single_agent")

_ROLE_ORDER: tuple[Role, ...] = (Role.REGULATOR, Role.INVESTOR, Role.FINANCING)

_GENERALIST_OBJECTIVE = (
    "作为通用金融风险分析智能体，在统一会话中依次完成监管、投资、融资三类主体的"
    "风险评估与决策建议；共享同一套证据与工具预算，不依赖其他智能体配合。"
)


class SingleAgentResult(BaseModel):
    """单智能体一次完整运行结果（三个主体卡片 + 聚合用量 + 合并 trace）。"""

    mode: ExperimentMode = ExperimentMode.SINGLE
    as_of: date
    run_id: str = ""
    cards: dict[str, AgentOutput] = Field(default_factory=dict)  # role.value -> AgentOutput
    tool_calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    trace: list[TraceEvent] = Field(default_factory=list)


class SingleAgent:
    """单智能体基线：一个通用 agent 顺序完成三主体任务。"""

    def __init__(
        self,
        registry: ToolRegistry,
        provider: DataProvider,
        kb: KnowledgeBase,
        llm: LLMClient,
        settings: AppSettings,
        *,
        role_specs: dict[Role, RoleSpec] | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.kb = kb
        self.llm = llm
        self.settings = settings
        self._logger = logger_ or logger
        self.role_specs: dict[Role, RoleSpec] = role_specs or load_role_specs()
        self._tool_plan = self._union_tool_plan()
        self._union_tools = self._union_permissions()
        self._system_prompt = single_agent_system_prompt(self.role_specs)
        self._agents: dict[Role, RoleAgent] = self._build_agents()

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #
    def analyze(self, context: AgentContext) -> SingleAgentResult:
        """顺序完成三主体任务，返回聚合结果。"""

        started = time.perf_counter()
        run_id = str(context.budget.get("run_id") or "").strip() or (
            f"single-{context.as_of.strftime('%Y%m%d')}"
        )
        cards: dict[str, AgentOutput] = {}
        trace: list[TraceEvent] = [
            TraceEvent(
                run_id=run_id,
                step=f"R{context.round}",
                role=None,
                action="single_agent_start",
                detail={
                    "roles": [role.value for role in _ROLE_ORDER],
                    "llm_mode": getattr(self.llm, "mode", "unknown"),
                    "tool_plan": list(self._tool_plan),
                },
            )
        ]
        tool_calls = 0
        tokens = 0
        latency_ms = 0

        for role in _ROLE_ORDER:
            agent = self._agents.get(role)
            if agent is None:
                continue
            sub_context = self._sub_context(context, run_id=run_id, role=role)
            try:
                output = agent.analyze(sub_context)
            except Exception as exc:  # noqa: BLE001 - 单主体失败不拖垮其余主体
                self._logger.exception("单智能体子任务失败 role=%s: %s", role.value, exc)
                trace.append(
                    TraceEvent(
                        run_id=run_id,
                        step=f"R{context.round}",
                        role=role.value,
                        action="role_failed",
                        detail={"error": str(exc)[:300]},
                    )
                )
                continue
            cards[role.value] = output
            tool_calls += output.tool_calls
            tokens += output.tokens
            latency_ms += output.latency_ms
            trace.extend(output.trace)

        total_latency = int((time.perf_counter() - started) * 1000)
        trace.append(
            TraceEvent(
                run_id=run_id,
                step=f"R{context.round}",
                role=None,
                action="finalize",
                detail={
                    "mode": ExperimentMode.SINGLE.value,
                    "cards": len(cards),
                    "tool_calls": tool_calls,
                    "tokens": tokens,
                    "latency_ms": total_latency,
                },
                latency_ms=total_latency,
                tokens=tokens,
            )
        )
        return SingleAgentResult(
            mode=ExperimentMode.SINGLE,
            as_of=context.as_of,
            run_id=run_id,
            cards=cards,
            tool_calls=tool_calls,
            tokens=tokens,
            latency_ms=total_latency,
            trace=trace,
        )

    def analyze_one(self, context: AgentContext, role: Role | str) -> AgentOutput:
        """只完成单个主体任务（便于逐步对照/测试）。"""

        role_key = Role(role) if isinstance(role, str) else role
        agent = self._agents[role_key]
        run_id = str(context.budget.get("run_id") or "").strip() or (
            f"single-{context.as_of.strftime('%Y%m%d')}"
        )
        return agent.analyze(self._sub_context(context, run_id=run_id, role=role_key))

    @property
    def tool_plan(self) -> list[str]:
        """三主体工具权限并集（不含 knowledge_search：KB 由 RoleAgent 直连检索）。"""

        return list(self._tool_plan)

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _sub_context(
        self, context: AgentContext, *, run_id: str, role: Role
    ) -> AgentContext:
        budget = dict(context.budget or {})
        budget["run_id"] = run_id
        budget["step"] = f"R{context.round}"
        budget["mode"] = ExperimentMode.SINGLE.value
        budget["role"] = role.value
        return context.model_copy(update={"budget": budget, "mode": ExperimentMode.SINGLE})

    def _union_tool_plan(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            for tool_name in spec.tool_permissions:
                if tool_name == "knowledge_search":
                    continue  # KB 检索由 RoleAgent 直连 kb.search，避免重复证据
                if tool_name not in seen:
                    seen.add(tool_name)
                    ordered.append(tool_name)
        return ordered

    def _union_permissions(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            for tool_name in spec.tool_permissions:
                if tool_name not in seen:
                    seen.add(tool_name)
                    ordered.append(tool_name)
        return ordered

    def _union_info_permissions(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            for item in spec.info_permissions:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return ordered

    def _union_focus(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            for item in spec.focus:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return ordered

    def _union_forbidden(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            for item in spec.forbidden_actions:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return ordered

    def _build_agents(self) -> dict[Role, RoleAgent]:
        agents: dict[Role, RoleAgent] = {}
        info_permissions = self._union_info_permissions()
        focus = self._union_focus()
        forbidden = self._union_forbidden()
        for role in _ROLE_ORDER:
            spec = self.role_specs.get(role)
            if spec is None:
                continue
            generalist_spec = spec.model_copy(
                update={
                    "display_name": f"通用分析智能体（{spec.display_name}任务）",
                    "objective": _GENERALIST_OBJECTIVE,
                    "focus": focus,
                    "info_permissions": info_permissions,
                    "tool_permissions": list(self._union_tools),
                    "forbidden_actions": forbidden,
                }
            )
            agents[role] = RoleAgent(
                role_spec=generalist_spec,
                registry=self.registry,
                provider=self.provider,
                kb=self.kb,
                llm=self.llm,
                settings=self.settings,
                system_prompt=self._system_prompt,
                tool_plan=self._tool_plan,
                enforce_registry_permissions=False,
            )
        return agents


def build_single_agent(
    registry: ToolRegistry,
    provider: DataProvider,
    kb: KnowledgeBase,
    llm: LLMClient,
    settings: AppSettings,
    *,
    role_specs: dict[Role, RoleSpec] | None = None,
) -> SingleAgent:
    """构建单智能体基线（P3 对照实验用）。"""

    return SingleAgent(
        registry=registry,
        provider=provider,
        kb=kb,
        llm=llm,
        settings=settings,
        role_specs=role_specs,
    )


__all__ = ["SingleAgent", "SingleAgentResult", "build_single_agent"]
