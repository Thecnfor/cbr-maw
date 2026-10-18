"""运行态缓存，以及证据 / 审计轨迹的「三层兜底」解析。

背景：``schemas.DecisionCard`` 本身**不携带** Evidence 列表，只有 evidence_id
引用（``RiskCard.evidence_ids``、``Claim.evidence_ids``、``Conflict.evidence_ids``、
``RiskSignal.evidence_id``）与 ``trace_ref``。为了让 UI 证据板与
``GET /api/evidence/{id}`` / ``GET /api/trace/{run_id}`` 在核心模块实现方式不完全
一致时仍可工作，本模块按以下顺序解析：

1. **编排层显式接口**：``orchestrator.get_evidence(evidence_id)`` /
   ``orchestrator.get_trace(run_id)`` / ``orchestrator.blackboard.get_evidence`` /
   黑板上的 evidence 字典等（duck-typing，兼容多种命名）；
2. **本进程缓存**：API/UI 生成决策后自动登记 ``DecisionCard.signal`` 与
   ``TraceEvent.detail`` 中内嵌的证据对象；
3. **artifacts 目录**：``artifacts/evidence/...`` 与 ``artifacts/traces/<run_id>.jsonl``
   等约定路径（见架构 3.6/3.7）。

本模块不依赖 FastAPI，API 与 Streamlit 共用。
"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from cbr.schemas import (
    ChatResponse,
    DecisionCard,
    Evidence,
    RiskSignal,
    SourceRef,
    TraceEvent,
)

_MAX_RUNS = 64
_MAX_EVIDENCE = 512

_RUNS: "OrderedDict[str, DecisionCard]" = OrderedDict()
_EVIDENCE: "OrderedDict[str, Evidence]" = OrderedDict()

_TRACE_FILE_SUFFIXES = (".jsonl", ".json")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def reset_cache() -> None:
    """清空进程内缓存（测试 / 重新加载服务时使用）。"""
    _RUNS.clear()
    _EVIDENCE.clear()


def _remember(mapping: "OrderedDict[str, Any]", key: str, value: Any, limit: int) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > limit:
        mapping.popitem(last=False)


def _dump(obj: Any) -> dict[str, Any]:
    """把 pydantic 模型 / dict 统一成 JSON 安全 dict（失败返回空 dict）。"""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:  # pragma: no cover - pydantic v1 兼容
            return dump()
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _coerce_date(value: Any, default: date | None = None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return default
    return default


def as_decision_card(obj: Any) -> DecisionCard | None:
    """尽力把编排层返回值解析为 DecisionCard（解析失败返回 None）。"""
    if obj is None:
        return None
    if isinstance(obj, DecisionCard):
        return obj
    if isinstance(obj, ChatResponse):
        return obj.decision
    payload = _dump(obj)
    if not payload:
        return None
    try:
        return DecisionCard.model_validate(payload)
    except Exception:  # noqa: BLE001 - 编排层返回不合约时由调用方降级
        return None


def as_evidence(obj: Any) -> Evidence | None:
    """尽力把任意对象解析为 Evidence（不是证据时返回 None）。"""
    if obj is None:
        return None
    if isinstance(obj, Evidence):
        return obj
    payload = _dump(obj)
    if not payload or not payload.get("evidence_id"):
        return None
    try:
        return Evidence.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None


def as_trace_event(obj: Any) -> TraceEvent | None:
    if obj is None:
        return None
    if isinstance(obj, TraceEvent):
        return obj
    payload = _dump(obj)
    if not payload:
        return None
    try:
        return TraceEvent.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# 证据：登记、收集与解析
# --------------------------------------------------------------------------- #
def evidence_from_signal(signal: RiskSignal | Mapping[str, Any] | None) -> Evidence | None:
    """把共享风险信号（RiskSignal）包装成一条 SIGNAL 证据，供证据板展示/复查。"""
    payload = _dump(signal)
    evidence_id = payload.get("evidence_id")
    if not evidence_id:
        return None
    as_of = _coerce_date(payload.get("as_of"))
    if as_of is None:
        return None
    horizons = payload.get("horizons") or {}
    value: float | None = None
    try:
        numeric = {int(k): float(v) for k, v in dict(horizons).items() if v is not None}
        if numeric:
            value = numeric.get(20, max(numeric.values()))
    except (TypeError, ValueError):
        value = None
    summary_bits: list[str] = []
    if horizons:
        try:
            summary_bits.append(
                "；".join(f"{int(k)}日 {float(v):.1%}" for k, v in dict(horizons).items())
            )
        except (TypeError, ValueError):
            pass
    if payload.get("percentile") is not None:
        try:
            summary_bits.append(f"历史分位 {float(payload['percentile']):.1%}")
        except (TypeError, ValueError):
            pass
    return Evidence(
        evidence_id=str(evidence_id),
        kind="signal",
        as_of=as_of,
        title="共享多模态融合风险信号",
        summary="；".join(summary_bits),
        payload=payload,
        unit=None,
        value=value,
        source=SourceRef(
            name=str(payload.get("model_version") or "多模态融合预测器"),
            extra={"label_version": payload.get("label_version")},
        ),
        produced_by="fusion",
        verified=None,
    )


def evidence_in_trace_event(event: TraceEvent | Mapping[str, Any] | None) -> list[Evidence]:
    """从一条 trace 事件的 ``detail`` 中递归挖掘内嵌的 Evidence 对象。"""
    found: list[Evidence] = []
    seen: set[str] = set()

    def walk(node: Any, depth: int) -> None:
        if depth > 5 or node is None:
            return
        if isinstance(node, Mapping):
            if "evidence_id" in node and ("kind" in node or "title" in node):
                evidence = as_evidence(node)
                if evidence is not None and evidence.evidence_id not in seen:
                    seen.add(evidence.evidence_id)
                    found.append(evidence)
                return
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, depth + 1)

    payload = _dump(event)
    walk(payload.get("detail"), 0)
    return found


def evidence_from_trace_events(
    events: Iterable[TraceEvent | Mapping[str, Any]] | None,
) -> list[Evidence]:
    """把轨迹中出现的证据对象去重收集起来，并登记进进程缓存。"""
    collected: "OrderedDict[str, Evidence]" = OrderedDict()
    for event in events or []:
        for evidence in evidence_in_trace_event(event):
            collected.setdefault(evidence.evidence_id, evidence)
    for evidence in collected.values():
        _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
    return list(collected.values())


def decision_evidence(card: Any) -> list[Evidence]:
    """取出 DecisionCard 内嵌的黑板证据快照（schemas 中 ``DecisionCard.evidence``）。"""
    decision = as_decision_card(card)
    if decision is None:
        return []
    evidence_list = getattr(decision, "evidence", None) or []
    return [item for item in evidence_list if isinstance(item, Evidence)]


def remember_decision(card: Any) -> DecisionCard | None:
    """登记一次决策运行：缓存 DecisionCard 与黑板证据快照。"""
    decision = as_decision_card(card)
    if decision is None:
        return None
    if decision.run_id:
        _remember(_RUNS, str(decision.run_id), decision, _MAX_RUNS)
    for evidence in decision_evidence(decision):
        _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
    signal_evidence = evidence_from_signal(decision.signal)
    if signal_evidence is not None and signal_evidence.evidence_id not in _EVIDENCE:
        _remember(_EVIDENCE, signal_evidence.evidence_id, signal_evidence, _MAX_EVIDENCE)
    return decision


def cached_decision(run_id: str | None) -> DecisionCard | None:
    if not run_id:
        return None
    return _RUNS.get(str(run_id))


def referenced_evidence_ids(card: Any) -> list[str]:
    """按出现顺序收集决策卡/风险卡/主张/冲突引用的证据 id（去重）。"""
    decision = as_decision_card(card)
    ids: "OrderedDict[str, None]" = OrderedDict()

    def add(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text and text not in ids:
            ids[text] = None

    if decision is None:
        return []
    for evidence in decision_evidence(decision):
        add(evidence.evidence_id)
    add(getattr(decision.signal, "evidence_id", None))
    cards = getattr(decision, "cards", None) or {}
    for risk_card in cards.values():
        add(getattr(risk_card, "base_signal_ref", None))
        for evidence_id in getattr(risk_card, "evidence_ids", None) or []:
            add(evidence_id)
        for metric in getattr(risk_card, "key_metrics", None) or []:
            add(getattr(metric, "evidence_id", None))
        for claim in getattr(risk_card, "claims", None) or []:
            for evidence_id in getattr(claim, "evidence_ids", None) or []:
                add(evidence_id)
    for conflict in getattr(decision, "conflicts", None) or []:
        for evidence_id in getattr(conflict, "evidence_ids", None) or []:
            add(evidence_id)
    return list(ids.keys())


def _artifacts_dir(service: Any) -> Path | None:
    """解析 artifacts 根目录（优先用 Service，其次 configs/app.yaml）。"""
    try:
        path = service.artifacts_dir()
        if path:
            return Path(path)
    except Exception:  # noqa: BLE001 - 服务可能未装配
        pass
    try:
        from cbr.config import load_settings, resolve_path

        return resolve_path(load_settings().paths.artifacts).resolve()
    except Exception:  # noqa: BLE001
        return None


def _resolve_trace_ref(ref: str | Path | None, service: Any) -> Path | None:
    if not ref:
        return None
    try:
        path = Path(ref)
    except (TypeError, ValueError):
        return None
    if path.is_absolute():
        return path if path.exists() else None
    candidates: list[Path] = [path]
    artifacts = _artifacts_dir(service)
    if artifacts is not None:
        candidates.extend([artifacts / path, artifacts.parent / path])
    try:
        from cbr.config import ROOT

        candidates.append(ROOT / path)
    except Exception:  # noqa: BLE001
        pass
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_trace_file(path: Path) -> list[TraceEvent]:
    """读取 JSONL / JSON 轨迹文件（容忍坏行，不抛异常）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    stripped = text.strip()
    if not stripped:
        return []
    rows: list[Any] = []
    if path.suffix.lower() == ".jsonl" or not stripped.startswith(("[", "{")):
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    else:
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            rows = data
        elif isinstance(data, Mapping):
            rows = data.get("events") or data.get("trace") or []
    events: list[TraceEvent] = []
    for row in rows:
        event = as_trace_event(row)
        if event is not None:
            events.append(event)
    return events


