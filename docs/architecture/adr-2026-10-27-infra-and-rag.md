# ADR-2026-10-27 · 可选基础设施（PG/Redis/Mongo/向量库）与 RAG 检索

- 状态：**已接受（Accepted）** — 已落地
- 决策者：Lead / 架构
- 相关：`docker-compose.yml`、`configs/infra.yaml`、`src/cbr/infra/`、`src/cbr/knowledge/vector.py`

## 1. 背景

实时抓取需要缓存 / 去重 / 归档；文本语料需要**语义检索**（现仅 BM25）。需求方明确
「必要时可用 Docker 起 redis / mongodb / 向量库 / pgsql」，并要求「注意 RAG 工程」。

约束：本仓库是**可离线复现**的研究原型——全量测试、SYNTHETIC 演示在无任何外部服务、
无任何额外依赖时必须跑通；不得因外部服务缺席而让启动失败或测试变红。

## 2. 决策

**基础设施全部「可选 + 可降级」，默认关闭。**

1. `docker-compose.yml` 提供 postgres(pgvector) / redis / mongo / qdrant，端口与 `configs/infra.yaml` 对齐。
2. `src/cbr/infra/` 提供：配置加载、健康探测（标准库 socket，无依赖）、可选客户端
   （缺驱动/不可达一律 `None`，调用方降级）。`infra.enabled=false` 时全部走本地实现。
3. RAG 采用**可插拔后端 + 默认离线可用**：
   - 向量化：默认 `HashingEmbedding`（hashing trick，确定性、无依赖）；可选 OpenAI 兼容嵌入。
   - 向量库：默认 `NumpyVectorStore`（内存 + npz）；可选 Qdrant / pgvector。
   - 检索：`HybridRetriever` 做 **BM25 + 向量 的加权 RRF 融合**，兼顾关键词（指标名/机构名）与语义。
   - 后端不可用自动回退本地实现（`build_embedder` / `build_vector_store` 捕获异常回退）。

## 3. 后果

- 正面：默认零依赖、离线可复现；需要时开 Docker 即获持久化与规模化检索；契约稳定，替换后端不改调用方。
- 负面：默认 `HashingEmbedding` 语义质量弱于真实嵌入模型（属**明示的降级默认**，非最优解）；
  外部后端尚未在真实数据集上做端到端评测。
- 边界（诚实声明）：`HybridRetriever` 目前是**独立可用组件**，尚未替换 `KnowledgeBaseImpl.search`
  的默认 BM25 路径；接入方式见下。
- 未决：真实嵌入模型选型与评测；pgvector/Qdrant 的数据规模与延迟基线；缓存（Redis）与归档（Mongo）
  在实时抓取中的具体落点（当前抓取报告落盘 `artifacts/ingest/`）。

## 4. 接入方式（RAG）

```python
from cbr.knowledge.vector import build_retriever

retriever = build_retriever(kb.chunks)          # 读 configs/infra.yaml 选后端（默认 local）
hits = retriever.search("美联储加息 人民币贬值", as_of="2024-08-05", top_k=5)
```

将 BM25 路径升级为混合检索：在 `KnowledgeBaseImpl` 内持有 `HybridRetriever`，
`search()` 用 `HybridRetriever.search` 替换 `bm25_scores` 排序即可（保持 `Evidence` 构造不变）。
这是后续可选的独立工作项，本 ADR 记录方向与理由。
