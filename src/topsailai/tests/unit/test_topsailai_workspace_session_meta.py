'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-07-30
  Purpose: Unit tests for workspace/session_meta.py.
'''

import json
import os
import time

import pytest

from topsailai.workspace import session_meta
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


@pytest.fixture(autouse=True)
def _isolate_meta_files(monkeypatch, tmp_path):
    """Redirect session metadata files into a temporary directory."""
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    yield


def _read_meta(path):
    with open(path, "r", encoding="utf-8") as fd:
        return json.load(fd)


def test_get_session_meta_path_with_session_id():
    path = session_meta.get_session_meta_path("abc")
    assert path.endswith(".session.meta")
    assert f"abc.{os.getpid()}.session.meta" in path


def test_get_session_meta_path_without_session_id(monkeypatch):
    monkeypatch.delenv("SESSION_ID", raising=False)
    monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
    path = session_meta.get_session_meta_path()
    assert path.endswith(f"topsailai.{os.getpid()}.session.meta")


def test_create_session_meta_writes_correct_json():
    class FakeLLM:
        model_name = "fake-model"

    class FakeAgent:
        agent_name = "FakeAgent"
        agent_type = "react"
        agent_role = "worker"
        llm_model = FakeLLM()

    path = session_meta.create_session_meta("s-001", FakeAgent())
    assert path is not None
    assert os.path.exists(path)

    meta = _read_meta(path)
    assert meta["version"] == 1
    assert meta["session_id"] == "s-001"
    assert meta["pid"] == os.getpid()
    assert meta["status"] == "running"
    assert meta["end_ts"] is None
    assert meta["agent_name"] == "FakeAgent"
    assert meta["agent_type"] == "react"
    assert meta["agent_role"] == "worker"
    assert meta["model_name"] == "fake-model"
    assert "files" in meta
    assert "events" in meta["files"]
    assert "stdout" in meta["files"]
    assert "feature_flags" in meta


def test_create_session_meta_without_agent():
    path = session_meta.create_session_meta("s-002")
    assert path is not None
    meta = _read_meta(path)
    assert meta["session_id"] == "s-002"
    assert meta["agent_name"] == ""
    assert meta["model_name"] == ""


def test_update_session_meta_status():
    session_meta.create_session_meta("s-003")
    session_meta.update_session_meta_status("completed", "s-003")

    path = session_meta.get_session_meta_path("s-003")
    meta = _read_meta(path)
    assert meta["status"] == "completed"
    assert meta["end_ts"] is not None


def test_update_session_meta_field():
    session_meta.create_session_meta("s-004")
    session_meta.update_session_meta_field("model_name", "new-model", "s-004")

    path = session_meta.get_session_meta_path("s-004")
    meta = _read_meta(path)
    assert meta["model_name"] == "new-model"


def test_update_session_meta_field_missing_file_is_best_effort(tmp_path):
    session_meta.update_session_meta_field("model_name", "x", "nonexistent-session")


def test_cleanup_removes_old_files(monkeypatch):
    # Create files with old and recent mtimes
    old_path = session_meta.get_session_meta_path("old")
    recent_path = session_meta.get_session_meta_path("recent")

    session_meta.create_session_meta("old")
    session_meta.create_session_meta("recent")

    old_time = time.time() - 10 * 86400
    os.utime(old_path, (old_time, old_time))

    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "7")
    monkeypatch.setenv("TOPSAILAI_SESSION_META_MAX_COUNT", "0")

    session_meta.cleanup_session_meta_files()

    assert not os.path.exists(old_path)
    assert os.path.exists(recent_path)


def test_cleanup_enforces_max_count(monkeypatch):
    paths = []
    for i in range(5):
        session_meta.create_session_meta(f"max-{i}")
        path = session_meta.get_session_meta_path(f"max-{i}")
        # stagger mtimes so sort order is deterministic
        os.utime(path, (time.time() - i, time.time() - i))
        paths.append(path)

    monkeypatch.setenv("TOPSAILAI_SESSION_META_RETENTION_DAYS", "0")
    monkeypatch.setenv("TOPSAILAI_SESSION_META_MAX_COUNT", "2")

    session_meta.cleanup_session_meta_files()

    remaining = [p for p in paths if os.path.exists(p)]
    assert len(remaining) == 2
    # newest files survive
    assert remaining == paths[:2]


def test_atomic_write_is_atomic(tmp_path):
    path = str(tmp_path / "atomic.meta")
    session_meta._atomic_write(path, {"key": "value"})
    assert _read_meta(path)["key"] == "value"


def test_finalize_on_exit_marks_interrupted():
    path = session_meta.create_session_meta("s-atexit")
    session_meta._finalize_on_exit(path)

    meta = _read_meta(path)
    assert meta["status"] == "interrupted"
    assert meta["end_ts"] is not None


def test_finalize_on_exit_does_not_overwrite_completed():
    path = session_meta.create_session_meta("s-atexit-done")
    session_meta.update_session_meta_status("completed", "s-atexit-done")
    session_meta._finalize_on_exit(path)

    meta = _read_meta(path)
    assert meta["status"] == "completed"


def test_create_session_meta_best_effort_on_failure(monkeypatch, tmp_path):
    # Simulate a write failure by making _atomic_write raise.
    def _failing_atomic_write(path, data):
        raise OSError("simulated write failure")

    monkeypatch.setattr(session_meta, "_atomic_write", _failing_atomic_write)
    result = session_meta.create_session_meta("s-fail")
    assert result is None


def test_safe_session_meta_decorator_suppresses_exceptions(caplog):
    @session_meta.safe_session_meta
    def _failing_func():
        raise RuntimeError("intentional failure")

    result = _failing_func()
    assert result is None
    assert "intentional failure" in caplog.text
    assert "_failing_func" in caplog.text


def test_safe_session_meta_decorator_returns_value():
    @session_meta.safe_session_meta
    def _success_func():
        return "ok"

    assert _success_func() == "ok"
