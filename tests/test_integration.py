"""端到端集成测试（Lead 维护）：真实装配全部模块，跑通预警决策与对话。

运行前提：已执行 scripts/build_sample_data.py（或存在用户自建数据）。
本测试是"可交付"的最终门槛，覆盖：
- 服务装配与数据卡；
- 共享风险信号（P1 产物）schema；
- 协同决策卡（三主体 + 证据 + 冲突 + 核验 + trace）；
- 三种模式（single / independent / collaborative）；
- 对话入口返回带证据的回答；
- 核验器关键指标（无时点泄漏、无越权、数值可核验）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbr.config import load_scenarios, load_settings
from cbr.schemas import ChatRequest, DecisionCard, ExperimentMode, RiskSignal


@pytest.fixture(scope="module")
def service():
    from cbr.service import build_service

    svc = build_service(load_settings())
    return svc


def _pick_as_of(service) -> date:
    """选一个数据覆盖范围内、且能产出风险信号的日期。"""
    candidates: list[date] = []
    for scenario in sorted(load_scenarios(), key=lambda s: s.as_of, reverse=True):
        candidates.append(scenario.as_of)
    for card in service.provider.data_cards():
        if card.coverage_end:
            candidates.append(card.coverage_end - timedelta(days=5))
    for as_of in candidates:
        try:
            signal = service.provider.risk_signal(as_of)
        except Exception:  # noqa: BLE001 - 数据未覆盖时尝试下一个候选
            continue
        if isinstance(signal, RiskSignal) and signal.horizons:
            return as_of
    pytest.skip("数据未构建或无可用日期；请先运行 scripts/build_sample_data.py")


def test_data_cards(service) -> None:
    cards = service.provider.data_cards()
    assert len(cards) >= 5, "数据卡过少，数据层未正确初始化"
    for card in cards:
        assert card.series_id and card.source


def test_risk_signal(service) -> None:
    as_of = _pick_as_of(service)
    signal = service.provider.risk_signal(as_of)
    assert signal.as_of == as_of
    assert signal.model_version
    assert signal.horizons, "RiskSignal.horizons 不能为空"
    for horizon, prob in signal.horizons.items():
        assert horizon in (5, 10, 20)
        assert 0.0 <= prob <= 1.0
    assert signal.evidence_id


def test_collaborative_decision(service) -> None:
    as_of = _pick_as_of(service)
    decision = service.orchestrator.run(as_of=as_of, mode="collaborative")
    assert isinstance(decision, DecisionCard)
    assert decision.mode == ExperimentMode.COLLABORATIVE
    assert set(decision.cards) == {"regulator", "investor", "financing"}
    assert decision.evidence, "决策卡应包含证据快照"
    assert decision.signal.horizons
    # 核验：无时点泄漏 / 无越权 / schema 正常
    report = decision.verification
    assert report.leakage_events == 0
    assert report.permission_violations == 0
    assert report.schema_errors == 0
    # 审计 trace 文件
    assert decision.trace_ref
    trace_path = Path(decision.trace_ref)
    if not trace_path.is_absolute():
        trace_path = Path(__file__).resolve().parents[1] / trace_path
    assert trace_path.exists(), f"trace 文件不存在: {trace_path}"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert events, "trace 为空"


def test_other_modes(service) -> None:
    as_of = _pick_as_of(service)
    for mode in ("single", "independent"):
        decision = service.orchestrator.run(as_of=as_of, mode=mode)
        assert isinstance(decision, DecisionCard)
        assert decision.mode.value == mode
        assert set(decision.cards) == {"regulator", "investor", "financing"}


def test_read_only_evidence_and_trace(service) -> None:
    as_of = _pick_as_of(service)
    decision = service.orchestrator.run(as_of=as_of, mode="collaborative")
    assert decision.evidence
    ev = decision.evidence[0]
    found = service.orchestrator.get_evidence(ev.evidence_id)
    assert found is not None
    assert found.evidence_id == ev.evidence_id
    if decision.trace_ref:
        trace = service.orchestrator.get_trace(decision.run_id)
        assert trace, "get_trace 应能读回 trace 事件"


def test_chat(service) -> None:
    as_of = _pick_as_of(service)
    response = service.orchestrator.chat(
        ChatRequest(message="当前跨境金融风险处于什么水平？监管、投资和融资主体分别应该关注什么？", as_of=as_of)
    )
    assert response.reply.strip(), "对话回复不能为空"
    assert response.decision is not None
    assert response.decision.as_of == as_of
