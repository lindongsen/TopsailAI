"""Real-process tests for the owned hook-script descriptor transport."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from topsailai.hooks.contracts import HookContext, HookEvent, HookStatus
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import HookScriptEntry
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_transport import ScriptTransportFacts
from topsailai.hooks.script_runner import OwnedHookScriptRunner

_CHILD = r'''#!/usr/bin/python3
import json
import os
import signal
import struct
import sys
import time

mode = sys.argv[1]
result_fd = int(os.environ["TOPSAILAI_HOOK_RESULT_FD"])
if mode == "bidirectional-backpressure":
    os.write(1, b"b" * 100000)
request = json.loads(sys.stdin.buffer.read())

def frame(value):
    envelope = {
        "protocol_version": 1,
        "delivery_id": request["delivery_id"],
        "invocation_id": request["invocation_id"],
        "entry_index": request["entry_index"],
        "value": value,
    }
    body = json.dumps(
        envelope, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return struct.pack("!I", len(body)) + body

def emit(value):
    os.write(result_fd, frame(value))

if mode == "inspect":
    descriptors = []
    for name in os.listdir("/proc/self/fd"):
        try:
            descriptor = int(name)
            os.fstat(descriptor)
        except (OSError, ValueError):
            continue
        descriptors.append(descriptor)
    observation = {
        "argv": sys.argv[2:],
        "cwd": os.getcwd(),
        "explicit": os.environ.get("SAFE_EXPLICIT"),
        "secret": os.environ.get("U06_SECRET_SENTINEL"),
        "descriptors": sorted(descriptors),
        "result_fd": result_fd,
        "request_entry": request["entry_index"],
        "request_delivery": request["delivery_id"],
    }
    sys.stdout.buffer.write(json.dumps(observation, sort_keys=True).encode("utf-8"))
    sys.stderr.buffer.write(b"binary\\x00diagnostic")
    emit({"ok": True})
elif mode == "flood":
    os.write(1, b"o" * 100000)
    os.write(2, b"e" * 100000)
    emit({"ok": True})
elif mode == "channel":
    channel, count = sys.argv[2], int(sys.argv[3])
    os.write(1 if channel == "stdout" else 2, channel[0].encode() * count)
    emit({"ok": True})
elif mode == "result-size":
    target = int(sys.argv[2])
    prefix = frame("")
    empty_body = len(prefix) - 4
    emit("r" * (target - empty_body))
elif mode == "split-result":
    payload = frame({"ok": True})
    for byte in payload:
        os.write(result_fd, bytes((byte,)))
    os.write(1, b"o" * int(sys.argv[2]))
    os.write(2, b"e" * int(sys.argv[2]))
elif mode == "early-result":
    emit({"ok": True})
    time.sleep(float(sys.argv[2]))
elif mode == "inherited-result":
    emit({"ok": True})
    child = os.fork()
    if child == 0:
        time.sleep(10)
        os._exit(0)
    time.sleep(10)
elif mode == "descendant-result-only":
    emit({"ok": True})
    child = os.fork()
    if child == 0:
        os.close(0)
        os.close(1)
        os.close(2)
        time.sleep(float(sys.argv[2]))
        os._exit(0)
elif mode == "bidirectional-backpressure":
    emit({"ok": True})
elif mode == "overflow":
    os.write(1, b"x" * 17)
    time.sleep(10)
elif mode == "malformed":
    os.write(result_fd, b"\\x00\\x00\\x00\\x00")
    time.sleep(10)
elif mode == "nonzero":
    raise SystemExit(7)
elif mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
elif mode == "missing":
    pass
elif mode == "hang":
    time.sleep(10)
else:
    emit({"ok": True})
'''


def _context(payload_size: int = 0) -> HookContext:
    """Build one detached context with an optional large transport payload."""
    event = HookEvent(
        "event-u06",
        "u06.event",
        1,
        "owner-u06",
        "scope-u06",
        "operation-u06",
        None,
        1,
        "2026-10-03T00:00:00Z",
        "test",
        "transport",
        {"left": "x" * (payload_size // 2), "right": "x" * (payload_size - payload_size // 2)}
        if payload_size
        else {"value": 1},
    )
    return HookContext(event, "delivery-u06", "hook_script", 1, 5_000)


def _child(tmp_path: Path) -> HookScriptEntry:
    """Create one literal executable child inside pytest-owned storage."""
    path = tmp_path / "u06-child"
    path.write_text(_CHILD, encoding="utf-8")
    path.chmod(0o700)
    return HookScriptEntry(path.resolve(strict=True), path.name)


def _runner(tmp_path: Path, backend_type: type[IsolatedProcessBackend] = IsolatedProcessBackend) -> OwnedHookScriptRunner:
    """Build one admission-scoped runner over a shared cleanup authority."""
    root = tmp_path / "runner-root"
    root.mkdir(mode=0o700)
    return OwnedHookScriptRunner(backend_type(temp_root=str(root)))


def _execute(
    runner: OwnedHookScriptRunner,
    entry: HookScriptEntry,
    mode: str,
    *,
    entry_index: int = 0,
    context: HookContext | None = None,
    policy: HookScriptExecutionPolicy = HookScriptExecutionPolicy(),
    timeout: float = 2.0,
    extra_argv: tuple[str, ...] = (),
    environment: tuple[tuple[str, str], ...] = (),
    output_remaining: int = 65536,
    cancellation: threading.Event | None = None,
) -> object:
    """Execute one child with immutable absolute deadlines."""
    now = time.monotonic()
    return runner.execute_entry(
        entry_index=entry_index,
        entry=entry,
        context=context or _context(),
        options=HookScriptExecutionOptions(
            argv=(mode, *extra_argv), environment=environment
        ),
        policy=policy,
        execution_deadline=now + timeout,
        cleanup_deadline=now + timeout + 1.0,
        output_remaining_bytes=output_remaining,
        cancellation=cancellation or threading.Event(),
    )


def test_real_transport_uses_literal_arguments_bounded_context_and_one_result_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child receives literal inputs and only standard pipes plus one result pipe."""
    monkeypatch.setenv("U06_SECRET_SENTINEL", "must-not-inherit")
    entry = _child(tmp_path)
    runner = _runner(tmp_path)

    result = _execute(
        runner,
        entry,
        "inspect",
        extra_argv=("$(not-expanded)", "semi;colon", "space value"),
        environment=(("SAFE_EXPLICIT", "explicit-value"),),
    )

    observation = json.loads(result.stdout)
    assert result.status is HookStatus.SUCCESS
    assert result.stderr == b"binary\\x00diagnostic"
    assert observation["argv"] == ["$(not-expanded)", "semi;colon", "space value"]
    assert observation["cwd"] == str(entry.source_path.parent)
    assert observation["explicit"] == "explicit-value"
    assert observation["secret"] is None
    assert observation["request_entry"] == 0
    assert observation["request_delivery"] == "delivery-u06"
    assert observation["result_fd"] >= 3
    assert observation["descriptors"] == [0, 1, 2, observation["result_fd"]]
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


