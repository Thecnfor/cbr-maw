"""基础设施配置（``configs/infra.yaml``）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cbr.config import load_yaml


class ServiceEndpoint(BaseModel):
    """通用服务端点（enabled + 连接串）。"""

    enabled: bool = False


class PostgresSettings(ServiceEndpoint):
    """PostgreSQL（元数据 / pgvector）。"""

    dsn: str = "postgresql://cbr:cbr@127.0.0.1:55432/cbr"


class RedisSettings(ServiceEndpoint):
    """Redis（实时缓存 / 抓取去重）。"""

    url: str = "redis://127.0.0.1:56379/0"


class MongoSettings(ServiceEndpoint):
    """MongoDB（原始文档 / 抓取快照归档）。"""

    uri: str = "mongodb://cbr:cbr@127.0.0.1:57017"
    database: str = "cbr"


class EmbeddingSettings(BaseModel):
    """向量化配置。"""

    provider: str = "hashing"  # hashing | openai
    model: str = "text-embedding-3-small"
    dimension: int = 256


class QdrantSettings(BaseModel):
    """Qdrant 向量库端点。"""

    url: str = "http://127.0.0.1:56333"


class PgVectorSettings(BaseModel):
    """pgvector 表配置。"""

    dsn: str = "postgresql://cbr:cbr@127.0.0.1:55432/cbr"
    table: str = "cbr_chunks"


class VectorSettings(BaseModel):
    """向量检索（RAG）配置。"""

    backend: str = "local"  # local | qdrant | pgvector
    collection: str = "cbr_chunks"
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    pgvector: PgVectorSettings = Field(default_factory=PgVectorSettings)


class InfraSettings(BaseModel):
    """基础设施总配置。"""

    enabled: bool = False
    probe_timeout_seconds: float = 1.0
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    mongodb: MongoSettings = Field(default_factory=MongoSettings)
    vector: VectorSettings = Field(default_factory=VectorSettings)

    def service_map(self) -> dict[str, tuple[bool, str]]:
        """返回 ``{服务名: (enabled, 连接串)}``，供健康探测遍历。"""
        return {
            "postgres": (self.postgres.enabled, self.postgres.dsn),
            "redis": (self.redis.enabled, self.redis.url),
            "mongodb": (self.mongodb.enabled, self.mongodb.uri),
            "qdrant": (self.vector.backend == "qdrant", self.vector.qdrant.url),
        }


def load_infra_settings(path: str = "configs/infra.yaml") -> InfraSettings:
    """读取基础设施配置；文件缺失时返回默认（全部关闭）。"""
    raw = load_yaml(path, default={}) or {}
    payload = raw.get("infra") if isinstance(raw, dict) else None
    return InfraSettings(**(payload or {}))
