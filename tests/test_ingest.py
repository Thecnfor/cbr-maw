"""实时智能抓取层测试（Lead 维护）。

覆盖：
- 来源配置加载与校验（未知序列 / 派生序列不可声明为可抓取）；
- PIT 增量写入幂等（同 (series_id, obs_date) 覆盖）；
- 缺口 / 陈旧度分析（missing / stale / 不可抓取）；
- 抓取智能体端到端（注入假抓取器，不走网络）：增量落库、备源回退、派生重算、报告；
- ``/api/ingest/*`` 端点契约（FakeService 隔离，refresh 用假智能体验证连接协调）。

全部用例离线运行，不访问真实网络。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from cbr.config import load_settings
from cbr.data.pit_store import PitStore
from cbr.ingest.agent import IngestAgent, load_source_specs
from cbr.ingest.contracts import FetchResult, SourceSpec
from cbr.ingest.derive import compute_derived, recompute_derived
from cbr.ingest.gaps import analyze_freshness, analyze_gaps, source_candidates
from cbr.schemas import IngestReport

AS_OF = dt.date(2026, 10, 27)


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #
class FakeFetcher:
    """返回预设观测行；可配置为抛错以触发备源回退。"""

    def __init__(self, spec: SourceSpec, observations: pd.DataFrame, *, fail: bool = False) -> None:
        self.spec = spec
        self._observations = observations
        self._fail = fail
        self.calls = 0

    def fetch(self, *, since=None, until, series_ids=None) -> FetchResult:  # noqa: ANN001
        self.calls += 1
        if self._fail:
            return FetchResult(source_id=self.spec.source_id, status="error", error="fake failure")
        frame = self._observations
        if series_ids:
            frame = frame[frame["series_id"].isin(series_ids)]
        return FetchResult(source_id=self.spec.source_id, status="ok", observations=frame.reset_index(drop=True))


def _obs(series_id: str, dates: list[str], values: list[float], unit: str = "点") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": series_id,
            "obs_date": pd.to_datetime(dates).date,
            "value": values,
            "release_time": pd.to_datetime(dates) + pd.Timedelta(hours=18),
            "source": "fake",
            "unit": unit,
        }
    )


def _store(tmp_path: Path) -> PitStore:
    store = PitStore(tmp_path / "pit.duckdb", read_only=False)
    store.initialize_schema()
    return store


# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #
def test_load_source_specs_from_repo_config() -> None:
    specs = load_source_specs()
    assert specs, "仓库应提供 configs/sources.yaml"
    kinds = {spec.kind for spec in specs}
    assert kinds.issubset({"http_csv", "http_json", "akshare", "rss"})
    assert any(spec.documents for spec in specs), "应至少有一个文本来源"
    # 同一序列可声明多个来源（主源 + 备源）
    candidates = source_candidates(specs, "market.cn_equity.csi300")
    assert len(candidates) >= 2


def test_source_spec_rejects_unknown_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "sources:\n  - id: bad\n    kind: http_csv\n    series: [no.such.series]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(Path.cwd())
    with pytest.raises(ValueError):
        load_source_specs(str(cfg))


def test_source_spec_rejects_derived_series(tmp_path: Path) -> None:
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        "sources:\n  - id: bad\n    kind: http_csv\n    series: [market.cn_bond.term_spread]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_source_specs(str(cfg))


# --------------------------------------------------------------------------- #
# PIT 增量写入
# --------------------------------------------------------------------------- #
def test_pit_upsert_is_idempotent_and_updates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _obs("market.global.vix", ["2026-10-20", "2026-10-21"], [18.0, 19.0])
    assert store.upsert_observations(first) == 2
    assert store.counts()["series_obs"] == 2
    # 重复写入（含更新值）不应新增行，但应覆盖旧值
    updated = _obs("market.global.vix", ["2026-10-21", "2026-10-22"], [20.0, 21.0])
    store.upsert_observations(updated)
    assert store.counts()["series_obs"] == 3
    values = dict(store.asof_values(AS_OF))
    assert values["market.global.vix"] == 21.0


def test_pit_upsert_documents_dedup_by_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    docs = pd.DataFrame(
        {
            "doc_id": ["a", "b"],
            "publish_time": ["2026-10-20 10:00:00", "2026-10-21 10:00:00"],
            "source": ["rss", "rss"],
            "title": ["t1", "t2"],
            "body": ["b1", "b2"],
            "url": [None, None],
            "hash": ["h1", "h1"],  # 同哈希 -> 去重
        }
    )
    assert store.upsert_documents(docs) == 1
    assert store.counts()["documents"] == 1


# --------------------------------------------------------------------------- #
# 缺口 / 陈旧度分析
# --------------------------------------------------------------------------- #
def test_analyze_gaps_marks_missing_and_stale(tmp_path: Path) -> None:
    settings = load_settings()
    specs = [
        SourceSpec(source_id="s_csi300", kind="http_json", series_ids=("market.cn_equity.csi300",)),
        SourceSpec(source_id="s_vix", kind="http_csv", series_ids=("market.global.vix",)),
    ]
    coverage = {
        "market.cn_equity.csi300": (dt.date(2026, 1, 1), dt.date(2026, 10, 27)),  # 新鲜
        "market.global.vix": (dt.date(2026, 1, 1), dt.date(2026, 10, 10)),  # 陈旧
    }
    tasks = analyze_gaps(coverage, specs, AS_OF, settings)
    by_id = {task.series_id: task for task in tasks}
    assert by_id["market.global.vix"].reason == "stale"
    assert "market.cn_equity.csi300" not in by_id  # 新鲜序列不进入计划
    # 未在 coverage 中的可抓取序列 -> missing
    tasks2 = analyze_gaps({}, specs, AS_OF, settings)
    ids2 = {task.series_id: task.reason for task in tasks2}
    assert ids2["market.global.vix"] == "missing"


def test_analyze_freshness_flags_derived_as_unfetchable() -> None:
    settings = load_settings()
    freshness = analyze_freshness({}, load_source_specs(), AS_OF, settings)
    derived = [f for f in freshness if f.series_id == "market.cn_bond.term_spread"][0]
    assert derived.fetchable is False
    assert derived.is_stale is False
    vix = [f for f in freshness if f.series_id == "market.global.vix"][0]
    assert vix.fetchable is True
    assert vix.is_stale is True  # 空库 -> 陈旧


# --------------------------------------------------------------------------- #
# 智能体端到端（注入假抓取器）
# --------------------------------------------------------------------------- #
def test_agent_run_writes_and_reports(tmp_path: Path) -> None:
    settings = load_settings()
    specs = [
        SourceSpec(source_id="s_csi300", kind="http_json", series_ids=("market.cn_equity.csi300",)),
        SourceSpec(source_id="s_vix", kind="http_csv", series_ids=("market.global.vix",)),
    ]
    store = _store(tmp_path)
    fetchers = {
        "s_csi300": FakeFetcher(specs[0], _obs("market.cn_equity.csi300", ["2026-10-26", "2026-10-27"], [3000, 3010])),
        "s_vix": FakeFetcher(specs[1], _obs("market.global.vix", ["2026-10-26"], [18.5])),
    }
    agent = IngestAgent(store, specs, settings, fetchers=fetchers)
    report = agent.run(AS_OF, mode="full")

    assert isinstance(report, IngestReport)
    assert report.n_observations == 3
    assert report.n_errors == 0
    assert set(report.written_series) >= {"market.cn_equity.csi300", "market.global.vix"}
    assert store.counts()["series_obs"] == 3
    # 数据卡覆盖期已刷新
    cards = {c.series_id: c for c in store.data_cards()}
    assert cards["market.global.vix"].coverage_end == dt.date(2026, 10, 26)


def test_agent_falls_back_to_alternate_source(tmp_path: Path) -> None:
    settings = load_settings()
    primary = SourceSpec(source_id="p", kind="http_json", series_ids=("market.cn_equity.csi300",))
    backup = SourceSpec(source_id="b", kind="http_json", series_ids=("market.cn_equity.csi300",))
    store = _store(tmp_path)
    fetchers = {
        "p": FakeFetcher(primary, _obs("market.cn_equity.csi300", [], []), fail=True),
        "b": FakeFetcher(backup, _obs("market.cn_equity.csi300", ["2026-10-27"], [3010])),
    }
    agent = IngestAgent(store, [primary, backup], settings, fetchers=fetchers)
    report = agent.run(AS_OF, series_ids=("market.cn_equity.csi300",), mode="forced")

    statuses = {r.source_id: r.status for r in report.results}
    assert statuses["p"] == "error"
    assert statuses["b"] == "ok"
    assert report.n_observations == 1
    assert store.counts()["series_obs"] == 1


def test_agent_recomputes_derived_series(tmp_path: Path) -> None:
    settings = load_settings()
    store = _store(tmp_path)
    store.upsert_observations(_obs("market.cn_bond.cgb_10y", ["2026-10-24", "2026-10-27"], [2.5, 2.6], unit="%"))
    store.upsert_observations(_obs("market.cn_bond.cgb_2y", ["2026-10-24", "2026-10-27"], [1.5, 1.5], unit="%"))
    written = recompute_derived(store, AS_OF, ["market.cn_bond.term_spread"])
    assert written.get("market.cn_bond.term_spread", 0) == 2
    values = dict(store.asof_values(AS_OF))
    assert values["market.cn_bond.term_spread"] == pytest.approx(110.0)  # (2.6-1.5)*100


def test_compute_derived_requires_inputs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    frame = compute_derived(store, "market.fx.cnh_cny_gap", AS_OF)
    assert frame.empty


# --------------------------------------------------------------------------- #
# API 端点
# --------------------------------------------------------------------------- #
def test_api_ingest_plan_and_freshness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from cbr.api.main import app
    from cbr.ingest import runtime

    runtime.reset_ingest_runtime()
    with TestClient(app) as client:
        plan = client.get("/api/ingest/plan")
        assert plan.status_code == 200
        assert isinstance(plan.json(), list)
        fresh = client.get("/api/ingest/freshness")
        assert fresh.status_code == 200
        assert any(item["series_id"] == "market.global.vix" for item in fresh.json())
        status = client.get("/api/ingest/status")
        assert status.status_code == 200
        assert "sources" in status.json()
    runtime.reset_ingest_runtime()


def test_api_ingest_refresh_coordinates_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from cbr.api import ingest as ingest_api
    from cbr.api.main import app

    events: list[str] = []

    class FakeProvider:
        def detach(self) -> None:
            events.append("detach")

        def reload(self) -> None:
            events.append("reload")

    class FakeService:
        def __init__(self) -> None:
            self.settings = load_settings()
            self.settings.data.pit_db = str(tmp_path / "pit.duckdb")
            self.provider = FakeProvider()

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        def run(self, as_of, series_ids=None, mode="gap", pre_run=None, on_written=None):  # noqa: ANN001
            if pre_run is not None:
                pre_run()
            if on_written is not None:
                on_written()
            return IngestReport(run_id="fake-run", as_of=as_of or AS_OF, mode=mode)

    monkeypatch.setattr(ingest_api, "IngestAgent", FakeAgent)
    fake_service = FakeService()

    import cbr.service as service_module

    monkeypatch.setattr(service_module, "get_service", lambda: fake_service)

    with TestClient(app) as client:
        resp = client.post("/api/ingest/refresh", json={"mode": "gap"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["run_id"] == "fake-run"
    # 写前 detach、写后 reload 的顺序必须成立
    assert events[0] == "detach"
    assert events[-1] == "reload"


def test_dig_supports_key_list_for_dotted_keys() -> None:
    """键本身含 "." 的端点（如腾讯 us.INX）需用键序列指定 JSON 路径。"""
    from cbr.ingest.sources import _dig

    rows = [["2026-10-27", "7697.49", "7699.47"]]
    payload = {"data": {"us.INX": {"day": rows}}}
    # 点分路径会被拆成 data/us/INX/day，无法命中含点的键
    assert _dig(payload, "data.us.INX.day") is None
    # 键序列可命中
    assert _dig(payload, ["data", "us.INX", "day"]) == rows
    # 字符串路径与 None 的既有语义不变
    assert _dig(payload, "data") == payload["data"]
    assert _dig(payload, None) is payload
