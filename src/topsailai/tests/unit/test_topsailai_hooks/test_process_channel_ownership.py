"""Concurrent and interrupted channel-ownership regressions."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from topsailai.hooks import HookContext, HookEvent
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord

HANDLERS = "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers"


def _context() -> HookContext:
    """Create one detached worker context."""
    event = HookEvent(
        "event-1",
        "conversation.started",
        1,
        "owner-1",
        "scope-1",
        "operation-1",
        None,
        1,
        "2026-09-30T00:00:00Z",
        "test",
        "worker",
        {"value": 1},
    )
    return HookContext(event, "delivery-1", "binding-1", 1, 1_000)


def test_active_channel_close_excludes_debt_retry_and_preserves_reused_fd(
    tmp_path: Path,
) -> None:
    """Debt retry must not overlap a close or later close its reused descriptor."""
    close_started = threading.Event()
    resume_close = threading.Event()

    class ExitedProcess:
        pid = 424242

        @staticmethod
        def poll():
            return 0

    class BarrierBackend(IsolatedProcessBackend):
        close_attempts = 0

        def _before_channel_close(self, record, name, descriptor):
            if name == "result":
                self.close_attempts += 1
                close_started.set()
                resume_close.wait(2)

        @staticmethod
        def _group_exists(pgid):
            return False

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = BarrierBackend(temp_root=str(tmp_path))
    process = ExitedProcess()
    record = LaunchRecord("debt", process=process, result_fd=read_fd)
    for name in ("stdin", "stdout", "stderr"):
        record.cleanup.channels[name].state = "closed"
    backend._record_process_debt("debt", process, "fixture", record)

    def close_result() -> None:
        with backend._cleanup_execution_lease(record) as lease:
            assert lease is not None
            backend._close_result_channel(record)

    thread = threading.Thread(target=close_result)
    opened: list[int] = []
    thread.start()
    try:
        assert close_started.wait(2)
        assert not backend.retry_cleanup("debt")
        assert backend.close_attempts == 1
        os.fstat(read_fd)
        resume_close.set()
        thread.join(2)
        assert not thread.is_alive()
        for _ in range(64):
            descriptor = os.open(
                tmp_path / "concurrent-close-reuse", os.O_RDWR | os.O_CREAT, 0o600
            )
            opened.append(descriptor)
            if descriptor == read_fd:
                break
        assert read_fd in opened
        assert backend.retry_cleanup("debt")
        os.fstat(read_fd)
        assert backend.close_attempts == 1
    finally:
        resume_close.set()
        thread.join(2)
        for descriptor in opened:
            os.close(descriptor)
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)


def test_stdin_close_interrupt_after_close_recovers_authoritative_state(
    tmp_path: Path,
) -> None:
    """A post-close interrupt must propagate after settling stdin and owned cleanup."""
    class InterruptBackend(IsolatedProcessBackend):
        record = None
        process = None
        interrupted = False

        def _after_stream_close_before_commit(self, record, name, descriptor):
            if name == "stdin" and not self.interrupted:
                self.record = record
                self.process = record.process
                self.interrupted = True
                raise KeyboardInterrupt()

    backend = InterruptBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    with pytest.raises(KeyboardInterrupt):
        backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
    assert backend.record is not None
    assert backend.process is not None and backend.process.poll() is not None
    assert backend.record.cleanup.channels["stdin"].state == "closed"
    assert backend.process.stdin is None
    assert backend.cleanup_debts() == ()


def _result_record(descriptor: int) -> LaunchRecord:
    """Create one record whose only open obligation is the result descriptor."""
    record = LaunchRecord("debt", process=object(), result_fd=descriptor)
    for name in ("stdin", "stdout", "stderr"):
        record.cleanup.channels[name].state = "closed"
    return record


def test_result_interrupt_immediately_before_close_remains_retryable(tmp_path: Path) -> None:
    """An interrupt after intent publication but before close must not strand closing."""
    class InterruptBackend(IsolatedProcessBackend):
        interrupted = False

        def _before_channel_close(self, record, name, descriptor):
            if name == "result" and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = InterruptBackend(temp_root=str(tmp_path))
    record = _result_record(read_fd)
    with backend._cleanup_execution_lease(record) as lease:
        assert lease is not None
        with pytest.raises(KeyboardInterrupt):
            backend._close_result_channel(record)
        assert record.cleanup.channels["result"].state == "open"
        os.fstat(read_fd)
        backend._close_result_channel(record)
        assert record.cleanup.channels["result"].state == "closed"
        with pytest.raises(OSError):
            os.fstat(read_fd)
    try:
        os.close(read_fd)
    except OSError:
        pass


def test_result_interrupt_immediately_after_close_settles_without_reclose(
    tmp_path: Path,
) -> None:
    """An interrupt after close must publish closed and never close a reused fd."""
    class InterruptBackend(IsolatedProcessBackend):
        def _after_result_close_before_commit(self, record, descriptor):
            raise KeyboardInterrupt()

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = InterruptBackend(temp_root=str(tmp_path))
    record = _result_record(read_fd)
    opened: list[int] = []
    with backend._cleanup_execution_lease(record) as lease:
        assert lease is not None
        try:
            with pytest.raises(KeyboardInterrupt):
                backend._close_result_channel(record)
            assert record.cleanup.channels["result"].state == "closed"
            for _ in range(64):
                descriptor = os.open(
                    tmp_path / "post-close-reuse", os.O_RDWR | os.O_CREAT, 0o600
                )
                opened.append(descriptor)
                if descriptor == read_fd:
                    break
            assert read_fd in opened
            backend._close_result_channel(record)
            os.fstat(read_fd)
        finally:
            for descriptor in opened:
                os.close(descriptor)


def test_retry_acquire_interrupt_restores_debt_and_next_retry_settles(tmp_path: Path) -> None:
    """An interrupt after lease publication must leave debt retryable and release the lease."""
    class ExitedProcess:
        pid = 424243

        @staticmethod
        def poll():
            return 0

    class InterruptBackend(IsolatedProcessBackend):
        interrupted = False

        def _after_cleanup_execution_acquired(self, record):
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

        @staticmethod
        def _group_exists(pgid):
            return False

    backend = InterruptBackend(temp_root=str(tmp_path))
    process = ExitedProcess()
    record = LaunchRecord("acquire-debt", process=process)
    record.cleanup.termination_started = True
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    backend._record_process_debt(record.debt_id, process, "fixture", record)

    with pytest.raises(KeyboardInterrupt):
        backend.retry_cleanup(record.debt_id)
    assert backend._debt_processes[record.debt_id].state == "pending"
    assert record.cleanup.execution_owner is None
    assert record.cleanup.execution_depth == 0
    assert backend.retry_cleanup(record.debt_id)
    assert backend.cleanup_debts() == ()
    assert record.cleanup.debt_state == "settled"


@pytest.mark.parametrize("reentrant", [False, True])
def test_lease_interrupt_before_yield_restores_exact_prior_state(
    tmp_path: Path, reentrant: bool
) -> None:
    """An interrupt on the production yield boundary must not orphan a lease."""
    import inspect
    import sys

    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("yield-boundary")
    prior = (None, 0, "owned")

    def interrupt_before_yield(frame, event, arg):
        if (
            event == "line"
            and frame.f_code is backend._cleanup_execution_lease.__wrapped__.__code__
            and frame.f_lineno == yield_line
        ):
            sys.settrace(None)
            raise KeyboardInterrupt()
        return interrupt_before_yield

    source, first_line = inspect.getsourcelines(
        backend._cleanup_execution_lease.__wrapped__
    )
    yield_line = first_line + next(
        index for index, line in enumerate(source) if line.strip() == "yield lease"
    )

    if not reentrant:
        sys.settrace(interrupt_before_yield)
        with pytest.raises(KeyboardInterrupt):
            with backend._cleanup_execution_lease(record):
                raise AssertionError("interrupted acquisition yielded a lease")
        sys.settrace(None)
        assert (
            record.cleanup.execution_owner,
            record.cleanup.execution_depth,
            record.cleanup.state,
        ) == (None, 0, "owned")
        _assert_cross_thread_lease_access(backend, record, expected=True)
        return

    with backend._cleanup_execution_lease(record) as outer:
        assert outer is not None
        prior = (
            record.cleanup.execution_owner,
            record.cleanup.execution_depth,
            record.cleanup.state,
        )
        sys.settrace(interrupt_before_yield)
        with pytest.raises(KeyboardInterrupt):
            with backend._cleanup_execution_lease(record):
                raise AssertionError("interrupted acquisition yielded a lease")
        sys.settrace(None)
        assert (
            record.cleanup.execution_owner,
            record.cleanup.execution_depth,
            record.cleanup.state,
        ) == prior
        _assert_cross_thread_lease_access(backend, record, expected=False)
    assert record.cleanup.execution_owner is None
    assert record.cleanup.execution_depth == 0
    _assert_cross_thread_lease_access(backend, record, expected=True)


@pytest.mark.parametrize("reentrant", [False, True])
def test_lease_interrupt_on_first_protected_body_line_releases_exact_level(
    tmp_path: Path, reentrant: bool
) -> None:
    """The first caller-body instruction must already be under exact-token cleanup."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("protected-body")

    def interrupt_inner() -> None:
        with backend._cleanup_execution_lease(record):
            raise KeyboardInterrupt()

    if not reentrant:
        with pytest.raises(KeyboardInterrupt):
            interrupt_inner()
        assert record.cleanup.execution_owner is None
        assert record.cleanup.execution_depth == 0
        _assert_cross_thread_lease_access(backend, record, expected=True)
        return

    with backend._cleanup_execution_lease(record) as outer:
        assert outer is not None
        prior = (
            record.cleanup.execution_owner,
            record.cleanup.execution_depth,
            record.cleanup.state,
        )
        with pytest.raises(KeyboardInterrupt):
            interrupt_inner()
        assert (
            record.cleanup.execution_owner,
            record.cleanup.execution_depth,
            record.cleanup.state,
        ) == prior
        _assert_cross_thread_lease_access(backend, record, expected=False)
    _assert_cross_thread_lease_access(backend, record, expected=True)