def _trace_candidate_files(service: Any, run_id: str) -> list[Path]:
    artifacts = _artifacts_dir(service)
    if artifacts is None:
        return []
    candidates = [
        artifacts / "traces" / f"{run_id}.jsonl",
        artifacts / "traces" / f"{run_id}.json",
        artifacts / "traces" / run_id,
        artifacts / "runs" / run_id / "trace.jsonl",
        artifacts / "runs" / run_id / "traces.jsonl",
        artifacts / "runs" / run_id / "trace.json",
    ]
    try:
        candidates.extend(sorted((artifacts / "runs" / run_id / "traces").glob("*.jsonl")))
    except OSError:
        pass
    try:
        candidates.extend(sorted((artifacts / "traces").glob(f"{run_id}*.jsonl")))
    except OSError:
        pass
    return candidates


def _normalize_trace(value: Any, service: Any) -> list[TraceEvent] | None:
    """把各种形态的 trace 返回值统一成 list[TraceEvent]；无法识别返回 None。"""
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        path = _resolve_trace_ref(value, service)
        return read_trace_file(path) if path is not None else None
    if isinstance(value, TraceEvent):
        return [value]
    if isinstance(value, Mapping):
        for key in ("events", "trace", "items", "records"):
            if key in value:
                nested = _normalize_trace(value[key], service)
                if nested is not None:
                    return nested
        row = as_trace_event(value)
        return [row] if row is not None else None
    if isinstance(value, (list, tuple)):
        events: list[TraceEvent] = []
        for item in value:
            if isinstance(item, (str, Path)):
                path = _resolve_trace_ref(item, service)
                if path is not None:
                    events.extend(read_trace_file(path))
                continue
            event = as_trace_event(item)
            if event is not None:
                events.append(event)
        return events
    return None


