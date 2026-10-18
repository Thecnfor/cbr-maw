"""智能体层（L4）：三角色预警智能体 + 单智能体基线 + prompt 模板。

对外主要接口（与 task-3 / 编排层约定一致）::

    from cbr.agents import (
        build_role_agent,      # 单角色
        build_role_agents,     # 三角色（编排层最常用）
        build_single_agent,    # P3 单智能体基线
        RoleAgent,             # 类：.analyze(context) -> AgentOutput
        SingleAgent,           # 类：.analyze(context) -> SingleAgentResult
    )

Prompt 模板位于 ``configs/prompts/``，可通过 ``role_system_prompt`` /
``cross_check_system_prompt`` / ``single_agent_system_prompt`` 渲染预览。
"""

from __future__ import annotations

from .prompts import (
    build_role_system_prompt,
    cross_check_system_prompt,
    role_system_prompt,
    single_agent_system_prompt,
)
from .role_agent import (
    LEVEL_CN,
    LEVEL_ORDER,
    ROLE_HORIZONS,
    RoleAgent,
    ToolPlanItem,
    build_role_agent,
    build_role_agents,
)
from .single_agent import SingleAgent, SingleAgentResult, build_single_agent

__all__ = [
    "LEVEL_CN",
    "LEVEL_ORDER",
    "ROLE_HORIZONS",
    "RoleAgent",
    "SingleAgent",
    "SingleAgentResult",
    "ToolPlanItem",
    "build_role_agent",
    "build_role_agents",
    "build_role_system_prompt",
    "build_single_agent",
    "cross_check_system_prompt",
    "role_system_prompt",
    "single_agent_system_prompt",
]
