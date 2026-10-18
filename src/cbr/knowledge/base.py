"""时点过滤知识库：BM25 检索 + 元数据过滤 + Evidence(kind=KB) 构造。

核心约束（架构 3.3 / 3.6）：
- 检索**强制** ``publish_time <= as_of``（时点过滤在知识库层执行，工具层再做一次）；
- 每个返回片段携带 ``chunk_id / doc_id / publish_time / source / url / hash``，
  供引文核验（P2 证据准确率）映射到原文；
- 检索结果按 ``(-score, chunk_id)`` 排序，保证同一 query/as_of 完全可复现。
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..schemas import Evidence, EvidenceKind, SourceRef
from ._index import Chunk, bm25_scores, build_bm25_stats, tokenize
from .build import (
    Document,
    build_corpus_index,
    build_manifest,
    read_index,
    write_index,
)

SCORE_DECIMALS = 10


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise TypeError(f"as_of must be date/datetime/ISO string, got {type(value)!r}")


def _sanitize(identifier: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in identifier)


class KnowledgeBaseImpl:
    """BM25 时点知识库实现（满足 ``cbr.contracts.KnowledgeBase`` 协议）。"""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        stats: Mapping[str, Any],
        manifest: Mapping[str, Any],
        *,
        documents: Sequence[Document] = (),
        index_dir: str | Path | None = None,
    ) -> None:
        self._chunks: list[Chunk] = list(chunks)
        self._stats: dict[str, Any] = dict(stats)
        self._manifest: dict[str, Any] = dict(manifest)
        self._documents: list[Document] = list(documents)
        self.index_dir = Path(index_dir) if index_dir is not None else None
        self._by_doc: dict[str, list[Chunk]] = {}
        for chunk in self._chunks:
            self._by_doc.setdefault(chunk.doc_id, []).append(chunk)

    # -- 构造/持久化 ------------------------------------------------------
    @classmethod
    def from_corpus(
        cls,
        corpus_dir: str | Path,
        *,
        chunk_size: int = 240,
        chunk_overlap: int = 48,
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
        index_version: str = "kb-bm25-v1",
    ) -> "KnowledgeBaseImpl":
        documents, chunks, corpus_hash = build_corpus_index(
            corpus_dir, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        stats = build_bm25_stats(chunks, k1=bm25_k1, b=bm25_b)
        manifest = build_manifest(
            documents=documents,
            chunks=chunks,
            corpus_hash=corpus_hash,
            index_version=index_version,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
        )
        return cls(chunks, stats, manifest, documents=documents)

    @classmethod
    def load(cls, index_dir: str | Path) -> "KnowledgeBaseImpl":
        documents, chunks, stats, manifest = read_index(index_dir)
        return cls(
            chunks, stats, manifest, documents=documents, index_dir=index_dir
        )

    def save(self, index_dir: str | Path) -> Path:
        """把当前索引写盘（scripts/build_knowledge.py 使用）。"""
        manifest = dict(self._manifest)
        manifest["n_chunks"] = len(self._chunks)
        manifest["n_docs"] = len(self._by_doc)
        return write_index(
            index_dir,
            documents=self._documents,
            chunks=self._chunks,
            stats=self._stats,
            manifest=manifest,
        )

    # -- 协议方法 ---------------------------------------------------------
    def count(self) -> int:
        """索引中的片段（chunk）总数。"""
        return len(self._chunks)

    def n_docs(self) -> int:
        return len(self._by_doc)

    def stats(self) -> dict[str, Any]:
        publish_times = sorted(
            doc["publish_time"] for doc in self._manifest.get("documents", [])
        )
        return {
            "n_docs": self.n_docs(),
            "n_chunks": len(self._chunks),
            "index_version": self._manifest.get("index_version"),
            "corpus_hash": self._manifest.get("corpus_hash"),
            "publish_time_min": publish_times[0] if publish_times else None,
            "publish_time_max": publish_times[-1] if publish_times else None,
            "avg_chunk_chars": round(
                sum(len(chunk.text) for chunk in self._chunks) / max(1, len(self._chunks)), 2
            ),
        }

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def documents(self) -> list[Document]:
        return list(self._documents)

    def search(
        self,
        query: str,
        as_of: date | datetime | str,
        top_k: int = 5,
        tags: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[Evidence]:
        """时点过滤检索：只返回 ``publish_time <= as_of`` 的片段。"""
        query = (query or "").strip()
        if not query:
            return []
        day = _as_date(as_of)
        top_k = max(1, int(top_k))

        candidates: list[Chunk] = []
        wanted_tags = {str(tag).lower() for tag in (tags or [])}
        wanted_sources = {str(src).lower() for src in (sources or [])}
        for chunk in self._chunks:
            if chunk.publish_time > day:  # 强制时点过滤
                continue
            if wanted_tags and not wanted_tags.issubset({tag.lower() for tag in chunk.tags}):
                continue
            if wanted_sources and chunk.source.lower() not in wanted_sources:
                continue
            candidates.append(chunk)
        if not candidates:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = bm25_scores(query_tokens, candidates, self._stats)
        ranked = sorted(
            zip(candidates, scores),
            key=lambda item: (-round(item[1], SCORE_DECIMALS), item[0].chunk_id),
        )
        hits = [(chunk, score) for chunk, score in ranked if score > 0.0][:top_k]
        return [self._chunk_to_evidence(chunk, score, day) for chunk, score in hits]

    # -- Evidence 构造 ----------------------------------------------------
    def _chunk_to_evidence(self, chunk: Chunk, score: float, as_of: date) -> Evidence:
        evidence_id = f"ev_kb_{_sanitize(chunk.doc_id)}_{chunk.chunk_index:03d}"
        release_time = datetime.combine(chunk.publish_time, time.min)
        source_ref = SourceRef(
            name=chunk.source,
            url=chunk.url,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            release_time=release_time,
            extra={"section": chunk.section, "chunk_hash": chunk.hash},
        )
        payload = {
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "title": chunk.title,
            "source": chunk.source,
            "publish_time": chunk.publish_time.isoformat(),
            "url": chunk.url,
            "tags": list(chunk.tags),
            "section": chunk.section,
            "score": round(float(score), SCORE_DECIMALS),
            "text": chunk.text,
            "content_hash": chunk.hash,
        }
        return Evidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.KB,
            as_of=as_of,
            title=chunk.title,
            summary=f"{chunk.section}：{chunk.text[:120]}",
            payload=payload,
            unit=None,
            value=None,
            source=source_ref,
            tool=None,
            produced_by="knowledge_base",
            citations=[source_ref],
            verified=None,
            hash=chunk.hash,
        )


# --------------------------------------------------------------------------- #
# 构建辅助（供 scripts/build_knowledge.py 复用）
# --------------------------------------------------------------------------- #
def build_knowledge_index(
    corpus_dir: str | Path,
    index_dir: str | Path,
    *,
    chunk_size: int = 240,
    chunk_overlap: int = 48,
    bm25_k1: float = 1.5,
    bm25_b: float = 0.75,
    index_version: str = "kb-bm25-v1",
) -> dict[str, Any]:
    """构建并写盘索引，返回 manifest。"""
    kb = KnowledgeBaseImpl.from_corpus(
        corpus_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        index_version=index_version,
    )
    kb.save(index_dir)
    return kb.manifest


__all__ = [
    "Document",
    "KnowledgeBaseImpl",
    "build_knowledge_index",
]
