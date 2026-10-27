"""基础设施健康探测：用标准库 socket 做 TCP 可达性 + 驱动可用性检查（无外部依赖）。

探测永不抛异常；结果形如 ``{"available": bool, "detail": str, "latency_ms": int|None}``。
"""

from __future__ import annotations

import importlib.util
import socket
import time
from typing import Any
from urllib.parse import urlparse

from .config import InfraSettings

#: 服务 -> 建议的 Python 驱动包（仅用于提示，不强制）
DRIVERS: dict[str, str] = {
    "postgres": "psycopg",
    "redis": "redis",
    "mongodb": "pymongo",
    "qdrant": "qdrant-client",
}


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    """从连接串中解析 host/port（兼容 redis://、postgresql://、mongodb://、http://）。"""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default_port
    return host, int(port)


def probe_service(name: str, url: str, timeout: float = 1.0) -> dict[str, Any]:
    """探测单个服务的 TCP 可达性（不验证认证/协议）。"""
    default_ports = {"postgres": 5432, "redis": 6379, "mongodb": 27017, "qdrant": 6333}
    host, port = _host_port(url, default_ports.get(name, 80))
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "available": True,
                "detail": f"TCP {host}:{port} 可达",
                "latency_ms": int((time.time() - started) * 1000),
                "driver": DRIVERS.get(name),
                "driver_installed": importlib.util.find_spec(DRIVERS[name]) is not None
                if name in DRIVERS
                else None,
            }
    except OSError as exc:
        return {
            "available": False,
            "detail": f"TCP {host}:{port} 不可达: {type(exc).__name__}: {exc}",
            "latency_ms": None,
            "driver": DRIVERS.get(name),
            "driver_installed": importlib.util.find_spec(DRIVERS[name]) is not None
            if name in DRIVERS
            else None,
        }


def probe_all(settings: InfraSettings | None = None) -> dict[str, dict[str, Any]]:
    """探测全部已启用服务；未启用的标注 ``enabled=False``。"""
    settings = settings or InfraSettings()
    out: dict[str, dict[str, Any]] = {}
    for name, (enabled, url) in settings.service_map().items():
        if not enabled:
            out[name] = {"available": False, "enabled": False, "detail": "未启用（configs/infra.yaml）"}
            continue
        result = probe_service(name, url, settings.probe_timeout_seconds)
        result["enabled"] = True
        out[name] = result
    return out
