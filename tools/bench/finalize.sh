#!/usr/bin/env bash
# 跑批收尾：合并分片 → 评分 → 重新生成论文表格/宏 → 重新编译 PDF。
#
# 用法（仓库根）：
#   bash tools/bench/finalize.sh
#
# 前提：`run_console_shards.sh` 已结束（或你想用当前已跑时点出中间报告）。
# 全流程不写入任何手工数字：所有表与正文宏都由 render_tables.py 从产物生成。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BENCH="${BENCH:-artifacts/bench}"
PY="${CBR_PYTHON:-$HOME/.cache/cbr-venv/bin/python}"
TECTONIC="${TECTONIC:-/home/xrak/rt/bin/tectonic}"

step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

step "合并分片"
"$PY" tools/bench/analysis/merge_shards.py "$BENCH" --out "$BENCH/console.json" || exit 1

step "评分（主表 + McNemar）"
"$PY" tools/bench/analysis/score_arms.py "$BENCH/console.json" || exit 1

step "生成论文表格与宏"
"$PY" tools/bench/analysis/render_tables.py --bench "$BENCH" || exit 1

step "编译 PDF"
HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}" \
  HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}" \
  "$TECTONIC" docs/25-paper/paper.tex 2>&1 | tail -5

printf '\n\033[1;32m✔ 完成\033[0m\n'
printf '  产物：%s/console.json\n' "$BENCH"
printf '  表格：docs/25-paper/tables/\n'
printf '  论文：docs/25-paper/paper.pdf\n'