def test_real_transport_concurrently_drains_all_output_channels(tmp_path: Path) -> None:
    """Large stdout and stderr writes cannot deadlock result delivery or process exit."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        stdout_limit_bytes=100000,
        stderr_limit_bytes=100000,
        output_total_limit_bytes=220000,
    )

    result = _execute(runner, entry, "flood", policy=policy, output_remaining=220000)

    assert result.status is HookStatus.SUCCESS
    assert result.stdout == b"o" * 100000
    assert result.stderr == b"e" * 100000
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


def test_real_transport_drains_output_while_writing_large_stdin(tmp_path: Path) -> None:
    """Child output backpressure cannot block completion of a large stdin request."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        stdin_limit_bytes=65536,
        stdout_limit_bytes=100000,
        output_total_limit_bytes=120000,
    )

    result = _execute(
        runner,
        entry,
        "bidirectional-backpressure",
        context=_context(60000),
        policy=policy,
        timeout=1.0,
        output_remaining=120000,
    )

    assert result.status is HookStatus.SUCCESS
    assert result.stdout == b"b" * 100000
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()



@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize("count", [15, 16, 17])
def test_diagnostic_channel_limits_are_inclusive(
    tmp_path: Path, channel: str, count: int
) -> None:
    """Each diagnostic channel accepts its cap and rejects only the next byte."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        stdout_limit_bytes=16,
        stderr_limit_bytes=16,
        output_total_limit_bytes=4096,
    )

    result = _execute(
        runner, entry, "channel", policy=policy, extra_argv=(channel, str(count))
    )

    expected = HookStatus.SUCCESS if count <= 16 else HookStatus.INVALID_OUTPUT
    assert result.status is expected
    assert len(result.stdout if channel == "stdout" else result.stderr) == min(count, 16)
    assert result.error_category == (
        None if count <= 16 else "hook_script_output_limit"
    )
    assert result.cleanup_confirmed


@pytest.mark.parametrize("body_size", [255, 256, 257])
def test_result_channel_limits_are_inclusive(
    tmp_path: Path, body_size: int
) -> None:
    """The result body cap excludes its header and rejects the first excess byte."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        result_limit_bytes=256,
        output_total_limit_bytes=4096,
    )

    result = _execute(
        runner, entry, "result-size", policy=policy, extra_argv=(str(body_size),)
    )

    expected = HookStatus.SUCCESS if body_size <= 256 else HookStatus.INVALID_OUTPUT
    assert result.status is expected
    assert result.error_category == (
        None if body_size <= 256 else "hook_script_output_limit"
    )
    assert result.cleanup_confirmed


