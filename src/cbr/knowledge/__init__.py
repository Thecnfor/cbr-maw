"""时点知识库工厂（service.py 约定）：

    from cbr.knowledge import build_knowledge_base
    kb = build_knowledge_base(settings)

行为：
1. 配置见 ``configs/tools.yaml`` 的 ``knowledge`` 段（也可用 ``CBR_TOOLS_CONFIG`` 覆盖）；
2. 若 ``data/knowledge/index/`` 已存在且 manifest 的 corpus_hash / index_version /
   切块参数与当前语料一致，则直接加载索引；
3. 否则在内存中从 ``data/knowledge/corpus/`` 重建（``auto_build=true``），
   是否顺带写盘由 ``write_index_on_miss`` 控制；显式落盘请运行 scripts/build_knowledge.py。
"""

from __future__ import annotations

from pathlib import Path

from ..config import AppSettings, load_settings, resolve_path
from .base import KnowledgeBaseImpl, build_knowledge_index
from .build import compute_corpus_hash, index_is_fresh
from .settings import KnowledgeSettings, load_knowledge_settings


def resolve_knowledge_paths(
    settings: AppSettings,
    config: KnowledgeSettings | None = None,
) -> tuple[Path, Path]:
    """解析 (corpus_dir, index_dir)：配置路径优先，否则基于 settings.paths.knowledge。"""
    config = config or load_knowledge_settings()
    default_base = resolve_path(settings.paths.knowledge)
    default_corpus = default_base / "corpus"
    default_index = default_base / "index"
    corpus_dir = (
        resolve_path(config.corpus_dir)
        if config.corpus_dir != "data/knowledge/corpus"
        else default_corpus
    )
    index_dir = (
        resolve_path(config.index_dir)
        if config.index_dir != "data/knowledge/index"
        else default_index
    )
    return corpus_dir, index_dir


def build_knowledge_base(
    settings: AppSettings | None = None,
    *,
    config_path: str | None = None,
    force_rebuild: bool = False,
) -> KnowledgeBaseImpl:
    """装配时点知识库（索引优先，缺失/过期时按语料重建）。"""
    settings = settings or load_settings()
    config = load_knowledge_settings(config_path)
    corpus_dir, index_dir = resolve_knowledge_paths(settings, config)
    if not corpus_dir.exists():
        raise FileNotFoundError(f"knowledge corpus not found: {corpus_dir}")

    corpus_hash = compute_corpus_hash(corpus_dir)
    if (
        not force_rebuild
        and index_dir.exists()
        and index_is_fresh(
            index_dir,
            corpus_hash=corpus_hash,
            index_version=config.index_version,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
    ):
        return KnowledgeBaseImpl.load(index_dir)

    if not config.auto_build:
        raise FileNotFoundError(
            f"knowledge index missing/stale at {index_dir} and auto_build=false; "
            "run scripts/build_knowledge.py first"
        )
    kb = KnowledgeBaseImpl.from_corpus(
        corpus_dir,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        bm25_k1=config.bm25_k1,
        bm25_b=config.bm25_b,
        index_version=config.index_version,
    )
    if config.write_index_on_miss:
        kb.save(index_dir)
    return kb


__all__ = [
    "Document",
    "KnowledgeBaseImpl",
    "KnowledgeSettings",
    "build_knowledge_base",
    "build_knowledge_index",
    "compute_corpus_hash",
    "index_is_fresh",
    "load_knowledge_settings",
    "resolve_knowledge_paths",
]

from .build import Document  # noqa: E402  (放末尾避免循环导入)
