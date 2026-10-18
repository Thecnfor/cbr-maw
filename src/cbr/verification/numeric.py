"""数值抽取与容差比对（核验器 / 黑板冲突检测共用纯函数）。

设计要点：
- 从 claim.text / recommendation 中抽取数字时，忽略年份与“5/10/20 日”这类
  时点口径数字，避免把风险期限误判为数值错误；
- 支持百分数归一化比较（92% <-> 0.92），用于容忍“分位/百分比”的两种写法；
- 相对容差与绝对容差同时生效（与 configs/app.yaml 的 orchestration 段一致）。
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

DEFAULT_ABS_TOL = 1e-6
DEFAULT_REL_TOL = 1e-3

# 普通的带符号数字（可带 % 后缀）
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?%?")
# “5/10/20 日”“5、10、20 个交易日”这类风险期限链，整体忽略
_HORIZON_CHAIN_RE = re.compile(r"\d+(?:\s*[/、]\s*\d+)+\s*(?:个?交易日|日|天)")
_PURE_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?%?")
_YEAR_MIN, _YEAR_MAX = 1900, 2100
_UNIT_SUFFIX_CHARS = set("日天月年周个点倍只股元万亿手张")


def extract_numbers(
    text: str,
    *,
    skip_years: bool = True,
    skip_unit_numbers: bool = True,
) -> list[float]:
    """从文本中抽取数值（按出现顺序）。

    - 跳过 1900-2100 的整数年份（不含小数/百分号）；
    - 跳过紧跟“日/天/月/年/周/个”等量词的数字（如“5 日”）；
    - 跳过“5/10/20 日”整条期限链。
    """
    if not text:
        return []
    cleaned = _HORIZON_CHAIN_RE.sub(" ", str(text))
    out: list[float] = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group(0)
        is_percent = raw.endswith("%")
        body = raw[:-1] if is_percent else raw
        try:
            value = float(body)
        except ValueError:  # pragma: no cover - 正则已保证可转
            continue
        if (
            skip_years
            and not is_percent
            and "." not in body
            and body.isdigit()
            and _YEAR_MIN <= value <= _YEAR_MAX
        ):
            continue
        if skip_unit_numbers:
            tail = cleaned[match.end():]
            nxt = next((ch for ch in tail if not ch.isspace()), "")
            if nxt and nxt in _UNIT_SUFFIX_CHARS:
                continue
        # 标识符里的数字（如 var_95、h20、5d）不是数量断言，跳过
        prev_char = cleaned[match.start() - 1] if match.start() > 0 else ""
        next_char = cleaned[match.end()] if match.end() < len(cleaned) else ""
        if prev_char and prev_char.isascii() and (prev_char.isalnum() or prev_char == "_"):
            continue
        if next_char and next_char.isascii() and (next_char.isalpha() or next_char == "_"):
            continue
        out.append(value)
    return out


def _close(a: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    scale = max(abs(a), abs(b), 1e-12)
    return diff / scale <= rel_tol


def numbers_match(
    a: float | int | None,
    b: float | int | None,
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
) -> bool:
    """容差比较两个数值；允许百分数写法互换（92 <-> 0.92）。"""
    if a is None or b is None:
        return False
    try:
        left, right = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(left) and math.isfinite(right)):
        return False
    if _close(left, right, abs_tol, rel_tol):
        return True
    # 百分数归一化：92% 与 0.92 等价；41 与 0.41 也允许（文本误写百分点）
    if _close(left / 100.0, right, abs_tol, rel_tol):
        return True
    if _close(left, right / 100.0, abs_tol, rel_tol):
        return True
    return False


def matches_any(
    value: float | int | None,
    candidates: list[float] | tuple[float, ...],
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
) -> bool:
    """value 是否与候选集合中任一数值在容差内一致。"""
    if value is None:
        return False
    return any(numbers_match(value, cand, abs_tol, rel_tol) for cand in candidates)


def flatten_numbers(
    obj: Any,
    *,
    max_items: int = 500,
    _out: list[float] | None = None,
) -> list[float]:
    """递归收集 dict/list/标量中的数值叶子（跳过 bool 与任意文本）。"""
    out: list[float] = [] if _out is None else _out
    if len(out) >= max_items:
        return out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        val = float(obj)
        if math.isfinite(val):
            out.append(val)
        return out
    if isinstance(obj, str):
        text = obj.strip()
        if text and _PURE_NUMBER_RE.fullmatch(text):
            try:
                out.append(float(text[:-1] if text.endswith("%") else text))
            except ValueError:  # pragma: no cover
                pass
        return out
    if isinstance(obj, Mapping):
        for value in obj.values():
            flatten_numbers(value, max_items=max_items, _out=out)
            if len(out) >= max_items:
                break
        return out
    if isinstance(obj, (list, tuple, set, frozenset)):
        for value in obj:
            flatten_numbers(value, max_items=max_items, _out=out)
            if len(out) >= max_items:
                break
    return out


def closest_number(value: float, candidates: list[float]) -> float | None:
    """返回候选集中距离 value 最近的数值（用于在工具 payload 中定位主指标）。"""
    if not candidates:
        return None
    return min(candidates, key=lambda cand: abs(float(cand) - float(value)))


__all__ = [
    "DEFAULT_ABS_TOL",
    "DEFAULT_REL_TOL",
    "extract_numbers",
    "numbers_match",
    "matches_any",
    "flatten_numbers",
    "closest_number",
]
