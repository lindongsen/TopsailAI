"""Real-process tests for the isolated hook worker and protocol."""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import pytest

from topsailai.hooks import HookContext, HookEvent
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.worker_protocol import ProtocolLimits, decode_frame, encode_frame

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


def _reap_test_resources(
    backend: IsolatedProcessBackend, *processes: object, timeout: float = 2.0
) -> None:
    """Boundedly settle this test's debts and exact captured processes."""
    deadline = time.monotonic() + timeout
    while backend.cleanup_debts() and time.monotonic() < deadline:
        for debt in backend.cleanup_debts():
            backend.retry_cleanup(debt.debt_id)
        time.sleep(0.01)
    for process in processes:
        if process is not None and process.poll() is None:
            backend._terminate_owned(process)


def test_protocol_rejects_malformed_partial_and_oversized_frames() -> None:
    """Protocol decoding must enforce complete bounded JSON framing."""
    frame = encode_frame({"value": 1}, 100)
    assert decode_frame(frame, 100) == {"value": 1}
    with pytest.raises(Exception, match="incomplete|length"):
        decode_frame(frame[:-1], 100)
    with pytest.raises(Exception, match="maximum"):
        decode_frame(struct.pack("!I", 101), 100)
    with pytest.raises(Exception, match="invalid JSON"):
        decode_frame(struct.pack("!I", 1) + b"{", 100)


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        ("sync_success", {"delivery": "delivery-1", "payload": {"value": 1}}),
        ("async_success", {"binding": "binding-1"}),
        ("custom_awaitable_success", {"awaitable": True}),
    ],
)
def test_real_worker_executes_sync_and_async_handlers(
    tmp_path: Path, handler: str, expected: object
) -> None:
    """Sync and async functions must use one isolated worker protocol."""
    result = _backend(tmp_path).execute(f"{HANDLERS}:{handler}", _context(), 2_000)
    assert result.status == "success"
    assert result.value == expected
    assert result.cleanup_confirmed


def test_worker_converts_handler_exception_and_import_failure(tmp_path: Path) -> None:
    """Plugin and import failures must be terminal data rather than host exceptions."""
    backend = _backend(tmp_path)
    raised = backend.execute(f"{HANDLERS}:raise_exception", _context(), 2_000)
    missing = backend.execute("missing_hooks_package.module:handle", _context(), 2_000)
    assert (raised.status, raised.error_category) == ("error", "handler_error")
    assert (missing.status, missing.error_category) == ("error", "import_error")
    assert raised.cleanup_confirmed and missing.cleanup_confirmed


def test_worker_rejects_non_json_handler_result(tmp_path: Path) -> None:
    """A handler return outside the bounded JSON contract must be invalid output."""
    result = _backend(tmp_path).execute(
        f"{HANDLERS}:return_invalid_value", _context(), 2_000
    )
    assert (result.status, result.error_category) == ("invalid_output", "protocol_error")
    assert result.value is None
    assert result.cleanup_confirmed


def test_timeout_uses_absolute_deadline_and_reaps_owned_worker(tmp_path: Path) -> None:
    """A blocked handler must time out near one deadline and be reaped."""
    started = time.monotonic()
    result = _backend(tmp_path, cleanup_grace_ms=50).execute(
        f"{HANDLERS}:block_forever", _context(), 150
    )
    elapsed = time.monotonic() - started
    assert result.status == "timeout"
    assert elapsed < 1.0
    assert result.cleanup_confirmed


def test_output_flood_is_drained_and_capped(tmp_path: Path) -> None:
    """Worker output floods must not deadlock or allocate unbounded capture buffers."""
    result = _backend(tmp_path, output_limit_bytes=1_024).execute(
        f"{HANDLERS}:flood_output", _context(), 3_000
    )
    assert result.status == "success"
    assert len(result.stdout) <= 1_024 and len(result.stderr) <= 1_024
    assert result.stdout_dropped > 0 and result.stderr_dropped > 0
    assert result.cleanup_confirmed


