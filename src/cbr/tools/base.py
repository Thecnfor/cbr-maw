"""确定性工具基类、工具注册表、角色权限矩阵与统一证据构造。

依赖（跨模块契约，不得在本模块内修改）：
- ``cbr.schemas``: ToolResult / Evidence / ToolRef / SourceRef / Role / RoleSpec
- ``cbr.contracts``: Tool / ToolRegistry 协议
- ``configs/roles.yaml``: 权限矩阵唯一来源（每个角色的 tool_permissions）
- ``configs/tools.yaml``: 工具版本与默认参数（由 tools/settings.py 读取）

设计约束（架构 3.3 / 3.6）：
1. 工具只做确定性纯计算，禁止调用 LLM；
2. 相同 ``(工具版本, as_of, 规范化参数)`` 必须产生相同 ``inputs_hash`` /
   ``evidence_id``；相同输入数据必须产生相同 ``evidence.hash``（payload 哈希）；
3. 越权调用返回 ``ok=False`` 的 ToolResult，并写入权限审计事件
   （供横切 A 的"越权阻断次数"指标使用）；
4. 工具内部数据错误用 :class:`ToolError` 显式失败（不返回编造数值）；
   未预期的编程错误直接抛出，便于测试暴露缺陷。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

from ..config import load_role_specs
from ..schemas import (
    Evidence,
    EvidenceKind,
    Role,
    RoleSpec,
    SourceRef,
    ToolRef,
    ToolResult,
    utcnow,
)

TOOL_LAYER_VERSION = "tools-v1"


# --------------------------------------------------------------------------- #
# 规范化哈希（确定性）
# --------------------------------------------------------------------------- #
def _json_default(obj: Any) -> Any:
    """JSON 序列化兜底：日期、Pydantic、numpy 标量/数组。"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if hasattr(obj, "tolist"):  # numpy array
        return obj.tolist()
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    raise TypeError(f"object of type {type(obj)!r} is not canonical-JSON serializable")


def canonical_json(obj: Any) -> str:
    """规范化 JSON：键排序、紧凑分隔符、保留中文，保证哈希可复现。"""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def to_native(obj: Any) -> Any:
    """递归转换为可 JSON 序列化的原生 Python 结构（numpy -> float/list 等）。"""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, BaseModel):
        return to_native(obj.model_dump(mode="json"))
    if isinstance(obj, Mapping):
        return {str(k): to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_native(v) for v in obj]
    if hasattr(obj, "tolist"):  # numpy array / scalar
        return to_native(obj.tolist())
    if hasattr(obj, "item"):
        return to_native(obj.item())
    return obj


