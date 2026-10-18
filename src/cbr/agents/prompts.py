"""角色智能体 Prompt 构建器。

Prompt 模板存放在 ``configs/prompts/``（见该目录 README），运行时与
``configs/roles.yaml`` 的 :class:`cbr.schemas.RoleSpec` 渲染合并：

- 三角色 system prompt：目标函数 / 关注重点 / 信息权限 / 工具权限 / 阈值 /
  决策损失权重 / 禁止行为 / 输出风格 全部来自 RoleSpec，避免 prompt 与配置漂移；
- 三角色共享 ``common_rules.md``：证据规则、JSON 输出 schema、反幻觉硬约束；
- 交叉验证轮 prompt：给定 peer 证据，复核 1-2 条关键数值主张；
- 单智能体基线 prompt：供 P3 对照实验，一个通用 agent 依次完成三主体任务。

模板缺失时回退到内置最小模板，保证模块可独立测试。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from ..config import ROOT
from ..schemas import Role, RoleSpec

PROMPTS_DIR = ROOT / "configs" / "prompts"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

_ROLE_BRIEF_FALLBACK = """# {{display_name}}（{{role_key}} rolespec 渲染回退模板）

## 目标函数
{{objective}}

## 关注重点
{{focus}}

## 信息权限
{{info_permissions}}

## 工具权限
{{tool_permissions}}

## 预警阈值
{{thresholds}}

## 决策损失权重
{{decision_loss_weights}}

## 禁止行为
{{forbidden_actions}}

## 输出风格
{{output_style}}
"""

_COMMON_FALLBACK = """# 通用证据规则与输出约束

1. 所有数值必须逐字复制证据包中 kind=tool/kind=signal 证据的 value/unit，不得编造；
2. 每条 claim 必须绑定证据包中存在的 evidence_id；
3. numeric claim 的 text 除该数值外不得出现其他数字；
4. text claim 必须绑定知识库（kind=kb）证据；
5. directional claim 必须绑定风险信号证据；
6. 证据不足写入 limitations；禁止给出具体个股买卖建议。
只输出一个符合 RoleAnalysisDraft JSON schema 的 JSON 对象。
"""

_CROSS_FALLBACK = """# 交叉验证（{{display_name}}）

复核 peer_facts 中最多 2 条关键数值证据，输出 findings/summary；
evidence_id 必须来自 peer_facts；verdict ∈ {confirmed, refuted, uncertain}；
不得编造重算数值。
"""

_SINGLE_FALLBACK = """# 单智能体基线

你是通用金融风险分析智能体，依次完成监管、投资、融资三类主体任务。
- 监管主体目标：{{regulator_objective}}
- 投资主体目标：{{investor_objective}}
- 融资主体目标：{{financing_objective}}
输出需遵循通用证据规则与 JSON schema。
"""


def _read_template(name: str, fallback: str) -> str:
    path: Path = PROMPTS_DIR / name
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            if text.strip():
                return text
        except OSError:  # pragma: no cover - 权限/编码异常时回退
            pass
    return fallback


def _render(template: str, values: dict[str, str]) -> str:
    """替换 ``{{key}}`` 占位符；未知占位符原样保留（便于发现配置问题）。"""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(repl, template)


def _bullets(items: Sequence[str], empty: str = "（无）") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return empty
    return "\n".join(f"- {value}" for value in values)


def _joined(items: Sequence[str], empty: str = "（无）") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "、".join(values) if values else empty


def _fmt_mapping(mapping: dict[str, float], *, empty: str = "（无）") -> str:
    if not mapping:
        return empty
    return "、".join(f"{key}={float(value):g}" for key, value in mapping.items())


def spec_values(spec: RoleSpec) -> dict[str, str]:
    """把 RoleSpec 渲染为 prompt 占位符取值。"""

    return {
        "display_name": spec.display_name,
        "role_key": spec.role.value,
        "role": spec.role.value,
        "objective": spec.objective.strip(),
        "focus": _bullets(spec.focus),
        "info_permissions": _joined(spec.info_permissions),
        "tool_permissions": _joined(spec.tool_permissions),
        "thresholds": _fmt_mapping(spec.thresholds),
        "decision_loss_weights": _fmt_mapping(spec.decision_loss_weights),
        "forbidden_actions": _bullets(spec.forbidden_actions),
        "output_style": spec.output_style.strip(),
    }


# --------------------------------------------------------------------------- #
# System prompts
# --------------------------------------------------------------------------- #
def role_system_prompt(spec: RoleSpec) -> str:
    """三角色 system prompt：角色简报 + 共享证据规则/输出 schema。"""

    values = spec_values(spec)
    role_brief = _render(_read_template(f"{spec.role.value}.md", _ROLE_BRIEF_FALLBACK), values)
    common = _render(_read_template("common_rules.md", _COMMON_FALLBACK), values)
    header = (
        f"# 角色设定\n你是 CBR-MAW 跨境金融风险多智能体协同预警系统中的"
        f"「{spec.display_name}」（role={spec.role.value}）。"
        "系统唯一共同预警目标是跨境金融市场压力高位状态；"
        "你与其他主体智能体共享同一基础风险信号，差异体现在目标函数、信息/工具权限、"
        "阈值与决策损失权重。"
    )
    separator = "\n\n---\n\n"
    return separator.join([header, role_brief, common])


# 语义别名：便于外部按 "build_*" 命名调用
def build_role_system_prompt(spec: RoleSpec) -> str:
    return role_system_prompt(spec)


def cross_check_system_prompt(spec: RoleSpec) -> str:
    """交叉验证轮 system prompt。"""

    values = spec_values(spec)
    template = _read_template("cross_validation.md", _CROSS_FALLBACK)
    header = (
        f"# 交叉验证任务\n你是 CBR-MAW 系统中的「{spec.display_name}」"
        f"（role={spec.role.value}），本轮负责复核共享黑板上其他主体的关键证据。"
    )
    return "\n\n---\n\n".join([header, _render(template, values)])


def single_agent_system_prompt(specs: Sequence[RoleSpec] | dict[Role, RoleSpec]) -> str:
    """单智能体基线 system prompt（P3 对照实验用）。"""

    spec_map: dict[Role, RoleSpec] = (
        dict(specs) if isinstance(specs, dict) else {spec.role: spec for spec in specs}
    )
    values = {
        "regulator_objective": spec_map[Role.REGULATOR].objective.strip()
        if Role.REGULATOR in spec_map
        else "监测系统性风险与跨市场外溢。",
        "investor_objective": spec_map[Role.INVESTOR].objective.strip()
        if Role.INVESTOR in spec_map
        else "控制组合尾部损失与回撤。",
        "financing_objective": spec_map[Role.FINANCING].objective.strip()
        if Role.FINANCING in spec_map
        else "评估融资成本与再融资风险。",
    }
    template = _read_template("single_agent.md", _SINGLE_FALLBACK)
    common = _render(_read_template("common_rules.md", _COMMON_FALLBACK), values)
    header = (
        "# 单智能体基线\n你是 CBR-MAW 的通用金融风险分析智能体；"
        "在一个会话中依次完成监管、投资、融资三类主体任务，不依赖其他智能体。"
    )
    return "\n\n---\n\n".join([header, _render(template, values), common])


# --------------------------------------------------------------------------- #
# User prompts
# --------------------------------------------------------------------------- #
_ROLE_USER_TEMPLATE = """# 本次任务