def find_trace(service: Any, run_id: str | None) -> list[TraceEvent] | None:
    """解析某次运行的审计轨迹；找不到返回 None（由调用方给 404 / 友好提示）。"""
    if not run_id:
        return None
    identifier = str(run_id)
    orchestrator = getattr(service, "orchestrator", None) if service is not None else None
    targets = [orchestrator, getattr(service, "trace_store", None)]
    if orchestrator is not None:
        targets.extend(
            [
                getattr(orchestrator, "trace_store", None),
                getattr(orchestrator, "tracer", None),
            ]
        )

    # 1) 编排层显式接口
    for target in targets:
        if target is None:
            continue
        for name in ("get_trace", "load_trace", "find_trace", "read_trace", "trace"):
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                result = method(identifier)
            except TypeError:
                try:
                    result = method(run_id=identifier)
                except Exception:  # noqa: BLE001
                    result = None
            except Exception:  # noqa: BLE001
                result = None
            normalized = _normalize_trace(result, service)
            if normalized:  # 空列表视为「未找到」，继续尝试后续兜底
                return normalized

    # 2) 编排层属性（dict 仓库 / list 集合）
    for target in targets:
        if target is None:
            continue
        for name in ("traces", "trace_store", "trace_index", "_traces", "events"):
            store = getattr(target, name, None)
            if isinstance(store, Mapping) and identifier in store:
                normalized = _normalize_trace(store[identifier], service)
                if normalized:
                    return normalized
            elif isinstance(store, (list, tuple)) and store:
                normalized = _normalize_trace(store, service)
                if normalized:
                    matched = [e for e in normalized if e.run_id in ("", identifier)]
                    if matched:
                        return matched

    # 3) 已缓存决策卡上的 trace_ref
    card = cached_decision(identifier)
    if card is not None:
        path = _resolve_trace_ref(getattr(card, "trace_ref", None), service)
        if path is not None:
            events = read_trace_file(path)
            if events:
                return events

    # 4) artifacts 约定路径
    for path in _trace_candidate_files(service, identifier):
        if path.is_file():
            events = read_trace_file(path)
            if events:
                return events
    return None


