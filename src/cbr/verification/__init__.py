"""横切 A：验证与审计层。

对外只暴露两个稳定入口：

- :func:`cbr.verification.verifier.verify`：一次决策卡的六类核验；
- :class:`cbr.verification.trace.TraceWriter` / :func:`read_trace`：JSONL 审计 trace。
"""

from .numeric import extract_numbers, flatten_numbers, numbers_match
from .trace import (
    TraceWriter,
    events_to_dicts,
    hash_obj,
    make_run_id,
    read_trace,
    resolve_trace_path,
    trace_ref_for,
)
from .verifier import resolve_tolerances, verify

__all__ = [
    "verify",
    "resolve_tolerances",
    "TraceWriter",
    "read_trace",
    "make_run_id",
    "resolve_trace_path",
    "trace_ref_for",
    "events_to_dicts",
    "hash_obj",
    "extract_numbers",
    "flatten_numbers",
    "numbers_match",
]
