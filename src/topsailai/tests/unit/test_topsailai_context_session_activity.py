"""Ownership observations and fail-closed boundaries (author: DawsonLin)."""
import json
import os
import socket
from unittest.mock import Mock

import psutil
import pytest

from topsailai.context.session_activity import (
    ActivityState as State,
    SessionActivityProbe,
    normalize_home_path,
    observe_process,
)


def record(root, sid="a.b[1]", pid=123, suffix="meta", hostname=None):
    """Create an exact owner fixture without touching production state."""
    path = root / f"{sid}.{pid}.session.{suffix}"
    owner_host = socket.gethostname() if hostname is None else hostname
    path.write_text(json.dumps({
        "session_id": sid, "pid": pid, "hostname": owner_host, "status": "completed",
    }))
    return path


@pytest.mark.parametrize("state", list(State))
def test_owner_states(tmp_path, state):
    """Terminal metadata never overrides the observed process state."""
    record(tmp_path)
    probe = SessionActivityProbe((tmp_path,), lambda pid: state)
    assert probe.observe("a.b[1]").state == state
    assert probe.can_clean("a.b[1]") == (state == State.STOPPED)


@pytest.mark.parametrize("suffix", [
    "stdout",
    "stderr",
    "events",
    "pipe",
    "sock",
    "stats.jsonl",
    "stats.1.jsonl",
    "agent2llm_inject_messages.jsonl",
    "agent2llm_interrupt.flag",
    "agent2llm_interrupt.fbt_waiting",
    "agent2llm_interrupt.fbt_retry",
])
def test_auxiliary_inventory_requires_metadata(tmp_path, suffix):
    """Auxiliary records participate only beside strict owner metadata."""
    record(tmp_path)
    record(tmp_path, suffix=suffix)
    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).can_clean("a.b[1]")


def test_real_stats_writer_rotation_is_cleanable(tmp_path):
    """Production stats rotation remains recognized by the cleanup probe."""
    from topsailai.workspace.session_stats_writer import StatsWriter, StorageConfig

    writer = StatsWriter(
        "a_b",
        directory=tmp_path,
        diagnostic=lambda category, name: True,
        config=StorageConfig(max_size_bytes=4096),
    )
    line = b"{" + b"x" * 4093 + b"}\n"
    assert writer.append(line).ok
    assert writer.append(line).ok
    rotated = writer.backup(1)
    assert rotated.exists()
    record(tmp_path, sid="a_b", pid=writer.pid)

    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED)
    assert probe.observe("a_b").state == State.STOPPED
    assert probe.can_clean("a_b")


@pytest.mark.parametrize("suffix", ["stats.jsonl", "sock", "agent2llm_interrupt.flag"])
def test_framework_auxiliary_records_do_not_block_cleanup(tmp_path, suffix):
    """Known auxiliary records do not invalidate strict owner metadata."""
    record(tmp_path, suffix="meta")
    (tmp_path / f"a.b[1].123.session.{suffix}").write_text("auxiliary")
    observation = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).observe("a.b[1]")

    assert observation.state == State.STOPPED
    assert observation.reason == "all verified local owners absent"


def test_foreign_owner_missing_local_pid_is_unknown(tmp_path):
    """A remote owner cannot be declared stopped from this host's process table."""
    record(tmp_path, hostname="remote-host")
    probe = SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED, hostname="local-host")

    assert probe.observe("a.b[1]").state == State.UNKNOWN
    assert not probe.can_clean("a.b[1]")


def test_running_metadata_blocks_same_hostname_pid_absence(tmp_path):
    """A running owner is protected across same-hostname PID namespaces."""
    path = record(tmp_path)
    data = json.loads(path.read_text())
    data["status"] = "running"
    path.write_text(json.dumps(data))

    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).observe(
        "a.b[1]"
    ).state == State.UNKNOWN


@pytest.mark.parametrize("hostname", ["", None, [], 42])
def test_missing_or_invalid_hostname_is_unknown(tmp_path, hostname):
    """Incomplete host identity never authorizes destructive cleanup."""
    path = record(tmp_path)
    data = json.loads(path.read_text())
    data["hostname"] = hostname
    path.write_text(json.dumps(data))

    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).observe(
        "a.b[1]"
    ).state == State.UNKNOWN


