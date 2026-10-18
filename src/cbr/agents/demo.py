"""三角色智能体 Mock 模式演示：输出三张 RiskCard JSON。

用法::

    # 默认：按 configs/app.yaml 自动选择模式（无 key → MockLLM，有 key → DeepSeek）
    $env:PYTHONPATH='src'; .venv\\Scripts\\python.exe -m cbr.agents.demo

    # 强制 Mock 模式并输出到指定目录
    .venv\\Scripts\\python.exe -m cbr.agents.demo --mock --out artifacts/demo

    # 强制真实 DeepSeek（需要 DEEPSEEK_API_KEY 或 secrets/deepseek.key）
    .venv\\Scripts\\python.exe -m cbr.agents.demo --real

演示数据：优先使用 data/tools/knowledge 模块的真实实现（若已就绪），
不可用时回退到内置的**合成样例**（明确标注 synthetic），保证 demo 可离线运行。
真实模型与 Mock 模式走完全相同的智能体流程，输出字段结构一致。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..config import ROOT, load_role_specs, load_settings
from ..llm import build_llm_client
from ..schemas import (
    AgentContext,
    DataCard,
    Evidence,
    EvidenceKind,
    MarketSnapshot,
    RiskDriver,
    RiskLevel,
    RiskSignal,
    Role,
    SourceRef,
    ToolRef,
    ToolResult,
)
from .role_agent import ROLE_HORIZONS, build_role_agents

DEMO_AS_OF = date(2024, 8, 5)
DEFAULT_OUT_DIR = ROOT / "artifacts" / "demo"

logger = logging.getLogger("cbr.agents.demo")


# --------------------------------------------------------------------------- #
# 内置合成样例（真实数据/工具/知识库模块未就绪时的回退）
# --------------------------------------------------------------------------- #
class _DemoTool:
    """演示用确定性工具：返回固定但合理的合成 Evidence。"""

    version = "demo-1.0.0"

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    def run(self, as_of: date, **kwargs: Any) -> ToolResult:  # noqa: ARG002 - 演示工具忽略参数
        key, value, unit = _DEMO_TOOL_VALUES[self.name]
        evidence = Evidence(
            evidence_id=f"ev_tool_{self.name}_{as_of.strftime('%Y%m%d')}_demo",
            kind=EvidenceKind.TOOL,
            as_of=as_of,
            title=f"{self.name}: {key}",
            summary=f"演示用合成工具输出（{self.description}）",
            payload={"primary_metric": key, "value": value, "note": "synthetic-demo"},
            unit=unit,
            value=value,
            source=SourceRef(name=f"tool:{self.name}"),
            tool=ToolRef(name=self.name, version=self.version),
            produced_by="demo_tool",
            hash=None,
        )
        return ToolResult(
            tool_name=self.name,
            version=self.version,
            as_of=as_of,
            ok=True,
            data={"primary_metric": key, "value": value, "unit": unit},
            unit=unit,
            evidence=evidence,
        )


_DEMO_TOOL_VALUES: dict[str, tuple[str, float, str]] = {
    "risk_measure": ("var_hist", 0.031, "ratio"),
    "systemic_risk": ("dy_spillover", 0.63, "ratio"),
    "capital_flow": ("northbound_outflow_z", 1.42, "z"),
    "funding_cost": ("funding_cost_change_bp", 62.0, "bp"),
    "scenario": ("scenario_loss", 0.087, "ratio"),
    "forecast": ("prob_high_stress", 0.48, "probability"),
}

_DEMO_TOOL_DESCRIPTIONS: dict[str, str] = {
    "risk_measure": "波动率 / VaR / CVaR / 回撤",
    "systemic_risk": "ΔCoVaR / MES / DY 溢出指数",
    "capital_flow": "跨境资金异常 z / 同步撤离",
    "funding_cost": "融资成本变化 / 信用利差 / 再融资窗口",
    "scenario": "汇率与美股冲击情景映射",
    "forecast": "读取共享融合预测器",
}


class _DemoRegistry:
    """演示用工具注册表：权限矩阵放行 RoleSpec 中出现的工具。"""

    def __init__(self) -> None:
        self._tools = {
            name: _DemoTool(name, _DEMO_TOOL_DESCRIPTIONS.get(name, ""))
            for name in _DEMO_TOOL_VALUES
        }

    def get(self, name: str):  # noqa: ANN201 - 与 ToolRegistry 协议一致
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def allow(self, role: Role, tool_name: str) -> bool:  # noqa: ARG002 - 演示放行，真实权限由 RoleSpec 校验
        return tool_name in self._tools or tool_name == "knowledge_search"


class _DemoKB:
    """演示用知识库：返回带 chunk_id / 发布时点的合成 KB 证据。"""

    _TOPICS: dict[str, tuple[str, str]] = {
        "regulator": (
            "跨境资本流动宏观审慎管理要点",
            "监管应关注跨境资金大进大出与跨市场同步下跌的外溢风险，必要时采用宏观审慎工具。",
        ),
        "investor": (
            "组合尾部风险与相关性上升的应对",
            "压力时期跨市场相关性上升会放大组合尾部损失，应通过风险预算与对冲管理回撤。",
        ),
        "financing": (
            "融资成本传导与再融资窗口管理",
            "市场压力上升会通过信用利差与流动性溢价推高融资成本，应提前锁定成本并保留缓冲。",
        ),
    }

    def __init__(self) -> None:
        self._counter = 0

    def search(self, query: str, as_of: date, top_k: int = 5) -> list[Evidence]:  # noqa: ARG002
        self._counter += 1
        topics = list(self._TOPICS.values())
        items: list[Evidence] = []
        for index, (title, summary) in enumerate(topics[: max(1, min(top_k, len(topics)))]):
            chunk_id = f"kb-demo-{index + 1:03d}"
            items.append(
                Evidence(
                    evidence_id=f"ev_kb_{chunk_id}",
                    kind=EvidenceKind.KB,
                    as_of=date(2024, 6, 28),
                    title=title,
                    summary=summary,
                    payload={"chunk_id": chunk_id, "query": query[:80]},
                    source=SourceRef(
                        name="demo_knowledge_base",
                        doc_id=f"doc-demo-{index + 1:03d}",
                        chunk_id=chunk_id,
                        release_time=datetime(2024, 6, 28, 9, 0, tzinfo=timezone.utc),
                    ),
                    produced_by="demo_knowledge_base",
                )
            )
        return items

    def count(self) -> int:
        return len(self._TOPICS)


class _DemoProvider:
    """演示用 DataProvider（合成数据，仅用于离线演示）。"""

    def risk_signal(self, as_of: date) -> RiskSignal:
        return RiskSignal(
            as_of=as_of,
            model_version="demo-fusion-v1",
            horizons={5: 0.32, 10: 0.48, 20: 0.57},
            percentile=0.86,
            level=RiskLevel.HIGH,
            drivers=[
                RiskDriver(
                    factor="northbound_outflow_z",
                    contribution=0.31,
                    direction="up",
                    description="北向资金异常流出",
                ),
                RiskDriver(
                    factor="global_volatility",
                    contribution=0.22,
                    direction="up",
                    description="全球波动率抬升",
                ),
                RiskDriver(
                    factor="credit_spread_widening",
                    contribution=0.15,
                    direction="up",
                    description="信用利差走阔",
                ),
            ],
            modality_contrib={"numeric": 0.72, "text": 0.28},
            label_version="stress_pca_q90",
            evidence_id=f"ev_sig_{as_of.strftime('%Y%m%d')}_demo-fusion-v1",
        )

    def market_snapshot(self, as_of: date) -> MarketSnapshot:
        return MarketSnapshot(
            as_of=as_of,
            series={
                "market.cn_equity.csi300": 0.012,
                "market.cn_bond.cgb_10y": -0.004,
                "market.fx.usdcny": 0.007,
                "market.global.vix": 0.21,
                "crossborder.flows.northbound_net": -82.4,
            },
            missing=[],
            data_cards=[
                DataCard(
                    series_id="market.cn_equity.csi300",
                    name="沪深300（合成）",
                    source="synthetic-demo",
                    frequency="daily",
                    coverage_start=date(2018, 1, 1),
                    coverage_end=as_of,
                    pit_grade="approximate",
                    unit="pct",
                    notes="演示用合成数据，不代表真实市场",
                )
            ],
        )

    def history(self, series_id: str, as_of: date, lookback: int = 120) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def label(self, as_of: date, horizon: int) -> int | None:  # noqa: ARG002
        return None

    def data_cards(self) -> list[DataCard]:
        return []


def _demo_components() -> tuple[Any, Any, Any, str]:
    return _DemoProvider(), _DemoKB(), _DemoRegistry(), "内置合成样例（synthetic）"


def _real_components(settings: Any) -> tuple[Any, Any, Any, str]:
    """尽量装配 data/tools/knowledge 真实模块，逐项回退到演示样例。

    逐项回退的好处：即使 data 模块尚未就绪，仍可使用 tools-knowledge 的真实
    确定性工具与知识库演示（它们只需要一个满足 DataProvider 契约的数据源）。
    """

    components: list[str] = []

    provider: Any = None
    try:
        from ..data import build_data_provider  # type: ignore

        provider = build_data_provider(settings)
        provider.risk_signal(DEMO_AS_OF)  # 冒烟
        components.append("data 真实模块")
    except Exception as exc:  # noqa: BLE001 - 逐项回退
        logger.warning("真实 data 模块不可用，回退 SyntheticProvider：%s", exc)
        from ..tools.demo_provider import SyntheticProvider  # 延迟导入避免硬依赖

        provider = SyntheticProvider()
        components.append("SyntheticProvider（合成数据）")

    kb: Any = None
    try:
        from ..knowledge import build_knowledge_base  # type: ignore

        kb = build_knowledge_base(settings)
        components.append("knowledge 真实模块")
    except Exception as exc:  # noqa: BLE001
        logger.warning("真实 knowledge 模块不可用，回退内置知识库样例：%s", exc)
        kb = _DemoKB()
        components.append("内置知识库样例")

    registry: Any = None
    try:
        from ..tools import build_tool_registry  # type: ignore

        registry = build_tool_registry(settings, provider, kb)
        components.append("tools 真实模块")
    except Exception as exc:  # noqa: BLE001
        logger.warning("真实 tools 模块不可用，回退内置工具样例：%s", exc)
        registry = _DemoRegistry()
        components.append("内置工具样例")

    return provider, kb, registry, "、".join(components)


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #
def run_demo(
    *,
    as_of: date = DEMO_AS_OF,
    prefer_real: bool = True,
    force_mock: bool = False,
    force_real: bool = False,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """运行三角色分析并写出示例文件，返回可 JSON 序列化的结果 dict。"""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    llm = build_llm_client(settings, force_mock=force_mock, force_real=force_real)

    provider, kb, registry, components = (
        _real_components(settings) if prefer_real else _demo_components()
    )
    role_specs = load_role_specs()
    agents = build_role_agents(
        registry=registry,
        provider=provider,
        kb=kb,
        llm=llm,
        settings=settings,
        role_specs=role_specs,
    )

    signal = provider.risk_signal(as_of)
    snapshot = provider.market_snapshot(as_of)
    context = AgentContext(
        as_of=as_of,
        mode="collaborative",  # type: ignore[arg-type]
        signal=signal,
        snapshot=snapshot,
        round=0,
        budget={"run_id": f"demo_{'mock' if getattr(llm, 'is_mock', False) else 'real'}_{as_of:%Y%m%d}"},
        task="演示：评估当前跨境金融压力，从监管/投资/融资三主体视角给出风险等级与建议。",
    )

    cards: dict[str, Any] = {}
    evidence_total = 0
    tool_calls = 0
    tokens = 0
    for role, agent in agents.items():
        output = agent.analyze(context)
        cards[role.value] = output.card.model_dump(mode="json")
        evidence_total += len(output.evidence)
        tool_calls += output.tool_calls
        tokens += output.tokens

    result: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "llm_mode": getattr(llm, "mode", "unknown"),
        "llm_is_mock": bool(getattr(llm, "is_mock", False)),
        "components": components,
        "roles": {role.value: ROLE_HORIZONS[role] for role in agents},
        "cards": cards,
        "usage": {
            "tool_calls": tool_calls,
            "tokens": tokens,
            "evidence_published": evidence_total,
            "llm_usage": llm.usage,
        },
    }

    target_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = "mock" if result["llm_is_mock"] else "real"
    combined_path = target_dir / f"{suffix}_role_cards.json"
    combined_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for role_key, card in cards.items():
        (target_dir / f"{suffix}_{role_key}_card.json").write_text(
            json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    result["output_files"] = {
        "combined": str(combined_path),
        **{
            role_key: str(target_dir / f"{suffix}_{role_key}_card.json")
            for role_key in cards
        },
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 三角色智能体演示（Mock/真实 LLM）")
    parser.add_argument("--as-of", default=DEMO_AS_OF.isoformat(), help="分析时点 YYYY-MM-DD")
    parser.add_argument("--mock", action="store_true", help="强制 MockLLM（离线确定性）")
    parser.add_argument("--real", action="store_true", help="强制真实 DeepSeek（需 API key）")
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT_DIR), help="示例文件输出目录（默认 artifacts/demo）"
    )
    parser.add_argument(
        "--synthetic-only", action="store_true", help="只使用内置合成样例，不装配真实数据/工具模块"
    )
    args = parser.parse_args(argv)
    if args.mock and args.real:
        parser.error("--mock 与 --real 不能同时使用")

    result = run_demo(
        as_of=date.fromisoformat(args.as_of),
        prefer_real=not args.synthetic_only,
        force_mock=args.mock,
        force_real=args.real,
        out_dir=Path(args.out),
    )

    print(f"[CBR-MAW demo] as_of={result['as_of']} llm={result['llm_mode']} "
          f"components={result['components']}")
    for role_key, card in result["cards"].items():
        print(f"\n===== RiskCard: {role_key} =====")
        print(json.dumps(card, ensure_ascii=False, indent=2))
    print("\n[CBR-MAW demo] 示例文件：")
    for label, path in result["output_files"].items():
        print(f"  - {label}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
