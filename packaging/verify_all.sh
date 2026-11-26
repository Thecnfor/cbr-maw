#!/usr/bin/env bash
# CBR-MAW 全门禁校验（Lead 用；一条命令跑完所有语言的静态检查与测试）
# 用法：packaging/verify_all.sh [--quick]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

PASS=0; FAIL=0; SKIP=0
declare -a FAILED

run() {           # run <名称> <命令...>
  local name="$1"; shift
  printf '\n\033[1;36m▶ %s\033[0m\n' "$name"
  if "$@"; then
    printf '\033[1;32m✔ %s\033[0m\n' "$name"; PASS=$((PASS+1))
  else
    printf '\033[1;31m✘ %s\033[0m\n' "$name"; FAIL=$((FAIL+1)); FAILED+=("$name")
  fi
}

# ---------- Dart / Flutter ----------
run "flutter analyze（零 error 零 warning）" flutter analyze
run "flutter test（app）" bash -c "cd apps/desktop && flutter test"
if [ "$QUICK" -eq 0 ]; then
  run "dart format 检查" dart format --set-exit-if-changed .
  run "packages 测试" flutter test packages/design_system packages/a2ui_catalog
  run "contracts 测试" dart test packages/contracts_dart
  run "契约一致性（validate_contract）" dart run tools/validate_contract.dart
  run "分层依赖（check_layers）" dart run tools/check_layers.dart
  run "版本一致性（check_version）" dart run tools/check_version.dart
fi

# ---------- Rust ----------
if [ -f services/kernel/Cargo.toml ]; then
  run "cargo fmt --check" bash -c 'cd services/kernel && cargo fmt --check'
  run "cargo clippy -D warnings" bash -c 'cd services/kernel && cargo clippy -- -D warnings'
  run "cargo test（Rust 内核）" bash -c 'cd services/kernel && cargo test'
else
  printf '\033[33m⏭ Rust 内核未就绪，跳过\033[0m\n'; SKIP=$((SKIP+1))
fi

# ---------- Go ----------
if [ -f services/collector/go.mod ]; then
  run "go vet" bash -c 'cd services/collector && go vet ./...'
  run "go test（采集器）" bash -c 'cd services/collector && go test ./...'
else
  printf '\033[33m⏭ Go 采集器未就绪，跳过\033[0m\n'; SKIP=$((SKIP+1))
fi

# ---------- 真实数据黄金一致性（若有） ----------
if [ -f contracts/golden-vectors/cfsi_stress_pca_q90_reference.json ] && [ -f services/kernel/Cargo.toml ]; then
  # 默认只跑快的两个（各 ~60-90s）；CFSI 逐日 + 派生重算要 10+ 分钟，设 CBR_FULL_GOLDEN=1 才跑
  run "黄金向量（dispersion + linkage）" bash -c 'cd services/kernel && cargo test --test dispersion_golden --test linkage_golden 2>&1 | tail -20'
  if [ "${CBR_FULL_GOLDEN:-0}" = "1" ]; then
    run "黄金向量（CFSI 逐日 + 派生重算）" bash -c 'cd services/kernel && cargo test --test golden 2>&1 | tail -20'
  else
    printf '\033[33m⏭ CFSI 逐日 + 派生重算（设 CBR_FULL_GOLDEN=1，约 10 分钟）\033[0m\n'; SKIP=$((SKIP+1))
  fi
else
  printf '\033[33m⏭ CFSI 黄金比对未就绪，跳过\033[0m\n'; SKIP=$((SKIP+1))
fi

# ---------- 端到端冒烟（需已构建 sidecar） ----------
if [ -x build/bin/collector ] && [ -x "services/kernel/target/debug/cbr-kernel" ]; then
  run "端到端冒烟（真实数据）" bash packaging/e2e_smoke.sh
else
  printf '\033[33m⏭ sidecar 未构建，跳过端到端冒烟\033[0m\n'; SKIP=$((SKIP+1))
fi

printf '\n\033[1m═══ 门禁汇总 ═══\033[0m\n通过 %d · 失败 %d · 跳过 %d\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
  printf '失败项：\n'; for f in "${FAILED[@]}"; do printf '  - %s\n' "$f"; done
  exit 1
fi
