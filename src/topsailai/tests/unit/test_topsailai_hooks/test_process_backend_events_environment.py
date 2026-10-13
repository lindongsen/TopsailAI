"""Controlled worker events-environment regressions. Author: DawsonLin."""

import json
import os
from pathlib import Path

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.tests.unit.test_topsailai_hooks.test_summary_events_observer_lifecycle import (
    ACTIVE, assert_recorded, emit, events, lifecycle, prepare,
)

EVENT_VARIABLES = (
    "TOPSAILAI_EVENTS_ENABLED",
    "TOPSAILAI_EVENTS_BUFFER_SIZE",
    "TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS",
    "TOPSAILAI_EVENTS_BACKEND",
    "TOPSAILAI_EVENTS_FILE_PATH",
    "TOPSAILAI_EVENTS_FILE_RETENTION_DAYS",
    "TOPSAILAI_EVENTS_FILE_MAX_COUNT",
    "TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT",
    "TOPSAILAI_EVENTS_FILE_FSYNC",
)
BASELINE = {
    "HOME", "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "TEMP", "TMP",
    "TMPDIR", "TOPSAILAI_HOME", "TOPSAILAI_HOOK_WORKER",
}
OPTIONAL = ("LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")


def test_exact_events_allowlist_preserves_values_and_excludes_host_state(tmp_path, monkeypatch):
    """Copy exact sentinels without broad environment inheritance or HOME overwrite."""
    values = {name: f"  sentinel-{index}=$HOME;unset\n" for index, name in enumerate(EVENT_VARIABLES)}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in OPTIONAL:
        monkeypatch.setenv(name, f"locale-{name}")
    for name in ("TOPSAILAI_HOME", "TOPSAILAI_UNRELATED", "TOPSAILAI_EVENTS_UNKNOWN",
                 "TOPSAILAI_SESSION_ID", "SESSION_ID", "UNRELATED_HOST_VALUE"):
        monkeypatch.setenv(name, "host-only")
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    environment = backend._worker_environment()
    assert set(environment) == BASELINE | set(EVENT_VARIABLES) | set(OPTIONAL)
    assert {name: environment[name] for name in EVENT_VARIABLES} == values
    for name in ("HOME", "TOPSAILAI_HOME", "TEMP", "TMP", "TMPDIR"):
        assert environment[name] == str(tmp_path)
    assert environment["TOPSAILAI_HOOK_WORKER"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PATH"] == os.environ.get("PATH", "")
    assert all(environment[name] == f"locale-{name}" for name in OPTIONAL)


def test_absent_events_variables_are_not_synthesized(tmp_path, monkeypatch):
    """Unset events settings stay absent and empty supplied strings remain exact."""
    for name in EVENT_VARIABLES + OPTIONAL:
        monkeypatch.delenv(name, raising=False)
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    assert set(backend._worker_environment()) == BASELINE
    for name in EVENT_VARIABLES:
        monkeypatch.setenv(name, "")
    environment = backend._worker_environment()
    assert set(environment) == BASELINE | set(EVENT_VARIABLES)
    assert all(environment[name] == "" for name in EVENT_VARIABLES)


@pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "configured-file"])
def test_captured_observer_honors_host_events_configuration(lifecycle, tmp_path, monkeypatch, enabled):
    """Real prepared workers honor disabling and the exact configured output path."""
    path = tmp_path / "host-configured.events"
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "1" if enabled else "0")
    monkeypatch.setenv("TOPSAILAI_EVENTS_BACKEND", "file")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_PATH", str(path))
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_RETENTION_DAYS", "0")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT", "0")
    monkeypatch.setenv("TOPSAILAI_HOME", str(tmp_path / "host-home"))
    monkeypatch.setenv("SESSION_ID", "host-session")
    runtime, _, root = lifecycle
    _, _, adapter = prepare(lifecycle)
    environment = runtime._backend._worker_environment()
    assert environment["TOPSAILAI_HOME"] == str(root)
    assert environment["TOPSAILAI_EVENTS_ENABLED"] == ("1" if enabled else "0")
    assert environment["TOPSAILAI_EVENTS_FILE_PATH"] == str(path)
    assert "SESSION_ID" not in environment
    assert_recorded(emit(adapter, ACTIVE[0], "host-configured"))
    assert events(lifecycle) == []
    assert not tuple(root.rglob("*.events"))
    assert not Path(os.environ["TOPSAILAI_HOME"]).exists()
    if not enabled:
        assert not path.exists()
        return
    observed = [json.loads(line) for line in path.read_text().splitlines() if line]
    summaries = [event for event in observed if event["event_type"] == "summary.hook.observed"]
    assert len(summaries) == 1
    assert summaries[0]["source"] == "hooks.summary_events_observer"
    assert summaries[0]["payload"]["point_name"] == ACTIVE[0].name
    assert summaries[0]["payload"]["operation_id"] == "host-configured"
    assert set(summaries[0]["payload"]) == ACTIVE[0].allowed_fields
