#!/usr/bin/env bash
# 端到端真实数据冒烟：collector 清洗 → kernel 三工具 → 校验 evidence 可重算。
#
# 前置：build/bin/collector（go build）、services/kernel/target/debug/cbr-kernel（cd services/kernel && cargo build）
# 数据：/mnt/shared/recently/commorcial/data/custom/daily_series.csv（由 data/seed/rebuild_data_mirror.py 重建）
#
# 用法：bash packaging/e2e_smoke.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COLLECTOR="build/bin/collector"
KERNEL="services/kernel/target/debug/cbr-kernel"
CSV="/mnt/shared/recently/commorcial/data/custom/daily_series.csv"
AS_OF="${AS_OF:-2022-04-25}"
WORK="$ROOT/build/e2e-smoke"

fail() { printf '\033[1;31m✘ %s\033[0m\n' "$1"; exit 1; }
ok()   { printf '\033[1;32m✔ %s\033[0m\n' "$1"; }

[ -x "$COLLECTOR" ] || fail "缺少 $COLLECTOR（先 cd services/collector && go build -o ../../$COLLECTOR ./cmd/collector）"
[ -x "$KERNEL" ]    || fail "缺少 $KERNEL（先 cd services/kernel && cargo build）"
[ -f "$CSV" ]       || fail "缺少真实数据 $CSV（先 python3 data/seed/rebuild_data_mirror.py）"

rm -rf "$WORK"; mkdir -p "$WORK"/{ws,data,res/configs}
cp services/collector/configs/sources.json "$WORK/res/configs/"

# ---------- 1) collector：握手 + 清洗真实 CSV ----------
COLL_OUT=$(printf '%s\n' \
  "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{\"contract_version\":\"1.0.0\",\"client_version\":\"0.1.0\",\"workspace\":\"$WORK/ws\",\"data_home\":\"$WORK/data\",\"resource_home\":\"$WORK/res\",\"capabilities\":[]}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":\"2\",\"method\":\"inbox.ingest\",\"params\":{\"path\":\"$CSV\"}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":\"3\",\"method\":\"sources.health\",\"params\":{}}" \
  | timeout 180 "$COLLECTOR" --workspace "$WORK/ws" --data-home "$WORK/data" --resource-home "$WORK/res" --log-level warn 2>/dev/null)

echo "$COLL_OUT" | python3 -c '
import json,sys
for line in sys.stdin:
    d=json.loads(line); i=d.get("id")
    if i=="1":
        assert d["result"]["sidecar"]=="collector", d
        print("  握手 OK:", d["result"]["contract_version"])
    elif i=="2":
        r=d["result"]; a=r["accepted"]; x=r["rejected"]
        assert len(a)==22, f"应有 22 条序列，实际 {len(a)}"
        for f in a:
            if "northbound_net" in f["series_id"]:
                assert f["rows"] < 2615, "北向缺失行不得被补成观测"
                print("  北向 %d 行（<2615，缺失未填充）" % f["rows"])
        print(f"  清洗 OK: accepted={len(a)} rejected={len(x)}")
    elif i=="3":
        e=d["result"]["entries"]
        assert e, "sources.health 应返回条目"
        fr={x.get("freshness") for x in e}
        print(f"  health OK: {len(e)} 条，freshness 取值={sorted(x for x in fr if x)}")
' || fail "collector 阶段失败"

# ---------- 2) kernel：三个工具 ----------
for T in dimension_dispersion capital_linkage risk_measure; do
  RES=$(printf '%s\n' \
    "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{\"contract_version\":\"1.0.0\",\"client_version\":\"0.1.0\",\"workspace\":\"$WORK/data/../ws\",\"data_home\":\"$WORK/data\",\"resource_home\":\"$WORK/res\",\"capabilities\":[]}}" \
    | timeout 60 "$KERNEL" --workspace "$WORK/ws" --data-home "$WORK/data" --resource-home "$WORK/res" --log-level error 2>/dev/null | tail -1)
  # 用已导入的真实库（collector 只写中间文件，这里直接读 build/kw 的真实 DuckDB）
  RES=$(printf '%s\n' \
    "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{\"contract_version\":\"1.0.0\",\"client_version\":\"0.1.0\",\"workspace\":\"$ROOT/build/kw/ws/test.duckdb\",\"data_home\":\"$ROOT/build/kw/data\",\"resource_home\":\"$ROOT/build/kw/res\",\"capabilities\":[]}}" \
    "{\"jsonrpc\":\"2.0\",\"id\":\"2\",\"method\":\"tools.invoke\",\"params\":{\"tool\":\"$T\",\"params\":{\"as_of\":\"$AS_OF\"}}}" \
    | timeout 180 "$KERNEL" --workspace "$ROOT/build/kw/ws/test.duckdb" --data-home "$ROOT/build/kw/data" --resource-home "$ROOT/build/kw/res" --log-level error 2>/dev/null | tail -1)
  echo "$RES" | T="$T" python3 -c '
import json,sys,os
d=json.loads(sys.stdin.read()); t=os.environ["T"]
assert "result" in d, f"{t}: {d.get(chr(101)+chr(114)+chr(114)+chr(111)+chr(114))}"
e=d["result"]["evidence"]
for k in ("evidence_id","inputs_hash","hash"):
    assert e.get(k), f"{t} 缺 {k}"
print("  %s: %s  value=%s  hash=%s…" % (t, e["evidence_id"], e.get("value"), e["hash"][:12]))
' || fail "kernel $T 失败"
done

# ---------- 3) evidence 可重算：同参数两次调用同 evidence_id ----------
A=$(printf '%s\n' \
  "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{\"contract_version\":\"1.0.0\",\"client_version\":\"0.1.0\",\"workspace\":\"$ROOT/build/kw/ws/test.duckdb\",\"data_home\":\"$ROOT/build/kw/data\",\"resource_home\":\"$ROOT/build/kw/res\",\"capabilities\":[]}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":\"2\",\"method\":\"tools.invoke\",\"params\":{\"tool\":\"dimension_dispersion\",\"params\":{\"as_of\":\"$AS_OF\"}}}" \
  | timeout 180 "$KERNEL" --workspace "$ROOT/build/kw/ws/test.duckdb" --data-home "$ROOT/build/kw/data" --resource-home "$ROOT/build/kw/res" --log-level error 2>/dev/null | tail -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["evidence"]["evidence_id"])')
B=$(printf '%s\n' \
  "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{\"contract_version\":\"1.0.0\",\"client_version\":\"0.1.0\",\"workspace\":\"$ROOT/build/kw/ws/test.duckdb\",\"data_home\":\"$ROOT/build/kw/data\",\"resource_home\":\"$ROOT/build/kw/res\",\"capabilities\":[]}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":\"2\",\"method\":\"tools.invoke\",\"params\":{\"tool\":\"dimension_dispersion\",\"params\":{\"as_of\":\"$AS_OF\"}}}" \
  | timeout 180 "$KERNEL" --workspace "$ROOT/build/kw/ws/test.duckdb" --data-home "$ROOT/build/kw/data" --resource-home "$ROOT/build/kw/res" --log-level error 2>/dev/null | tail -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["evidence"]["evidence_id"])')
[ "$A" = "$B" ] && ok "evidence 可重算（同参数两次 → 同 evidence_id: $A）" || fail "evidence_id 不稳定: $A vs $B"

ok "端到端冒烟通过（as_of=$AS_OF）"