角色视角：{display_name}（role={role_key}）
分析时点 as_of（严格遵守，只允许使用此前的信息）：{as_of}
实验模式：{mode}
协同轮次：{round_label}
任务说明：{task}

# 共享风险信号（唯一共同风险锚，由 P1 多模态融合模型给出）

{signal_text}

# 已获取证据（编号 → 内容摘要；只能引用这些编号）

{evidence_text}

# 交叉验证材料（如非空，仅为复核参考，不是你的新证据）

{peer_text}

# 输出要求

1. 只输出一个 JSON 对象，字段严格符合 system 中给出的 JSON schema；不要输出 markdown 代码块。
2. claims 3-6 条；numeric claim 的 value/unit 必须逐字抄录证据包，text 只能引用 KB 证据，
   directional 必须绑定信号证据；每条 claim 都要有 evidence_ids。
3. 不得输出证据包之外的数字/日期/来源；证据不足时写入 limitations。
4. recommendation 必须体现本角色目标函数，并遵守禁止行为。
5. 机器可读证据包（含全部允许引用的 evidence_id 与数值）：

{packet_text}
"""

_CROSS_USER_TEMPLATE = """# 本次任务：交叉验证

角色视角：{display_name}（role={role_key}）
分析时点 as_of：{as_of}
协同轮次：R{round_no}（交叉验证）

# 待复核的 peer 证据（只能引用其中 evidence_id）

{peer_text}

# 本角色已掌握的证据（仅用于口径对照，不得作为 peer 证据引用）

{own_evidence_text}

# 输出要求

只输出一个 JSON 对象：{{"findings": [...], "summary": "..."}}；
findings 最多 2 条，evidence_id 必须来自上面的 peer 证据，不得编造重算数值。

