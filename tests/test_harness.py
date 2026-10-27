"""执行 harness 层测试（进程内实现 + 远程适配器降级，不依赖外部服务）。"""

from __future__ import annotations

from cbr.harness import InProcessHarness, RemoteHarness, TaskSpec, build_harness, load_harness_settings


def test_load_harness_settings_defaults() -> None:
    settings = load_harness_settings()
    assert settings.get("backend") == "in-process"


def test_in_process_harness_dispatch_and_errors() -> None:
    harness = InProcessHarness(handlers={"echo": lambda task: {"got": task.payload}})
    ok = harness.run(TaskSpec(task_id="t1", kind="echo", payload={"x": 1}))
    assert ok.ok is True
    assert ok.output == {"got": {"x": 1}}
    assert ok.metadata["elapsed_ms"] >= 0

    missing = harness.run(TaskSpec(task_id="t2", kind="unknown"))
    assert missing.ok is False
    assert "未注册" in (missing.error or "")

    def boom(_task: TaskSpec) -> None:
        raise ValueError("kaboom")

    harness.register("boom", boom)
    failed = harness.run(TaskSpec(task_id="t3", kind="boom"))
    assert failed.ok is False
    assert "kaboom" in (failed.error or "")


def test_in_process_harness_info_lists_kinds() -> None:
    harness = InProcessHarness(handlers={"a": lambda task: None, "b": lambda task: None})
    info = harness.info()
    assert info["available"] is True
    assert info["kinds"] == ["a", "b"]


def test_build_harness_selects_backend() -> None:
    local = build_harness({"backend": "in-process"}, handlers={"x": lambda task: 1})
    assert isinstance(local, InProcessHarness)
    remote = build_harness({"backend": "remote", "base_url": "http://127.0.0.1:1"})
    assert isinstance(remote, RemoteHarness)


def test_remote_harness_degrades_when_unreachable() -> None:
    harness = RemoteHarness("http://127.0.0.1:1", timeout_seconds=0.5)
    assert harness.info()["available"] is False
    result = harness.run(TaskSpec(task_id="t1", kind="decision"))
    assert result.ok is False
    assert result.error
