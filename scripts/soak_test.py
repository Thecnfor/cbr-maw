"""CBR-MAW 长时（soak）测试脚本：反复触发实时抓取，采集稳定性与资源趋势。

把「实时智能抓取」当作一个长跑组件来压：以可配置的总时长与运行间隔反复触发
``IngestAgent.run``（或后台调度器的 ``run_once`` 路径），逐次记录耗时、成功率、
观测/文档写入数、各来源状态、陈旧序列数与进程常驻内存（RSS），并实时落盘 JSONL，
末尾输出汇总，用于观察长时稳定性与资源是否随运行次数漂移。

用法（项目根目录）::

    # 5 分钟、每 60 秒抓一次（真实来源，先把代理关掉避免抓取被劫持）
    .venv/bin/python scripts/soak_test.py --duration 1800 --interval 60

    # 只抓固定的少量序列、强制刷新、不写库（快速冒烟）
    .venv/bin/python scripts/soak_test.py --duration 300 --interval 30 \
        --series csi300,csi500 --mode forced --no-write --max-runs 3

    # 走后台调度器路径（覆盖 IngestScheduler.run_once）
    .venv/bin/python scripts/soak_test.py --duration 600 --interval 120 --via-scheduler

注意：真实公开来源需要直连（不要开 http(s)_proxy，否则返回被拦截的页面）。
若环境里导出了代理，用 ``env -u http_proxy -u https_proxy -u all_proxy`` 清除后再跑。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # 允许直接 python scripts/soak_test.py
    sys.path.insert(0, str(ROOT / "src"))

from cbr.config import load_settings, resolve_path  # noqa: E402
from cbr.ingest import build_ingest_agent  # noqa: E402


# --------------------------------------------------------------------------- #
# 资源观测
# --------------------------------------------------------------------------- #
def read_rss_mb() -> float | None:
    """读取当前进程 RSS（MB）；取不到返回 ``None``。"""
    try:  # 首选 psutil（跨平台）
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001 - 缺依赖/无权限时降级
        pass
    try:  # Linux /proc
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _percentile(values: list[float], pct: float) -> float | None:
    """线性插值分位数（``values`` 非空）。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


