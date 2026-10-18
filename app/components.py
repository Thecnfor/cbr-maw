"""CBR-MAW Streamlit 界面组件库（中文、浅色主题、录屏友好）。

设计原则：
- **只消费 schemas.py 已定义字段**，并以 dict 形式渲染，任何字段缺失都退化为「—」，
  不抛异常（向后兼容核心模块演进）；
- 所有动态文本进入 HTML 前做转义，避免证据/文本内容破坏页面；
- 图表统一使用 Plotly（白底、紧凑布局，适合一屏展示与录屏）；
- 本模块不 import 核心实现模块（data/tools/…），只通过传入的 service 对象交互，
  核心未就绪时由 ``render_not_ready`` 给出清晰提示。
"""

from __future__ import annotations

import datetime as dt
import html
import inspect
import json
from typing import Any, Iterable, Mapping

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------- #
# 常量与配色（浅色主题，风险等级：红/橙/黄/绿）
# --------------------------------------------------------------------------- #
RISK_META: dict[str, dict[str, str]] = {
    "critical": {"label": "极高", "color": "#C0392B", "bg": "#FDEDEC", "icon": "🔴"},
    "high": {"label": "高", "color": "#E67E22", "bg": "#FEF5E7", "icon": "🟠"},
    "medium": {"label": "中", "color": "#B7950B", "bg": "#FCF3CF", "icon": "🟡"},
    "low": {"label": "低", "color": "#1E8449", "bg": "#E9F7EF", "icon": "🟢"},
}
RISK_UNKNOWN = {"label": "未知", "color": "#7F8C8D", "bg": "#F2F4F4", "icon": "⚪"}

ROLE_META: dict[str, dict[str, str]] = {
    "regulator": {"label": "监管主体", "icon": "🛡️", "focus": "系统性风险 / 跨市场外溢"},
    "investor": {"label": "投资主体", "icon": "📈", "focus": "组合尾部损失 / 对冲"},
    "financing": {"label": "融资主体", "icon": "🏦", "focus": "融资成本 / 现金流"},
    "coordinator": {"label": "协调者", "icon": "🧭", "focus": "冲突仲裁 / 决策卡"},
    "verifier": {"label": "核验者", "icon": "🔍", "focus": "数值 / 引文 / 时点核验"},
}
ROLE_ORDER = ("regulator", "investor", "financing")

MODE_LABELS = {
    "collaborative": "协同模式（完整系统）",
    "independent": "独立模式（无共享）",
    "single": "单智能体模式",
    "auto": "自动",
}
MODE_SHORT = {
    "collaborative": "协同",
    "independent": "独立",
    "single": "单智能体",
    "auto": "自动",
}

CONFLICT_TYPE_META = {
    "fact": {"label": "事实冲突", "color": "#C0392B"},
    "directional": {"label": "方向冲突", "color": "#E67E22"},
    "preference": {"label": "偏好差异", "color": "#2980B9"},
}
SEVERITY_META = {
    "high": {"label": "高", "color": "#C0392B"},
    "medium": {"label": "中", "color": "#E67E22"},
    "low": {"label": "低", "color": "#7F8C8D"},
}
RESOLVED_BY_LABELS = {
    "tool": "工具复核",
    "authority": "权威裁定",
    "human": "人工介入",
    "consensus": "共识收敛",
    "unresolved": "未解决",
}
EVIDENCE_KIND_META = {
    "signal": {"label": "风险信号", "icon": "📊"},
    "tool": {"label": "工具输出", "icon": "🔧"},
    "kb": {"label": "知识库", "icon": "📚"},
    "market": {"label": "行情快照", "icon": "💹"},
    "policy": {"label": "政策文本", "icon": "📜"},
}
CLAIM_STATUS_LABELS = {
    "unverified": "待核验",
    "verified": "已核验",
    "conflicted": "有冲突",
    "rejected": "已驳回",
    "preference": "偏好差异",
}
CLAIM_TYPE_LABELS = {"numeric": "数值主张", "text": "文本主张", "directional": "方向判断"}
ISSUE_TYPE_LABELS = {
    "numeric": "数值核验",
    "citation": "引文核验",
    "leakage": "时点泄漏",
    "permission": "越权调用",
    "schema": "Schema 校验",
    "unsupported": "无依据断言",
}
ACTION_LABELS = {
    "signal": "读取共享信号",
    "tool_call": "工具调用",
    "llm_call": "LLM 调用",
    "claim": "形成主张",
    "conflict": "冲突检测",
    "verify": "核验",
    "hitl": "人工介入",
    "finalize": "决策卡定稿",
}
PIT_LABELS = {"strict": "严格可得", "approximate": "近似可得", "unavailable": "不可得"}

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

#: 审计轨迹动作配色（用于 trace 时间线散点）
ACTION_COLORS = {
    "signal": "#1F618D",
    "tool_call": "#8E44AD",
    "llm_call": "#16A085",
    "claim": "#D68910",
    "conflict": "#C0392B",
    "verify": "#1E8449",
    "hitl": "#B03A2E",
    "finalize": "#154360",
    "run_start": "#7F8C8D",
    "analysis_start": "#95A5A6",
    "analysis_done": "#5D6D7E",
    "evidence_share": "#2E86C1",
    "evidence_dedup": "#5499C7",
    "cross_validate": "#48C9B0",
    "agent_error": "#922B21",
    "budget_exceeded": "#AF601A",
}


def _stretch_kwargs(func: Any) -> dict[str, Any]:
    """兼容新旧 Streamlit：新版本用 ``width="stretch"``，旧版本回退 ``use_container_width=True``。"""
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover
        return {"use_container_width": True}
    if "width" in parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


#: 各元素「占满可用宽度」参数的版本适配副本（避免旧版 Streamlit 参数错误、新版弃用告警）
STRETCH_PLOTLY = _stretch_kwargs(st.plotly_chart)
STRETCH_DATAFRAME = _stretch_kwargs(st.dataframe)
STRETCH_BUTTON = _stretch_kwargs(st.button)
STRETCH_DOWNLOAD = _stretch_kwargs(st.download_button)
PAGE_DASHBOARD = "🛰️ 风险驾驶台"
PAGE_CHAT = "💬 智能对话"
PAGE_ABOUT = "📖 关于系统"
PAGES = [PAGE_DASHBOARD, PAGE_CHAT, PAGE_ABOUT]

_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'


