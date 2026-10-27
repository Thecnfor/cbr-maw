"""CBR-MAW FastAPI 应用（L6 决策支持与演示层）。

启动方式::

    set PYTHONPATH=src
    .venv\\Scripts\\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000

端点：
- ``GET  /api/health``                服务/LLM/数据源/核心模块就绪状态（永远 200）
- ``GET  /api/scenarios``             历史压力情景列表
- ``GET  /api/decision``              生成一次多智能体预警决策（DecisionCard）
- ``GET  /api/decision/stream``       同上，SSE 流式推送 run/stage/trace/decision（见 streaming.py）
- ``POST /api/chat``                  自然语言对话（ChatRequest -> ChatResponse）
- ``POST /api/chat/stream``           同上，SSE 流式推送 run/stage/trace/chat
- ``GET  /api/evidence/{evidence_id}`` 证据详情
- ``GET  /api/data-cards``            数据卡（序列口径/时点可得性）
- ``GET  /api/trace/{run_id}``        审计轨迹事件列表

降级约定：核心模块（data/knowledge/tools/llm/orchestration）未就绪或执行失败时，
业务端点统一返回 **503 + 中文说明**；本模块在 import 阶段不加载任何核心实现模块，
因此 ``uvicorn`` 可以在核心未完成时正常启动。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cbr.api import readiness, state
from cbr.api.ingest import router as ingest_router
from cbr.api.streaming import router as streaming_router
from cbr.schemas import (
    ChatRequest,
    ChatResponse,
    DataCard,
    DecisionCard,
    Evidence,
    Scenario,
    TraceEvent,
)

API_VERSION = "2.0.0"
MODE_LITERAL = Literal["collaborative", "independent", "single"]

# React 前端（web/dist）静态托管路径；不存在时 API 仍可用，根路径回退为 JSON 说明。
ROOT_DIR = Path(__file__).resolve().parents[3]
WEB_DIST = Path(os.environ.get("CBR_WEB_DIST", str(ROOT_DIR / "web" / "dist")))

# 决策结果短时缓存：避免前端刷新/切换页签时重复调用真实 LLM（成本与延迟）。
# 键 = (as_of, mode, scenario)；TTL 默认 30 分钟，可用 CBR_DECISION_CACHE_TTL 覆盖。
_DECISION_CACHE: dict[tuple[str, str, str], tuple[float, DecisionCard]] = {}
_DECISION_CACHE_TTL = float(os.environ.get("CBR_DECISION_CACHE_TTL", "1800"))


def _decision_cache_key(as_of: dt.date, mode: str, scenario: str | None) -> tuple[str, str, str]:
    return (as_of.isoformat(), mode, scenario or "")


def _decision_cache_get(key: tuple[str, str, str]) -> DecisionCard | None:
    item = _DECISION_CACHE.get(key)
    if item is None:
        return None
    ts, card = item
    if time.time() - ts > _DECISION_CACHE_TTL:
        _DECISION_CACHE.pop(key, None)
        return None
    return card


def _decision_cache_put(key: tuple[str, str, str], card: DecisionCard) -> None:
    _DECISION_CACHE[key] = (time.time(), card)


def clear_decision_cache() -> None:
    """清空决策缓存（测试/演示时强制重新生成时使用）。"""
    _DECISION_CACHE.clear()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：按配置启动/停止实时抓取后台调度器（失败不影响主流程）。"""
    try:
        from cbr.ingest.runtime import start_if_enabled

        start_if_enabled()
    except Exception as exc:  # noqa: BLE001 - 调度器失败不阻断 API 启动
        logging.getLogger(__name__).warning("实时抓取调度器启动失败: %s", exc)
    try:
        yield
    finally:
        try:
            from cbr.ingest.runtime import stop_scheduler

            stop_scheduler()
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(
    title="CBR-MAW API",
    version=API_VERSION,
    description=(
        "跨境金融风险多智能体协同预警系统（CBR-MAW）后端 API。"
        "核心模块未就绪时业务端点返回 503 中文提示；就绪状态见 /api/health。"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8501",
        "http://localhost:8501",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _service_or_503() -> Any:
    """获取服务单例；核心未就绪时抛 503（中文说明，含待实现模块清单）。"""
    service, error = readiness.acquire_service()
    if service is None:
        raise HTTPException(status_code=503, detail=readiness.not_ready_message(error))
    return service


def _call_core(action: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    """执行核心模块调用；任何异常都转成 503，绝不裸 500。"""
    try:
        return func(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 核心执行失败统一降级
        raise HTTPException(
            status_code=503,
            detail=(
                f"核心服务执行失败（{action}）：{type(exc).__name__}: {exc}。"
                "请查看服务日志与 /api/health 确认模块状态。"
            ),
        ) from exc


def _coerce(model: Any, raw: Any, action: str) -> Any:
    """把编排层返回值校验为契约模型；不合约同样降级为 503。"""
    if isinstance(raw, model):
        return raw
    try:
        return model.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"编排层返回的{action}不符合 schemas.py 契约：{type(exc).__name__}: {exc}",
        ) from exc


def _scenarios_of(service: Any) -> list[Scenario]:
    """优先使用服务装配的场景，其次回退到 configs/scenarios.yaml。"""
    if service is not None:
        try:
            scenarios = service.available_scenarios()
            if scenarios:
                return [item if isinstance(item, Scenario) else Scenario.model_validate(item) for item in scenarios]
        except Exception:  # noqa: BLE001 - 回退配置
            pass
    try:
        from cbr.config import load_scenarios

        return load_scenarios()
    except Exception:  # noqa: BLE001
        return []


def _default_as_of(service: Any, scenario: str | None) -> dt.date:
    """缺省分析时点：优先匹配场景日期，其次最近场景，最后今天。"""
    scenarios = _scenarios_of(service)
    if scenario:
        for item in scenarios:
            if item.scenario_id == scenario:
                return item.as_of
    if scenarios:
        return scenarios[-1].as_of
    return dt.date.today()


# --------------------------------------------------------------------------- #
# 全局异常处理：任何情况下都返回结构化 JSON（中文提示）
# --------------------------------------------------------------------------- #
@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(_request: Any, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "请求参数校验失败",
            "errors": jsonable_encoder(exc.errors()),
            "hint": "日期格式应为 YYYY-MM-DD；mode 取值 collaborative|independent|single。",
        },
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request: Any, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"服务内部错误：{type(exc).__name__}: {exc}",
            "hint": "本错误已被捕获（非裸崩）；请查看服务日志，并访问 /api/health 确认核心模块状态。",
        },
    )


# --------------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index() -> Any:
    """有 React 构建产物时跳转到驾驶台 /ui/；否则返回 API 入口说明。"""
    if WEB_DIST.is_dir() and (WEB_DIST / "index.html").exists():
        return RedirectResponse(url="/ui/", status_code=307)
    return {
        "name": "CBR-MAW API",
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/api/health",
        "ui": "未找到 web/dist（运行 bun run build 后可通过 /ui/ 访问 React 驾驶台）",
        "endpoints": [
            "GET /api/health",
            "GET /api/scenarios",
            "GET /api/decision?as_of=YYYY-MM-DD&scenario=&mode=collaborative|independent|single",
            "GET /api/decision/stream?as_of=YYYY-MM-DD&scenario=&mode=collaborative|independent|single",
            "POST /api/chat",
            "POST /api/chat/stream",
            "GET /api/evidence/{evidence_id}",
            "GET /api/data-cards",
            "GET /api/trace/{run_id}",
        ],
    }


@app.get("/api/health", tags=["系统"], summary="健康检查（LLM/数据源/核心模块）")
def health() -> dict[str, Any]:
    """健康检查：永远返回 200，用 ``status`` 区分 ok / degraded。"""
    summary = readiness.readiness_summary()
    settings = readiness.settings_snapshot()
    service, service_error = readiness.acquire_service()
    service_ready = service is not None

    data_status: dict[str, Any] = {
        "ready": False,
        "provider": None,
        "data_cards": None,
        "orchestrator": None,
    }
    scenario_count = 0
    llm_runtime: dict[str, Any] = {}
    if service_ready:
        provider = getattr(service, "provider", None)
        orchestrator = getattr(service, "orchestrator", None)
        data_status["provider"] = type(provider).__name__ if provider is not None else None
        data_status["orchestrator"] = type(orchestrator).__name__ if orchestrator is not None else None
        data_cards_fn = getattr(provider, "data_cards", None)
        if callable(data_cards_fn):
            try:
                cards = data_cards_fn()
                data_status["data_cards"] = len(cards) if cards is not None else 0
                data_status["ready"] = True
            except Exception as exc:  # noqa: BLE001
                data_status["error"] = f"{type(exc).__name__}: {exc}"
        else:
            data_status["error"] = "DataProvider 未实现 data_cards()"
        try:
            scenario_count = len(service.available_scenarios())
        except Exception:  # noqa: BLE001
            scenario_count = 0
        llm = getattr(service, "llm", None)
        if llm is not None:
            llm_runtime["client"] = type(llm).__name__
    else:
        # 核心未就绪时仍报告配置层可用的场景数（前端场景选择器不受影响）
        try:
            scenario_count = len(_scenarios_of(None))
        except Exception:  # noqa: BLE001
            scenario_count = 0
        data_status["error"] = "核心服务未就绪，数据源状态不可用"

    configured_llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    llm_status: dict[str, Any] = {
        "provider": configured_llm.get("provider"),
        "model": configured_llm.get("model"),
        "mock": configured_llm.get("mock"),
    }
    llm_status.update(llm_runtime)

    ingest_status: dict[str, Any] = {"enabled": False}
    try:
        from cbr.config import load_settings as _load_settings

        _settings = getattr(service, "settings", None) or _load_settings()
        ingest_status["enabled"] = bool(_settings.ingest.enabled)
        if _settings.ingest.enabled or service_ready:
            from cbr.api.ingest import ingest_status as _ingest_status_fn

            snapshot = _ingest_status_fn()
            ingest_status.update(
                {
                    "running": snapshot.running,
                    "n_sources": snapshot.n_sources,
                    "n_stale_series": len(snapshot.stale_series),
                    "last_run_at": snapshot.last_run_at.isoformat() if snapshot.last_run_at else None,
                }
            )
    except Exception as exc:  # noqa: BLE001 - 状态附加失败不影响健康检查
        ingest_status["error"] = f"{type(exc).__name__}: {exc}"

    # 以「服务是否装配成功」判定整体状态；模块明细单独在 modules/pending_modules 中给出
    status = "ok" if service_ready else "degraded"
    return {
        "status": status,
        "app": settings.get("app_name", "CBR-MAW") if isinstance(settings, dict) else "CBR-MAW",
        "version": API_VERSION,
        "service_ready": service_ready,
        "service_error": service_error,
        "core_ready": summary["ready"],
        "ready_modules": summary["ready_modules"],
        "pending_modules": summary["pending_modules"],
        "modules": summary["modules"],
        "llm": llm_status,
        "data_sources": data_status,
        "scenarios": scenario_count,
        "ingest": ingest_status,
        "server": settings.get("server", {}) if isinstance(settings, dict) else {},
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@app.get("/api/scenarios", response_model=list[Scenario], tags=["元数据"], summary="历史压力情景列表")
def list_scenarios() -> list[Scenario]:
    """场景来自 configs/scenarios.yaml，核心未就绪时仍可用（便于前端展示）。"""
    service, _error = readiness.acquire_service()
    scenarios = _scenarios_of(service)
    if scenarios:
        return scenarios
    raise HTTPException(
        status_code=503,
        detail="无法读取场景配置 configs/scenarios.yaml，且核心服务未提供场景列表。",
    )


@app.get("/api/decision", response_model=DecisionCard, tags=["决策"], summary="生成多智能体预警决策卡")
def get_decision(
    as_of: dt.date | None = Query(None, description="分析时点 YYYY-MM-DD；缺省取场景日期或最近场景"),
    scenario: str | None = Query(None, description="场景 id（见 /api/scenarios）"),
    mode: MODE_LITERAL = Query("collaborative", description="实验模式：协同/独立/单智能体"),
    refresh: bool = Query(False, description="true 时跳过 30 分钟结果缓存，强制重新生成"),
) -> DecisionCard:
    service = _service_or_503()
    orchestrator = getattr(service, "orchestrator", None)
    run = getattr(orchestrator, "run", None)
    if not callable(run):
        raise HTTPException(
            status_code=503,
            detail="编排层未就绪：Orchestrator 未实现 run(as_of, mode, scenario) 接口（见 contracts.py）。",
        )
    target_date = as_of or _default_as_of(service, scenario)
    cache_key = _decision_cache_key(target_date, mode, scenario)
    if not refresh:
        cached = _decision_cache_get(cache_key)
        if cached is not None:
            return cached
    raw = _call_core(
        "生成预警决策",
        run,
        target_date,
        mode=mode,
        scenario=scenario,
    )
    card = _coerce(DecisionCard, raw, "决策卡")
    state.remember_decision(card)
    _decision_cache_put(cache_key, card)
    return card


@app.post("/api/chat", response_model=ChatResponse, tags=["对话"], summary="自然语言对话入口")
def chat(request: ChatRequest) -> ChatResponse:
    service = _service_or_503()
    orchestrator = getattr(service, "orchestrator", None)
    chat_fn = getattr(orchestrator, "chat", None)
    if not callable(chat_fn):
        raise HTTPException(
            status_code=503,
            detail="编排层未就绪：Orchestrator 未实现 chat(ChatRequest) -> ChatResponse 接口（见 contracts.py）。",
        )
    raw = _call_core("对话推理", chat_fn, request)
    response = _coerce(ChatResponse, raw, "对话响应")
    state.remember_decision(response.decision)
    if response.as_of is None:
        response = response.model_copy(update={"as_of": _default_as_of(service, None)})
    return response


@app.get(
    "/api/evidence/{evidence_id}",
    response_model=Evidence,
    tags=["证据"],
    summary="证据详情（来源/时点/工具版本/输入哈希/内容）",
)
def get_evidence(evidence_id: str) -> Evidence:
    service = _service_or_503()
    evidence = state.find_evidence(service, evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到证据 {evidence_id}：编排层未通过 get_evidence()/黑板暴露该证据，"
                "artifacts 中也没有对应文件。请确认证据 id 或等待本次运行写入黑板。"
            ),
        )
    return evidence


@app.get("/api/data-cards", response_model=list[DataCard], tags=["元数据"], summary="数据卡列表")
def get_data_cards() -> list[DataCard]:
    service = _service_or_503()
    provider = getattr(service, "provider", None)
    data_cards_fn = getattr(provider, "data_cards", None)
    if not callable(data_cards_fn):
        raise HTTPException(
            status_code=503,
            detail="数据层未就绪：DataProvider 未实现 data_cards() 接口（见 contracts.py）。",
        )
    raw_cards = _call_core("读取数据卡", data_cards_fn) or []
    cards: list[DataCard] = []
    for item in raw_cards:
        try:
            cards.append(item if isinstance(item, DataCard) else DataCard.model_validate(item))
        except Exception:  # noqa: BLE001 - 跳过不合契约的单条数据卡，不影响整体
            continue
    return cards


@app.get(
    "/api/trace/{run_id}",
    response_model=list[TraceEvent],
    tags=["审计"],
    summary="审计轨迹事件列表",
)
def get_trace(run_id: str) -> list[TraceEvent]:
    service = _service_or_503()
    events = state.find_trace(service, run_id)
    if events is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"未找到 run_id={run_id} 的审计轨迹：已尝试 orchestrator.get_trace()、"
                "artifacts/traces/<run_id>.jsonl 等约定路径。"
            ),
        )
    return events


