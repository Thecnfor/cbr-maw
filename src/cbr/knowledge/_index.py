"""BM25 索引核心：中英混合分词、倒排统计、打分。

- 中文按"单字 + 相邻二元组"切分（无需 jieba，确定性、无 GPU、无外部依赖）；
- 英文/数字按小写词切分（保留 ``_ + - .`` 以匹配指标名，如 ``var_95``）；
- BM25（Lucene 变体）：idf = ln(1 + (N - df + 0.5)/(df + 0.5))，
  score = Σ idf·tf·(k1+1)/(tf + k1·(1 - b + b·dl/avgdl))。
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+\-.]*")


def tokenize(text: str) -> list[str]:
    """中英混合分词：中文单字 + 二元组，英文/数字小写词。"""
    lowered = (text or "").lower()
    tokens: list[str] = []
    for match in WORD_RE.finditer(lowered):
        tokens.append(match.group(0))
    for match in CJK_RE.finditer(lowered):
        run = match.group(0)
        tokens.extend(run)
        if len(run) >= 2:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class Chunk(BaseModel):
    """知识库切片（chunk 级元数据 + 正文）。"""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    title: str
    source: str
    publish_time: date
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    section: str = "正文"
    text: str
    index_text: str = ""
    chunk_index: int = 0
    hash: str = ""


def build_bm25_stats(chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75) -> dict[str, Any]:
    """统计文档频率与平均长度（确定性，JSON 可序列化）。"""
    df: dict[str, int] = {}
    total_length = 0
    for chunk in chunks:
        tokens = tokenize(chunk.index_text or chunk.text)
        total_length += len(tokens)
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    n_chunks = len(chunks)
    return {
        "n_chunks": n_chunks,
        "avgdl": (total_length / n_chunks) if n_chunks else 0.0,
        "df": df,
        "k1": float(k1),
        "b": float(b),
    }


def bm25_scores(query_tokens: Sequence[str], chunks: Sequence[Chunk], stats: dict[str, Any]) -> list[float]:
    """对 chunks 逐个打分（与 chunks 顺序一一对应）。"""
    n_chunks = int(stats.get("n_chunks", len(chunks)))
    avgdl = float(stats.get("avgdl", 0.0)) or 1.0
    df: dict[str, int] = stats.get("df", {})
    k1 = float(stats.get("k1", 1.5))
    b = float(stats.get("b", 0.75))
    unique_query = list(dict.fromkeys(query_tokens))

    scores: list[float] = []
    for chunk in chunks:
        tokens = tokenize(chunk.index_text or chunk.text)
        dl = len(tokens)
        if dl == 0:
            scores.append(0.0)
            continue
        tf: dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for token in unique_query:
            freq = tf.get(token, 0)
            if freq == 0:
                continue
            token_df = df.get(token, 0)
            idf = math.log(1.0 + (n_chunks - token_df + 0.5) / (token_df + 0.5))
            denominator = freq + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * freq * (k1 + 1.0) / denominator
        scores.append(score)
    return scores