# --------------------------------------------------------------------------- #
# 通用安全取值 / 格式化
# --------------------------------------------------------------------------- #
def to_dict(obj: Any) -> dict[str, Any]:
    """pydantic 模型 / Mapping -> JSON 安全 dict（失败返回空 dict）。"""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:  # pragma: no cover
            try:
                return dump()
            except Exception:  # noqa: BLE001
                return {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def get(obj: Any, *keys: str, default: Any = None) -> Any:
    """安全嵌套取值：``get(card, "signal", "level")``。"""
    current: Any = obj
    for key in keys:
        current = to_dict(current)
        if key not in current:
            return default
        current = current[key]
        if current is None:
            return default
    return current


def _esc(value: Any, default: str = "") -> str:
    """HTML 转义（用于 f-string 注入）。"""
    text = default if value is None else str(value)
    return html.escape(text, quote=False)


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def fmt_date(value: Any) -> str:
    parsed = _to_date(value)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    return text[:10] if text else "—"


def _to_local(value: dt.datetime) -> dt.datetime:
    """带时区的 datetime 转本地时区（展示用）；naive 时间原样返回。"""
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone()
    except (OSError, ValueError, OverflowError):  # pragma: no cover - 极端时区异常
        return value


def fmt_datetime(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return _to_local(value).strftime("%Y-%m-%d %H:%M")
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        return _to_local(dt.datetime.fromisoformat(text.replace("Z", "+00:00"))).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def _parse_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return _to_local(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _to_local(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def fmt_pct(value: Any, digits: int = 1, *, ratio: bool = True) -> str:
    """比率（0-1）格式化为百分比；无法解析返回「—」。"""
    number = _to_float(value)
    if number is None:
        return "—"
    if ratio and abs(number) <= 1.0:
        number *= 100.0
    return f"{number:.{digits}f}%"


def fmt_num(value: Any, digits: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        if isinstance(value, str) and value.strip():
            return value
        return "—"
    return f"{number:,.{digits}f}"


def fmt_metric_value(value: Any, unit: Any = None) -> str:
    unit_text = str(unit or "").strip()
    number = _to_float(value)
    if number is None:
        if isinstance(value, str) and value.strip():
            return value
        return "—"
    if unit_text.lower() in {"ratio", "prob", "probability", "%"}:
        return fmt_pct(number)
    if unit_text in {"bp", "bp.", "基点"}:
        return f"{number:,.0f} bp"
    if unit_text:
        return f"{fmt_num(number)} {unit_text}"
    return fmt_num(number)


def _enum_str(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).strip().lower()


def risk_meta(level: Any) -> dict[str, str]:
    key = _enum_str(level)
    meta = RISK_META.get(key)
    if meta is not None:
        return meta
    if key:
        return {**RISK_UNKNOWN, "label": key}
    return RISK_UNKNOWN


def role_meta(role: Any) -> dict[str, str]:
    key = _enum_str(role)
    return ROLE_META.get(key, {"label": key or "未知主体", "icon": "👤", "focus": ""})


def evidence_kind_meta(kind: Any) -> dict[str, str]:
    key = _enum_str(kind)
    return EVIDENCE_KIND_META.get(key, {"label": key or "其他证据", "icon": "📎"})


def chip(text: Any, color: str, bg: str, icon: str = "") -> str:
    """HTML 徽章（返回字符串，供 st.markdown 使用）。"""
    prefix = f"{icon} " if icon else ""
    return (
        f'<span class="cbr-chip" style="color:{color};background:{bg};'
        f'border-color:{color}33;">{prefix}{_esc(text)}</span>'
    )


def risk_chip(level: Any) -> str:
    meta = risk_meta(level)
    return chip(meta["label"], meta["color"], meta["bg"], meta["icon"])


def _prob_color(prob: float | None) -> str:
    if prob is None:
        return "#AAB7B8"
    if prob >= 0.6:
        return "#C0392B"
    if prob >= 0.4:
        return "#E67E22"
    if prob >= 0.2:
        return "#D4AC0D"
    return "#1E8449"


def _horizons(value: Any) -> dict[int, float | None]:
    raw = to_dict(value) if not isinstance(value, Mapping) else dict(value)
    parsed: dict[int, float | None] = {}
    for key, item in raw.items():
        try:
            horizon = int(key)
        except (TypeError, ValueError):
            continue
        parsed[horizon] = _to_float(item)
    return parsed


def _avg_confidence(claims: Iterable[Any]) -> float | None:
    values = []
    for claim in claims or []:
        number = _to_float(get(claim, "confidence"))
        if number is not None:
            values.append(number)
    return sum(values) / len(values) if values else None


def _shorten(text: Any, limit: int = 420) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n…（已截断，共 {len(value)} 字符）"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)


# --------------------------------------------------------------------------- #
# 页面基础：主题 / 状态加载
# --------------------------------------------------------------------------- #
_CSS = f"""
<style>
:root {{
  --cbr-ink: #1B2631; --cbr-muted: #5D6D7E; --cbr-line: #E5EAF0;
  --cbr-bg: #F6F8FB; --cbr-accent: #1F618D;
}}
html, body, [data-testid="stAppViewContainer"] {{
  font-family: {_FONT};
  color: var(--cbr-ink);
}}
.stApp {{ background: linear-gradient(180deg, #F6F8FB 0%, #F1F5F9 100%); }}
[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid var(--cbr-line); }}
[data-testid="stHeader"] {{ background: rgba(246,248,251,.82); backdrop-filter: blur(6px); }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1500px; }}
h1, h2, h3, h4 {{ color: var(--cbr-ink); letter-spacing: .2px; }}
.cbr-hero {{
  background: linear-gradient(135deg, #FFFFFF 0%, #F2F7FC 100%);
  border: 1px solid var(--cbr-line); border-radius: 16px;
  padding: 16px 20px; box-shadow: 0 2px 10px rgba(21,67,96,.05);
}}
.cbr-chip {{
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 10px; border-radius: 999px; font-size: 12.5px;
  font-weight: 600; border: 1px solid transparent; margin: 2px 4px 2px 0;
  white-space: nowrap;
}}
.cbr-muted {{ color: var(--cbr-muted); font-size: 12.5px; }}
.cbr-card {{
  background: #FFFFFF; border: 1px solid var(--cbr-line); border-radius: 14px;
  padding: 14px 16px; box-shadow: 0 2px 8px rgba(21,67,96,.04); margin-bottom: 10px;
}}
.cbr-agent-head {{
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px dashed var(--cbr-line); padding-bottom: 8px; margin-bottom: 8px;
  font-size: 15.5px; font-weight: 700;
}}
.cbr-kv {{ display: grid; grid-template-columns: 92px 1fr; gap: 4px 10px; font-size: 13px; }}
.cbr-kv .k {{ color: var(--cbr-muted); }}
.cbr-kv .v {{ color: var(--cbr-ink); word-break: break-all; }}
.cbr-section-title {{
  font-size: 17px; font-weight: 800; margin: 4px 0 10px 0; color: #154360;
  display: flex; align-items: center; gap: 6px;
}}
.cbr-risk-banner {{
  border-radius: 14px; padding: 12px 16px; border: 1px solid var(--cbr-line);
  background: #FFFFFF; box-shadow: 0 2px 8px rgba(21,67,96,.04);
}}
.cbr-risk-banner .level {{ font-size: 25px; font-weight: 800; line-height: 1.15; }}
.cbr-divider {{ height: 1px; background: var(--cbr-line); margin: 14px 0; border: 0; }}
[data-testid="stMetricValue"] {{ font-size: 21px; }}
[data-testid="stExpander"] {{ background: #FFFFFF; border: 1px solid var(--cbr-line); border-radius: 12px; }}
.stButton > button, .stDownloadButton > button {{ border-radius: 10px; }}
div[data-testid="stTabs"] button {{ font-weight: 600; }}
footer {{ visibility: hidden; }}
</style>
"""


def page_config() -> None:
    """统一页面配置（必须在首个 Streamlit 命令前调用）。"""
    st.set_page_config(
        page_title="CBR-MAW · 跨境金融风险预警驾驶台",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def load_service_state(force: bool = False) -> tuple[Any | None, str | None, dict[str, Any], dict[str, Any]]:
    """获取服务单例与就绪状态（返回 ``(service, error, readiness, settings)``）。"""
    try:
        from cbr.api.readiness import acquire_service, readiness_summary, settings_snapshot
    except Exception as exc:  # noqa: BLE001 - 连探测模块都不可用时仍给出友好提示
        return None, f"{type(exc).__name__}: {exc}", {"ready": False, "modules": [], "pending_modules": []}, {}
    if force:
        try:
            from cbr.service import reset_service

            reset_service()
        except Exception:  # noqa: BLE001
            pass
    service, error = acquire_service()
    try:
        readiness = readiness_summary()
    except Exception:  # noqa: BLE001
        readiness = {"ready": False, "modules": [], "pending_modules": []}
    try:
        settings = settings_snapshot()
    except Exception:  # noqa: BLE001
        settings = {}
    return service, error, readiness, settings


def load_scenarios(service: Any | None = None) -> list[dict[str, Any]]:
    """场景列表：优先服务装配结果，回退 configs/scenarios.yaml。"""
    if service is not None:
        try:
            items = service.available_scenarios()
            if items:
                return [to_dict(item) for item in items]
        except Exception:  # noqa: BLE001
            pass
    try:
        from cbr.config import load_scenarios as _load_scenarios

        return [to_dict(item) for item in _load_scenarios()]
    except Exception:  # noqa: BLE001
        return []


def not_ready_hint(error: str | None = None) -> str:
    try:
        from cbr.api.readiness import not_ready_message

        return not_ready_message(error)
    except Exception:  # noqa: BLE001
        return "CBR-MAW 核心服务暂未就绪，请稍后重试并检查服务日志。"


# --------------------------------------------------------------------------- #
# 侧边栏
# --------------------------------------------------------------------------- #
def render_sidebar(
    service: Any | None,
    error: str | None,
    readiness: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """渲染统一侧边栏（功能页 / 场景 / as_of / 模式 / 系统状态），返回控制参数。"""
    scenarios = load_scenarios(service)
    with st.sidebar:
        st.markdown("## 🛰️ CBR-MAW")
        st.caption("跨境金融风险多智能体协同预警系统")
        page = st.radio("功能页面", PAGES, index=0, label_visibility="collapsed")
        st.markdown('<hr class="cbr-divider" />', unsafe_allow_html=True)

        scenario_id: str | None = None
        scenario_name = ""
        scenario_desc = ""
        default_as_of = dt.date.today()
        if scenarios:
            labels: list[str] = []
            name_to_scenario: dict[str, dict[str, Any]] = {}
            for item in scenarios:
                label = str(item.get("name") or item.get("scenario_id") or "未命名场景")
                if label in name_to_scenario:
                    label = f"{label}（{item.get('scenario_id')}）"
                labels.append(label)
                name_to_scenario[label] = item
            st.markdown("**演示场景**")
            chosen_label = st.selectbox(
                "历史压力情景", labels, index=0, label_visibility="collapsed"
            )
            scenario = name_to_scenario.get(chosen_label, {})
            scenario_id = str(scenario.get("scenario_id") or "") or None
            scenario_name = str(scenario.get("name") or scenario_id or "")
            scenario_desc = str(scenario.get("description") or "")
            default_as_of = _to_date(scenario.get("as_of")) or dt.date.today()
            if scenario_desc:
                st.caption(scenario_desc)
        else:
            st.info("未读取到 configs/scenarios.yaml 中的演示场景。")

        st.markdown("**分析时点（Point-in-Time）**")
        as_of_value = st.date_input(
            "分析时点",
            value=default_as_of,
            min_value=dt.date(2005, 1, 1),
            max_value=dt.date.today() + dt.timedelta(days=1),
            format="YYYY-MM-DD",
            label_visibility="collapsed",
            key=f"cbr_as_of_{scenario_id or 'default'}",  # 切换场景时自动回到该场景时点
        )
        as_of = as_of_value if isinstance(as_of_value, dt.date) else default_as_of
        st.caption("系统仅使用该时点可得的信息重新生成预警，杜绝未来数据泄漏。")

        st.markdown("**实验模式（消融对照）**")
        mode_label = st.radio(
            "实验模式",
            ["协同模式（完整系统）", "独立模式（无共享）", "单智能体模式"],
            index=0,
            label_visibility="collapsed",
        )
        mode = {
            "协同模式（完整系统）": "collaborative",
            "独立模式（无共享）": "independent",
            "单智能体模式": "single",
        }[mode_label]

        st.markdown('<hr class="cbr-divider" />', unsafe_allow_html=True)
        generate = st.button(
            "🔮 生成 / 刷新预警",
            type="primary",
            **STRETCH_BUTTON,
            disabled=service is None,
        )
        if st.button("🔄 重新检测核心模块", **STRETCH_BUTTON):
            st.session_state["cbr_force_reload"] = True
            st.rerun()

        st.markdown('<hr class="cbr-divider" />', unsafe_allow_html=True)
        _render_sidebar_status(service, error, readiness, settings)

    return {
        "page": page,
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "scenario_desc": scenario_desc,
        "as_of": as_of,
        "mode": mode,
        "generate": generate,
        "scenarios": scenarios,
    }


def _render_sidebar_status(
    service: Any | None,
    error: str | None,
    readiness: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    st.markdown("**系统状态**")
    if service is not None:
        st.markdown(
            chip("核心服务已就绪", "#1E8449", "#E9F7EF", "✅"), unsafe_allow_html=True
        )
    else:
        st.markdown(
            chip("核心服务未就绪", "#C0392B", "#FDEDEC", "⛔"), unsafe_allow_html=True
        )
    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    if isinstance(llm, dict) and llm:
        mode_text = "mock 模式" if llm.get("mock") else "真实调用"
        st.caption(f"LLM：{llm.get('provider') or '—'} / {llm.get('model') or '—'}（{mode_text}）")
    pending = readiness.get("pending_modules") or []
    if pending:
        st.caption("待就绪模块：" + "、".join(str(m).replace("cbr.", "") for m in pending))
    if error:
        with st.expander("就绪错误详情", expanded=False):
            st.code(str(error), language="text")


# --------------------------------------------------------------------------- #
# 未就绪 / 错误态
# --------------------------------------------------------------------------- #
def render_not_ready(
    error: str | None,
    readiness: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    """核心模块未就绪时的友好说明页（绝不白屏/裸崩）。"""
    st.markdown("## ⚠️ 核心服务尚未就绪 · 界面已优雅降级")
    st.warning(not_ready_hint(error))
    st.caption(
        "接口与界面无需修改：核心模块（data/knowledge/tools/llm/orchestration）"
        "按 `src/cbr/service.py` 的装配约定提供工厂函数并重启即可自动生效。"
    )

    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    if isinstance(llm, dict) and llm:
        st.caption(
            f"LLM 配置：{llm.get('provider') or '—'} / {llm.get('model') or '—'}"
            f"（{'mock 模式' if llm.get('mock') else '真实调用'}）"
        )

    st.markdown('<div class="cbr-section-title">🧩 核心模块装配状态</div>', unsafe_allow_html=True)
    modules = readiness.get("modules") or []
    if modules:
        rows = []
        for item in modules:
            module = item.get("module") if isinstance(item, dict) else item
            factory = item.get("factory") if isinstance(item, dict) else ""
            ready = bool(item.get("ready")) if isinstance(item, dict) else False
            detail = item.get("detail") if isinstance(item, dict) else ""
            rows.append(
                {
                    "核心模块": module,
                    "需实现工厂函数": factory,
                    "状态": "✅ 就绪" if ready else "⏳ 未就绪",
                    "说明": detail or ("已暴露约定工厂函数" if ready else "模块尚未创建或缺少工厂函数"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH_DATAFRAME)
    else:
        st.info("模块就绪探测不可用，请直接查看服务日志。")

    st.markdown('<div class="cbr-section-title">▶️ 就绪后本页可完成的演示流程</div>', unsafe_allow_html=True)
    st.markdown(
        "1. **选择场景 / 时点** → 2. **查看风险信号**（5/10/20 日概率、历史分位、归因） → "
        "3. **三智能体卡片**（监管 / 投资 / 融资） → 4. **证据板**（来源 / 时点 / 工具版本 / 输入哈希） → "
        "5. **分歧与协调** → 6. **核验与审计 trace** → 7. **导出 Markdown / JSON 预警简报**"
    )
    st.markdown("**启动命令（在项目根目录）**")
    st.code(
        "set PYTHONPATH=src\n"
        ".venv\\Scripts\\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000\n"
        ".venv\\Scripts\\python.exe -m streamlit run app/dashboard.py --server.port 8501",
        language="bat",
    )
    st.info(
        f"此前 API 已可启动：`GET /api/health` 返回 `status=degraded`，业务端点返回 503 中文提示"
        f"（浏览器打开 http://127.0.0.1:8000/docs 查看）。当前进程错误：{error or '—'}"
    )


def render_error(message: str, *, title: str = "本次操作失败") -> None:
    """业务异常的友好展示（不抛异常、不白屏）。"""
    st.error(f"{title}：{message}")
    st.caption(
        "可点击侧边栏「🔄 重新检测核心模块」或稍后重试；"
        "接口状态见 `GET /api/health`，审计与错误细节见服务日志。"
    )


# --------------------------------------------------------------------------- #
# 顶部信息与信号概览
# --------------------------------------------------------------------------- #
def render_header(decision: dict[str, Any], controls: dict[str, Any], settings: dict[str, Any]) -> None:
    decision = to_dict(decision)
    signal = to_dict(decision.get("signal"))
    scenario_name = controls.get("scenario_name") or decision.get("scenario") or "—"
    mode = _enum_str(decision.get("mode")) or controls.get("mode") or "collaborative"
    verification = to_dict(decision.get("verification"))
    conflicts = decision.get("conflicts") or []
    unresolved = [c for c in conflicts if not to_dict(c).get("resolved")]
    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    llm_text = f"mock · {llm.get('model') or '—'}" if llm.get("mock") else f"{llm.get('provider') or '—'} · {llm.get('model') or '—'}"

    verify_chip = (
        chip("核验通过", "#1E8449", "#E9F7EF", "✅")
        if verification.get("passed") is True
        else chip("核验存在异常", "#C0392B", "#FDEDEC", "⚠️")
        if verification.get("passed") is False
        else chip("核验报告缺失", "#7F8C8D", "#F2F4F4", "➖")
    )
    conflict_chip = (
        chip(
            f"未解决冲突 {len(unresolved)}",
            "#C0392B" if unresolved else "#1E8449",
            "#FDEDEC" if unresolved else "#E9F7EF",
            "⚖️",
        )
    )
    st.markdown(
        f"""
        <div class="cbr-hero">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap;">
            <div>
              <div style="font-size:22px;font-weight:800;color:#154360;">跨境金融风险协同预警驾驶台</div>
              <div class="cbr-muted" style="margin-top:6px;">
                场景：{_esc(scenario_name)}　·　时点：{fmt_date(decision.get("as_of") or controls.get("as_of"))}　·　
                模式：{_esc(MODE_LABELS.get(mode, mode))}　·　run_id：<code>{_esc(decision.get("run_id") or "—")}</code>
              </div>
            </div>
            <div style="text-align:right;max-width:520px;">
              {chip("综合风险 " + risk_meta(signal.get("level"))["label"], risk_meta(signal.get("level"))["color"], risk_meta(signal.get("level"))["bg"], risk_meta(signal.get("level"))["icon"])}
              {verify_chip}
              {conflict_chip}
              <div class="cbr-muted" style="margin-top:6px;">LLM：{_esc(llm_text)}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_signal_overview(signal: Any) -> None:
    """共享风险信号一屏概览：等级 / 5-10-20 日概率 / 历史分位。"""
    signal = to_dict(signal)
    st.markdown('<div class="cbr-section-title">📡 共享风险信号（P1 多模态融合）</div>', unsafe_allow_html=True)
    meta = risk_meta(signal.get("level"))
    horizons = _horizons(signal.get("horizons"))
    cols = st.columns([1.5, 1, 1, 1, 1.2])
    with cols[0]:
        st.markdown(
            f"""
            <div class="cbr-risk-banner" style="border-left:6px solid {meta['color']};">
              <div class="cbr-muted">综合风险等级</div>
              <div class="level" style="color:{meta['color']};">{meta['icon']} {_esc(meta['label'])}</div>
              <div class="cbr-muted">模型：{_esc(signal.get("model_version") or "—")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for col, horizon in zip(cols[1:4], (5, 10, 20)):
        value = horizons.get(horizon)
        with col:
            st.metric(f"{horizon} 日高压力概率", fmt_pct(value))
            st.progress(min(max(value or 0.0, 0.0), 1.0))
    with cols[4]:
        st.metric("历史分位", fmt_pct(signal.get("percentile")))
        percentile = _to_float(signal.get("percentile"))
        if percentile is not None:
            st.progress(min(max(percentile if percentile <= 1 else percentile / 100.0, 0.0), 1.0))


def _base_layout(title: str, height: int = 260) -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 13, "color": "#1B2631"}},
        "height": height,
        "margin": {"l": 10, "r": 10, "t": 40, "b": 10},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": _FONT, "size": 12, "color": "#34495E"},
        "showlegend": False,
    }


def fig_horizon_probabilities(signal: Any) -> go.Figure:
    signal = to_dict(signal)
    horizons = _horizons(signal.get("horizons"))
    keys = sorted(horizons) or [5, 10, 20]
    values = [horizons.get(k) for k in keys]
    display = [(v or 0.0) * 100 for v in values]
    colors = [_prob_color(v) for v in values]
    figure = go.Figure(
        go.Bar(
            x=[f"{k} 日" for k in keys],
            y=display,
            marker_color=colors,
            marker_line_width=0,
            width=0.52,
            text=[fmt_pct(v) if v is not None else "—" for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>高压力概率 %{y:.1f}%<extra></extra>",
        )
    )
    figure.update_layout(**_base_layout("未来 5 / 10 / 20 日高压力概率", 260))
    figure.update_yaxes(
        range=[0, max(display + [10]) * 1.3],
        ticksuffix="%",
        gridcolor="#EEF2F6",
        zeroline=False,
        title_text="高压力概率",
    )
    figure.update_xaxes(showgrid=False)
    return figure


def fig_percentile_gauge(signal: Any) -> go.Figure:
    signal = to_dict(signal)
    percentile = _to_float(signal.get("percentile"))
    if percentile is None:
        value = 0.0
    else:
        value = percentile * 100 if abs(percentile) <= 1.0 else percentile
    meta = risk_meta(signal.get("level"))
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": "%", "font": {"size": 26}},
            title={"text": "历史分位（阈值 90%）", "font": {"size": 12.5}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#B0BEC5"},
                "bar": {"color": meta["color"], "thickness": 0.34},
                "bgcolor": "#F4F6F8",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 50], "color": "#EAF6EE"},
                    {"range": [50, 80], "color": "#FDF3E0"},
                    {"range": [80, 95], "color": "#FDEBDC"},
                    {"range": [95, 100], "color": "#FADBD8"},
                ],
                "threshold": {
                    "line": {"color": "#C0392B", "width": 3},
                    "thickness": 0.82,
                    "value": 90,
                },
            },
        )
    )
    figure.update_layout(**_base_layout("", 260))
    return figure


def fig_drivers(signal: Any) -> go.Figure:
    signal = to_dict(signal)
    drivers = [to_dict(item) for item in (signal.get("drivers") or [])]
    drivers = [d for d in drivers if _to_float(d.get("contribution")) is not None]
    drivers.sort(key=lambda item: abs(_to_float(item.get("contribution")) or 0.0), reverse=True)
    drivers = drivers[:8][::-1]
    labels = [str(item.get("factor") or "—") for item in drivers]
    values = [abs(_to_float(item.get("contribution")) or 0.0) for item in drivers]
    colors = ["#E74C3C" if _enum_str(item.get("direction") or "up") != "down" else "#27AE60" for item in drivers]
    descriptions = [str(item.get("description") or "") for item in drivers]
    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            marker_line_width=0,
            text=[f"{value:.3f}" for value in values],
            textposition="outside",
            cliponaxis=False,
            customdata=descriptions,
            hovertemplate="%{y}<br>贡献度 %{x:.3f}<br>%{customdata}<extra></extra>",
        )
    )
    figure.update_layout(**_base_layout("驱动因子归因（红=推高风险 / 绿=缓解风险）", 280))
    figure.update_xaxes(gridcolor="#EEF2F6", zeroline=False, title_text="贡献度")
    figure.update_yaxes(showgrid=False)
    return figure


def fig_modality(signal: Any) -> go.Figure:
    signal = to_dict(signal)
    contrib = to_dict(signal.get("modality_contrib")) if isinstance(signal.get("modality_contrib"), dict) else {}
    labels_map = {"numeric": "数值模态", "text": "文本模态"}
    colors_map = {"numeric": "#1F618D", "text": "#AF7AC5"}
    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    for key, value in contrib.items():
        number = _to_float(value)
        if number is None:
            continue
        labels.append(labels_map.get(str(key), str(key)))
        values.append(number)
        colors.append(colors_map.get(str(key), "#7F8C8D"))
    if not values:
        figure = go.Figure()
        figure.add_annotation(text="无模态贡献数据", showarrow=False, font={"size": 13, "color": "#7F8C8D"})
        figure.update_layout(**_base_layout("模态贡献（数值 vs 文本）", 280))
        return figure
    figure = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.56,
            marker={"colors": colors},
            textinfo="label+percent",
            hovertemplate="%{label}<br>贡献 %{percent}<extra></extra>",
        )
    )
    figure.update_layout(**_base_layout("模态贡献（数值 vs 文本）", 280))
    return figure


def fig_trace_timeline(events: Iterable[Any]) -> go.Figure:
    """审计轨迹时间线：x=事件时间，y=协同步骤，颜色=动作类型，点大小=耗时。"""
    items = [to_dict(item) for item in (events or [])]
    points: list[tuple[dt.datetime, str, dict[str, Any]]] = []
    step_order: list[str] = []
    for event in items:
        timestamp = _parse_datetime(event.get("ts"))
        if timestamp is None:
            continue
        step = str(event.get("step") or "—")
        if step not in step_order:
            step_order.append(step)
        points.append((timestamp, step, event))
    if not points:
        figure = go.Figure()
        figure.add_annotation(text="轨迹缺少有效时间戳，无法绘制时间线", showarrow=False, font={"size": 13, "color": "#7F8C8D"})
        figure.update_layout(**_base_layout("审计轨迹时间线", 240))
        return figure
    groups: dict[str, list[tuple[dt.datetime, str, dict[str, Any]]]] = {}
    for timestamp, step, event in points:
        action = _enum_str(event.get("action")) or "other"
        groups.setdefault(action, []).append((timestamp, step, event))
    figure = go.Figure()
    for action, rows in groups.items():
        sizes = [8 + min(_to_float(event.get("latency_ms")) or 0.0, 600.0) / 60.0 for _, _, event in rows]
        custom = [
            " · ".join(
                part
                for part in (
                    role_meta(event.get("role"))["label"] if event.get("role") else "",
                    action,
                    str(event.get("tool") or ""),
                    f"{int(_to_float(event.get('latency_ms')) or 0)} ms",
                )
                if part
            )
            for _, _, event in rows
        ]
        figure.add_trace(
            go.Scatter(
                x=[timestamp for timestamp, _, _ in rows],
                y=[step for _, step, _ in rows],
                mode="markers",
                name=ACTION_LABELS.get(action, action),
                marker={
                    "size": sizes,
                    "color": ACTION_COLORS.get(action, "#7F8C8D"),
                    "line": {"width": 1, "color": "#FFFFFF"},
                    "opacity": 0.9,
                },
                customdata=custom,
                hovertemplate="%{x|%H:%M:%S} · %{y}<br>%{customdata}<extra></extra>",
            )
        )
    figure.update_layout(**_base_layout("审计轨迹时间线（颜色=动作类型，点大小=耗时）", 300))
    figure.update_layout(
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"size": 10}},
        margin={"l": 10, "r": 10, "t": 62, "b": 10},
    )
    figure.update_yaxes(
        categoryorder="array",
        categoryarray=step_order[::-1],
        showgrid=True,
        gridcolor="#EEF2F6",
        title_text="协同步骤",
    )
    figure.update_xaxes(showgrid=False, title_text="时间")
    return figure


