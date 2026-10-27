"""RAG 向量检索层：可插拔的向量化 + 向量库 + BM25/向量的混合检索。

设计原则与仓库一致：**默认离线可用、外部服务可选**。

- 向量化默认用 :class:`HashingEmbedding`（hashing trick，无外部依赖、确定性），
  可通过 ``configs/infra.yaml`` 切到 OpenAI 兼容嵌入；
- 向量库默认用 :class:`NumpyVectorStore`（内存 + npz 持久化），可切到 Qdrant / pgvector；
- 检索默认提供 :func:`hybrid_search`（BM25 与向量的 Reciprocal Rank Fusion），
  在关键词（指标名、机构名）与语义（近义表述）之间取得平衡。

外部服务不可用时（未装 Docker / 缺驱动）自动回退到本地实现，不抛异常。

.. code-block:: python

    from cbr.knowledge.vector import build_retriever

    retriever = build_retriever(chunks)          # 读 configs/infra.yaml 选后端
    hits = retriever.search("美联储加息 人民币贬值", as_of="2024-08-05", top_k=5)
    for chunk, score in hits:
        print(score, chunk.title)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

from cbr.infra.config import VectorSettings, load_infra_settings
from cbr.knowledge._index import Chunk, bm25_scores, build_bm25_stats, tokenize

logger = logging.getLogger(__name__)

#: 混合检索中两种信号的 RRF 平滑常数
RRF_K = 60.0
#: 混合检索里 BM25 / 向量 的默认权重
DEFAULT_BM25_WEIGHT = 0.5


def _as_date(value: date | datetime | str | Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


# --------------------------------------------------------------------------- #
# 向量化
# --------------------------------------------------------------------------- #
class EmbeddingProvider(Protocol):
    """向量化协议。"""

    dimension: int

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """把文本批量编码为 ``(n, dimension)`` 的 float32 矩阵。"""
        ...


class HashingEmbedding:
    """基于 hashing trick 的离线确定性向量化（无外部依赖）。

    复用知识库的中英混合分词（中文单字 + 二元组），把 token 哈希到固定维度并用
    符号散列（signed hashing）抵消部分冲突，最后做 L2 归一化。
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = max(8, int(dimension))

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text or ""):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                out[row, index] += sign
            norm = float(np.linalg.norm(out[row]))
            if norm > 0:
                out[row] /= norm
        return out


class OpenAIEmbedding:
    """OpenAI 兼容嵌入（需安装 openai 且配置 API key；不可用时抛 ImportError 由工厂回退）。"""

    def __init__(self, model: str = "text-embedding-3-small", dimension: int = 256, client: Any = None) -> None:
        if client is None:  # pragma: no cover - 需要网络/密钥
            from openai import OpenAI  # noqa: PLC0415

            client = OpenAI()
        self._client = client
        self.model = model
        self.dimension = int(dimension)

    def embed(self, texts: Sequence[str]) -> np.ndarray:  # pragma: no cover - 需要网络/密钥
        resp = self._client.embeddings.create(model=self.model, input=list(texts))
        vectors = np.array([item.embedding for item in resp.data], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


def build_embedder(settings: VectorSettings | None = None) -> EmbeddingProvider:
    """按配置构造向量化器；OpenAI 不可用时回退 ``HashingEmbedding``。"""
    settings = settings or load_infra_settings().vector
    if settings.embedding.provider == "openai":
        try:
            return OpenAIEmbedding(settings.embedding.model, settings.embedding.dimension)
        except Exception as exc:  # noqa: BLE001 - 环境不支持时回退离线实现
            logger.info("OpenAI 嵌入不可用（%s），回退 HashingEmbedding", exc)
    return HashingEmbedding(settings.embedding.dimension)


# --------------------------------------------------------------------------- #
# 向量库
# --------------------------------------------------------------------------- #
class VectorStore(Protocol):
    """向量库协议：按 id 写入向量与载荷，按向量检索。"""

    def add(self, ids: Sequence[str], vectors: np.ndarray, payloads: Sequence[dict[str, Any]]) -> int: ...

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict[str, Any]]]: ...


