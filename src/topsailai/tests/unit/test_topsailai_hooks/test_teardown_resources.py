"""Regressions for unconditional focused-test resource teardown."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import CleanupDebt, LaunchRecord
from topsailai.tests.unit.test_topsailai_hooks.conftest import (
    _attempt_all_cleanup,
    _resource_failures,
)


class _ExitedProcess:
    """Represent one exact test-owned leader whose process group may remain."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    @staticmethod
    def poll() -> int:
        return 0


class _TeardownBackend:
    """Expose deterministic teardown behavior without signaling host processes."""

    def __init__(self, debts: tuple[CleanupDebt, ...] = ()) -> None:
        self.debts = debts
        self._debt_processes = {}
        self.group_exists = True
        self.terminated: list[int] = []
        self.retries: list[str] = []

    def cleanup_debts(self):
        """Return configured cleanup obligations."""
        return self.debts

    def retry_cleanup(self, debt_id: str) -> bool:
        """Record one debt retry."""
        self.retries.append(debt_id)
        return False

    def _group_exists(self, pgid: int) -> bool:
        """Report the exact tracked group state."""
        return self.group_exists

    def _terminate_owned(self, process: _ExitedProcess) -> bool:
        """Converge only the exact process supplied by the fixture."""
        self.terminated.append(process.pid)
        self.group_exists = False
        return True


def test_teardown_does_not_signal_historical_group_after_leader_exit() -> None:
    """A reused historical PGID must be reported uncertain without termination."""
    process = _ExitedProcess(410001)
    backend = _TeardownBackend()
    failures: list[str] = []

    _attempt_all_cleanup([backend], {}, [process], failures)

    assert backend.terminated == []
    assert failures == []
    assert _resource_failures([backend], {}, [process]) == [
        f"historical process group {process.pid} remains uncertain"
    ]


def test_teardown_tracks_launching_debt_without_unknown_group_signal() -> None:
    """A launching debt is retried by identity without signaling an unknown PGID."""
    debt = CleanupDebt("launching-1", "launching", None, "pending publication")
    backend = _TeardownBackend((debt,))
    record = LaunchRecord(debt.debt_id)
    failures: list[str] = []

    _attempt_all_cleanup([backend], {id(record): (backend, record)}, [], failures)

    assert backend.retries == [debt.debt_id]
    assert backend.terminated == []
    assert failures == []
    assert _resource_failures(
        [backend], {id(record): (backend, record)}, []
    ) == [
        f"launch record {debt.debt_id} remains unpublished",
        f"cleanup debt remains: {debt.debt_id} (launching)",
    ]


def test_teardown_closes_leaked_record_channel(tmp_path: Path) -> None:
    """A leaked authoritative descriptor is closed even after its leader exits."""
    class SafeBackend(IsolatedProcessBackend):
        @staticmethod
        def _group_exists(pgid):
            return False

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = SafeBackend(temp_root=str(tmp_path))
    process = _ExitedProcess(410002)
    record = LaunchRecord("leaked-channel", process=process, result_fd=read_fd)
    record.cleanup.termination_confirmed = True
    for name in ("stdin", "stdout", "stderr"):
        record.cleanup.channels[name].state = "closed"
    failures: list[str] = []

    try:
        _attempt_all_cleanup(
            [backend], {id(record): (backend, record)}, [process], failures
        )
        assert failures == []
        assert record.cleanup.channels["result"].state == "closed"
        assert record.result_fd is None
        try:
            os.fstat(read_fd)
        except OSError:
            pass
        else:
            raise AssertionError("teardown left the result descriptor open")
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


def test_teardown_retry_exception_does_not_skip_other_debts() -> None:
    """One retry exception must not prevent attempts for other exact debts."""
    class RetryBackend(_TeardownBackend):
        def retry_cleanup(self, debt_id: str) -> bool:
            self.retries.append(debt_id)
            if debt_id == "first":
                raise RuntimeError("injected")
            return False

    debts = (
        CleanupDebt("first", "launching", None, "fixture"),
        CleanupDebt("second", "launching", None, "fixture"),
    )
    backend = RetryBackend(debts)
    first = LaunchRecord("first")
    second = LaunchRecord("second")
    failures: list[str] = []

    _attempt_all_cleanup(
        [backend], {id(first): (backend, first), id(second): (backend, second)}, [], failures
    )

    assert backend.retries == ["first", "second"]
    assert failures == ["debt first: RuntimeError"]


def test_teardown_process_error_still_closes_record_descriptor(tmp_path: Path) -> None:
    """A process-cleanup exception must not skip independent channel closure."""
    class LiveProcess(_ExitedProcess):
        @staticmethod
        def poll():
            return None

    class ErrorBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process):
            raise RuntimeError("injected termination failure")

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = ErrorBackend(temp_root=str(tmp_path))
    process = LiveProcess(410003)
    record = LaunchRecord("process-error-channel", process=process, result_fd=read_fd)
    for name in ("stdin", "stdout", "stderr"):
        record.cleanup.channels[name].state = "closed"
    failures: list[str] = []

    try:
        _attempt_all_cleanup(
            [backend], {id(record): (backend, record)}, [process], failures
        )
        assert record.result_fd is None
        assert record.cleanup.channels["result"].state == "closed"
        assert any("record process-error-channel process: RuntimeError" == item for item in failures)
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


def test_channel_validation_rejects_closed_label_with_live_fd(tmp_path: Path) -> None:
    """Teardown validation must inspect the fd obligation beyond its state label."""
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    process = _ExitedProcess(410004)
    record = LaunchRecord("false-closed", process=process, result_fd=read_fd)
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    try:
        failures = _resource_failures(
            [backend], {id(record): (backend, record)}, [process]
        )
        assert "record false-closed channels remain: ['result']" in failures
        os.fstat(read_fd)
    finally:
        os.close(read_fd)
