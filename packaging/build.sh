#!/usr/bin/env bash
# CBR-MAW 构建脚本：构建两个 sidecar + Flutter 应用，并把产物摆到打包目录。
# 用法：
#   packaging/build.sh sidecars          # 只构建 collector/kernel
#   packaging/build.sh linux             # 构建 Linux 桌面版（开发/验证）
#   packaging/build.sh windows           # 构建 Windows 桌面版（需在 Windows 上跑）
#   packaging/build.sh all               # 全部
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(tr -d '[:space:]' < contracts/VERSION)"
SIDECAR_OUT="$ROOT/packaging/sidecars"

log() { printf '\033[1;36m[build]\033[0m %s\n' "$*"; }

build_sidecars() {
  log "collector (Go) → $SIDECAR_OUT/collector"
  mkdir -p "$SIDECAR_OUT"
  (cd services/collector && go build -trimpath -ldflags "-s -w -X main.version=$VERSION" -o "$SIDECAR_OUT/collector" .)

  log "kernel (Rust) → $SIDECAR_OUT/kernel"
  (cd services/kernel && cargo build --release)
  cp services/kernel/target/release/kernel "$SIDECAR_OUT/kernel"
}

cross_sidecars_windows() {
  log "交叉编译 Windows sidecar（Go/Rust 可跨；Flutter 官方不支持从 Linux 交叉编译 Windows）"
  (cd services/collector && GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w" -o "$SIDECAR_OUT/collector.exe" .)
  (cd services/kernel && cargo build --release --target x86_64-pc-windows-gnu)
  cp services/kernel/target/x86_64-pc-windows-gnu/release/kernel.exe "$SIDECAR_OUT/kernel.exe"
}

build_flutter() {
  local platform="${1:-linux}"
  log "flutter build $platform --release"
  (cd apps/desktop && flutter build "$platform" --release)
}

case "${1:-all}" in
  sidecars) build_sidecars ;;
  linux)    build_sidecars; build_flutter linux ;;
  windows)  build_sidecars; cross_sidecars_windows; build_flutter windows ;;
  all)      build_sidecars; build_flutter linux ;;
  *) echo "用法: $0 {sidecars|linux|windows|all}" >&2; exit 2 ;;
esac

log "完成。版本 $VERSION"
