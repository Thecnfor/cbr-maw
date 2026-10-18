"""LLM 抽象层公共基类、异常、用量统计与证据包编解码。

设计要点（对应论文 4.2/4.3 与 ``contracts.LLMClient``）：

- 所有 LLM 实现共享同一接口：``structured`` 返回 Pydantic 对象，``text`` 返回字符串；
- 用量统一累计到 ``usage``：``prompt_tokens`` / ``completion_tokens`` /
  ``total_tokens`` / ``calls``，编排层据此做 token 预算对齐（P3 可比性）；
- 真实模型与 mock 模型共享同一调用契约。RoleAgent 会把机器可读的"证据包"
  （EVIDENCE_PACKET）嵌入 user prompt，MockLLM 依此做确定性生成；真实模型也会
  看到同一份证据包，但主要依赖 system prompt 中的输出 schema 说明。
- 本模块不依赖 openai SDK；只有 ``deepseek.py`` 在真正调用时才惰性导入。
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..config import LLMSettings, resolve_path

T = TypeVar("T", bound=BaseModel)

# --------------------------------------------------------------------------- #
# 证据包标记：RoleAgent 把机器可读证据包序列化后嵌入 user prompt
# --------------------------------------------------------------------------- #
PACKET_START = "<<<CBR_EVIDENCE_PACKET>>>"
PACKET_END = "<<<END_CBR_EVIDENCE_PACKET>>>"
_PACKET_RE = re.compile(
    re.escape(PACKET_START) + r"\s*(.*?)\s*" + re.escape(PACKET_END), re.DOTALL
)

LLM_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "calls")


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class LLMError(RuntimeError):
    """LLM 调用层异常基类。"""


class LLMConfigError(LLMError):
    """配置错误（缺少 key、缺少 SDK 等），通常可在工厂层回退 mock。"""


class LLMOutputError(LLMError):
    """模型输出无法解析/不符合 schema，且重试后仍失败。"""

    def __init__(self, message: str, *, raw_output: str = "", attempts: int = 0) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.attempts = attempts


class LLMUnavailableError(LLMError):
    """网络/服务不可用（超时、限流、连接失败）重试耗尽后抛出。"""


# --------------------------------------------------------------------------- #
# 序列化工具
# --------------------------------------------------------------------------- #
def dumps(value: Any, *, indent: int | None = None) -> str:
    """稳健的 JSON 序列化（中文不转义、日期转字符串、键排序保证确定性）。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        default=str,
    )


def extract_packet(prompt: str) -> dict[str, Any] | None:
    """从 prompt 中提取证据包；不存在或解析失败返回 None。"""

    match = _PACKET_RE.search(prompt or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def encode_packet(payload: dict[str, Any]) -> str:
    """把证据包编码为带标记的文本块（确定性：键排序）。"""

    return f"{PACKET_START}\n{dumps(payload)}\n{PACKET_END}"


def format_number(value: float) -> str:
    """确定性数值格式化：整数不带小数点，其余保留 6 位有效数字。

    统一数字串格式是为了让"数值核验器从 claim.text 抽取数字"能稳定匹配
    ``claim.value``（避免 0.4800000000000001 之类的浮点噪声）。
    """

    number = float(value)
    if number.is_integer() and abs(number) < 1e12:
        return str(int(number))
    return f"{number:.6g}"


# --------------------------------------------------------------------------- #
# API key 解析（环境变量 > .env > secrets 文件；绝不硬编码）
# --------------------------------------------------------------------------- #
def resolve_api_key(settings: LLMSettings) -> str | None:
    """按优先级解析 API key：进程环境变量 > .env > ``settings.api_key_file``。"""

    env_name = settings.api_key_env or "DEEPSEEK_API_KEY"
    key = os.environ.get(env_name, "").strip()
    if key:
        return key

    # .env（若安装 python-dotenv）；load_dotenv 不覆盖已有环境变量
    try:
        from dotenv import load_dotenv  # type: ignore

        env_file = resolve_path(".env")
        if env_file.exists():
            load_dotenv(env_file, override=False)
        key = os.environ.get(env_name, "").strip()
        if key:
            return key
    except ImportError:  # pragma: no cover - dotenv 是可选依赖
        pass

    if settings.api_key_file:
        key_file: Path = resolve_path(settings.api_key_file)
        if key_file.exists():
            content = key_file.read_text(encoding="utf-8").strip()
            if content:
                return content
    return None


# --------------------------------------------------------------------------- #
# 基类
# --------------------------------------------------------------------------- #
class BaseLLMClient(ABC):
    """LLM 客户端基类：统一用量统计 / 模式标记 / 最近一次调用元数据。"""

    provider: str = "base"
    model: str = ""
    is_mock: bool = False

    def __init__(self) -> None:
        self._usage: dict[str, int] = {key: 0 for key in LLM_USAGE_KEYS}
        self._last_call: dict[str, Any] = {}

    # -- 协议属性 ---------------------------------------------------------
    @property
    def usage(self) -> dict[str, int]:
        """累计用量 ``{"prompt_tokens","completion_tokens","total_tokens","calls"}``。"""

        return dict(self._usage)

    @property
    def last_call(self) -> dict[str, Any]:
        """最近一次调用的元数据（模式、重试次数、字符数等），供 trace 记录。"""

        return dict(self._last_call)

    @property
    def mode(self) -> str:
        """人类可读模式标识，写入 trace / 日志。"""

        return "mock" if self.is_mock else f"{self.provider}:{self.model}"

    # -- 用量统计 ---------------------------------------------------------
    def reset_usage(self) -> None:
        for key in self._usage:
            self._usage[key] = 0

    def _record_usage(
        self, prompt_tokens: int = 0, completion_tokens: int = 0, *, calls: int = 1
    ) -> None:
        prompt_tokens = max(0, int(prompt_tokens))
        completion_tokens = max(0, int(completion_tokens))
        self._usage["prompt_tokens"] += prompt_tokens
        self._usage["completion_tokens"] += completion_tokens
        self._usage["total_tokens"] += prompt_tokens + completion_tokens
        self._usage["calls"] += max(0, int(calls))

    def usage_delta(self, before: dict[str, int]) -> dict[str, int]:
        """计算相对 ``before`` 快照的用量增量（供单次调用 trace 统计）。"""

        return {key: self._usage.get(key, 0) - before.get(key, 0) for key in LLM_USAGE_KEYS}

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略 token 估计（中文约 1.8 字符/token，英文约 4 字符/token）。

        与 DeepSeek 实际分词比例接近，使 mock 模式的 token 预算统计对真实模式
        有参考意义（不刻意高估，避免演示时误触发 token_budget_exceeded）。
        """

        if not text:
            return 0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return max(1, int(cjk / 1.8 + other / 4.0))

    def _set_last_call(self, **meta: Any) -> None:
        self._last_call = dict(meta)

    # -- 协议方法 ---------------------------------------------------------
    @abstractmethod
    def structured(
        self, system: str, user: str, schema: type[T], **kwargs: Any
    ) -> T:
        """要求模型输出符合给定 Pydantic schema 的结构化结果。"""

    @abstractmethod
    def text(self, system: str, user: str, **kwargs: Any) -> str:
        """自由文本生成（用于对话入口/汇总）。"""
