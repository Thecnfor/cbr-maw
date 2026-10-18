"""DeepSeek 真实 LLM 客户端（OpenAI 兼容接口）。

要点（对应 task-3 验收）：

- 通过 ``openai`` SDK 调用 ``base_url=https://api.deepseek.com``（可配置）；
- **JSON 输出**：``response_format={"type": "json_object"}`` + 把 Pydantic JSON
  Schema 写入 system prompt，再用 ``model_validate_json`` 强校验；
- **重试**：网络/限流/5xx 走指数退避重试；schema 校验失败自动附带错误信息
  "修复重试"（最多 ``max_retries+1`` 轮），两次失败抛 ``LLMOutputError``；
- **超时**：OpenAI client 与每次请求都传 ``settings.timeout_seconds``；
- **token 统计**：每次 API 响应写入 ``usage``（含失败重试消耗的 token）；
- **key 安全**：只从 ``settings.api_key_env`` 环境变量 / ``.env`` /
  ``settings.api_key_file`` 读取，构造函数也可注入（测试用），不硬编码。

单元测试可以注入 ``client``（假 OpenAI 客户端）与 ``sleep_fn``（假等待），
从而在无网络、无 key、无等待的情况下验证全部真实路径逻辑。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..config import LLMSettings
from .base import (
    BaseLLMClient,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMUnavailableError,
    resolve_api_key,
)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_ALLOWED_KWARGS = {
    "temperature",
    "max_tokens",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "stop",
}

_REPAIR_TEMPLATE = (
    "\n\n[输出修复要求]\n"
    "上一次输出未通过 JSON Schema 校验，请**只输出一个 JSON 对象**（不要 markdown 代码块、"
    "不要解释文字），逐项修正下列问题后重新输出：\n{errors}\n"
    "允许的顶层字段：{fields}\n"
    "字段结构必须符合以下 JSON Schema：\n{schema}"
)


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _is_retryable(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS
    name = type(exc).__name__
    return any(
        token in name
        for token in (
            "Timeout",
            "Connection",
            "RateLimit",
            "InternalServer",
            "ServiceUnavailable",
            "APIError",
        )
    )


class DeepSeekClient(BaseLLMClient):
    """DeepSeek（OpenAI 兼容）结构化/文本客户端。"""

    provider = "deepseek"
    is_mock = False

    def __init__(
        self,
        settings: LLMSettings,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        logger: logging.Logger | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.model or "deepseek-chat"
        self._logger = logger or logging.getLogger("cbr.llm.deepseek")
        self._sleep = sleep_fn or time.sleep
        self._transport_attempts = 0

        if client is not None:
            # 测试注入：不要求 key、不导入 openai SDK
            self._client = client
            self._api_key = api_key
        else:
            self._api_key = api_key or resolve_api_key(settings)
            self._client = None
            if not self._api_key:
                raise LLMConfigError(
                    "未找到 DeepSeek API key：请设置环境变量 "
                    f"{settings.api_key_env!r} 或写入 {settings.api_key_file!r}"
                )

    # ------------------------------------------------------------------ #
    # 协议实现
    # ------------------------------------------------------------------ #
    def structured(
        self, system: str, user: str, schema: type, **kwargs: Any
    ) -> BaseModel:  # type: ignore[override]
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise LLMError(f"structured 需要 Pydantic model schema，收到 {schema!r}")

        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, sort_keys=True)
        system_content = (
            f"{system}\n\n[结构化输出要求] 你必须返回**单个 JSON 对象**（不要 markdown "
            f"代码块或额外解释），且严格符合以下 JSON Schema：\n{schema_json}"
        )
        max_schema_attempts = max(1, min(3, int(self.settings.max_retries) + 1))
        user_content = user
        last_error: ValidationError | None = None
        raw_output = ""
        last_content = ""

        for attempt in range(max_schema_attempts):
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ]
            response = self._create_completion(messages=messages, schema=schema, **kwargs)
            raw_output = self._extract_content(response)
            last_content = raw_output
            try:
                parsed = self._parse_json(schema, raw_output)
            except ValidationError as exc:
                last_error = exc
                self._logger.warning(
                    "[LLM] DeepSeek 输出未通过 schema 校验（第 %d/%d 轮）：%s",
                    attempt + 1,
                    max_schema_attempts,
                    _format_errors(exc),
                )
                user_content = user + _REPAIR_TEMPLATE.format(
                    errors=_format_errors(exc),
                    fields=", ".join(schema.model_fields.keys()),
                    schema=schema_json,
                )
                continue
            self._set_last_call(
                mode=f"{self.provider}:{self.model}",
                provider=self.provider,
                model=self.model,
                schema=schema.__name__,
                attempts=attempt + 1,
                transport_attempts=self._transport_attempts,
                prompt_chars=len(system_content) + len(user_content),
                completion_chars=len(raw_output),
                json_mode=True,
            )
            return parsed

        self._set_last_call(
            mode=f"{self.provider}:{self.model}",
            provider=self.provider,
            model=self.model,
            schema=schema.__name__,
            attempts=max_schema_attempts,
            transport_attempts=self._transport_attempts,
            completion_chars=len(last_content),
            json_mode=True,
            failed=True,
        )
        raise LLMOutputError(
            f"DeepSeek 输出在 {max_schema_attempts} 轮重试后仍不符合 {schema.__name__}："
            f"{_format_errors(last_error) if last_error else '空输出'}",
            raw_output=raw_output,
            attempts=max_schema_attempts,
        )

    def text(self, system: str, user: str, **kwargs: Any) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response = self._create_completion(messages=messages, text_mode=True, **kwargs)
        content = self._extract_content(response)
        self._set_last_call(
            mode=f"{self.provider}:{self.model}",
            provider=self.provider,
            model=self.model,
            attempts=1,
            transport_attempts=self._transport_attempts,
            prompt_chars=len(system) + len(user),
            completion_chars=len(content),
            json_mode=False,
        )
        return content

    # ------------------------------------------------------------------ #
    # OpenAI 调用封装（传输层重试 + 用量统计）
    # ------------------------------------------------------------------ #
    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖缺失时
            raise LLMConfigError(
                "真实 DeepSeek 模式需要 openai SDK：请先安装 openai>=1.50"
            ) from exc
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self.settings.base_url or "https://api.deepseek.com",
            timeout=float(self.settings.timeout_seconds),
            # SDK 自带重试会绕过我们的 token/审计统计，这里全部自己管理
            max_retries=0,
        )
        return self._client

    def _create_completion(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """调用 chat.completions.create，做传输层指数退避重试并记录用量。"""

        client = self._ensure_client()
        schema = kwargs.pop("schema", None)
        text_mode = bool(kwargs.pop("text_mode", False))
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": float(kwargs.pop("temperature", self.settings.temperature)),
            "max_tokens": int(kwargs.pop("max_tokens", self.settings.max_tokens)),
            "timeout": float(self.settings.timeout_seconds),
        }
        for key in list(kwargs.keys()):
            if key in _ALLOWED_KWARGS:
                params[key] = kwargs.pop(key)
            else:  # 忽略未知参数，避免 API 端 400
                kwargs.pop(key)
        if not text_mode:
            params["response_format"] = {"type": "json_object"}

        attempts = max(1, int(self.settings.max_retries) + 1)
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            self._transport_attempts = attempt + 1
            try:
                response = client.chat.completions.create(**params)
            except Exception as exc:  # noqa: BLE001 - 需要按 SDK 异常分类
                last_exc = exc
                status = _status_code(exc)
                if attempt + 1 >= attempts or not _is_retryable(exc):
                    break
                delay = min(2.0, 0.5 * (2**attempt))
                self._logger.warning(
                    "[LLM] DeepSeek 调用失败（attempt %d/%d, status=%s），%.1fs 后重试：%s",
                    attempt + 1,
                    attempts,
                    status,
                    delay,
                    exc,
                )
                self._sleep(delay)
                continue
            self._record_response_usage(response)
            return response

        raise LLMUnavailableError(
            f"DeepSeek 调用失败（已重试 {attempts} 次）: {last_exc}"
        ) from last_exc

    def _record_response_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        self._record_usage(prompt_tokens, completion_tokens, calls=1)

    # ------------------------------------------------------------------ #
    # 输出解析
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_content(response: Any) -> str:
        try:
            choices = response.choices
            message = choices[0].message
            content = message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMError(f"无法从 DeepSeek 响应中读取 content：{exc!r}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMOutputError("DeepSeek 返回空 content", raw_output=str(content or ""))
        return content

    @staticmethod
    def _parse_json(schema: type[BaseModel], raw: str) -> BaseModel:
        text = _strip_code_fence(raw)
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            # 兜底：从文本中截取第一个 { 到最后一个 }（有些模型会带说明文字）
            start, end = text.find("{"), text.rfind("}")
            if 0 <= start < end:
                try:
                    return schema.model_validate_json(text[start : end + 1])
                except ValidationError:
                    raise exc from None
            raise


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _format_errors(exc: ValidationError | None) -> str:
    if exc is None:
        return "无可用错误信息"
    formatted: list[str] = []
    for error in exc.errors(include_url=False)[:5]:
        loc = ".".join(str(part) for part in error.get("loc", ()))
        formatted.append(f"- {loc}: {error.get('msg', 'invalid')}")
    return "\n".join(formatted) or "未知校验错误"
