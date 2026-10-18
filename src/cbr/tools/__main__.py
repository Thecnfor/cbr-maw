"""工具层演示 CLI：用确定性合成数据调用每类工具并打印 ToolResult/Evidence JSON。

用法（项目根目录）::

    $env:PYTHONPATH="src"; .venv\\Scripts\\python.exe -m cbr.tools --as-of 2024-08-05

说明：真实系统由 service.py 注入 data-model 的 DataProvider 与真实知识库；
本 CLI 仅用于验收/演示"每个工具都返回合法 ToolResult + Evidence"。
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from ..config import load_settings
from ..knowledge import build_knowledge_base
from . import build_tool_registry
from .demo_provider import SyntheticProvider

DEMO_CALLS: list[tuple[str, str, dict]] = [
    ("regulator", "risk_measure", {}),
    ("regulator", "systemic_risk", {}),
    ("regulator", "capital_flow", {}),
    ("financing", "funding_cost", {}),
    ("regulator", "scenario", {"us_equity_drop_pct": 12.0, "fx_depreciation_pct": 6.0}),
    ("investor", "forecast", {"horizon": 10}),
    ("regulator", "knowledge_search", {"query": "VaR CVaR 历史模拟 尾部分位", "top_k": 3}),
]


def _evidence_summary(result) -> dict:
    evidence = result.evidence
    return {
        "ok": result.ok,
        "tool_name": result.tool_name,
        "version": result.version,
        "as_of": result.as_of.isoformat(),
        "unit": result.unit,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
        "evidence": (
            {
                "evidence_id": evidence.evidence_id,
                "kind": evidence.kind.value,
                "title": evidence.title,
                "value": evidence.value,
                "unit": evidence.unit,
                "tool": evidence.tool.model_dump(mode="json") if evidence.tool else None,
                "hash": evidence.hash,
                "payload_keys": sorted(evidence.payload),
                "summary": evidence.summary,
            }
            if evidence is not None
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 确定性工具层演示")
    parser.add_argument("--as-of", default="2024-08-05", help="时点（ISO 日期）")
    parser.add_argument(
        "--full",
        action="store_true",
        help="打印完整 ToolResult（含 evidence.payload），否则只打印证据摘要",
    )
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of)
    settings = load_settings()
    provider = SyntheticProvider()

    try:
        kb = build_knowledge_base(settings)
        kb_note = f"知识库 {kb.n_docs()} 篇 / {kb.count()} 块"
    except (FileNotFoundError, ValueError) as exc:  # 语料缺失时 demo 仍可运行
        kb = None
        kb_note = f"知识库不可用：{exc}"

    registry = build_tool_registry(settings, provider, kb)
    print(
        json.dumps(
            {
                "registry": registry.names(),
                "roles": registry.permissions_table(),
                "knowledge": kb_note,
                "as_of": as_of.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("=" * 80)

    for role, tool_name, kwargs in DEMO_CALLS:
        result = registry.run(role, tool_name, as_of, **kwargs)
        payload = (
            result.model_dump(mode="json")
            if args.full
            else _evidence_summary(result)
        )
        print(f"[{role}] {tool_name} kwargs={json.dumps(kwargs, ensure_ascii=False)}")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        print("-" * 80)

    # 权限矩阵演示：融资主体无权调用系统性风险工具 → 返回 disallowed + 审计事件
    denied = registry.run("financing", "systemic_risk", as_of)
    print("[financing] systemic_risk（应被权限矩阵阻断）")
    print(json.dumps(denied.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print("audit_events:", json.dumps(
        [event.model_dump(mode="json") for event in registry.audit_events],
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
