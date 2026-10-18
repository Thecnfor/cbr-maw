"""knowledge_search：时点过滤的知识库检索工具。

调用 ``KnowledgeBase.search(query, as_of, top_k)``，返回带 chunk_id / publish_time
的 KB 证据；工具层再做一次 ``publish_time <= as_of`` 防御性校验（双保险）。
"""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from ..schemas import Evidence, EvidenceKind, SourceRef
from ._numeric import r
from .base import BaseTool, ToolError, ToolOutput, normalize_as_of

_PUBLISH_TIME_ERROR = "point-in-time violation in knowledge base search results"


class KnowledgeSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)
    tags: list[str] | None = None


def _parse_publish_time(value: object) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = "时点过滤的知识库检索（政策/方法学/事件复盘），返回 chunk_id 可核验引文"
    unit = None
    params_model = KnowledgeSearchParams

    def _call_search(
        self, query: str, as_of: date, top_k: int, tags: list[str] | None
    ) -> list[Evidence]:
        if self.kb is None:
            raise ToolError("knowledge base is not configured for knowledge_search tool")
        try:
            return list(self.kb.search(query, as_of, top_k, tags=tags))
        except TypeError:
            # 兼容只实现 KnowledgeBase 协议（search(query, as_of, top_k)）的知识库实现
            results = list(self.kb.search(query, as_of, top_k))
            if tags:
                wanted = {str(t).lower() for t in tags}
                results = [
                    ev
                    for ev in results
                    if wanted.issubset(
                        {str(t).lower() for t in (ev.payload or {}).get("tags", [])}
                    )
                ]
            return results

    def compute(self, as_of: date, params: KnowledgeSearchParams) -> ToolOutput:
        results = self._call_search(params.query, as_of, params.top_k, params.tags)

        clean: list[Evidence] = []
        dropped_future = 0
        for ev in results:
            publish = _parse_publish_time((ev.payload or {}).get("publish_time"))
            if publish is None and ev.source.release_time is not None:
                publish = normalize_as_of(ev.source.release_time)
            if publish is not None and publish > as_of:
                dropped_future += 1
                continue
            clean.append(ev)

        records: list[dict] = []
        citations: list[SourceRef] = []
        for ev in clean:
            payload = ev.payload or {}
            publish = _parse_publish_time(payload.get("publish_time")) or (
                normalize_as_of(ev.source.release_time)
                if ev.source.release_time is not None
                else None
            )
            record = {
                "evidence_id": ev.evidence_id,
                "chunk_id": payload.get("chunk_id") or ev.source.chunk_id,
                "doc_id": payload.get("doc_id") or ev.source.doc_id,
                "title": payload.get("title") or ev.title,
                "source": payload.get("source") or ev.source.name,
                "publish_time": publish.isoformat() if publish else None,
                "url": payload.get("url") or ev.source.url,
                "tags": list(payload.get("tags") or []),
                "section": payload.get("section"),
                "score": r(payload.get("score")) if payload.get("score") is not None else None,
                "text": payload.get("text", ""),
            }
            records.append(record)
            citations.append(
                SourceRef(
                    name=str(record["source"]),
                    url=record["url"],
                    doc_id=record["doc_id"],
                    chunk_id=record["chunk_id"],
                    release_time=(
                        datetime.combine(publish, time.min) if publish is not None else None
                    ),
                )
            )

        top = records[0] if records else None
        if top is not None:
            summary = (
                f"时点 {as_of} 检索「{params.query}」命中 {len(records)} 个片段；"
                f"top1={top['title']}（{top['publish_time']}，score={top['score']}）。"
            )
        else:
            summary = f"时点 {as_of} 检索「{params.query}」无命中（或全部晚于时点被过滤）。"

        data = {
            "query": params.query,
            "as_of": as_of.isoformat(),
            "top_k": params.top_k,
            "tags": params.tags,
            "result_count": len(records),
            "dropped_future": dropped_future,
            "results": records,
            "unit_map": {},
        }
        return ToolOutput(
            data=data,
            unit=None,
            value=None,
            title=f"知识检索：{params.query}",
            summary=summary,
            citations=citations,
            kind=EvidenceKind.KB,
        )