def render_signal_charts(signal: Any) -> None:
    """风险仪表盘：概率柱状图 + 分位仪表 + 驱动归因 + 模态贡献。"""
    signal = to_dict(signal)
    st.markdown('<div class="cbr-section-title">📊 风险仪表盘 · 归因分析</div>', unsafe_allow_html=True)
    if not signal:
        st.info("决策卡未包含共享风险信号（signal 字段缺失），无法绘制仪表盘。")
        return
    row1_left, row1_right = st.columns([1.45, 1])
    with row1_left:
        st.plotly_chart(fig_horizon_probabilities(signal), config=PLOTLY_CONFIG, **STRETCH_PLOTLY)
    with row1_right:
        st.plotly_chart(fig_percentile_gauge(signal), config=PLOTLY_CONFIG, **STRETCH_PLOTLY)
    row2_left, row2_right = st.columns([1.3, 1])
    with row2_left:
        st.plotly_chart(fig_drivers(signal), config=PLOTLY_CONFIG, **STRETCH_PLOTLY)
    with row2_right:
        st.plotly_chart(fig_modality(signal), config=PLOTLY_CONFIG, **STRETCH_PLOTLY)
    label_version = signal.get("label_version")
    if label_version:
        st.caption(f"标签版本：{label_version}　·　模态贡献与驱动因子均来自共享信号 evidence_id：{signal.get('evidence_id') or '—'}")


