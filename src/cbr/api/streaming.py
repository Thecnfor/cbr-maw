"""SSE 流式端点（AI-native 交互升级，契约见 ``docs/design/ai-native-interaction-spec.md`` §1）。

新增两个与同步端点并存的流式接口：

- ``GET  /api/decision/stream``：查询参数同 ``/api/decision``；
  事件 ``run / stage / trace / decision / error`` + 心跳 ``: ping``；
- ``POST /api/chat/stream``：body 同 ``ChatRequest``；
  事件 ``run / stage / trace / chat / error`` + 心跳 ``: ping``。

实现要点（与 spec §1 对齐）：

1. **缓存**：决策命中 30 分钟缓存（``refresh=false``）时立即推 ``decision``，不构建编排器；
2. **隔离**：每次真实请求在 ``artifacts/traces/stream-<uuid>/`` 下创建**独立 trace 目录**，
   并用 ``build_orchestrator(..., trace_dir=...)`` 构建独立编排器——避免并发请求共享
   ``OrchestratorImpl._last_board`` 等可变状态，也让每个请求的 trace 互不干扰；
3. **后台线程 + tail**：线程执行 ``run``/``chat``；生成器增量 tail 该目录最新 ``*.jsonl``，
   按**完整行**解析 ``TraceEvent`` 推 ``trace``，发现首个 trace 文件即发 ``run``；
   并按 spec §1.3 用 :func:`map_trace_to_stage` 推 ``stage``；
4. **健壮性**：每 :data:`HEARTBEAT_SECONDS` 秒 ``: ping``；总超时默认 300s
   （``CBR_STREAM_TIMEOUT`` 可覆盖）；客户端断开后生成器停止 tail，后台线程允许自然结束
   （daemon，不阻塞响应关闭）；线程异常 / 契约不符 / 服务未就绪一律以 SSE ``error`` 事件
   上报（HTTP 状态仍为 200，data 为 ``{"status": ..., "message": 中文说明}``）。

本模块不在 import 阶段加载任何核心实现模块（``build_orchestrator`` 惰性导入），
因此核心未就绪时 API 仍可启动并返回可读的 SSE 错误事件。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from cbr.api import readiness, state as api_state
from cbr.schemas import ChatRequest, ChatResponse, DecisionCard, TraceEvent

#: 与 ``main.MODE_LITERAL`` 保持一致（仅用于查询参数校验/文档）。
MODE_LITERAL = Literal["collaborative", "independent", "single"]

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

#: 心跳间隔（秒）；代理/浏览器通常在 30–60s 无数据时断连，10s 心跳足够保守。
HEARTBEAT_SECONDS = 10.0
#: 单次流式请求的总超时（秒）；上游 LLM 单次决策约 15s，300s 覆盖最坏重试。
STREAM_TIMEOUT_SECONDS = float(os.environ.get("CBR_STREAM_TIMEOUT", "300"))
#: tail 轮询间隔（秒）；0.1s 对新事件已是「即时」，同时避免空转占满 CPU。
POLL_INTERVAL_SECONDS = float(os.environ.get("CBR_STREAM_POLL_INTERVAL", "0.1"))

#: 角色 -> 中文主体名（spec §1.3）；未知/单智能体角色回退为通用智能体。
ROLE_DISPLAY: dict[str, str] = {
    "regulator": "监管主体",
    "investor": "投资主体",
    "financing": "融资主体",
    "coordinator": "协调者",
    "verifier": "核验器",
}
DEFAULT_ROLE_DISPLAY = "通用智能体"

#: TraceEvent.action -> (stage, label, status)，label 中的 ``{role}`` 按角色替换。
#: 未列出的 action（tool_call / claim / verify / budget_exceeded ...）只推 ``trace``，不推 ``stage``。
STAGE_RULES: dict[str, tuple[str, str, str]] = {
    "run_start": ("R0", "初始化协同分析", "started"),
    "analysis_start": ("R0", "{role}分析中", "started"),
    "analysis_done": ("R0", "{role}分析完成", "finished"),
    "evidence_share": ("R1", "证据共享与去重", "started"),
    "evidence_share_summary": ("R1", "证据共享完成", "finished"),
    "cross_check": ("R2", "交叉验证关键数值", "started"),
    "cross_check_summary": ("R2", "交叉验证关键数值", "finished"),
    "conflict_detection": ("R3", "分歧识别", "started"),
    "conflict_resolution": ("R4", "冲突协调", "started"),
    "coordination_round": ("R4", "冲突协调", "started"),
    "finalize": ("R5", "汇总决策卡", "finished"),
}

#: 独立 trace 目录保留上限（按 mtime 清理最旧目录，避免 `artifacts/traces/stream-*` 无限增长）。
STREAM_TRACE_RETENTION = int(os.environ.get("CBR_STREAM_TRACE_RETENTION", "50"))

router = APIRouter(tags=["流式"])


# --------------------------------------------------------------------------- #
# SSE 序列化
# --------------------------------------------------------------------------- #
def sse_event(name: str, data: Any) -> str:
    """序列化一个 SSE 事件（``event:`` + 单行 ``data:``）。

    ``json.dumps`` 会把换行/回车转义成 ``\\n`` / ``\\r``，因此 data 始终是单行；
    这里再做一次防御性替换，保证不会因为意外字符串打断 SSE 帧。
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    payload = payload.replace("\r", "\\r").replace("\n", "\\n")
    return f"event: {name}\ndata: {payload}\n\n"