def test_split_result_frame_and_diagnostic_flood_settle_without_deadlock(
    tmp_path: Path,
) -> None:
    """A byte-split frame remains accounted while both diagnostics are drained."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        stdout_limit_bytes=50000,
        stderr_limit_bytes=50000,
        result_limit_bytes=256,
        output_total_limit_bytes=120000,
    )

    result = _execute(
        runner,
        entry,
        "split-result",
        policy=policy,
        extra_argv=("50000",),
        output_remaining=120000,
    )

    assert result.status is HookStatus.SUCCESS
    assert result.stdout == b"o" * 50000
    assert result.stderr == b"e" * 50000
    assert result.cleanup_confirmed



class _CountingLaunchBackend(IsolatedProcessBackend):
    """Count real script launches for aggregate preflight assertions."""

    def __init__(self, **kwargs: object) -> None:
        """Initialize the backend with no observed launches."""
        super().__init__(**kwargs)
        self.launches = 0

    def launch_script(self, **kwargs: object) -> object:
        """Count and delegate one real owned script launch."""
        self.launches += 1
        return super().launch_script(**kwargs)


def test_mixed_aggregate_observations_block_successor_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retained and non-retained mixed bytes compose into one exhausted batch cap."""
    entry = _child(tmp_path)
    root = tmp_path / "runner-root"
    root.mkdir(mode=0o700)
    backend = _CountingLaunchBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    facts = ScriptTransportFacts(
        stdout=bytearray(b"abc"),
        stderr=bytearray(b"def"),
        result=bytearray(b"\x00\x00\x00\x01"),
        stderr_dropped=1,
        result_observed_bytes=4,
        overflow=True,
        observed_bytes=11,
    )
    monkeypatch.setattr(
        "topsailai.hooks.script_runner.drain_script_process", lambda *args, **kwargs: facts
    )
    policy = HookScriptExecutionPolicy(
        stdout_limit_bytes=16,
        stderr_limit_bytes=16,
        result_limit_bytes=16,
        output_total_limit_bytes=10,
    )

    first = _execute(runner, entry, "hang", policy=policy, output_remaining=10)
    second = _execute(
        runner,
        entry,
        "ok",
        entry_index=1,
        policy=policy,
        output_remaining=4,
    )

    assert facts.observed_bytes == 11
    assert len(facts.result) + len(facts.stdout) + len(facts.stderr) == 10
    assert first.status is HookStatus.INVALID_OUTPUT
    assert first.stdout == b"abc"
    assert first.stderr == b"def"
    assert first.stdout_dropped == 0
    assert first.stderr_dropped == 1
    assert second.status is HookStatus.INVALID_OUTPUT
    assert second.error_category == "hook_script_output_limit"
    assert not second.started
    assert backend.launches == 1
    assert runner.cleanup_debts() == ()