# --------------------------------------------------------------------------- #
# 三智能体卡片
# --------------------------------------------------------------------------- #
def _claims_rows(claims: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for claim in claims or []:
        claim = to_dict(claim)
        rows.append(
            {
                "类型": CLAIM_TYPE_LABELS.get(_enum_str(claim.get("claim_type")), str(claim.get("claim_type") or "—")),
                "主张": str(claim.get("text") or claim.get("subject") or "—"),
                "状态": CLAIM_STATUS_LABELS.get(_enum_str(claim.get("status")), str(claim.get("status") or "—")),
                "置信度": fmt_pct(claim.get("confidence")),
                "证据数": len(claim.get("evidence_ids") or []),
            }
        )
    return rows


def render_agent_card(card: Any, role_key: str | None = None) -> None:
    """单个智能体风险卡（风险等级 / 关键指标 / 建议 / 置信度 / 局限）。"""
    card = to_dict(card)
    role = role_meta(role_key or card.get("role"))
    level_meta = risk_meta(card.get("risk_level"))
    claims = card.get("claims") or []
    limitations = [str(item) for item in (card.get("limitations") or []) if str(item).strip()]
    confidence = _avg_confidence(claims)

    with st.container(border=True):
        st.markdown(
            f'<div class="cbr-agent-head"><span>{role["icon"]} {_esc(role["label"])}</span>'
            f'{risk_chip(card.get("risk_level"))}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:13.5px;font-weight:650;min-height:40px;line-height:1.45;">'
            f'{_esc(card.get("headline") or "未提供核心结论")}</div>',
            unsafe_allow_html=True,
        )
        metrics = [to_dict(item) for item in (card.get("key_metrics") or [])][:4]
        if metrics:
            rows = "".join(
                f'<div class="k">{_esc(metric.get("label") or metric.get("name") or "指标")}</div>'
                f'<div class="v">{_esc(fmt_metric_value(metric.get("value"), metric.get("unit")))}</div>'
                for metric in metrics
            )
            st.markdown(f'<div class="cbr-kv" style="margin-top:4px;">{rows}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="cbr-muted" style="margin-top:9px;">💡 建议</div>'
            f'<div style="font-size:13px;line-height:1.5;">{_esc(card.get("recommendation") or "—")}</div>',
            unsafe_allow_html=True,
        )
        col_conf, col_progress = st.columns([1, 1])
        with col_conf:
            st.caption(f"置信度：{fmt_pct(confidence) if confidence is not None else '—'}")
        with col_progress:
            if confidence is not None:
                st.progress(min(max(float(confidence), 0.0), 1.0))
        st.caption(
            f"工具调用 {card.get('tool_calls', 0)} 次 · tokens {card.get('tokens', 0)} · "
            f"耗时 {card.get('latency_ms', 0)} ms · 轮次 R{card.get('round', 0)}"
        )
        with st.expander(f"主张与局限（{len(claims)} 条主张 / {len(limitations)} 项局限）", expanded=False):
            if claims:
                st.dataframe(pd.DataFrame(_claims_rows(claims)), hide_index=True, **STRETCH_DATAFRAME)
            else:
                st.caption("未提供结构化主张（claims 为空）。")
            if limitations:
                st.markdown("**局限说明**")
                st.markdown("\n".join(f"- {item}" for item in limitations))
            else:
                st.caption("未提供局限说明。")


def render_agent_cards(decision: Any) -> None:
    decision = to_dict(decision)
    cards = to_dict(decision.get("cards"))
    st.markdown('<div class="cbr-section-title">🤖 三智能体风险卡（监管 / 投资 / 融资）</div>', unsafe_allow_html=True)
    roles = [role for role in ROLE_ORDER if role in cards] or list(cards)
    if not roles:
        st.info("决策卡未包含三智能体结果（cards 为空），可能处于单智能体模式或编排层尚未产出。")
        return
    columns = st.columns(max(len(roles), 1))
    for column, role_key in zip(columns, roles):
        with column:
            render_agent_card(cards[role_key], role_key)


def render_coordination_stats(decision: Any) -> None:
    """协同开销与整体建议（三卡片下方一行，保持一屏信息密度）。"""
    decision = to_dict(decision)
    coordination = to_dict(decision.get("coordination"))
    columns = st.columns([1, 1, 1, 1, 1, 1.6])
    metrics = [
        ("协同轮次", coordination.get("rounds", 0)),
        ("共享证据", coordination.get("evidence_shared", 0)),
        ("冲突 / 已解决", f"{coordination.get('conflicts_total', 0)} / {coordination.get('conflicts_resolved', 0)}"),
        ("工具调用", coordination.get("tool_calls", 0)),
        ("tokens", coordination.get("tokens", 0)),
        ("端到端耗时", f"{fmt_num((coordination.get('latency_ms') or 0) / 1000, 1)} s"),
    ]
    for column, (label, value) in zip(columns[:6], metrics):
        column.metric(label, value)
    with st.container(border=True):
        st.markdown(
            f'<div class="cbr-muted" style="font-size:12px;text-transform:uppercase;letter-spacing:.6px;">'
            f'最终综合建议（决策卡 · final_advice）</div>'
            f'<div style="font-size:14px;line-height:1.6;margin-top:2px;">'
            f'{_esc(decision.get("final_advice") or "—")}</div>',
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# 证据板
# --------------------------------------------------------------------------- #
def _render_evidence_detail(evidence: dict[str, Any]) -> None:
    source = to_dict(evidence.get("source"))
    tool = to_dict(evidence.get("tool"))
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("**来源与可追溯信息**")
        rows: list[tuple[str, str]] = [
            ("证据 ID", f"`{_esc(evidence.get('evidence_id') or '—')}`"),
            ("证据类型", evidence_kind_meta(evidence.get("kind"))["label"]),
            ("证据时点", fmt_date(evidence.get("as_of"))),
            ("产出方", str(evidence.get("produced_by") or "—")),
            ("来源", str(source.get("name") or "—")),
        ]
        if source.get("url"):
            source_url = html.escape(str(source.get("url")), quote=True)
            rows.append(("来源链接", f'<a href="{source_url}" target="_blank">{_esc(source.get("url"))}</a>'))
        if source.get("doc_id"):
            rows.append(("文档 ID", str(source.get("doc_id"))))
        if source.get("chunk_id"):
            rows.append(("片段 ID", str(source.get("chunk_id"))))
        if source.get("release_time"):
            rows.append(("发布时间", fmt_datetime(source.get("release_time"))))
        if tool:
            rows.append(("工具", f"{_esc(tool.get('name') or '—')} v{_esc(tool.get('version') or '—')}"))
            if tool.get("inputs_hash"):
                rows.append(("输入哈希", f"`{_esc(tool.get('inputs_hash'))}`"))
            rows.append(("工具耗时", f"{tool.get('elapsed_ms', 0)} ms"))
        if evidence.get("hash"):
            rows.append(("证据哈希", f"`{_esc(evidence.get('hash'))}`"))
        if evidence.get("created_at"):
            rows.append(("生成时间", fmt_datetime(evidence.get("created_at"))))
        verified = evidence.get("verified")
        if verified is not None:
            rows.append(("核验状态", "✅ 已核验" if verified else "⚠️ 未通过"))
        kv = "".join(f'<div class="k">{_esc(k)}</div><div class="v">{v}</div>' for k, v in rows)
        st.markdown(f'<div class="cbr-kv">{kv}</div>', unsafe_allow_html=True)
        citations = [to_dict(item) for item in (evidence.get("citations") or [])]
        if citations:
            st.markdown("**引文**")
            st.markdown(
                "\n".join(
                    f"- {item.get('name') or '—'}"
                    + (f"（{item.get('doc_id')}/{item.get('chunk_id')}）" if item.get("chunk_id") else "")
                    + (f" · 发布 {fmt_datetime(item.get('release_time'))}" if item.get("release_time") else "")
                    for item in citations
                )
            )
    with right:
        st.markdown("**证据内容**")
        if evidence.get("value") is not None:
            st.metric("数值", fmt_metric_value(evidence.get("value"), evidence.get("unit")))
        if evidence.get("summary"):
            st.markdown(str(evidence.get("summary")))
        payload = evidence.get("payload")
        if payload:
            st.code(_shorten(_safe_json(payload), 3800), language="json")
        else:
            st.caption("该证据无结构化 payload。")


def render_evidence_board(evidences: Iterable[Any], missing: Iterable[str]) -> None:
    st.markdown('<div class="cbr-section-title">🧾 证据板（可展开追溯来源 / 时点 / 工具版本 / 输入哈希）</div>', unsafe_allow_html=True)
    items = [to_dict(item) for item in (evidences or [])]
    missing_ids = [str(item) for item in (missing or [])]
    all_kinds = sorted({_enum_str(item.get("kind")) or "unknown" for item in items})
    col_kind, col_search = st.columns([1.05, 1.4])
    with col_kind:
        selected = st.multiselect(
            "证据类型过滤",
            options=all_kinds,
            default=all_kinds,
            format_func=lambda key: evidence_kind_meta(key)["label"],
        )
    with col_search:
        query = st.text_input("搜索（标题 / 来源 / 证据 ID）", placeholder="例如：VaR、外管局、ev_sig")

    query_lower = query.strip().lower()

    def _match(item: dict[str, Any]) -> bool:
        if selected and (_enum_str(item.get("kind")) or "unknown") not in selected:
            return False
        if not query_lower:
            return True
        haystack = " ".join(
            str(item.get(key) or "") for key in ("title", "summary", "evidence_id")
        ) + " " + str(to_dict(item.get("source")).get("name") or "")
        return query_lower in haystack.lower()

    filtered = [item for item in items if _match(item)]
    summary = f"共 {len(items)} 条证据，当前展示 {len(filtered)} 条"
    if missing_ids:
        summary += f"；另有 {len(missing_ids)} 条引用未能在服务中解析"
    st.caption(summary)

    if not items and not missing_ids:
        st.info("本次决策未引用证据，或编排层尚未把证据写入黑板（DecisionCard 不直接携带 Evidence 列表）。")
        return

    for item in filtered:
        kind = evidence_kind_meta(item.get("kind"))
        title = str(item.get("title") or item.get("evidence_id") or "未命名证据")
        label = (
            f'{kind["icon"]} [{kind["label"]}] {title}　·　{fmt_date(item.get("as_of"))}'
            f'　·　{str(item.get("evidence_id") or "—")[:40]}'
        )
        with st.expander(label, expanded=False):
            _render_evidence_detail(item)

    if missing_ids:
        with st.expander(f"⚠️ {len(missing_ids)} 条引用证据暂不可解析（点击查看）", expanded=False):
            st.markdown(
                "以下 evidence_id 被决策卡引用，但编排层未通过 `get_evidence()` / 黑板暴露，"
                "且 artifacts 目录无对应文件。**这不是界面错误**，而是证据检索接口待核心模块补齐："
            )
            st.code("\n".join(missing_ids), language="text")
            st.caption("建议编排层实现 `orchestrator.get_evidence(evidence_id)`，或在黑板维护 evidence 字典。")


def render_evidence_brief(evidences: Iterable[Any], missing: Iterable[str]) -> None:
    """对话页使用的精简证据列表。"""
    items = [to_dict(item) for item in (evidences or [])]
    missing_ids = [str(item) for item in (missing or [])]
    if not items and not missing_ids:
        return
    label = f"🔎 引用证据 {len(items)} 条"
    if missing_ids:
        label += f"（另有 {len(missing_ids)} 条未解析）"
    with st.expander(label, expanded=False):
        for item in items[:10]:
            kind = evidence_kind_meta(item.get("kind"))
            st.markdown(
                f'- {kind["icon"]} **{item.get("title") or "未命名证据"}**　·　{kind["label"]}'
                f'　·　{fmt_date(item.get("as_of"))}　·　`{item.get("evidence_id") or "—"}`'
            )
            if item.get("summary"):
                st.caption(str(item.get("summary")))
            tool = to_dict(item.get("tool"))
            if tool:
                st.caption(
                    f"工具 {tool.get('name') or '—'} v{tool.get('version') or '—'}"
                    + (f" · 输入哈希 `{tool.get('inputs_hash')}`" if tool.get("inputs_hash") else "")
                )
        if missing_ids:
            st.caption("未解析引用：" + "、".join(missing_ids[:12]))


# --------------------------------------------------------------------------- #
# 分歧与协调
# --------------------------------------------------------------------------- #
def _severity_weight(severity: Any) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(_enum_str(severity), 2)


def render_conflicts(conflicts: Iterable[Any]) -> None:
    st.markdown('<div class="cbr-section-title">⚖️ 分歧与协调面板</div>', unsafe_allow_html=True)
    items = [to_dict(item) for item in (conflicts or [])]
    resolved = [item for item in items if item.get("resolved")]
    columns = st.columns(3)
    columns[0].metric("冲突总数", len(items))
    columns[1].metric("已解决", len(resolved))
    columns[2].metric("未解决 / 升级", len(items) - len(resolved))
    if not items:
        st.success("本轮未检测到智能体间冲突：三类主体的结论与证据保持一致，无需协调。")
        return

    ordered = sorted(items, key=lambda item: (bool(item.get("resolved")), -_severity_weight(item.get("severity"))))
    for conflict in ordered:
        conflict_type = CONFLICT_TYPE_META.get(_enum_str(conflict.get("type")), {"label": str(conflict.get("type") or "未知"), "color": "#7F8C8D"})
        severity = SEVERITY_META.get(_enum_str(conflict.get("severity")), SEVERITY_META["medium"])
        resolved_flag = bool(conflict.get("resolved"))
        status_chip = (
            chip("已解决", "#1E8449", "#E9F7EF", "✅") if resolved_flag else chip("未解决", "#C0392B", "#FDEDEC", "⚠️")
        )
        with st.container(border=True):
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">'
                f'<div style="font-size:14.5px;font-weight:700;">{_esc(conflict.get("subject") or "未命名冲突")}</div>'
                f'<div>{chip(conflict_type["label"], conflict_type["color"], conflict_type["color"] + "18")}'
                f'{chip("严重度 " + severity["label"], severity["color"], severity["color"] + "18")}{status_chip}</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div style="font-size:13px;line-height:1.55;margin-top:4px;">{_esc(conflict.get("description") or "—")}</div>', unsafe_allow_html=True)
            roles = "、".join(role_meta(role)["label"] for role in (conflict.get("roles") or []))
            st.caption(f"涉及主体：{roles or '—'}　·　关联主张：{len(conflict.get('claim_ids') or [])} 条　·　引用证据：{len(conflict.get('evidence_ids') or [])} 条")
            if resolved_flag:
                st.markdown(
                    f'**协调结果（{RESOLVED_BY_LABELS.get(_enum_str(conflict.get("resolved_by")), "—")}）**：'
                    f'{conflict.get("resolution") or "—"}'
                )
            else:
                st.warning("该冲突尚未收敛，可能升级至人工介入（HITL）。")


# --------------------------------------------------------------------------- #
# 核验与审计
# --------------------------------------------------------------------------- #
def render_verification(report: Any) -> None:
    report = to_dict(report)
    st.markdown('<div class="cbr-section-title">🔍 核验与审计（横切 A）</div>', unsafe_allow_html=True)
    passed = report.get("passed")
    if passed is True:
        st.success("✅ 核验通过：数值、引文、时点、权限与 Schema 检查均无异常。")
    elif passed is False:
        st.error("⚠️ 核验存在异常项，详见下方问题列表（数值核验 / 引文 / 时点 / 越权 / Schema）。")
    else:
        st.info("核验报告缺失（VerificationReport 未提供）。")

    numeric_total = int(_to_float(report.get("numeric_checks_total")) or 0)
    numeric_passed = int(_to_float(report.get("numeric_checks_passed")) or 0)
    citation_total = int(_to_float(report.get("citation_checks_total")) or 0)
    citation_passed = int(_to_float(report.get("citation_checks_passed")) or 0)
    error_rate = _to_float(report.get("numeric_error_rate"))
    if error_rate is not None:
        numeric_rate: float | None = 1.0 - error_rate
    elif numeric_total:
        numeric_rate = numeric_passed / numeric_total
    else:
        numeric_rate = None
    columns = st.columns(6)
    columns[0].metric("数值核验通过率", fmt_pct(numeric_rate))
    columns[1].metric("证据准确率", fmt_pct(report.get("evidence_accuracy")))
    columns[2].metric("无依据断言率", fmt_pct(report.get("unsupported_claim_rate")))
    columns[3].metric("越权拦截", int(_to_float(report.get("permission_violations")) or 0))
    columns[4].metric("时点泄漏", int(_to_float(report.get("leakage_events")) or 0))
    columns[5].metric("Schema 错误", int(_to_float(report.get("schema_errors")) or 0))

    col_a, col_b = st.columns(2)
    with col_a:
        st.caption(f"数值核验：{numeric_passed} / {numeric_total} 通过")
        st.progress(min(max(numeric_rate if numeric_rate is not None else 0.0, 0.0), 1.0))
    with col_b:
        st.caption(f"引文核验：{citation_passed} / {citation_total} 通过")
        citation_rate = citation_passed / citation_total if citation_total else 0.0
        st.progress(min(max(citation_rate, 0.0), 1.0))

    issues = [to_dict(item) for item in (report.get("issues") or [])]
    if issues:
        st.markdown(f"**核验问题列表（{len(issues)} 条）**")
        rows = [
            {
                "类型": ISSUE_TYPE_LABELS.get(_enum_str(item.get("issue_type")), str(item.get("issue_type") or "—")),
                "角色": role_meta(item.get("role"))["label"] if item.get("role") else "—",
                "严重度": SEVERITY_META.get(_enum_str(item.get("severity")), SEVERITY_META["medium"])["label"],
                "说明": str(item.get("detail") or ""),
            }
            for item in issues
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH_DATAFRAME)
    else:
        st.caption("未报告任何核验问题（issues 为空）。")


def render_trace(events: Iterable[Any], decision: Any) -> None:
    events = [to_dict(item) for item in (events or [])]
    decision = to_dict(decision)
    st.markdown('<div class="cbr-section-title">🧾 审计轨迹时间线（trace）</div>', unsafe_allow_html=True)
    if not events:
        trace_ref = decision.get("trace_ref")
        st.info(
            "当前进程未获取到审计轨迹：编排层未提供 get_trace()，artifacts/traces/ 下也没有对应文件。"
            + (f" 决策卡 trace_ref：{trace_ref}" if trace_ref else "")
        )
        st.caption("约定路径：`artifacts/traces/<run_id>.jsonl`（每行一个 TraceEvent）。")
        return
    tool_calls = sum(1 for event in events if _enum_str(event.get("action")) == "tool_call")
    total_latency = sum(_to_float(event.get("latency_ms")) or 0.0 for event in events)
    total_tokens = sum(_to_float(event.get("tokens")) or 0.0 for event in events)
    columns = st.columns(4)
    columns[0].metric("事件数", len(events))
    columns[1].metric("工具调用", tool_calls)
    columns[2].metric("累计耗时", f"{total_latency / 1000:.2f} s")
    columns[3].metric("累计 tokens", int(total_tokens))
    st.plotly_chart(fig_trace_timeline(events), config=PLOTLY_CONFIG, **STRETCH_PLOTLY)
    rows = []
    for event in events:
        rows.append(
            {
                "时间": fmt_datetime(event.get("ts")),
                "步骤": str(event.get("step") or "—"),
                "角色": role_meta(event.get("role"))["label"] if event.get("role") else "—",
                "动作": ACTION_LABELS.get(_enum_str(event.get("action")), str(event.get("action") or "—")),
                "工具": str(event.get("tool") or "—"),
                "耗时(ms)": int(_to_float(event.get("latency_ms")) or 0),
                "tokens": int(_to_float(event.get("tokens")) or 0),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH_DATAFRAME, height=min(320, 38 + 35 * len(rows)))
    with st.expander("展开单条事件详情（args_hash / result_hash / detail）", expanded=False):
        for index, event in enumerate(events[:40], start=1):
            role_label = role_meta(event.get("role"))["label"] if event.get("role") else "—"
            action_label = ACTION_LABELS.get(_enum_str(event.get("action")), str(event.get("action") or "—"))
            with st.expander(f"{index:02d} · {event.get('step') or '—'} · {role_label} · {action_label}", expanded=False):
                st.markdown(
                    f"工具：`{event.get('tool') or '—'}`　·　args_hash：`{event.get('args_hash') or '—'}`　·　"
                    f"result_hash：`{event.get('result_hash') or '—'}`　·　耗时 {event.get('latency_ms', 0)} ms　·　"
                    f"tokens {event.get('tokens', 0)}"
                )
                detail = event.get("detail")
                if detail:
                    st.code(_shorten(_safe_json(detail), 3000), language="json")


# --------------------------------------------------------------------------- #
# 数据卡
# --------------------------------------------------------------------------- #
def render_data_cards(cards: Iterable[Any]) -> None:
    st.markdown('<div class="cbr-section-title">🗂️ 数据卡（数据口径 / 覆盖期 / 时点可得性）</div>', unsafe_allow_html=True)
    items = [to_dict(item) for item in (cards or [])]
    if not items:
        st.info("数据层未返回数据卡（DataProvider.data_cards() 为空或尚未实现）。")
        return
    rows = []
    for item in items:
        coverage = ""
        if item.get("coverage_start") or item.get("coverage_end"):
            coverage = f"{fmt_date(item.get('coverage_start'))} ~ {fmt_date(item.get('coverage_end'))}"
        rows.append(
            {
                "序列 ID": item.get("series_id") or "—",
                "名称": item.get("name") or "—",
                "来源": item.get("source") or "—",
                "频率": item.get("frequency") or "—",
                "覆盖期": coverage or "—",
                "发布滞后(天)": item.get("release_lag_days", 0),
                "时点评级": PIT_LABELS.get(_enum_str(item.get("pit_grade")), str(item.get("pit_grade") or "—")),
                "单位": item.get("unit") or "—",
                "备注": item.get("notes") or "",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH_DATAFRAME)
    st.caption("时点评级：严格 = release_time 精确可得；近似 = 用交易日近似；不可得 = 仅用于事后评估。")


# --------------------------------------------------------------------------- #
# 导出：Markdown 简报 + JSON 数据包
# --------------------------------------------------------------------------- #
def _briefing_header(decision: dict[str, Any], scenario_name: str | None) -> list[str]:
    signal = to_dict(decision.get("signal"))
    mode = _enum_str(decision.get("mode"))
    return [
        "# CBR-MAW 跨境金融风险预警简报",
        "",
        f"- **场景**：{scenario_name or decision.get('scenario') or '—'}",
        f"- **分析时点（as_of）**：{fmt_date(decision.get('as_of'))}",
        f"- **实验模式**：{MODE_LABELS.get(mode, mode or '—')}",
        f"- **运行 ID**：`{decision.get('run_id') or '—'}`",
        f"- **生成时间**：{fmt_datetime(decision.get('created_at'))}",
        "",
        "## 一、共享风险信号",
        "",
        f"- 综合风险等级：**{risk_meta(signal.get('level'))['label']}**",
        f"- 模型版本：{signal.get('model_version') or '—'}（标签版本 {signal.get('label_version') or '—'}）",
    ]


def build_markdown_briefing(
    decision: Any,
    evidences: Iterable[Any] | None = None,
    trace_events: Iterable[Any] | None = None,
    scenario_name: str | None = None,
) -> str:
    """生成结构化预警简报（Markdown，可复核的决策支持产物）。"""
    decision = to_dict(decision)
    signal = to_dict(decision.get("signal"))
    lines = _briefing_header(decision, scenario_name)
    horizons = _horizons(signal.get("horizons"))
    for horizon in sorted(horizons):
        lines.append(f"- {horizon} 日高压力概率：{fmt_pct(horizons.get(horizon))}")
    lines.append(f"- 历史分位：{fmt_pct(signal.get('percentile'))}")
    drivers = [to_dict(item) for item in (signal.get("drivers") or [])][:5]
    if drivers:
        lines.append("- 主要驱动因子：")
        for driver in drivers:
            direction = "推高" if _enum_str(driver.get("direction") or "up") != "down" else "缓解"
            lines.append(
                f"  - `{driver.get('factor') or '—'}`（贡献 {fmt_num(driver.get('contribution'), 3)}，{direction}风险）"
                f"{('：' + str(driver.get('description'))) if driver.get('description') else ''}"
            )
    modality = to_dict(signal.get("modality_contrib"))
    if modality:
        lines.append(
            "- 模态贡献：" + "、".join(f"{key} {fmt_pct(value)}" for key, value in modality.items())
        )
    lines.append("")

    lines.extend(["## 二、三主体判断与建议", ""])
    cards = to_dict(decision.get("cards"))
    for role_key in ROLE_ORDER:
        if role_key not in cards:
            continue
        card = to_dict(cards[role_key])
        role = role_meta(role_key)
        lines.append(f"### {role['icon']} {role['label']} · 风险等级：{risk_meta(card.get('risk_level'))['label']}")
        lines.append("")
        lines.append(f"- 核心结论：{card.get('headline') or '—'}")
        metrics = [to_dict(item) for item in (card.get("key_metrics") or [])][:4]
        if metrics:
            lines.append(
                "- 关键指标："
                + "；".join(
                    f"{metric.get('label') or metric.get('name')} = {fmt_metric_value(metric.get('value'), metric.get('unit'))}"
                    for metric in metrics
                )
            )
        lines.append(f"- 建议：{card.get('recommendation') or '—'}")
        confidence = _avg_confidence(card.get("claims") or [])
        if confidence is not None:
            lines.append(f"- 置信度（主张均值）：{fmt_pct(confidence)}")
        limitations = [str(item) for item in (card.get("limitations") or []) if str(item).strip()]
        if limitations:
            lines.append("- 局限：" + "；".join(limitations))
        lines.append("")

    lines.extend(["## 三、分歧与协调", ""])
    conflicts = [to_dict(item) for item in (decision.get("conflicts") or [])]
    if not conflicts:
        lines.append("本轮未检测到智能体间冲突。")
    else:
        for conflict in conflicts:
            conflict_type = CONFLICT_TYPE_META.get(_enum_str(conflict.get("type")), {"label": str(conflict.get("type") or "—")})
            status = "已解决" if conflict.get("resolved") else "未解决"
            lines.append(
                f"- **{conflict.get('subject') or '未命名冲突'}**（{conflict_type['label']} · {status}）："
                f"{conflict.get('description') or '—'}"
            )
            if conflict.get("resolved"):
                lines.append(
                    f"  - 协调结果（{RESOLVED_BY_LABELS.get(_enum_str(conflict.get('resolved_by')), '—')}）："
                    f"{conflict.get('resolution') or '—'}"
                )
    lines.append("")

    lines.extend(["## 四、核验与审计", ""])
    report = to_dict(decision.get("verification"))
    lines.extend(
        [
            f"- 核验结论：{'通过' if report.get('passed') else '存在异常' if report.get('passed') is False else '—'}",
            f"- 数值核验：{int(_to_float(report.get('numeric_checks_passed')) or 0)} / {int(_to_float(report.get('numeric_checks_total')) or 0)}"
            f"（错误率 {fmt_pct(report.get('numeric_error_rate'))}）",
            f"- 引文核验：{int(_to_float(report.get('citation_checks_passed')) or 0)} / {int(_to_float(report.get('citation_checks_total')) or 0)}"
            f"（证据准确率 {fmt_pct(report.get('evidence_accuracy'))}）",
            f"- 越权拦截：{int(_to_float(report.get('permission_violations')) or 0)} 次；"
            f"时点泄漏：{int(_to_float(report.get('leakage_events')) or 0)} 次；"
            f"Schema 错误：{int(_to_float(report.get('schema_errors')) or 0)} 次",
            f"- 审计轨迹：`{decision.get('trace_ref') or '—'}`，事件 {len(list(trace_events or []))} 条",
        ]
    )
    issues = [to_dict(item) for item in (report.get("issues") or [])]
    if issues:
        lines.append("- 核验问题：")
        for issue in issues:
            lines.append(
                f"  - [{ISSUE_TYPE_LABELS.get(_enum_str(issue.get('issue_type')), issue.get('issue_type'))}]"
                f" {issue.get('detail') or '—'}"
            )
    lines.append("")

    lines.extend(["## 五、证据清单（可复核）", ""])
    evidence_items = [to_dict(item) for item in (evidences or [])]
    if not evidence_items:
        lines.append("（本次运行未获取到证据对象，证据检索接口以 evidence_id 引用形式保留。）")
    for item in evidence_items:
        kind = evidence_kind_meta(item.get("kind"))
        source = to_dict(item.get("source"))
        tool = to_dict(item.get("tool"))
        lines.append(
            f"- `{item.get('evidence_id') or '—'}` · {kind['label']} · {item.get('title') or '—'} · "
            f"as_of {fmt_date(item.get('as_of'))} · 来源 {source.get('name') or '—'}"
            + (f" · 工具 {tool.get('name')} v{tool.get('version')}" if tool else "")
        )
    lines.append("")
    lines.extend(
        [
            "## 六、说明与免责声明",
            "",
            "- 本简报由 CBR-MAW 多智能体协同系统在指定 `as_of` 时点、仅使用当日可得信息生成，用于研究与演示。",
            "- 数值与结论均已通过数值核验 / 引文溯源 / 时点核验流程；仍存在模型与数据局限，不构成投资建议。",
            f"- 协同开销：tokens {to_dict(decision.get('coordination')).get('tokens', 0)}，"
            f"工具调用 {to_dict(decision.get('coordination')).get('tool_calls', 0)} 次，"
            f"端到端 {fmt_num((to_dict(decision.get('coordination')).get('latency_ms') or 0) / 1000, 2)} s。",
            "",
        ]
    )
    return "\n".join(lines)


def build_json_briefing(
    decision: Any,
    evidences: Iterable[Any] | None = None,
    trace_events: Iterable[Any] | None = None,
    scenario_name: str | None = None,
) -> str:
    """生成 JSON 数据包（decision + evidence + trace，可直接进实验/归档）。"""
    payload = {
        "brief_version": "1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scenario_name": scenario_name,
        "decision": to_dict(decision),
        "evidence": [to_dict(item) for item in (evidences or [])],
        "trace": [to_dict(item) for item in (trace_events or [])],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _file_slug(decision: dict[str, Any]) -> str:
    as_of = fmt_date(decision.get("as_of")).replace("-", "")
    run_id = str(decision.get("run_id") or "run").replace("/", "_")[:32]
    return f"CBR-MAW_预警简报_{as_of}_{run_id}"


def render_export(
    decision: Any,
    evidences: Iterable[Any] | None = None,
    trace_events: Iterable[Any] | None = None,
    scenario_name: str | None = None,
) -> None:
    st.markdown('<div class="cbr-section-title">📤 导出可复核的预警简报</div>', unsafe_allow_html=True)
    decision_dict = to_dict(decision)
    evidence_list = list(evidences or [])
    trace_list = list(trace_events or [])
    markdown_text = build_markdown_briefing(decision_dict, evidence_list, trace_list, scenario_name)
    json_text = build_json_briefing(decision_dict, evidence_list, trace_list, scenario_name)
    slug = _file_slug(decision_dict)

    columns = st.columns([1, 1, 1])
    with columns[0]:
        st.download_button(
            "⬇️ 下载 Markdown 简报",
            data=markdown_text,
            file_name=f"{slug}.md",
            mime="text/markdown; charset=utf-8",
            **STRETCH_DOWNLOAD,
            type="primary",
        )
    with columns[1]:
        st.download_button(
            "⬇️ 下载 JSON 数据包",
            data=json_text,
            file_name=f"{slug}.json",
            mime="application/json; charset=utf-8",
            **STRETCH_DOWNLOAD,
        )
    with columns[2]:
        trace_text = "\n".join(
            json.dumps(item, ensure_ascii=False, default=str) for item in trace_list
        )
        st.download_button(
            "⬇️ 下载审计轨迹 JSONL",
            data=trace_text or "[]",
            file_name=f"{slug}_trace.jsonl",
            mime="application/x-ndjson; charset=utf-8",
            **STRETCH_DOWNLOAD,
            disabled=not trace_list,
        )
    st.caption(
        f"简报固定包含：as_of 时点、run_id、共享信号、三主体卡片、冲突协调、核验结果与证据清单"
        f"（当前证据 {len(evidence_list)} 条、trace {len(trace_list)} 条）。"
    )
    with st.expander("预览 Markdown 预警简报", expanded=False):
        st.markdown(markdown_text)


# --------------------------------------------------------------------------- #
# 对话页辅助
# --------------------------------------------------------------------------- #
def render_citations(citations: Iterable[Any]) -> None:
    items = [to_dict(item) for item in (citations or [])]
    if not items:
        return
    with st.expander(f"📚 引用来源 {len(items)} 条", expanded=False):
        for item in items:
            label = str(item.get("name") or item.get("doc_id") or "来源")
            st.markdown(f"- **{label}**")
            meta = []
            if item.get("doc_id"):
                meta.append(f"doc_id `{item.get('doc_id')}`")
            if item.get("chunk_id"):
                meta.append(f"chunk_id `{item.get('chunk_id')}`")
            if item.get("release_time"):
                meta.append(f"发布时间 {fmt_datetime(item.get('release_time'))}")
            if meta:
                st.caption(" · ".join(meta))
            if item.get("url"):
                st.caption(str(item.get("url")))


def render_decision_compact(decision: Any, key_suffix: int | str | None = None) -> None:
    decision = to_dict(decision)
    cards = to_dict(decision.get("cards"))
    signal = to_dict(decision.get("signal"))
    chips = "".join(
        f'{role_meta(role_key)["icon"]} {role_meta(role_key)["label"]} {risk_chip(to_dict(cards.get(role_key)).get("risk_level"))}'
        for role_key in ROLE_ORDER
        if role_key in cards
    )
    st.markdown(
        f"""
        <div class="cbr-card">
          <div style="font-weight:700;margin-bottom:6px;">🔗 关联决策卡 · run_id <code>{_esc(decision.get("run_id") or "—")}</code>
            · as_of {fmt_date(decision.get("as_of"))} · 综合风险 {_esc(risk_meta(signal.get("level"))["label"])}</div>
          <div style="margin-bottom:4px;">{chips}</div>
          <div class="cbr-muted">{_esc(decision.get("final_advice") or "无综合建议")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("查看三主体建议与信号详情", expanded=False):
        for role_key in ROLE_ORDER:
            if role_key not in cards:
                continue
            card = to_dict(cards[role_key])
            st.markdown(
                f"**{role_meta(role_key)['label']}**（{risk_meta(card.get('risk_level'))['label']}）："
                f"{card.get('headline') or '—'}"
            )
            st.caption(f"建议：{card.get('recommendation') or '—'}")
        horizons = _horizons(signal.get("horizons"))
        if horizons:
            st.caption(
                "共享信号：" + " · ".join(f"{horizon} 日 {fmt_pct(value)}" for horizon, value in sorted(horizons.items()))
                + f" · 历史分位 {fmt_pct(signal.get('percentile'))}"
            )
        md = build_markdown_briefing(decision, scenario_name=decision.get("scenario"))
        st.download_button(
            "⬇️ 下载本次对话的决策简报",
            data=md,
            file_name=f"{_file_slug(decision)}.md",
            mime="text/markdown; charset=utf-8",
            key=f"chat_download_{decision.get('run_id') or 'run'}_{key_suffix or 0}",
        )


# --------------------------------------------------------------------------- #
# 关于页
# --------------------------------------------------------------------------- #
def render_about(readiness: dict[str, Any], settings: dict[str, Any]) -> None:
    st.markdown("## 📖 关于 CBR-MAW")
    st.markdown(
        "**跨境金融风险多智能体协同预警系统**（Cross-Border Risk Multi-Agent Warning）。"
        "系统以「可解释、可核验、可复现」为目标：共享多模态风险信号 → 监管 / 投资 / 融资三角色智能体 → "
        "黑板证据共享与冲突协调 → 数值 / 引文 / 时点 / 权限核验 → 决策卡与可复核简报。"
    )
    layers = pd.DataFrame(
        [
            ["L1 数据与时点层", "DuckDB Point-in-Time 存储、数据卡、风险标签（5/10/20 交易日）"],
            ["L2 多模态融合层", "数值 + 政策/新闻文本特征、融合预测器、驱动因子与模态贡献归因"],
            ["L3 知识与工具层", "时点过滤 RAG、确定性金融工具（risk_measure / systemic_risk / capital_flow / scenario / funding_cost …）、权限矩阵"],
            ["L4 智能体层", "监管 / 投资 / 融资三角色 RiskCard、Evidence 引用与反幻觉约束"],
            ["L5 协同编排层", "R0 独立分析 → R1 证据共享 → R2 交叉验证 → R3 分歧识别 → R4 协调仲裁 → R5 决策卡"],
            ["L6 决策支持层", "本驾驶台：场景/时点回放、风险仪表盘、三卡片、证据板、分歧与核验、简报导出、对话入口"],
            ["横切 A 验证与审计", "数值核验、引文溯源、时点核验、越权阻断、Schema 校验、trace 审计"],
            ["横切 B 实验与评估", "配置化消融（P1/P2/P3）、时点回放、指标与统计检验"],
        ],
        columns=["层级", "内容"],
    )
    st.dataframe(layers, hide_index=True, **STRETCH_DATAFRAME)

    st.markdown("### 🎬 录屏演示脚本")
    st.markdown(
        "1. 侧边栏选择历史压力场景（如「2024 日元套息交易逆转」），系统自动设定 `as_of`；\n"
        "2. 主页面自上而下：综合风险信号（5/10/20 日概率、历史分位）→ 三智能体卡片；\n"
        "3. 「📊 风险仪表盘」页签查看驱动因子归因与模态贡献（Plotly）；\n"
        "4. 「🧾 证据板」展开任一条证据，展示来源、时点、工具版本与输入哈希（可重算）；\n"
        "5. 「⚖️ 分歧与协调」展示事实/方向/偏好冲突及仲裁结果；\n"
        "6. 「🔍 核验与审计」查看数值核验通过率、越权拦截、时点泄漏与 trace 时间线；\n"
        "7. 「📤 导出」下载 Markdown 简报与 JSON 数据包；\n"
        "8. 切换到「💬 智能对话」用自然语言追问，回复附带引用证据与关联决策卡。"
    )

    st.markdown("### 🚀 启动方式")
    st.code(
        "set PYTHONPATH=src\n"
        ".venv\\Scripts\\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000\n"
        ".venv\\Scripts\\python.exe -m streamlit run app/dashboard.py --server.port 8501",
        language="bat",
    )
    st.markdown("### 🔌 API 端点")
    st.markdown(
        "- `GET /api/health`：服务/LLM/数据源/模块就绪状态\n"
        "- `GET /api/scenarios`：历史压力情景\n"
        "- `GET /api/decision?as_of=&scenario=&mode=`：多智能体预警决策卡\n"
        "- `POST /api/chat`：对话入口（ChatRequest → ChatResponse）\n"
        "- `GET /api/evidence/{evidence_id}`：证据详情\n"
        "- `GET /api/data-cards`：数据卡\n"
        "- `GET /api/trace/{run_id}`：审计轨迹\n"
        "- `GET /docs`：交互式 OpenAPI 文档"
    )
    st.markdown("### 🧩 当前运行状态")
    llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
    columns = st.columns(3)
    columns[0].metric("核心模块", "就绪" if readiness.get("ready") else "待就绪")
    columns[1].metric("LLM 模式", "mock" if (isinstance(llm, dict) and llm.get("mock")) else "真实调用")
    columns[2].metric("待就绪模块数", len(readiness.get("pending_modules") or []))
    st.caption("本演示使用公开数据与历史压力情景，仅用于研究与演示，不构成投资建议。")


# --------------------------------------------------------------------------- #
# 通用小节 / 空状态
# --------------------------------------------------------------------------- #
def section_title(text: str, icon: str = "") -> None:
    prefix = f"{icon} " if icon else ""
    st.markdown(f'<div class="cbr-section-title">{_esc(prefix + text)}</div>', unsafe_allow_html=True)


def render_page_footer(decision: dict[str, Any] | None = None) -> None:
    decision = to_dict(decision)
    st.markdown('<hr class="cbr-divider" />', unsafe_allow_html=True)
    st.caption(
        "CBR-MAW · 决策支持与演示层（L6）　|　"
        "时点回放：仅使用 as_of 当日可得信息　|　"
        f"run_id：{decision.get('run_id') or '—'}　|　"
        "研究演示用途，不构成投资建议"
    )
