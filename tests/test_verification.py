"""验证与审计层测试：六类核验问题各 1 例 + 比率/window + trace 读写。

- numeric：claim.value / claim.text 与引用证据数值不一致；
- citation：引用的证据不存在 / KB 证据缺少 chunk_id 或 publish_time；
- leakage：证据 as_of / release_time 晚于决策 as_of；
- permission：trace 中 tool_denied / allowed=false；
- schema：RiskCard 重新校验失败、claim_id 重复；
- unsupported：claim 未绑定 evidence_ids。
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from cbr.config import AppSettings, OrchestrationSettings
from cbr.schemas import (
    Claim,
    ClaimStatus,
    ClaimType,
    DecisionCard,
    Evidence,
    EvidenceKind,
    MetricItem,
    RiskCard,
    RiskLevel,
    RiskSignal,
    Role,
    SourceRef,
    ToolRef,
    TraceEvent,
)
from cbr.verification import resolve_tolerances, verify
from cbr.verification.numeric import extract_numbers, flatten_numbers, numbers_match
from cbr.verification.trace import (
    TraceWriter,
    events_to_dicts,
    make_run_id,
    read_trace,
    resolve_trace_path,
    trace_ref_for,
)

AS_OF = date(2024, 8, 5)


# --------------------------------------------------------------------------- #
# 构造工具
# --------------------------------------------------------------------------- #
def make_evidence(
    evidence_id: str,
    *,
    kind: EvidenceKind = EvidenceKind.TOOL,
    value: float | None = None,
    payload: dict | None = None,
    as_of: date = AS_OF,
    unit: str | None = None,
    chunk_id: str | None = None,
    publish_time: datetime | None = None,
    summary: str = "",
) -> Evidence:
    if value is not None and payload is None:
        payload = {"value": value}
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        as_of=as_of,
        title=evidence_id,
        summary=summary or (f"{evidence_id}={value}" if value is not None else evidence_id),
        payload=payload or {},
        value=value,
        unit=unit,
        source=SourceRef(name="stub", chunk_id=chunk_id, release_time=publish_time),
        tool=ToolRef(name="stub_tool", version="1.0.0", inputs_hash=evidence_id)
        if kind == EvidenceKind.TOOL
        else None,
    )


def make_claim(
    claim_id: str = "c1",
    *,
    role: str = "regulator",
    claim_type: ClaimType = ClaimType.NUMERIC,
    subject: str = "northbound_outflow_z",
    text: str = "",
    value: float | None = None,
    unit: str | None = None,
    evidence_ids: list[str] | None = None,
    direction: str | None = None,
    status: ClaimStatus = ClaimStatus.UNVERIFIED,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        role=role,
        claim_type=claim_type,
        subject=subject,
        text=text,
        value=value,
        unit=unit,
        direction=direction,  # type: ignore[arg-type]
        evidence_ids=evidence_ids if evidence_ids is not None else [],
        status=status,
    )


def make_card(
    *,
    role: Role = Role.REGULATOR,
    claims: list[Claim] | None = None,
    recommendation: str = "",
    key_metrics: list[MetricItem] | None = None,
    evidence_ids: list[str] | None = None,
    as_of: date = AS_OF,
) -> RiskCard:
    return RiskCard(
        role=role,
        as_of=as_of,
        risk_level=RiskLevel.MEDIUM,
        headline="测试卡片",
        claims=claims or [],
        recommendation=recommendation,
        key_metrics=key_metrics or [],
        evidence_ids=evidence_ids
        or sorted({eid for claim in (claims or []) for eid in claim.evidence_ids}),
    )


def make_decision(
    cards: dict[str, RiskCard] | None = None,
    *,
    evidence: list[Evidence] | None = None,
    as_of: date = AS_OF,
    trace_ref: str | None = None,
    run_id: str = "test_run",
    signal_level: RiskLevel = RiskLevel.HIGH,
) -> DecisionCard:
    return DecisionCard(
        run_id=run_id,
        as_of=as_of,
        mode="collaborative",  # type: ignore[arg-type]
        signal=RiskSignal(
            as_of=as_of,
            model_version="stub-v1",
            horizons={5: 0.12, 10: 0.28, 20: 0.41},
            percentile=0.86,
            level=signal_level,
        ),
        cards=cards or {},
        evidence=evidence or [],
        trace_ref=trace_ref,
    )


def _index(*evidences: Evidence) -> dict[str, Evidence]:
    return {evidence.evidence_id: evidence for evidence in evidences}


@pytest.fixture()
def settings() -> AppSettings:
    app = AppSettings()
    app.orchestration.numeric_tolerance_abs = 1e-6
    app.orchestration.numeric_tolerance_rel = 1e-3
    return app


# --------------------------------------------------------------------------- #
# 1) numeric
# --------------------------------------------------------------------------- #
def test_numeric_error_detected(settings: AppSettings) -> None:
    evidence = make_evidence("ev_metric", value=1.0)
    claim = make_claim("c_num", value=1.5, unit="z", text="北向流出 z=1.50", evidence_ids=["ev_metric"])
    card = make_card(claims=[claim])
    decision = make_decision({"regulator": card}, evidence=[evidence])

    report = verify(decision, _index(evidence), settings)

    assert report.numeric_checks_total == 1
    assert report.numeric_checks_passed == 0
    assert report.numeric_error_rate == 1.0
    numeric_issues = [issue for issue in report.issues if issue.issue_type == "numeric"]
    assert len(numeric_issues) == 1
    assert numeric_issues[0].claim_id == "c_num"
    assert numeric_issues[0].severity == "error"
    assert report.passed is False


def test_numeric_tolerance_absolute_and_relative(settings: AppSettings) -> None:
    evidence = make_evidence("ev_metric", value=1.0)
    # 相对 1e-3 → 1.0005 通过；收紧到 1e-9 后失败
    claim = make_claim("c_num", value=1.0005, unit="z", evidence_ids=["ev_metric"])
    decision = make_decision({"regulator": make_card(claims=[claim])}, evidence=[evidence])

    tolerant = verify(decision, _index(evidence), settings)
    assert tolerant.numeric_checks_passed == 1
    assert tolerant.numeric_error_rate == 0.0

    strict_settings = AppSettings()
    strict_settings.orchestration.numeric_tolerance_abs = 1e-9
    strict_settings.orchestration.numeric_tolerance_rel = 1e-9
    strict = verify(decision, _index(evidence), strict_settings)
    assert strict.numeric_checks_passed == 0
    assert strict.numeric_error_rate == 1.0


def test_numeric_clean_claim_passes(settings: AppSettings) -> None:
    evidence = make_evidence("ev_metric", value=0.41)
    claim = make_claim("c_num", value=0.41, unit="prob", text="20 日高压力概率 0.41", evidence_ids=["ev_metric"])
    decision = make_decision({"regulator": make_card(claims=[claim])}, evidence=[evidence])
    report = verify(decision, _index(evidence), settings)
    assert report.numeric_checks_total == 1
    assert report.numeric_checks_passed == 1
    assert report.numeric_error_rate == 0.0
    assert report.passed is True


def test_recommendation_number_without_evidence_is_flagged(settings: AppSettings) -> None:
    evidence = make_evidence("ev_metric", value=0.41)
    claim = make_claim("c_num", value=0.41, unit="prob", evidence_ids=["ev_metric"])
    card = make_card(claims=[claim], recommendation="建议将仓位下调 5.5% 并维持对冲。")
    decision = make_decision({"regulator": card}, evidence=[evidence], )
    report = verify(decision, _index(evidence), settings)
    assert report.numeric_checks_total == 2  # claim 1 + recommendation 1
    assert report.numeric_checks_passed == 1
    assert any(
        issue.issue_type == "numeric" and "recommendation" in issue.detail for issue in report.issues
    )


# --------------------------------------------------------------------------- #
# 2) citation
# --------------------------------------------------------------------------- #
def test_citation_missing_evidence_detected(settings: AppSettings) -> None:
    claim = make_claim(
        "c_cite",
        claim_type=ClaimType.TEXT,
        text="监管政策强调跨境资本流动管理",
        evidence_ids=["ev_missing"],
    )
    decision = make_decision({"regulator": make_card(claims=[claim])})
    report = verify(decision, {}, settings)
    assert report.citation_checks_total == 1
    assert report.citation_checks_passed == 0
    assert report.evidence_accuracy == 0.0
    assert report.leakage_events == 0
    assert any(issue.issue_type == "citation" for issue in report.issues)
    # 共享 schema 的 passed 只看 numeric/permission/leakage/schema；
    # 引文准确率单独作为 P2 指标（evidence_accuracy），不并入 passed。
    assert report.passed is True 


def test_citation_kb_requires_chunk_and_publish_time(settings: AppSettings) -> None:
    kb_ok = make_evidence(
        "ev_kb_ok",
        kind=EvidenceKind.KB,
        chunk_id="chunk_1",
        publish_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        summary="政策文件：跨境资本流动宏观审慎管理",
    )
    kb_bad = make_evidence("ev_kb_bad", kind=EvidenceKind.KB, publish_time=None)
    claim_ok = make_claim(
        "c_kb_ok", claim_type=ClaimType.TEXT, text="宏观审慎管理", evidence_ids=["ev_kb_ok"]
    )
    claim_bad = make_claim(
        "c_kb_bad", claim_type=ClaimType.TEXT, text="缺乏元数据的知识片段", evidence_ids=["ev_kb_bad"]
    )
    decision = make_decision({"regulator": make_card(claims=[claim_ok, claim_bad])})
    report = verify(decision, _index(kb_ok, kb_bad), settings)
    assert report.citation_checks_total == 2
    assert report.citation_checks_passed == 1
    assert report.evidence_accuracy == 0.5
    assert any(issue.issue_type == "citation" and issue.claim_id == "c_kb_bad" for issue in report.issues)


def test_citation_kb_publish_time_after_as_of_detected(settings: AppSettings) -> None:
    future_kb = make_evidence(
        "ev_kb_future",
        kind=EvidenceKind.KB,
        chunk_id="chunk_future",
        publish_time=datetime(2024, 8, 6, tzinfo=timezone.utc),
        summary="未来才发布的政策文本",
    )
    claim = make_claim(
        "c_kb_future", claim_type=ClaimType.TEXT, text="政策文本", evidence_ids=["ev_kb_future"]
    )
    decision = make_decision({"regulator": make_card(claims=[claim])})
    report = verify(decision, _index(future_kb), settings)
    assert report.citation_checks_total == 1
    assert report.citation_checks_passed == 0
    assert report.leakage_events == 1  # 同时命中时点泄漏
    assert any(issue.issue_type == "citation" for issue in report.issues)
    assert any(issue.issue_type == "leakage" for issue in report.issues)


# --------------------------------------------------------------------------- #
# 3) leakage
# --------------------------------------------------------------------------- #
def test_leakage_evidence_after_as_of(settings: AppSettings) -> None:
    future_evidence = make_evidence("ev_future", value=1.0, as_of=AS_OF + timedelta(days=1))
    claim = make_claim("c_future", value=1.0, unit="z", evidence_ids=["ev_future"])
    decision = make_decision({"regulator": make_card(claims=[claim])})
    report = verify(decision, _index(future_evidence), settings)
    assert report.leakage_events == 1
    assert report.passed is False
    leakage_issues = [issue for issue in report.issues if issue.issue_type == "leakage"]
    assert len(leakage_issues) == 1
    assert "晚于决策 as_of" in leakage_issues[0].detail


def test_leakage_source_release_time_after_as_of(settings: AppSettings) -> None:
    evidence = make_evidence(
        "ev_release",
        value=1.0,
        publish_time=datetime.combine(AS_OF + timedelta(days=3), time(9, 0), tzinfo=timezone.utc),
    )
    decision = make_decision({"regulator": make_card(claims=[])})
    report = verify(decision, _index(evidence), settings)
    assert report.leakage_events == 1
    assert report.passed is False


# --------------------------------------------------------------------------- #
# 4) permission
# --------------------------------------------------------------------------- #
def test_permission_violation_from_trace_file(settings: AppSettings, tmp_path: Path) -> None:
    writer = TraceWriter("perm_run", tmp_path / "traces")
    writer.emit(
        step="R0",
        action="tool_denied",
        role="regulator",
        tool="funding_cost",
        detail={"reason": "role=regulator 无 funding_cost 权限", "violation": True},
    )
    writer.emit(step="R2", action="cross_check", role="investor", detail={"allowed": False, "skipped": True})
    writer.emit(step="R0", action="analysis_done", role="investor", detail={"claims": 1})

    decision = make_decision({"regulator": make_card(claims=[])}, trace_ref=str(writer.path))
    report = verify(decision, {}, settings)

    assert report.permission_violations == 1  # cross_check 的编排器自查不算越权
    assert report.passed is False
    issues = [issue for issue in report.issues if issue.issue_type == "permission"]
    assert len(issues) == 1
    assert issues[0].role == "regulator"
    assert "funding_cost" in issues[0].detail


def test_permission_tool_call_allowed_false(settings: AppSettings) -> None:
    event = TraceEvent(
        run_id="r1",
        step="R0",
        role="investor",
        action="tool_call",
        tool="funding_cost",
        detail={"allowed": False},
    )
    decision = make_decision({"regulator": make_card(claims=[])})
    report = verify(decision, {}, settings, trace_events=[event])
    assert report.permission_violations == 1
    assert report.passed is False


# --------------------------------------------------------------------------- #
# 5) schema
# --------------------------------------------------------------------------- #
def test_schema_error_invalid_riskcard(settings: AppSettings) -> None:
    good = make_card(claims=[])
    # 用 model_construct 构造一个绕过校验的非法卡片（模拟外部/LLM 直接写入的坏数据）
    bad = RiskCard.model_construct(
        role=Role.REGULATOR,
        as_of=AS_OF,
        risk_level="bogus-level",
        headline="bad",
        base_signal_ref=None,
        key_metrics=[],
        claims=[],
        recommendation="",
        decision_loss={},
        limitations=[],
        evidence_ids=[],
        tool_calls=0,
        tokens=0,
        latency_ms=0,
        round=0,
    )
    decision = make_decision({"regulator": good, "investor": bad})
    report = verify(decision, {}, settings)
    assert report.schema_errors == 1
    assert report.passed is False
    assert any(issue.issue_type == "schema" for issue in report.issues)


def test_schema_error_duplicate_claim_ids(settings: AppSettings) -> None:
    claim_a = make_claim("dup_id", value=1.0, evidence_ids=[])
    claim_b = make_claim("dup_id", value=2.0, evidence_ids=[])
    decision = make_decision({"regulator": make_card(claims=[claim_a, claim_b])})
    report = verify(decision, {}, settings)
    assert report.schema_errors >= 1
    assert any(issue.issue_type == "schema" and "重复" in issue.detail for issue in report.issues)


# --------------------------------------------------------------------------- #
# 6) unsupported
# --------------------------------------------------------------------------- #
def test_unsupported_claim_detected(settings: AppSettings) -> None:
    claim = make_claim(
        "c_unsupported", claim_type=ClaimType.TEXT, text="市场上存在隐性风险", evidence_ids=[]
    )
    decision = make_decision({"regulator": make_card(claims=[claim])})
    report = verify(decision, {}, settings)
    assert report.unsupported_claims == 1
    assert report.unsupported_claim_rate == 1.0
    assert report.citation_checks_total == 0
    assert any(issue.issue_type == "unsupported" for issue in report.issues)
    # schema 中 passed 只看数值/越权/泄漏/schema，无依据断言单独度量
    assert report.passed is True


def test_unsupported_rate_with_mixed_claims(settings: AppSettings) -> None:
    evidence = make_evidence("ev_metric", value=0.41)
    supported = make_claim("c1", value=0.41, unit="prob", evidence_ids=["ev_metric"])
    unsupported = make_claim("c2", claim_type=ClaimType.TEXT, text="无引用断言", evidence_ids=[])
    decision = make_decision({"regulator": make_card(claims=[supported, unsupported])}, evidence=[evidence])
    report = verify(decision, _index(evidence), settings)
    assert report.citation_checks_total == 1
    assert report.unsupported_claims == 1
    assert report.unsupported_claim_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# 干净决策 / 偏好差异 / settings 解析
# --------------------------------------------------------------------------- #
def test_clean_decision_passes_all_checks(settings: AppSettings) -> None:
    tool_evidence = make_evidence("ev_tool", value=0.41)
    kb_evidence = make_evidence(
        "ev_kb",
        kind=EvidenceKind.KB,
        chunk_id="chunk_1",
        publish_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        summary="跨境资本流动管理政策",
    )
    numeric = make_claim("c_num", value=0.41, unit="prob", text="20 日高压力概率 0.41", evidence_ids=["ev_tool"])
    text = make_claim(
        "c_text",
        claim_type=ClaimType.TEXT,
        subject="policy",
        text="监管政策强调跨境资本流动管理",
        evidence_ids=["ev_kb"],
    )
    card = make_card(claims=[numeric, text], recommendation="维持防御仓位并关注政策变化。")
    decision = make_decision({"regulator": card}, evidence=[tool_evidence, kb_evidence])
    report = verify(decision, _index(tool_evidence, kb_evidence), settings)
    assert report.passed is True
    assert report.numeric_error_rate == 0.0
    assert report.evidence_accuracy == 1.0
    assert report.unsupported_claims == 0
    assert report.leakage_events == 0
    assert report.permission_violations == 0
    assert report.schema_errors == 0


def test_preference_status_is_not_error(settings: AppSettings) -> None:
    evidence = make_evidence("ev_shared", value=0.41)
    up = make_claim(
        "c_up",
        claim_type=ClaimType.DIRECTIONAL,
        subject="stress_prob_h20",
        text="压力上行",
        value=0.41,
        direction="up",
        evidence_ids=["ev_shared"],
        status=ClaimStatus.PREFERENCE,
    )
    flat = make_claim(
        "c_flat",
        role="investor",
        claim_type=ClaimType.DIRECTIONAL,
        subject="stress_prob_h20",
        text="压力持平",
        value=0.41,
        direction="flat",
        evidence_ids=["ev_shared"],
        status=ClaimStatus.PREFERENCE,
    )
    card_reg = make_card(claims=[up])
    card_inv = make_card(role=Role.INVESTOR, claims=[flat])
    decision = make_decision({"regulator": card_reg, "investor": card_inv}, evidence=[evidence])
    report = verify(decision, _index(evidence), settings)
    assert report.numeric_error_rate == 0.0
    assert report.passed is True
    assert not [issue for issue in report.issues if issue.issue_type == "numeric"]


def test_resolve_tolerances_variants() -> None:
    app = AppSettings()
    app.orchestration.numeric_tolerance_abs = 2e-6
    app.orchestration.numeric_tolerance_rel = 2e-3
    assert resolve_tolerances(app) == (2e-6, 2e-3)
    assert resolve_tolerances(app.orchestration) == (2e-6, 2e-3)
    assert resolve_tolerances({"numeric_tolerance_abs": 3e-6, "numeric_tolerance_rel": 3e-3}) == (3e-6, 3e-3)
    assert resolve_tolerances(None) == (1e-6, 1e-3)


def test_numeric_helper_extracts_and_ignores_units() -> None:
    numbers = extract_numbers("5/10/20 日压力概率分别为 0.12、0.28、0.41，2024 年 92% 分位")
    assert 0.12 in numbers
    assert 0.28 in numbers
    assert 0.41 in numbers
    assert 92.0 in numbers
    assert 2024 not in numbers  # 年份被忽略
    assert 5 not in numbers and 10 not in numbers and 20 not in numbers  # 期限链被忽略
    assert numbers_match(92.0, 0.92)
    assert numbers_match(0.41, 0.4100004)
    assert not numbers_match(0.41, 0.55)
    assert flatten_numbers({"a": 1, "b": {"c": 2.5}, "d": ["3", True]}) == [1.0, 2.5, 3.0]


def test_verification_report_finalize_rates() -> None:
    from cbr.schemas import VerificationReport

    report = VerificationReport(
        numeric_checks_total=4,
        numeric_checks_passed=3,
        citation_checks_total=4,
        citation_checks_passed=2,
        unsupported_claims=1,
    ).finalize()
    assert report.numeric_error_rate == 0.25
    assert report.evidence_accuracy == 0.5
    assert report.unsupported_claim_rate == pytest.approx(0.2)
    assert report.passed is False  # numeric_error_rate > 0


# --------------------------------------------------------------------------- #
# trace writer
# --------------------------------------------------------------------------- #
def test_trace_writer_roundtrip(tmp_path: Path) -> None:
    run_id = make_run_id("collaborative", AS_OF, nonce="abcd1234")
    assert run_id == "collaborative_2024-08-05_abcd1234"
    writer = TraceWriter(run_id, tmp_path / "traces")
    first = writer.emit(
        step="R0",
        action="tool_call",
        role="regulator",
        tool="risk_measure",
        args_hash="args123",
        result_hash="res456",
        detail={"value": 0.41, "中文": "可读"},
        latency_ms=12,
        tokens=34,
    )
    writer.emit(step="R5", action="finalize", detail={"decision_path": str(writer.decision_path)})
    events = read_trace(writer.path)
    assert len(events) == 2
    assert events[0].run_id == run_id
    assert events[0].step == "R0"
    assert events[0].action == "tool_call"
    assert events[0].role == "regulator"
    assert events[0].tool == "risk_measure"
    assert events[0].args_hash == "args123"
    assert events[0].result_hash == "res456"
    assert events[0].detail["中文"] == "可读"
    assert events[0].latency_ms == 12
    assert events[0].tokens == 34
    assert first.ts is not None

    # 每个 JSONL 行都是合法 JSON（UI/API 可直接消费）
    with writer.path.open("r", encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert len(lines) == 2
    assert lines[0]["run_id"] == run_id

    # 追加写 + dict 序列化
    writer.write(events[0])  # 再写一条
    assert len(read_trace(writer.path)) == 3
    dicts = events_to_dicts(events)
    assert isinstance(dicts[0]["ts"], str)

    # 决策卡快照
    writer.write_decision({"run_id": run_id, "as_of": AS_OF.isoformat()})
    assert writer.decision_path.is_file()
    assert json.loads(writer.decision_path.read_text(encoding="utf-8"))["run_id"] == run_id

    assert resolve_trace_path(writer.path) == writer.path
    assert resolve_trace_path("not_exists.jsonl") is None
    assert read_trace("not_exists.jsonl") == []
    assert trace_ref_for(writer.path)


def test_trace_writer_tolerates_bad_lines(tmp_path: Path) -> None:
    writer = TraceWriter("bad_lines", tmp_path / "traces")
    writer.emit(step="R0", action="analysis_start")
    with writer.path.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json}\n")
    writer.emit(step="R1", action="evidence_share")
    events = read_trace(writer.path)
    assert len(events) == 2


def test_verify_reads_trace_ref_permission_violation(tmp_path: Path) -> None:
    writer = TraceWriter("perm_trace", tmp_path / "traces")
    writer.emit(
        step="R0",
        action="tool_call",
        role="financing",
        tool="capital_flow",
        args_hash="a",
        detail={"allowed": False},
    )
    settings = AppSettings()
    decision = make_decision({"regulator": make_card(claims=[])}, trace_ref=trace_ref_for(writer.path))
    report = verify(decision, {}, settings)
    assert report.permission_violations == 1
    assert report.passed is False
