#!/usr/bin/env python3
"""预取本地向量模型（BGE-small-zh-v1.5）到工作区，并写 SHA256 清单。

为什么需要单独一步：fastembed 内置的 HF 下载在镜像端点上会因缺少 ETag 头失败
（实测 `MissingHeader("etag")`）。这里用标准库自己下，落盘后由 kernel 逐文件校验。

用法：
    python3 packaging/prefetch_embedding_model.py --out <workspace>/models
    HF_ENDPOINT=https://hf-mirror.com python3 packaging/prefetch_embedding_model.py --out ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPO = 'Xenova/bge-small-zh-v1.5'
FILES = [
    'onnx/model.onnx',
    'tokenizer.json',
    'config.json',
    'special_tokens_map.json',
    'tokenizer_config.json',
]
TARGET_NAMES = {'onnx/model.onnx': 'model.onnx'}


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={'User-Agent': 'cbr-maw-prefetch'})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, 'wb') as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, help='模型根目录（<workspace>/models）')
    args = parser.parse_args()

    endpoint = os.environ.get('HF_ENDPOINT', 'https://huggingface.co').rstrip('/')
    root = Path(args.out) / 'bge-small-zh-v1.5'
    root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, str] = {}
    for remote in FILES:
        name = TARGET_NAMES.get(remote, Path(remote).name)
        dest = root / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f'跳过已存在 {name}')
        else:
            url = f'{endpoint}/{REPO}/resolve/main/{remote}'
            print(f'下载 {url}')
            download(url, dest)
        manifest[name] = hashlib.sha256(dest.read_bytes()).hexdigest()

    (root / 'manifest.json').write_text(
        json.dumps({'repo': REPO, 'files': manifest}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(f'完成 → {root}（{len(manifest)} 个文件，已写 manifest.json）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
