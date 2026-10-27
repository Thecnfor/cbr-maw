"""可选基础设施层测试：探测、降级、客户端可用性（不依赖任何外部服务）。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from cbr.infra import get_mongo, get_postgres, get_redis, load_infra_settings, probe_all, probe_service


def test_load_infra_settings_defaults_off() -> None:
    settings = load_infra_settings()
    assert settings.enabled is False
    assert settings.vector.backend == "local"
    assert settings.vector.embedding.provider == "hashing"
    assert set(settings.service_map()) == {"postgres", "redis", "mongodb", "qdrant"}


def test_probe_service_closed_port_unavailable() -> None:
    result = probe_service("redis", "redis://127.0.0.1:1", timeout=0.2)
    assert result["available"] is False
    assert "不可达" in result["detail"]


def test_probe_service_open_socket_available() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        result = probe_service("postgres", f"postgresql://127.0.0.1:{port}/cbr", timeout=0.5)
        assert result["available"] is True
    finally:
        server.close()


def test_probe_all_marks_disabled_services() -> None:
    result = probe_all(load_infra_settings())
    assert all(item["available"] is False for item in result.values())
    assert result["redis"]["enabled"] is False


def test_clients_return_none_when_disabled() -> None:
    settings = load_infra_settings()
    settings.enabled = False
    assert get_redis(settings) is None
    assert get_postgres(settings) is None
    assert get_mongo(settings) is None


def test_clients_return_none_when_enabled_but_unreachable() -> None:
    settings = load_infra_settings()
    settings.enabled = True
    settings.redis.enabled = True
    settings.redis.url = "redis://127.0.0.1:1/0"
    # 驱动可能未安装或服务不可达，两种情况都必须优雅返回 None
    assert get_redis(settings) is None


def test_infra_config_file_exists() -> None:
    assert Path("configs/infra.yaml").exists()
    assert Path("docker-compose.yml").exists()
