"""Focused C05 arbitration and immutable-cleanup regressions."""

from __future__ import annotations

import json
import signal
import threading
import time
from pathlib import Path

import pytest

from topsailai.hooks.contracts import HookContext, HookEvent, HookStatus
from topsailai.hooks.hook_script_contracts import (
    HookScriptEntryResult,
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import HookScriptEntry
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import CleanupDebt, LaunchRecord, WorkerResult
from topsailai.hooks.process_transport import ScriptTransportFacts
from topsailai.hooks.script_protocol import ScriptResult, encode_script_result
from topsailai.hooks.script_runner import OwnedHookScriptRunner, _classify_result
from topsailai.hooks.temporary_storage import TemporaryStorageOwner


def test_owned_runner_is_public_and_satisfies_runner_protocol() -> None:
    """The package export must expose a concrete structural runner implementation."""
    import topsailai.hooks as hooks

    required = tuple(
        name for name in hooks.HookScriptRunner.__dict__ if not name.startswith("_")
    )
    assert "OwnedHookScriptRunner" in hooks.__all__
    assert hooks.OwnedHookScriptRunner is OwnedHookScriptRunner
    assert required == (
        "execute_entry",
        "current_result",
        "cleanup_debts",
        "retry_cleanup",
    )
    assert all(callable(getattr(OwnedHookScriptRunner, name, None)) for name in required)


@pytest.fixture
def context() -> HookContext:
    """Build one valid detached execution context."""
    event = HookEvent(
        "event-u06-03",
        "u06.arbitration",
        1,
        "owner-u06",
        "scope-u06",
        "operation-u06",
        None,
        1,
        "2026-10-04T00:00:00Z",
        "test",
        "arbitration",
        {"value": 1},
    )
    return HookContext(event, "delivery-u06-03", "hook_script", 1, 5_000)


def _base() -> HookScriptEntryResult:
    """Build the classification seed used by pure arbitration checks."""
    return HookScriptEntryResult(0, "script", HookStatus.ERROR, True)


def _valid_result(context: HookContext) -> bytes:
    """Encode one valid correlated result frame."""
    return encode_script_result(
        delivery_id=context.delivery_id,
        invocation_id="a" * 32,
        entry_index=0,
        value={"ok": True},
        result_limit_bytes=16_384,
    )


def _complete_json_frame(value: dict[str, object]) -> bytes:
    """Frame one complete JSON object without applying result schema validation."""
    body = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return len(body).to_bytes(4, "big") + body


def _classify(context: HookContext, **facts: object) -> HookScriptEntryResult:
    """Classify controlled independent facts through the production arbiter."""
    observed = ScriptTransportFacts(
        result=bytearray(_valid_result(context)), exit_code=0, settled=True
    )
    for name, value in facts.items():
        setattr(observed, name, value)
    return _classify_result(
        _base(),
        observed,
        context,
        "a" * 32,
        HookScriptExecutionPolicy(),
        time.monotonic(),
    )


@pytest.mark.parametrize(
    ("facts", "status", "category"),
    [
        ({"cancelled": True, "deadline": True}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"cancelled": True, "overflow": True}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"cancelled": True, "exit_code": -signal.SIGTERM}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"cancelled": True, "exit_code": 7}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"cancelled": True, "invalid_result": True}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"cancelled": True, "transport_error": True}, HookStatus.CANCELLED, "hook_script_cancelled"),
        ({"deadline": True, "overflow": True}, HookStatus.TIMEOUT, "hook_script_timeout"),
        ({"deadline": True, "exit_code": -signal.SIGTERM}, HookStatus.TIMEOUT, "hook_script_timeout"),
        ({"deadline": True, "exit_code": 7}, HookStatus.TIMEOUT, "hook_script_timeout"),
        ({"deadline": True, "invalid_result": True}, HookStatus.TIMEOUT, "hook_script_timeout"),
        ({"deadline": True, "transport_error": True}, HookStatus.TIMEOUT, "hook_script_timeout"),
        ({"overflow": True, "exit_code": -signal.SIGTERM}, HookStatus.INVALID_OUTPUT, "hook_script_output_limit"),
        ({"overflow": True, "exit_code": 7}, HookStatus.INVALID_OUTPUT, "hook_script_output_limit"),
        ({"overflow": True, "invalid_result": True}, HookStatus.INVALID_OUTPUT, "hook_script_output_limit"),
        ({"overflow": True, "transport_error": True}, HookStatus.INVALID_OUTPUT, "hook_script_output_limit"),
        ({"exit_code": -signal.SIGTERM, "invalid_result": True}, HookStatus.WORKER_LOST, "hook_script_signal_exit"),
        ({"exit_code": -signal.SIGTERM, "transport_error": True}, HookStatus.WORKER_LOST, "hook_script_signal_exit"),
        ({"exit_code": 7, "invalid_result": True}, HookStatus.ERROR, "hook_script_nonzero_exit"),
        ({"exit_code": 7, "transport_error": True}, HookStatus.ERROR, "hook_script_nonzero_exit"),
        ({"invalid_result": True, "transport_error": True}, HookStatus.INVALID_OUTPUT, "hook_script_invalid_result"),
    ],
)
def test_c05_failure_priority_pairs(
    context: HookContext,
    facts: dict[str, object],
    status: HookStatus,
    category: str,
) -> None:
    """Every higher-priority observed failure must dominate its paired lower fact."""
    result = _classify(context, **facts)

    assert result.status is status
    assert result.error_category == category


