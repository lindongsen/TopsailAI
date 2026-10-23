"""Ownership observations and fail-closed boundaries (author: DawsonLin)."""
import json
import os
from unittest.mock import Mock

import psutil
import pytest

from topsailai.context.session_activity import ActivityState as State, SessionActivityProbe, observe_process


def record(root, sid="a.b[1]", pid=123, suffix="meta"):
    """Create an exact owner fixture without touching production state."""
    path = root / f"{sid}.{pid}.session.{suffix}"
    path.write_text(json.dumps({"session_id": sid, "pid": pid, "status": "completed"}))
    return path


@pytest.mark.parametrize("state", list(State))
def test_owner_states(tmp_path, state):
    """Terminal metadata never overrides the observed process state."""
    record(tmp_path)
    probe = SessionActivityProbe((tmp_path,), lambda pid: state)
    assert probe.observe("a.b[1]").state == state
    assert probe.can_clean("a.b[1]") == (state == State.STOPPED)


@pytest.mark.parametrize("suffix", ["stdout", "stderr", "events", "pipe", "agent2llm_inject_messages.jsonl"])
def test_fallback_inventory(tmp_path, suffix):
    """Fallback records are inspected by name without reading their payload."""
    record(tmp_path, suffix=suffix)
    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).can_clean("a.b[1]")


def test_multiple_owners_and_pid_reuse(tmp_path):
    """Any live PID protects all records even without a birth identity token."""
    record(tmp_path, pid=123)
    record(tmp_path, pid=456)
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.RUNNING if pid == 456 else State.STOPPED)
    assert not probe.can_clean("a.b[1]")


@pytest.mark.parametrize("content", ["{broken", "[]", '{"pid":123}', '{"pid":true,"session_id":"a.b[1]"}', '{"pid":123,"session_id":"other"}'])
def test_corrupt_records(tmp_path, content):
    """Bad metadata cannot be rescued by an absent PID or fallback file."""
    record(tmp_path).write_text(content)
    record(tmp_path, suffix="stdout")
    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).observe("a.b[1]").state == State.UNKNOWN


def test_missing_empty_wrong_home_and_prefix(tmp_path):
    """No evidence and unrelated prefixes do not authorize cleanup."""
    record(tmp_path, sid="a.b[1].other")
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)
    assert not probe.can_clean("a.b[1]")
    assert not probe.can_clean("a.b[1].other", "/unverified-home")
    assert not SessionActivityProbe((tmp_path / "missing",)).can_clean("a")
    assert not SessionActivityProbe().can_clean("a")


@pytest.mark.parametrize("session_id", ["", [], {}])
def test_invalid_single_session_id_is_unknown(tmp_path, session_id):
    """Invalid single-session input fails closed without requiring hashability."""
    observation = SessionActivityProbe((tmp_path,)).observe(session_id)

    assert observation.state == State.UNKNOWN
    assert observation.reason == "missing local authority"


def test_malformed_pid_and_partial_record(tmp_path):
    """Potentially matching malformed records retain uncertainty."""
    record(tmp_path)
    (tmp_path / "a.b[1].bad.session.meta").write_text("{}")
    assert not SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).can_clean("a.b[1]")


def test_real_process_is_protected(tmp_path):
    """The real portable observer protects this live process without signals."""
    record(tmp_path, pid=os.getpid())
    assert not SessionActivityProbe((tmp_path,)).can_clean("a.b[1]")


@pytest.mark.parametrize("error, expected", [(psutil.NoSuchProcess(123), State.STOPPED), (psutil.AccessDenied(123), State.UNKNOWN), (OSError("denied"), State.UNKNOWN)])
def test_process_probe_errors(monkeypatch, error, expected):
    """Only confirmed process absence permits reclamation."""
    monkeypatch.setattr("topsailai.context.session_activity.psutil.Process", Mock(side_effect=error))
    assert observe_process(123) == expected