{packet_text}
"""


def _round_label(round_no: int) -> str:
    if round_no <= 0:
        return "R0 独立分析（本轮不引用其他主体结论）"
    return f"R{round_no} 交叉验证/修订"


def role_user_prompt(
    spec: RoleSpec,
    *,
    as_of: str,
    mode: str,
    round_no: int = 0,
    task: str = "",
    signal_text: str = "",
    evidence_text: str = "",
    peer_text: str = "",
    packet_text: str = "",
) -> str:
    """角色分析 user prompt（含人类可读摘要 + 机器可读证据包）。"""

    return _ROLE_USER_TEMPLATE.format(
        display_name=spec.display_name,
        role_key=spec.role.value,
        as_of=as_of,
        mode=mode,
        round_label=_round_label(round_no),
        task=task.strip() or f"基于共享风险信号与已获取证据，给出{spec.display_name}的风险评估与建议。",
        signal_text=signal_text.strip() or "（无信号摘要）",
        evidence_text=evidence_text.strip() or "（无可用证据）",
        peer_text=peer_text.strip() or "（无：本轮为独立分析）",
        packet_text=packet_text.strip() or "（无证据包）",
    )


def cross_check_user_prompt(
    spec: RoleSpec,
    *,
    as_of: str,
    round_no: int,
    peer_text: str = "",
    own_evidence_text: str = "",
    packet_text: str = "",
) -> str:
    """交叉验证 user prompt。"""

    return _CROSS_USER_TEMPLATE.format(
        display_name=spec.display_name,
        role_key=spec.role.value,
        as_of=as_of,
        round_no=max(1, int(round_no)),
        peer_text=peer_text.strip() or "（无 peer 证据）",
        own_evidence_text=own_evidence_text.strip() or "（无）",
        packet_text=packet_text.strip() or "（无证据包）",
    )


# --------------------------------------------------------------------------- #
# 辅助摘要渲染（供 RoleAgent 组装 prompt）
# --------------------------------------------------------------------------- #
_HORIZON_WORDS = {5: "近端", 10: "中期", 20: "远端"}


def horizon_word(horizon: int) -> str:
    """把预测窗口转成不含数字的中文词，避免 prompt/结论中出现无法核验的孤立数字。"""

    return _HORIZON_WORDS.get(int(horizon), f"第{int(horizon)}期")


def signal_summary_text(signal, *, role_horizon: int) -> str:  # noqa: ANN001 - 避免循环 imports
    """渲染共享风险信号摘要（用于 user prompt）。"""

    horizons = getattr(signal, "horizons", {}) or {}
    parts = [
        f"{horizon_word(h)}（{int(h)} 日）高压力概率 {float(p):.3f}"
        for h, p in sorted(horizons.items(), key=lambda item: int(item[0]))
    ]
    lines = [f"- 模型版本：{getattr(signal, 'model_version', 'unknown')}"]
    lines.append(f"- 预测窗口概率：" + "；".join(parts) if parts else "- 预测窗口概率：（无）")
    level = getattr(signal, "level", None)
    lines.append(f"- 信号等级：{getattr(level, 'value', level)}")
    percentile = getattr(signal, "percentile", None)
    if percentile is not None:
        lines.append(f"- 历史分位：{float(percentile):.3f}")
    drivers = getattr(signal, "drivers", []) or []
    if drivers:
        driver_text = "；".join(
            f"{getattr(d, 'factor', '?')}（贡献 {float(getattr(d, 'contribution', 0.0)):.3f}，"
            f"方向 {getattr(d, 'direction', 'up')}）"
            for d in drivers[:3]
        )
        lines.append(f"- 主要驱动因子：{driver_text}")
    lines.append(
        f"- 本角色采用的判定窗口：{horizon_word(role_horizon)}（{int(role_horizon)} 日）"
    )
    return "\n".join(lines)


def evidence_summary_text(evidence_items: Sequence, *, limit: int = 12) -> str:  # noqa: ANN001
    """渲染证据列表摘要（编号 → 内容）。"""

    if not evidence_items:
        return "（无可用证据）"
    lines: list[str] = []
    for item in evidence_items[:limit]:
        kind = getattr(getattr(item, "kind", None), "value", getattr(item, "kind", "?"))
        evidence_id = getattr(item, "evidence_id", "?")
        title = str(getattr(item, "title", "") or "").strip()
        value = getattr(item, "value", None)
        unit = getattr(item, "unit", None)
        summary = str(getattr(item, "summary", "") or "").strip()
        detail = title + ("：" + summary if summary else "")
        if value is not None:
            detail += f"（数值={value}" + (f" {unit}" if unit else "") + "）"
        lines.append(f"- [{kind}] {evidence_id} — {detail}".strip())
    if len(evidence_items) > limit:
        lines.append(f"- ……共 {len(evidence_items)} 条证据，其余略")
    return "\n".join(lines)


def peer_evidence_summary_text(evidence_items: Sequence, *, limit: int = 6) -> str:  # noqa: ANN001
    """渲染 peer 证据摘要（交叉验证用）。"""

    if not evidence_items:
        return "（无）"
    lines: list[str] = []
    for item in evidence_items[:limit]:
        evidence_id = getattr(item, "evidence_id", "?")
        title = str(getattr(item, "title", "") or "").strip()
        value = getattr(item, "value", None)
        unit = getattr(item, "unit", None)
        source = getattr(item, "source", None)
        source_name = getattr(source, "name", None) or "unknown"
        produced_by = getattr(item, "produced_by", "unknown")
        detail = f"- {evidence_id}（{title or '证据'}，来源={source_name}，产出={produced_by}）"
        if value is not None:
            detail += f"，数值={value}" + (f" {unit}" if unit else "")
        lines.append(detail)
    if len(evidence_items) > limit:
        lines.append(f"- ……共 {len(evidence_items)} 条 peer 证据，其余略")
    return "\n".join(lines)
