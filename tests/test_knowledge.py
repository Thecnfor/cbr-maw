"""时点知识库测试。

覆盖：
- 语料规模/元数据完整性/年份覆盖（2018–2025）；
- 切块与索引构建（chunk_id、内容哈希、manifest）；
- BM25 检索返回 Evidence(kind=KB)，携带 chunk_id / publish_time / source；
- **强制时点过滤**：publish_time > as_of 的文档永不返回（含构造的未来文档）；
- 标签元数据过滤、排序合理性、索引持久化往返与过期检测。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from cbr.config import load_settings
from cbr.knowledge import (
    KnowledgeBaseImpl,
    build_knowledge_base,
    build_knowledge_index,
    load_knowledge_settings,
)
from cbr.knowledge._index import Chunk, tokenize
from cbr.knowledge.build import (
    build_chunks,
    chunk_text,
    compute_corpus_hash,
    corpus_stats,
    index_is_fresh,
    load_documents,
)
from cbr.schemas import Evidence, EvidenceKind

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "knowledge" / "corpus"
AS_OF = date(2024, 12, 31)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def documents():
    return load_documents(CORPUS_DIR)


@pytest.fixture(scope="module")
def kb(documents) -> KnowledgeBaseImpl:
    return KnowledgeBaseImpl.from_corpus(CORPUS_DIR, chunk_size=240, chunk_overlap=48)


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def _make_temp_corpus(root: Path, records: list[dict]) -> Path:
    corpus = root / "corpus"
    _write_jsonl(corpus / "docs.jsonl", records)
    return corpus


# --------------------------------------------------------------------------- #
# 语料元数据
# --------------------------------------------------------------------------- #
def test_corpus_has_at_least_20_metadata_complete_docs(documents) -> None:
    assert len(documents) >= 20
    doc_ids = [doc.doc_id for doc in documents]
    assert len(doc_ids) == len(set(doc_ids))
    for doc in documents:
        assert doc.title.strip()
        assert doc.source.strip()
        assert isinstance(doc.publish_time, datetime)
        assert doc.url and doc.url.startswith("http")
        assert doc.tags, f"{doc.doc_id} 缺少 tags"
        assert doc.text.strip()
        assert doc.section.strip()


def test_corpus_covers_2018_to_2025() -> None:
    stats = corpus_stats(CORPUS_DIR)
    assert stats["n_docs"] >= 20
    assert stats["publish_time_min"] <= "2018-12-31"
    assert stats["publish_time_max"] >= "2025-01-01"
    # 至少覆盖政策/事件复盘/方法学三类内容
    tags = set(stats["tags"])
    assert {"历史事件", "方法学"} & tags
    assert any("货币" in tag or "政策" in tag for tag in tags)


def test_corpus_self_written_content_not_boilerplate(documents) -> None:
    # 自有改写语料应具有足够的信息量（每篇至少 120 字），且文本互不重复
    texts = [doc.text for doc in documents]
    assert all(len(text) >= 120 for text in texts)
    assert len(set(texts)) == len(texts)


# --------------------------------------------------------------------------- #
# 切块 / 索引
# --------------------------------------------------------------------------- #
def test_chunking_produces_valid_chunks(documents) -> None:
    chunks = build_chunks(documents, chunk_size=240, chunk_overlap=48)
    assert len(chunks) >= len(documents)  # 每篇至少一块
    doc_ids = {doc.doc_id for doc in documents}
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    assert len(chunk_ids) == len(set(chunk_ids))
    for chunk in chunks:
        assert chunk.doc_id in doc_ids
        assert chunk.chunk_id == f"{chunk.doc_id}#c{chunk.chunk_index:03d}"
        assert isinstance(chunk.publish_time, date)
        assert chunk.text.strip()
        assert len(chunk.hash) == 64
        assert chunk.title in chunk.index_text
        assert tokenize(chunk.index_text)
    # 每篇文档至少产生一块
    assert {chunk.doc_id for chunk in chunks} == doc_ids


def test_chunk_text_respects_target_size_and_overlap() -> None:
    text = "。".join(f"第{i}句跨境金融风险监测要点，包含北向资金与汇率信息" for i in range(60)) + "。"
    pieces = chunk_text(text, chunk_size=120, chunk_overlap=36)
    assert len(pieces) > 1
    assert all(piece.strip() for piece in pieces)
    assert max(len(piece) for piece in pieces) <= 240  # 允许单句超长的硬切上限
    combined = "".join(pieces)
    assert len(combined) >= len(text)


def test_index_manifest_and_stats(kb: KnowledgeBaseImpl) -> None:
    manifest = kb.manifest
    assert manifest["index_version"] == "kb-bm25-v1"
    assert manifest["n_chunks"] == kb.count()
    assert manifest["n_docs"] == kb.n_docs() == len(manifest["documents"])
    assert len(manifest["corpus_hash"]) == 64
    stats = kb.stats()
    assert stats["n_docs"] >= 20
    assert stats["publish_time_min"] <= "2018-12-31"
    assert stats["publish_time_max"] >= "2025-01-01"
    assert stats["avg_chunk_chars"] > 0


# --------------------------------------------------------------------------- #
# 检索：Evidence 契约
# --------------------------------------------------------------------------- #
def test_search_returns_kb_evidence_with_citations(kb: KnowledgeBaseImpl) -> None:
    hits = kb.search("VaR CVaR 历史模拟 尾部分位", AS_OF, top_k=3)
    assert hits
    scores = []
    for evidence in hits:
        assert isinstance(evidence, Evidence)
        assert evidence.kind == EvidenceKind.KB
        assert evidence.evidence_id.startswith("ev_kb_")
        assert evidence.as_of == AS_OF
        payload = evidence.payload
        assert payload["chunk_id"].startswith(payload["doc_id"])
        assert payload["publish_time"]
        assert date.fromisoformat(payload["publish_time"]) <= AS_OF
        assert payload["text"]
        assert len(payload["content_hash"]) == 64
        assert evidence.source.chunk_id == payload["chunk_id"]
        assert evidence.source.doc_id == payload["doc_id"]
        assert evidence.source.release_time is not None
        assert evidence.source.release_time.date() == date.fromisoformat(payload["publish_time"])
        assert evidence.citations and evidence.citations[0].chunk_id == payload["chunk_id"]
        assert evidence.hash == payload["content_hash"]
        scores.append(payload["score"])
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_search_ranking_prefers_exact_methodology_title(kb: KnowledgeBaseImpl) -> None:
    hits = kb.search("Diebold-Yilmaz 溢出指数", AS_OF, top_k=5)
    assert hits
    assert hits[0].payload["doc_id"] == "kb-meth-003"
    assert hits[0].payload["title"].startswith("方法学：Diebold-Yilmaz")


def test_empty_query_returns_empty(kb: KnowledgeBaseImpl) -> None:
    assert kb.search("", AS_OF) == []
    assert kb.search("   ", AS_OF) == []


# --------------------------------------------------------------------------- #
# 强制时点过滤
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "as_of",
    [date(2019, 1, 1), date(2021, 6, 30), date(2023, 12, 31), date(2025, 6, 30)],
)
def test_search_never_returns_future_documents(kb: KnowledgeBaseImpl, as_of: date) -> None:
    hits = kb.search("北向资金 汇率 风险 压力", as_of, top_k=10)
    for evidence in hits:
        publish = date.fromisoformat(evidence.payload["publish_time"])
        assert publish <= as_of
        assert evidence.source.release_time.date() <= as_of


def test_search_result_count_monotonic_in_as_of(kb: KnowledgeBaseImpl) -> None:
    # top_k 取全量候选，保证"晚时点结果 ⊇ 早时点结果"（BM25 统计量不随候选集变化）
    early = kb.search("北向资金 汇率 风险", date(2019, 6, 30), top_k=kb.count())
    late = kb.search("北向资金 汇率 风险", date(2025, 6, 30), top_k=kb.count())
    assert len(late) >= len(early)
    early_ids = {evidence.payload["chunk_id"] for evidence in early}
    late_ids = {evidence.payload["chunk_id"] for evidence in late}
    assert early_ids.issubset(late_ids)


def test_future_documents_are_excluded_from_temp_corpus(tmp_path: Path) -> None:
    corpus = _make_temp_corpus(
        tmp_path,
        [
            {
                "doc_id": "kb-hist-001",
                "title": "历史政策文件",
                "source": "测试来源",
                "publish_time": "2020-01-01",
                "url": "https://example.com/hist",
                "tags": ["测试", "政策"],
                "text": "北向资金异常流出的阈值设定与同步撤离指标说明，用于历史时点检索。",
            },
            {
                "doc_id": "kb-future-001",
                "title": "未来政策文件",
                "source": "测试来源",
                "publish_time": "2030-01-01",
                "url": "https://example.com/future",
                "tags": ["测试", "政策"],
                "text": "北向资金未来政策信息与同步撤离指标，绝不应在2025年被检索到。",
            },
        ],
    )
    kb_local = KnowledgeBaseImpl.from_corpus(corpus)
    hits_2025 = kb_local.search("北向资金 同步撤离 指标", date(2025, 6, 30), top_k=10)
    assert hits_2025
    assert {evidence.payload["doc_id"] for evidence in hits_2025} == {"kb-hist-001"}
    assert all(
        date.fromisoformat(evidence.payload["publish_time"]) <= date(2025, 6, 30)
        for evidence in hits_2025
    )
    hits_2031 = kb_local.search("北向资金 同步撤离 指标", date(2031, 6, 30), top_k=10)
    assert {evidence.payload["doc_id"] for evidence in hits_2031} == {
        "kb-hist-001",
        "kb-future-001",
    }


def test_publish_time_equal_to_as_of_is_visible(tmp_path: Path) -> None:
    corpus = _make_temp_corpus(
        tmp_path,
        [
            {
                "doc_id": "kb-boundary-001",
                "title": "边界日政策文件",
                "source": "测试来源",
                "publish_time": "2024-12-31",
                "url": "https://example.com/boundary",
                "tags": ["测试"],
                "text": "边界日发布的跨境资金流动政策文本，应在其发布当日可见。",
            }
        ],
    )
    kb_local = KnowledgeBaseImpl.from_corpus(corpus)
    same_day = kb_local.search("跨境资金流动政策", date(2024, 12, 31))
    assert {evidence.payload["doc_id"] for evidence in same_day} == {"kb-boundary-001"}
    before = kb_local.search("跨境资金流动政策", date(2024, 12, 30))
    assert before == []


# --------------------------------------------------------------------------- #
# 元数据过滤
# --------------------------------------------------------------------------- #
def test_tags_filter(kb: KnowledgeBaseImpl) -> None:
    hits = kb.search("风险 方法 指标", date(2025, 6, 30), top_k=10, tags=["方法学"])
    assert hits
    for evidence in hits:
        assert "方法学" in {tag.lower() for tag in evidence.payload["tags"]}
        assert "方法学" in evidence.payload["tags"]
    assert kb.search("北向资金", date(2025, 6, 30), tags=["不存在的标签"]) == []


def test_sources_filter(kb: KnowledgeBaseImpl) -> None:
    hits = kb.search("政策 跨境 资金", date(2025, 6, 30), top_k=10, sources=["国家外汇管理局"])
    assert hits
    assert all(evidence.payload["source"] == "国家外汇管理局" for evidence in hits)


# --------------------------------------------------------------------------- #
# 索引持久化 / 过期检测 / 工厂
# --------------------------------------------------------------------------- #
def test_index_roundtrip(tmp_path: Path, kb: KnowledgeBaseImpl) -> None:
    index_dir = tmp_path / "index"
    manifest = build_knowledge_index(
        CORPUS_DIR, index_dir, chunk_size=240, chunk_overlap=48
    )
    for name in ("documents.jsonl", "chunks.jsonl", "bm25.json", "manifest.json"):
        assert (index_dir / name).exists()
    assert manifest["n_chunks"] > 0
    loaded = KnowledgeBaseImpl.load(index_dir)
    assert loaded.count() == kb.count()
    assert loaded.n_docs() == kb.n_docs()

    query = "CoVaR MES 尾部风险溢出"
    original = kb.search(query, AS_OF, top_k=5)
    reloaded = loaded.search(query, AS_OF, top_k=5)
    assert [ev.evidence_id for ev in original] == [ev.evidence_id for ev in reloaded]
    assert [ev.payload["score"] for ev in original] == [ev.payload["score"] for ev in reloaded]
    assert [ev.payload["text"] for ev in original] == [ev.payload["text"] for ev in reloaded]


def test_index_freshness_detects_corpus_change(tmp_path: Path) -> None:
    corpus = _make_temp_corpus(
        tmp_path,
        [
            {
                "doc_id": "kb-fresh-001",
                "title": "语料新鲜度测试",
                "source": "测试来源",
                "publish_time": "2023-01-01",
                "url": "https://example.com/fresh",
                "tags": ["测试"],
                "text": "第一版语料文本，用于索引过期检测。",
            }
        ],
    )
    index_dir = tmp_path / "index"
    build_knowledge_index(corpus, index_dir, chunk_size=240, chunk_overlap=48)
    initial_hash = compute_corpus_hash(corpus)
    config = load_knowledge_settings()
    assert index_is_fresh(
        index_dir,
        corpus_hash=initial_hash,
        index_version=config.index_version,
        chunk_size=240,
        chunk_overlap=48,
    )
    # 修改语料 → 哈希变化 → 索引应判定为过期
    (corpus / "docs.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "kb-fresh-001",
                "title": "语料新鲜度测试",
                "source": "测试来源",
                "publish_time": "2023-01-01",
                "url": "https://example.com/fresh",
                "tags": ["测试"],
                "text": "第二版语料文本（已修改），用于索引过期检测。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert compute_corpus_hash(corpus) != initial_hash
    assert not index_is_fresh(
        index_dir,
        corpus_hash=compute_corpus_hash(corpus),
        index_version=config.index_version,
        chunk_size=240,
        chunk_overlap=48,
    )


def test_build_knowledge_base_factory_works() -> None:
    kb_local = build_knowledge_base(load_settings())
    assert kb_local.count() > 0
    assert kb_local.n_docs() >= 20
    hits = kb_local.search("跨境融资宏观审慎调节参数", date(2025, 6, 30), top_k=3)
    assert hits
    assert all(
        date.fromisoformat(evidence.payload["publish_time"]) <= date(2025, 6, 30)
        for evidence in hits
    )