def test_missing_interpreter_and_startup_failure_are_structured(tmp_path: Path) -> None:
    """Unqualified launchers and missing worker modules must not execute inline."""
    unsupported = _backend(tmp_path, interpreter=str(tmp_path / "not-python")).execute(
        f"{HANDLERS}:sync_success", _context(), 500
    )
    failed = _backend(tmp_path, worker_module="missing.worker.module").execute(
        f"{HANDLERS}:sync_success", _context(), 1_000
    )
    assert unsupported.status == "unsupported_backend"
    assert failed.status in ("worker_lost", "invalid_output")
    assert failed.cleanup_confirmed


def test_wrong_correlation_and_malformed_worker_output_are_rejected(tmp_path: Path) -> None:
    """The host must reject terminal bytes that fail protocol or correlation checks."""
    wrong = _backend(
        tmp_path, worker_module="topsailai.tests.unit.test_topsailai_hooks.fake_worker_wrong"
    ).execute(f"{HANDLERS}:sync_success", _context(), 1_000)
    malformed = _backend(
        tmp_path, worker_module="topsailai.tests.unit.test_topsailai_hooks.fake_worker_malformed"
    ).execute(f"{HANDLERS}:sync_success", _context(), 1_000)
    assert wrong.status == "invalid_output"
    assert malformed.status == "invalid_output"
    assert wrong.cleanup_confirmed and malformed.cleanup_confirmed


def test_timeout_reaps_owned_descendant_process_group(tmp_path: Path) -> None:
    """Timeout cleanup must stop a descendant in the worker's owned process group."""
    result = _backend(tmp_path, output_limit_bytes=1_024, cleanup_grace_ms=100).execute(
        f"{HANDLERS}:spawn_descendant_and_block", _context(), 2_000
    )
    assert result.status == "timeout"
    assert result.cleanup_confirmed
    line = result.stdout.decode().strip()
    assert line.startswith("CHILD:")
    child_pid = int(line.split(":", 1)[1])
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_protocol_normalizes_parser_resource_failures() -> None:
    """Deep JSON and oversized integer parsing failures must stay protocol errors."""
    from topsailai.hooks.contracts import ValidationError

    deep = ("[" * 2_000 + "0" + "]" * 2_000).encode()
    huge_int = ("9" * 10_000).encode()
    for body in (deep, huge_int):
        frame = struct.pack("!I", len(body)) + body
        with pytest.raises(ValidationError):
            decode_frame(frame, len(body) + 1)


def test_large_request_and_startup_flood_share_nonblocking_io(tmp_path: Path) -> None:
    """Large writes and startup output floods must progress concurrently."""
    payload = {"first": "v" * 20000, "second": "v" * 20000}
    context = _context()
    context = HookContext(
        HookEvent(
            context.event.event_id,
            context.event.name,
            context.event.major_version,
            context.event.owner_id,
            context.event.scope_id,
            context.event.operation_id,
            context.event.parent_operation_id,
            context.event.sequence,
            context.event.timestamp,
            context.event.layer,
            context.event.purpose,
            payload,
        ),
        context.delivery_id,
        context.binding_id,
        context.registry_generation,
        context.remaining_budget_ms,
    )
    result = _backend(
        tmp_path,
        output_limit_bytes=512,
        worker_module="topsailai.tests.unit.test_topsailai_hooks.fake_worker_startup_flood",
    ).execute(f"{HANDLERS}:sync_success", context, 3_000)
    assert result.status == "success"
    assert result.stdout_dropped > 0 and result.stderr_dropped > 0
    assert result.cleanup_confirmed


def test_worker_not_reading_large_request_returns_bounded(tmp_path: Path) -> None:
    """A full stdin pipe must not strand a buffered writer or unbound execute."""
    context = _context()
    context = HookContext(
        HookEvent(
            context.event.event_id, context.event.name, context.event.major_version,
            context.event.owner_id, context.event.scope_id, context.event.operation_id,
            context.event.parent_operation_id, context.event.sequence, context.event.timestamp,
            context.event.layer, context.event.purpose, {"first": "x" * 20000, "second": "x" * 20000},
        ),
        context.delivery_id, context.binding_id, context.registry_generation,
        context.remaining_budget_ms,
    )
    started = time.monotonic()
    result = _backend(
        tmp_path,
        cleanup_grace_ms=50,
        worker_module="topsailai.tests.unit.test_topsailai_hooks.fake_worker_no_read",
    ).execute(f"{HANDLERS}:sync_success", context, 150)
    assert result.status == "timeout"
    assert time.monotonic() - started < 1.0
    assert result.cleanup_confirmed


