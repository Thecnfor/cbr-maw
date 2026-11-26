#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用旧版 Python 生成黄金向量（contracts/golden-vectors/hash_vectors.json）。

用法：
    CBR_LEGACY_SRC=/path/to/commorcial/src \
      python3 packages/contracts_dart/tool/generate_golden_vectors.py

旧版源码位置默认为 `/mnt/shared/recently/commorcial/src`（只读语义参考）。
本脚本**直接 import** 旧版 `cbr.tools.base` 的 canonical_json / compute_inputs_hash /
sha256_text / to_native，因此向量与旧版实现逐字节一致（不重写口径）。

若旧版环境不可用，可用 `CBR_LEGACY_SRC` 指向任一包含 `cbr/tools/base.py` 的副本。
"""
import json
import os
import sys
from datetime import date

LEGACY_SRC = os.environ.get("CBR_LEGACY_SRC", "/mnt/shared/recently/commorcial/src")
sys.path.insert(0, LEGACY_SRC)

try:
    from cbr.tools.base import canonical_json, compute_inputs_hash, sha256_text, to_native
except ImportError as exc:  # noqa: BLE001
    print("无法导入旧版 cbr.tools.base：%s" % exc)
    print("请设置 CBR_LEGACY_SRC 指向旧版 src 目录。")
    raise SystemExit(2) from exc

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(REPO, "contracts/golden-vectors/hash_vectors.json")

CASES = [
    {
        "name": "flat-int-params",
        "note": "基线：纯整数参数（工具默认 lookback/annualization）",
        "tool": "risk_measure",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"lookback": 252, "annualization": 252, "horizon_days": 1},
        "payload": {"value": 0.0231, "unit": "loss_ratio", "as_of": "2026-06-30"},
    },
    {
        "name": "float-small-0.1",
        "note": "浮点边界：0.1（须输出 0.1，不得 0.10000000000000001）",
        "tool": "risk_measure",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"confidence": 0.1, "ratio": 0.1},
        "payload": {"value": 0.1, "unit": "loss_ratio"},
    },
    {
        "name": "float-large-1e16",
        "note": "浮点边界：1e16 → Python 字面量 1e+16",
        "tool": "risk_measure",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"big": 1e16, "threshold": 1e16},
        "payload": {"value": 1e16},
    },
    {
        "name": "float-tiny-1e-05",
        "note": "浮点边界：1e-05 → Python 字面量 1e-05",
        "tool": "funding_cost",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"cost_jump_bp": 1e-05, "cost_medium_bp": 1e-05},
        "payload": {"value": 1e-05, "unit": "bp"},
    },
    {
        "name": "float-negative-zero",
        "note": "浮点边界：-0.0 → Python 字面量 -0.0（不得折叠为 0.0）",
        "tool": "scenario",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"us_equity_drop_pct": -0.0, "fx_depreciation_pct": -0.0},
        "payload": {"value": -0.0},
    },
    {
        "name": "float-nan-inf-to-null",
        "note": "浮点边界：NaN / Inf 经 to_native 归一为 null（缺失 ≠ 零值）",
        "tool": "capital_flow",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")},
        "payload": {"value": float("nan"), "missing": True},
    },
    {
        "name": "chinese-strings",
        "note": "中文字符串：ensure_ascii=False，逐字节保持 UTF-8",
        "tool": "knowledge_search",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"query": "跨境资金异常流动与同步撤离", "tags": ["监管", "外溢"]},
        "payload": {"summary": "跨境资金异常流动的监管口径", "unit": "亿元"},
    },
    {
        "name": "empty-collections",
        "note": "空列表与空字典",
        "tool": "forecast",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"series_ids": [], "dims": {}},
        "payload": {"drivers": [], "dims": {}},
    },
    {
        "name": "nested-dict",
        "note": "嵌套字典：键排序按字典序，深度不限",
        "tool": "signal.compute",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {
            "dims": {
                "equity": {"weight": 0.2, "value": 0.35},
                "fx": {"value": 0.21, "weight": 0.15},
            },
            "missing_dims": ["credit"],
        },
        "payload": {"dims": {"equity": {"value": 0.35}}, "limitations": []},
    },
    {
        "name": "mixed-scalars",
        "note": "混合标量：bool / null / int / float 同层",
        "tool": "kb.search",
        "version": "1.0.0",
        "as_of": date(2026, 6, 30),
        "params": {"top_k": 5, "include": True, "score": 8.42, "note": None},
        "payload": {"score": 8.42, "published_at": None, "ok": True},
    },
]


def build():
    vectors = []
    for case in CASES:
        params_native = to_native(case["params"])
        payload_native = to_native(case["payload"])

        inputs_hash = compute_inputs_hash(
            case["tool"], case["version"], case["as_of"], params_native
        )
        # 证据 id：contracts/README.md §6 —— "ev_" + sha256({tool,version,inputs_hash}) 前 16 位
        evidence_id = "ev_" + sha256_text(
            canonical_json(
                {"tool": case["tool"], "version": case["version"], "inputs_hash": inputs_hash}
            )
        )[:16]
        evidence_hash = sha256_text(canonical_json(payload_native))

        vectors.append(
            {
                "name": case["name"],
                "note": case["note"],
                "tool": case["tool"],
                "version": case["version"],
                "as_of": case["as_of"].isoformat(),
                "params": params_native,
                "canonical_json": canonical_json(
                    {
                        "tool": case["tool"],
                        "version": case["version"],
                        "as_of": case["as_of"].isoformat(),
                        "params": params_native,
                    }
                ),
                "inputs_hash": inputs_hash,
                "evidence_id": evidence_id,
                "evidence_payload": payload_native,
                "evidence_hash": evidence_hash,
                "legacy_evidence_id": (
                    f"ev_tool_{case['tool']}_{case['as_of']:%Y%m%d}_{inputs_hash[:12]}"
                ),
            }
        )
    return {
        "vector_version": "1.0.0",
        "contract_version": "1.0.0",
        "generator": {
            "source": "commorcial/src/cbr/tools/base.py",
            "functions": [
                "canonical_json",
                "compute_inputs_hash",
                "sha256_text",
                "to_native",
            ],
            "python": sys.version.split()[0],
            "command": (
                "CBR_LEGACY_SRC=<commorcial>/src "
                "python3 packages/contracts_dart/tool/generate_golden_vectors.py"
            ),
        },
        "rules": {
            "canonical_json": 'json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)',
            "to_native": "NaN/Inf -> null；date/datetime -> isoformat；numpy -> 原生",
            "inputs_hash": "sha256(canonical_json({tool, version, as_of, params}))，64 位小写 hex",
            "evidence_id": '"ev_" + sha256(canonical_json({tool, version, inputs_hash}))[:16]',
            "evidence_hash": "sha256(canonical_json(evidence_payload))，64 位小写 hex",
            "legacy_evidence_id": "旧版 ev_tool_<tool>_<YYYYMMDD>_<inputs_hash[:12]>，仅作历史对照，非 v1 规范值",
            "nan_inf": "输入的 NaN / Infinity 经 to_native 归一为 null（写入 params 前已完成）",
        },
        "vectors": vectors,
    }


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("vectors: %d -> %s" % (len(doc["vectors"]), OUT))
    for v in doc["vectors"]:
        print(" ", v["name"], v["inputs_hash"][:16], v["evidence_id"])


if __name__ == "__main__":
    main()
