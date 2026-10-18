"""核心模块就绪探测与服务获取。

约定（见 ``src/cbr/service.py`` 文档字符串与 ``src/cbr/contracts.py``）：
各核心模块必须提供工厂函数，``cbr.service.build_service()`` 才能完成装配：

- ``cbr.data.build_data_provider(settings)``
- ``cbr.knowledge.build_knowledge_base(settings)``
- ``cbr.tools.build_tool_registry(settings, provider, kb)``
- ``cbr.llm.build_llm_client(settings)``
- ``cbr.orchestration.build_orchestrator(settings, provider, registry, kb, llm)``

本模块只做「探测 + 获取」，不 import 上述实现模块（探测失败也不抛异常），
供 API（``/api/health``、503 降级）与 Streamlit 界面（就绪状态面板）共用。
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any

# 模块名 -> 必须存在的装配工厂函数（与 cbr.service.build_service 保持一致）
CORE_MODULES: dict[str, str] = {
    "cbr.data": "build_data_provider",
    "cbr.knowledge": "build_knowledge_base",
    "cbr.tools": "build_tool_registry",
    "cbr.llm": "build_llm_client",
    "cbr.orchestration": "build_orchestrator",
}


@dataclass
class ModuleStatus:
    """单个核心模块的就绪状态。"""

    module: str
    factory: str
    ready: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "factory": self.factory,
            "ready": self.ready,
            "detail": self.detail,
        }


def module_statuses() -> list[ModuleStatus]:
    """逐个探测核心模块是否可导入且暴露约定工厂函数（永不抛异常）。"""
    statuses: list[ModuleStatus] = []
    for module, factory in CORE_MODULES.items():
        status = ModuleStatus(module=module, factory=factory)
        statuses.append(status)
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError) as exc:  # 父包不存在 / 路径异常
            spec = None
            status.detail = f"无法解析模块：{type(exc).__name__}: {exc}"
        if spec is None:
            status.detail = status.detail or "模块尚未创建"
            continue
        try:
            imported = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - 探测阶段吞掉一切异常
            status.detail = f"导入失败：{type(exc).__name__}: {exc}"
            continue
        factory_fn = getattr(imported, factory, None)
        if callable(factory_fn):
            status.ready = True
        else:
            status.detail = f"缺少工厂函数 {factory}()"
    return statuses


def readiness_summary() -> dict[str, Any]:
    """核心模块整体就绪情况（供 /api/health 与界面状态面板使用）。"""
    statuses = module_statuses()
    ready_modules = [s.module for s in statuses if s.ready]
    pending_modules = [s.module for s in statuses if not s.ready]
    return {
        "ready": not pending_modules,
        "ready_modules": ready_modules,
        "pending_modules": pending_modules,
        "modules": [s.as_dict() for s in statuses],
    }


def acquire_service() -> tuple[Any | None, str | None]:
    """获取进程内 Service 单例。

    Returns:
        ``(service, error)``。成功时 ``error`` 为 ``None``；核心模块未就绪
        （或装配时抛出任何异常）时返回 ``(None, "ExceptionType: message")``，
        **不抛出**，由调用方决定如何降级。
    """
    # 延迟 import + 运行时取属性，便于测试 monkeypatch cbr.service.get_service
    from cbr import service as service_module

    try:
        return service_module.get_service(), None
    except Exception as exc:  # noqa: BLE001 - 装配失败统一降级
        return None, f"{type(exc).__name__}: {exc}"


def not_ready_message(error: str | None = None) -> str:
    """构造面向调用方/用户的中文未就绪提示。"""
    summary = readiness_summary()
    pending = summary.get("pending_modules") or []
    if pending:
        message = f"CBR-MAW 核心服务暂未就绪（待实现模块：{'、'.join(pending)}）"
        if error:
            message += f"；装配错误：{error}"
        message += (
            "。请先完成 data/knowledge/tools/llm/orchestration 五层模块并暴露约定工厂函数，"
            "或检查 PYTHONPATH=src / 依赖安装后重启服务。"
        )
        return message
    message = "CBR-MAW 核心服务装配失败"
    if error:
        message += f"：{error}"
    message += (
        "。五层模块均已存在，请检查数据文件（data/）、配置文件（configs/）与运行日志后重启服务；"
        "也可访问 /api/health 查看模块明细。"
    )
    return message


def settings_snapshot() -> dict[str, Any]:
    """安全读取 configs/app.yaml（不依赖核心模块；失败时返回 error 字段）。"""
    try:
        from cbr.config import load_settings

        settings = load_settings()
        return {
            "app_name": settings.app_name,
            "timezone": settings.timezone,
            "llm": {
                "provider": settings.llm.provider,
                "model": settings.llm.model,
                "mock": settings.llm.mock,
            },
            "server": settings.server.model_dump(),
            "data": {"dataset": settings.data.dataset, "pit_db": settings.data.pit_db},
            "orchestration": {
                "rounds": settings.orchestration.rounds,
                "modes": settings.orchestration.modes,
                "human_in_the_loop": settings.orchestration.human_in_the_loop,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
