#!/usr/bin/env bash
# 构建前预检：磁盘、负载、孤儿产物。失败即退出（set -e 链上安全）。
#
#   MIN_FREE_GB   仓库所在分区最少剩余（默认 20）
#   MAX_LOAD_RATIO 允许的 1 分钟负载 / CPU 核数上限（默认 2.0，留出交互余量）
#
# 用法：bash packaging/preflight.sh [--force]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

MIN_FREE_GB="${MIN_FREE_GB:-20}"
MAX_LOAD_RATIO="${MAX_LOAD_RATIO:-2.0}"
fail=0

# 1) 磁盘
free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  printf '\033[1;31m✘ 磁盘不足：%sGB 可用，需要 ≥ %sGB\033[0m\n' "$free_gb" "$MIN_FREE_GB"
  printf '  先跑：bash packaging/clean_build_leaks.sh\n'
  fail=1
else
  printf '\033[1;32m✔ 磁盘 %sGB 可用\033[0m\n' "$free_gb"
fi

# 2) 负载
nproc_n=$(nproc)
load1=$(awk '{print int($1)}' /proc/loadavg)
limit=$(awk -v n="$nproc_n" -v r="$MAX_LOAD_RATIO" 'BEGIN{printf "%d", n*r}')
if [ "$load1" -gt "$limit" ]; then
  printf '\033[1;33m⚠ 负载偏高：1 分钟 %s（%s 核，阈值 %s）——并发编译会互相拖慢\033[0m\n' "$load1" "$nproc_n" "$limit"
else
  printf '\033[1;32m✔ 负载 %s / %s 核\033[0m\n' "$load1" "$nproc_n"
fi

# 3) 孤儿产物（被中断的构建残留）
leaks=$(find "$ROOT"/services/*/target -type f -path '*/build/*/out/rustc*' 2>/dev/null | wc -l)
if [ "$leaks" -gt 0 ]; then
  printf '\033[1;33m⚠ 发现 %s 个孤儿临时对象（上次构建被中断）——建议 bash packaging/clean_build_leaks.sh\033[0m\n' "$leaks"
fi

if [ "$fail" -eq 1 ] && [ "$FORCE" -eq 0 ]; then
  exit 1
fi
