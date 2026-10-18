"""CBR-MAW API 端点测试（FakeService 隔离，不依赖核心模块实现）。

覆盖：
- 正常路径：health / scenarios / decision / chat / evidence / data-cards / trace 的
  状态码与 schemas.py 契约字段；
- 降级路径：核心模块未就绪（``cbr.service.get_service`` 抛 ImportError）时，
  ``/api/health`` 必须 200 + status=degraded，业务端点必须 503 + 中文提示，绝不 500 裸崩；
- 兜底路径：证据/轨迹可从进程缓存或 artifacts 文件解析；
- Streamlit 冒烟（若安装 streamlit）：驾驶台在「服务就绪」与「核心未就绪」两种情况下
  都能渲染且不抛异常（AppTest，不开浏览器）。

运行：``.venv\\Scripts\\python.exe -m pytest tests/test_api.py``
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from cbr import service as service_module
from cbr.api import state as api_state
from cbr.api.main import app
from cbr.config import load_settings
from cbr.schemas import (
    ChatRequest,
    ChatResponse,
    Claim,
    ClaimStatus,
    ClaimType,
    Conflict,
    ConflictType,
    CoordinationStats,
    DataCard,
    DecisionCard,
    Evidence,
    EvidenceKind,
    ExperimentMode,
    MetricItem,
    RiskCard,
    RiskDriver,
    RiskLevel,
    RiskSignal,
    Role,
    Scenario,
    SourceRef,
    ToolRef,
    TraceEvent,
    VerificationIssue,
    VerificationReport,
)
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.date(2024, 8, 5)
RUN_ID = "run-test-0001"
SIGNAL_EVIDENCE_ID = "ev_sig_20240805_v1"
TOOL_EVIDENCE_ID = "ev_tool_risk_20240805"
RELEASE_TIME = dt.datetime(2024, 8, 4, 9, 30, tzinfo=dt.timezone.utc)


# --------------------------------------------------------------------------- #
# 样例数据（仅测试使用，不进入 UI 主流程）
# --------------------------------------------------------------------------- #
def _signal_evidence() -> Evidence:
    return Evidence(
        evidence_id=SIGNAL_EVIDENCE_ID,
        kind=EvidenceKind.SIGNAL,
        as_of=AS_OF,
        title="共享多模态融合风险信号",
        summary="20 日高压力概率 47.0%；历史分位 86.0%",
        payload={"horizons": {"5": 0.18, "10": 0.33, "20": 0.47}, "model_version": "fusion-xgb-v1"},
        value=0.47,
        source=SourceRef(name="多模态融合预测器", release_time=RELEASE_TIME),
        produced_by="fusion",
    )


def _tool_evidence() -> Evidence:
    return Evidence(
        evidence_id=TOOL_EVIDENCE_ID,
        kind=EvidenceKind.TOOL,
        as_of=AS_OF,
        title="组合 VaR(95%, 1日)",
        summary="组合 VaR(95%) 约为 3.2%，处于近一年 91% 分位",
        payload={"var_95": 0.032, "lookback": 250},
        unit="ratio",
        value=0.032,
        source=SourceRef(name="行情快照", url="https://example.com/snapshot", extra={"snapshot": "pit-20251018"}),
        tool=ToolRef(name="risk_measure", version="1.2.0", inputs_hash="sha256:abc123", elapsed_ms=120),
        produced_by="investor",
        citations=[SourceRef(name="沪深300 日行情", release_time=RELEASE_TIME)],
        verified=True,
    )


def _risk_signal() -> RiskSignal:
    return RiskSignal(
        as_of=AS_OF,
        model_version="fusion-xgb-v1",
        horizons={5: 0.18, 10: 0.33, 20: 0.47},
        percentile=0.86,
        level=RiskLevel.HIGH,
        drivers=[
            RiskDriver(factor="northbound_outflow_z", contribution=0.31, direction="up", description="北向资金异常流出"),
            RiskDriver(factor="vix_change", contribution=0.12, direction="down", description="全球波动回落"),
        ],
        modality_contrib={"numeric": 0.72, "text": 0.28},
        label_version="stress_pca_q90",
        evidence_id=SIGNAL_EVIDENCE_ID,
    )


def _risk_card(role: Role) -> RiskCard:
    headline = {
        Role.REGULATOR: "跨境资金异常流出与外部波动叠加，系统性压力偏高",
        Role.INVESTOR: "组合尾部损失风险上升，建议降低风险预算",
        Role.FINANCING: "再融资窗口收窄，融资成本存在上行压力",
    }[role]
    recommendation = {
        Role.REGULATOR: "建议持续监测北向资金与汇率联动，准备宏观审慎工具",
        Role.INVESTOR: "建议将权益风险预算下调 10%，增加尾部对冲",
        Role.FINANCING: "建议提前锁定部分融资额度，延长债务久期",
    }[role]
    return RiskCard(
        role=role,
        as_of=AS_OF,
        risk_level=RiskLevel.HIGH if role is not Role.FINANCING else RiskLevel.MEDIUM,
        headline=headline,
        base_signal_ref=SIGNAL_EVIDENCE_ID,
        key_metrics=[
            MetricItem(name="prob_high_stress_20d", label="20日高压力概率", value=0.47, unit="ratio", evidence_id=SIGNAL_EVIDENCE_ID),
            MetricItem(name="var_95", label="组合 VaR(95%)", value=0.032, unit="ratio", evidence_id=TOOL_EVIDENCE_ID),
        ],
        claims=[
            Claim(
                claim_id=f"{role.value}-c1",
                role=role.value,
                claim_type=ClaimType.NUMERIC,
                subject="组合 VaR",
                text="组合 VaR(95%, 1日) 约为 3.2%",
                value=0.032,
                unit="ratio",
                direction="up",
                evidence_ids=[TOOL_EVIDENCE_ID],
                confidence=0.82,
                status=ClaimStatus.VERIFIED,
            )
        ],
        recommendation=recommendation,
        decision_loss={"miss": 5.0, "false_alarm": 1.0},
        limitations=["未覆盖场外衍生品敞口", "文本模态仅使用公开新闻"],
        evidence_ids=[SIGNAL_EVIDENCE_ID, TOOL_EVIDENCE_ID],
        tool_calls=3,
        tokens=1200,
        latency_ms=850,
        round=2,
    )


def _decision_card() -> DecisionCard:
    verification = VerificationReport(
        run_id=RUN_ID,
        numeric_checks_total=9,
        numeric_checks_passed=9,
        citation_checks_total=6,
        citation_checks_passed=6,
        unsupported_claims=0,
        permission_violations=0,
        leakage_events=0,
        schema_errors=0,
        issues=[
            VerificationIssue(
                issue_type="permission",
                role="financing",
                detail="拦截 1 次越权调用：financing 角色尝试访问 capital_flow 工具",
                severity="warning",
            )
        ],
    ).finalize()
    return DecisionCard(
        run_id=RUN_ID,
        as_of=AS_OF,
        scenario="yen_carry_2024",
        mode=ExperimentMode.COLLABORATIVE,
        signal=_risk_signal(),
        cards={role.value: _risk_card(role) for role in (Role.REGULATOR, Role.INVESTOR, Role.FINANCING)},
        conflicts=[
            Conflict(
                conflict_id="cf-1",
                subject="风险等级判断",
                claim_ids=["regulator-c1", "investor-c1"],
                roles=["regulator", "investor"],
                type=ConflictType.DIRECTIONAL,
                description="监管主体给出高风险，投资主体认为短期可控",
                severity="medium",
                resolved=True,
                resolution="以共享信号与工具证据为准，统一为高风险",
                resolved_by="tool",
                evidence_ids=[TOOL_EVIDENCE_ID],
            )
        ],
        verification=verification,
        coordination=CoordinationStats(
            rounds=2,
            evidence_shared=6,
            duplicate_evidence=1,
            conflicts_total=1,
            conflicts_resolved=1,
            tool_calls=8,
            tokens=3600,
            latency_ms=2400,
        ),
        final_advice="建议监管关注跨境资金异动，投资端下调风险预算，融资端提前锁定额度。",
        trace_ref=f"traces/{RUN_ID}.jsonl",
    )


def _trace_events() -> list[TraceEvent]:
    return [
        TraceEvent(
            run_id=RUN_ID,
            step="R0",
            role="regulator",
            action="signal",
            detail={"signal": _risk_signal().model_dump(mode="json"), "evidence": _signal_evidence().model_dump(mode="json")},
            latency_ms=35,
        ),
        TraceEvent(
            run_id=RUN_ID,
            step="R1",
            role="investor",
            action="tool_call",
            tool="risk_measure",
            args_hash="sha256:args",
            result_hash="sha256:result",
            detail={"evidence": _tool_evidence().model_dump(mode="json")},
            latency_ms=120,
            tokens=80,
        ),
        TraceEvent(
            run_id=RUN_ID,
            step="R3",
            role="coordinator",
            action="conflict",
            detail={"conflict_id": "cf-1", "resolved_by": "tool"},
            latency_ms=15,
        ),
    ]


# --------------------------------------------------------------------------- #
# Fake 服务（替代 cbr.service.get_service，隔离核心模块）
# --------------------------------------------------------------------------- #
class FakeOrchestrator:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []
        self.chat_calls: list[ChatRequest] = []
        self.evidence = {
            SIGNAL_EVIDENCE_ID: _signal_evidence(),
            TOOL_EVIDENCE_ID: _tool_evidence(),
        }
        self.traces: dict[str, list[TraceEvent]] = {RUN_ID: _trace_events()}
        self.fail_run: Exception | None = None
        self.return_bad_contract = False

    def run(self, as_of: dt.date, mode: str = "collaborative", scenario: str | None = None) -> DecisionCard:
        self.run_calls.append({"as_of": as_of, "mode": mode, "scenario": scenario})
        if self.fail_run is not None:
            raise self.fail_run
        if self.return_bad_contract:
            return {"not": "a decision card"}  # type: ignore[return-value]
        card = _decision_card().model_copy(deep=True)
        card.as_of = as_of
        card.mode = ExperimentMode(mode)
        card.scenario = scenario
        return card

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls.append(request)
        return ChatResponse(
            reply="基于 2024-08-05 时点的共享信号，跨境资金流出压力偏高，建议关注汇率联动与流动性缓冲。",
            as_of=AS_OF,
            decision=_decision_card(),
            citations=[
                SourceRef(
                    name="国家外汇管理局：跨境资金流动情况",
                    url="https://example.com/safe",
                    doc_id="doc-1",
                    chunk_id="chunk-1",
                    release_time=RELEASE_TIME,
                )
            ],
            trace_id=RUN_ID,
        )

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self.evidence.get(evidence_id)

    def get_trace(self, run_id: str) -> list[TraceEvent] | None:
        return self.traces.get(run_id)


class FakeProvider:
    def data_cards(self) -> list[DataCard]:
        return [
            DataCard(
                series_id="cn_equity_hs300",
                name="沪深300 收盘价",
                source="akshare",
                frequency="daily",
                coverage_start=dt.date(2015, 1, 5),
                coverage_end=AS_OF,
                release_lag_days=0,
                pit_grade="strict",
                unit="point",
                notes="时点严格可得",
            )
        ]


class FakeLLM:
    @property
    def usage(self) -> dict[str, int]:
        return {"prompt_tokens": 100, "completion_tokens": 50, "calls": 2}


class FakeService:
    def __init__(self, artifacts_root: Path) -> None:
        self.orchestrator = FakeOrchestrator()
        self.provider = FakeProvider()
        self.llm = FakeLLM()
        self.settings = load_settings()
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

    def available_scenarios(self) -> list[Scenario]:
        return list(self.scenarios)

    def artifacts_dir(self) -> Path:
        self._artifacts_root.mkdir(parents=True, exist_ok=True)
        return self._artifacts_root


@pytest.fixture()
def fake_service(tmp_path: Path) -> FakeService:
    api_state.reset_cache()
    return FakeService(tmp_path / "artifacts")


@pytest.fixture()
def client(fake_service: FakeService, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(service_module, "get_service", lambda: fake_service)
    api_state.reset_cache()
    with TestClient(app) as test_client:
        yield test_client
    api_state.reset_cache()


@pytest.fixture()
def degraded_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def _not_ready() -> Any:
        raise ImportError("No module named 'cbr.orchestration'")

    monkeypatch.setattr(service_module, "get_service", _not_ready)
    api_state.reset_cache()
    with TestClient(app) as test_client:
        yield test_client
    api_state.reset_cache()


# --------------------------------------------------------------------------- #
# 正常路径
# --------------------------------------------------------------------------- #
def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service_ready"] is True
    assert body["service_error"] is None
    assert body["scenarios"] == 1
    assert body["llm"]["mock"] in (True, False)
    assert body["data_sources"]["ready"] is True
    assert body["data_sources"]["data_cards"] == 1
    assert isinstance(body["modules"], list) and len(body["modules"]) == 5
    assert body["timestamp"]


def test_scenarios(client: TestClient) -> None:
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert isinstance(scenarios, list) and scenarios
    assert scenarios[0]["scenario_id"] == "yen_carry_2024"
    assert scenarios[0]["as_of"] == "2024-08-05"


def test_decision_defaults(fake_service: FakeService, client: TestClient) -> None:
    response = client.get("/api/decision")
    assert response.status_code == 200
    body = response.json()
    # 缺省参数：as_of 取场景日期、mode=collaborative
    assert fake_service.orchestrator.run_calls == [
        {"as_of": AS_OF, "mode": "collaborative", "scenario": None}
    ]
    assert body["run_id"] == RUN_ID
    assert body["mode"] == "collaborative"
    assert body["as_of"] == "2024-08-05"
    # schema 关键字段
    assert set(body["cards"].keys()) == {"regulator", "investor", "financing"}
    assert body["signal"]["level"] == "high"
    assert float(body["signal"]["horizons"]["20"]) == pytest.approx(0.47)
    assert body["cards"]["investor"]["claims"][0]["status"] == "verified"
    assert body["verification"]["numeric_error_rate"] == pytest.approx(0.0)
    assert body["conflicts"][0]["type"] == "directional"


def test_decision_explicit_params(fake_service: FakeService, client: TestClient) -> None:
    response = client.get(
        "/api/decision",
        params={"as_of": "2020-03-16", "scenario": "covid_2020", "mode": "independent"},
    )
    assert response.status_code == 200
    body = response.json()
    assert fake_service.orchestrator.run_calls[-1] == {
        "as_of": dt.date(2020, 3, 16),
        "mode": "independent",
        "scenario": "covid_2020",
    }
    assert body["mode"] == "independent"
    assert body["as_of"] == "2020-03-16"


def test_decision_invalid_mode_returns_422(client: TestClient) -> None:
    response = client.get("/api/decision", params={"mode": "wrong"})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "请求参数校验失败"
    assert body["errors"]


def test_decision_invalid_date_returns_422(client: TestClient) -> None:
    response = client.get("/api/decision", params={"as_of": "2024/08/05"})
    assert response.status_code == 422
    assert response.json()["detail"] == "请求参数校验失败"


def test_chat(fake_service: FakeService, client: TestClient) -> None:
    payload = {"message": "当前跨境资金流出压力如何？", "as_of": "2024-08-05", "session_id": "s-1"}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "跨境资金" in body["reply"]
    assert body["as_of"] == "2024-08-05"
    assert body["decision"]["run_id"] == RUN_ID
    assert body["citations"][0]["name"].startswith("国家外汇管理局")
    assert body["trace_id"] == RUN_ID
    assert fake_service.orchestrator.chat_calls[0].message == payload["message"]
    assert fake_service.orchestrator.chat_calls[0].session_id == "s-1"


def test_chat_invalid_body_returns_422(client: TestClient) -> None:
    response = client.post("/api/chat", json={"as_of": "2024-08-05"})
    assert response.status_code == 422
    assert response.json()["detail"] == "请求参数校验失败"


def test_evidence_found(client: TestClient) -> None:
    response = client.get(f"/api/evidence/{TOOL_EVIDENCE_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"] == TOOL_EVIDENCE_ID
    assert body["kind"] == "tool"
    assert body["tool"]["version"] == "1.2.0"
    assert body["tool"]["inputs_hash"] == "sha256:abc123"
    assert body["citations"]
    assert body["payload"]["var_95"] == pytest.approx(0.032)


def test_evidence_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/api/evidence/ev-not-exist")
    assert response.status_code == 404
    assert "未找到证据" in response.json()["detail"]


def test_evidence_from_decision_cache(
    fake_service: FakeService, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 模拟编排层未提供 get_evidence：共享信号证据应能从进程缓存解析
    monkeypatch.setattr(fake_service.orchestrator, "get_evidence", None)
    assert client.get("/api/decision").status_code == 200
    response = client.get(f"/api/evidence/{SIGNAL_EVIDENCE_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "signal"
    assert body["title"] == "共享多模态融合风险信号"
    assert body["value"] == pytest.approx(0.47)


def test_data_cards(client: TestClient) -> None:
    response = client.get("/api/data-cards")
    assert response.status_code == 200
    cards = response.json()
    assert len(cards) == 1
    assert cards[0]["series_id"] == "cn_equity_hs300"
    assert cards[0]["pit_grade"] == "strict"


def test_trace_found(client: TestClient) -> None:
    response = client.get(f"/api/trace/{RUN_ID}")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 3
    assert events[0]["step"] == "R0"
    assert events[1]["action"] == "tool_call"
    assert events[1]["tool"] == "risk_measure"
    assert events[1]["args_hash"] == "sha256:args"


def test_trace_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/api/trace/run-not-exist")
    assert response.status_code == 404
    assert "未找到" in response.json()["detail"]


def test_trace_artifact_fallback(
    fake_service: FakeService, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 模拟编排层没有 get_trace/traces，但已写 artifacts/traces/<run_id>.jsonl
    monkeypatch.setattr(fake_service.orchestrator, "get_trace", None)
    fake_service.orchestrator.traces = {}
    trace_dir = fake_service.artifacts_dir() / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) for event in _trace_events())
    (trace_dir / f"{RUN_ID}.jsonl").write_text(payload, encoding="utf-8")
    response = client.get(f"/api/trace/{RUN_ID}")
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_root_index(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "CBR-MAW API"
    assert any("/api/decision" in item for item in body["endpoints"])


# --------------------------------------------------------------------------- #
# 降级 / 异常路径（禁止 500 裸崩）
# --------------------------------------------------------------------------- #
def test_health_degraded_when_core_not_ready(degraded_client: TestClient) -> None:
    response = degraded_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["service_ready"] is False
    assert body["service_error"]
    assert "No module named 'cbr.orchestration'" in body["service_error"]
    assert isinstance(body["pending_modules"], list)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/decision", None),
        ("post", "/api/chat", {"message": "现在风险如何？"}),
        ("get", f"/api/evidence/{SIGNAL_EVIDENCE_ID}", None),
        ("get", "/api/data-cards", None),
        ("get", f"/api/trace/{RUN_ID}", None),
    ],
)
def test_business_endpoints_503_when_core_not_ready(
    degraded_client: TestClient, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    call = getattr(degraded_client, method)
    response = call(path, json=payload) if payload is not None else call(path)
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "核心服务暂未就绪" in detail
    assert "cbr." in detail  # 明确指出待实现模块


def test_scenarios_still_available_when_core_not_ready(degraded_client: TestClient) -> None:
    # 场景来自 configs/scenarios.yaml，核心未就绪时前端仍可展示
    response = degraded_client.get("/api/scenarios")
    assert response.status_code == 200
    assert response.json()


def test_orchestrator_failure_returns_503_not_500(fake_service: FakeService, client: TestClient) -> None:
    fake_service.orchestrator.fail_run = RuntimeError("PIT 数据缺失：2024-08-05")
    response = client.get("/api/decision")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "核心服务执行失败" in detail
    assert "PIT 数据缺失" in detail


def test_orchestrator_bad_contract_returns_503(fake_service: FakeService, client: TestClient) -> None:
    fake_service.orchestrator.return_bad_contract = True
    response = client.get("/api/decision")
    assert response.status_code == 503
    assert "不符合 schemas.py 契约" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Streamlit 冒烟（AppTest，不开浏览器）
# --------------------------------------------------------------------------- #
def test_streamlit_dashboard_smoke(
    fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """驾驶台在核心服务就绪时应能完整渲染（不抛异常）。"""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(service_module, "get_service", lambda: fake_service)
    api_state.reset_cache()
    app_test = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=60)
    app_test.run()
    assert not app_test.exception, [str(exc.value) for exc in app_test.exception]


def test_streamlit_dashboard_degraded_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """核心模块未就绪时，驾驶台应显示友好提示而不是白屏/异常。"""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    def _not_ready() -> Any:
        raise ImportError("No module named 'cbr.orchestration'")

    monkeypatch.setattr(service_module, "get_service", _not_ready)
    app_test = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=60)
    app_test.run()
    assert not app_test.exception, [str(exc.value) for exc in app_test.exception]
