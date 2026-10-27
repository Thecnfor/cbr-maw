"""可选基础设施层：PostgreSQL / Redis / MongoDB / 向量库的**可降级**接入。

原则：基础设施全部**可选**。任一服务不可用（未装 Docker、未启动、缺驱动）时，
``probe_*`` 返回 ``available=False`` 与原因，调用方（实时抓取缓存、RAG 向量检索）
自动改用本地实现，绝不因此让系统启动失败或测试变红。

.. code-block:: python

    from cbr.infra import load_infra_settings, probe_all, get_redis

    settings = load_infra_settings()
    print(probe_all(settings))       # {服务: {available, detail, latency_ms}}
    cache = get_redis(settings)      # 不可用时返回 None
"""

from __future__ import annotations

from .clients import get_mongo, get_postgres, get_redis
from .config import InfraSettings, load_infra_settings
from .health import probe_all, probe_service

__all__ = [
    "InfraSettings",
    "get_mongo",
    "get_postgres",
    "get_redis",
    "load_infra_settings",
    "probe_all",
    "probe_service",
]