def sse_ping() -> str:
    """SSE 注释心跳（浏览器 EventSource 会忽略注释，但代理不会判定连接空闲）。"""
    return ": ping\n\n"


# --------------------------------------------------------------------------- #
# trace -> stage 映射（spec §1.3）
# --------------------------------------------------------------------------- #
def _iso_timestamp(value: Any) -> str:
    """统一成与 ``TraceEvent.model_dump(mode="json")`` 一致的 ISO 文本（UTC 用 ``Z``）。"""
    if isinstance(value, dt.datetime):
        text = value.isoformat()
        if text.endswith("+00:00"):
            return f"{text[:-6]}Z"
        return text
    if isinstance(value, str) and value:
        return value
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _stage_root(step: Any) -> str | None:
    """从 ``TraceEvent.step`` 取阶段根（``R0:regulator`` -> ``R0``）。"""
    if not isinstance(step, str):
        return None
    root = step.strip().split(":", 1)[0].strip().upper()
    return root if root in {"R0", "R1", "R2", "R3", "R4", "R5"} else None


def map_trace_to_stage(event: TraceEvent | dict[str, Any]) -> dict[str, Any] | None:
    """把一条 trace 事件映射为 ``stage`` 事件 data；未命中映射表时返回 ``None``。

    一致性保护：智能体内部 trace 也会复用 ``finalize`` 等 action（step 形如
    ``R0:regulator``），若把这类事件也映射成 R5 会让进度条提前跳到汇总阶段。
    因此当事件 step 明确带阶段根且与映射阶段不一致时，视为不映射（只推 ``trace``）。
    """
    if isinstance(event, TraceEvent):
        action = event.action or ""
        role = event.role
        ts = event.ts
        step = event.step
    elif isinstance(event, dict):
        action = str(event.get("action") or "")
        role = event.get("role")
        ts = event.get("ts")
        step = event.get("step")
    else:  # pragma: no cover - 调用方保证类型
        return None
    rule = STAGE_RULES.get(action)
    if rule is None:
        return None
    stage, label, status = rule
    step_root = _stage_root(step)
    if step_root is not None and step_root != stage:
        return None
    role_value = str(role) if role else None
    display = ROLE_DISPLAY.get(role_value or "", DEFAULT_ROLE_DISPLAY)
    return {
        "stage": stage,
        "label": label.format(role=display),
        "role": role_value,
        "status": status,
        "action": action,
        "ts": _iso_timestamp(ts),
    }


# --------------------------------------------------------------------------- #
# trace 目录 / 增量 tail
# --------------------------------------------------------------------------- #
def _default_artifacts_dir() -> Path:
    try:
        from cbr.config import load_settings, resolve_path

        return resolve_path(load_settings().paths.artifacts)
    except Exception:  # noqa: BLE001 - 配置不可用时仍允许流式端点工作
        import tempfile

        return Path(tempfile.gettempdir()) / "cbr-artifacts"


def _traces_root(service: Any) -> Path:
    """解析 trace 父目录：优先 ``Service.artifacts_dir()``，其次 configs/app.yaml。"""
    try:
        base = Path(service.artifacts_dir())
    except Exception:  # noqa: BLE001 - 服务可能未提供该方法
        base = _default_artifacts_dir()
    return base / "traces"


