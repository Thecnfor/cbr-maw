"""LLM 抽象层工厂与导出。

约定（``cbr.service`` 装配契约）::

    from cbr.llm import build_llm_client
    llm = build_llm_client(settings)          # settings: AppSettings

模式选择规则（与 ``configs/app.yaml`` 注释一致）：

1. ``force_mock=True`` 或 ``settings.llm.mock=True`` → ``MockLLM``；
2. ``settings.llm.mock=False`` 且能解析到 API key → ``DeepSeekClient``；
3. ``settings.llm.mock=False`` 但无 key → ``MockLLM``（WARNING 日志说明原因）；
4. 真实客户端初始化失败（如缺 openai SDK）→ 回退 ``MockLLM``（WARNING）。

模式切换会在 logger ``cbr.llm`` 上输出明确提示（"MockLLM 模式"/"真实模型模式"），
``GET /api/health`` 也可通过 ``client.is_mock`` / ``client.mode`` 暴露当前状态。
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import AppSettings, LLMSettings
from ..contracts import LLMClient
from .base import (
    BaseLLMClient,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMUnavailableError,
    encode_packet,
    extract_packet,
    format_number,
    resolve_api_key,
)
from .deepseek import DeepSeekClient
from .drafts import (
    CrossCheckDraft,
    CrossCheckFinding,
    DraftClaim,
    RoleAnalysisDraft,
)
from .mock import MockLLM

__all__ = [
    "BaseLLMClient",
    "CrossCheckDraft",
    "CrossCheckFinding",
    "DeepSeekClient",
    "DraftClaim",
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMOutputError",
    "LLMUnavailableError",
    "MockLLM",
    "RoleAnalysisDraft",
    "build_llm_client",
    "encode_packet",
    "extract_packet",
    "format_number",
    "resolve_api_key",
]

logger = logging.getLogger("cbr.llm")


def _coerce_llm_settings(settings: Any | None) -> LLMSettings:
    if settings is None:
        from ..config import load_settings

        return load_settings().llm
    if isinstance(settings, LLMSettings):
        return settings
    if isinstance(settings, AppSettings):
        return settings.llm
    llm_settings = getattr(settings, "llm", None)
    if isinstance(llm_settings, LLMSettings):
        return llm_settings
    if isinstance(settings, dict):
        return LLMSettings(**settings)
    raise TypeError(
        "build_llm_client 需要 AppSettings / LLMSettings / 含 .llm 的配置对象，"
        f"收到 {type(settings)!r}"
    )


def build_llm_client(
    settings: Any | None = None,
    *,
    force_mock: bool = False,
    force_real: bool = False,
) -> LLMClient:
    """按配置构建 LLM 客户端（DeepSeek 或确定性 MockLLM）。"""

    llm_settings = _coerce_llm_settings(settings)

    if force_mock and force_real:
        raise ValueError("force_mock 与 force_real 不能同时为 True")

    if force_mock:
        logger.info("[LLM] 使用 MockLLM（确定性离线模式）：force_mock=True")
        return MockLLM()

    api_key = resolve_api_key(llm_settings)

    if force_real:
        return _build_deepseek(llm_settings, api_key, require_key=True)

    if llm_settings.mock:
        logger.info(
            "[LLM] 使用 MockLLM（确定性离线模式）：配置 llm.mock=true；"
            "如需真实模型请设置 %s 或写入 %s 并将 mock 置 false",
            llm_settings.api_key_env,
            llm_settings.api_key_file,
        )
        return MockLLM()

    if not api_key:
        logger.warning(
            "[LLM] 使用 MockLLM（确定性离线模式）：未检测到 API key"
            "（环境变量 %s / 文件 %s 均为空）",
            llm_settings.api_key_env,
            llm_settings.api_key_file,
        )
        return MockLLM()

    return _build_deepseek(llm_settings, api_key, require_key=True)


def _build_deepseek(
    llm_settings: LLMSettings,
    api_key: str | None,
    *,
    require_key: bool,
) -> LLMClient:
    if require_key and not api_key:
        raise LLMConfigError(
            "请求真实 DeepSeek 模式但未找到 API key：请设置环境变量 "
            f"{llm_settings.api_key_env!r} 或写入 {llm_settings.api_key_file!r}"
        )
    try:
        client = DeepSeekClient(llm_settings, api_key=api_key)
    except LLMError as exc:
        logger.warning("[LLM] 真实模型初始化失败，回退 MockLLM：%s", exc)
        return MockLLM()
    logger.info(
        "[LLM] 使用真实模型模式：provider=%s model=%s base_url=%s",
        client.provider,
        client.model,
        llm_settings.base_url,
    )
    return client
