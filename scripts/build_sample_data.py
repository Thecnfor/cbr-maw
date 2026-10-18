"""生成 CBR-MAW 确定性仿真样例数据（SYNTHETIC）。

用法::

    .venv\\Scripts\\python.exe scripts/build_sample_data.py
    .venv\\Scripts\\python.exe scripts/build_sample_data.py --seed 20240601 --start 2018-01-02 --end 2025-09-30

输出（默认 ``data/samples/``）：

- ``market_daily.parquet/.csv``：日频宽表（行=交易日，列=序列 ID）
- ``macro_monthly.parquet/.csv``：月频宏观指标（行=观测月末）
- ``documents.parquet/.csv``：政策/新闻语料（≥300 条，含发布时间/来源/标题/正文/URL/哈希）
- ``data_cards.json``：每个序列的数据卡
- ``series_catalog.json``：序列目录
- ``MANIFEST.json`` / ``README.md``：数据集清单与 SYNTHETIC 声明

数据由固定随机种子生成，可完全复现；全部为仿真数据，不映射真实历史行情。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 允许直接以 `python scripts/build_sample_data.py` 运行（无需先安装包）
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cbr.data.synthetic import (  # noqa: E402
    MIN_DOCUMENTS,
    SAMPLE_END,
    SAMPLE_SEED,
    SAMPLE_START,
    generate_dataset,
    write_sample_data,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="生成 CBR-MAW 仿真样例数据（SYNTHETIC）")
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED, help="随机种子（默认 20240601，固定可复现）")
    parser.add_argument("--start", type=str, default=SAMPLE_START, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=SAMPLE_END, help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "data" / "samples"),
        help="输出目录（默认 data/samples）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """生成并落盘仿真数据，返回进程退出码。"""
    args = parse_args(argv)
    started = time.time()
    print("=" * 78)
    print("CBR-MAW 样例数据生成（SYNTHETIC 仿真数据，非真实市场数据）")
    print(f"seed={args.seed}  start={args.start}  end={args.end}  out={args.out}")
    print("=" * 78)
    dataset = generate_dataset(seed=args.seed, start=args.start, end=args.end)
    paths = write_sample_data(dataset, args.out)
    daily = dataset.daily_frame()
    elapsed = time.time() - started
    print(f"[OK] 交易日 {len(daily)} 天，序列 {daily.shape[1]} 条，文档 {len(dataset.documents)} 条")
    if len(dataset.documents) < MIN_DOCUMENTS:
        print(f"[WARN] 文档数量 {len(dataset.documents)} 少于要求 {MIN_DOCUMENTS}，请扩大样本区间")
    print(f"[OK] 观测长表 {len(dataset.obs)} 行（日频 + 月频 + 派生序列）")
    print("-" * 78)
    for key, path in paths.items():
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            relative = path
        print(f"  {key:24s} -> {relative}")
    print("-" * 78)
    print(f"[DONE] 用时 {elapsed:.2f}s；全部数据为 SYNTHETIC 仿真数据，可复现（seed={args.seed}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
