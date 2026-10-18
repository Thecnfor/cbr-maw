"""知识库配置：读取 configs/tools.yaml 的 ``knowledge`` 段。

与工具层共用同一份配置文件的 hunk，避免两份配置漂移；缺失时使用内置默认值。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..config import load_yaml, resolve_path

DEFAULT_KNOWLEDGE_CONFIG_PATH = "configs/tools.yaml"


class KnowledgeSettings(BaseModel):
    """时点知识库配置。"""

    corpus_dir: str = "data/knowledge/corpus"
    index_dir: str = "data/knowledge/index"
    chunk_size: int = Field(240, ge=50, le=2000)
    chunk_overlap: int = Field(48, ge=0, le=1000)
    top_k: int = Field(5, ge=1, le=20)
    bm25_k1: float = Field(1.5, gt=0.0)
    bm25_b: float = Field(0.75, ge=0.0, le=1.0)
    index_version: str = "kb-bm25-v1"
    auto_build: bool = True
    write_index_on_miss: bool = False
    # 预留 embedding 召回接口（当前 BM25-only，无需 GPU）
    embedding: dict[str, Any] = Field(default_factory=dict)


def load_knowledge_settings(
    path: str | os.PathLike[str] | None = None,
) -> KnowledgeSettings:
    """读取知识库配置；文件/配置段缺失时返回内置默认值。"""
    cfg_path = Path(path) if path is not None else resolve_path(
        os.environ.get("CBR_TOOLS_CONFIG", DEFAULT_KNOWLEDGE_CONFIG_PATH)
    )
    raw = load_yaml(cfg_path, default=None)
    if not raw or not isinstance(raw, Mapping):
        return KnowledgeSettings()
    section = raw.get("knowledge") or {}
    if not isinstance(section, Mapping):
        raise ValueError(f"invalid knowledge config section in {cfg_path}")
    return KnowledgeSettings(**dict(section))
