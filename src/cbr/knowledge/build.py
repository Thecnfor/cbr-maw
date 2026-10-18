"""知识库语料加载、切块与索引构建（corpus -> chunks + BM25 统计 + manifest）。

语料格式（``data/knowledge/corpus/`` 下，至少 20 篇）：
1. Markdown + YAML front matter::

       ---
       doc_id: kb-2024-001
       title: 标题
       source: 中国人民银行
       publish_time: 2024-08-05
       url: https://www.pbc.gov.cn/
       tags: [货币政策, 流动性]
       section: 政策要点
       ---
       正文……

2. JSONL（每行一个文档对象，字段同上，正文键为 ``text`` 或 ``content``）。

索引写入 ``data/knowledge/index/``：documents.jsonl / chunks.jsonl / bm25.json / manifest.json。
manifest 内 ``corpus_hash`` 用于判断索引是否过期（语料变更后自动重建）。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..schemas import utcnow
from ._index import Chunk, build_bm25_stats, tokenize

FRONT_MATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.S)
CORPUS_SUFFIXES = (".md", ".markdown", ".jsonl")
REQUIRED_META = ("title", "source", "publish_time")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s*|\n+")


# --------------------------------------------------------------------------- #
# 文档模型与解析
# --------------------------------------------------------------------------- #
def _parse_publish_time(value: Any, *, source: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(text[:10]), time.min)
            except ValueError as exc:
                raise ValueError(f"invalid publish_time {value!r} in {source}") from exc
    raise ValueError(f"missing/invalid publish_time in {source}")


class Document(BaseModel):
    """知识库文档（语料元数据 + 正文）。"""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    title: str
    source: str
    publish_time: datetime
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    section: str = "正文"
    text: str = ""

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in re.split(r"[,，;；]", value) if part.strip()]
        return [str(item).strip() for item in value if str(item).strip()]


def _document_from_meta(meta: Mapping[str, Any], body: str, *, origin: str) -> Document:
    missing = [key for key in REQUIRED_META if not meta.get(key)]
    if missing:
        raise ValueError(f"missing required metadata {missing} in {origin}")
    doc_id = str(meta.get("doc_id") or Path(origin).stem)
    return Document(
        doc_id=doc_id,
        title=str(meta["title"]).strip(),
        source=str(meta["source"]).strip(),
        publish_time=_parse_publish_time(meta["publish_time"], source=origin),
        url=(str(meta["url"]).strip() if meta.get("url") else None),
        tags=meta.get("tags") or [],
        section=str(meta.get("section") or "正文").strip(),
        text=str(body or "").strip(),
    )


def _load_markdown(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        raise ValueError(f"markdown corpus file lacks YAML front matter: {path}")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, Mapping):
        raise ValueError(f"invalid YAML front matter: {path}")
    body = raw[match.end() :]
    return _document_from_meta(meta, body, origin=path.as_posix())


def _load_jsonl(path: Path) -> list[Document]:
    documents: list[Document] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_no}: {exc}") from exc
            if not isinstance(record, Mapping):
                raise ValueError(f"JSONL record must be an object at {path}:{line_no}")
            meta = dict(record)
            body = meta.pop("text", meta.pop("content", ""))
            meta.setdefault("doc_id", f"{path.stem}-{len(documents) + 1:03d}")
            documents.append(_document_from_meta(meta, body, origin=f"{path}:{line_no}"))
    return documents


def load_documents(corpus_dir: str | Path) -> list[Document]:
    """加载语料目录下全部 .md / .jsonl 文档（按 publish_time, doc_id 排序）。"""
    root = Path(corpus_dir)
    if not root.exists():
        raise FileNotFoundError(f"knowledge corpus directory not found: {root}")
    documents: list[Document] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CORPUS_SUFFIXES:
            continue
        if path.suffix.lower() in (".md", ".markdown"):
            documents.append(_load_markdown(path))
        else:
            documents.extend(_load_jsonl(path))
    if not documents:
        raise ValueError(f"no corpus documents found under {root}")
    seen: dict[str, str] = {}
    for doc in documents:
        if doc.doc_id in seen:
            raise ValueError(f"duplicate doc_id {doc.doc_id!r}: {seen[doc.doc_id]} vs {doc.doc_id}")
        seen[doc.doc_id] = doc.doc_id
    documents.sort(key=lambda d: (d.publish_time, d.doc_id))
    return documents


# --------------------------------------------------------------------------- #
# 切块
# --------------------------------------------------------------------------- #
def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(text or "")]
    return [part for part in parts if part]


def _overlap_tail(sentences: Sequence[str], overlap_chars: int) -> list[str]:
    tail: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        if tail and length + len(sentence) + 1 > overlap_chars:
            break
        tail.insert(0, sentence)
        length += len(sentence) + 1
    return tail


def chunk_text(text: str, chunk_size: int = 240, chunk_overlap: int = 48) -> list[str]:
    """按句子边界把正文切成目标长度块，块间保留约 ``chunk_overlap`` 字符重叠。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(chunk_overlap, chunk_size // 2))
    sentences = _split_sentences(text)
    if not sentences:
        return []
    # 超长句硬切，保证块长可控
    hard: list[str] = []
    for sentence in sentences:
        if len(sentence) > chunk_size * 2:
            hard.extend(
                sentence[start : start + chunk_size]
                for start in range(0, len(sentence), chunk_size)
            )
        else:
            hard.append(sentence)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    index = 0
    carried = False
    while index < len(hard):
        sentence = hard[index]
        if current and current_len + len(sentence) + 1 > chunk_size:
            if not carried:
                chunks.append("\n".join(current))
                current = _overlap_tail(current, overlap)
                current_len = sum(len(part) + 1 for part in current)
                carried = True
                continue
            # 重叠后仍放不下（单句过长）：接受超长块，继续推进避免死循环
            current.append(sentence)
            current_len += len(sentence) + 1
            index += 1
            carried = False
            continue
        current.append(sentence)
        current_len += len(sentence) + 1
        index += 1
        carried = False
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_chunks(
    documents: Sequence[Document], chunk_size: int = 240, chunk_overlap: int = 48
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        publish_date = doc.publish_time.date()
        tag_text = " ".join(doc.tags)
        for idx, piece in enumerate(chunk_text(doc.text, chunk_size, chunk_overlap)):
            chunk_id = f"{doc.doc_id}#c{idx:03d}"
            index_text = f"{doc.title}\n{doc.section}\n{tag_text}\n{piece}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    source=doc.source,
                    publish_time=publish_date,
                    url=doc.url,
                    tags=list(doc.tags),
                    section=doc.section,
                    text=piece,
                    index_text=index_text,
                    chunk_index=idx,
                    hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                )
            )
    return chunks