def test_live_endpoint_protects_foreign_owner(tmp_path):
    """A responding endpoint is positive liveness evidence on any host."""
    record(tmp_path, hostname="remote-host")
    endpoint = Mock(return_value=True)
    process = Mock(return_value=State.STOPPED)
    probe = SessionActivityProbe(
        (tmp_path,), process, endpoint_observer=endpoint, hostname="local-host",
    )

    assert probe.observe("a.b[1]").state == State.RUNNING
    endpoint.assert_called_once_with(tmp_path / "a.b[1].123.session.sock")
    process.assert_not_called()


def test_endpoint_probe_failure_blocks_cleanup(tmp_path):
    """A broken liveness check cannot become deletion authorization."""
    record(tmp_path)
    endpoint = Mock(side_effect=OSError("probe failed"))
    process = Mock(return_value=State.STOPPED)
    probe = SessionActivityProbe(
        (tmp_path,), process, endpoint_observer=endpoint,
    )

    assert probe.observe("a.b[1]").state == State.UNKNOWN
    assert not probe.can_clean("a.b[1]")
    process.assert_not_called()


def test_default_endpoint_probe_failure_blocks_cleanup(tmp_path, monkeypatch):
    """The production endpoint adapter preserves uncertain socket failures."""
    record(tmp_path)
    (tmp_path / "a.b[1].123.session.sock").write_text("endpoint")
    process = Mock(return_value=State.STOPPED)
    monkeypatch.setattr(
        "topsailai.context.session_activity.stat.S_ISSOCK",
        Mock(return_value=True),
    )
    monkeypatch.setattr(
        "topsailai.context.session_activity.socket.socket",
        Mock(side_effect=PermissionError("probe denied")),
    )

    probe = SessionActivityProbe((tmp_path,), process)

    assert probe.observe("a.b[1]").state == State.UNKNOWN
    assert not probe.can_clean("a.b[1]")
    process.assert_not_called()


def test_each_owner_pid_requires_its_own_metadata(tmp_path):
    """Auxiliary files for another PID cannot borrow one owner's metadata."""
    record(tmp_path, pid=123)
    record(tmp_path, pid=456, suffix="stdout")

    assert SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).observe(
        "a.b[1]"
    ).state == State.UNKNOWN


def test_unknown_suffix_still_fails_closed(tmp_path):
    """An unrecognized owner-like record keeps cleanup unauthorized."""
    record(tmp_path)
    (tmp_path / "a.b[1].123.session.unknown_suffix").write_text("{}")

    assert not SessionActivityProbe((tmp_path,), lambda pid: State.STOPPED).can_clean("a.b[1]")


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


def test_symlinked_home_authorizes_cleanup_with_the_folder_constants_spelling(tmp_path):
    """A symlinked home must authorize cleanup when both sides share one spelling.

    The folder constants normalize the home with ``os.path.abspath``, which keeps
    symbolic links unresolved, and that exact value is what the database records.
    A probe that resolved its roots would compare a resolved root against an
    unresolved recorded home and refuse every deletion.
    """
    real = tmp_path / "real_home"
    (real / "workspace" / "task").mkdir(parents=True)
    link = tmp_path / "link_home"
    link.symlink_to(real, target_is_directory=True)
    record(link / "workspace" / "task")

    probe = SessionActivityProbe((link / "workspace" / "task",), lambda pid: State.STOPPED)

    observation = probe.observe("a.b[1]", home=str(link))

    assert observation.state == State.STOPPED
    assert probe.can_clean("a.b[1]", home=str(link))


def test_resolved_home_spelling_is_still_refused(tmp_path):
    """A home that is not an admitted root stays fail-closed after normalization."""
    real = tmp_path / "real_home"
    (real / "workspace" / "task").mkdir(parents=True)
    link = tmp_path / "link_home"
    link.symlink_to(real, target_is_directory=True)
    record(link / "workspace" / "task")

    probe = SessionActivityProbe((link / "workspace" / "task",), lambda pid: State.STOPPED)

    observation = probe.observe("a.b[1]", home=str(real))

    assert observation.state == State.UNKNOWN
    assert observation.reason == "unverified recorded home"
    assert not probe.can_clean("a.b[1]", home=str(real))


def test_normalize_home_path_keeps_symlinks_and_collapses_parent_segments(tmp_path):
    """Normalization matches the folder constants: absolute, no symlink following."""
    real = tmp_path / "real_home"
    real.mkdir()
    link = tmp_path / "link_home"
    link.symlink_to(real, target_is_directory=True)

    assert normalize_home_path(str(link)) == str(link)
    assert normalize_home_path(str(link)) != str(real)
    assert normalize_home_path(f"{link}/../link_home") == str(link)
    assert normalize_home_path("") == ""
