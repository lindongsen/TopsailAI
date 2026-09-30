"""Cleanup and interruption tests for the isolated hook backend."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from topsailai.hooks import HookContext, HookEvent
from topsailai.hooks.process_backend import IsolatedProcessBackend

HANDLERS = "topsailai.tests.unit.test_topsailai_hooks.fixture_handlers"


def _context(delivery_id: str = "delivery-1") -> HookContext:
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
    return HookContext(event, delivery_id, "binding-1", 1, 1_000)


def _backend(tmp_path: Path, **changes: object) -> IsolatedProcessBackend:
    """Build a backend whose temporary root is owned by the test."""
    return IsolatedProcessBackend(temp_root=str(tmp_path), **changes)


def test_worker_exact_reader_handles_controlled_segments_and_early_eof(monkeypatch) -> None:
    """Production framing must reconstruct arbitrary segments and reject early EOF."""
    from topsailai.hooks import worker
    from topsailai.hooks.contracts import ValidationError

    body = b'{"value":1}'
    pieces = [len(body).to_bytes(4, "big")[:1], len(body).to_bytes(4, "big")[1:], body[:2], body[2:5], body[5:]]

    def segmented_read(fd, size):
        return pieces.pop(0)

    monkeypatch.setattr(worker.os, "read", segmented_read)
    assert worker._read_request_frame(100) == len(body).to_bytes(4, "big") + body

    pieces[:] = [len(body).to_bytes(4, "big"), body[:3], b""]
    with pytest.raises(ValidationError, match="ended before"):
        worker._read_request_frame(100)


def test_interrupt_after_publication_before_spawn_return_cleans_owner(tmp_path: Path) -> None:
    """An interrupt in published-to-return handoff must clean the recorded owner."""
    class InterruptedBackend(IsolatedProcessBackend):
        process = None

        def _after_launch_published(self, record):
            self.process = record.process
            raise KeyboardInterrupt()

    backend = InterruptedBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    with pytest.raises(KeyboardInterrupt):
        backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
    assert backend.process is not None and backend.process.poll() is not None
    assert backend.cleanup_debts() == ()


def test_interrupt_after_spawn_return_before_lease_release_cleans_owner(tmp_path: Path) -> None:
    """An interrupt before execute disarms the lease must clean its exact resources."""
    class InterruptedBackend(IsolatedProcessBackend):
        process = None

        def _before_launch_lease_release(self, record):
            self.process = record.process
            raise KeyboardInterrupt()

    backend = InterruptedBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    with pytest.raises(KeyboardInterrupt):
        backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
    assert backend.process is not None and backend.process.poll() is not None
    assert backend.process.stdin is None
    assert backend.process.stdout is None
    assert backend.process.stderr is None
    assert backend.cleanup_debts() == ()


def test_cleanup_debt_retry_is_exclusive(tmp_path: Path) -> None:
    """Concurrent retries must never acquire the same process cleanup authority."""
    import threading

    entered = threading.Event()
    release = threading.Event()

    class FakeProcess:
        pid = 424242

        def poll(self):
            return None

    class ExclusiveBackend(IsolatedProcessBackend):
        calls = 0

        def _terminate_owned(self, process):
            self.calls += 1
            entered.set()
            release.wait(1)
            return True

    backend = ExclusiveBackend(temp_root=str(tmp_path))
    process = FakeProcess()
    backend._record_process_debt("debt", process, "fixture")
    results = []
    first = threading.Thread(target=lambda: results.append(backend.retry_cleanup("debt")))
    first.start()
    assert entered.wait(1)
    assert not backend.retry_cleanup("debt")
    release.set()
    first.join(1)
    assert results == [True]
    assert backend.calls == 1
    assert backend.retry_cleanup("debt")
    assert backend.calls == 1


def test_deadline_expires_during_observed_terminal_validation(tmp_path: Path) -> None:
    """Terminal acceptance must recheck a controlled deadline after validation."""
    class DeadlineBackend(IsolatedProcessBackend):
        validated = False

        def _validate_terminal(self, response, **expected):
            terminal = super()._validate_terminal(response, **expected)
            self.validated = True
            return terminal

        def _deadline_expired(self, deadline):
            assert self.validated
            return True

    backend = DeadlineBackend(temp_root=str(tmp_path))
    result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
    assert backend.validated
    assert (result.status, result.error_category) == ("timeout", "deadline")
    assert result.cleanup_confirmed


def test_real_killpg_oserror_records_debt_and_channels_close(
    tmp_path: Path, monkeypatch
) -> None:
    """An injected signal-boundary OSError must retain debt without leaking streams."""
    import topsailai.hooks.process_backend as process_backend

    class CaptureBackend(IsolatedProcessBackend):
        process = None

        def _finish_record(self, record, *args, **kwargs):
            self.process = record.process
            return super()._finish_record(record, *args, **kwargs)

    backend = CaptureBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    original_killpg = process_backend.os.killpg

    def fail_signal(pgid, sig):
        raise OSError("fixture signal failure")

    try:
        monkeypatch.setattr(process_backend.os, "killpg", fail_signal)
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        assert not result.cleanup_confirmed and result.cleanup_debt
        assert backend.process is not None
        assert backend.process.stdin is None
        assert backend.process.stdout is None
        assert backend.process.stderr is None
    finally:
        monkeypatch.setattr(process_backend.os, "killpg", original_killpg)
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
    assert backend.cleanup_debts() == ()


def test_unverified_posix_platform_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """Capability presence alone must not qualify an unverified non-Linux platform."""
    import topsailai.hooks.process_backend as process_backend

    monkeypatch.setattr(process_backend.sys, "platform", "darwin")
    result = _backend(tmp_path).execute(f"{HANDLERS}:sync_success", _context(), 500)
    assert (result.status, result.error_category) == (
        "unsupported_backend",
        "unsupported_platform",
    )


def test_pretransfer_interrupt_has_one_cleanup_owner_and_one_fd_close(tmp_path: Path) -> None:
    """A pre-transfer interrupt must invoke exactly one terminal cleanup path."""
    class CountingBackend(IsolatedProcessBackend):
        terminations = 0
        result_closes = 0

        def _before_launch_lease_release(self, record):
            raise KeyboardInterrupt()

        def _terminate_owned(self, process):
            self.terminations += 1
            return super()._terminate_owned(process)

        def _after_record_result_fd_close(self, record, descriptor):
            self.result_closes += 1

    backend = CountingBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    with pytest.raises(KeyboardInterrupt):
        backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
    assert backend.terminations == 1
    assert backend.result_closes == 1
    assert backend.cleanup_debts() == ()


def test_pretransfer_cleanup_failure_records_one_debt_and_closes_fd_once(
    tmp_path: Path,
) -> None:
    """One failed lease cleanup must create one debt and always reap its worker."""
    class FailedBackend(IsolatedProcessBackend):
        terminations = 0
        result_closes = 0
        fail = True

        def _before_launch_lease_release(self, record):
            raise KeyboardInterrupt()

        def _terminate_owned(self, process):
            self.terminations += 1
            if self.fail:
                return False
            return super()._terminate_owned(process)

        def _after_record_result_fd_close(self, record, descriptor):
            self.result_closes += 1

    backend = FailedBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
        assert backend.terminations == 1
        assert backend.result_closes == 1
        debts = backend.cleanup_debts()
        assert len(debts) == 1
    finally:
        backend.fail = False
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
    assert backend.cleanup_debts() == ()


def test_retry_resolves_already_exited_group_without_signaling(tmp_path: Path) -> None:
    """A fully ended owned group must settle without signaling its historical PGID."""
    class ExitedProcess:
        pid = 424242

        def poll(self):
            return 0

    class SettledBackend(IsolatedProcessBackend):
        terminations = 0

        def _group_exists(self, pgid):
            return False

        def _terminate_owned(self, process):
            self.terminations += 1
            return True

    backend = SettledBackend(temp_root=str(tmp_path))
    backend._record_process_debt("debt", ExitedProcess(), "fixture")
    assert backend.retry_cleanup("debt")
    assert backend.terminations == 0
    assert backend.cleanup_debts() == ()


def test_retry_retains_exited_leader_with_uncertain_descendants_without_signal(
    tmp_path: Path,
) -> None:
    """An exited leader with a surviving group must retain debt without stale signaling."""
    class ExitedProcess:
        pid = 424242

        def poll(self):
            return 0

    class UncertainBackend(IsolatedProcessBackend):
        terminations = 0

        def _group_exists(self, pgid):
            return True

        def _terminate_owned(self, process):
            self.terminations += 1
            return True

    backend = UncertainBackend(temp_root=str(tmp_path))
    backend._record_process_debt("debt", ExitedProcess(), "fixture")
    assert not backend.retry_cleanup("debt")
    assert backend.terminations == 0
    assert backend.cleanup_debts()[0].debt_id == "debt"


def test_retry_poll_error_and_interrupt_restore_pending_state(tmp_path: Path) -> None:
    """Retry failures must remain observable without stranding a claimed debt."""
    class Process:
        pid = 424242
        poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls == 1:
                raise OSError("fixture poll failure")
            return None

    class InterruptBackend(IsolatedProcessBackend):
        attempts = 0

        def _terminate_owned(self, process):
            self.attempts += 1
            raise KeyboardInterrupt()

    backend = InterruptBackend(temp_root=str(tmp_path))
    process = Process()
    backend._record_process_debt("debt", process, "fixture")
    with pytest.raises(OSError, match="fixture poll failure"):
        backend.retry_cleanup("debt")
    assert backend._debt_processes["debt"].state == "pending"
    with pytest.raises(KeyboardInterrupt):
        backend.retry_cleanup("debt")
    assert backend._debt_processes["debt"].state == "pending"


def test_actual_monotonic_comparison_expires_during_validation(
    tmp_path: Path, monkeypatch
) -> None:
    """The production deadline comparison must observe time advanced by validation."""
    import topsailai.hooks.process_backend as process_backend

    real_monotonic = time.monotonic

    class ClockBackend(IsolatedProcessBackend):
        validated = False

        def _validate_terminal(self, response, **expected):
            terminal = super()._validate_terminal(response, **expected)
            self.validated = True
            return terminal

    backend = ClockBackend(temp_root=str(tmp_path))

    def controlled_monotonic():
        if backend.validated:
            return real_monotonic() + 10
        return real_monotonic()

    monkeypatch.setattr(process_backend.time, "monotonic", controlled_monotonic)
    result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
    assert backend.validated
    assert (result.status, result.error_category) == ("timeout", "deadline")
    assert result.cleanup_confirmed


def test_interrupt_after_termination_resumes_without_second_signal(tmp_path: Path) -> None:
    """An interrupt after retained termination must not repeat termination."""
    class InterruptBackend(IsolatedProcessBackend):
        terminations = 0
        interrupted = False

        def _terminate_owned(self, process):
            self.terminations += 1
            return super()._terminate_owned(process)

        def _after_record_termination(self, record):
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

    backend = InterruptBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    with pytest.raises(KeyboardInterrupt):
        backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
    assert backend.terminations == 1
    assert backend.cleanup_debts() == ()


def test_interrupt_after_debt_publication_keeps_one_debt_and_retries(tmp_path: Path) -> None:
    """An interrupt after debt publication must preserve one stable retry obligation."""
    class DebtInterruptBackend(IsolatedProcessBackend):
        terminations = 0
        fail = True
        interrupted = False

        def _terminate_owned(self, process):
            self.terminations += 1
            if self.fail:
                return False
            return super()._terminate_owned(process)

        def _after_record_debt(self, record):
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

    backend = DebtInterruptBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        debts = backend.cleanup_debts()
        assert len(debts) == 1
        assert backend.terminations == 1
    finally:
        backend.fail = False
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
    assert backend.cleanup_debts() == ()


def test_lease_internal_termination_interrupt_retains_owner_and_debt(tmp_path: Path) -> None:
    """An interrupt inside Lease termination must retain cleanup authority before propagation."""
    class InternalInterruptBackend(IsolatedProcessBackend):
        process = None
        attempts = 0

        def _before_launch_lease_release(self, record):
            self.process = record.process
            raise KeyboardInterrupt()

        def _terminate_owned(self, process):
            self.attempts += 1
            if self.attempts == 1:
                raise KeyboardInterrupt()
            return super()._terminate_owned(process)

    backend = InternalInterruptBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:block_forever", _context(), 2_000)
        debts = backend.cleanup_debts()
        assert len(debts) == 1
        assert backend.process is not None
        assert backend.process.stdin is None
        assert backend.process.stdout is None
        assert backend.process.stderr is None
    finally:
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
    assert backend.cleanup_debts() == ()


def test_raw_result_fd_reuse_survives_outer_interrupt_cleanup(tmp_path: Path) -> None:
    """A reused raw result descriptor must not be closed by resumed outer cleanup."""
    class ReuseBackend(IsolatedProcessBackend):
        reused_fd = None
        opened = []
        interrupted = False

        def _after_record_result_fd_close(self, record, descriptor):
            if self.interrupted:
                return
            self.interrupted = True
            for _ in range(64):
                fd = os.open(tmp_path / "raw-result-reuse", os.O_RDWR | os.O_CREAT, 0o600)
                self.opened.append(fd)
                if fd == descriptor:
                    self.reused_fd = fd
                    raise KeyboardInterrupt()
            raise AssertionError("raw result descriptor was not reused")

    backend = ReuseBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        assert backend.reused_fd is not None
        os.fstat(backend.reused_fd)
        assert backend.cleanup_debts() == ()
    finally:
        for descriptor in backend.opened:
            os.close(descriptor)


def test_result_close_interrupt_before_call_retains_owner_and_eventually_closes(
    tmp_path: Path,
) -> None:
    """An interrupt before os.close must preserve the exact raw descriptor owner."""
    from topsailai.hooks.process_state import LaunchRecord

    class InterruptBackend(IsolatedProcessBackend):
        interrupted = False

        def _before_channel_close(self, record, name, descriptor):
            if name == "result" and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt()

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = InterruptBackend(temp_root=str(tmp_path))
    record = LaunchRecord("debt", process=object(), result_fd=read_fd)
    for name in ("stdin", "stdout", "stderr"):
        record.cleanup.channels[name].state = "closed"
    try:
        with pytest.raises(KeyboardInterrupt):
            backend._close_result_channel(record)
        assert record.result_fd == read_fd
        assert record.cleanup.channels["result"].state == "open"
        assert record.cleanup.channels["result"].resource == read_fd
        os.fstat(read_fd)
        backend._close_result_channel(record)
        assert record.result_fd is None
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


def test_result_close_error_retains_owner_and_eventually_closes(
    tmp_path: Path, monkeypatch
) -> None:
    """An ordinary close error must keep an identifiable obligation for retry."""
    import topsailai.hooks.process_cleanup as process_cleanup
    from topsailai.hooks.process_state import LaunchRecord

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("debt", process=object(), result_fd=read_fd)
    real_close = process_cleanup.os.close
    failed = False

    def fail_once(descriptor):
        nonlocal failed
        if descriptor == read_fd and not failed:
            failed = True
            raise OSError("fixture close failure")
        return real_close(descriptor)

    try:
        monkeypatch.setattr(process_cleanup.os, "close", fail_once)
        backend._close_result_channel(record)
        assert record.result_fd == read_fd
        assert record.cleanup.channels["result"].state == "open"
        os.fstat(read_fd)
        backend._close_result_channel(record)
        assert record.result_fd is None
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        monkeypatch.setattr(process_cleanup.os, "close", real_close)
        try:
            real_close(read_fd)
        except OSError:
            pass


def test_result_close_interrupt_after_call_does_not_close_reused_fd(
    tmp_path: Path,
) -> None:
    """An interrupt after confirmed close must not act on a reused descriptor."""
    from topsailai.hooks.process_state import LaunchRecord

    class InterruptBackend(IsolatedProcessBackend):
        opened = []
        reused_fd = None

        def _after_channel_close(self, record, name, descriptor):
            if name != "result":
                return
            for _ in range(64):
                candidate = os.open(tmp_path / "close-after-reuse", os.O_RDWR | os.O_CREAT, 0o600)
                self.opened.append(candidate)
                if candidate == descriptor:
                    self.reused_fd = candidate
                    raise KeyboardInterrupt()
            raise AssertionError("result descriptor was not reused")

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    backend = InterruptBackend(temp_root=str(tmp_path))
    record = LaunchRecord("debt", process=object(), result_fd=read_fd)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend._close_result_channel(record)
        assert record.cleanup.channels["result"].state == "closed"
        assert record.result_fd is None
        assert backend.reused_fd == read_fd
        backend._close_result_channel(record)
        os.fstat(backend.reused_fd)
    finally:
        for descriptor in backend.opened:
            os.close(descriptor)


def test_active_original_cleanup_excludes_retry_then_debt_settles_once(
    tmp_path: Path,
) -> None:
    """Debt retry must wait until the original record cleanup owner releases authority."""
    import threading

    published = threading.Event()
    resume = threading.Event()

    class BarrierBackend(IsolatedProcessBackend):
        fail = True
        terminations = 0

        def _terminate_owned(self, process):
            self.terminations += 1
            if self.fail:
                return False
            return super()._terminate_owned(process)

        def _after_record_debt(self, record):
            published.set()
            resume.wait(2)

    backend = BarrierBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    outcome = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        )
    )
    thread.start()
    try:
        assert published.wait(2)
        debts = backend.cleanup_debts()
        assert len(debts) == 1
        debt_id = debts[0].debt_id
        backend.fail = False
        assert not backend.retry_cleanup(debt_id)
        resume.set()
        thread.join(2)
        assert not thread.is_alive()
        assert len(outcome) == 1
        assert not outcome[0].cleanup_confirmed
        assert outcome[0].cleanup_debt == debt_id
        assert backend.retry_cleanup(debt_id)
        assert backend.cleanup_debts() == ()
        assert backend.terminations == 2
    finally:
        backend.fail = False
        resume.set()
        thread.join(2)
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
