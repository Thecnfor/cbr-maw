"""SSE 流式端点测试（契约见 docs/design/ai-native-interaction-spec.md §1）。

覆盖：
- 单元：SSE 序列化格式（单行 data / 中文不转义 / 心跳）、trace -> stage 映射
  （spec §1.3 全表 + 角色中文名 + step 一致性保护）、增量 tail（只读完整行、容忍坏行）；
- 端点：FakeService + monkeypatch 的流式编排器（写若干 TraceEvent 到独立 trace 目录后
  返回 DecisionCard/ChatResponse），断言事件顺序与最终业务事件、缓存短路、异常 -> error
  且 HTTP 仍 200、心跳、超时、参数校验；
- 收尾：决策写入 30 分钟缓存、决策卡登记进进程缓存后 /api/trace/{run_id} 仍可解析。

运行：``.venv\\Scripts\\python.exe -m pytest tests/test_streaming.py``
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cbr import service as service_module
from cbr.api import state as api_state
from cbr.api import streaming
from cbr.api.main import app
from cbr.config import load_settings
from cbr.schemas import (
    ChatRequest,
    ChatResponse,
    DecisionCard,
    ExperimentMode,
    RiskCard,
    RiskLevel,
    RiskSignal,
    Role,
    Scenario,
    SourceRef,
    TraceEvent,
)
from cbr.verification.trace import TraceWriter

AS_OF = dt.date(2024, 8, 5)
RUN_ID = "collaborative_2024-08-05_ab12cd34"

#: 与真实编排器动作顺序同构的 trace 脚本（step, action, role）。
TRACE_SCRIPT: list[tuple[str, str, str | None]] = [
    ("R0", "run_start", None),
    ("R0", "analysis_start", "regulator"),
    ("R0:regulator", "tool_call", "regulator"),  # 不映射 stage，仅 trace
    ("R0", "analysis_done", "regulator"),
    ("R0", "analysis_start", "investor"),
    ("R0", "analysis_done", "investor"),
    ("R0", "analysis_start", "financing"),
    ("R0", "analysis_done", "financing"),
    ("R1", "evidence_share", "regulator"),
    ("R1", "evidence_share_summary", None),
    ("R2", "cross_check", "investor"),
    ("R2", "cross_check_summary", None),
    ("R3", "conflict_detection", None),
    ("R4", "coordination_round", None),
    ("R4", "conflict_resolution", None),
    ("R5", "finalize", None),
]


# --------------------------------------------------------------------------- #
# 样例对象
# --------------------------------------------------------------------------- #
def _decision_card(trace_ref: str | None = None) -> DecisionCard:
    signal = RiskSignal(
        as_of=AS_OF,
        model_version="fusion-xgb-v1",
        horizons={5: 0.18, 10: 0.33, 20: 0.47},
        percentile=0.86,
        level=RiskLevel.HIGH,
        evidence_id="ev_sig_20240805",
    )
    card = RiskCard(
        role=Role.REGULATOR,
        as_of=AS_OF,
        risk_level=RiskLevel.HIGH,
        headline="跨境资金异常流出与外部波动叠加，系统性压力偏高",
        base_signal_ref="ev_sig_20240805",
        recommendation="建议持续监测北向资金与汇率联动，准备宏观审慎工具",
        evidence_ids=["ev_sig_20240805"],
    )
    return DecisionCard(
        run_id=RUN_ID,
        as_of=AS_OF,
        scenario="yen_carry_2024",
        mode=ExperimentMode.COLLABORATIVE,
        signal=signal,
        cards={"regulator": card},
        final_advice="建议监管关注跨境资金异动。",
        trace_ref=trace_ref,
    )


def _chat_response(trace_ref: str | None = None) -> ChatResponse:
    return ChatResponse(
        reply="已按协同模式完成 2024-08-05 的预警分析。",
        decision=_decision_card(trace_ref),
        citations=[SourceRef(name="国家外汇管理局：跨境资金流动情况", doc_id="doc-1")],
        trace_id=RUN_ID,
    )


# --------------------------------------------------------------------------- #
# Fake 服务 / 编排器（隔离核心模块与真实 LLM）
# --------------------------------------------------------------------------- #
class FakeStreamOrchestrator:
    """向独立 trace 目录写 TraceEvent，然后返回决策卡/对话响应。"""

    def __init__(self, trace_dir: str | Path, owner: "FakeService") -> None:
        self.trace_dir = Path(trace_dir)
        self.owner = owner
        self.run_calls: list[dict[str, Any]] = []
        self.chat_calls: list[ChatRequest] = []

    @property
    def trace_ref(self) -> str:
        return str(self.trace_dir / f"{RUN_ID}.jsonl")

    def _write_trace(self) -> None:
        if self.owner.start_delay:
            time.sleep(self.owner.start_delay)
        if not self.owner.write_trace:
            return
        writer = TraceWriter(RUN_ID, self.trace_dir)
        for step, action, role in self.owner.script:
            writer.emit(step=step, action=action, role=role)

    def run(self, as_of: dt.date, mode: str = "collaborative", scenario: str | None = None) -> DecisionCard:
        self.run_calls.append({"as_of": as_of, "mode": mode, "scenario": scenario})
        self._write_trace()
        if self.owner.fail is not None:
            raise self.owner.fail
        card = _decision_card(self.trace_ref)
        return card.model_copy(
            update={"as_of": as_of, "mode": ExperimentMode(mode), "scenario": scenario}
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls.append(request)
        self._write_trace()
        if self.owner.fail is not None:
            raise self.owner.fail
        return _chat_response(self.trace_ref)


class FakeSharedOrchestrator:
    """共享编排器占位：流式端点不应复用；同步端点仅在缓存命中时才会通过前置校验。"""

    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []

    def run(self, as_of: dt.date, mode: str = "collaborative", scenario: str | None = None) -> Any:
        self.run_calls.append({"as_of": as_of, "mode": mode, "scenario": scenario})
        raise RuntimeError("流式测试不应调用共享编排器（缓存未命中）")


class FakeService:
    def __init__(self, artifacts_root: Path) -> None:
        self.settings = load_settings()
        self.provider = object()
        self.registry = object()
        self.kb = object()
        self.llm = object()
        # 流式端点必须构建独立编排器，不复用共享 orchestration 实例
        self.orchestrator = FakeSharedOrchestrator()
        self.scenarios = [
            Scenario(
                scenario_id="yen_carry_2024",
                name="2024 日元套息交易逆转",
                as_of=AS_OF,
                description="日元套息交易平仓引发全球风险资产波动",
                tags=["全球冲击", "波动率"],
            )
        ]
        self._artifacts_root = artifacts_root
        # 流式编排器可调行为（供用例按需改写）
        self.script = list(TRACE_SCRIPT)
        self.fail: Exception | None = None
        self.start_delay = 0.0
        self.write_trace = True
        # 记录
        self.trace_dirs: list[Path] = []
        self.orchestrators: list[FakeStreamOrchestrator] = []

    def available_scenarios(self) -> list[Scenario]:
        return list(self.scenarios)

    def artifacts_dir(self) -> Path:
        self._artifacts_root.mkdir(parents=True, exist_ok=True)
        return self._artifacts_root


@pytest.fixture()
def fake_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeService:
    from cbr.api import main as api_main

    api_state.reset_cache()
    api_main.clear_decision_cache()
    service = FakeService(tmp_path / "artifacts")

    monkeypatch.setattr(service_module, "get_service", lambda: service)

    def _build(service_obj: Any, trace_dir: str | Path) -> FakeStreamOrchestrator:
        assert service_obj is service
        orchestrator = FakeStreamOrchestrator(trace_dir, service)
        service.trace_dirs.append(Path(trace_dir))
        service.orchestrators.append(orchestrator)
        return orchestrator

    monkeypatch.setattr(streaming, "build_stream_orchestrator", _build)
    return service


@pytest.fixture()
def client(fake_service: FakeService) -> TestClient:
    from cbr.api import main as api_main

    api_state.reset_cache()
    api_main.clear_decision_cache()
    with TestClient(app) as test_client:
        yield test_client
    api_state.reset_cache()
    api_main.clear_decision_cache()


@pytest.fixture()
def degraded_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from cbr.api import main as api_main

    def _not_ready() -> Any:
        raise ImportError("No module named 'cbr.orchestration'")

    monkeypatch.setattr(service_module, "get_service", _not_ready)
    api_state.reset_cache()
    api_main.clear_decision_cache()
    with TestClient(app) as test_client:
        yield test_client
    api_state.reset_cache()
    api_main.clear_decision_cache()


# --------------------------------------------------------------------------- #
# SSE 解析工具
# --------------------------------------------------------------------------- #
def _read_stream(
    client: TestClient, method: str, path: str, **kwargs: Any
) -> tuple[int, dict[str, str], list[dict[str, Any]]]:
    with client.stream(method, path, **kwargs) as response:
        status = response.status_code
        headers = dict(response.headers)
        lines = list(response.iter_lines())
    return status, headers, _parse_sse(lines)


def _parse_sse(lines: list[str]) -> list[dict[str, Any]]:
    """把 SSE 文本行解析为 ``[{"event": name, "data": payload}]``（含 ping）。"""
    events: list[dict[str, Any]] = []
    name: str | None = None
    data: list[str] = []
    for line in lines:
        if line.startswith(":"):
            events.append({"event": "ping", "data": {}})
            continue
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].lstrip())
        elif not line.strip():
            if name is not None:
                events.append({"event": name, "data": json.loads("\n".join(data))})
            name, data = None, []
    return events


def _names(events: list[dict[str, Any]]) -> list[str]:
    return [item["event"] for item in events]


# --------------------------------------------------------------------------- #
# 单元：SSE 序列化
# --------------------------------------------------------------------------- #
def test_sse_event_single_line_json_keeps_unicode() -> None:
    frame = streaming.sse_event("trace", {"text": "监管主体\n完成", "run_id": RUN_ID})
    assert frame.startswith("event: trace\ndata: ")
    assert frame.endswith("\n\n")
    # event 行 + data 行 + 两个结尾换行 => 恰好 4 段
    parts = frame.split("\n")
    assert parts[0] == "event: trace"
    assert parts[1].startswith("data: ")
    assert parts[2:] == ["", ""]
    payload = json.loads(parts[1][len("data: ") :])
    assert payload["text"] == "监管主体\n完成"
    assert payload["run_id"] == RUN_ID
    # 中文不转义为 \uXXXX，换行被 JSON 转义为字面 \n（不产生裸换行）
    assert "监管主体" in parts[1]
    assert "\\n" in parts[1]


def test_sse_event_is_single_line() -> None:
    frame = streaming.sse_event("stage", {"label": "证据共享与去重"})
    assert frame.count("\n\n") == 1
    data_line = frame.split("\n")[1]
    assert "\n" not in data_line and "\r" not in data_line


def test_sse_ping_format() -> None:
    assert streaming.sse_ping() == ": ping\n\n"


# --------------------------------------------------------------------------- #
# 单元：trace -> stage 映射（spec §1.3 全表）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("step", "action", "role", "stage", "status", "label"),
    [
        ("R0", "run_start", None, "R0", "started", "初始化协同分析"),
        ("R0", "analysis_start", "regulator", "R0", "started", "监管主体分析中"),
        ("R0", "analysis_start", "investor", "R0", "started", "投资主体分析中"),
        ("R0", "analysis_start", "financing", "R0", "started", "融资主体分析中"),
        ("R0", "analysis_done", "regulator", "R0", "finished", "监管主体分析完成"),
        ("R0", "analysis_done", "investor", "R0", "finished", "投资主体分析完成"),
        ("R0", "analysis_done", "financing", "R0", "finished", "融资主体分析完成"),
        ("R1", "evidence_share", "regulator", "R1", "started", "证据共享与去重"),
        ("R1", "evidence_share_summary", None, "R1", "finished", "证据共享完成"),
        ("R2", "cross_check", "investor", "R2", "started", "交叉验证关键数值"),
        ("R2", "cross_check_summary", None, "R2", "finished", "交叉验证关键数值"),
        ("R3", "conflict_detection", None, "R3", "started", "分歧识别"),
        ("R4", "coordination_round", None, "R4", "started", "冲突协调"),
        ("R4", "conflict_resolution", None, "R4", "started", "冲突协调"),
        ("R5", "finalize", None, "R5", "finished", "汇总决策卡"),
    ],
)
def test_map_trace_to_stage_covers_spec_table(
    step: str,
    action: str,
    role: str | None,
    stage: str,
    status: str,
    label: str,
) -> None:
    event = TraceEvent(run_id=RUN_ID, step=step, action=action, role=role)
    mapped = streaming.map_trace_to_stage(event)
    assert mapped is not None
    assert mapped["stage"] == stage
    assert mapped["status"] == status
    assert mapped["label"] == label
    assert mapped["role"] == role
    assert mapped["action"] == action
    # 字段齐全：stage/label/role/status/action/ts
    assert set(mapped) == {"stage", "label", "role", "status", "action", "ts"}
    assert dt.datetime.fromisoformat(mapped["ts"])


def test_map_trace_to_stage_role_display_names() -> None:
    for role, display in streaming.ROLE_DISPLAY.items():
        mapped = streaming.map_trace_to_stage(
            TraceEvent(run_id=RUN_ID, step="R0", action="analysis_start", role=role)
        )
        assert mapped is not None
        assert mapped["label"] == f"{display}分析中"


@pytest.mark.parametrize("action", ["tool_call", "claim", "verify", "hitl", "budget_exceeded", ""])
def test_map_trace_to_stage_unknown_action_returns_none(action: str) -> None:
    event = TraceEvent(run_id=RUN_ID, step="R0", action=action)
    assert streaming.map_trace_to_stage(event) is None


def test_map_trace_to_stage_guards_agent_level_finalize() -> None:
    """智能体内部 trace 的 finalize（step=R0:regulator）不得把进度提前推到 R5。"""
    agent_level = TraceEvent(
        run_id=RUN_ID, step="R0:regulator", action="finalize", role="regulator"
    )
    assert streaming.map_trace_to_stage(agent_level) is None
    orchestrator_level = TraceEvent(run_id=RUN_ID, step="R5", action="finalize")
    mapped = streaming.map_trace_to_stage(orchestrator_level)
    assert mapped is not None and mapped["stage"] == "R5"


def test_map_trace_to_stage_accepts_mapping_payload() -> None:
    payload = {
        "run_id": RUN_ID,
        "step": "R1",
        "action": "evidence_share",
        "role": "regulator",
        "ts": "2024-08-05T01:02:03+00:00",
    }
    mapped = streaming.map_trace_to_stage(payload)
    assert mapped is not None
    assert mapped["stage"] == "R1"
    assert mapped["ts"] == "2024-08-05T01:02:03+00:00"


# --------------------------------------------------------------------------- #
# 单元：增量 tail
# --------------------------------------------------------------------------- #
def test_trace_tailer_reads_complete_lines_only(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    tailer = streaming.TraceTailer(trace_dir)
    assert tailer.discover() is None
    assert tailer.read_new() == []

    writer = TraceWriter(RUN_ID, trace_dir)
    writer.emit(step="R0", action="run_start")
    assert tailer.discover() == trace_dir / f"{RUN_ID}.jsonl"
    events = tailer.read_new()
    assert [event.action for event in events] == ["run_start"]
    assert tailer.read_new() == []

    # 模拟写入中途：只落半行时不解析
    path = trace_dir / f"{RUN_ID}.jsonl"
    line = (
        json.dumps(
            TraceEvent(run_id=RUN_ID, step="R0", action="analysis_start", role="regulator").model_dump(
                mode="json"
            ),
            ensure_ascii=False,
        )
        + "\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line[:12])
    assert tailer.read_new() == []

    with path.open("a", encoding="utf-8") as handle:
        handle.write(line[12:])
    events = tailer.read_new()
    assert len(events) == 1
    assert events[0].action == "analysis_start"
    assert events[0].role == "regulator"


def test_trace_tailer_skips_broken_lines(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    writer = TraceWriter(RUN_ID, trace_dir)
    path = writer.path
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write('{"run_id": "broken", "step": 5}\n')  # 类型不合契约
    writer.emit(step="R5", action="finalize")
    tailer = streaming.TraceTailer(trace_dir)
    events = tailer.read_new()
    assert [event.action for event in events] == ["finalize"]


# --------------------------------------------------------------------------- #
# 端点：decision 正常路径
# --------------------------------------------------------------------------- #
def test_decision_stream_event_sequence(fake_service: FakeService, client: TestClient) -> None:
    status, headers, events = _read_stream(
        client,
        "GET",
        "/api/decision/stream",
        params={"as_of": "2024-08-05", "scenario": "yen_carry_2024", "mode": "collaborative"},
    )
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"

    names = _names(events)
    assert names[0] == "run"
    assert names[-1] == "decision"
    assert "trace" in names and "stage" in names
    assert "error" not in names

    assert events[0]["data"]["run_id"] == RUN_ID
    trace_events = [item for item in events if item["event"] == "trace"]
    assert len(trace_events) == len(TRACE_SCRIPT)
    assert [item["data"]["action"] for item in trace_events] == [
        action for _step, action, _role in TRACE_SCRIPT
    ]

    # 可映射的 trace 之后必须紧跟同名 stage
    for index, item in enumerate(events):
        if item["event"] != "trace":
            continue
        expected = streaming.map_trace_to_stage(item["data"])
        if expected is None:
            continue
        assert index + 1 < len(events)
        assert events[index + 1]["event"] == "stage"
        assert events[index + 1]["data"] == expected

    stages = [item["data"] for item in events if item["event"] == "stage"]
    assert [item["stage"] for item in stages][0] == "R0"
    assert ("R0", "started") in {(item["stage"], item["status"]) for item in stages}
    assert ("R0", "finished") in {(item["stage"], item["status"]) for item in stages}
    assert ("R1", "finished") in {(item["stage"], item["status"]) for item in stages}
    assert ("R2", "finished") in {(item["stage"], item["status"]) for item in stages}
    assert ("R3", "started") in {(item["stage"], item["status"]) for item in stages}
    assert ("R4", "started") in {(item["stage"], item["status"]) for item in stages}
    assert ("R5", "finished") in {(item["stage"], item["status"]) for item in stages}

    decision = events[-1]["data"]
    assert decision["run_id"] == RUN_ID
    assert decision["as_of"] == "2024-08-05"
    assert decision["scenario"] == "yen_carry_2024"
    assert decision["mode"] == "collaborative"
    assert set(decision["cards"]) == {"regulator"}

    # 每次真实请求使用独立 trace 目录 + 独立编排器
    assert len(fake_service.trace_dirs) == 1
    assert fake_service.trace_dirs[0].name.startswith("stream-")
    assert fake_service.trace_dirs[0].parent.name == "traces"
    assert len(fake_service.orchestrators) == 1
    assert fake_service.orchestrators[0].run_calls == [
        {"as_of": AS_OF, "mode": "collaborative", "scenario": "yen_carry_2024"}
    ]
    assert (fake_service.trace_dirs[0] / f"{RUN_ID}.jsonl").is_file()

    # 决策卡已登记：/api/trace/{run_id} 可经缓存决策卡的 trace_ref 解析
    trace_response = client.get(f"/api/trace/{RUN_ID}")
    assert trace_response.status_code == 200
    assert len(trace_response.json()) == len(TRACE_SCRIPT)


def test_decision_stream_cache_hit_is_immediate(fake_service: FakeService, client: TestClient) -> None:
    params = {"as_of": "2024-08-05"}
    first_status, _headers, first_events = _read_stream(
        client, "GET", "/api/decision/stream", params=params
    )
    assert first_status == 200
    assert first_events[-1]["event"] == "decision"
    assert len(fake_service.orchestrators) == 1
    assert len(fake_service.trace_dirs) == 1

    second_status, _headers, second_events = _read_stream(
        client, "GET", "/api/decision/stream", params=params
    )
    assert second_status == 200
    assert _names(second_events) == ["decision"]
    assert second_events[0]["data"]["run_id"] == RUN_ID
    # 命中缓存：不重建编排器 / 不新建 trace 目录
    assert len(fake_service.orchestrators) == 1
    assert len(fake_service.trace_dirs) == 1

    # 同步端点同样命中这份缓存（共享编排器的 run 一旦被调用就会抛错 -> 503）
    sync_response = client.get("/api/decision", params=params)
    assert sync_response.status_code == 200, sync_response.text
    assert sync_response.json()["run_id"] == RUN_ID
    assert fake_service.orchestrator.run_calls == []  # type: ignore[attr-defined]

    refresh_status, _headers, refresh_events = _read_stream(
        client, "GET", "/api/decision/stream", params={**params, "refresh": "true"}
    )
    assert refresh_status == 200
    assert "trace" in _names(refresh_events)
    assert len(fake_service.orchestrators) == 2
    assert len(fake_service.trace_dirs) == 2


def test_decision_stream_error_event_keeps_http_200(
    fake_service: FakeService, client: TestClient
) -> None:
    fake_service.fail = RuntimeError("PIT 数据缺失：2024-08-05")
    status, headers, events = _read_stream(client, "GET", "/api/decision/stream")

    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    names = _names(events)
    assert names[0] == "run"  # 已产生的 trace 仍会推送
    assert names[-1] == "error"
    assert "decision" not in names
    error = events[-1]["data"]
    assert error["status"] == 503
    assert "核心服务执行失败" in error["message"]
    assert "RuntimeError" in error["message"]
    assert "PIT 数据缺失" in error["message"]


def test_decision_stream_timeout_emits_error(
    fake_service: FakeService, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(streaming, "STREAM_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(streaming, "POLL_INTERVAL_SECONDS", 0.005)
    fake_service.start_delay = 0.15
    try:
        status, _headers, events = _read_stream(client, "GET", "/api/decision/stream")
        assert status == 200
        assert events[-1]["event"] == "error"
        assert events[-1]["data"]["status"] == 504
        assert "超时" in events[-1]["data"]["message"]
    finally:
        # 等后台线程自然结束，避免跨用例干扰
        time.sleep(0.2)


def test_stream_heartbeat_ping(
    fake_service: FakeService, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(streaming, "POLL_INTERVAL_SECONDS", 0.005)
    fake_service.start_delay = 0.05
    status, _headers, events = _read_stream(client, "GET", "/api/decision/stream")
    assert status == 200
    names = _names(events)
    assert "ping" in names
    assert names[-1] == "decision"
    # 心跳是 SSE 注释，出现在业务事件之间/之前，不改变最终事件
    assert names.index("ping") < names.index("decision")


def test_client_disconnect_stops_tail_without_breaking_server(
    fake_service: FakeService, client: TestClient
) -> None:
    """浏览器断开后生成器停止 tail；后续请求仍能正常完整推送事件。"""
    fake_service.start_delay = 0.2
    with client.stream("GET", "/api/decision/stream") as response:
        assert response.status_code == 200
        first_line = next(response.iter_lines())
        assert first_line == "event: run"
        # 主动断开：不再读取 decision
    time.sleep(0.1)

    fake_service.start_delay = 0.0
    status, _headers, events = _read_stream(
        client, "GET", "/api/decision/stream", params={"refresh": "true"}
    )
    assert status == 200
    assert events[-1]["event"] == "decision"
    assert "trace" in _names(events)


def test_decision_stream_invalid_params_return_422(client: TestClient) -> None:
    assert client.get("/api/decision/stream", params={"mode": "wrong"}).status_code == 422
    assert client.get("/api/decision/stream", params={"as_of": "2024/08/05"}).status_code == 422


# --------------------------------------------------------------------------- #
# 端点：chat
# --------------------------------------------------------------------------- #
def test_chat_stream_event_sequence(fake_service: FakeService, client: TestClient) -> None:
    payload = {"message": "当前跨境资金流出压力如何？", "as_of": "2024-08-05", "session_id": "s-1"}
    status, headers, events = _read_stream(client, "POST", "/api/chat/stream", json=payload)

    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"

    names = _names(events)
    assert names[0] == "run"
    assert names[-1] == "chat"
    assert "trace" in names and "stage" in names
    assert "decision" not in names and "error" not in names

    chat = events[-1]["data"]
    assert "跨境" in chat["reply"] or "协同" in chat["reply"]
    assert chat["trace_id"] == RUN_ID
    assert chat["decision"]["run_id"] == RUN_ID
    assert chat["citations"][0]["name"].startswith("国家外汇管理局")
    assert chat["as_of"] == "2024-08-05"

    orchestrator = fake_service.orchestrators[0]
    assert orchestrator.chat_calls[0].message == payload["message"]
    assert orchestrator.chat_calls[0].session_id == "s-1"
    assert fake_service.trace_dirs[0].name.startswith("stream-")


def test_chat_stream_defaults_as_of_from_scenario(
    fake_service: FakeService, client: TestClient
) -> None:
    status, _headers, events = _read_stream(
        client, "POST", "/api/chat/stream", json={"message": "当前风险如何？"}
    )
    assert status == 200
    assert events[-1]["event"] == "chat"
    assert events[-1]["data"]["as_of"] == "2024-08-05"


def test_chat_stream_error_event_keeps_http_200(
    fake_service: FakeService, client: TestClient
) -> None:
    fake_service.fail = ValueError("对话编排失败")
    status, _headers, events = _read_stream(
        client, "POST", "/api/chat/stream", json={"message": "当前风险如何？"}
    )
    assert status == 200
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["status"] == 503
    assert "ValueError" in events[-1]["data"]["message"]
    assert "对话编排失败" in events[-1]["data"]["message"]


def test_chat_stream_invalid_body_returns_422(client: TestClient) -> None:
    response = client.post("/api/chat/stream", json={"as_of": "2024-08-05"})
    assert response.status_code == 422
    assert response.json()["detail"] == "请求参数校验失败"


# --------------------------------------------------------------------------- #
# 端点：降级 / OpenAPI
# --------------------------------------------------------------------------- #
def test_stream_returns_error_event_when_core_not_ready(degraded_client: TestClient) -> None:
    status, headers, events = _read_stream(degraded_client, "GET", "/api/decision/stream")
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert _names(events) == ["error"]
    error = events[0]["data"]
    assert error["status"] == 503
    assert "核心服务" in error["message"]


def test_stream_chat_returns_error_event_when_core_not_ready(degraded_client: TestClient) -> None:
    status, _headers, events = _read_stream(
        degraded_client, "POST", "/api/chat/stream", json={"message": "当前风险如何？"}
    )
    assert status == 200
    assert _names(events) == ["error"]
    assert events[0]["data"]["status"] == 503


def test_openapi_contains_streaming_endpoints(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    assert "/api/decision/stream" in paths
    assert "/api/chat/stream" in paths
    # 同步端点保持不变
    assert "/api/decision" in paths
    assert "/api/chat" in paths