@pytest.mark.parametrize(
    "module",
    [
        "fake_worker_wrong",
        "fake_worker_channel",
        "fake_worker_delivery",
        "fake_worker_malformed",
    ],
)
def test_all_invalid_terminal_envelopes_are_protocol_errors(
    tmp_path: Path, module: str
) -> None:
    """Malformed and mismatched terminal data must have one classification."""
    result = _backend(
        tmp_path,
        worker_module=f"topsailai.tests.unit.test_topsailai_hooks.{module}",
    ).execute(f"{HANDLERS}:sync_success", _context(), 1_000)
    assert (result.status, result.error_category) == ("invalid_output", "protocol_error")
    assert result.cleanup_confirmed


@pytest.mark.parametrize(
    "handler",
    ["block_coroutine", "raise_system_exit", "raise_keyboard_interrupt", "raise_cancelled"],
)
def test_worker_control_flow_is_contained(tmp_path: Path, handler: str) -> None:
    """Worker-origin hangs and BaseException control flow must not escape the host."""
    timeout = 150 if handler == "block_coroutine" else 2_000
    result = _backend(tmp_path, cleanup_grace_ms=50).execute(
        f"{HANDLERS}:{handler}", _context(), timeout
    )
    if handler == "block_coroutine":
        assert result.status == "timeout"
    else:
        assert (result.status, result.error_category) == ("error", "handler_error")
    assert result.cleanup_confirmed


def test_late_valid_result_is_not_accepted(tmp_path: Path) -> None:
    """A terminal frame arriving after the absolute deadline must be rejected."""
    result = _backend(
        tmp_path,
        cleanup_grace_ms=50,
        worker_module="topsailai.tests.unit.test_topsailai_hooks.fake_worker_late",
    ).execute(f"{HANDLERS}:sync_success", _context(), 100)
    assert (result.status, result.error_category) == ("timeout", "deadline")
    assert result.cleanup_confirmed


def test_startup_timeout_handoff_retains_and_resolves_queryable_debt(tmp_path: Path) -> None:
    """Cancel-before-publish must leave creator-owned cleanup visible until reaped."""
    import threading

    entered = threading.Event()
    release = threading.Event()

    class PausedBackend(IsolatedProcessBackend):
        def _before_publish_process(self, record):
            entered.set()
            release.wait(1)

    backend = PausedBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 100)
        assert entered.is_set()
        assert not result.cleanup_confirmed and result.cleanup_debt
        assert backend.cleanup_debts()[0].debt_id == result.cleanup_debt
    finally:
        release.set()
        _reap_test_resources(backend)
    assert backend.cleanup_debts() == ()


def test_cleanup_failure_is_retained_for_retry(tmp_path: Path) -> None:
    """Unconfirmed cleanup must retain exact process ownership rather than claim success."""
    class RetryBackend(IsolatedProcessBackend):
        attempts = 0

        def _terminate_owned(self, process):
            self.attempts += 1
            if self.attempts == 1:
                return False
            return super()._terminate_owned(process)

    backend = RetryBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        assert not result.cleanup_confirmed and result.cleanup_debt
        debt = backend.cleanup_debts()[0]
        assert debt.pid is not None and debt.debt_id == result.cleanup_debt
        assert backend.retry_cleanup(debt.debt_id)
    finally:
        _reap_test_resources(backend)
    assert backend.cleanup_debts() == ()


def test_blocking_import_obeys_shared_deadline(tmp_path: Path) -> None:
    """An import stall must terminate within the same absolute delivery deadline."""
    started = time.monotonic()
    result = _backend(tmp_path, cleanup_grace_ms=50).execute(
        "topsailai.tests.unit.test_topsailai_hooks.fixture_blocking_import:handle",
        _context(),
        150,
    )
    assert (result.status, result.error_category) == ("timeout", "deadline")
    assert time.monotonic() - started < 1.0
    assert result.cleanup_confirmed