# --------------------------------------------------------------------------- #
# 单次运行
# --------------------------------------------------------------------------- #
def run_once(agent: Any, scheduler: Any, args: argparse.Namespace, index: int) -> dict[str, Any]:
    """触发一次抓取并返回结构化记录（异常被捕获进 ``error`` 字段）。"""
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "index": index,
        "started_at": started_at.isoformat(),
        "mode": args.mode,
        "rss_before_mb": read_rss_mb(),
    }
    try:
        if scheduler is not None:
            report = scheduler.run_once(as_of=args.as_of, series_ids=args.series_ids, mode=args.mode)
        else:
            report = agent.run(
                args.as_of,
                series_ids=args.series_ids,
                mode=args.mode,
                write=not args.no_write,
            )
        statuses: dict[str, int] = {"ok": 0, "empty": 0, "error": 0, "skipped": 0}
        per_source: list[dict[str, Any]] = []
        for result in report.results:
            statuses[result.status] = statuses.get(result.status, 0) + 1
            per_source.append(
                {
                    "source_id": result.source_id,
                    "status": result.status,
                    "n_observations": result.n_observations,
                    "n_documents": result.n_documents,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                }
            )
        freshness = agent.freshness(args.as_of)
        record.update(
            {
                "run_id": report.run_id,
                # 单次运行成功 = 未抛异常并产出报告；个别来源失败由多源回退兜底，
                # 通过 source_statuses / n_errors 单独观察，不判定整次运行失败。
                "ok": True,
                "n_tasks": report.n_tasks,
                "n_observations": report.n_observations,
                "n_documents": report.n_documents,
                "n_errors": report.n_errors,
                "n_written_series": len(report.written_series),
                "source_statuses": statuses,
                "sources": per_source,
                "stale_series": sum(1 for item in freshness if item.is_stale),
                "fetchable_series": sum(1 for item in freshness if item.fetchable),
            }
        )
    except Exception as exc:  # noqa: BLE001 - soak 单次失败不应中断整体
        record.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    record["wall_ms"] = int((time.perf_counter() - started) * 1000)
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["rss_after_mb"] = read_rss_mb()
    return record


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
def _source_rollup(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按来源聚合各次状态与耗时。"""
    rollup: dict[str, dict[str, Any]] = {}
    for record in records:
        for src in record.get("sources") or []:
            agg = rollup.setdefault(
                src["source_id"],
                {"runs": 0, "ok": 0, "empty": 0, "error": 0, "skipped": 0, "obs": 0, "docs": 0, "latencies": []},
            )
            agg["runs"] += 1
            agg[src["status"]] = agg.get(src["status"], 0) + 1
            agg["obs"] += int(src.get("n_observations") or 0)
            agg["docs"] += int(src.get("n_documents") or 0)
            if src.get("latency_ms"):
                agg["latencies"].append(int(src["latency_ms"]))
    for agg in rollup.values():
        lats = agg.pop("latencies")
        agg["latency_ms_mean"] = round(statistics.fmean(lats), 1) if lats else None
        agg["latency_ms_p95"] = round(_percentile(lats, 0.95), 1) if lats else None
    return rollup


def summarize(
    records: list[dict[str, Any]],
    *,
    started_at: datetime,
    planned_duration: int,
    label: str,
) -> dict[str, Any]:
    """汇总全部运行记录。"""
    finished_at = datetime.now(timezone.utc)
    latencies = [float(r["wall_ms"]) for r in records if r.get("wall_ms") is not None]
    rss_values = [r["rss_after_mb"] for r in records if r.get("rss_after_mb") is not None]
    ok_runs = [r for r in records if r.get("ok")]
    return {
        "label": label,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "planned_duration_s": planned_duration,
        "actual_duration_s": round((finished_at - started_at).total_seconds(), 1),
        "n_runs": len(records),
        "n_ok": len(ok_runs),
        "n_failed": len(records) - len(ok_runs),
        "success_rate": round(len(ok_runs) / len(records), 4) if records else None,
        "total_observations": sum(int(r.get("n_observations") or 0) for r in records),
        "total_documents": sum(int(r.get("n_documents") or 0) for r in records),
        "total_errors": sum(int(r.get("n_errors") or 0) for r in records),
        "stale_series_start": next((r.get("stale_series") for r in records if "stale_series" in r), None),
        "stale_series_end": next((r.get("stale_series") for r in reversed(records) if "stale_series" in r), None),
        "latency_ms": {
            "min": round(min(latencies), 1) if latencies else None,
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "rss_mb": {
            "start": rss_values[0] if rss_values else None,
            "end": rss_values[-1] if rss_values else None,
            "peak": max(rss_values) if rss_values else None,
            "delta": round(rss_values[-1] - rss_values[0], 1) if len(rss_values) >= 2 else None,
        },
        "sources": _source_rollup(records),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    """打印人读汇总。"""
    lat = summary["latency_ms"]
    rss = summary["rss_mb"]
    print("\n================= SOAK SUMMARY =================")
    print(f"label             : {summary['label']}")
    print(f"runs              : {summary['n_runs']} (ok={summary['n_ok']}, failed={summary['n_failed']})")
    print(f"success_rate      : {summary['success_rate']}")
    print(f"duration          : {summary['actual_duration_s']}s / planned {summary['planned_duration_s']}s")
    print(f"observations/docs : {summary['total_observations']} / {summary['total_documents']}")
    print(f"source errors     : {summary['total_errors']}")
    print(f"stale series      : {summary['stale_series_start']} -> {summary['stale_series_end']}")
    print(f"latency ms        : min={lat['min']} mean={lat['mean']} p50={lat['median']} p95={lat['p95']} max={lat['max']}")
    print(f"rss mb            : start={rss['start']} end={rss['end']} peak={rss['peak']} delta={rss['delta']}")
    print("sources           :")
    for source_id, agg in sorted(summary["sources"].items()):
        print(
            f"  - {source_id:20s} runs={agg['runs']:3d} ok={agg['ok']:3d} empty={agg['empty']:3d} "
            f"error={agg['error']:3d} skipped={agg['skipped']:3d} obs={agg['obs']:6d} docs={agg['docs']:5d} "
            f"lat_mean={agg['latency_ms_mean']}"
        )
    print("===============================================\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="CBR-MAW 长时（soak）测试：反复触发实时抓取")
    parser.add_argument("--duration", type=int, default=1800, help="总时长（秒），默认 1800（30 分钟）")
    parser.add_argument("--interval", type=int, default=300, help="两次抓取间隔（秒），默认 300")
    parser.add_argument("--max-runs", type=int, default=0, help="最多运行次数（0 = 不限制，按 --duration）")
    parser.add_argument("--mode", choices=["gap", "full", "forced"], default="gap", help="抓取模式")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="基准日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--series", type=str, default=None, help="仅抓取这些序列（逗号分隔）")
    parser.add_argument("--no-write", action="store_true", help="只抓取不写回 PIT（干跑）")
    parser.add_argument("--via-scheduler", action="store_true", help="通过 IngestScheduler.run_once 路径运行")
    parser.add_argument("--output-dir", type=str, default="artifacts/soak", help="结果落盘目录")
    parser.add_argument("--label", type=str, default=None, help="本次运行的标签（默认用时间戳）")
    parser.add_argument("--min-success-rate", type=float, default=0.0, help="低于该成功率则以非零码退出")
    args = parser.parse_args(argv)
    args.series_ids = tuple(s.strip() for s in args.series.split(",") if s.strip()) if args.series else None
    return args


def main(argv: list[str] | None = None) -> int:
    """入口：按计划反复抓取，实时落盘并输出汇总。"""
    args = parse_args(argv)
    settings = load_settings()
    label = args.label or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = resolve_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"soak-{label}.jsonl"
    summary_path = out_dir / f"soak-{label}.summary.json"

    agent = build_ingest_agent(settings)
    scheduler = None
    if args.via_scheduler:
        from cbr.ingest import IngestScheduler

        scheduler = IngestScheduler(agent, settings)

    started_at = datetime.now(timezone.utc)
    deadline = started_at.timestamp() + args.duration
    records: list[dict[str, Any]] = []

    print(
        f"[soak] label={label} duration={args.duration}s interval={args.interval}s "
        f"mode={args.mode} write={not args.no_write} scheduler={args.via_scheduler}"
    )
    print(f"[soak] 结果落盘: {jsonl_path}")

    index = 0
    try:
        while True:
            if args.max_runs and index >= args.max_runs:
                break
            if index > 0 and time.time() >= deadline:
                break
            index += 1
            record = run_once(agent, scheduler, args, index)
            records.append(record)
            with jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                f"[soak] run {index:3d} ok={record.get('ok')} obs={record.get('n_observations')} "
                f"docs={record.get('n_documents')} errors={record.get('n_errors')} "
                f"stale={record.get('stale_series')} wall={record.get('wall_ms')}ms "
                f"rss={record.get('rss_after_mb')}MB"
            )
            if args.max_runs and index >= args.max_runs:
                break
            if time.time() + args.interval > deadline and args.duration > 0:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[soak] 收到中断，提前收尾并输出汇总…")

    summary = summarize(records, started_at=started_at, planned_duration=args.duration, label=label)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(summary)
    print(f"[soak] 汇总落盘: {summary_path}")

    if args.min_success_rate and (summary["success_rate"] or 0.0) < args.min_success_rate:
        print(f"[soak] 成功率 {summary['success_rate']} 低于阈值 {args.min_success_rate}")
        return 1
    if summary["n_runs"] == 0:
        print("[soak] 未执行任何运行")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
