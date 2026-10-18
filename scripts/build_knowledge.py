"""构建 CBR-MAW 时点知识库 BM25 索引。

语料：``data/knowledge/corpus/*.jsonl``（自有改写文本，含 title/source/
publish_time/url/tags 元数据）；索引：``data/knowledge/index/``
（documents.jsonl / chunks.jsonl / bm25.json / manifest.json）。

用法（项目根目录）::

    .venv\\Scripts\\python.exe scripts\\build_knowledge.py
    .venv\\Scripts\\python.exe scripts\\build_knowledge.py --as-of 2022-12-31 --query "北向资金 同步撤离"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # 允许直接 python scripts/build_knowledge.py
    sys.path.insert(0, str(ROOT / "src"))

from cbr.config import load_settings, resolve_path  # noqa: E402
from cbr.knowledge import (  # noqa: E402
    KnowledgeBaseImpl,
    build_knowledge_index,
    load_knowledge_settings,
)
from cbr.knowledge.build import corpus_stats  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 CBR-MAW 时点知识库索引")
    parser.add_argument("--corpus-dir", default=None, help="语料目录（默认取自 configs/tools.yaml）")
    parser.add_argument("--index-dir", default=None, help="索引输出目录（默认 data/knowledge/index）")
    parser.add_argument(
        "--query",
        default="VaR CVaR 历史模拟 尾部分位",
        help="构建后用于冒烟检索的查询",
    )
    parser.add_argument("--as-of", default=None, help="冒烟检索的时点（ISO 日期，默认今天）")
    args = parser.parse_args(argv)

    load_settings()  # 初始化环境（.env 等），知识库路径可被 settings 覆盖
    config = load_knowledge_settings()
    corpus_dir = resolve_path(args.corpus_dir or config.corpus_dir)
    index_dir = resolve_path(args.index_dir or config.index_dir)

    manifest = build_knowledge_index(
        corpus_dir,
        index_dir,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        bm25_k1=config.bm25_k1,
        bm25_b=config.bm25_b,
        index_version=config.index_version,
    )

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    kb = KnowledgeBaseImpl.load(index_dir)
    hits = kb.search(args.query, as_of, top_k=3)
    payload = {
        "index_dir": str(index_dir),
        "corpus_dir": str(corpus_dir),
        "manifest": {
            key: manifest.get(key)
            for key in (
                "index_version",
                "corpus_hash",
                "n_docs",
                "n_chunks",
                "chunk_size",
                "chunk_overlap",
                "bm25_k1",
                "bm25_b",
                "built_at",
            )
        },
        "corpus_stats": corpus_stats(corpus_dir),
        "smoke_search": {
            "query": args.query,
            "as_of": as_of.isoformat(),
            "hits": [
                {
                    "evidence_id": ev.evidence_id,
                    "chunk_id": ev.payload.get("chunk_id"),
                    "title": ev.payload.get("title"),
                    "publish_time": ev.payload.get("publish_time"),
                    "score": ev.payload.get("score"),
                }
                for ev in hits
            ],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