@pytest.mark.parametrize("error_fact", ["overflow", "transport_error"])
@pytest.mark.parametrize(
    ("stop_fact", "expected_status", "expected_category"),
    [
        ("deadline", HookStatus.TIMEOUT, "hook_script_timeout"),
        ("cancelled", HookStatus.CANCELLED, "hook_script_cancelled"),
    ],
)
def test_transport_error_preserves_higher_priority_public_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_fact: str,
    stop_fact: str,
    expected_status: HookStatus,
    expected_category: str,
) -> None:
    """A concurrent stop fact outranks an event error in the returned result."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    facts = ScriptTransportFacts()
    setattr(facts, error_fact, True)
    setattr(facts, stop_fact, True)
    monkeypatch.setattr(
        "topsailai.hooks.script_runner.drain_script_process", lambda *args, **kwargs: facts
    )

    result = _execute(runner, entry, "hang", timeout=0.5)

    assert result.status is expected_status
    assert result.error_category == expected_category
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


def test_exact_aggregate_cap_succeeds_and_next_entry_does_not_launch(
    tmp_path: Path,
) -> None:
    """Observed result framing consumes the batch cap and blocks a successor."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        result_limit_bytes=256,
        output_total_limit_bytes=260,
    )

    first = _execute(
        runner,
        entry,
        "result-size",
        policy=policy,
        extra_argv=("256",),
        output_remaining=260,
    )
    second = _execute(
        runner,
        entry,
        "ok",
        entry_index=1,
        policy=policy,
        output_remaining=260,
    )

    assert first.status is HookStatus.SUCCESS
    assert second.status is HookStatus.INVALID_OUTPUT
    assert second.error_category == "hook_script_output_limit"
    assert not second.started

def test_aggregate_cap_plus_one_fails(tmp_path: Path) -> None:
    """The first byte beyond aggregate capacity terminates the entry."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(
        result_limit_bytes=256,
        output_total_limit_bytes=259,
    )

    result = _execute(
        runner,
        entry,
        "result-size",
        policy=policy,
        extra_argv=("256",),
        output_remaining=259,
    )

    assert result.status is HookStatus.INVALID_OUTPUT
    assert result.error_category == "hook_script_output_limit"
    assert result.cleanup_confirmed


@pytest.mark.parametrize(
    ("delay", "timeout", "expected"),
    [(0.05, 0.5, HookStatus.SUCCESS), (0.5, 0.1, HookStatus.TIMEOUT)],
)
def test_early_result_waits_for_process_exit_and_eof(
    tmp_path: Path, delay: float, timeout: float, expected: HookStatus
) -> None:
    """An early valid frame cannot bypass process exit or output EOF settlement."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    started = time.monotonic()

    result = _execute(
        runner, entry, "early-result", timeout=timeout, extra_argv=(str(delay),)
    )

    assert result.status is expected
    assert time.monotonic() - started >= min(delay, timeout) * 0.8
    assert result.cleanup_confirmed


def test_inherited_open_result_descriptor_is_bounded_by_execution_deadline(
    tmp_path: Path,
) -> None:
    """A descendant-held result writer cannot renew the absolute deadline."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    started = time.monotonic()

    result = _execute(runner, entry, "inherited-result", timeout=0.15)

    assert result.status is HookStatus.TIMEOUT
    assert time.monotonic() - started < 1.0
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


def test_exited_leader_with_descendant_only_result_writer_retains_debt(
    tmp_path: Path,
) -> None:
    """A historical group is not signalled after its leader exits before result EOF."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    started = time.monotonic()

    result = _execute(
        runner,
        entry,
        "descendant-result-only",
        timeout=0.1,
        extra_argv=("0.3",),
    )

    assert time.monotonic() - started < 0.5
    assert result.status is HookStatus.WORKER_LOST
    assert result.error_category == "hook_script_cleanup_pending"
    assert result.exit_code == 0
    assert not result.cleanup_confirmed
    assert result.cleanup_debt is not None
    assert tuple(debt.debt_id for debt in runner.cleanup_debts()) == (
        result.cleanup_debt,
    )

    time.sleep(0.35)
    assert runner.retry_cleanup(result.cleanup_debt)
    assert runner.cleanup_debts() == ()


