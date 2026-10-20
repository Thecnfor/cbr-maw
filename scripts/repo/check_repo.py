#!/usr/bin/env python
"""仓库卫生检查（CI / pre-commit 共用，仅依赖 Python 标准库）。

检查项：

1. ``--check-large``  大文件：在「已跟踪 + 未跟踪且未被 .gitignore 忽略」的文件中，
   找出超过阈值（默认 50MB，GitHub 单文件硬限制）的文件；
2. ``--check-secrets`` 疑似密钥：扫描文本文件中的 API key / 私钥 / 硬编码口令，
   并检查 ``.env``、``secrets/`` 是否被误跟踪；
3. ``--check-links``  Markdown 相对链接：检查 ``*.md`` 中的相对链接/图片目标是否存在。

设计取舍：

- 使用 ``git ls-files`` 判定「会被提交的文件」，因此被 .gitignore 忽略的
  ``data/custom/``、``artifacts/``、``docs/金融数据.zip`` 等不会误报；
- 无 git 环境时退化为目录遍历（跳过 .git/.venv/node_modules 等）；
- 链接检查只针对已跟踪文件，避免工作区中半成品文档造成假失败；
- 退出码 0 = 通过，1 = 发现错误（CI 可直接作为门禁使用）。

用法::

    .venv\\Scripts\\python.exe scripts/repo/check_repo.py
    .venv\\Scripts\\python.exe scripts/repo/check_repo.py --check-large --check-secrets
    .venv\\Scripts\\python.exe scripts/repo/check_repo.py --check-links --max-mb 50
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

DEFAULT_MAX_MB = 50.0
MAX_SCAN_BYTES = 2 * 1024 * 1024  # 单文件密钥扫描上限，避免误读大文件

# 目录遍历回退模式下跳过的目录（有 git 时以 .gitignore 为准）
SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv-probe",
    ".references",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "artifacts",
}

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".zip",
    ".7z",
    ".rar",
    ".gz",
    ".tgz",
    ".parquet",
    ".duckdb",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".pyc",
    ".pyd",
    ".so",
    ".dll",
    ".exe",
}

# 常见密钥特征；宁可少报也不要大量误报（CI 门禁）
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI/DeepSeek 风格 API Key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub Token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("私钥内容", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----")),
    (
        "硬编码密钥/口令赋值",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)\b"
            r"\s*[:=]\s*[\"'][A-Za-z0-9/+_\-]{24,}[\"']"
        ),
    ),
]

SECRET_ALLOWLIST_MARKERS = (
    "pragma: allowlist secret",
    "noqa: secret",
    "placeholder",
    "example-key",
    "your-api-key",
    "sk-test",
    "sk-xxx",
    "sk-...",
)

# Markdown 行内链接/图片：[text](target "title") / ![alt](<target with space>)
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>\n]*>|[^)\s]+)")
# 引用式链接定义： [label]: path
REF_LINK_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
SKIP_URL_PREFIXES = ("mailto:", "tel:", "data:", "javascript:", "#")
WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


# --------------------------------------------------------------------------- #
# 文件清单
# --------------------------------------------------------------------------- #
def _git_files(root: Path, *args: str) -> list[str] | None:
    """执行 git 命令并返回 NUL 分隔的文件列表；git 不可用/失败时返回 None。"""
    cmd = ["git", "-C", str(root), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", "surrogateescape")
    return [item for item in raw.split("\0") if item]


def _walk_files(root: Path) -> list[str]:
    """无 git 回退：遍历工作区，跳过已知目录。"""
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        found.append(path.relative_to(root).as_posix())
    return found


def collect_files(root: Path) -> tuple[list[str], list[str]]:
    """返回 (已跟踪文件, 未跟踪且未被忽略的文件)；均相对于仓库根目录。"""
    tracked = _git_files(root, "ls-files", "-z")
    others = _git_files(root, "ls-files", "-z", "--others", "--exclude-standard")
    if tracked is None:
        files = sorted(_walk_files(root))
        return files, []
    return sorted(tracked), sorted(others or [])


# --------------------------------------------------------------------------- #
# 检查 1：大文件
# --------------------------------------------------------------------------- #
def check_large(root: Path, files: list[str], max_mb: float) -> list[str]:
    limit = max_mb * 1024 * 1024
    hits: list[tuple[int, str]] = []
    for rel in files:
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > limit:
            hits.append((size, rel))
    if not hits:
        return []
    hits.sort(reverse=True)
    lines = [f"发现 {len(hits)} 个超过 {max_mb:g}MB 的文件（应加入 .gitignore 或使用 Git LFS）:"]
    for size, rel in hits:
        lines.append(f"  - {size / 1024 / 1024:.1f}MB  {rel}")
    return lines


# --------------------------------------------------------------------------- #
# 检查 2：疑似密钥
# --------------------------------------------------------------------------- #
def _looks_binary(path: Path, sample_size: int = 2048) -> bool:
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError:
        return True
    return b"\0" in chunk


def check_secrets(root: Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        posix = rel.replace("\\", "/")
        name = Path(posix).name
        if posix == ".env" or posix.startswith("secrets/") or "/secrets/" in posix:
            errors.append(f"{posix}: 敏感文件被纳入版本控制（应删除并加入 .gitignore）")
            continue
        if posix.endswith(".example") or name == ".env.example":
            continue
        path = root / posix
        if path.suffix.lower() in BINARY_SUFFIXES or _looks_binary(path):
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in SECRET_ALLOWLIST_MARKERS):
                continue
            for label, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match is None:
                    continue
                snippet = match.group(0)[:12]
                errors.append(f"{posix}:{lineno}: 疑似{label}（{snippet}…，已截断）")
                break
    return errors


# --------------------------------------------------------------------------- #
# 检查 3：Markdown 相对链接
# --------------------------------------------------------------------------- #
def _strip_code(text: str) -> str:
    """移除围栏代码块与行内代码，保留空行以维持行号。"""
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append("")
            continue
        if in_fence:
            out_lines.append("")
            continue
        out_lines.append(INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line))
    return "\n".join(out_lines)


def _iter_link_targets(line: str) -> list[str]:
    targets = [match.group(1) for match in INLINE_LINK_RE.finditer(line)]
    ref = REF_LINK_RE.match(line)
    if ref is not None:
        targets.append(ref.group(1))
    return targets


def _resolve_target(root: Path, md_path: Path, target: str) -> str | None:
    """返回错误信息；链接正常或应跳过时返回 None。"""
    raw = target.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    if not raw:
        return None
    if raw.startswith(SKIP_URL_PREFIXES):
        return None
    if URL_SCHEME_RE.match(raw) or WINDOWS_ABS_RE.match(raw):
        return None
    path_part = raw.split("#", 1)[0].strip()
    if not path_part:
        return None
    decoded = unquote(path_part)
    if decoded.startswith("/"):
        resolved = root / decoded.lstrip("/")
    else:
        resolved = md_path.parent / decoded
    try:
        resolved = resolved.resolve()
    except OSError:
        return f"链接目标无法解析：{raw}"
    if not resolved.exists():
        return f"链接目标不存在：{raw}"
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return f"链接指向仓库外：{raw}"
    return None


def check_links(root: Path, files: list[str]) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    for rel in files:
        if not rel.lower().endswith((".md", ".markdown")):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(_strip_code(text).splitlines(), start=1):
            for target in _iter_link_targets(line):
                checked += 1
                issue = _resolve_target(root, path, target)
                if issue:
                    errors.append(f"{rel}:{lineno}: {issue}")
    return errors, checked


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def _default_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2], here.parents[1], Path.cwd()]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return here.parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CBR-MAW 仓库卫生检查（大文件 / 密钥 / Markdown 链接）")
    parser.add_argument("--repo-root", default=None, help="仓库根目录（默认自动探测）")
    parser.add_argument("--check-large", action="store_true", help="检查超过阈值的文件")
    parser.add_argument("--check-secrets", action="store_true", help="检查疑似密钥/敏感文件")
    parser.add_argument("--check-links", action="store_true", help="检查 Markdown 相对链接")
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB, help="大文件阈值（MB，默认 50）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enabled = [args.check_large, args.check_secrets, args.check_links]
    if not any(enabled):  # 默认全部检查
        args.check_large = args.check_secrets = args.check_links = True

    root = Path(args.repo_root).resolve() if args.repo_root else _default_root().resolve()
    if not root.is_dir():
        print(f"[ERROR] 仓库根目录不存在：{root}")
        return 1

    tracked, untracked = collect_files(root)
    all_files = sorted(set(tracked) | set(untracked))
    print("=" * 72)
    print("CBR-MAW 仓库卫生检查")
    print(f"仓库根目录：{root}")
    print(f"检查范围：已跟踪 {len(tracked)} 个文件 + 未跟踪未忽略 {len(untracked)} 个文件")
    print("=" * 72)

    failed = False

    if args.check_large:
        print(f"\n[大文件] 阈值 {args.max_mb:g}MB")
        problems = check_large(root, all_files, args.max_mb)
        if problems:
            failed = True
            print("\n".join(f"  [ERROR] {line}" for line in problems))
        else:
            print("  [OK] 未发现超限文件")

    if args.check_secrets:
        print("\n[疑似密钥]")
        problems = check_secrets(root, all_files)
        if problems:
            failed = True
            print("\n".join(f"  [ERROR] {line}" for line in problems))
        else:
            print("  [OK] 未发现疑似密钥或误入版本控制的敏感文件")

    if args.check_links:
        print("\n[Markdown 相对链接]")
        problems, checked = check_links(root, tracked)
        if problems:
            failed = True
            print("\n".join(f"  [ERROR] {line}" for line in problems))
            print(f"  共检查 {checked} 个相对链接，{len(problems)} 处异常")
        else:
            print(f"  [OK] 共检查 {checked} 个相对链接，未发现断链")

    print("\n" + "=" * 72)
    if failed:
        print("结论：失败（请修复上面标记的 [ERROR] 项）")
        print("=" * 72)
        return 1
    print("结论：通过")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
