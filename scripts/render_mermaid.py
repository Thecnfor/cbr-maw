"""把 Markdown 中的 ```mermaid 代码块渲染为 PNG（通过 mermaid.ink 公开渲染服务）。

用法::

    .venv\\Scripts\\python.exe scripts\\render_mermaid.py docs\\techdoc\\chapter4_method.md

输出：docs/techdoc/figures/fig_01.png ...（按出现顺序编号），并生成 figures/manifest.json。
渲染失败不终止，记录失败项；转换 DOCX 时以文字占位。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.S)


def extract_blocks(md_text: str) -> list[str]:
    return [block.strip() for block in MERMAID_RE.findall(md_text) if block.strip()]


def _encode(diagram: str) -> str:
    return base64.urlsafe_b64encode(diagram.encode("utf-8")).decode("ascii")


def render_one(diagram: str, timeout: int = 60, width: int = 2000) -> bytes:
    """通过 mermaid.ink 渲染为图片字节（服务返回 JPEG，统一转为 PNG 便于 DOCX 嵌入）。"""
    url = f"https://mermaid.ink/img/{_encode(diagram)}?bgColor=white&width={width}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    image = Image.open(BytesIO(resp.content)).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: python scripts/render_mermaid.py <markdown> [输出目录]")
        return 2
    md_path = Path(argv[0])
    out_dir = Path(argv[1]) if len(argv) > 1 else md_path.parent / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    diagrams = extract_blocks(md_path.read_text(encoding="utf-8"))
    manifest: list[dict] = []
    for index, diagram in enumerate(diagrams, start=1):
        digest = hashlib.sha256(diagram.encode("utf-8")).hexdigest()[:12]
        target = out_dir / f"fig_{index:02d}.png"
        entry = {"index": index, "source_sha": digest, "path": str(target), "ok": False}
        try:
            data = render_one(diagram)
            target.write_bytes(data)
            entry.update(ok=True, bytes=len(data))
            print(f"[OK] 图 {index} -> {target} ({len(data)} bytes)")
        except Exception as exc:  # noqa: BLE001 - 渲染失败保留占位
            print(f"[FAIL] 图 {index}: {exc}")
            entry["error"] = str(exc)[:200]
        manifest.append(entry)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
