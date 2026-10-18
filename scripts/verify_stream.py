"""流式接口验收脚本（Lead 用）：连接运行中的 API，打印 SSE 事件序列与耗时。

用法::

    # 先启动服务（另开进程）:
    .venv\\Scripts\\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
    # 再验收:
    .venv\\Scripts\\python.exe scripts\\verify_stream.py --base http://127.0.0.1:8000
    .venv\\Scripts\\python.exe scripts\\verify_stream.py --chat "当前风险如何？"

检查项：事件顺序（run → stage/trace → decision/chat）、最终业务事件、错误事件、
事件间隔是否体现真实流式（首个 trace 明显早于最终事件）。
"""

from __future__ import annotations

import argparse
import json
import time

import requests


def iter_sse(response: requests.Response):
    """解析 SSE 流，逐条 yield (event, data_dict_or_raw, elapsed_sec)。"""
    started = time.time()
    event = "message"
    data_lines: list[str] = []
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw == "":
            if data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = payload
                yield event, data, time.time() - started
            event, data_lines = "message", []
            continue
        if raw.startswith(":"):
            yield "ping", raw, time.time() - started
            continue
        if raw.startswith("event:"):
            event = raw.split(":", 1)[1].strip()
        elif raw.startswith("data:"):
            data_lines.append(raw.split(":", 1)[1].lstrip())


def summarize(event: str, data) -> str:
    if event == "decision":
        return f"decision cards={list(data.get('cards', {}))} conflicts={len(data.get('conflicts', []))}"
    if event == "chat":
        reply = str(data.get("reply", "")).replace("\n", " ")
        return f"chat reply={reply[:60]}... citations={len(data.get('citations') or [])}"
    if event == "run":
        return f"run_id={data.get('run_id')}"
    if event == "stage":
        return f"stage={data.get('stage')} status={data.get('status')} label={data.get('label')}"
    if event == "trace":
        return f"{data.get('action')} role={data.get('role')} tool={data.get('tool')}"
    if event == "error":
        return f"ERROR {data}"
    return str(data)[:80]


def run_decision(base: str, params: dict, limit: int = 60) -> int:
    url = f"{base}/api/decision/stream"
    print(f"== GET {url} params={params}")
    with requests.get(url, params=params, stream=True, timeout=300) as resp:
        print("status:", resp.status_code, resp.headers.get("content-type"))
        if resp.status_code != 200:
            print(resp.text[:400])
            return 1
        first_trace_at = None
        final_at = None
        counts: dict[str, int] = {}
        for event, data, elapsed in iter_sse(resp):
            counts[event] = counts.get(event, 0) + 1
            if counts[event] <= limit or event in ("decision", "error", "run"):
                print(f"[{elapsed:6.2f}s] {event:8s} {summarize(event, data)}")
            if event == "trace" and first_trace_at is None:
                first_trace_at = elapsed
            if event in ("decision", "error", "chat"):
                final_at = elapsed
                break
        print("counts:", counts)
        if final_at is None:
            print("FAIL: 没有收到最终业务事件")
            return 1
        if first_trace_at is not None and first_trace_at >= final_at - 0.5:
            print("WARN: 首个 trace 与最终事件几乎同时，未体现流式")
        else:
            print(f"OK: 首个 trace {first_trace_at}s / 最终 {final_at:.2f}s")
    return 0


def run_chat(base: str, message: str, as_of: str | None) -> int:
    url = f"{base}/api/chat/stream"
    body = {"message": message}
    if as_of:
        body["as_of"] = as_of
    print(f"== POST {url} body={body}")
    with requests.post(url, json=body, stream=True, timeout=300) as resp:
        print("status:", resp.status_code, resp.headers.get("content-type"))
        if resp.status_code != 200:
            print(resp.text[:400])
            return 1
        counts: dict[str, int] = {}
        final_at = None
        for event, data, elapsed in iter_sse(resp):
            counts[event] = counts.get(event, 0) + 1
            if counts[event] <= 20 or event == "chat":
                print(f"[{elapsed:6.2f}s] {event:8s} {summarize(event, data)}")
            if event == "chat":
                final_at = elapsed
                break
        print("counts:", counts, "| final at", final_at)
        return 0 if final_at is not None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW SSE 验收")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--as-of", default="2024-08-05")
    parser.add_argument("--scenario", default="yen_carry_2024")
    parser.add_argument("--mode", default="collaborative")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--chat", default=None, help="测试对话流式，传入问题")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()
    if args.chat:
        return run_chat(args.base, args.chat, args.as_of)
    params = {"as_of": args.as_of, "scenario": args.scenario, "mode": args.mode}
    if args.refresh:
        params["refresh"] = "true"
    return run_decision(args.base, params, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
