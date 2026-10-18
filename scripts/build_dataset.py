"""构建 PIT 数据库 + 融合风险信号产物，并打印样例 as_of 的 RiskSignal。

用法::

    .venv\\Scripts\\python.exe scripts/build_dataset.py
    .venv\\Scripts\\python.exe scripts/build_dataset.py --with-custom
    .venv\\Scripts\\python.exe scripts/build_dataset.py --demo-date 2024-08-05 --retrain-every 40
    .venv\\Scripts\\python.exe scripts/build_dataset.py --skip-pit --skip-signal   # 仅检查

产物：

- ``data/pit.duckdb``：series_obs / documents / series_meta 三张 PIT 表
- ``artifacts/models/manifest.json``：模型注册表清单
- ``artifacts/models/<model_version>/model_info.json``：模型元数据（特征、快照、指标）
- ``artifacts/models/<model_version>/signals.parquet``：逐日预计算 RiskSignal（API/UI 快速读取）

**数据声明**：未接入真实数据前，全部产物由 SYNTHETIC 仿真数据训练，仅用于演示/测试。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cbr.config import load_settings, resolve_path  # noqa: E402
from cbr.data import (  # noqa: E402
    MarketDataset,
    PitStore,
    SAMPLE_SEED,
    build_stress_labels,
    generate_dataset,
    load_sample_dataset,
    time_split,
)
from cbr.data.custom import CustomDatasetAdapter  # noqa: E402
from cbr.data.provider import _merge_datasets  # noqa: E402
from cbr.data.synthetic import dataset_fingerprint  # noqa: E402
from cbr.features import build_feature_bundle  # noqa: E402
from cbr.models import SignalEngine  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="构建 CBR-MAW PIT 数据库与融合风险信号产物")
    parser.add_argument("--sample-dir", default="data/samples", help="仿真样例数据目录")
    parser.add_argument("--pit-db", default="data/pit.duckdb", help="PIT 数据库路径")
    parser.add_argument("--artifacts", default="artifacts/models", help="模型产物目录")
    parser.add_argument(
        "--retrain-every",
        type=int,
        default=0,
        help="滚动重训间隔（交易日）；0 表示使用 configs/app.yaml 的 signal.retrain_every",
    )
    parser.add_argument("--demo-date", default="2024-08-05", help="打印 RiskSignal 样例的 as_of 日期")
    parser.add_argument("--seed", type=int, default=42, help="模型随机种子")
    parser.add_argument("--fusion", default="early", choices=["early", "late"], help="多模态融合方式")
    parser.add_argument("--with-custom", action="store_true", help="并入 data/custom 用户自建数据")
    parser.add_argument("--skip-pit", action="store_true", help="跳过 PIT 数据库构建")
    parser.add_argument("--skip-signal", action="store_true", help="跳过信号模型训练与产物保存")
    return parser.parse_args(argv)


def _load_dataset(args: argparse.Namespace) -> MarketDataset:
    """加载样例数据（文件缺失时内存生成），可选并入用户自建数据。"""
    sample_dir = resolve_path(args.sample_dir)
    try:
        dataset = load_sample_dataset(sample_dir)
        print(f"[OK] 加载样例数据: {sample_dir}")
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"[WARN] 样例数据不可用（{exc}），使用内存生成 SYNTHETIC 数据")
        dataset = generate_dataset(seed=SAMPLE_SEED)
    if args.with_custom:
        adapter = CustomDatasetAdapter(custom_data_dir=resolve_path("data/custom"))
        if adapter.has_custom:
            custom_dataset, _ = adapter.load()
            dataset = _merge_datasets(custom_dataset, dataset)
            print(f"[OK] 已并入用户自建数据: {len(custom_dataset.obs)} 条观测")
        else:
            print("[INFO] --with-custom 指定但 data/custom 无可用数据，忽略")
    return dataset


def _build_pit_database(dataset: MarketDataset, pit_path: Path) -> bool:
    """先构建到临时文件再原子替换，避免其他进程正在读取时中断构建。

    若目标文件被其他进程占用（Windows 不允许覆盖），保留旧数据库并给出提示，
    返回 False；调用方不应因此失败。
    """
    tmp_path = pit_path.with_name(pit_path.name + ".build_tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    t0 = time.time()
    store = PitStore.from_dataset(dataset, tmp_path)
    counts = store.counts()
    store.close()
    try:
        os.replace(tmp_path, pit_path)
        print(f"[OK] PIT 数据库: {pit_path}  {counts}  用时 {time.time() - t0:.2f}s")
        return True
    except OSError as exc:
        try:
            tmp_path.unlink()
        except OSError:  # pragma: no cover
            pass
        print(
            f"[WARN] PIT 数据库目标文件被其他进程占用（{exc.__class__.__name__}: {exc}），"
            "保留既有数据库；稍后重新运行本脚本即可更新"
        )
        return False


def _write_pit_manifest(dataset: MarketDataset, pit_path: Path, fingerprint: dict[str, str]) -> Path:
    """写 PIT 数据库清单（数据快照 ID / 文本语料哈希 / 行列数 / 构建时间）。"""
    manifest_path = pit_path.parent / "pit_manifest.json"
    payload = {
        "dataset": "cbr-maw-pit",
        "synthetic": str(dataset.source) == "synthetic-simulation",
        "source": dataset.source,
        "dataset_snapshot_id": fingerprint.get("dataset_snapshot_id"),
        "corpus_hash": fingerprint.get("corpus_hash"),
        "n_obs": int(len(dataset.obs)),
        "n_documents": int(len(dataset.documents)),
        "n_series": int(dataset.obs["series_id"].nunique()),
        "start": str(dataset.start.date()) if dataset.start is not None else None,
        "end": str(dataset.end.date()) if dataset.end is not None else None,
        "pit_db": pit_path.name,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "PIT 库由 scripts/build_dataset.py 从样例/自建数据构建；SYNTHETIC 数据仅用于演示/测试",
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    """执行构建流程，返回进程退出码。"""
    args = parse_args(argv)
    started = time.time()
    print("=" * 78)
    print("CBR-MAW 数据集与风险信号构建（SYNTHETIC 仿真数据，非真实市场数据）")
    print(f"sample={args.sample_dir}  pit={args.pit_db}  artifacts={args.artifacts}")
    print("=" * 78)
    settings = load_settings()
    dataset = _load_dataset(args)
    calendar = dataset.calendar
    fingerprint = dataset_fingerprint(dataset)
    print(
        f"[OK] 数据集: {len(calendar)} 个交易日 {calendar[0].date()}~{calendar[-1].date()}，"
        f"{dataset.obs['series_id'].nunique()} 条序列，{len(dataset.documents)} 篇文档，"
        f"source={dataset.source}"
    )
    print(
        f"     快照 ID: {fingerprint['dataset_snapshot_id']}  语料哈希: {fingerprint['corpus_hash']}"
    )

    # ---- 1) PIT 数据库 -------------------------------------------------- #
    if not args.skip_pit:
        pit_path = resolve_path(args.pit_db)
        rebuilt = _build_pit_database(dataset, pit_path)
        if rebuilt:
            manifest_path = _write_pit_manifest(dataset, pit_path, fingerprint)
            print(f"[OK] PIT 清单: {manifest_path}")
    else:
        print("[SKIP] PIT 数据库构建")

    # ---- 2) 特征 + 标签 + 信号模型 ------------------------------------- #
    demo_signal = None
    if not args.skip_signal:
        t0 = time.time()
        labels = build_stress_labels(dataset, label_version=settings.data.label_version)
        splits = time_split(calendar)
        frame = labels.frame
        print(
            f"[OK] 风险标签({labels.config.label_version}): 训练截止 {labels.train_end.date()}，"
            f"高压力阈值 τ={labels.threshold:.2f}，高压力日占比 "
            f"{frame['high_stress'].mean():.3f}（训练 {frame.loc[splits['train']]['high_stress'].mean():.3f} / "
            f"测试 {frame.loc[splits['test']]['high_stress'].mean():.3f}）"
        )
        bundle = build_feature_bundle(
            dataset,
            label_version=settings.data.label_version,
            text_enabled=bool(settings.signal.text_enabled),
            labels=labels,
        )
        print(
            f"[OK] 特征包: {bundle.X.shape[0]} 行 × {bundle.X.shape[1]} 列"
            f"（数值 {len(bundle.numeric_cols)} + 文本 {len(bundle.text_cols)}）"
        )
        signal_settings = settings.signal.model_copy(
            update={
                "retrain_every": int(args.retrain_every) if int(args.retrain_every) > 0 else settings.signal.retrain_every
            }
        )
        engine = SignalEngine(
            bundle=bundle,
            settings=signal_settings,
            seed=int(args.seed),
            artifact_dir=resolve_path(args.artifacts),
            fusion=str(args.fusion),
        )
        eval_dates = list(splits["test"])
        t0 = time.time()
        metrics = engine.evaluate(dates=eval_dates)
        print(f"[OK] 样本外评估（测试期 {len(eval_dates)} 个交易日）用时 {time.time() - t0:.1f}s")
        for horizon in sorted(metrics):
            item = metrics[horizon]
            print(
                f"     h={horizon:<3d} PR-AUC={item['pr_auc']:.3f}  ROC-AUC={item['roc_auc']:.3f}  "
                f"Brier={item['brier']:.3f}  召回(Top10%)={item['recall_top10pct']:.3f}  "
                f"n={item['n']}  pos={item['pos_rate']:.3f}"
            )
        entry = engine.save_artifacts(
            metrics=metrics,
            notes=(
                f"SYNTHETIC 仿真数据训练的演示模型；retrain_every={signal_settings.retrain_every}，"
                f"fusion={args.fusion}，仅用于演示/测试"
            ),
            data_snapshot={
                **fingerprint,
                "source": dataset.source,
                "n_obs": int(len(dataset.obs)),
                "n_documents": int(len(dataset.documents)),
                "start": str(calendar[0].date()),
                "end": str(calendar[-1].date()),
            },
        )
        print(f"[OK] 模型注册: version={entry['model_version']}")
        print(f"     artifacts_dir={entry.get('artifacts_dir')}")
        print(f"     signals_path={entry.get('signals_path')}")
        snapshot_count = len(engine.snapshot_dates())
        print(f"[OK] 滚动训练快照数 {snapshot_count}（每 {signal_settings.retrain_every} 交易日重训一次）")

        # ---- 3) 样例 as_of 的 RiskSignal（验收要求） -------------------- #
        demo_signal = engine.predict(args.demo_date)
        print("-" * 78)
        print(f"[DEMO] as_of={args.demo_date} 的 RiskSignal（JSON，SYNTHETIC 仿真数据模型输出）:")
        print(json.dumps(demo_signal.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print("[SKIP] 信号模型训练与产物保存")

    elapsed = time.time() - started
    print("-" * 78)
    print(f"[DONE] 构建完成，用时 {elapsed:.1f}s")
    print("[NOTE] 全部数据/模型均为 SYNTHETIC 仿真产物，禁止用于真实投资或监管决策")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
