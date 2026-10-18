"""确定性工具层测试。

覆盖：
- 每个工具返回合法 ToolResult + Evidence（kind/value/unit/payload/hash）；
- inputs_hash / evidence_id / evidence.hash 对相同输入稳定，对 as_of 敏感；
- 角色权限矩阵与越权阻断审计（权限唯一来源 configs/roles.yaml）；
- 数值合理性：历史/参数 VaR、CVaR、最大回撤、资金流 z-score、融资成本 bp、
  情景线性映射与历史类比、共享信号 Evidence 复用、知识检索 chunk_id/时点。
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from cbr.config import load_role_specs, load_settings
from cbr.contracts import Tool, ToolRegistry
from cbr.knowledge import KnowledgeBaseImpl
from cbr.schemas import (
    DataCard,
    Evidence,
    EvidenceKind,
    MarketSnapshot,
    RiskDriver,
    RiskLevel,
    RiskSignal,
    Role,
    ToolResult,
)
from cbr.tools import ToolRegistryImpl, build_tool_registry
from cbr.tools._numeric import (
    historical_tail,
    max_drawdown,
    parametric_tail,
    quantile,
    simple_returns,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "knowledge" / "corpus"
AS_OF = date(2024, 8, 5)


# --------------------------------------------------------------------------- #
# 测试用确定性 stub DataProvider（不依赖 data-model 模块）
# --------------------------------------------------------------------------- #
def _business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _price_levels(days: list[date], *, seed: int, base: float, drift: float, vol: float) -> np.ndarray:
    rng = np.random.RandomState(seed)
    returns = rng.normal(drift, vol, len(days))
    return base * np.exp(np.cumsum(returns))


class StubProvider:
    """满足 DataProvider 协议的固定合成数据，用于工具单测。"""

    def __init__(self) -> None:
        self._days = _business_days(date(2018, 1, 1), date(2025, 12, 31))
        self._series: dict[str, dict[date, float]] = {}
        specs = {
            "market.cn_equity.csi300": (11, 3500.0, 0.00015, 0.012),
            "market.cn_bond.cgb_index": (12, 100.0, 0.00002, 0.0025),
            "market.global.sp500": (13, 2700.0, 0.00035, 0.011),
            "market.fx.usdcny": (14, 6.5, 0.00003, 0.003),
            "market.global.vix": (19, 18.0, 0.0, 0.02),
        }
        for series_id, (seed, base, drift, vol) in specs.items():
            levels = _price_levels(self._days, seed=seed, base=base, drift=drift, vol=vol)
            self._series[series_id] = {
                day: float(value) for day, value in zip(self._days, levels)
            }
        rng = np.random.RandomState(15)
        self._series["rates.credit.aa_spread"] = {
            day: float(1.2 * math.exp(x))
            for day, x in zip(self._days, np.cumsum(rng.normal(0.0001, 0.004, len(self._days))))
        }
        rng = np.random.RandomState(16)
        self._series["crossborder.flows.northbound_net"] = {
            day: float(value) for day, value in zip(self._days, rng.normal(20.0, 55.0, len(self._days)))
        }
        rng = np.random.RandomState(17)
        self._series["crossborder.flows.southbound_net"] = {
            day: float(value) for day, value in zip(self._days, rng.normal(15.0, 45.0, len(self._days)))
        }
        rng = np.random.RandomState(18)
        self._series["crossborder.flows.ah_premium"] = {
            day: float(0.25 + 0.03 * math.sin(i / 50.0) + noise)
            for i, (day, noise) in enumerate(zip(self._days, rng.normal(0.0, 0.02, len(self._days))))
        }

    # -- 测试辅助 ---------------------------------------------------------
    def set_series(self, series_id: str, values: list[float], end: date = AS_OF) -> None:
        idx = self._index_of(end)
        days = self._days[idx - len(values) + 1 : idx + 1]
        assert len(days) == len(values)
        self._series[series_id] = {day: float(v) for day, v in zip(days, values)}

    # -- DataProvider 协议 -------------------------------------------------
    def risk_signal(self, as_of: date) -> RiskSignal:
        return RiskSignal(
            as_of=as_of,
            model_version="stub-fusion-v1",
            horizons={5: 0.25, 10: 0.40, 20: 0.55},
            percentile=0.81,
            level=RiskLevel.HIGH,
            drivers=[
                RiskDriver(factor="northbound_outflow_z", contribution=0.31, direction="up", description="北向流出"),
                RiskDriver(factor="us_equity_drawdown", contribution=0.22, direction="up", description="外部回撤"),
            ],
            modality_contrib={"numeric": 0.7, "text": 0.3},
            label_version="stress_pca_q90",
            evidence_id=f"ev_sig_{as_of:%Y%m%d}_stub",
        )

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        idx = self._index_of(as_of)
        day = self._days[idx]
        return MarketSnapshot(as_of=as_of, series={sid: values[day] for sid, values in self._series.items()})

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict]:
        values = self._series.get(series_id)
        if not values:
            return []
        end = self._index_of(as_of)
        start = max(0, end + 1 - max(1, int(lookback)))
        return [
            {"date": day, "value": values[day]}
            for day in self._days[start : end + 1]
            if day in values
        ]

    def label(self, as_of: date, horizon: int) -> int | None:
        return None

    def data_cards(self) -> list[DataCard]:
        return [
            DataCard(series_id=sid, name=sid, source="stub", coverage_end=AS_OF)
            for sid in sorted(self._series)
        ]

    # -- 内部 --------------------------------------------------------------
    def _index_of(self, as_of: date) -> int:
        if as_of <= self._days[0]:
            return 0
        if as_of >= self._days[-1]:
            return len(self._days) - 1
        low, high = 0, len(self._days) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if self._days[mid] <= as_of:
                low = mid
            else:
                high = mid - 1
        return low


class FutureRowProvider(StubProvider):
    """故意返回 as_of 之后的记录，验证工具层 PIT 防御。"""

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict]:
        rows = super().history(series_id, as_of, lookback)
        rows = list(rows)
        rows.append({"date": as_of + timedelta(days=7), "value": 1.0})
        return rows


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def provider() -> StubProvider:
    return StubProvider()


@pytest.fixture(scope="module")
def kb() -> KnowledgeBaseImpl:
    assert CORPUS_DIR.exists(), f"knowledge corpus missing: {CORPUS_DIR}"
    return KnowledgeBaseImpl.from_corpus(
        CORPUS_DIR, chunk_size=240, chunk_overlap=48
    )


@pytest.fixture(scope="module")
def registry(provider: StubProvider, kb: KnowledgeBaseImpl) -> ToolRegistryImpl:
    settings = load_settings()
    return build_tool_registry(settings, provider, kb)


def _assert_valid_tool_result(
    result: ToolResult,
    *,
    expected_kind: EvidenceKind = EvidenceKind.TOOL,
    unit_required: bool = True,
) -> Evidence:
    assert isinstance(result, ToolResult)
    assert result.ok is True, result.error
    assert isinstance(result.evidence, Evidence)
    evidence = result.evidence
    assert evidence.kind == expected_kind
    assert evidence.as_of == result.as_of
    assert evidence.evidence_id.startswith("ev_")
    assert evidence.tool is not None
    assert len(evidence.tool.inputs_hash or "") == 64
    assert len(evidence.hash or "") == 64
    assert evidence.payload == result.data
    assert result.elapsed_ms >= 0
    assert evidence.tool.elapsed_ms == result.elapsed_ms
    if unit_required:
        assert result.unit is not None
        assert evidence.unit == result.unit
    # 数值证据的主指标必须非空；文本 KB 证据允许 value=None
    if expected_kind in (EvidenceKind.TOOL, EvidenceKind.SIGNAL):
        assert evidence.value is not None
    # 必须可 JSON 序列化（供 API/trace 落盘）
    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    return evidence


def _run(registry: ToolRegistryImpl, role: str, tool: str, **kwargs) -> ToolResult:
    return registry.run(role, tool, AS_OF, **kwargs)


# --------------------------------------------------------------------------- #
# 注册表与权限矩阵
# --------------------------------------------------------------------------- #
def test_registry_factory_and_protocol(registry: ToolRegistryImpl) -> None:
    expected = {
        "capital_flow",
        "forecast",
        "funding_cost",
        "knowledge_search",
        "risk_measure",
        "scenario",
        "systemic_risk",
    }
    assert set(registry.names()) == expected
    assert len(registry) == 7
    assert isinstance(registry, ToolRegistry)
    assert isinstance(registry.get("risk_measure"), Tool)
    assert registry.get("risk_measure").version == "1.0.0"
    assert registry.tool_version("knowledge_search") == "1.0.0"


def test_permission_matrix_matches_roles_yaml(registry: ToolRegistryImpl) -> None:
    role_specs = load_role_specs()
    for role, spec in role_specs.items():
        for tool_name in registry.names():
            assert registry.allow(role, tool_name) == (tool_name in spec.tool_permissions), (
                role,
                tool_name,
            )
    # 未在 roles.yaml 定义的角色全部拒绝
    for role in ("coordinator", "verifier", "auditor"):
        assert all(not registry.allow(role, name) for name in registry.names())
    # 未知工具拒绝
    assert registry.allow("regulator", "report_export") is False


def test_permission_denied_returns_disallowed_and_audits(registry: ToolRegistryImpl) -> None:
    before = len(registry.audit_events)
    result = _run(registry, "financing", "systemic_risk")
    assert result.ok is False
    assert result.evidence is None
    assert result.data["disallowed"] is True
    assert result.data["role"] == "financing"
    assert result.error and "disallowed" in result.error
    events = registry.audit_events
    assert len(events) == before + 1
    event = events[-1]
    assert event.event_type == "permission_denied"
    assert event.role == "financing"
    assert event.tool_name == "systemic_risk"
    assert event.as_of == AS_OF
    assert result.data["audit_event_id"] == event.event_id


def test_allowed_call_does_not_audit(registry: ToolRegistryImpl) -> None:
    before = len(registry.audit_events)
    result = _run(registry, "investor", "risk_measure")
    assert result.ok is True
    assert len(registry.audit_events) == before


def test_registry_get_unknown_raises(registry: ToolRegistryImpl) -> None:
    with pytest.raises(KeyError):
        registry.get("no_such_tool")
    result = _run(registry, "regulator", "no_such_tool")
    assert result.ok is False
    assert result.data["unknown_tool"] is True
    assert "unknown tool" in (result.error or "")


def test_unknown_parameters_rejected(registry: ToolRegistryImpl) -> None:
    result = _run(registry, "regulator", "risk_measure", bogus_parameter=1)
    assert result.ok is False
    assert "invalid parameters" in (result.error or "")
    assert result.evidence is None


# --------------------------------------------------------------------------- #
# 通用：schema / 哈希稳定性 / 时点敏感性
# --------------------------------------------------------------------------- #
ALL_CALLS = [
    ("regulator", "risk_measure", {}),
    ("regulator", "systemic_risk", {}),
    ("investor", "capital_flow", {}),
    ("financing", "funding_cost", {}),
    ("regulator", "scenario", {}),
    ("investor", "forecast", {"horizon": 10}),
    ("regulator", "knowledge_search", {"query": "VaR CVaR 历史模拟", "top_k": 3}),
]


@pytest.mark.parametrize("role,tool_name,kwargs", ALL_CALLS, ids=[c[1] for c in ALL_CALLS])
def test_each_tool_returns_valid_result(registry: ToolRegistryImpl, role, tool_name, kwargs) -> None:
    result = _run(registry, role, tool_name, **kwargs)
    expected_kind = {
        "forecast": EvidenceKind.SIGNAL,
        "knowledge_search": EvidenceKind.KB,
    }.get(tool_name, EvidenceKind.TOOL)
    evidence = _assert_valid_tool_result(
        result,
        expected_kind=expected_kind,
        unit_required=tool_name != "knowledge_search",
    )
    assert evidence.tool is not None and evidence.tool.name == tool_name
    assert result.tool_name == tool_name
    assert result.version == "1.0.0"


@pytest.mark.parametrize("role,tool_name,kwargs", ALL_CALLS, ids=[c[1] for c in ALL_CALLS])
def test_hash_stability_and_as_of_sensitivity(registry: ToolRegistryImpl, role, tool_name, kwargs) -> None:
    first = _run(registry, role, tool_name, **kwargs)
    second = _run(registry, role, tool_name, **kwargs)
    assert first.ok and second.ok
    assert first.data == second.data
    assert first.evidence.evidence_id == second.evidence.evidence_id
    assert first.evidence.tool.inputs_hash == second.evidence.tool.inputs_hash
    assert first.evidence.hash == second.evidence.hash

    later = registry.run(role, tool_name, AS_OF + timedelta(days=1), **kwargs)
    assert later.ok
    assert later.evidence.tool.inputs_hash != first.evidence.tool.inputs_hash
    assert later.evidence.evidence_id != first.evidence.evidence_id


def test_inputs_hash_key_order_invariance() -> None:
    from cbr.tools import compute_inputs_hash

    first = compute_inputs_hash("risk_measure", "1.0.0", AS_OF, {"lookback": 252, "confidence": 0.95})
    second = compute_inputs_hash("risk_measure", "1.0.0", AS_OF, {"confidence": 0.95, "lookback": 252})
    assert first == second
    assert len(first) == 64


# --------------------------------------------------------------------------- #
# risk_measure：手算 VaR / CVaR / 最大回撤
# --------------------------------------------------------------------------- #
FIXED_RETURNS = [-0.10, -0.08, -0.06, -0.04, -0.02] + [0.0] * 14 + [0.01]


def _fixed_returns_provider() -> StubProvider:
    p = StubProvider()
    p.set_series("test.fixed_returns", FIXED_RETURNS)
    return p


def _risk_result(provider_obj: StubProvider, **kwargs) -> ToolResult:
    from cbr.tools import RiskMeasureTool

    tool = RiskMeasureTool(
        provider=provider_obj,
        version="1.0.0",
        defaults={
            "series_id": "test.fixed_returns",
            "values_are": "return",
            "lookback": 30,
            "min_observations": 20,
        },
    )
    return tool.run(AS_OF, **kwargs)


def test_risk_measure_historical_var_cvar_hand_calculation() -> None:
    result = _risk_result(_fixed_returns_provider())
    evidence = _assert_valid_tool_result(result)
    data = result.data
    assert evidence.kind == EvidenceKind.TOOL
    assert data["values_are"] == "return"
    assert data["observations"] == len(FIXED_RETURNS)
    # 手算：20 个收益，5% 分位线性插值 = -0.10 + 0.95*(0.02) = -0.081 → VaR = 0.081
    q = np.quantile(np.asarray(FIXED_RETURNS), 0.05, method="linear")
    assert q == pytest.approx(-0.081)
    assert data["var_hist"] == pytest.approx(0.081, abs=1e-9)
    # 尾部仅 -0.10 一个观测 → CVaR = 0.10
    assert data["cvar_hist"] == pytest.approx(0.10, abs=1e-9)
    expected_var, expected_cvar, _ = historical_tail(FIXED_RETURNS, 0.95, 1)
    assert data["var_hist"] == pytest.approx(expected_var, abs=1e-9)
    assert data["cvar_hist"] == pytest.approx(expected_cvar, abs=1e-9)
    assert data["cvar_hist"] >= data["var_hist"]


def test_risk_measure_parametric_var_cvar_formula() -> None:
    result = _risk_result(_fixed_returns_provider())
    data = result.data
    returns = np.asarray(FIXED_RETURNS, dtype=float)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    dist = statistics.NormalDist()
    z = dist.inv_cdf(0.05)
    expected_var = -(mu + sigma * z)
    expected_cvar = -mu + sigma * dist.pdf(z) / 0.05
    assert data["var_param"] == pytest.approx(expected_var, abs=1e-9)
    assert data["cvar_param"] == pytest.approx(expected_cvar, abs=1e-9)
    assert data["cvar_param"] >= data["var_param"]
    assert data["var_param"] == pytest.approx(parametric_tail(returns, 0.95, 1)[0], abs=1e-9)


def test_risk_measure_annualized_volatility_and_drawdown() -> None:
    result = _risk_result(_fixed_returns_provider())
    data = result.data
    returns = np.asarray(FIXED_RETURNS, dtype=float)
    expected_vol = float(np.std(returns, ddof=1) * math.sqrt(252))
    assert data["annualized_volatility"] == pytest.approx(expected_vol, abs=1e-9)
    assert data["max_drawdown"] == pytest.approx(max_drawdown(np.concatenate([[1.0], np.cumprod(1 + returns)])), abs=1e-9)
    # 压力分位应为负收益且 q01 < q05 < q10
    stress = data["stress_quantiles"]
    assert stress["q01"] <= stress["q05"] <= stress["q10"]
    assert stress["q05"] == pytest.approx(quantile(returns, 0.05), abs=1e-12)
    assert data["current_return_percentile"] is not None


def test_risk_measure_price_series_max_drawdown_hand_calculation() -> None:
    provider_obj = StubProvider()
    provider_obj.set_series("test.prices", [100.0, 120.0, 90.0, 110.0, 80.0, 100.0])
    from cbr.tools import RiskMeasureTool

    tool = RiskMeasureTool(
        provider=provider_obj,
        version="1.0.0",
        defaults={
            "series_id": "test.prices",
            "values_are": "price",
            "lookback": 30,
            "min_observations": 3,
        },
    )
    result = tool.run(AS_OF)
    _assert_valid_tool_result(result)
    # 峰值 120 → 谷底 80，最大回撤 = 40/120 = 1/3
    assert result.data["max_drawdown"] == pytest.approx(1.0 / 3.0, abs=1e-9)
    # 5 个收益：其中 120→90 与 110→80 的跌幅
    expected_returns = simple_returns([100.0, 120.0, 90.0, 110.0, 80.0, 100.0])
    assert result.data["observations"] == 5
    assert result.data["var_hist"] == pytest.approx(
        historical_tail(expected_returns, 0.95, 1)[0], abs=1e-9
    )


def test_risk_measure_insufficient_data_fails_explicitly() -> None:
    provider_obj = StubProvider()
    provider_obj.set_series("test.short", [1.0, 1.1, 1.2, 1.3, 1.4])
    from cbr.tools import RiskMeasureTool

    tool = RiskMeasureTool(provider=provider_obj, version="1.0.0")
    result = tool.run(AS_OF, series_id="test.short")
    assert result.ok is False
    assert result.evidence is None
    assert "insufficient" in (result.error or "")


def test_pit_violation_is_blocked_at_tool_layer() -> None:
    from cbr.tools import RiskMeasureTool

    tool = RiskMeasureTool(provider=FutureRowProvider(), version="1.0.0")
    result = tool.run(AS_OF, series_id="market.cn_equity.csi300")
    assert result.ok is False
    assert "point-in-time violation" in (result.error or "")


# --------------------------------------------------------------------------- #
# systemic_risk
# --------------------------------------------------------------------------- #
def test_systemic_risk_outputs(registry: ToolRegistryImpl) -> None:
    result = _run(registry, "regulator", "systemic_risk")
    evidence = _assert_valid_tool_result(result)
    data = result.data
    assert evidence.kind == EvidenceKind.TOOL
    assert data["dy_spillover_index"] == pytest.approx(data["dy_spillover_percent"] / 100.0, abs=1e-9)
    assert 0.0 <= data["dy_spillover_index"] <= 1.0
    assert data["delta_covar_abs"] >= 0.0
    assert data["mes_q"] >= 0.0
    assert data["market_var_loss_q"] > 0.0
    assert data["dy_fevd_matrix"] and len(data["dy_fevd_matrix"]) == len(data["dy_series_order"])
    # 溢出矩阵每行（份额）应接近 1
    for row in data["dy_fevd_matrix"]:
        assert sum(row) == pytest.approx(1.0, abs=1e-6)
    assert evidence.value == data["dy_spillover_index"]
    assert result.unit == "ratio"


# --------------------------------------------------------------------------- #
# capital_flow
# --------------------------------------------------------------------------- #
def test_capital_flow_zscore_matches_manual_calculation(registry: ToolRegistryImpl, provider) -> None:
    result = _run(registry, "investor", "capital_flow")
    _assert_valid_tool_result(result)
    data = result.data
    rows = provider.history("crossborder.flows.northbound_net", AS_OF, 60)
    values = np.asarray([row["value"] for row in rows], dtype=float)
    baseline = values[:-1]  # 不含当日
    expected_z = (values[-1] - baseline.mean()) / baseline.std(ddof=1)
    assert data["net_inflow_z"] == pytest.approx(expected_z, abs=1e-9)
    assert data["anomaly_direction"] in {"none", "inflow", "outflow"}
    assert 0.0 <= data["synchronized_outflow_share"] <= 1.0
    assert 0.0 < data["concentration_top_share"] <= 1.0
    assert data["flow_hhi"] > 0.0
    assert data["unit_map"]["net_inflow_z"] == "z"
    assert result.unit == "z"
    assert data["flow_unit"] == "亿元"


# --------------------------------------------------------------------------- #
# funding_cost：手算 bp 与再融资窗口
# --------------------------------------------------------------------------- #
def test_funding_cost_hand_calculation() -> None:
    provider_obj = StubProvider()
    # 240 期 1.00%（100bp），最后 20 期 1.10%（110bp）→ 20 期变化 = +10bp
    provider_obj.set_series("test.spread", [1.00] * 240 + [1.10] * 20)
    from cbr.tools import FundingCostTool

    tool = FundingCostTool(
        provider=provider_obj,
        version="1.0.0",
        defaults={
            "spread_series_id": "test.spread",
            "spread_unit": "pct",
            "lookback": 252,
            "momentum_window": 20,
        },
    )
    result = tool.run(AS_OF)
    _assert_valid_tool_result(result)
    data = result.data
    assert data["credit_spread_pct"] == pytest.approx(1.10)
    assert data["credit_spread_bp"] == pytest.approx(110.0)
    assert data["funding_cost_change_bp"] == pytest.approx(10.0)
    assert data["credit_spread_median_bp"] == pytest.approx(100.0)
    # 最新利差高于中位数 → 再融资窗口关闭，压力档位 low（10bp < 25bp）
    assert data["refinancing_window_status"] == "closed"
    assert data["refinancing_window_days"] == 0
    assert data["stress_level"] == "low"
    assert data["momentum_bp_per_day"] == pytest.approx(0.5)
    assert result.unit == "bp"


def test_funding_cost_bp_unit_input() -> None:
    provider_obj = StubProvider()
    provider_obj.set_series("test.spread_bp", [120.0] * 240 + [170.0] * 20)
    from cbr.tools import FundingCostTool

    tool = FundingCostTool(
        provider=provider_obj,
        version="1.0.0",
        defaults={
            "spread_series_id": "test.spread_bp",
            "spread_unit": "bp",
            "lookback": 252,
            "momentum_window": 20,
            "cost_jump_bp": 50.0,
        },
    )
    result = tool.run(AS_OF)
    _assert_valid_tool_result(result)
    assert result.data["credit_spread_bp"] == pytest.approx(170.0)
    assert result.data["funding_cost_change_bp"] == pytest.approx(50.0)
    assert result.data["stress_level"] == "high"


# --------------------------------------------------------------------------- #
# scenario：线性映射与历史类比
# --------------------------------------------------------------------------- #
def test_scenario_zero_shock_has_zero_expected_return(registry: ToolRegistryImpl) -> None:
    result = _run(
        registry,
        "regulator",
        "scenario",
        us_equity_drop_pct=0.0,
        fx_depreciation_pct=0.0,
        spread_widening_bp=0.0,
        method="linear",
    )
    _assert_valid_tool_result(result)
    assert result.data["linear"]["expected_target_return"] == pytest.approx(0.0, abs=1e-12)


def test_scenario_linear_monotonicity_and_contributions(registry: ToolRegistryImpl) -> None:
    base = _run(registry, "regulator", "scenario", method="linear", us_equity_drop_pct=10.0)
    severe = _run(registry, "regulator", "scenario", method="linear", us_equity_drop_pct=20.0)
    _assert_valid_tool_result(base)
    _assert_valid_tool_result(severe)
    expected_base = base.data["linear"]["expected_target_return"]
    expected_severe = severe.data["linear"]["expected_target_return"]
    assert expected_severe < expected_base
    contributions = base.data["linear"]["contributions"]
    assert sum(contributions.values()) == pytest.approx(expected_base, abs=1e-8)
    assert set(contributions) == {"us_equity_return", "fx_change", "spread_change_bp"}


def test_scenario_historical_analog_recomputable(registry: ToolRegistryImpl, provider) -> None:
    result = _run(registry, "regulator", "scenario", method="historical", analog_k=10)
    _assert_valid_tool_result(result)
    historical = result.data["historical"]
    assert historical["analog_count"] == 10
    assert len(historical["analog_dates"]) == 10
    # 用 provider 原始数据独立复算"历史近邻均值"（目标序列收益）
    rows = provider.history("market.cn_equity.csi300", AS_OF, 252)
    prices = [row["value"] for row in rows]
    returns = simple_returns(prices)
    return_map = {rows[i + 1]["date"]: float(returns[i]) for i in range(len(returns))}
    analog_returns = [return_map[date.fromisoformat(day)] for day in historical["analog_dates"]]
    assert historical["analog_mean_return"] == pytest.approx(float(np.mean(analog_returns)), abs=1e-9)
    assert historical["analog_worst_return"] == pytest.approx(float(np.min(analog_returns)), abs=1e-9)
    assert historical["analog_worst_return"] <= historical["analog_median_return"] <= historical["analog_best_return"]


# --------------------------------------------------------------------------- #
# forecast：共享信号 Evidence 复用
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("horizon,expected", [(5, 0.25), (10, 0.40), (20, 0.55)])
def test_forecast_reuses_shared_signal_evidence(registry: ToolRegistryImpl, provider, horizon, expected) -> None:
    result = _run(registry, "investor", "forecast", horizon=horizon)
    evidence = _assert_valid_tool_result(result, expected_kind=EvidenceKind.SIGNAL)
    signal = provider.risk_signal(AS_OF)
    assert evidence.evidence_id == signal.evidence_id  # 三 agent 共享同一风险锚
    assert evidence.value == pytest.approx(expected)
    assert result.unit == "probability"
    assert result.data["probability"] == pytest.approx(expected)
    assert result.data["signal_evidence_id"] == signal.evidence_id
    assert result.data["signal_as_of"] == AS_OF.isoformat()
    assert evidence.tool is not None and evidence.tool.name == "forecast"


def test_forecast_unknown_horizon_fails(registry: ToolRegistryImpl) -> None:
    result = _run(registry, "investor", "forecast", horizon=7)
    assert result.ok is False
    assert "horizon" in (result.error or "")


# --------------------------------------------------------------------------- #
# knowledge_search：KB 证据 + 时点
# --------------------------------------------------------------------------- #
def test_knowledge_search_returns_chunk_evidence(registry: ToolRegistryImpl) -> None:
    result = _run(registry, "regulator", "knowledge_search", query="VaR CVaR 历史模拟", top_k=3)
    evidence = _assert_valid_tool_result(
        result, expected_kind=EvidenceKind.KB, unit_required=False
    )
    assert evidence.value is None and evidence.unit is None
    data = result.data
    assert data["result_count"] >= 1
    assert data["dropped_future"] == 0
    for record in data["results"]:
        assert record["chunk_id"] and "#c" in record["chunk_id"]
        assert date.fromisoformat(record["publish_time"]) <= AS_OF
        assert record["title"] and record["source"]
        assert record["text"]
    cited = [ref.chunk_id for ref in result.citations]
    assert cited == [record["chunk_id"] for record in data["results"]]
    assert all(ref.release_time is not None for ref in result.citations)


def test_knowledge_search_respects_as_of(registry: ToolRegistryImpl) -> None:
    result = registry.run(
        "regulator", "knowledge_search", date(2020, 6, 30), query="北向资金 同步撤离", top_k=5
    )
    assert result.ok
    for record in result.data["results"]:
        assert date.fromisoformat(record["publish_time"]) <= date(2020, 6, 30)


def test_knowledge_search_without_kb_fails(provider: StubProvider) -> None:
    registry = build_tool_registry(load_settings(), provider, None)
    result = registry.run("regulator", "knowledge_search", AS_OF, query="VaR")
    assert result.ok is False
    assert "knowledge base is not configured" in (result.error or "")