def test_host_interrupt_cleans_owned_process_before_propagating(tmp_path: Path) -> None:
    """A genuine host interrupt must propagate only after bounded owned cleanup."""
    class InterruptBackend(IsolatedProcessBackend):
        process = None

        def _exchange(self, record, process, *args):
            self.process = process
            raise KeyboardInterrupt()

    backend = InterruptBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:block_forever", _context(), 1_000)
        assert backend.process is not None
        assert backend.process.poll() is not None
        assert backend.cleanup_debts() == ()
    finally:
        _reap_test_resources(backend, backend.process)


def _large_context() -> HookContext:
    """Create a request large enough to require many segmented pipe writes."""
    context = _context()
    event = context.event
    return HookContext(
        HookEvent(
            event.event_id, event.name, event.major_version, event.owner_id,
            event.scope_id, event.operation_id, event.parent_operation_id,
            event.sequence, event.timestamp, event.layer, event.purpose,
            {"first": "s" * 20000, "second": "s" * 20000},
        ),
        context.delivery_id, context.binding_id, context.registry_generation,
        context.remaining_budget_ms,
    )


def test_production_worker_reads_large_request_in_forced_segments(tmp_path: Path) -> None:
    """The production worker must reconstruct a large frame sent in tiny segments."""
    class SegmentedBackend(IsolatedProcessBackend):
        def _request_write_chunk_size(self):
            return 7

    result = SegmentedBackend(temp_root=str(tmp_path)).execute(
        f"{HANDLERS}:async_success", _large_context(), 3_000
    )
    assert result.status == "success"
    assert result.cleanup_confirmed


def test_deadline_is_rechecked_after_response_decode(tmp_path: Path, monkeypatch) -> None:
    """A frame decoded before expiry must still be rejected if validation crosses it."""
    import topsailai.hooks.process_backend as process_backend

    original = process_backend.validate_response

    def delayed_validation(*args, **kwargs):
        value = original(*args, **kwargs)
        time.sleep(0.08)
        return value

    monkeypatch.setattr(process_backend, "validate_response", delayed_validation)
    result = _backend(tmp_path).execute(f"{HANDLERS}:sync_success", _context(), 100)
    assert (result.status, result.error_category) == ("timeout", "deadline")
    assert result.cleanup_confirmed


def test_startup_host_interrupt_abandons_and_resolves_launch(tmp_path: Path) -> None:
    """Host interruption before publication must leave cleanup with the launcher."""
    import threading

    entered = threading.Event()
    release = threading.Event()

    class InterruptedBackend(IsolatedProcessBackend):
        waits = 0

        def _before_publish_process(self, record):
            entered.set()
            release.wait(1)

        def _wait_for_launch(self, record, remaining):
            self.waits += 1
            assert entered.wait(1)
            raise KeyboardInterrupt()

    backend = InterruptedBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        with pytest.raises(KeyboardInterrupt):
            backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        debts = backend.cleanup_debts()
        assert len(debts) == 1 and debts[0].state == "launching"
    finally:
        release.set()
        _reap_test_resources(backend)
    assert backend.cleanup_debts() == ()


def test_pipe_allocation_failure_is_structured(tmp_path: Path, monkeypatch) -> None:
    """A pipe allocation failure must publish startup failure without hanging."""
    import topsailai.hooks.process_backend as process_backend

    def fail_pipe():
        raise OSError("fixture pipe failure")

    monkeypatch.setattr(process_backend.os, "pipe", fail_pipe)
    result = _backend(tmp_path).execute(f"{HANDLERS}:sync_success", _context(), 500)
    assert (result.status, result.error_category) == ("worker_lost", "startup_failure")
    assert result.cleanup_confirmed and result.cleanup_debt is None


def test_startup_timeout_cleanup_failure_remains_queryable(tmp_path: Path) -> None:
    """Late launch cleanup failure must replace launch debt with exact process debt."""
    import threading

    entered = threading.Event()
    release = threading.Event()

    class FailedLateCleanupBackend(IsolatedProcessBackend):
        attempts = 0

        def _before_publish_process(self, record):
            entered.set()
            release.wait(1)

        def _terminate_owned(self, process):
            self.attempts += 1
            if self.attempts == 1:
                return False
            return super()._terminate_owned(process)

    backend = FailedLateCleanupBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 100)
        assert entered.is_set() and result.cleanup_debt
        release.set()
        end = time.monotonic() + 1
        while time.monotonic() < end:
            debts = backend.cleanup_debts()
            if debts and debts[0].state == "process":
                break
            time.sleep(0.01)
        debt = backend.cleanup_debts()[0]
        assert debt.debt_id == result.cleanup_debt and debt.pid is not None
        assert backend.retry_cleanup(debt.debt_id)
    finally:
        release.set()
        _reap_test_resources(backend)
    assert backend.cleanup_debts() == ()


