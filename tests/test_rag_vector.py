"""RAG 向量检索层测试（离线，使用默认 hashing 嵌入 + 本地向量库）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from cbr.infra.config import EmbeddingSettings, VectorSettings
from cbr.knowledge._index import Chunk
from cbr.knowledge.vector import (
    HashingEmbedding,
    HybridRetriever,
    NumpyVectorStore,
    build_embedder,
    build_retriever,
    build_vector_store,
)


def _chunk(chunk_id: str, title: str, text: str, publish: str, source: str = "测试", tags=None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=chunk_id.split("-")[0],
        title=title,
        source=source,
        publish_time=dt.date.fromisoformat(publish),
        tags=list(tags or []),
        text=text,
    )


@pytest.fixture()
def chunks() -> list[Chunk]:
    return [
        _chunk("d1-0", "美联储加息与人民币汇率", "美联储加息导致美元走强，人民币汇率承压贬值。", "2024-01-10", tags=["macro"]),
        _chunk("d2-0", "北向资金流出", "北向资金净流出，跨境资本流动压力上升。", "2024-02-15", tags=["flow"]),
        _chunk("d3-0", "国债收益率上行", "十年期国债收益率上行，信用利差走阔。", "2024-08-20", tags=["bond"]),
    ]


def test_hashing_embedding_is_normalized_and_deterministic() -> None:
    embedder = HashingEmbedding(64)
    first = embedder.embed(["美联储加息", "北向资金"])
    second = embedder.embed(["美联储加息", "北向资金"])
    assert first.shape == (2, 64)
    np.testing.assert_allclose(first, second)
    norms = np.linalg.norm(first, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_numpy_store_search_and_roundtrip(tmp_path: Path) -> None:
    store = NumpyVectorStore(8)
    vectors = np.eye(3, 8, dtype=np.float32)
    store.add(["a", "b", "c"], vectors, [{"k": 1}, {"k": 2}, {"k": 3}])
    hits = store.search(np.eye(8, dtype=np.float32)[1], 2)
    assert hits[0][0] == "b"
    assert hits[0][1] == pytest.approx(1.0)

    path = tmp_path / "vectors"
    store.save(path)
    restored = NumpyVectorStore.load(path)
    assert len(restored) == 3
    assert restored.search(vectors[2], 1)[0][0] == "c"


def test_hybrid_retriever_time_filter(chunks: list[Chunk]) -> None:
    retriever = HybridRetriever(chunks)
    hits = retriever.search("北向资金", as_of="2024-01-31", top_k=5)
    ids = [chunk.chunk_id for chunk, _ in hits]
    assert "d2-0" not in ids  # 2024-02-15 晚于 as_of，必须被时点过滤掉
    later = retriever.search("北向资金", as_of="2024-03-01", top_k=5)
    assert any(chunk.chunk_id == "d2-0" for chunk, _ in later)


def test_hybrid_retriever_relevance_and_filters(chunks: list[Chunk]) -> None:
    retriever = HybridRetriever(chunks)
    hits = retriever.search("人民币贬值 汇率", as_of="2024-12-31", top_k=3)
    assert hits, "应能召回相关片段"
    assert hits[0][0].chunk_id == "d1-0"
    # 标签过滤
    tagged = retriever.search("债券 利差", as_of="2024-12-31", top_k=3, tags=["bond"])
    assert all("bond" in chunk.tags for chunk, _ in tagged)
    # top_k 生效
    assert len(retriever.search("资金", as_of="2024-12-31", top_k=1)) == 1


def test_hybrid_retriever_empty_query(chunks: list[Chunk]) -> None:
    assert HybridRetriever(chunks).search("", as_of="2024-12-31") == []


def test_build_retriever_default_local_backend(chunks: list[Chunk]) -> None:
    retriever = build_retriever(chunks)
    assert retriever._indexed is True
    assert retriever.search("国债收益率", as_of="2024-12-31", top_k=1)


def test_build_vector_store_falls_back_for_qdrant() -> None:
    settings = VectorSettings(backend="qdrant", embedding=EmbeddingSettings(dimension=16))
    settings.qdrant.url = "http://127.0.0.1:1"
    store = build_vector_store(settings)  # 无 qdrant-client / 服务不可达 -> 回退本地
    assert isinstance(store, NumpyVectorStore)


def test_build_embedder_falls_back_to_hashing() -> None:
    settings = VectorSettings(embedding=EmbeddingSettings(provider="hashing", dimension=32))
    assert isinstance(build_embedder(settings), HashingEmbedding)
