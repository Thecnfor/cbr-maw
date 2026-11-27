#!/usr/bin/env bash
# 清理被中断的 Rust 构建留下的孤儿临时对象。
#
# 由来（2026-11-27 实测）：release 构建被 kill 后，rustc 会把临时对象
# 留在 target/<profile>/build/<crate>/<hash>/out/ 里，形如 `rustcXXXXXX`
# 与 `*.rcgu.o.rcgu.o`，cargo 永不复用，单份约 200MB。7 次中断 = 1.3GB。
#
# 用法：
#   bash packaging/clean_build_leaks.sh           # 清理并报告释放空间
#   bash packaging/clean_build_leaks.sh --dry-run # 只报告
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

TARGETS=()
for d in "$ROOT"/services/*/target "$ROOT"/target; do
  [ -d "$d" ] && TARGETS+=("$d")
done

if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "无 target 目录，跳过"
  exit 0
fi

before=$(du -sm "${TARGETS[@]}" 2>/dev/null | awk '{s+=$1} END {print s+0}')
files=$(find "${TARGETS[@]}" -type f \( -path '*/build/*/out/rustc*' -o -name '*.rcgu.o.rcgu.o' \) 2>/dev/null)
count=$(printf '%s\n' "$files" | grep -c . || true)
bytes=$(printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 -r du -cm 2>/dev/null | tail -1 | cut -f1)

if [ "$count" -eq 0 ]; then
  echo "无孤儿临时对象（target 合计 ${before}MB）"
  exit 0
fi

printf '发现 %s 个孤儿临时对象，约 %sMB\n' "$count" "${bytes:-0}"
if [ "$DRY" -eq 1 ]; then
  echo "（dry-run，未删除）"
  exit 0
fi

printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 -r rm -f
# 清掉因此变空的 out/ 目录
find "${TARGETS[@]}" -type d -path '*/build/*/out' -empty -delete 2>/dev/null

after=$(du -sm "${TARGETS[@]}" 2>/dev/null | awk '{s+=$1} END {print s+0}')
printf '已清理：%sMB → %sMB（释放 %sMB）\n' "$before" "$after" "$((before - after))"