def _prune_stream_trace_dirs(root: Path) -> None:
    """按保留上限清理最旧的 ``stream-*`` 目录（失败静默，不影响流式请求）。"""
    try:
        dirs = [item for item in root.glob("stream-*") if item.is_dir()]
        if len(dirs) < STREAM_TRACE_RETENTION:
            return
        dirs.sort(key=lambda item: item.stat().st_mtime)
        excess = len(dirs) - STREAM_TRACE_RETENTION + 1
        for old in dirs[:excess]:
            try:
                shutil.rmtree(old)
            except OSError:
                continue
    except OSError:  # pragma: no cover - 目录不可读/并发删除
        return


def new_stream_trace_dir(service: Any) -> Path:
    """为一次流式请求创建独立 trace 目录（``artifacts/traces/stream-<uuid>/``）。"""
    root = _traces_root(service)
    _prune_stream_trace_dirs(root)
    directory = root / f"stream-{uuid.uuid4().hex[:12]}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _parse_trace_line(raw: bytes) -> TraceEvent | None:
    """把一行 JSONL 解析为 TraceEvent；坏行/半行返回 ``None``（不打断整条流）。"""
    line = raw.strip()
    if not line:
        return None
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        return TraceEvent.model_validate(payload)
    except ValidationError:
        return None


