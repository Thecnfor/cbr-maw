"""CBR-MAW 智能对话页：自然语言提问 → 协同编排 → 回复 + 引用证据 + 关联决策卡。

- 会话上下文保存在 ``st.session_state``（session_id、历史消息、引用证据、决策卡）；
- 所有异常都转为对话内的友好错误消息，不中断页面；
- 核心服务未就绪时展示与驾驶台一致的模块状态说明。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import streamlit as st

from app import components as C

EXAMPLE_QUESTIONS = (
    "2024-08-05 前后跨境资金流出压力如何？主要驱动因子是什么？",
    "监管、投资、融资三类主体对当前风险的判断有哪些分歧？如何协调？",
    "如果人民币短期贬值 3%，对本组合与融资成本的影响如何？",
)


def _session_id() -> str:
    if "cbr_chat_session_id" not in st.session_state:
        st.session_state["cbr_chat_session_id"] = f"ui-{uuid.uuid4().hex[:12]}"
    return str(st.session_state["cbr_chat_session_id"])


def _call_chat(
    service: Any,
    message: str,
    as_of: dt.date | None,
    mode: str,
    session_id: str,
) -> dict[str, Any]:
    """调用编排层 chat()，并把结果整理成可缓存的会话记录。"""
    try:
        from cbr.schemas import ChatRequest

        orchestrator = getattr(service, "orchestrator", None)
        chat_fn = getattr(orchestrator, "chat", None)
        if not callable(chat_fn):
            return {"error": "编排层未就绪：Orchestrator 未实现 chat(ChatRequest) -> ChatResponse 接口（见 contracts.py）。"}
        request = ChatRequest(
            message=message,
            as_of=as_of,
            session_id=session_id,
            mode=mode if mode in ("collaborative", "independent", "single") else "auto",
        )
        raw = chat_fn(request)
    except Exception as exc:  # noqa: BLE001 - 对话失败不能中断页面
        return {"error": f"{type(exc).__name__}: {exc}"}

    payload = C.to_dict(raw)
    if not payload:
        return {"error": "对话服务返回为空或无法序列化。"}

    decision = payload.get("decision")
    evidences: list[dict] = []
    missing: list[str] = []
    if decision:
        try:
            from cbr.api.state import collect_evidence

            found, missing_ids = collect_evidence(service, decision)
            evidences = [C.to_dict(item) for item in found]
            missing = [str(item) for item in missing_ids]
        except Exception:  # noqa: BLE001 - 证据缺失不影响回复展示
            pass

    return {
        "reply": payload.get("reply") or "（服务未返回回复文本）",
        "as_of": payload.get("as_of") or as_of,
        "citations": payload.get("citations") or [],
        "trace_id": payload.get("trace_id"),
        "decision": decision,
        "evidence": evidences,
        "missing": missing,
    }


def _render_assistant_record(record: dict[str, Any], key_suffix: int | str | None = None) -> None:
    st.markdown(str(record.get("content") or record.get("reply") or ""))
    if record.get("error"):
        st.caption("可点击侧边栏「🔄 重新检测核心模块」后重试，或稍后再试。")
    C.render_citations(record.get("citations") or [])
    if record.get("decision"):
        C.render_decision_compact(record["decision"], key_suffix=key_suffix)
    if record.get("evidence") or record.get("missing"):
        C.render_evidence_brief(record.get("evidence") or [], record.get("missing") or [])
    if record.get("trace_id"):
        st.caption(f"本次对话 trace_id：`{record.get('trace_id')}`")


def render(
    service: Any | None,
    error: str | None,
    readiness: dict[str, Any],
    settings: dict[str, Any],
    controls: dict[str, Any],
) -> None:
    as_of = controls.get("as_of")
    mode = controls.get("mode") or "collaborative"
    st.markdown("## 💬 智能对话")
    st.caption(
        "自然语言提问 → 共享信号 / 工具 / 时点知识库协同推理 → 回复附带引用来源、"
        "关联决策卡与证据编号；会话上下文保存在本页。"
    )
    if service is None:
        st.warning("核心服务尚未就绪，对话功能暂不可用（可先浏览「关于系统」了解演示流程）。")
        C.render_not_ready(error, readiness, settings)
        return

    session_id = _session_id()
    messages: list[dict[str, Any]] = st.session_state.setdefault("cbr_chat_messages", [])

    info_col, clear_col = st.columns([4.2, 1])
    with info_col:
        st.caption(
            f"会话 ID：`{session_id}`　·　as_of：{C.fmt_date(as_of)}　·　"
            f"模式：{C.MODE_LABELS.get(mode, mode)}　·　历史消息 {len(messages)} 条"
        )
    with clear_col:
        if st.button("🧹 清空对话", **C.STRETCH_BUTTON):
            st.session_state["cbr_chat_messages"] = []
            st.session_state["cbr_chat_session_id"] = f"ui-{uuid.uuid4().hex[:12]}"
            st.rerun()

    if not messages:
        st.markdown("**试试这些问题（点击即发送）**")
        columns = st.columns(len(EXAMPLE_QUESTIONS))
        for index, (column, question) in enumerate(zip(columns, EXAMPLE_QUESTIONS)):
            with column:
                if st.button(question, key=f"chat_example_{index}", **C.STRETCH_BUTTON):
                    st.session_state["cbr_chat_pending"] = question
                    st.rerun()
        st.info(
            "提示：对话结果与「风险驾驶台」共享同一套 schemas（ChatResponse.decision 为 DecisionCard），"
            "因此回复会同步展示关联决策卡与引用证据。"
        )

    for index, record in enumerate(messages):
        role = "user" if str(record.get("role")) == "user" else "assistant"
        with st.chat_message(role):
            if role == "user":
                st.markdown(str(record.get("content") or ""))
            else:
                _render_assistant_record(record, key_suffix=index)

    prompt = st.chat_input("输入你的问题，例如：当前跨境资金流出压力如何？")
    pending = st.session_state.pop("cbr_chat_pending", None)
    prompt = prompt or pending
    if not prompt:
        return

    messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("协同编排推理中（共享信号 → 工具 → 证据核验）…"):
            result = _call_chat(service, prompt, as_of, mode, session_id)
        if result.get("error"):
            st.error(f"对话失败：{result['error']}")
            record: dict[str, Any] = {
                "role": "assistant",
                "content": f"对话失败：{result['error']}",
                "error": True,
            }
        else:
            record = {"role": "assistant", **result, "content": result["reply"]}
            _render_assistant_record(record, key_suffix=len(messages))
    messages.append(record)
    st.session_state["cbr_chat_messages"] = messages
    st.rerun()
