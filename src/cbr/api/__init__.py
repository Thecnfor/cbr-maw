"""CBR-MAW API 层（L6）。

模块划分：
- ``readiness``：核心模块就绪探测 / 服务获取（纯 Python，无 FastAPI 依赖，UI 亦可复用）；
- ``state``：运行态缓存与证据/审计轨迹解析（纯 Python，API 与 Streamlit 共用）；
- ``main``：FastAPI 应用（``uvicorn cbr.api.main:app``）。

设计约束：本包**不 import** data/knowledge/tools/llm/orchestration 任何实现模块，
因此核心模块尚未就绪时 API 仍可启动，并以稳定的 ``503 + 中文提示`` 降级，
而不是抛出 500 或启动失败。
"""

from __future__ import annotations

__all__ = ["readiness", "state"]
