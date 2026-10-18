"""CBR-MAW Streamlit 驾驶台主入口。

启动::

    .venv\\Scripts\\python.exe -m streamlit run app/dashboard.py --server.port 8501

页面结构（录屏顺序）：
侧边栏（场景 / as_of / 实验模式 / 系统状态）→ 顶部决策卡信息 → 共享风险信号概览
→ 三智能体卡片 → 协同开销与综合建议 → 页签（风险仪表盘 / 证据板 / 分歧与协调 /
核验与审计 / 数据卡 / 导出）→ 页脚。

核心模块（data/knowledge/tools/llm/orchestration）未就绪时，页面显示清晰的模块装配
状态与启动说明（``components.render_not_ready``），不会白屏或抛出裸异常。
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (str(_ROOT), str(_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import streamlit as st  # noqa: E402

from app import chat as chat_page  # noqa: E402
from app import components as C  # noqa: E402


# --------------------------------------------------------------------------- #
# 服务调用（全部带异常兜底，失败时展示友好错误，不裸崩）
# --------------------------------------------------------------------------- #
def _fetch_decision(
    service: object,
    scenario_id: str | None,
    as_of: dt.date,
    mode: str,
) -> tuple[dict | None, str | None]:
    """调用 orchestrator.run() 生成决策卡（返回 dict 便于渲染与缓存）。"""
    try:
        orchestrator = getattr(service, "orchestrator", None)
        run = getattr(orchestrator, "run", None)
        if not callable(run):
            return None, "编排层未就绪：Orchestrator 未实现 run(as_of, mode, scenario) 接口（见 contracts.py）。"
        raw = run(as_of, mode=mode, scenario=scenario_id)
    except Exception as exc:  # noqa: BLE001 - 页面必须优雅降级
        return None, f"{type(exc).__name__}: {exc}"
    payload = C.to_dict(raw)
    if not payload:
        return None, "编排层返回的决策卡为空或无法序列化。"
    return payload, None


def _collect_aux(service: object, decision: dict, key: str) -> tuple[list[dict], list[str], list[dict]]:
    """收集证据快照 / 未解析引用 / 审计轨迹（带 session 缓存）。"""
    cache = st.session_state.setdefault("cbr_aux_cache", {})
    cached = cache.get(key)
    if cached is not None:
        return cached["evidences"], cached["missing"], cached["trace"]
    evidences: list[dict] = []
    missing: list[str] = []
    trace: list[dict] = []
    try:
        from cbr.api.state import collect_evidence, find_trace

        found, missing_ids = collect_evidence(service, decision)
        evidences = [C.to_dict(item) for item in found]
        missing = [str(item) for item in missing_ids]
        events = find_trace(service, C.get(decision, "run_id"))
        trace = [C.to_dict(item) for item in (events or [])]
    except Exception:  # noqa: BLE001 - 证据/轨迹缺失时页面仍可展示决策卡
        pass
    cache[key] = {"evidences": evidences, "missing": missing, "trace": trace}
    while len(cache) > 8:  # 避免 session_state 无限增长
        cache.pop(next(iter(cache)), None)
    return evidences, missing, trace


def _load_data_cards(service: object) -> list[dict]:
    """读取数据卡（失败返回空列表，由组件给出占位说明）。"""
    try:
        provider = getattr(service, "provider", None)
        data_cards_fn = getattr(provider, "data_cards", None)
        if not callable(data_cards_fn):
            return []
        return [C.to_dict(item) for item in (data_cards_fn() or [])]
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# 驾驶台页面
# --------------------------------------------------------------------------- #
def render_dashboard_page(service: object, settings: dict, controls: dict) -> None:
    as_of: dt.date = controls.get("as_of") or dt.date.today()
    scenario_id = controls.get("scenario_id")
    mode = controls.get("mode") or "collaborative"
    cache_key = f"{scenario_id}|{as_of.isoformat()}|{mode}"

    cache = st.session_state.setdefault("cbr_decision_cache", {})
    if controls.get("generate") or cache.get("key") != cache_key:
        with st.spinner(
            "多智能体协同推理中：R0 独立分析 → R1 证据共享 → R2 交叉验证 → "
            "R3 分歧识别 → R4 协调仲裁 → R5 决策卡…"
        ):
            decision_payload, fetch_error = _fetch_decision(service, scenario_id, as_of, mode)
        cache.clear()
        cache.update(
            {
                "key": cache_key,
                "decision": decision_payload,
                "error": fetch_error,
                "fetched_at": dt.datetime.now().strftime("%H:%M:%S"),
            }
        )

    decision: dict = cache.get("decision") or {}
    error: str | None = cache.get("error")
    if error:
        C.render_error(error, title="生成预警决策失败")
        st.caption("可在 /api/health 查看核心模块状态，或点击侧边栏「🔄 重新检测核心模块」后重试。")
        return
    if not decision:
        st.info("请点击侧边栏「🔮 生成 / 刷新预警」开始。")
        return

    run_id = C.get(decision, "run_id") or ""
    aux_evidences, aux_missing, aux_trace = _collect_aux(service, decision, f"{cache_key}|{run_id}")

    C.render_header(decision, controls, settings)
    C.render_signal_overview(decision.get("signal"))
    C.render_agent_cards(decision)
    C.render_coordination_stats(decision)

    tabs = st.tabs(
        [
            "📊 风险仪表盘",
            "🧾 证据板",
            "⚖️ 分歧与协调",
            "🔍 核验与审计",
            "🗂️ 数据卡",
            "📤 导出",
        ]
    )
    with tabs[0]:
        C.render_signal_charts(decision.get("signal"))
    with tabs[1]:
        C.render_evidence_board(aux_evidences, aux_missing)
    with tabs[2]:
        C.render_conflicts(decision.get("conflicts"))
    with tabs[3]:
        C.render_verification(decision.get("verification"))
        st.markdown('<hr class="cbr-divider" />', unsafe_allow_html=True)
        C.render_trace(aux_trace, decision)
    with tabs[4]:
        C.render_data_cards(_load_data_cards(service))
    with tabs[5]:
        C.render_export(
            decision,
            aux_evidences,
            aux_trace,
            controls.get("scenario_name"),
        )

    fetched_at = cache.get("fetched_at")
    if fetched_at:
        st.caption(f"本次决策生成于 {fetched_at}；切换场景 / 时点 / 模式后将自动重新生成。")
    C.render_page_footer(decision)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main() -> None:
    C.page_config()
    C.inject_css()

    force_reload = bool(st.session_state.pop("cbr_force_reload", False))
    service, error, readiness, settings = C.load_service_state(force=force_reload)
    controls = C.render_sidebar(service, error, readiness, settings)
    page = controls.get("page")

    if page == C.PAGE_CHAT:
        chat_page.render(service, error, readiness, settings, controls)
        C.render_page_footer()
        return
    if page == C.PAGE_ABOUT:
        C.render_about(readiness, settings)
        C.render_page_footer()
        return

    if service is None:
        C.render_not_ready(error, readiness, settings)
        C.render_page_footer()
        return

    try:
        render_dashboard_page(service, settings, controls)
    except Exception as exc:  # noqa: BLE001 - 渲染兜底：捕获后友好展示，绝不白屏
        st.error("页面渲染出现异常，已捕获并降级展示（不影响 API 服务）。")
        st.caption(f"{type(exc).__name__}: {exc}")
        with st.expander("异常详情（供排障）", expanded=False):
            st.exception(exc)


if __name__ == "__main__":
    main()