def _assert_cross_thread_lease_access(
    backend: IsolatedProcessBackend, record: LaunchRecord, *, expected: bool
) -> None:
    """Assert whether another thread can acquire and release one exact lease level."""
    outcomes: list[bool] = []

    def acquire() -> None:
        with backend._cleanup_execution_lease(record) as lease:
            outcomes.append(lease is not None)

    thread = threading.Thread(target=acquire)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert outcomes == [expected]

def test_debt_cleaning_publication_interrupt_restores_and_settles(tmp_path: Path) -> None:
    """An interrupt after cleaning mutation must leave the next retry able to settle."""
    class ExitedProcess:
        pid = 424244

        @staticmethod
        def poll():
            return 0

    class InterruptBackend(IsolatedProcessBackend):
        interrupted = False

        def _after_cleanup_debt_claimed(self, entry):
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

        @staticmethod
        def _group_exists(pgid):
            return False

    backend = InterruptBackend(temp_root=str(tmp_path))
    process = ExitedProcess()
    record = LaunchRecord("debt-publication", process=process)
    record.cleanup.termination_started = True
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    backend._record_process_debt(record.debt_id, process, "fixture", record)

    with pytest.raises(KeyboardInterrupt):
        backend.retry_cleanup(record.debt_id)
    assert backend._debt_processes[record.debt_id].state == "pending"
    assert backend.retry_cleanup(record.debt_id)
    assert backend.cleanup_debts() == ()
    assert record.cleanup.debt_state == "settled"