class NumpyVectorStore:
    """内存向量库（余弦相似度），支持 npz 持久化，零外部依赖。"""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = int(dimension)
        self._ids: list[str] = []
        self._vectors: np.ndarray = np.zeros((0, self.dimension), dtype=np.float32)
        self._payloads: list[dict[str, Any]] = []

    def add(self, ids: Sequence[str], vectors: np.ndarray, payloads: Sequence[dict[str, Any]]) -> int:
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(f"向量维度不匹配：期望 {self.dimension}")
        self._ids.extend(str(i) for i in ids)
        self._vectors = np.vstack([self._vectors, vectors]) if len(self._vectors) else vectors
        self._payloads.extend(payloads)
        return len(ids)

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict[str, Any]]]:
        if not self._ids:
            return []
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm
        scores = self._vectors @ query
        order = np.argsort(-scores)[: max(1, int(top_k))]
        return [(self._ids[i], float(scores[i]), self._payloads[i]) for i in order]

    def __len__(self) -> int:
        return len(self._ids)

    def save(self, path: str | Path) -> Path:
        """持久化到 ``.npz``（向量） + ``.json``（id/载荷）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path.with_suffix(".npz"), vectors=self._vectors)
        path.with_suffix(".json").write_text(
            json.dumps({"ids": self._ids, "payloads": self._payloads, "dimension": self.dimension}),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "NumpyVectorStore":
        """从 ``save`` 产生的文件恢复。"""
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        store = cls(int(meta.get("dimension", 256)))
        store._ids = list(meta.get("ids", []))
        store._payloads = list(meta.get("payloads", []))
        store._vectors = np.load(path.with_suffix(".npz"))["vectors"].astype(np.float32)
        return store


class QdrantVectorStore:
    """Qdrant 向量库（需 ``qdrant-client`` 与运行中的 Qdrant；不可用时由工厂回退）。"""

    def __init__(self, url: str, collection: str, dimension: int) -> None:  # pragma: no cover - 需服务
        from qdrant_client import QdrantClient  # noqa: PLC0415

        self._client = QdrantClient(url=url)
        self.collection = collection
        self.dimension = int(dimension)
        self._ensure_collection()

    def _ensure_collection(self) -> None:  # pragma: no cover - 需服务
        from qdrant_client.models import Distance, VectorParams  # noqa: PLC0415

        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection not in existing:
            self._client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
            )

    def add(self, ids, vectors, payloads) -> int:  # pragma: no cover - 需服务
        from qdrant_client.models import PointStruct  # noqa: PLC0415

        points = [
            PointStruct(id=index, vector=np.asarray(vec, dtype=np.float32).tolist(), payload={"key": key, **payload})
            for index, (key, vec, payload) in enumerate(zip(ids, vectors, payloads, strict=False))
        ]
        self._client.upsert(self.collection, points=points)
        return len(points)

    def search(self, vector, top_k) -> list[tuple[str, float, dict[str, Any]]]:  # pragma: no cover - 需服务
        query = np.asarray(vector, dtype=np.float32).tolist()
        if hasattr(self._client, "query_points"):
            # qdrant-client >= 1.10：search 已被 query_points 取代
            result = self._client.query_points(self.collection, query=query, limit=int(top_k))
            hits = result.points
        else:  # 旧版客户端回退
            hits = self._client.search(self.collection, query_vector=query, limit=int(top_k))
        return [(str(hit.payload.get("key")), float(hit.score), dict(hit.payload)) for hit in hits]


class PgVectorStore:
    """PostgreSQL + pgvector 向量库（需 ``psycopg`` 与运行中的 PG；不可用时回退）。"""

    def __init__(self, dsn: str, table: str, dimension: int) -> None:  # pragma: no cover - 需服务
        import psycopg  # noqa: PLC0415

        self.table = table
        self.dimension = int(dimension)
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_table()

    def _ensure_table(self) -> None:  # pragma: no cover - 需服务
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} "
            f"(chunk_id TEXT PRIMARY KEY, embedding vector({self.dimension}), payload JSONB)"
        )

    @staticmethod
    def _literal(vector) -> str:
        """把向量格式化为 pgvector 可解析的字面量 ``"[v0,v1,...]"``。"""
        return "[" + ",".join(f"{float(x):.7g}" for x in np.asarray(vector, dtype=np.float32)) + "]"

    def add(self, ids, vectors, payloads) -> int:  # pragma: no cover - 需服务
        with self._conn.cursor() as cur:
            for key, vec, payload in zip(ids, vectors, payloads, strict=False):
                cur.execute(
                    f"INSERT INTO {self.table} (chunk_id, embedding, payload) VALUES (%s, %s::vector, %s) "
                    f"ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding, "
                    f"payload = EXCLUDED.payload",
                    (key, self._literal(vec), json.dumps(payload, ensure_ascii=False)),
                )
        return len(ids)

    def search(self, vector, top_k) -> list[tuple[str, float, dict[str, Any]]]:  # pragma: no cover - 需服务
        literal = self._literal(vector)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT chunk_id, payload, 1 - (embedding <=> %s::vector) AS score FROM {self.table} "
                f"ORDER BY embedding <=> %s::vector LIMIT %s",
                (literal, literal, int(top_k)),
            )
            return [(row[0], float(row[2]), row[1]) for row in cur.fetchall()]


def build_vector_store(settings: VectorSettings | None = None) -> VectorStore:
    """按配置构造向量库；外部后端不可用时回退 :class:`NumpyVectorStore`。"""
    settings = settings or load_infra_settings().vector
    backend = (settings.backend or "local").lower()
    dim = settings.embedding.dimension
    try:
        if backend == "qdrant":
            return QdrantVectorStore(settings.qdrant.url, settings.collection, dim)
        if backend == "pgvector":
            return PgVectorStore(settings.pgvector.dsn, settings.pgvector.table, dim)
    except Exception as exc:  # noqa: BLE001 - 外部后端不可用时回退
        logger.info("向量库后端 %s 不可用（%s），回退本地 NumpyVectorStore", backend, exc)
    return NumpyVectorStore(dim)


# --------------------------------------------------------------------------- #
# 混合检索
# --------------------------------------------------------------------------- #
def _reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    weights: Sequence[float],
    k: float = RRF_K,
) -> dict[str, float]:
    """对多路排名做加权 RRF 融合，返回 ``{id: score}``。"""
    fused: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights, strict=False):
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + weight / (k + rank)
    return fused


class HybridRetriever:
    """BM25 + 向量的混合检索器（时点过滤、标签/来源过滤）。"""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        embedder: EmbeddingProvider | None = None,
        store: VectorStore | None = None,
        *,
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
    ) -> None:
        self.chunks = list(chunks)
        self.embedder = embedder or HashingEmbedding()
        self.store = store or NumpyVectorStore(self.embedder.dimension)
        self.bm25_weight = float(bm25_weight)
        self._stats = build_bm25_stats(self.chunks)
        self._by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        self._indexed = False

    def index(self, *, force: bool = False) -> int:
        """把切片写入向量库（幂等：已建索引且未强制则跳过）。"""
        if self._indexed and not force:
            return len(self.chunks)
        if not self.chunks:
            return 0
        texts = [chunk.index_text or chunk.text for chunk in self.chunks]
        vectors = self.embedder.embed(texts)
        payloads = [
            {"doc_id": chunk.doc_id, "title": chunk.title, "source": chunk.source, "chunk_index": chunk.chunk_index}
            for chunk in self.chunks
        ]
        self.store.add([chunk.chunk_id for chunk in self.chunks], vectors, payloads)
        self._indexed = True
        return len(self.chunks)

    def search(
        self,
        query: str,
        as_of: date | datetime | str,
        top_k: int = 5,
        tags: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """混合检索，返回 ``[(chunk, 融合分数)]``（已按时点/标签/来源过滤）。"""
        query = (query or "").strip()
        if not query:
            return []
        day = _as_date(as_of)
        wanted_tags = {str(tag).lower() for tag in (tags or [])}
        wanted_sources = {str(src).lower() for src in (sources or [])}
        candidates = [
            chunk
            for chunk in self.chunks
            if chunk.publish_time <= day
            and (not wanted_tags or wanted_tags.issubset({t.lower() for t in chunk.tags}))
            and (not wanted_sources or chunk.source.lower() in wanted_sources)
        ]
        if not candidates:
            return []
        if not self._indexed:
            self.index()

        # 1) BM25 排名（在候选集内）
        query_tokens = tokenize(query)
        bm25 = bm25_scores(query_tokens, candidates, self._stats)
        bm25_rank = [
            chunk.chunk_id
            for chunk, _score in sorted(
                zip(candidates, bm25), key=lambda item: (-item[1], item[0].chunk_id)
            )
        ]

        # 2) 向量排名（在候选集内，按 chunk_id 取回分数）
        query_vec = self.embedder.embed([query])[0]
        vector_hits = self.store.search(query_vec, max(len(candidates), top_k))
        candidate_ids = {chunk.chunk_id for chunk in candidates}
        vector_rank = [key for key, _score, _payload in vector_hits if key in candidate_ids]

        fused = _reciprocal_rank_fusion(
            [bm25_rank, vector_rank],
            [self.bm25_weight, 1.0 - self.bm25_weight],
        )
        ranked_ids = sorted(fused, key=lambda key: (-fused[key], key))[: max(1, int(top_k))]
        return [(self._by_id[key], fused[key]) for key in ranked_ids if key in self._by_id]


def build_retriever(
    chunks: Sequence[Chunk],
    settings: VectorSettings | None = None,
    *,
    index: bool = True,
) -> HybridRetriever:
    """按基础设施配置构造混合检索器（并默认立即建索引）。"""
    settings = settings or load_infra_settings().vector
    embedder = build_embedder(settings)
    store = build_vector_store(settings)
    retriever = HybridRetriever(chunks, embedder=embedder, store=store)
    if index:
        retriever.index()
    return retriever
