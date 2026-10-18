"""三角色智能体 + LLM 抽象层测试（task-3 验收）。

覆盖：
1. MockLLM 确定性、用量统计；
2. 三角色对样例 AgentContext 各生成合法 AgentOutput；
3. 全部 claim 绑定 evidence_ids（numeric 绑定工具证据且 value 逐字一致、
   text 绑定 KB chunk、directional 绑定信号证据）；
4. 越权工具被拒绝且不执行（角色白名单 / 注册表权限矩阵两条路径）；
5. token/tool_calls/latency 统计准确且递增，工具/token 预算生效；
6. 交叉验证轮、单智能体基线、LLM 失败降级；
7. DeepSeek 真实路径（假 OpenAI 客户端注入：JSON 模式、修复重试、传输重试、
   超时/模型参数、token 统计）；真实网络调用无 key 时自动 skip；
8. prompt 三角色差异与占位符渲染；Mock demo 可运行并落盘三张 RiskCard。

依赖全部用本文件内 stub 实现（DataProvider / ToolRegistry / KnowledgeBase），
不依赖 data-model / tools-knowledge 同事的进度。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from cbr.agents import (
    LEVEL_ORDER,
    RoleAgent,
    SingleAgent,
    build_role_agent,
    build_role_agents,
    build_single_agent,
    cross_check_system_prompt,
    role_system_prompt,
    single_agent_system_prompt,
)
from cbr.agents.demo import DEMO_AS_OF, run_demo
from cbr.agents.prompts import PROMPTS_DIR
from cbr.config import AppSettings, LLMSettings, load_role_specs, load_settings
from cbr.contracts import DataProvider, KnowledgeBase, LLMClient, ToolRegistry
from cbr.llm import (
    DeepSeekClient,
    LLMConfigError,
    LLMOutputError,
    LLMUnavailableError,
    MockLLM,
    build_llm_client,
    resolve_api_key,
)
from cbr.llm.base import encode_packet, format_number
from cbr.llm.drafts import CrossCheckDraft, DraftClaim, RoleAnalysisDraft
from cbr.schemas import (
    AgentContext,
    AgentOutput,
    ClaimType,
    DataCard,
    Evidence,
    EvidenceKind,
    ExperimentMode,
    MarketSnapshot,
    RiskDriver,
    RiskLevel,
    RiskSignal,
    Role,
    RoleSpec,
    SourceRef,
    ToolRef,
    ToolResult,
)

AS_OF = date(2024, 8, 5)


# =========================================================================== #
# Stub 依赖（contracts 协议的最小实现）
# =========================================================================== #
_TOOL_FIXTURES: dict[str, tuple[str, float, str]] = {
    "risk_measure": ("var_hist", 0.031, "ratio"),
    "systemic_risk": ("dy_spillover", 0.31, "ratio"),
    "capital_flow": ("northbound_outflow_z", 1.42, "z"),
    "funding_cost": ("funding_cost_change_bp", 12.0, "bp"),
    "scenario": ("scenario_loss", 0.087, "ratio"),
    "forecast": ("prob_high_stress", 0.48, "probability"),
}


class StubTool:
    """确定性工具 stub：返回带 Evidence 的 ToolResult，记录调用次数/参数。"""

    version = "stub-1.0.0"

    def __init__(
        self,
        name: str,
        *,
        kind: EvidenceKind = EvidenceKind.TOOL,
        evidence_id: str | None = None,
        value_override: float | None = None,
        unit_override: str | None = None,
        as_of_delta_days: int = 0,
        fail: bool = False,
    ) -> None:
        self.name = name
        self.description = f"stub tool {name}"
        self.kind = kind
        self.evidence_id = evidence_id or f"ev_tool_{name}_stub"
        self.value = value_override
        self.unit = unit_override
        self.as_of_delta_days = as_of_delta_days
        self.fail = fail
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}

    def run(self, as_of: date, **kwargs: Any) -> ToolResult:
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        if self.fail:
            raise RuntimeError(f"{self.name} simulated failure")
        key, value, unit = _TOOL_FIXTURES.get(self.name, ("metric", 0.5, "ratio"))
        if self.value is not None:
            value = self.value
        if self.unit is not None:
            unit = self.unit
        evidence_as_of = as_of + timedelta(days=self.as_of_delta_days)
        evidence = Evidence(
            evidence_id=self.evidence_id,
            kind=self.kind,
            as_of=evidence_as_of,
            title=f"{self.name}: {key}",
            summary=f"stub 工具输出（{self.name}）",
            payload={"primary_metric": key, "value": value},
            unit=unit,
            value=value,
            source=SourceRef(name=f"tool:{self.name}"),
            tool=ToolRef(name=self.name, version=self.version),
            produced_by="stub_tool",
        )
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=evidence_as_of,
            ok=True,
            data={"primary_metric": key, "value": value},
            unit=unit,
            evidence=evidence,
        )


class StubRegistry:
    """工具注册表 stub：权限矩阵 = role_specs 的 tool_permissions，可额外 deny。"""

    def __init__(
        self,
        role_specs: dict[Role, RoleSpec],
        *,
        denied: frozenset[str] = frozenset(),
        tools: dict[str, StubTool] | None = None,
    ) -> None:
        self.role_specs = role_specs
        self.denied = set(denied)
        self.tools = tools or {name: StubTool(name) for name in _TOOL_FIXTURES}

    def get(self, name: str) -> StubTool:
        return self.tools[name]  # 未注册 -> KeyError（与 ToolRegistry 协议一致）

    def names(self) -> list[str]:
        return sorted(self.tools)

    def allow(self, role: Role, tool_name: str) -> bool:
        if tool_name in self.denied:
            return False
        spec = self.role_specs.get(role)
        return bool(spec and tool_name in spec.tool_permissions)


class StubKB:
    """知识库 stub：返回带 chunk_id/publish_time 的 KB 证据，可选未来证据。"""

    def __init__(self, *, future: bool = False) -> None:
        self.future = future
        self.queries: list[tuple[str, date]] = []

    def search(self, query: str, as_of: date, top_k: int = 5) -> list[Evidence]:
        self.queries.append((query, as_of))
        items = [
            self._evidence("kb-001", "跨境资本流动宏观审慎管理要点", date(2024, 6, 28), as_of),
            self._evidence("kb-002", "组合尾部风险与相关性上升的应对", date(2024, 7, 15), as_of),
        ]
        if self.future:
            items.append(
                self._evidence("kb-future", "未来才会发布的政策文件", date(2024, 9, 1), as_of)
            )
        return items[:top_k]

    @staticmethod
    def _evidence(chunk_id: str, title: str, publish: date, as_of: date) -> Evidence:
        return Evidence(
            evidence_id=f"ev_{chunk_id}",
            kind=EvidenceKind.KB,
            as_of=publish,
            title=title,
            summary=f"{title}（stub 知识库片段）",
            payload={"chunk_id": chunk_id, "query_as_of": as_of.isoformat()},
            source=SourceRef(
                name="stub_knowledge_base",
                doc_id=f"doc-{chunk_id}",
                chunk_id=chunk_id,
            ),
            produced_by="stub_knowledge_base",
        )

    def count(self) -> int:
        return 3


class StubProvider:
    """DataProvider stub（RoleAgent 不直接消费，但构造函数契约要求）。"""

    def __init__(self, signal: RiskSignal | None = None) -> None:
        self._signal = signal

    def risk_signal(self, as_of: date) -> RiskSignal:
        return self._signal or make_signal(as_of)

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        return MarketSnapshot(as_of=as_of, series={"market.cn_equity.csi300": 0.01})

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict[str, Any]]:
        return []

    def label(self, as_of: date, horizon: int) -> int | None:
        return None

    def data_cards(self) -> list[DataCard]:
        return []


class FailingLLM:
    """LLMClient stub：结构化调用总是失败，用于测试降级路径。"""

    is_mock = False
    provider = "failing"
    model = "failing"
    mode = "failing:test"

    def __init__(self) -> None:
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        self.last_call: dict[str, Any] = {}

    @property
    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    def structured(self, system: str, user: str, schema: type, **kwargs: Any) -> Any:
        self._usage["calls"] += 1
        raise LLMUnavailableError("simulated network failure")

    def text(self, system: str, user: str, **kwargs: Any) -> str:
        raise LLMUnavailableError("simulated network failure")


# =========================================================================== #
# 数据 fixtures
# =========================================================================== #
def make_signal(as_of: date = AS_OF, *, horizons: dict[int, float] | None = None) -> RiskSignal:
    return RiskSignal(
        as_of=as_of,
        model_version="test-fusion-v1",
        horizons=horizons or {5: 0.32, 10: 0.48, 20: 0.57},
        percentile=0.86,
        level=RiskLevel.HIGH,
        drivers=[
            RiskDriver(factor="northbound_outflow_z", contribution=0.31, direction="up"),
            RiskDriver(factor="global_volatility", contribution=0.22, direction="up"),
        ],
        modality_contrib={"numeric": 0.72, "text": 0.28},
        evidence_id="ev_sig_test_20240805",
    )


def make_context(
    *,
    as_of: date = AS_OF,
    horizons: dict[int, float] | None = None,
    round_no: int = 0,
    peer_evidence: list[Evidence] | None = None,
    budget: dict[str, Any] | None = None,
) -> AgentContext:
    return AgentContext(
        as_of=as_of,
        mode=ExperimentMode.COLLABORATIVE,
        signal=make_signal(as_of, horizons=horizons),
        snapshot=MarketSnapshot(as_of=as_of, series={"market.cn_equity.csi300": 0.012}),
        round=round_no,
        peer_evidence=peer_evidence or [],
        budget=budget or {"run_id": "test-run"},
        task="测试：评估当前跨境金融压力。",
    )


@pytest.fixture(scope="session")
def settings() -> AppSettings:
    loaded = load_settings()
    loaded.llm.mock = True  # 测试固定走 MockLLM，不受本机 key 影响
    return loaded


@pytest.fixture(scope="session")
def role_specs() -> dict[Role, RoleSpec]:
    return load_role_specs()


@pytest.fixture()
def deps(role_specs: dict[Role, RoleSpec]) -> tuple[StubProvider, StubKB, StubRegistry]:
    return StubProvider(), StubKB(), StubRegistry(role_specs)


@pytest.fixture()
def mock_llm() -> MockLLM:
    return MockLLM()


def build_agent(
    role: Role,
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    llm: Any | None = None,
    **kwargs: Any,
) -> RoleAgent:
    provider, kb, registry = deps
    return build_role_agent(
        role_specs[role], registry, provider, kb, llm or MockLLM(), settings, **kwargs
    )


# =========================================================================== #
# 1. LLM 抽象层
# =========================================================================== #
def test_build_llm_client_uses_mock_without_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    llm_settings = LLMSettings(
        mock=False,
        api_key_env="DEEPSEEK_API_KEY",
        api_key_file="secrets/__missing_for_test__.key",
    )
    caplog.set_level(logging.INFO, logger="cbr.llm")
    client = build_llm_client(llm_settings)
    assert isinstance(client, MockLLM)
    assert client.is_mock is True
    assert "MockLLM" in caplog.text
    assert set(client.usage) == {"prompt_tokens", "completion_tokens", "total_tokens", "calls"}
    # force_real 且无 key 必须显式报错（绝不硬编码/偷偷联网）
    with pytest.raises(LLMConfigError):
        build_llm_client(llm_settings, force_real=True)


def test_build_llm_client_real_client_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-injected")
    llm_settings = LLMSettings(
        mock=False,
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        api_key_file="secrets/__missing_for_test__.key",
    )
    client = build_llm_client(llm_settings)
    assert isinstance(client, DeepSeekClient)
    assert client.is_mock is False
    assert client.provider == "deepseek"
    assert client.model == "deepseek-chat"


def test_mock_llm_deterministic_and_usage_monotonic() -> None:
    llm = MockLLM()
    packet = {
        "as_of": "2024-08-05",
        "role_key": "regulator",
        "role": {"key": "regulator", "display_name": "监管主体智能体"},
        "risk_level": "high",
        "signal": {"evidence_id": "ev_sig_x", "drivers": [{"factor": "f", "direction": "up"}]},
        "facts": [
            {
                "evidence_id": "ev_tool_risk_measure",
                "claim_type": "numeric",
                "label": "历史模拟 VaR",
                "value": 0.031,
                "unit": "ratio",
            },
            {"evidence_id": "ev_kb_1", "claim_type": "text", "title": "知识库片段"},
        ],
    }
    prompt = "请分析证据包：\n" + encode_packet(packet)
    first = llm.structured("system", prompt, RoleAnalysisDraft)
    usage_after_first = llm.usage
    second = llm.structured("system", prompt, RoleAnalysisDraft)
    usage_after_second = llm.usage

    assert first == second  # 完全确定性
    assert usage_after_first["calls"] == 1
    assert usage_after_second["calls"] == 2
    assert usage_after_second["total_tokens"] > usage_after_first["total_tokens"] > 0
    assert llm.last_call["mode"] == "mock"
    numeric_claims = [claim for claim in second.claims if claim.claim_type == "numeric"]
    assert numeric_claims and numeric_claims[0].value == 0.031
    assert numeric_claims[0].unit == "ratio"


def test_llm_protocol_runtime_check(mock_llm: MockLLM) -> None:
    assert isinstance(mock_llm, LLMClient)
    assert callable(mock_llm.structured) and callable(mock_llm.text)


# --------------------------------------------------------------------------- #
# DeepSeek 真实路径（注入假 OpenAI 客户端，不联网）
# --------------------------------------------------------------------------- #
class _FakeUsage:
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class _FakeResponse:
    def __init__(self, content: str, usage: _FakeUsage | None = None) -> None:
        message = type("_Msg", (), {"content": content})()
        choice = type("_Choice", (), {"message": message})()
        self.choices = [choice]
        self.usage = usage or _FakeUsage()


class _FakeCompletions:
    def __init__(
        self,
        contents: list[str] | None = None,
        *,
        error_sequence: list[BaseException] | None = None,
    ) -> None:
        self.contents = list(contents or [])
        self.error_sequence = list(error_sequence or [])
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if self.error_sequence:
            error = self.error_sequence.pop(0)
            if error is not None:
                raise error
        content = self.contents[min(len(self.calls) - 1, len(self.contents) - 1)]
        return _FakeResponse(content)


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = type("_Chat", (), {"completions": completions})()


def _deepseek_with_fake(completions: _FakeCompletions, **overrides: Any) -> DeepSeekClient:
    llm_settings = LLMSettings(
        mock=False,
        model="deepseek-chat",
        max_retries=overrides.pop("max_retries", 2),
        timeout_seconds=overrides.pop("timeout_seconds", 30),
        **overrides,
    )
    return DeepSeekClient(
        llm_settings,
        api_key="sk-test-injected",
        client=_FakeClient(completions),
        sleep_fn=lambda seconds: None,
    )


def test_deepseek_json_mode_and_schema_repair_retry() -> None:
    valid = RoleAnalysisDraft(headline="修复后的标题", claims=[], limitations=[]).model_dump_json()
    completions = _FakeCompletions(contents=["{\"claims\": 123}", valid])
    client = _deepseek_with_fake(completions)

    result = client.structured("系统提示", "用户提示", RoleAnalysisDraft)
    assert isinstance(result, RoleAnalysisDraft)
    assert result.headline == "修复后的标题"
    assert len(completions.calls) == 2

    first_call = completions.calls[0]
    assert first_call["model"] == "deepseek-chat"
    assert first_call["response_format"] == {"type": "json_object"}
    assert first_call["timeout"] == 30
    assert "JSON Schema" in first_call["messages"][0]["content"]
    assert "json" in first_call["messages"][0]["content"].lower()

    second_call = completions.calls[1]
    assert "输出修复要求" in second_call["messages"][1]["content"]

    usage = client.usage
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 20 and usage["completion_tokens"] == 10
    assert usage["total_tokens"] == 30
    assert client.last_call["attempts"] == 2


def test_deepseek_output_error_after_repair_exhausted() -> None:
    completions = _FakeCompletions(contents=["not-json", "still-not-json", "{}"])
    client = _deepseek_with_fake(completions, max_retries=1)
    with pytest.raises(LLMOutputError) as excinfo:
        client.structured("system", "user", RoleAnalysisDraft)
    assert excinfo.value.attempts == 2
    assert len(completions.calls) == 2


def test_deepseek_transport_retry_with_backoff() -> None:
    class TransientError(Exception):
        status_code = 503

    valid = RoleAnalysisDraft(headline="成功", claims=[], limitations=[]).model_dump_json()
    completions = _FakeCompletions(contents=[valid], error_sequence=[TransientError("503")])
    sleeps: list[float] = []
    llm_settings = LLMSettings(mock=False, max_retries=2, timeout_seconds=10)
    client = DeepSeekClient(
        llm_settings,
        api_key="sk-test",
        client=_FakeClient(completions),
        sleep_fn=sleeps.append,
    )
    result = client.structured("system", "user", RoleAnalysisDraft)
    assert result.headline == "成功"
    assert len(completions.calls) == 2
    assert sleeps == [0.5]
    assert client.last_call["transport_attempts"] == 2
    assert client.usage["calls"] == 1  # 只有成功响应计入 usage


def test_deepseek_unavailable_after_all_retries() -> None:
    class TransientError(Exception):
        status_code = 429

    completions = _FakeCompletions(error_sequence=[TransientError("429")] * 3)
    sleeps: list[float] = []
    llm_settings = LLMSettings(mock=False, max_retries=2, timeout_seconds=10)
    client = DeepSeekClient(
        llm_settings,
        api_key="sk-test",
        client=_FakeClient(completions),
        sleep_fn=sleeps.append,
    )
    with pytest.raises(LLMUnavailableError):
        client.structured("system", "user", RoleAnalysisDraft)
    assert len(completions.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_deepseek_text_generation_usage() -> None:
    completions = _FakeCompletions(contents=["这是自由文本回复"])
    client = _deepseek_with_fake(completions)
    assert client.text("系统", "用户") == "这是自由文本回复"
    assert client.usage["calls"] == 1
    assert "response_format" not in completions.calls[0]
    assert client.last_call["json_mode"] is False


def test_deepseek_real_call_skipped_without_key(settings: AppSettings) -> None:
    """真实 DeepSeek 网络调用：无 key 自动 skip（有 key 时验证同一代码路径）。"""

    key = resolve_api_key(settings.llm)
    if not key:
        pytest.skip("未配置 DEEPSEEK_API_KEY / secrets/deepseek.key，跳过真实 DeepSeek 调用")

    class TinyOutput(BaseModel):
        ok: bool = False
        note: str = ""

    client = DeepSeekClient(settings.llm, api_key=key)
    try:
        result = client.structured(
            "你是一个 JSON 输出助手。",
            '请输出 JSON：{"ok": true, "note": "pong"}',
            TinyOutput,
        )
    except LLMUnavailableError as exc:  # 有 key 但网络不可用：跳过而非误报红
        pytest.skip(f"网络不可用，跳过真实调用：{exc}")
    assert isinstance(result, TinyOutput)
    assert result.ok is True


# =========================================================================== #
# 2. Prompt 模板
# =========================================================================== #
def test_role_prompts_reflect_spec_differences(role_specs: dict[Role, RoleSpec]) -> None:
    prompts: dict[Role, str] = {}
    for role, spec in role_specs.items():
        prompt = role_system_prompt(spec)
        prompts[role] = prompt
        assert spec.display_name in prompt
        assert spec.objective.strip()[:20] in prompt
        for tool_name in spec.tool_permissions:
            assert tool_name in prompt, f"{role.value} prompt 缺少工具 {tool_name}"
        for forbidden in spec.forbidden_actions:
            assert forbidden in prompt
        assert "evidence_ids" in prompt
        assert "{{" not in prompt, "prompt 中存在未渲染占位符"
        assert "JSON" in prompt
    # 三个角色的 prompt 必须实质不同（目标/权限/禁止行为差异）
    assert len(set(prompts.values())) == len(prompts)
    assert "具体证券买卖建议" in prompts[Role.REGULATOR]
    assert "尾部" in prompts[Role.INVESTOR]
    assert "融资" in prompts[Role.FINANCING]


def test_cross_validation_and_single_agent_prompts(role_specs: dict[Role, RoleSpec]) -> None:
    cross = cross_check_system_prompt(role_specs[Role.REGULATOR])
    assert "peer_facts" in cross
    assert "confirmed" in cross
    assert "复核" in cross

    single = single_agent_system_prompt(role_specs)
    assert "单智能体基线" in single
    for spec in role_specs.values():
        assert spec.objective.strip()[:20] in single
    assert "{{" not in single
    # prompt 模板目录存在且被加载
    assert PROMPTS_DIR.exists()
    assert (PROMPTS_DIR / "common_rules.md").exists()
    assert (PROMPTS_DIR / "regulator.md").exists()


# =========================================================================== #
# 3. 三角色 AgentOutput 合法性
# =========================================================================== #
def test_three_roles_produce_valid_agent_outputs(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    mock_llm: MockLLM,
) -> None:
    context = make_context()
    agents = build_role_agents(
        deps[2], deps[0], deps[1], mock_llm, settings, role_specs=role_specs
    )
    assert set(agents) == {Role.REGULATOR, Role.INVESTOR, Role.FINANCING}

    for role, agent in agents.items():
        output = agent.analyze(context)
        assert isinstance(output, AgentOutput)
        assert output.role == role
        assert output.card.role == role
        # schema 再次校验（Pydantic round-trip）
        AgentOutput.model_validate(output.model_dump())

        available = {item.evidence_id for item in output.evidence}
        assert output.card.base_signal_ref in available
        assert output.card.claims, f"{role.value} 未产出 claims"
        assert output.card.evidence_ids
        assert output.card.as_of == context.as_of
        assert output.card.risk_level in set(RiskLevel)

        for claim in output.card.claims:
            assert claim.evidence_ids, f"{role.value} claim {claim.claim_id} 无证据"
            assert set(claim.evidence_ids) <= available
            assert claim.claim_type in set(ClaimType)
            if claim.claim_type == ClaimType.NUMERIC:
                assert claim.value is not None and claim.unit is not None
                bound_numeric = [
                    evidence
                    for evidence in output.evidence
                    if evidence.evidence_id in claim.evidence_ids
                    and evidence.kind == EvidenceKind.TOOL
                    and evidence.value is not None
                ]
                assert bound_numeric, "numeric claim 未绑定工具证据"
                assert any(abs(float(e.value) - claim.value) <= 1e-9 for e in bound_numeric)
            elif claim.claim_type == ClaimType.TEXT:
                bound_text = [
                    evidence
                    for evidence in output.evidence
                    if evidence.evidence_id in claim.evidence_ids
                    and evidence.kind == EvidenceKind.KB
                ]
                assert bound_text, "text claim 未绑定 KB 证据"
                assert any(e.source.chunk_id for e in bound_text)
            elif claim.claim_type == ClaimType.DIRECTIONAL:
                assert claim.direction in {"up", "down", "flat", "none"}
                assert output.card.base_signal_ref in claim.evidence_ids

        assert output.tool_calls > 0
        assert output.tokens > 0
        assert output.latency_ms >= 0
        actions = {event.action for event in output.trace}
        assert {"signal", "tool_call", "llm_call", "claim", "finalize"} <= actions
        # 工具调用数与实际成功执行的 tool_call 事件一致
        tool_call_events = [
            event for event in output.trace if event.action == "tool_call" and event.detail.get("ok")
        ]
        assert output.tool_calls >= len(tool_call_events)
        # JSON 可序列化
        assert json.loads(output.model_dump_json())["role"] == role.value

    # 三角色风险等级存在差异（阈值不同：监管 0.50 / 投资 0.45 / 融资 0.40）
    levels = {
        role: agent.analyze(context).card.risk_level for role, agent in agents.items()
    }
    assert levels[Role.FINANCING] >= levels[Role.INVESTOR] or levels[Role.INVESTOR] >= levels[Role.REGULATOR]


def test_role_thresholds_are_role_specific(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    mock_llm: MockLLM,
) -> None:
    context = make_context(horizons={5: 0.46, 10: 0.46, 20: 0.46})
    agents = build_role_agents(
        deps[2], deps[0], deps[1], mock_llm, settings, role_specs=role_specs
    )
    regulator = agents[Role.REGULATOR].analyze(context).card.risk_level
    investor = agents[Role.INVESTOR].analyze(context).card.risk_level
    financing = agents[Role.FINANCING].analyze(context).card.risk_level
    assert regulator == RiskLevel.MEDIUM  # 0.46 < 0.50
    assert investor == RiskLevel.HIGH  # 0.46 >= 0.45
    assert financing == RiskLevel.HIGH  # 0.46 >= 0.40


def test_mock_numeric_claims_never_fabricate_numbers(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    mock_llm: MockLLM,
) -> None:
    context = make_context()
    agents = build_role_agents(
        deps[2], deps[0], deps[1], mock_llm, settings, role_specs=role_specs
    )
    for role, agent in agents.items():
        output = agent.analyze(context)
        evidence_by_id = {item.evidence_id: item for item in output.evidence}
        for claim in output.card.claims:
            if claim.claim_type != ClaimType.NUMERIC:
                continue
            evidence = evidence_by_id[claim.evidence_ids[0]]
            assert evidence.kind == EvidenceKind.TOOL
            assert float(evidence.value) == claim.value
            numbers = re.findall(r"-?\d+(?:\.\d+)?", claim.text)
            assert [float(number) for number in numbers] == [claim.value], (
                f"{role.value}/{claim.claim_id} 文本数字与 value 不一致：{claim.text}"
            )
            assert format_number(claim.value) in claim.text


def test_mock_outputs_are_deterministic(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    context = make_context()
    first = build_agent(Role.REGULATOR, deps, settings, role_specs, MockLLM()).analyze(context)
    second = build_agent(Role.REGULATOR, deps, settings, role_specs, MockLLM()).analyze(context)
    # latency_ms 为真实耗时，不参与确定性比较
    assert first.card.model_dump(exclude={"latency_ms"}) == second.card.model_dump(
        exclude={"latency_ms"}
    )
    assert first.tokens == second.tokens
    assert first.tool_calls == second.tool_calls


# =========================================================================== #
# 4. 权限 / 预算 / 时点
# =========================================================================== #
def test_tool_permission_denied_by_role_spec_is_not_executed(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    provider, kb, registry = deps
    restricted = role_specs[Role.REGULATOR].model_copy(
        update={"tool_permissions": ["knowledge_search"]}
    )
    agent = build_role_agent(restricted, registry, provider, kb, MockLLM(), settings)
    output = agent.analyze(make_context())

    denied = [event for event in output.trace if event.action == "tool_denied"]
    assert denied, "越权工具未记录 trace"
    assert all(event.detail.get("violation") is True for event in denied)
    assert all(event.detail.get("reason") == "not_in_role_permissions" for event in denied)
    assert output.tool_calls == 0
    for tool_name, tool in registry.tools.items():
        assert tool.calls == 0, f"越权工具 {tool_name} 被执行"
    # 仍能用共享信号 + KB 证据产出合法 claim（证据不足时不得编造数字）
    assert output.card.claims
    numeric_claims = [c for c in output.card.claims if c.claim_type == ClaimType.NUMERIC]
    assert numeric_claims == []
    assert all(c.evidence_ids for c in output.card.claims)
    assert output.card.risk_level in set(RiskLevel)


def test_tool_permission_denied_by_registry_is_recorded(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    provider, kb, registry = deps
    registry.denied = {"risk_measure"}
    agent = build_role_agent(role_specs[Role.INVESTOR], registry, provider, kb, MockLLM(), settings)
    output = agent.analyze(make_context())

    denied = [event for event in output.trace if event.action == "tool_denied"]
    assert any(event.tool == "risk_measure" for event in denied)
    assert all(event.detail.get("reason") == "registry_denied" for event in denied)
    assert registry.tools["risk_measure"].calls == 0
    assert all(e.evidence_id != "ev_tool_risk_measure_stub" for e in output.evidence)


def test_tool_budget_limits_calls(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    context = make_context(budget={"run_id": "budget-run", "max_tool_calls": 2})
    agent = build_agent(Role.REGULATOR, deps, settings, role_specs)
    output = agent.analyze(context)
    assert output.tool_calls == 2
    assert any(event.action == "tool_skip" for event in output.trace)
    assert output.card.claims


def test_kb_future_evidence_filtered(
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    mock_llm: MockLLM,
) -> None:
    provider = StubProvider()
    kb = StubKB(future=True)
    registry = StubRegistry(role_specs)
    agent = build_role_agent(role_specs[Role.REGULATOR], registry, provider, kb, mock_llm, settings)
    output = agent.analyze(make_context())

    kb_evidence = [item for item in output.evidence if item.kind == EvidenceKind.KB]
    assert kb_evidence
    assert all(item.as_of <= AS_OF for item in kb_evidence)
    assert all(item.evidence_id != "ev_kb-future" for item in output.evidence)
    available = {item.evidence_id for item in output.evidence}
    for claim in output.card.claims:
        assert set(claim.evidence_ids) <= available


def test_tool_evidence_with_future_as_of_is_rejected(
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
    mock_llm: MockLLM,
) -> None:
    provider, kb = StubProvider(), StubKB()
    leaking = StubTool("risk_measure", as_of_delta_days=10)
    registry = StubRegistry(role_specs, tools={name: StubTool(name) for name in _TOOL_FIXTURES})
    registry.tools["risk_measure"] = leaking
    agent = build_role_agent(role_specs[Role.INVESTOR], registry, provider, kb, mock_llm, settings)
    output = agent.analyze(make_context())

    assert not any(e.evidence_id == leaking.evidence_id for e in output.evidence)
    assert any(event.action == "leakage_reject" for event in output.trace)
    assert leaking.calls == 1


# =========================================================================== #
# 5. token / tool 统计
# =========================================================================== #
def test_token_and_tool_stats_are_accurate(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    llm = MockLLM()
    context = make_context()
    before = llm.usage

    output = build_agent(Role.REGULATOR, deps, settings, role_specs, llm).analyze(context)
    after = llm.usage
    delta = {key: after[key] - before[key] for key in after}

    assert delta["calls"] == 1  # R0 只有一次角色分析 LLM 调用
    assert output.tokens == delta["total_tokens"] > 0
    assert output.card.tokens == output.tokens
    assert output.tool_calls == len(
        [event for event in output.trace if event.action == "tool_call" and event.detail.get("ok")]
    )
    llm_event = next(event for event in output.trace if event.action == "llm_call")
    assert llm_event.tokens == delta["total_tokens"]
    assert llm_event.detail["prompt_tokens"] == delta["prompt_tokens"]
    assert llm_event.detail["llm_mode"] == "mock"

    # 第二次调用 token 继续累计
    second = build_agent(Role.INVESTOR, deps, settings, role_specs, llm).analyze(context)
    assert llm.usage["total_tokens"] > after["total_tokens"]
    assert second.tokens > 0


# =========================================================================== #
# 6. 交叉验证 / 单智能体 / 降级
# =========================================================================== #
def _peer_evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id="ev_peer_1",
            kind=EvidenceKind.TOOL,
            as_of=AS_OF,
            title="peer risk_measure: var_hist",
            payload={"primary_metric": "var_hist", "value": 0.029},
            unit="ratio",
            value=0.029,
            produced_by="investor",
            tool=ToolRef(name="risk_measure", version="stub-1.0.0"),
        ),
        Evidence(
            evidence_id="ev_peer_2",
            kind=EvidenceKind.TOOL,
            as_of=AS_OF,
            title="peer funding_cost: funding_cost_change_bp",
            payload={"primary_metric": "funding_cost_change_bp", "value": 55.0},
            unit="bp",
            value=55.0,
            produced_by="financing",
            tool=ToolRef(name="funding_cost", version="stub-1.0.0"),
        ),
    ]


def test_cross_validation_round(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    llm = MockLLM()
    context = make_context(round_no=1, peer_evidence=_peer_evidence())
    output = build_agent(Role.REGULATOR, deps, settings, role_specs, llm).analyze(context)

    assert llm.usage["calls"] == 2  # 角色分析 + 交叉验证
    cross_events = [event for event in output.trace if event.action == "cross_check"]
    assert cross_events
    finding_events = [event for event in cross_events if "verdict" in event.detail]
    assert finding_events
    peer_ids = {item.evidence_id for item in _peer_evidence()}
    for event in finding_events:
        assert event.detail["evidence_id"] in peer_ids
        assert event.detail["verdict"] in {"confirmed", "refuted", "uncertain"}
    assert any("交叉复核" in limitation for limitation in output.card.limitations)
    assert output.tokens > 0


def test_single_agent_mode(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    llm = MockLLM()
    single = build_single_agent(deps[2], deps[0], deps[1], llm, settings, role_specs=role_specs)
    assert isinstance(single, SingleAgent)
    # 三主体工具权限并集：既包含投资侧的 capital_flow，也包含融资侧的 funding_cost
    assert "capital_flow" in single.tool_plan
    assert "funding_cost" in single.tool_plan
    assert "knowledge_search" not in single.tool_plan  # KB 由智能体直连检索

    result = single.analyze(make_context())
    assert result.mode == ExperimentMode.SINGLE
    assert set(result.cards) == {"regulator", "investor", "financing"}
    assert llm.usage["calls"] == 3  # 一个通用 agent 依次完成三次主体任务
    assert result.tool_calls == sum(output.tool_calls for output in result.cards.values()) > 0
    assert result.tokens == sum(output.tokens for output in result.cards.values()) > 0
    start_events = [event for event in result.trace if event.action == "single_agent_start"]
    finalize_events = [event for event in result.trace if event.action == "finalize"]
    assert start_events and finalize_events
    for output in result.cards.values():
        AgentOutput.model_validate(output.model_dump())
        assert output.card.claims
        assert all(claim.evidence_ids for claim in output.card.claims)
    # 通用 agent 使用三主体工具并集：监管任务也会调用融资工具 funding_cost
    regulator_evidence = {e.evidence_id for e in result.cards["regulator"].evidence}
    assert "ev_tool_funding_cost_stub" in regulator_evidence


def test_single_agent_analyze_one_returns_agent_output(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    single = build_single_agent(deps[2], deps[0], deps[1], MockLLM(), settings, role_specs=role_specs)
    output = single.analyze_one(make_context(), Role.FINANCING)
    assert isinstance(output, AgentOutput)
    assert output.role == Role.FINANCING


def test_llm_failure_falls_back_to_deterministic_card(
    deps: tuple[StubProvider, StubKB, StubRegistry],
    settings: AppSettings,
    role_specs: dict[Role, RoleSpec],
) -> None:
    output = build_agent(
        Role.REGULATOR, deps, settings, role_specs, FailingLLM()
    ).analyze(make_context())

    assert output.card.claims
    available = {item.evidence_id for item in output.evidence}
    assert all(set(claim.evidence_ids) <= available for claim in output.card.claims)
    actions = {event.action for event in output.trace}
    assert "llm_error" in actions
    assert "llm_fallback" in actions
    assert any("降级" in limitation or "不可用" in limitation for limitation in output.card.limitations)


# =========================================================================== #
# 7. Demo（Mock 模式三张 RiskCard 落盘）
# =========================================================================== #
def test_demo_mock_writes_three_risk_cards(tmp_path: Any) -> None:
    result = run_demo(prefer_real=False, force_mock=True, out_dir=tmp_path)
    assert result["llm_is_mock"] is True
    assert set(result["cards"]) == {"regulator", "investor", "financing"}
    combined = tmp_path / "mock_role_cards.json"
    assert combined.exists()
    payload = json.loads(combined.read_text(encoding="utf-8"))
    assert set(payload["cards"]) == {"regulator", "investor", "financing"}
    for role in ("regulator", "investor", "financing"):
        card_path = tmp_path / f"mock_{role}_card.json"
        assert card_path.exists()
        card = json.loads(card_path.read_text(encoding="utf-8"))
        assert card["role"] == role
        assert card["claims"]
        for claim in card["claims"]:
            assert claim["evidence_ids"]
    assert result["usage"]["tokens"] > 0
    assert result["as_of"] == DEMO_AS_OF.isoformat()
