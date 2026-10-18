"""CBR-MAW 一键启动 / 演示入口（命令行，可选）。

在项目根目录运行::

    .venv\\Scripts\\python.exe app\\demo_entry.py            # 环境自检 + 打印启动命令
    .venv\\Scripts\\python.exe app\\demo_entry.py --open     # 自检并打开驾驶台/API 文档
    .venv\\Scripts\\python.exe app\\demo_entry.py --serve    # 直接后台启动 API + UI（Ctrl+C 退出）

说明：``--serve`` 只是本地演示便利脚本；生产/答辩演示建议分别用两条正式命令启动，
以便独立查看日志（见 README 与 docs/architecture）。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PYTHON = sys.executable
API_URL = "http://127.0.0.1:8000/docs"
UI_URL = "http://127.0.0.1:8501"

for _candidate in (str(ROOT), str(SRC)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

REQUIRED_MODULES = ("fastapi", "uvicorn", "streamlit", "plotly", "pandas", "pydantic", "yaml", "httpx")


def _check_imports() -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []
    for module in REQUIRED_MODULES:
        try:
            installed = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            installed = False
        results.append((module, installed))
    return results


def _check_core() -> list[tuple[str, bool, str]]:
    try:
        from cbr.api.readiness import module_statuses

        return [(item.module, item.ready, item.detail) for item in module_statuses()]
    except Exception as exc:  # noqa: BLE001
        return [("cbr.api.readiness", False, f"{type(exc).__name__}: {exc}")]


def _print_status() -> bool:
    print("=" * 78)
    print("CBR-MAW · 跨境金融风险多智能体协同预警系统 · 演示入口")
    print("=" * 78)
    print(f"项目根目录 : {ROOT}")
    print(f"Python     : {PYTHON}")
    print()
    print("[1] 依赖检查")
    all_ok = True
    for module, installed in _check_imports():
        marker = "OK  " if installed else "MISS"
        all_ok = all_ok and installed
        print(f"    [{marker}] {module}")
    print()
    print("[2] 核心模块装配状态（data/knowledge/tools/llm/orchestration）")
    core_ready = True
    for module, ready, detail in _check_core():
        marker = "OK  " if ready else "WAIT"
        note = "" if ready else f"  # {detail}"
        core_ready = core_ready and ready
        print(f"    [{marker}] {module}{note}")
    print()
    print("[3] 启动命令（另开两个终端，均在项目根目录执行）")
    print("    set PYTHONPATH=src")
    print("    .venv\\Scripts\\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000")
    print("    .venv\\Scripts\\python.exe -m streamlit run app/dashboard.py --server.port 8501")
    print()
    print(f"    API 文档 : {API_URL}")
    print(f"    驾驶台   : {UI_URL}")
    print()
    print("[4] 演示流程")
    print("    选场景 → 看风险信号（5/10/20 日概率/历史分位/驱动归因）→ 三智能体卡片 →")
    print("    证据板（来源/时点/工具版本/输入哈希）→ 分歧与协调 → 核验与审计 trace →")
    print("    导出 Markdown/JSON 简报 → 智能对话追问")
    print()
    if not all_ok:
        print("⚠️  存在缺失依赖：请先执行 `.venv\\Scripts\\python.exe -m pip install -e .`（或 pip install -r requirements.txt）。")
    elif not core_ready:
        print("ℹ️  核心模块尚未全部就绪：API 仍可启动（/api/health 返回 degraded，业务端点 503 中文提示），")
        print("    驾驶台会显示模块装配状态与就绪后的演示流程，不会白屏。")
    else:
        print("✅ 环境与核心模块均就绪，可以开始演示。")
    print("=" * 78)
    return all_ok and core_ready


def _serve() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    api_cmd = [
        PYTHON,
        "-m",
        "uvicorn",
        "cbr.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    ui_cmd = [
        PYTHON,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "app" / "dashboard.py"),
        "--server.port",
        "8501",
    ]
    print("启动 API / UI（Ctrl+C 退出）…")
    processes = [
        subprocess.Popen(api_cmd, cwd=str(ROOT), env=env),
        subprocess.Popen(ui_cmd, cwd=str(ROOT), env=env),
    ]
    try:
        while True:
            time.sleep(1.0)
            for process in processes:
                if process.poll() is not None:
                    code = process.returncode
                    print(f"子进程退出（code={code}），停止其余进程。")
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("正在停止…")
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBR-MAW 演示入口：环境自检 / 启动 API+UI")
    parser.add_argument("--open", action="store_true", help="自检后打开驾驶台与 API 文档")
    parser.add_argument("--serve", action="store_true", help="后台启动 uvicorn + streamlit（Ctrl+C 退出）")
    args = parser.parse_args(argv)

    ready = _print_status()
    if args.serve:
        return _serve()
    if args.open:
        import webbrowser

        print(f"打开 {UI_URL} 与 {API_URL} …")
        webbrowser.open(UI_URL)
        webbrowser.open(API_URL)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