def normalize_as_of(value: date | datetime | str) -> date:
    """把调用方传入的时点统一为 ``date``（时点层只用日粒度）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise TypeError(f"as_of 必须是 date/datetime/ISO 字符串，收到 {type(value)!r}")


def compute_inputs_hash(
    tool_name: str,
    tool_version: str,
    as_of: date,
    params: Mapping[str, Any],
) -> str:
    """sha256(规范化 JSON{工具名, 版本, as_of, 规范化参数})。"""
    payload = {
        "tool": tool_name,
        "version": tool_version,
        "as_of": as_of.isoformat(),
        "params": to_native(dict(params)),
    }
    return sha256_text(canonical_json(payload))


def build_evidence(
    *,
    tool_name: str,
    tool_version: str,
    as_of: date,
    inputs_hash: str,
    elapsed_ms: int,
    data: Mapping[str, Any],
    unit: str | None,
    value: float | None,
    title: str,
    summary: str,
    citations: Sequence[SourceRef] | None = None,
    kind: EvidenceKind = EvidenceKind.TOOL,
    evidence_id: str | None = None,
    source: SourceRef | None = None,
) -> Evidence:
    """统一构造 Evidence（数值证据的原子单位）。

    约定：
    - ``evidence_id = ev_tool_<tool>_<YYYYMMDD>_<inputs_hash[:12]>``；
    - ``tool.inputs_hash`` 覆盖 (工具版本, as_of, 参数)，用于重算与冲突仲裁；
    - ``evidence.hash`` = sha256(规范化 payload)，用于核验"数值未被篡改"。
    """
    payload = to_native(dict(data))
    eid = evidence_id or f"ev_tool_{tool_name}_{as_of:%Y%m%d}_{inputs_hash[:12]}"
    src = source or SourceRef(
        name=f"{tool_name}@{tool_version}",
        doc_id=f"{tool_name}:{as_of.isoformat()}:{inputs_hash[:16]}",
    )
    return Evidence(
        evidence_id=eid,
        kind=kind,
        as_of=as_of,
        title=title,
        summary=summary,
        payload=payload,
        unit=unit,
        value=value,
        source=src,
        tool=ToolRef(
            name=tool_name,
            version=tool_version,
            inputs_hash=inputs_hash,
            elapsed_ms=max(0, int(elapsed_ms)),
        ),
        produced_by="tool",
        citations=list(citations or []),
        verified=None,
        hash=sha256_text(canonical_json(payload)),
    )


# --------------------------------------------------------------------------- #
# 异常与输出容器
# --------------------------------------------------------------------------- #
class ToolError(Exception):
    """工具可控失败（数据不足、序列缺失、参数组合不可计算等）。"""


@dataclass
class ToolOutput:
    """工具计算结果：数据和证据由基类统一封装。"""

    data: dict[str, Any]
    unit: str | None = None
    value: float | None = None
    title: str = ""
    summary: str = ""
    citations: list[SourceRef] = field(default_factory=list)
    #: 证据类型：普通工具为 TOOL；forecast 复用共享信号（SIGNAL）；知识检索为 KB
    kind: EvidenceKind = EvidenceKind.TOOL
    #: 复用的证据 id（如共享 RiskSignal.evidence_id）；None 时按工具+inputs_hash 生成
    evidence_id: str | None = None
    source: SourceRef | None = None


# --------------------------------------------------------------------------- #
# 工具基类
# --------------------------------------------------------------------------- #
class BaseTool:
    """确定性金融工具基类：参数校验 -> 纯计算 -> ToolResult + Evidence。"""

    name: str = "base"
    description: str = ""
    unit: str | None = None
    params_model: type[BaseModel] = BaseModel

    def __init__(
        self,
        provider: Any | None = None,
        kb: Any | None = None,
        *,
        version: str = "1.0.0",
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.kb = kb
        self.version = str(version)
        self.defaults: dict[str, Any] = dict(defaults or {})

    # -- 子类实现 ---------------------------------------------------------
    def compute(self, as_of: date, params: Any) -> ToolOutput:  # pragma: no cover
        raise NotImplementedError

    # -- 公共入口 ---------------------------------------------------------
    def run(self, as_of: date | datetime | str, **kwargs: Any) -> ToolResult:
        t0 = time.perf_counter()
        try:
            day = normalize_as_of(as_of)
        except (TypeError, ValueError) as exc:
            return self._failure(
                date.today(), f"invalid as_of: {exc}", _elapsed_ms(t0)
            )

        # 参数合并顺序：显式参数 > configs/tools.yaml 默认值 > 参数模型内置默认值。
        merged: dict[str, Any] = dict(self.defaults)
        merged.update({k: v for k, v in kwargs.items() if v is not None})
        try:
            params = self.params_model(**merged)
        except ValidationError as exc:
            return self._failure(day, f"invalid parameters: {exc.errors()}", _elapsed_ms(t0))

        try:
            output = self.compute(day, params)
        except ToolError as exc:
            return self._failure(day, str(exc), _elapsed_ms(t0))

        data = to_native(output.data)
        elapsed_ms = _elapsed_ms(t0)
        params_norm = to_native(params.model_dump(mode="json"))
        inputs_hash = compute_inputs_hash(self.name, self.version, day, params_norm)
        citations = list(output.citations or [])
        evidence = build_evidence(
            tool_name=self.name,
            tool_version=self.version,
            as_of=day,
            inputs_hash=inputs_hash,
            elapsed_ms=elapsed_ms,
            data=data,
            unit=output.unit if output.unit is not None else self.unit,
            value=output.value,
            title=output.title or f"{self.name} @ {day.isoformat()}",
            summary=output.summary,
            citations=citations,
            kind=output.kind,
            evidence_id=output.evidence_id,
            source=output.source,
        )
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=day,
            ok=True,
            data=data,
            unit=output.unit if output.unit is not None else self.unit,
            evidence=evidence,
            citations=citations,
            elapsed_ms=elapsed_ms,
            error=None,
        )

    # -- 数据访问辅助 -----------------------------------------------------
    def _history(self, series_id: str, as_of: date, lookback: int) -> list[tuple[date, float]]:
        """读取时点历史序列：显式校验 date <= as_of（PIT 双保险）。"""
        if self.provider is None:
            raise ToolError("data provider is not configured for this tool instance")
        if not series_id:
            raise ToolError("series_id 不能为空")
        rows = self.provider.history(series_id, as_of, lookback) or []
        out: dict[date, float] = {}
        for row in rows:
            try:
                day = normalize_as_of(row["date"])
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if day > as_of:
                raise ToolError(
                    f"point-in-time violation: series {series_id} rows contain {day} > as_of {as_of}"
                )
            if value != value or value in (float("inf"), float("-inf")):
                continue
            out[day] = value
        items = sorted(out.items())
        if not items:
            raise ToolError(f"no available history for series {series_id} as of {as_of}")
        return items[-lookback:] if lookback > 0 else items

    def _series_param(self, explicit: str | None, key: str, default_map: Mapping[str, str]) -> str:
        """解析序列 id：显式参数 > configs/tools.yaml defaults > 内置默认映射。"""
        if explicit:
            return explicit
        if key in self.defaults and self.defaults[key]:
            return str(self.defaults[key])
        if key in default_map:
            return default_map[key]
        raise ToolError(f"no series_id configured for {key}")

    # -- 失败结果 ---------------------------------------------------------
    def _failure(self, as_of: date, error: str, elapsed_ms: int) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=as_of,
            ok=False,
            data={},
            unit=self.unit,
            evidence=None,
            citations=[],
            elapsed_ms=max(0, int(elapsed_ms)),
            error=error,
        )

    # -- 元信息 -----------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "unit": self.unit,
            "defaults": to_native(self.defaults),
            "params_schema": self.params_model.model_json_schema(),
        }


def _elapsed_ms(t0: float) -> int:
    return max(0, int(round((time.perf_counter() - t0) * 1000.0)))


# --------------------------------------------------------------------------- #
# 权限审计事件
# --------------------------------------------------------------------------- #
class AuditEvent(BaseModel):
    """越权/调用审计事件（供 VerificationReport.permission_violations 计数）。"""

    event_id: str
    event_type: str = "permission_denied"
    role: str
    tool_name: str
    as_of: date
    reason: str = ""
    created_at: datetime = None  # type: ignore[assignment]

    def model_post_init(self, __context: Any) -> None:  # noqa: D401
        if self.created_at is None:
            self.created_at = utcnow()


# --------------------------------------------------------------------------- #
# 工具注册表 + 角色权限矩阵
# --------------------------------------------------------------------------- #
class ToolRegistryImpl:
    """工具注册表：按 roles.yaml 的 tool_permissions 做 allow/deny 与审计。"""

    def __init__(
        self,
        tools: Iterable[BaseTool],
        role_specs: Mapping[Role, RoleSpec] | None = None,
        *,
        default_deny: bool = True,
        audit_sink: Callable[[AuditEvent], None] | None = None,
        registry_version: str = TOOL_LAYER_VERSION,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool
        self._role_specs: dict[Role, RoleSpec] = dict(
            role_specs if role_specs is not None else load_role_specs()
        )
        self._permissions: dict[Role, set[str]] = {
            role: set(spec.tool_permissions) for role, spec in self._role_specs.items()
        }
        self.default_deny = bool(default_deny)
        self.registry_version = registry_version
        self._audit_events: list[AuditEvent] = []
        self._audit_sink = audit_sink

    # -- ToolRegistry 协议 ------------------------------------------------
    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name!r}; available={sorted(self._tools)}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def allow(self, role: Role | str, tool_name: str) -> bool:
        try:
            role_enum = role if isinstance(role, Role) else Role(role)
        except ValueError:
            return False  # 未知角色一律拒绝
        if tool_name not in self._tools:
            return False
        perms = self._permissions.get(role_enum)
        if perms is None:
            return not self.default_deny
        return tool_name in perms

    # -- 扩展：带权限校验的执行入口 --------------------------------------
    def run(
        self, role: Role | str, tool_name: str, as_of: date | datetime | str, **kwargs: Any
    ) -> ToolResult:
        """权限校验后执行工具；越权返回 disallowed 结果并写审计事件。"""
        try:
            day = normalize_as_of(as_of)
        except (TypeError, ValueError):
            day = date.today()
        role_name = role.value if isinstance(role, Role) else str(role)

        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                version="unknown",
                as_of=day,
                ok=False,
                data={"unknown_tool": True, "available": self.names()},
                error=f"unknown tool: {tool_name!r}",
            )

        if not self.allow(role, tool_name):
            event = self._record_permission_denied(role_name, tool_name, day)
            tool = self._tools[tool_name]
            return ToolResult(
                tool_name=tool_name,
                version=tool.version,
                as_of=day,
                ok=False,
                data={
                    "disallowed": True,
                    "role": role_name,
                    "tool": tool_name,
                    "audit_event_id": event.event_id,
                },
                unit=tool.unit,
                evidence=None,
                citations=[],
                elapsed_ms=0,
                error=f"disallowed: role={role_name} is not permitted to call tool={tool_name}",
            )

        return self._tools[tool_name].run(day, **kwargs)

    # -- 审计 -------------------------------------------------------------
    def _record_permission_denied(self, role_name: str, tool_name: str, day: date) -> AuditEvent:
        event = AuditEvent(
            event_id=f"audit_{len(self._audit_events) + 1:04d}_{tool_name}_{role_name}_{day:%Y%m%d}",
            event_type="permission_denied",
            role=role_name,
            tool_name=tool_name,
            as_of=day,
            reason=f"role={role_name} 无 {tool_name} 调用权限（configs/roles.yaml）",
        )
        self._audit_events.append(event)
        if self._audit_sink is not None:
            self._audit_sink(event)
        return event

    @property
    def audit_events(self) -> list[AuditEvent]:
        return list(self._audit_events)

    def permissions_table(self) -> dict[str, list[str]]:
        """角色 -> 允许工具列表（来自 roles.yaml）。"""
        return {role.value: sorted(tools) for role, tools in sorted(
            self._permissions.items(), key=lambda item: item[0].value
        )}

    def describe(self) -> list[dict[str, Any]]:
        return [self._tools[name].describe() for name in self.names()]

    # -- 便捷访问 ---------------------------------------------------------
    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def tool_version(self, name: str) -> str:
        return self.get(name).version
