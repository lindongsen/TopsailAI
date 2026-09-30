"""Process-group signal authorization regressions."""

from __future__ import annotations

import signal

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord


class _Process:
    """Provide controlled leader liveness for signal authorization tests."""

    pid = 424242

    def __init__(self, polls: list[int | None]) -> None:
        self._polls = iter(polls)
        self._last: int | None = None

    def poll(self) -> int | None:
        """Return the next controlled leader state."""
        self._last = next(self._polls, self._last)
        return self._last

    def wait(self, timeout: float) -> int:
        """Return the final controlled status without changing ownership."""
        return 0 if self._last is not None else 1


class _AuthorizationBackend(IsolatedProcessBackend):
    """Avoid real process-group inspection in deterministic authorization tests."""

    group_exists = False

    def _group_exists(self, pgid: int) -> bool:
        """Return the controlled process-group state."""
        return self.group_exists


def _closed_record(process: _Process) -> LaunchRecord:
    """Create a record with only process termination left to settle."""
    record = LaunchRecord("authorization", process=process)
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    return record


def test_initial_cleanup_of_exited_leader_never_signals_historical_group(
    tmp_path, monkeypatch
) -> None:
    """Initial cleanup must settle a gone group without signaling its old PGID."""
    backend = _AuthorizationBackend(temp_root=str(tmp_path))
    process = _Process([0])
    signals = []
    monkeypatch.setattr(
        "topsailai.hooks.process_cleanup.os.killpg",
        lambda *args: signals.append(args),
    )

    result = backend._cleanup_launch_record(_closed_record(process), "fixture")

    assert result.cleanup_confirmed
    assert signals == []


def test_initial_cleanup_retains_debt_for_exited_leader_with_uncertain_group(
    tmp_path, monkeypatch
) -> None:
    """A surviving historical PGID must remain debt without receiving a signal."""
    backend = _AuthorizationBackend(temp_root=str(tmp_path))
    backend.group_exists = True
    process = _Process([0])
    signals = []
    monkeypatch.setattr(
        "topsailai.hooks.process_cleanup.os.killpg",
        lambda *args: signals.append(args),
    )

    result = backend._cleanup_launch_record(_closed_record(process), "fixture")

    assert not result.cleanup_confirmed
    assert result.cleanup_debt == "authorization"
    assert signals == []


def test_live_leader_with_mismatched_group_is_not_signaled(tmp_path, monkeypatch) -> None:
    """A reused or changed process group must fail closed before signaling."""
    backend = _AuthorizationBackend(temp_root=str(tmp_path))
    process = _Process([None])
    signals = []
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.getpgid", lambda pid: pid + 1)
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.killpg", lambda *args: signals.append(args))

    assert not backend._terminate_owned(process)
    assert signals == []


def test_leader_exit_between_term_and_kill_prevents_escalation(tmp_path, monkeypatch) -> None:
    """A leader reaped after TERM must revoke authority before SIGKILL."""
    backend = _AuthorizationBackend(temp_root=str(tmp_path), cleanup_grace_ms=1)
    backend.group_exists = True
    process = _Process([None, None, 0])
    signals = []
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.getpgid", lambda pid: pid)
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.killpg", lambda *args: signals.append(args))

    assert not backend._terminate_owned(process)
    assert signals == [(process.pid, signal.SIGTERM)]


def test_live_owned_group_authorizes_term_and_kill(tmp_path, monkeypatch) -> None:
    """A continuously live exact leader still permits bounded escalation."""
    backend = _AuthorizationBackend(temp_root=str(tmp_path), cleanup_grace_ms=1)
    backend.group_exists = True
    process = _Process([None])
    signals = []
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.getpgid", lambda pid: pid)
    monkeypatch.setattr("topsailai.hooks.process_cleanup.os.killpg", lambda *args: signals.append(args))

    assert not backend._terminate_owned(process)
    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
