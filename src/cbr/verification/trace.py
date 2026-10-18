"""审计 trace：JSONL 追加写入 + 读回（供核验 / API / UI 使用）。

约定（对应架构 3.6 横切 A）：

- 每次 run 一个文件：``artifacts/traces/<run_id>.jsonl``；
- run_id 形如 ``{mode}_{as_of}_{short_uuid}``；
- 每行一个 :class:`cbr.schemas.TraceEvent`（JSON），字段与 schema 完全一致，
  下游（api / ui / verification）只需 ``read_trace`` 即可解析；
- 同目录另写 ``<run_id>.decision.json``（DecisionCard 快照），便于演示与离线复现。

本模块只依赖标准库 + ``cbr.config`` / ``cbr.schemas``，不反向上游依赖。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from pydantic import ValidationError

from ..config import ROOT
from ..schemas import TraceEvent, utcnow


# --------------------------------------------------------------------------- #
# 路径 / 命名
# --------------------------------------------------------------------------- #
def make_run_id(mode: str, as_of: date | str, *, nonce: str | None = None) -> str:
    """生成 ``{mode}_{as_of}_{short_uuid}`` 形式的 run_id。"""
    as_of_str = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
    token = nonce or uuid4().hex[:8]
    return f"{mode}_{as_of_str}_{token}"


def resolve_path(path: str | Path) -> Path:
    """相对路径按项目根目录解析（与 cbr.config.resolve_path 一致）。"""
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def trace_ref_for(path: str | Path) -> str:
    """把 trace 路径转成可写入 DecisionCard.trace_ref 的字符串（优先项目内相对路径）。"""
    p = resolve_path(path)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


def resolve_trace_path(path_or_ref: str | Path | None) -> Path | None:
    """把 trace_ref / 文件名 / 绝对路径解析为已存在的 trace 文件；找不到返回 None。"""
    if path_or_ref is None:
        return None
    raw = Path(path_or_ref)
    candidates: list[Path]
    if raw.is_absolute():
        candidates = [raw]
    else:
        candidates = [
            ROOT / raw,
            raw,
            ROOT / "artifacts" / "traces" / raw.name,
        ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # pragma: no cover - 权限/非法路径
            continue
    return None


def hash_obj(obj: Any) -> str:
    """规范化 JSON 之后取 sha256 前 16 位，用于 args_hash/result_hash。"""
    try:
        payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - 兜底
        payload = repr(obj)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# TraceWriter
# --------------------------------------------------------------------------- #
class TraceWriter:
    """JSONL 追加写入器。

    用法::

        writer = TraceWriter(run_id="collaborative_2024-08-05_ab12cd34")
        writer.emit(step="R0", action="analysis_start", role="regulator")
        ...
        events = writer.read()
    """

    def __init__(
        self,
        run_id: str,
        trace_dir: str | Path = "artifacts/traces",
        *,
        path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.run_id = run_id
        self._clock = clock or utcnow
        if path is not None:
            resolved = resolve_path(path)
        else:
            resolved = resolve_path(trace_dir) / f"{run_id}.jsonl"
        self.path = resolved
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover - 只读文件系统兜底
            pass
        self._events: list[TraceEvent] = []

    # -- 写入 --------------------------------------------------------------
    def emit(
        self,
        step: str = "",
        action: str = "",
        *,
        role: str | None = None,
        tool: str | None = None,
        args_hash: str | None = None,
        result_hash: str | None = None,
        detail: dict[str, Any] | None = None,
        latency_ms: int = 0,
        tokens: int = 0,
    ) -> TraceEvent:
        """构造并追加一条 trace 事件。"""
        event = TraceEvent(
            run_id=self.run_id,
            ts=self._clock(),
            step=step,
            role=None if role is None else str(role),
            action=action,
            tool=tool,
            args_hash=args_hash,
            result_hash=result_hash,
            detail=detail or {},
            latency_ms=max(int(latency_ms or 0), 0),
            tokens=max(int(tokens or 0), 0),
        )
        return self.write(event)

    def write(self, event: TraceEvent) -> TraceEvent:
        """追加一条已构造的 TraceEvent（run_id 缺省时补齐）。"""
        if not event.run_id:
            event.run_id = self.run_id
        line = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:  # pragma: no cover - 写入失败时保留内存副本，UI 不崩
            pass
        self._events.append(event)
        return event

    # -- 读取 --------------------------------------------------------------
    @property
    def events(self) -> list[TraceEvent]:
        """本次 writer 内存中已写入的事件（按写入顺序）。"""
        return list(self._events)

    def read(self) -> list[TraceEvent]:
        return read_trace(self.path)

    def __len__(self) -> int:
        return len(self._events)

    # -- 产物 --------------------------------------------------------------
    @property
    def decision_path(self) -> Path:
        return self.path.with_suffix(".decision.json")

    @property
    def trace_ref(self) -> str:
        return trace_ref_for(self.path)

    def write_decision(self, data: dict[str, Any]) -> Path:
        """把 DecisionCard 快照写到 trace 同目录，返回路径。"""
        path = self.decision_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover
            pass
        return path

    def close(self) -> None:  # noqa: D401 - 兼容 with 语法
        """保留接口；写入即时落盘，无需显式关闭。"""

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# 读回
# --------------------------------------------------------------------------- #
def read_trace(path: str | Path, *, missing_ok: bool = True) -> list[TraceEvent]:
    """读回 JSONL trace；坏行容忍跳过（UI/API 不因单行损坏整体 500）。"""
    resolved = resolve_trace_path(path)
    if resolved is None:
        if missing_ok:
            return []
        raise FileNotFoundError(f"trace 文件不存在: {path}")
    events: list[TraceEvent] = []
    with resolved.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(TraceEvent.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError, TypeError):
                continue
    return events


def events_to_dicts(events: Iterable[TraceEvent]) -> list[dict[str, Any]]:
    """trace 事件转 dict（供 API 直接返回 JSON）。"""
    return [event.model_dump(mode="json") for event in events]


__all__ = [
    "TraceWriter",
    "make_run_id",
    "read_trace",
    "resolve_trace_path",
    "resolve_path",
    "trace_ref_for",
    "hash_obj",
    "events_to_dicts",
]