# --------------------------------------------------------------------------- #
# 语料哈希 / 索引读写
# --------------------------------------------------------------------------- #
def compute_corpus_hash(corpus_dir: str | Path) -> str:
    """语料目录内容哈希（相对路径 + 文件内容），用于判断索引是否过期。"""
    root = Path(corpus_dir)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CORPUS_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def build_corpus_index(
    corpus_dir: str | Path, chunk_size: int = 240, chunk_overlap: int = 48
) -> tuple[list[Document], list[Chunk], str]:
    """从语料构建 (documents, chunks, corpus_hash)。"""
    documents = load_documents(corpus_dir)
    chunks = build_chunks(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        raise ValueError("corpus produced zero chunks")
    return documents, chunks, compute_corpus_hash(corpus_dir)


def build_manifest(
    *,
    documents: Sequence[Document],
    chunks: Sequence[Chunk],
    corpus_hash: str,
    index_version: str,
    chunk_size: int,
    chunk_overlap: int,
    bm25_k1: float,
    bm25_b: float,
) -> dict[str, Any]:
    return {
        "index_version": index_version,
        "built_at": utcnow().isoformat(),
        "corpus_hash": corpus_hash,
        "n_docs": len(documents),
        "n_chunks": len(chunks),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "bm25_k1": bm25_k1,
        "bm25_b": bm25_b,
        "documents": [
            {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "source": doc.source,
                "publish_time": doc.publish_time.date().isoformat(),
                "url": doc.url,
                "tags": list(doc.tags),
            }
            for doc in documents
        ],
    }


def write_index(
    index_dir: str | Path,
    documents: Sequence[Document],
    chunks: Sequence[Chunk],
    stats: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Path:
    """把索引写入目录（chunks.jsonl / documents.jsonl / bm25.json / manifest.json）。"""
    target = Path(index_dir)
    target.mkdir(parents=True, exist_ok=True)
    with (target / "documents.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for doc in documents:
            handle.write(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with (target / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(mode="json"), ensure_ascii=False) + "\n")
    (target / "bm25.json").write_text(
        json.dumps(dict(stats), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (target / "manifest.json").write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def read_index(
    index_dir: str | Path,
) -> tuple[list[Document], list[Chunk], dict[str, Any], dict[str, Any]]:
    """读取索引目录，返回 (documents, chunks, stats, manifest)。"""
    root = Path(index_dir)
    required = ["documents.jsonl", "chunks.jsonl", "bm25.json", "manifest.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise FileNotFoundError(f"knowledge index incomplete under {root}: missing {missing}")
    documents = [
        Document(**json.loads(line))
        for line in (root / "documents.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    chunks = [
        Chunk(**json.loads(line))
        for line in (root / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stats = json.loads((root / "bm25.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if int(manifest.get("n_chunks", -1)) != len(chunks):
        raise ValueError(
            f"index chunk count mismatch: manifest={manifest.get('n_chunks')} actual={len(chunks)}"
        )
    return documents, chunks, stats, manifest


def index_is_fresh(
    index_dir: str | Path,
    *,
    corpus_hash: str,
    index_version: str,
    chunk_size: int,
    chunk_overlap: int,
) -> bool:
    manifest_path = Path(index_dir) / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return (
        manifest.get("corpus_hash") == corpus_hash
        and manifest.get("index_version") == index_version
        and int(manifest.get("chunk_size", -1)) == int(chunk_size)
        and int(manifest.get("chunk_overlap", -1)) == int(chunk_overlap)
    )


# --------------------------------------------------------------------------- #
# 可复现的统计辅助（供查询/测试使用）
# --------------------------------------------------------------------------- #
def corpus_stats(corpus_dir: str | Path) -> dict[str, Any]:
    documents = load_documents(corpus_dir)
    total_chars = sum(len(doc.text) for doc in documents)
    return {
        "n_docs": len(documents),
        "total_chars": total_chars,
        "publish_time_min": min(doc.publish_time for doc in documents).date().isoformat(),
        "publish_time_max": max(doc.publish_time for doc in documents).date().isoformat(),
        "sources": sorted({doc.source for doc in documents}),
        "tags": sorted({tag for doc in documents for tag in doc.tags}),
        "vocabulary_size": len(
            {token for doc in documents for token in tokenize(doc.text)}
        ),
    }
