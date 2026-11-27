#!/usr/bin/env bash
# 分片并行跑真实链路基准，并把产物合并成一份可评分的 JSON。
#
# 用法（仓库根）：
#   PAIRS=60 SHARDS=4 bash tools/bench/run_console_shards.sh
#
# 口径：PAIRS 是**每类（压力/平静）**的时点数，总时点 = 2*PAIRS；分片只切分同一份
# 抽样（seed 固定），因此合并后与单进程跑完全等价，可逐时点复现。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PAIRS="${PAIRS:-60}"
SHARDS="${SHARDS:-4}"
ARMS="${ARMS:-collaborative,single,independent}"
OUT="${OUT:-artifacts/bench}"
SEED="${SEED:-11}"
EXTRA_ARGS="${EXTRA_ARGS:-}"   # 额外控制台参数，如 --no-memory（不带引号展开）

mkdir -p "$OUT"
pids=()
for i in $(seq 0 $((SHARDS - 1))); do
  printf '▶ shard %s/%s → %s/shard%s.json\n' "$i" "$SHARDS" "$OUT" "$i"
  dart run apps/desktop/tool/bench_console.dart \
    --pairs "$PAIRS" --shards "$SHARDS" --shard "$i" \
    --arms "$ARMS" --seed "$SEED" \
    --out "$OUT/shard$i.json" $EXTRA_ARGS > "$OUT/shard$i.log" 2>&1 &
  pids+=($!)
done

fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done

if [ "$fail" -ne 0 ]; then
  printf '✘ 至少一个分片失败；日志见 %s/shard*.log\n' "$OUT"
  exit 1
fi

~/.cache/cbr-venv/bin/python tools/bench/analysis/merge_shards.py "$OUT" --out "$OUT/console.json"
printf '✔ 合并完成 → %s/console.json\n' "$OUT"
printf '评分：~/.cache/cbr-venv/bin/python tools/bench/analysis/score_arms.py %s/console.json\n' "$OUT"
