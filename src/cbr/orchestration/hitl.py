"""人工接管（HITL）接口（架构 3.5 / 3.6 的“未解决冲突、高风险、越权、核验失败”）。

设计：

- :class:`HITLQueue` 维护待处理项队列，支持 ``approve / reject / override``，
  所有动作写入对应 run 的审计 trace；
- 同步 ``run()`` 默认没有人工在线，因此编排器在 R5 调用 :meth:`HITLQueue.auto_process`
  按规则自动处理（``escalate`` = 保留并标记需人工复核，``record`` = 仅记录），
  并在 DecisionCard.final_advice / CoordinationStats 中体现 escalated；
- 人工后续可通过 ``approve/reject/override`` 覆盖自动结论，同样写 trace。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

from ..schemas import utcnow

HITLKind = Literal[
    "high_risk",
    "unresolved_conflict",
    "permission_violation",
    "verification_failure",
    "budget_exceeded",
]
HITLStatus = Literal["pending", "approved", "rejected", "overridden", "auto_processed"]
HITLAction = Literal["approve", "reject", "override"]

#: 无人工在线时的默认自动策略：escalate = 保留并标记需人工复核。
DEFAULT_AUTO_POLICIES: dict[str, str] = {
    "high_risk": "escalate",
    "unresolved_conflict": "escalate",
    "permission_violation": "escalate",
    "verification_failure": "escalate",
    "budget_exceeded": "record",
}

_AUTO_RESOLUTIONS: dict[str, str] = {
    "escalate": "无人工在线：保留该项并在决策卡标记「需人工复核」（escalated）",
    "record": "无人工在线：仅记录，不阻塞决策卡输出",
}

_ACTION_RESOLUTIONS: dict[str, str] = {
    "approve": "人工批准：维持现有结论",
    "reject": "人工驳回：相关结论不计入最终建议",
    "override": "人工覆盖：按人工给定内容替换相关结论",
}


class HITLItem(BaseModel):
    """一个人工接管事项。"""

    item_id: str
    run_id: str = ""
    kind: HITLKind
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: HITLStatus = "pending"
    auto_policy: str = ""
    resolution: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    handled_at: datetime | None = None

    @property
    def needs_human_review(self) -> bool:
        return self.status == "pending" or self.auto_policy == "escalate"


class HITLQueue:
    """待处理项队列 + 人工结论记录。

    ``trace_factory(run_id) -> TraceWriter`` 用于把人工动作追加到对应 run 的 trace；
    缺省时只更新内存队列（测试/离线场景）。
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        trace_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self._trace_factory = trace_factory
        self._clock = clock or utcnow
        self._items: list[HITLItem] = []
        self._counter = 0

    # -- 入队 / 查询 -------------------------------------------------------
    def enqueue(
        self,
        kind: HITLKind | str,
        summary: str,
        *,
        run_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> HITLItem:
        self._counter += 1
        item = HITLItem(
            item_id=f"hitl_{self._counter:04d}",
            run_id=run_id,
            kind=kind,  # type: ignore[arg-type]
            summary=summary,
            payload=payload or {},
            created_at=self._clock(),
        )
        self._items.append(item)
        self._emit_trace(item, action="hitl", detail={"event": "enqueue", "kind": item.kind, "summary": summary})
        return item

    @property
    def items(self) -> list[HITLItem]:
        return list(self._items)

    def pending(self, run_id: str | None = None) -> list[HITLItem]:
        return [
            item
            for item in self._items
            if item.status == "pending" and (run_id is None or item.run_id == run_id)
        ]

    def needs_review(self, run_id: str | None = None) -> list[HITLItem]:
        return [
            item
            for item in self._items
            if item.needs_human_review and (run_id is None or item.run_id == run_id)
        ]

    def for_run(self, run_id: str) -> list[HITLItem]:
        return [item for item in self._items if item.run_id == run_id]

    def get(self, item_id: str) -> HITLItem | None:
        return next((item for item in self._items if item.item_id == item_id), None)

    # -- 自动处理（无人工在线） --------------------------------------------
    def auto_process(
        self,
        *,
        run_id: str | None = None,
        policies: dict[str, str] | None = None,
    ) -> list[HITLItem]:
        """按默认策略处理 pending 项；返回本轮处理过的项（仍保留在队列中供 UI 展示）。"""
        rules = {**DEFAULT_AUTO_POLICIES, **(policies or {})}
        processed: list[HITLItem] = []
        for item in self.pending(run_id=run_id):
            policy = rules.get(item.kind, "escalate")
            item.status = "auto_processed"
            item.auto_policy = policy
            item.resolution = _AUTO_RESOLUTIONS.get(policy, _AUTO_RESOLUTIONS["escalate"])
            item.handled_at = self._clock()
            processed.append(item)
            self._emit_trace(
                item,
                action="hitl",
                detail={
                    "event": "auto_process",
                    "kind": item.kind,
                    "policy": policy,
                    "escalated": policy == "escalate",
                },
            )
        return processed

    # -- 人工动作 ----------------------------------------------------------
    def approve(self, item_id: str, note: str = "", *, actor: str = "human") -> HITLItem:
        return self._handle(item_id, "approve", note=note, actor=actor)

    def reject(self, item_id: str, note: str = "", *, actor: str = "human") -> HITLItem:
        return self._handle(item_id, "reject", note=note, actor=actor)

    def override(
        self,
        item_id: str,
        replacement: dict[str, Any],
        note: str = "",
        *,
        actor: str = "human",
    ) -> HITLItem:
        return self._handle(item_id, "override", note=note, actor=actor, replacement=replacement)

    def _handle(
        self,
        item_id: str,
        action: HITLAction,
        *,
        note: str = "",
        actor: str = "human",
        replacement: dict[str, Any] | None = None,
    ) -> HITLItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"未知 HITL 事项: {item_id}")
        item.status = {"approve": "approved", "reject": "rejected", "override": "overridden"}[action]  # type: ignore[assignment]
        item.note = note
        item.resolution = _ACTION_RESOLUTIONS[action]
        if replacement is not None:
            item.payload = {**item.payload, "replacement": replacement}
        item.handled_at = self._clock()
        self._emit_trace(
            item,
            action="hitl",
            detail={
                "event": action,
                "kind": item.kind,
                "actor": actor,
                "note": note,
                "replacement": replacement,
            },
        )
        return item

    # -- trace -------------------------------------------------------------
    def _emit_trace(self, item: HITLItem, *, action: str, detail: dict[str, Any]) -> None:
        if self._trace_factory is None or not item.run_id:
            return
        try:
            writer = self._trace_factory(item.run_id)
            if writer is None:
                return
            writer.emit(
                step="HITL",
                action=action,
                role=None,
                detail={**detail, "item_id": item.item_id, "run_id": item.run_id, "status": item.status},
            )
        except Exception:  # pragma: no cover - 审计失败不影响主流程
            pass

    def clear(self) -> None:
        self._items.clear()
        self._counter = 0


__all__ = [
    "HITLItem",
    "HITLQueue",
    "DEFAULT_AUTO_POLICIES",
]
