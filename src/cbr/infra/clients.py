"""可选基础设施客户端：驱动缺失或服务不可达时返回 ``None``（调用方自行降级）。

只在真正调用时惰性 import 驱动，因此不安装 redis/psycopg/pymongo 也能导入本模块。
"""

from __future__ import annotations

import logging
from typing import Any

from .config import InfraSettings, load_infra_settings

logger = logging.getLogger(__name__)


def get_redis(settings: InfraSettings | None = None) -> Any | None:
    """返回 Redis 客户端；未启用或不可用时返回 ``None``。"""
    settings = settings or load_infra_settings()
    if not settings.enabled or not settings.redis.enabled:
        return None
    try:
        import redis  # noqa: PLC0415 - 可选依赖
    except ImportError:
        logger.info("未安装 redis 驱动，Redis 缓存降级为本地实现")
        return None
    try:
        client = redis.Redis.from_url(settings.redis.url, socket_connect_timeout=settings.probe_timeout_seconds)
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.info("Redis 不可用（%s），降级为本地实现", exc)
        return None


def get_postgres(settings: InfraSettings | None = None) -> Any | None:
    """返回 PostgreSQL 连接；未启用 / 缺驱动 / 不可达时返回 ``None``。"""
    settings = settings or load_infra_settings()
    if not settings.enabled or not settings.postgres.enabled:
        return None
    try:
        import psycopg  # noqa: PLC0415 - 可选依赖
    except ImportError:
        logger.info("未安装 psycopg 驱动，PostgreSQL 相关能力降级")
        return None
    try:
        return psycopg.connect(settings.postgres.dsn, connect_timeout=int(settings.probe_timeout_seconds))
    except Exception as exc:  # noqa: BLE001
        logger.info("PostgreSQL 不可用（%s），降级", exc)
        return None


def get_mongo(settings: InfraSettings | None = None) -> Any | None:
    """返回 MongoDB 数据库句柄；未启用 / 缺驱动 / 不可达时返回 ``None``。"""
    settings = settings or load_infra_settings()
    if not settings.enabled or not settings.mongodb.enabled:
        return None
    try:
        from pymongo import MongoClient  # noqa: PLC0415 - 可选依赖
    except ImportError:
        logger.info("未安装 pymongo 驱动，MongoDB 归档能力降级")
        return None
    try:
        client = MongoClient(settings.mongodb.uri, serverSelectionTimeoutMS=int(settings.probe_timeout_seconds * 1000))
        client.admin.command("ping")
        return client[settings.mongodb.database]
    except Exception as exc:  # noqa: BLE001
        logger.info("MongoDB 不可用（%s），降级", exc)
        return None