def test_recheck_observes_new_owner(tmp_path):
    """There is no cached stopped decision across deletion attempts."""
    record(tmp_path)
    observer = Mock(side_effect=[State.STOPPED, State.RUNNING])
    probe = SessionActivityProbe((tmp_path,), observer)
    assert probe.can_clean("a.b[1]")
    assert not probe.can_clean("a.b[1]")


def test_permission_and_inventory_change(tmp_path, monkeypatch):
    """Unreadable inventories and concurrent publication cannot allow cleanup."""
    record(tmp_path)
    original = type(tmp_path).iterdir
    def denied(path):
        """Simulate an inaccessible local evidence root."""
        raise PermissionError("test inventory denied")
    with monkeypatch.context() as context:
        context.setattr(type(tmp_path), "iterdir", denied)
        assert not SessionActivityProbe((tmp_path,)).can_clean("a.b[1]")
    def changing(pid):
        """Publish another owner while the snapshot is inspected."""
        record(tmp_path, pid=456)
        return State.STOPPED
    assert not SessionActivityProbe((tmp_path,), changing).can_clean("a.b[1]")


def test_stat_access_time_is_not_identity(tmp_path):
    """Reading valid metadata must not invalidate its own stopped evidence."""
    path = record(tmp_path)
    os.utime(path, (1, 1))
    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).can_clean("a.b[1]")


def test_invalid_metadata_and_symlink(tmp_path):
    """Do not follow symlinked metadata or accept oversized payloads."""
    path = record(tmp_path)
    path.write_text(" " * 65537 + "{}")
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)
    assert not probe.can_clean("a.b[1]")


def test_metadata_symlink_and_replacement(tmp_path, monkeypatch):
    """Reject nonregular metadata and replacement during the read boundary."""
    from pathlib import Path
    path = record(tmp_path)
    target = tmp_path / "target"
    target.write_text(path.read_text())
    link = tmp_path / "linked.123.session.meta"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)
    assert not probe.can_clean("linked")
    original = Path.lstat
    calls = 0
    def replace_during_stat(candidate):
        """Change file contents before the second identity observation."""
        nonlocal calls
        if candidate == path:
            calls += 1
            if calls == 2:
                path.write_text(path.read_text() + " ")
        return original(candidate)
    monkeypatch.setattr(Path, "lstat", replace_during_stat)
    assert not probe.can_clean("a.b[1]")


def test_observe_many_uses_one_stable_inventory_per_root(tmp_path, monkeypatch):
    """Batch observation scans each root twice regardless of session count."""
    record(tmp_path, sid="first", pid=101)
    record(tmp_path, sid="second", pid=202)
    original = type(tmp_path).iterdir
    calls = 0

    def counted_iterdir(path):
        """Count complete root snapshots without changing their contents."""
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(type(tmp_path), "iterdir", counted_iterdir)
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)

    observations = probe.observe_many(("first", "second"))

    assert observations["first"].state == State.STOPPED
    assert observations["second"].state == State.STOPPED
    assert calls == 2


def test_observe_many_preserves_prefix_conflict_uncertainty(tmp_path):
    """A longer session owner remains malformed evidence for its shorter prefix."""
    record(tmp_path, sid="alpha", pid=101)
    record(tmp_path, sid="alpha.child", pid=202)
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)

    observations = probe.observe_many(("alpha", "alpha.child"))

    assert observations["alpha"].state == State.UNKNOWN
    assert observations["alpha.child"].state == State.STOPPED


def test_observe_many_preserves_independent_session_states(tmp_path):
    """One live or uncertain session does not change another batch result."""
    record(tmp_path, sid="stopped", pid=101)
    record(tmp_path, sid="running", pid=202)
    record(tmp_path, sid="unknown", pid=303)
    states = {
        101: State.STOPPED,
        202: State.RUNNING,
        303: State.UNKNOWN,
    }
    probe = SessionActivityProbe((tmp_path,), states.__getitem__)

    observations = probe.observe_many(("stopped", "running", "unknown"))

    assert observations["stopped"].state == State.STOPPED
    assert observations["running"].state == State.RUNNING
    assert observations["unknown"].state == State.UNKNOWN