class TraceTailer:
    """增量 tail 一个目录下最新 ``*.jsonl``（只解析完整行，容忍半行/坏行）。

    文件一旦确定就不再切换（一次 run 只写一个文件）；首次 :meth:`discover` 时才选取
    该目录中最新文件——即 ``run`` 事件能尽早携带 run_id。
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.path: Path | None = None
        self._offset = 0
        self._buffer = b""

    def _latest(self) -> Path | None:
        try:
            files = [item for item in self.directory.glob("*.jsonl") if item.is_file()]
        except OSError:  # pragma: no cover - 目录被删除/无权限
            return None
        if not files:
            return None
        try:
            files.sort(key=lambda item: (item.stat().st_mtime, item.name))
        except OSError:  # pragma: no cover
            files.sort(key=lambda item: item.name)
        return files[-1]

    def discover(self) -> Path | None:
        """返回已发现的 trace 文件；尚未出现时返回 ``None``。"""
        if self.path is None:
            self.path = self._latest()
        return self.path

    def read_new(self) -> list[TraceEvent]:
        """读取自上次调用以来新增的完整行（返回解析成功的事件）。"""
        path = self.path or self.discover()
        if path is None:
            return []
        try:
            with path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
        except OSError:  # pragma: no cover - 写端可能刚创建/删除文件
            return []
        if not chunk:
            return []
        self._offset += len(chunk)
        self._buffer += chunk
        events: list[TraceEvent] = []
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            event = _parse_trace_line(line)
            if event is not None:
                events.append(event)
        return events


# --------------------------------------------------------------------------- #
# 编排器 / 线程
# --------------------------------------------------------------------------- #
def build_stream_orchestrator(service: Any, trace_dir: str | Path) -> Any:
    """为单次流式请求构建独立编排器（模块级函数，测试可 monkeypatch）。"""
    from cbr.orchestration import build_orchestrator

    return build_orchestrator(
        getattr(service, "settings", None),
        getattr(service, "provider", None),
        getattr(service, "registry", None),
        getattr(service, "kb", None),
        getattr(service, "llm", None),
        trace_dir=str(trace_dir),
    )


class _RunState:
    """后台线程与生成器之间的一次运行状态（线程只写、生成器只读）。"""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


def _worker(work: Callable[[], Any], state: _RunState) -> None:
    try:
        state.result = work()
    except BaseException as exc:  # noqa: BLE001 - 线程内异常统一通过 error 事件上报
        state.error = exc
    finally:
        state.done.set()


def _failure_message(action: str, exc: BaseException) -> str:
    return (
        f"核心服务执行失败（流式{action}）：{type(exc).__name__}: {exc}。"
        "请查看服务日志与 /api/health 确认模块状态；也可改用同步端点重试。"
    )


def _coerce(model: type[Any], raw: Any, action: str) -> Any:
    """把编排层返回值校验为契约模型；不合约时抛 ValueError（由 error 事件上报）。"""
    if isinstance(raw, model):
        return raw
    try:
        return model.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"编排层返回的{action}不符合 schemas.py 契约：{type(exc).__name__}: {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# 延迟引用 main（避免 main -> streaming -> main 循环 import）
# --------------------------------------------------------------------------- #
def _default_as_of(service: Any, scenario: str | None) -> dt.date:
    from cbr.api import main as api_main

    return api_main._default_as_of(service, scenario)


def _cache_key(as_of: dt.date, mode: str, scenario: str | None) -> tuple[str, str, str]:
    from cbr.api import main as api_main

    return api_main._decision_cache_key(as_of, mode, scenario)


def _cache_get(key: tuple[str, str, str]) -> DecisionCard | None:
    from cbr.api import main as api_main

    return api_main._decision_cache_get(key)


def _cache_put(key: tuple[str, str, str], card: DecisionCard) -> None:
    from cbr.api import main as api_main

    api_main._decision_cache_put(key, card)


# --------------------------------------------------------------------------- #
# 通用流式生成器
# --------------------------------------------------------------------------- #
def _stream_events(
    kind: Literal["decision", "chat"],
    *,
    service: Any,
    request: ChatRequest | None = None,
    as_of: dt.date | None = None,
    scenario: str | None = None,
    mode: str = "collaborative",
    cache_key: tuple[str, str, str] | None = None,
) -> Iterator[str]:
    """真实执行的流式事件序列（不含缓存命中的 ``decision`` 短路）。"""
    action = "对话推理" if kind == "chat" else "生成预警决策"
    trace_dir = new_stream_trace_dir(service)
    orchestrator = build_stream_orchestrator(service, trace_dir)

    if kind == "chat":
        if request is None:
            raise ValueError("chat 流式请求缺少 ChatRequest")
        chat_request = request

        def work() -> Any:
            return orchestrator.chat(chat_request)
    else:
        if as_of is None:
            raise ValueError("decision 流式请求缺少 as_of")
        target_date = as_of

        def work() -> Any:
            return orchestrator.run(target_date, mode=mode, scenario=scenario)

    state = _RunState()
    thread = threading.Thread(
        target=_worker,
        args=(work, state),
        daemon=True,
        name=f"cbr-sse-{kind}",
    )
    thread.start()

    tailer = TraceTailer(trace_dir)
    started = time.monotonic()
    last_ping = started
    run_sent = False
    timeout = STREAM_TIMEOUT_SECONDS

    while True:
        now = time.monotonic()
        if not state.done.is_set() and now - started > timeout:
            yield sse_event(
                "error",
                {
                    "status": 504,
                    "message": (
                        f"流式{action}超时（超过 {timeout:.0f} 秒），已停止推送；"
                        "上游分析可能仍在后台运行，可稍后通过 run_id/trace 查看结果。"
                    ),
                },
            )
            return

        discovered = tailer.discover()
        if discovered is not None and not run_sent:
            # 发现首个 trace 文件即尽早发 run：文件名即 run_id（TraceWriter 约定）。
            yield sse_event("run", {"run_id": discovered.stem})
            run_sent = True

        events = tailer.read_new()
        if not run_sent and tailer.path is not None:
            # 文件可能在 discover 与 read_new 之间刚创建（read_new 内部再次 discover）。
            # 先把 run 发出去，保证顺序严格为 run -> trace/stage。
            yield sse_event("run", {"run_id": tailer.path.stem})
            run_sent = True
        if events:
            for event in events:
                yield sse_event("trace", event.model_dump(mode="json"))
                stage = map_trace_to_stage(event)
                if stage is not None:
                    yield sse_event("stage", stage)
            last_ping = time.monotonic()
            continue

        if state.done.is_set():
            # 线程已结束：再读一次，避免「读空 -> 线程写最后一行 -> done」的竞态丢事件。
            for event in tailer.read_new():
                yield sse_event("trace", event.model_dump(mode="json"))
                stage = map_trace_to_stage(event)
                if stage is not None:
                    yield sse_event("stage", stage)
            break

        if now - last_ping >= HEARTBEAT_SECONDS:
            yield sse_ping()
            last_ping = now

        time.sleep(POLL_INTERVAL_SECONDS)

    if state.error is not None:
        yield sse_event("error", {"status": 503, "message": _failure_message(action, state.error)})
        return

    try:
        if kind == "chat":
            payload = _coerce(ChatResponse, state.result, "对话响应")
            if payload.as_of is None:
                payload = payload.model_copy(update={"as_of": _default_as_of(service, None)})
        else:
            payload = _coerce(DecisionCard, state.result, "决策卡")
    except ValueError as exc:
        yield sse_event("error", {"status": 503, "message": str(exc)})
        return

    if not run_sent:
        # 极少见：编排器没有写 trace 文件（如自定义实现）；仍从结果补齐 run。
        fallback_run_id = payload.trace_id if kind == "chat" else payload.run_id
        if fallback_run_id:
            yield sse_event("run", {"run_id": str(fallback_run_id)})

    # 与同步端点保持一致：登记进程缓存的决策卡/证据，并写 30 分钟决策缓存。
    try:
        if kind == "chat":
            if payload.decision is not None:
                api_state.remember_decision(payload.decision)
        else:
            api_state.remember_decision(payload)
            if cache_key is not None:
                _cache_put(cache_key, payload)
    except Exception:  # noqa: BLE001 - 缓存登记失败不影响最终业务事件
        pass

    yield sse_event(kind, payload.model_dump(mode="json"))  # 最终业务事件


def _decision_event_stream(
    as_of: dt.date | None,
    scenario: str | None,
    mode: str,
    refresh: bool,
) -> Iterator[str]:
    """``GET /api/decision/stream`` 的事件生成器（含缓存短路与统一错误兜底）。"""
    try:
        service, service_error = readiness.acquire_service()
        if service is None:
            yield sse_event(
                "error",
                {"status": 503, "message": readiness.not_ready_message(service_error)},
            )
            return

        target_date = as_of or _default_as_of(service, scenario)
        cache_key = _cache_key(target_date, mode, scenario)
        if not refresh:
            cached = _cache_get(cache_key)
            if cached is not None:
                yield sse_event("decision", cached.model_dump(mode="json"))
                return

        yield from _stream_events(
            "decision",
            service=service,
            as_of=target_date,
            scenario=scenario,
            mode=mode,
            cache_key=cache_key,
        )
    except Exception as exc:  # noqa: BLE001 - 流已开始后仍要以 error 事件收尾
        yield sse_event("error", {"status": 503, "message": _failure_message("生成预警决策", exc)})


def _chat_event_stream(request: ChatRequest) -> Iterator[str]:
    """``POST /api/chat/stream`` 的事件生成器（含统一错误兜底）。"""
    try:
        service, service_error = readiness.acquire_service()
        if service is None:
            yield sse_event(
                "error",
                {"status": 503, "message": readiness.not_ready_message(service_error)},
            )
            return
        yield from _stream_events("chat", service=service, request=request)
    except Exception as exc:  # noqa: BLE001 - 流已开始后仍要以 error 事件收尾
        yield sse_event("error", {"status": 503, "message": _failure_message("对话推理", exc)})


# --------------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------------- #
@router.get(
    "/api/decision/stream",
    summary="流式生成多智能体预警决策（SSE）",
    response_class=StreamingResponse,
)
def decision_stream(
    as_of: dt.date | None = Query(None, description="分析时点 YYYY-MM-DD；缺省取场景日期或最近场景"),
    scenario: str | None = Query(None, description="场景 id（见 /api/scenarios）"),
    mode: MODE_LITERAL = Query("collaborative", description="实验模式：协同/独立/单智能体"),
    refresh: bool = Query(False, description="true 时跳过 30 分钟结果缓存，强制重新生成"),
) -> StreamingResponse:
    """流式决策：``run`` → ``stage``/``trace``（实时）→ ``decision`` 或 ``error``。"""
    return StreamingResponse(
        _decision_event_stream(as_of, scenario, mode, refresh),
        media_type=SSE_MEDIA_TYPE,
        headers=dict(SSE_HEADERS),
    )


@router.post(
    "/api/chat/stream",
    summary="流式自然语言对话（SSE）",
    response_class=StreamingResponse,
)
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """流式对话：``run`` → ``stage``/``trace``（实时）→ ``chat`` 或 ``error``。"""
    return StreamingResponse(
        _chat_event_stream(request),
        media_type=SSE_MEDIA_TYPE,
        headers=dict(SSE_HEADERS),
    )


__all__ = [
    "router",
    "SSE_MEDIA_TYPE",
    "SSE_HEADERS",
    "STAGE_RULES",
    "HEARTBEAT_SECONDS",
    "STREAM_TIMEOUT_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "TraceTailer",
    "build_stream_orchestrator",
    "map_trace_to_stage",
    "new_stream_trace_dir",
    "sse_event",
    "sse_ping",
]