# --------------------------------------------------------------------------- #
# 流式端点（SSE）：独立 trace 目录 + 后台线程 tail，实现见 cbr/api/streaming.py
# 保持现有同步端点不变；此处一次性挂载，避免重写既有路由。
# --------------------------------------------------------------------------- #
app.include_router(streaming_router)
app.include_router(ingest_router)


# --------------------------------------------------------------------------- #
# React 前端静态托管（web/dist；由 bun run build 生成）
# --------------------------------------------------------------------------- #
def _mount_web_ui() -> None:
    """存在构建产物时把 /ui 挂载为 React 驾驶台；不存在时保持纯 API 模式。"""
    if not (WEB_DIST.is_dir() and (WEB_DIST / "index.html").exists()):
        return
    app.mount("/ui", StaticFiles(directory=str(WEB_DIST), html=True), name="web-ui")


_mount_web_ui()


def run() -> None:  # pragma: no cover - 手动启动入口
    """``python -m cbr.api.main`` 手动启动（读取 configs/app.yaml server 段）。"""
    import uvicorn

    host, port = "127.0.0.1", 8000
    try:
        from cbr.config import load_settings

        server = load_settings().server
        host, port = server.api_host, server.api_port
    except Exception:  # noqa: BLE001 - 配置读取失败时用默认值
        pass
    uvicorn.run("cbr.api.main:app", host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run()