def _evidence_candidate_files(service: Any, evidence_id: str) -> list[Path]:
    artifacts = _artifacts_dir(service)
    if artifacts is None:
        return []
    candidates = [
        artifacts / "evidence" / f"{evidence_id}.json",
        artifacts / "evidence" / evidence_id / "evidence.json",
        artifacts / "evidence.jsonl",
    ]
    try:
        candidates.extend(sorted((artifacts / "evidence").glob(f"**/{evidence_id}.json")))
    except OSError:
        pass
    try:
        candidates.extend(sorted((artifacts / "runs").glob(f"*/evidence/{evidence_id}.json")))
    except OSError:
        pass
    try:
        candidates.extend(sorted((artifacts / "runs").glob("*/evidence.jsonl")))
    except OSError:
        pass
    return candidates


def _load_evidence_from_artifacts(service: Any, evidence_id: str) -> Evidence | None:
    for path in _evidence_candidate_files(service, evidence_id):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".jsonl":
            for line in read_trace_file_text_lines(path):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                evidence = as_evidence(row)
                if evidence is not None and evidence.evidence_id == evidence_id:
                    return evidence
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates: Iterable[Any] = data if isinstance(data, list) else [data]
        for row in candidates:
            evidence = as_evidence(row)
            if evidence is not None and evidence.evidence_id == evidence_id:
                return evidence
    return None