def test_transport_setup_error_is_structured_and_cleanup_runs(
    tmp_path: Path, monkeypatch
) -> None:
    """Selector setup I/O failure must not escape or bypass owned cleanup."""
    import topsailai.hooks.process_backend as process_backend

    original = process_backend.os.set_blocking
    calls = 0

    def fail_once(fd, blocking):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("fixture setup failure")
        return original(fd, blocking)

    monkeypatch.setattr(process_backend.os, "set_blocking", fail_once)
    result = _backend(tmp_path).execute(f"{HANDLERS}:block_forever", _context(), 1_000)
    assert (result.status, result.error_category) == ("worker_lost", "transport_error")
    assert result.cleanup_confirmed


def test_cleanup_signal_failure_records_debt_and_still_closes_channels(tmp_path: Path) -> None:
    """Signal failure must retain ownership debt without preventing channel closure."""
    class SignalFailureBackend(IsolatedProcessBackend):
        captured = None
        attempts = 0

        def _terminate_owned(self, process):
            self.captured = process
            self.attempts += 1
            if self.attempts == 1:
                return False
            return super()._terminate_owned(process)

    backend = SignalFailureBackend(temp_root=str(tmp_path), cleanup_grace_ms=50)
    try:
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        assert not result.cleanup_confirmed and result.cleanup_debt
        assert backend.captured is not None
        assert backend.captured.stdin is None
        assert backend.captured.stdout is None
        assert backend.captured.stderr is None
        assert backend.retry_cleanup(result.cleanup_debt)
    finally:
        _reap_test_resources(backend, backend.captured)
    assert backend.cleanup_debts() == ()


def test_closed_popen_streams_cannot_close_reused_descriptor(tmp_path: Path) -> None:
    """Popen stream finalization must not retain ownership of reused descriptors."""
    import gc

    class CaptureBackend(IsolatedProcessBackend):
        process = None
        old_fds = ()

        def _finish_record(self, record, *args, **kwargs):
            self.process = record.process
            if not self.old_fds:
                self.old_fds = tuple(
                    stream.fileno()
                    for stream in (
                        record.process.stdin,
                        record.process.stdout,
                        record.process.stderr,
                    )
                    if stream is not None
                )
            return super()._finish_record(record, *args, **kwargs)

    backend = CaptureBackend(temp_root=str(tmp_path))
    opened = []
    try:
        result = backend.execute(f"{HANDLERS}:sync_success", _context(), 2_000)
        assert result.cleanup_confirmed
        assert backend.process is not None
        assert all(
            getattr(backend.process, name) is None
            for name in ("stdin", "stdout", "stderr")
        )
        reused = None
        for _ in range(64):
            fd = os.open(tmp_path / "fd-reuse", os.O_RDWR | os.O_CREAT, 0o600)
            opened.append(fd)
            if fd in backend.old_fds:
                reused = fd
                break
        assert reused is not None
        process = backend.process
        backend.process = None
        del process
        gc.collect()
        os.fstat(reused)
    finally:
        for fd in opened:
            os.close(fd)


def test_transport_read_error_is_structured_and_cleanup_runs(tmp_path: Path) -> None:
    """Ordinary result-channel read failure must remain a structured transport outcome."""
    class ReadFailureBackend(IsolatedProcessBackend):
        def _read_channel(self, descriptor, size):
            raise OSError("fixture read failure")

    result = ReadFailureBackend(temp_root=str(tmp_path), cleanup_grace_ms=50).execute(
        f"{HANDLERS}:sync_success", _context(), 2_000
    )
    assert (result.status, result.error_category) == ("worker_lost", "transport_error")
    assert result.cleanup_confirmed