def test_cooperative_cancellation_stops_transport_and_settles_process(
    tmp_path: Path,
) -> None:
    """Cooperative cancellation is observed without abandoning process ownership."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    cancellation = threading.Event()
    timer = threading.Timer(0.05, cancellation.set)
    timer.start()
    try:
        result = _execute(
            runner, entry, "hang", timeout=1.0, cancellation=cancellation
        )
    finally:
        timer.cancel()

    assert result.status is HookStatus.CANCELLED
    assert result.error_category == "hook_script_cancelled"
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


def test_host_interruption_propagates_after_owned_process_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host interruption propagates only after process ownership is settled."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)

    def interrupt_transport(*args: object, **kwargs: object) -> object:
        """Interrupt after launch while the runner owns the live child."""
        raise KeyboardInterrupt("host interruption")

    monkeypatch.setattr(
        "topsailai.hooks.script_runner.drain_script_process", interrupt_transport
    )

    with pytest.raises(KeyboardInterrupt, match="host interruption"):
        _execute(runner, entry, "hang", timeout=1.0)

    snapshot = runner.current_result(0)
    assert snapshot.status is HookStatus.WORKER_LOST
    assert snapshot.error_category == "host_interrupted"
    assert snapshot.started
    assert snapshot.cleanup_confirmed
    assert runner.cleanup_debts() == ()

@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_category"),
    [
        ("nonzero", HookStatus.ERROR, "hook_script_nonzero_exit"),
        ("signal", HookStatus.WORKER_LOST, "hook_script_signal_exit"),
        ("missing", HookStatus.INVALID_OUTPUT, "hook_script_missing_result"),
        ("hang", HookStatus.TIMEOUT, "hook_script_timeout"),
        ("overflow", HookStatus.INVALID_OUTPUT, "hook_script_output_limit"),
        ("malformed", HookStatus.INVALID_OUTPUT, "hook_script_invalid_result"),
    ],
)
def test_real_transport_arbitrates_exit_timeout_and_enforcement(
    tmp_path: Path,
    mode: str,
    expected_status: HookStatus,
    expected_category: str,
) -> None:
    """Observed script failures retain their frozen category after process cleanup."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path)
    policy = HookScriptExecutionPolicy(stdout_limit_bytes=16, terminate_grace_ms=20)

    result = _execute(runner, entry, mode, policy=policy, timeout=0.15)

    assert result.status is expected_status
    assert result.error_category == expected_category
    assert result.started
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


class _OneFailedTerminationBackend(IsolatedProcessBackend):
    """Inject one unconfirmed cleanup attempt before using real owned termination."""

    def __init__(self, **kwargs: object) -> None:
        """Initialize one deterministic failure counter."""
        super().__init__(**kwargs)
        self.failures_remaining = 1

    def _terminate_record(self, record: object, process: object) -> bool:
        """Retain the first cleanup debt and delegate every later exact retry."""
        if self.failures_remaining:
            self.failures_remaining -= 1
            return False
        return super()._terminate_record(record, process)


def test_cleanup_failure_is_queryable_and_retryable_without_storage_removal(
    tmp_path: Path,
) -> None:
    """Unconfirmed process cleanup owns storage until exact debt retry succeeds."""
    entry = _child(tmp_path)
    runner = _runner(tmp_path, _OneFailedTerminationBackend)

    result = _execute(runner, entry, "hang", timeout=0.1)

    assert result.status is HookStatus.WORKER_LOST
    assert result.error_category == "hook_script_cleanup_pending"
    assert not result.cleanup_confirmed
    assert result.cleanup_debt is not None
    assert tuple(debt.debt_id for debt in runner.cleanup_debts()) == (
        result.cleanup_debt,
    )
    assert runner.retry_cleanup(result.cleanup_debt)
    assert runner.cleanup_debts() == ()