def read_trace_file_text_lines(path: Path) -> list[str]:
    """按行读取文本（JSONL 专用，容忍编码/IO 错误）。"""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def find_evidence(service: Any, evidence_id: str | None) -> Evidence | None:
    """解析一条证据：显式接口 -> 进程缓存 -> artifacts 文件。"""
    if evidence_id is None:
        return None
    identifier = str(evidence_id).strip()
    if not identifier:
        return None
    if identifier in _EVIDENCE:
        return _EVIDENCE[identifier]

    orchestrator = getattr(service, "orchestrator", None) if service is not None else None
    targets = [orchestrator, getattr(orchestrator, "blackboard", None) if orchestrator else None,
               getattr(orchestrator, "board", None) if orchestrator else None,
               getattr(service, "blackboard", None) if service is not None else None]

    # 1) 显式方法
    for target in targets:
        if target is None:
            continue
        for name in ("get_evidence", "find_evidence", "lookup_evidence", "evidence"):
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                result = method(identifier)
            except TypeError:
                try:
                    result = method(evidence_id=identifier)
                except Exception:  # noqa: BLE001
                    result = None
            except Exception:  # noqa: BLE001
                result = None
            evidence = as_evidence(result)
            if evidence is not None:
                _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
                return evidence

    # 2) 黑板上的证据仓库（dict / list）
    for target in targets:
        if target is None:
            continue
        for name in ("evidence", "evidence_store", "evidence_index", "evidence_by_id", "_evidence"):
            store = getattr(target, name, None)
            if isinstance(store, Mapping) and identifier in store:
                evidence = as_evidence(store[identifier])
                if evidence is not None:
                    _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
                    return evidence
            elif isinstance(store, (list, tuple)):
                for item in store:
                    evidence = as_evidence(item)
                    if evidence is not None and evidence.evidence_id == identifier:
                        _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
                        return evidence

    # 3) artifacts 文件
    evidence = _load_evidence_from_artifacts(service, identifier)
    if evidence is not None:
        _remember(_EVIDENCE, evidence.evidence_id, evidence, _MAX_EVIDENCE)
        return evidence
    return None


def collect_evidence(service: Any, card: Any) -> tuple[list[Evidence], list[str]]:
    """汇总一张决策卡引用的全部证据。

    Returns:
        ``(evidences, missing_ids)``。``missing_ids`` 是当前服务/artifacts 都
        拿不到内容的引用 id，UI 以「占位提示」展示而不是报错。
    """
    decision = as_decision_card(card)
    found: "OrderedDict[str, Evidence]" = OrderedDict()
    missing: "OrderedDict[str, None]" = OrderedDict()

    if decision is not None:
        # 1) DecisionCard 内嵌的黑板证据快照（schemas.DecisionCard.evidence）
        for evidence in decision_evidence(decision):
            found.setdefault(evidence.evidence_id, evidence)
        # 2) trace 中内嵌的证据
        trace_events = find_trace(service, decision.run_id) or []
        for evidence in evidence_from_trace_events(trace_events):
            found.setdefault(evidence.evidence_id, evidence)
        # 3) 其余被引用但未内嵌的证据：走编排层接口 / artifacts
        for evidence_id in referenced_evidence_ids(decision):
            if evidence_id in found:
                continue
            evidence = find_evidence(service, evidence_id)
            if evidence is not None:
                found.setdefault(evidence.evidence_id, evidence)
            elif evidence_id not in found:
                missing.setdefault(evidence_id, None)
    return list(found.values()), list(missing.keys())


def chat_response_decision(response: Any) -> DecisionCard | None:
    """从 ChatResponse（或 dict）中取出关联决策卡。"""
    if response is None:
        return None
    if isinstance(response, ChatResponse):
        return response.decision
    payload = _dump(response)
    decision = payload.get("decision")
    return as_decision_card(decision) if decision else None
