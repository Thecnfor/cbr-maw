"""CBR-MAW 实验运行器：P1 模态消融 / P2 工具与知识增强消融 / P3 三模式协同对照。

用法::

    .venv\\Scripts\\python.exe scripts\\run_experiment.py --kind p1
    .venv\\Scripts\\python.exe scripts\\run_experiment.py --kind p3 --p3-dates 8
    .venv\\Scripts\\python.exe scripts\\run_experiment.py --kind all

输出：artifacts/runs/<run_id>/{p1.json,p1.md,p3.json,p3.md,p2.json,p2.md,summary.md}
注意：默认样例数据为 SYNTHETIC 仿真数据，结果仅用于流程验证/系统演示，不代表真实市场结论。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from cbr.config import load_experiment_config, load_settings, resolve_path
from cbr.eval.backtest import compare_ablation, run_backtest
from cbr.eval.metrics import pr_auc
from cbr.schemas import (
    ChatRequest,
    DecisionCard,
    ExperimentMode,
    RiskLevel,
    ToolResult,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cbr.experiment")


def _data_label(provider: Any) -> tuple[bool, str]:
    """返回 (是否 synthetic, 展示用数据来源标签)。"""
    source = getattr(getattr(provider, "dataset", None), "source", "") or "unknown"
    synthetic = source == "synthetic-simulation"
    label = "SYNTHETIC 仿真数据（流程验证用途）" if synthetic else f"真实数据（source={source}）"
    return synthetic, label


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def trading_dates(provider, start: date, end: date, step: int = 1) -> list[date]:
    """从数据层交易日历取 [start, end] 的交易日（可等间隔抽样）。"""
    engine = provider._get_engine()  # noqa: SLF001 - 实验脚本需要访问信号引擎
    calendar = engine.calendar
    mask = (calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))
    dates = [ts.date() for ts in calendar[mask]]
    return dates[:: max(1, step)]


def _result_dir(run_id: str) -> Path:
    path = resolve_path(Path("artifacts") / "runs" / run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- #
# P1：多模态信息增益（数值 vs 数值+文本）
# --------------------------------------------------------------------------- #
def run_p1(provider, config, out: Path, max_days: int | None = None) -> dict[str, Any]:
    settings = provider.settings
    engine = provider._get_engine()  # noqa: SLF001
    start = pd.Timestamp((config.target or {}).get("eval_start", settings.data.sample_start)).date()
    end = pd.Timestamp(settings.data.sample_end).date()
    dates = trading_dates(provider, start, end)
    if max_days:
        dates = dates[-max_days:]

    def numeric_signal(d: date):
        return engine.predict(d, text_enabled=False)

    def fusion_signal(d: date):
        return engine.predict(d, text_enabled=True)

    horizons = tuple(int(h) for h in (config.target or {}).get("horizons", settings.data.horizons))
    n_boot = int((config.eval or {}).get("bootstrap", 200))
    label_fn = provider.label

    logger.warning("P1 回测：%d 个交易日 × %d 个期限（numeric vs fusion）", len(dates), len(horizons))
    result_numeric = run_backtest(
        "numeric_only", numeric_signal, label_fn, dates, horizons=horizons, n_boot=n_boot,
        warning_quantile=0.9,
        config={"eval_start": str(start), "eval_end": str(end), "text_enabled": False},
    )
    result_fusion = run_backtest(
        "fusion_text", fusion_signal, label_fn, dates, horizons=horizons, n_boot=n_boot,
        warning_quantile=0.9,
        config={"eval_start": str(start), "eval_end": str(end), "text_enabled": True},
    )
    comparisons = {}
    for horizon in horizons:
        comparisons[f"h{horizon}"] = compare_ablation(result_fusion, result_numeric, horizon, n_boot=n_boot)

    synthetic, data_label = _data_label(provider)
    payload = {
        "kind": "p1_modality",
        "synthetic": synthetic,
        "data_source": data_label,
        "n_dates": len(dates),
        "numeric": result_numeric.to_dict() | {"table": result_numeric.table_markdown()},
        "fusion": result_fusion.to_dict() | {"table": result_fusion.table_markdown()},
        "paired_bootstrap": comparisons,
    }
    _save_json(out / "p1.json", payload)

    lines = [
        "# P1 多模态信息增益（数值 vs 数值+文本）",
        "",
        f"- 评估区间：{start} ~ {end}，交易日 {len(dates)} 个",
        f"- 数据来源：{data_label}",
        "",
        "## 数值-only 基线",
        "",
        result_numeric.table_markdown(),
        "## 数值+文本融合",
        "",
        result_fusion.table_markdown(),
        "## 配对自助法检验（fusion - numeric, PR-AUC）",
        "",
        "| 期限 | n | PR-AUC(fusion) | PR-AUC(numeric) | Δ | 95%CI | p 值 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, comp in comparisons.items():
        lines.append(
            f"| {key} | {comp['n']} | {comp['pr_auc_a']:.4f} | {comp['pr_auc_b']:.4f} | "
            f"{comp['delta']:+.4f} | [{comp['ci_low']:+.4f}, {comp['ci_high']:+.4f}] | {comp['p_value']:.4f} |"
        )
    (out / "p1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# P2：工具与知识增强（full vs no-tools/no-kb）
# --------------------------------------------------------------------------- #
class _NoToolRegistry:
    """禁用全部工具的注册表包装（P2 消融用）。"""

    def __init__(self) -> None:
        self.tool_calls = 0

    def get(self, name: str):
        raise KeyError(name)

    def names(self) -> list[str]:
        return []

    def allow(self, role, tool_name: str) -> bool:  # noqa: ANN001, ARG002
        return False


class _EmptyKnowledgeBase:
    """空知识库（P2 消融用）。"""

    def search(self, query: str, as_of, top_k: int = 5):  # noqa: ANN001, ARG002
        return []

    def count(self) -> int:
        return 0


def _decision_metrics(decision: DecisionCard) -> dict[str, float]:
    """从决策卡提取 P2/P3 指标（含证据门槛版任务完成率）。"""
    v = decision.verification
    cards = decision.cards
    claims = [c for card in cards.values() for c in card.claims]
    claims_with_ev = [c for c in claims if c.evidence_ids]
    losses = []
    for card in cards.values():
        if card.decision_loss:
            losses.append(statistics.fmean(card.decision_loss.values()))
    task_completion = statistics.fmean(
        1.0 if (card.headline and card.recommendation and len(card.claims) >= 2) else 0.0
        for card in cards.values()
    ) if cards else 0.0
    # 证据门槛版：每张卡至少 1 条主张绑定证据（避免真实 LLM 下"全是无证据方向性判断也算完成"）
    def _has_evidence(card) -> bool:  # noqa: ANN001 - 局部辅助
        return any(claim.evidence_ids for claim in card.claims)

    evidence_kind = {item.evidence_id: item.kind.value for item in decision.evidence}

    def _has_tool_evidence(card) -> bool:  # noqa: ANN001 - 局部辅助
        """至少一条主张绑定工具/KB/政策证据（共享 signal 不算能力增强证据）。"""
        for claim in card.claims:
            for eid in claim.evidence_ids:
                if evidence_kind.get(eid, "signal") not in ("signal",):
                    return True
        return False

    task_completion_gated = statistics.fmean(
        1.0
        if (
            card.headline
            and card.recommendation
            and len(card.claims) >= 2
            and _has_evidence(card)
        )
        else 0.0
        for card in cards.values()
    ) if cards else 0.0
    task_completion_tool_gated = statistics.fmean(
        1.0
        if (
            card.headline
            and card.recommendation
            and len(card.claims) >= 2
            and _has_tool_evidence(card)
        )
        else 0.0
        for card in cards.values()
    ) if cards else 0.0
    numeric_claims = [c for c in claims if c.claim_type.value == "numeric"]
    return {
        "n_cards": float(len(cards)),
        "n_claims": float(len(claims)),
        "n_numeric_claims": float(len(numeric_claims)),
        "claims_with_evidence_ratio": (len(claims_with_ev) / len(claims)) if claims else 0.0,
        "task_completion": task_completion,
        "task_completion_evidence_gated": task_completion_gated,
        "task_completion_tool_evidence_gated": task_completion_tool_gated,
        "decision_loss_mean": statistics.fmean(losses) if losses else 0.0,
        "numeric_error_rate": v.numeric_error_rate,
        "evidence_accuracy": v.evidence_accuracy,
        "unsupported_claim_rate": v.unsupported_claim_rate,
        "permission_violations": float(v.permission_violations),
        "leakage_events": float(v.leakage_events),
        "schema_errors": float(v.schema_errors),
        "verification_passed": 1.0 if v.passed else 0.0,
        "tool_calls": float(decision.coordination.tool_calls),
        "tokens": float(decision.coordination.tokens),
        "latency_ms": float(decision.coordination.latency_ms),
        "cost_units": float(decision.coordination.cost_usd),
        "conflicts_total": float(decision.coordination.conflicts_total),
        "conflicts_resolved": float(decision.coordination.conflicts_resolved),
        "conflicts_escalated": float(decision.coordination.conflicts_escalated),
    }


def _llm_usage_snapshot(llm: Any) -> dict[str, float]:
    """读取 LLM 客户端累计用量（真实 API 的 prompt/completion token 与调用次数）。"""
    try:
        usage = llm.usage or {}
    except Exception:  # noqa: BLE001 - mock/自定义客户端可能无 usage
        return {"total_tokens": 0.0, "calls": 0.0}
    return {
        "total_tokens": float(usage.get("total_tokens", 0) or 0),
        "calls": float(usage.get("calls", 0) or 0),
    }


def _trace_metrics(orchestrator: Any, run_id: str) -> dict[str, float]:
    """从审计 trace 统计草稿级指标（被拒主张/越权工具/预算截断等）。"""
    try:
        events = orchestrator.get_trace(run_id) or []
    except Exception:  # noqa: BLE001 - trace 读取失败不影响主结果
        events = []
    counts: dict[str, float] = {"trace_events": float(len(events))}
    for event in events:
        action = getattr(event, "action", None)
        if action is None and isinstance(event, dict):
            action = event.get("action")
        if not action:
            continue
        key = f"trace_{action}"
        counts[key] = counts.get(key, 0.0) + 1.0
    return counts


def _aggregate(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = sorted({key for row in rows for key in row})
    return {
        key: {
            "mean": statistics.fmean(row[key] for row in rows if key in row),
            "std": statistics.pstdev([row[key] for row in rows if key in row]) if len(rows) > 1 else 0.0,
            "n": float(sum(1 for row in rows if key in row)),
        }
        for key in keys
    }


# 表格中展示的 trace 指标白名单（JSON 中保留全部 trace_* 明细）
TRACE_DISPLAY_KEYS = {
    "trace_events",
    "trace_llm_call",
    "trace_tool_call",
    "trace_tool_denied",
    "trace_claim_rejected",
    "trace_budget_exceeded",
    "trace_kb_search",
    "trace_cross_check",
}


def _display_keys(results: dict[str, list[dict[str, float]]]) -> list[str]:
    keys = {k for rows in results.values() for row in rows for k in row}
    return sorted(k for k in keys if not k.startswith("trace_") or k in TRACE_DISPLAY_KEYS)


def _fmt_cell(value: float | None) -> str:
    if value is None or not isinstance(value, (int, float)) or value != value:  # NaN check
        return "—"
    return f"{value:.4f}"


def _build_ablation_orchestrator(service, no_tools: bool, no_kb: bool):
    """构造增强消融配置：no_tools=角色工具权限清空（不产生越权尝试）；no_kb=空知识库。"""
    from cbr.config import load_role_specs
    from cbr.orchestration import build_orchestrator

    registry = service.registry
    kb = _EmptyKnowledgeBase() if no_kb else service.kb
    role_specs = load_role_specs()
    if no_tools:
        role_specs = {
            role: spec.model_copy(update={"tool_permissions": []}) for role, spec in role_specs.items()
        }
    return build_orchestrator(
        service.settings, service.provider, registry, kb, service.llm, role_specs=role_specs
    )


def _run_one(orchestrator: Any, service: Any, d: date, mode: str) -> dict[str, float]:
    """执行一次决策并附带 trace / 真实 API 用量指标。"""
    usage_before = _llm_usage_snapshot(service.llm)
    decision = orchestrator.run(as_of=d, mode=mode)
    usage_after = _llm_usage_snapshot(service.llm)
    row = _decision_metrics(decision)
    row["llm_tokens_actual"] = usage_after["total_tokens"] - usage_before["total_tokens"]
    row["llm_calls_actual"] = usage_after["calls"] - usage_before["calls"]
    row.update(_trace_metrics(orchestrator, decision.run_id))
    return row


def run_p2(service, config, out: Path, n_dates: int = 4, llm_label: str = "unknown") -> dict[str, Any]:
    settings = service.settings
    start = pd.Timestamp((config.target or {}).get("eval_start", settings.data.sample_start)).date()
    end = pd.Timestamp(settings.data.sample_end).date()
    dates = trading_dates(service.provider, start, end, step=max(1, len(trading_dates(service.provider, start, end)) // max(1, n_dates)))[:n_dates]
    if not dates:
        raise RuntimeError("P2 无法选取评估日")

    variants: dict[str, Any] = {"full": service.orchestrator}
    variants["no_tools_no_kb"] = _build_ablation_orchestrator(service, no_tools=True, no_kb=True)

    results: dict[str, list[dict[str, float]]] = {}
    for name, orchestrator in variants.items():
        logger.warning("P2 %s：%d 个评估日", name, len(dates))
        rows = [_run_one(orchestrator, service, d, "collaborative") for d in dates]
        results[name] = rows

    synthetic, data_label = _data_label(service.provider)
    payload = {
        "kind": "p2_augment",
        "synthetic": synthetic,
        "data_source": data_label,
        "llm": llm_label,
        "dates": [str(d) for d in dates],
        "variants": {name: {"rows": rows, "aggregate": _aggregate(rows)} for name, rows in results.items()},
    }
    _save_json(out / "p2.json", payload)

    lines = [
        "# P2 金融知识与专业工具增强消融",
        "",
        f"- 评估日（{len(dates)} 个）：{', '.join(str(d) for d in dates)}",
        "- 对照：full（7 工具 + 29 篇知识库） vs no_tools_no_kb（禁用工具与知识库）",
        f"- 数据来源：{data_label}",
        f"- LLM：{llm_label}",
        "",
        "| 指标 | full | no_tools_no_kb |",
        "|---|---|---|",
    ]
    for key in _display_keys(results):
        f = _aggregate(results["full"]).get(key, {}).get("mean", float("nan"))
        n = _aggregate(results["no_tools_no_kb"]).get(key, {}).get("mean", float("nan"))
        lines.append(f"| {key} | {_fmt_cell(f)} | {_fmt_cell(n)} |")
    (out / "p2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# P3：单智能体 / 独立三智能体 / 完整协同
# --------------------------------------------------------------------------- #
def run_p3(service, config, out: Path, n_dates: int = 8, llm_label: str = "unknown") -> dict[str, Any]:
    settings = service.settings
    start = pd.Timestamp((config.target or {}).get("eval_start", settings.data.sample_start)).date()
    end = pd.Timestamp(settings.data.sample_end).date()
    all_dates = trading_dates(service.provider, start, end)
    if not all_dates:
        raise RuntimeError("P3 无法选取评估日")
    step = max(1, len(all_dates) // max(1, n_dates))
    dates = all_dates[::step][:n_dates]

    modes = [ExperimentMode.SINGLE.value, ExperimentMode.INDEPENDENT.value, ExperimentMode.COLLABORATIVE.value]
    results: dict[str, list[dict[str, float]]] = {}
    for mode in modes:
        logger.warning("P3 %s：%d 个评估日", mode, len(dates))
        rows = [_run_one(service.orchestrator, service, d, mode) for d in dates]
        results[mode] = rows

    synthetic, data_label = _data_label(service.provider)
    payload = {
        "kind": "p3_collaboration",
        "synthetic": synthetic,
        "data_source": data_label,
        "llm": llm_label,
        "dates": [str(d) for d in dates],
        "variants": {mode: {"rows": rows, "aggregate": _aggregate(rows)} for mode, rows in results.items()},
    }
    _save_json(out / "p3.json", payload)

    lines = [
        "# P3 多智能体协同对照（单智能体 / 三独立智能体 / 完整协同）",
        "",
        f"- 评估日（{len(dates)} 个）：{', '.join(str(d) for d in dates)}",
        f"- 数据来源：{data_label}",
        f"- LLM：{llm_label}",
        "",
        "| 指标 | single | independent | collaborative |",
        "|---|---|---|---|",
    ]
    for key in _display_keys(results):
        vals = []
        for mode in modes:
            agg = _aggregate(results[mode]).get(key)
            vals.append(agg["mean"] if agg else float("nan"))
        lines.append(f"| {key} | " + " | ".join(_fmt_cell(v) for v in vals) + " |")
    (out / "p3.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 实验运行器（P1/P2/P3）")
    parser.add_argument("--config", default="configs/experiments/p1_modality.yaml")
    parser.add_argument("--kind", choices=["p1", "p2", "p3", "all"], default="all")
    parser.add_argument("--p1-max-days", type=int, default=None, help="P1 只回测最近 N 个交易日")
    parser.add_argument("--p2-dates", type=int, default=4)
    parser.add_argument("--p3-dates", type=int, default=8)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    config = load_experiment_config(args.config)
    run_id = args.run_id or f"{config.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out = _result_dir(run_id)
    data_label = "未知数据源"
    summary: dict[str, Any] = {"run_id": run_id, "config": args.config, "synthetic": True, "kinds": {}}

    if args.kind in ("p1", "all"):
        from cbr.data import build_data_provider

        provider = build_data_provider(load_settings())
        synthetic, data_label = _data_label(provider)
        summary["synthetic"] = synthetic
        summary["data_source"] = data_label
        summary["kinds"]["p1"] = run_p1(provider, config, out, args.p1_max_days)

    if args.kind in ("p2", "p3", "all"):
        from cbr.service import build_service

        service = build_service()
        synthetic, data_label = _data_label(service.provider)
        summary["synthetic"] = synthetic
        summary["data_source"] = data_label
        llm = getattr(service, "llm", None)
        llm_label = type(llm).__name__ if llm is not None else "unknown"
        if llm is not None:
            if getattr(llm, "is_mock", False):
                llm_label += "（确定性 mock）"
            else:
                provider = getattr(llm, "provider", None)
                model = getattr(llm, "model", None)
                if provider:
                    llm_label = f"{provider}:{model}" if model else str(provider)
        summary["llm"] = llm_label
        if args.kind in ("p2", "all"):
            summary["kinds"]["p2"] = run_p2(service, config, out, args.p2_dates, llm_label)
        if args.kind in ("p3", "all"):
            summary["kinds"]["p3"] = run_p3(service, config, out, args.p3_dates, llm_label)

    _save_json(out / "summary.json", summary)
    (out / "SUMMARY.md").write_text(
        "# CBR-MAW 实验运行摘要\n\n"
        f"- run_id: `{run_id}`\n"
        f"- 配置: `{args.config}`\n"
        f"- 类别: {', '.join(summary['kinds'])}\n"
        f"- 数据: {data_label}\n"
        f"- 产物目录: `{out}`\n",
        encoding="utf-8",
    )
    print(f"[OK] 实验完成：{out}")
    for kind in summary["kinds"]:
        print(f"  - {kind}: {out / (kind + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