def test_valid_settlement_uses_u05_decoder(
    context: HookContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful settlement must pass its exact frame through the U05 decoder."""
    calls: list[tuple[bytes, dict[str, object]]] = []

    def decode(data: bytes, **expected: object) -> ScriptResult:
        calls.append((data, expected))
        return ScriptResult({"ok": True}, len(data))

    monkeypatch.setattr("topsailai.hooks.script_runner.decode_script_result", decode)

    result = _classify(context)

    assert result.status is HookStatus.SUCCESS
    assert result.error_category is None
    assert calls == [
        (
            _valid_result(context),
            {
                "delivery_id": context.delivery_id,
                "invocation_id": "a" * 32,
                "entry_index": 0,
                "result_limit_bytes": 16_384,
            },
        )
    ]


class _LaunchFailureBackend(IsolatedProcessBackend):
    """Return a controlled pre-process startup failure."""

    def launch_script(self, **kwargs: object) -> WorkerResult:
        """Reject before process creation with confirmed cleanup."""
        return WorkerResult("worker_lost", error_category="startup_failure")


def test_confirmed_preprocess_launch_failure_maps_to_startup_failed(
    tmp_path: Path, context: HookContext
) -> None:
    """A launch failure before process creation uses the frozen startup category."""
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    script = tmp_path / "script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    now = time.monotonic()

    result = runner.execute_entry(
        entry_index=0,
        entry=HookScriptEntry(script.resolve(strict=True), script.name),
        context=context,
        options=HookScriptExecutionOptions(),
        policy=HookScriptExecutionPolicy(),
        execution_deadline=now + 1,
        cleanup_deadline=now + 2,
        output_remaining_bytes=65_536,
        cancellation=threading.Event(),
    )

    assert not result.started
    assert result.status is HookStatus.ERROR
    assert result.error_category == "hook_script_startup_failed"
    assert result.cleanup_confirmed
    assert runner.cleanup_debts() == ()


class _LiveProcess:
    """Represent one still-running exact process leader."""

    pid = 424242

    def poll(self) -> None:
        """Keep the process live for every cleanup retry."""
        return None


class _ExpiredCleanupBackend(IsolatedProcessBackend):
    """Expose exact group state without touching a real process."""

    def _group_exists(self, pgid: int) -> bool:
        """Keep the exact owned group live after its immutable deadline."""
        return True


def test_expired_cleanup_debt_retry_never_renews_deadline_or_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated debt retries retain the original expired deadline and authority."""
    backend = _ExpiredCleanupBackend(temp_root=str(tmp_path))
    process = _LiveProcess()
    original_deadline = time.monotonic() - 1
    record = LaunchRecord(
        "expired-cleanup",
        process=process,  # type: ignore[arg-type]
        cleanup_deadline=original_deadline,
        termination_grace=10.0,
        group_authorized=True,
    )
    record.cleanup.termination_started = True
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "topsailai.hooks.process_termination.os.killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )
    backend._record_process_debt(
        record.debt_id,
        process,  # type: ignore[arg-type]
        "fixture",
        record,
    )

    assert not backend.retry_cleanup(record.debt_id)
    assert not backend.retry_cleanup(record.debt_id)
    assert record.cleanup_deadline == original_deadline
    assert signals == []
    assert backend.cleanup_debts()[0].debt_id == record.debt_id


def test_prelaunch_deadline_precedes_exhausted_aggregate(
    tmp_path: Path, context: HookContext
) -> None:
    """An expired execution deadline must precede prelaunch output exhaustion."""
    root = tmp_path / "deadline-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "deadline-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    now = time.monotonic()

    result = runner.execute_entry(
        entry_index=0,
        entry=HookScriptEntry(script.resolve(strict=True), script.name),
        context=context,
        options=HookScriptExecutionOptions(),
        policy=HookScriptExecutionPolicy(),
        execution_deadline=now - 1,
        cleanup_deadline=now + 1,
        output_remaining_bytes=0,
        cancellation=threading.Event(),
    )

    assert not result.started
    assert result.status is HookStatus.SKIPPED_DEADLINE
    assert result.error_category == "hook_script_deadline"
    assert tuple(root.iterdir()) == ()


def test_prelaunch_cancellation_precedes_deadline_and_output_limit(
    tmp_path: Path, context: HookContext
) -> None:
    """Cooperative cancellation must dominate every prelaunch exhausted budget."""
    root = tmp_path / "cancel-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "cancel-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    cancellation = threading.Event()
    cancellation.set()
    now = time.monotonic()

    result = runner.execute_entry(
        entry_index=0,
        entry=HookScriptEntry(script.resolve(strict=True), script.name),
        context=context,
        options=HookScriptExecutionOptions(),
        policy=HookScriptExecutionPolicy(),
        execution_deadline=now - 1,
        cleanup_deadline=now + 1,
        output_remaining_bytes=0,
        cancellation=cancellation,
    )

    assert not result.started
    assert result.status is HookStatus.CANCELLED
    assert result.error_category == "hook_script_cancelled"
    assert tuple(root.iterdir()) == ()


def _classify_observed(
    context: HookContext, observed: ScriptTransportFacts
) -> HookScriptEntryResult:
    """Classify an explicitly constructed transport observation."""
    return _classify_result(
        _base(),
        observed,
        context,
        "a" * 32,
        HookScriptExecutionPolicy(),
        time.monotonic(),
    )


def test_missing_result_precedes_transport_error_when_complete(
    context: HookContext,
) -> None:
    """A known zero exit and result EOF provide sufficient missing-result evidence."""
    facts = ScriptTransportFacts(
        exit_code=0,
        transport_error=True,
        eof={"result"},
    )

    result = _classify_observed(context, facts)

    assert result.status is HookStatus.INVALID_OUTPUT
    assert result.error_category == "hook_script_missing_result"


@pytest.mark.parametrize("result_eof", [False, True])
def test_complete_schema_invalid_result_precedes_transport_error(
    context: HookContext, result_eof: bool
) -> None:
    """A complete framed schema failure must precede transport fallback."""
    frame = _complete_json_frame(
        {
            "protocol_version": 1,
            "delivery_id": context.delivery_id,
            "invocation_id": "a" * 32,
            "entry_index": 0,
            "unexpected": True,
        }
    )
    facts = ScriptTransportFacts(
        result=bytearray(frame),
        exit_code=0,
        transport_error=True,
        eof={"result"} if result_eof else set(),
    )

    result = _classify_observed(context, facts)

    assert result.status is HookStatus.INVALID_OUTPUT
    assert result.error_category == "hook_script_invalid_result"


@pytest.mark.parametrize("result_eof", [False, True])
def test_complete_correlation_invalid_result_precedes_transport_error(
    context: HookContext, result_eof: bool
) -> None:
    """A complete correlated frame mismatch must precede transport fallback."""
    frame = encode_script_result(
        delivery_id=context.delivery_id,
        invocation_id="b" * 32,
        entry_index=0,
        value={"ok": True},
        result_limit_bytes=16_384,
    )
    facts = ScriptTransportFacts(
        result=bytearray(frame),
        exit_code=0,
        transport_error=True,
        eof={"result"} if result_eof else set(),
    )

    result = _classify_observed(context, facts)

    assert result.status is HookStatus.INVALID_OUTPUT
    assert result.error_category == "hook_script_invalid_result"


@pytest.mark.parametrize("result_eof", [False, True])
def test_complete_valid_result_with_transport_error_does_not_succeed(
    context: HookContext, result_eof: bool
) -> None:
    """Transport failure remains authoritative after a complete valid result."""
    facts = ScriptTransportFacts(
        result=bytearray(_valid_result(context)),
        exit_code=0,
        transport_error=True,
        eof={"result"} if result_eof else set(),
    )

    result = _classify_observed(context, facts)

    assert result.status is HookStatus.WORKER_LOST
    assert result.error_category == "hook_script_transport_error"


@pytest.mark.parametrize(
    "facts",
    [
        ScriptTransportFacts(transport_error=True),
        ScriptTransportFacts(exit_code=0, transport_error=True),
    ],
)
def test_incomplete_result_evidence_is_not_classified_as_missing(
    context: HookContext, facts: ScriptTransportFacts
) -> None:
    """Unknown exit or absent result EOF must fall back to transport failure."""
    result = _classify_observed(context, facts)

    assert result.status is HookStatus.WORKER_LOST
    assert result.error_category == "hook_script_transport_error"


@pytest.mark.parametrize(
    "result",
    [
        b"\x00\x00",
        (100).to_bytes(4, "big") + b"partial-body",
    ],
)
def test_nonempty_incomplete_result_without_eof_defers_to_transport_error(
    context: HookContext, result: bytes
) -> None:
    """A valid frame prefix without EOF is not conclusive invalid-output evidence."""
    facts = ScriptTransportFacts(
        result=bytearray(result),
        exit_code=0,
        transport_error=True,
    )

    classified = _classify_observed(context, facts)

    assert classified.status is HookStatus.WORKER_LOST
    assert classified.error_category == "hook_script_transport_error"


@pytest.mark.parametrize(
    "result",
    [
        b"\x00\x00",
        (100).to_bytes(4, "big") + b"partial-body",
    ],
)
def test_incomplete_result_with_eof_is_invalid(
    context: HookContext, result: bytes
) -> None:
    """Result EOF makes a partial header or body conclusive invalid output."""
    facts = ScriptTransportFacts(
        result=bytearray(result),
        exit_code=0,
        transport_error=True,
        eof={"result"},
    )

    classified = _classify_observed(context, facts)

    assert classified.status is HookStatus.INVALID_OUTPUT
    assert classified.error_category == "hook_script_invalid_result"


class _SettledProcessDebtBackend(IsolatedProcessBackend):
    """Confirm one controlled process debt without mutating storage."""

    def retry_cleanup(self, debt_id: str) -> bool:
        """Confirm only the fixture process debt."""
        return debt_id == "process-debt"

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Expose no process debt after the controlled retry succeeds."""
        return ()


def test_interrupted_process_to_storage_cleanup_retains_exact_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host interruption during storage handoff preserves queryable exact debt."""
    root = tmp_path / "storage-root"
    root.mkdir(mode=0o700)
    runner = OwnedHookScriptRunner(_SettledProcessDebtBackend(temp_root=str(root)))
    storage = TemporaryStorageOwner(root)
    unrelated = TemporaryStorageOwner(root)
    assert storage.allocate()
    assert unrelated.allocate()
    storage_path = storage.path
    unrelated_path = unrelated.path
    runner._remember_process_storage("process-debt", storage)
    runner._remember_storage(unrelated)
    storage_debt = storage.cleanup_debts()[0]
    unrelated_debt = unrelated.cleanup_debts()[0]
    interruption = KeyboardInterrupt("storage cleanup interrupted")
    original_rmtree = __import__("shutil").rmtree
    interrupted = False

    def interrupt_target(path: Path) -> None:
        nonlocal interrupted
        if Path(path) == storage_path and not interrupted:
            interrupted = True
            raise interruption
        original_rmtree(path)

    monkeypatch.setattr("topsailai.hooks.temporary_storage.shutil.rmtree", interrupt_target)

    with pytest.raises(KeyboardInterrupt) as caught:
        runner.retry_cleanup("process-debt")

    assert caught.value is interruption
    assert storage_path.exists()
    assert unrelated_path.exists()
    assert {debt.debt_id for debt in runner.cleanup_debts()} == {
        storage_debt.debt_id,
        unrelated_debt.debt_id,
    }

    assert runner.retry_cleanup("process-debt")
    assert not storage_path.exists()
    assert unrelated_path.exists()
    assert {debt.debt_id for debt in runner.cleanup_debts()} == {
        unrelated_debt.debt_id
    }
    assert runner.retry_cleanup(unrelated_debt.debt_id)
    assert not unrelated_path.exists()
    assert runner.cleanup_debts() == ()
