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


@pytest.mark.parametrize("boundary", ["uuid", "encode", "argv", "cwd", "environment", "clock", "record_uuid", "record"])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup_mode", ["success", "failure", "interrupt"])
def test_prelaunch_interrupt_preserves_exact_storage_custody(
    tmp_path: Path, context: HookContext, monkeypatch: pytest.MonkeyPatch,
    boundary: str, interrupt_type: type[BaseException], cleanup_mode: str,
) -> None:
    """Every prelaunch interruption retains exact recoverable storage authority."""
    import inspect
    import sys
    from types import SimpleNamespace
    import topsailai.hooks.script_runner as module

    root = tmp_path / "prelaunch-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "prelaunch-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    unrelated = TemporaryStorageOwner(root)
    assert unrelated.allocate()
    unrelated_path = unrelated.path
    unrelated_path.joinpath("keep").write_text("unchanged", encoding="utf-8")
    now = time.monotonic()
    primary = interrupt_type("prelaunch primary")
    owners: list[TemporaryStorageOwner] = []
    launches: list[object] = []
    original_allocate = TemporaryStorageOwner.allocate
    original_cleanup = TemporaryStorageOwner.cleanup
    original_uuid = module.uuid.uuid4
    source, first_line = inspect.getsourcelines(module.OwnedHookScriptRunner.execute_entry)
    argv_line = first_line + next(i for i, line in enumerate(source) if "argv = (" in line)
    prior_trace = sys.gettrace()

    def allocate(owner: TemporaryStorageOwner) -> bool:
        """Observe only the real successfully allocated invocation owner."""
        accepted = original_allocate(owner)
        if accepted:
            owners.append(owner)
        return accepted

    def fail(*args, **kwargs):
        """Raise the exact primary exception at the chosen boundary."""
        raise primary

    def cleanup(owner: TemporaryStorageOwner) -> bool:
        """Inject cleanup failure only for this invocation's exact owner."""
        if owners and owner is owners[0]:
            if cleanup_mode == "failure":
                return False
            if cleanup_mode == "interrupt":
                raise SystemExit("secondary cleanup interrupt")
        return original_cleanup(owner)

    uuid_calls = 0

    def uuid_value():
        """Leave allocation UUID intact and interrupt the selected runner UUID."""
        nonlocal uuid_calls
        uuid_calls += 1
        if uuid_calls == (1 if boundary == "uuid" else 2):
            raise primary
        return original_uuid()

    def trace(frame, event, arg):
        """Interrupt argv construction without mutating shared platform modules."""
        if frame.f_code is module.OwnedHookScriptRunner.execute_entry.__code__ and event == "line" and frame.f_lineno == argv_line:
            raise primary
        return trace

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(TemporaryStorageOwner, "cleanup", cleanup)
            patch.setattr(runner._backend, "launch_script", lambda **kwargs: launches.append(kwargs))
            if boundary in {"uuid", "record_uuid"}:
                patch.setattr(module, "uuid", SimpleNamespace(uuid4=uuid_value))
            elif boundary == "clock":
                patch.setattr(module, "time", SimpleNamespace(monotonic=lambda: fail() if owners else now))
            elif boundary != "argv":
                target = {"encode": "encode_script_input", "cwd": "_execution_cwd", "environment": "_execution_environment", "record": "LaunchRecord"}[boundary]
                patch.setattr(module, target, fail)
            if boundary == "argv":
                sys.settrace(trace)
            try:
                with pytest.raises(interrupt_type) as caught:
                    runner.execute_entry(
                        entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                        context=context, options=HookScriptExecutionOptions(),
                        policy=HookScriptExecutionPolicy(), execution_deadline=now + 5,
                        cleanup_deadline=now + 6, output_remaining_bytes=65_536,
                        cancellation=threading.Event(),
                    )
            finally:
                sys.settrace(prior_trace)
            assert caught.value is primary
            traceback = caught.value.__traceback__
            names = []
            while traceback is not None:
                names.append(traceback.tb_frame.f_code.co_name)
                traceback = traceback.tb_next
            assert names[-1] in {"fail", "uuid_value", "trace"}
            assert "execute_entry" in names
            assert launches == []
            assert len(owners) == 1
            assert unrelated_path.joinpath("keep").read_text(encoding="utf-8") == "unchanged"
            debts = runner.cleanup_debts()
            if cleanup_mode == "success":
                assert debts == ()
                assert owners[0].cleanup_debts() == ()
                assert tuple(root.iterdir()) == (unrelated_path,)
            else:
                assert debts == owners[0].cleanup_debts()
                assert len(debts) == 1
                assert runner._storage[debts[0].debt_id] is owners[0]
        for debt in runner.cleanup_debts():
            assert runner.retry_cleanup(debt.debt_id)
        assert runner.cleanup_debts() == ()
        assert runner._storage == {}
        assert unrelated_path.exists()
    finally:
        sys.settrace(prior_trace)
        for owner in owners:
            original_cleanup(owner)
        original_cleanup(unrelated)


@pytest.mark.parametrize("error", [OSError("setup"), ValueError("setup")])
def test_prelaunch_ordinary_setup_classification(tmp_path, context, monkeypatch, error):
    """Ordinary setup failures retain startup classification and settle storage."""
    root = tmp_path / "ordinary-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "ordinary-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))

    def fail(*args, **kwargs):
        """Reject setup before the backend can launch."""
        raise error

    monkeypatch.setattr("topsailai.hooks.script_runner._execution_cwd", fail)
    now = time.monotonic()
    result = runner.execute_entry(
        entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
        context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
        execution_deadline=now + 5, cleanup_deadline=now + 6,
        output_remaining_bytes=65_536, cancellation=threading.Event(),
    )
    assert not result.started and result.error_category == "hook_script_startup_failed"
    assert result.cleanup_confirmed and runner.cleanup_debts() == ()
    assert tuple(root.iterdir()) == ()


@pytest.mark.parametrize("stage", ["retain", "observe", "lock", "before", "after", "allocate"])
@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [RuntimeError, SystemExit])
@pytest.mark.parametrize("cleanup_mode", ["success", "failure", "interrupt"])
def test_recovery_registration_failure_preserves_primary_and_owner(
    tmp_path, context, monkeypatch, stage, primary_type, secondary_type, cleanup_mode,
):
    """Registration failure cannot strand a real owner or replace its primary."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "recovery-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "recovery-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    unrelated = TemporaryStorageOwner(root)
    assert unrelated.allocate()
    keep = unrelated.path / "keep"
    keep.write_text("unchanged", encoding="utf-8")
    primary = primary_type("primary")
    secondary = secondary_type("registration")
    owners, launches, cleanups = [], [], []
    allocate_original = TemporaryStorageOwner.allocate
    cleanup_original = TemporaryStorageOwner.cleanup
    retain_original = TemporaryStorageOwner.retain_cleanup_debt
    debts_original = TemporaryStorageOwner.cleanup_debts
    remember_original = runner._remember_storage
    lock_original = runner._lock
    now = time.monotonic()

    def allocate(owner):
        """Allocate genuine storage, then interrupt the allocation handoff."""
        result = allocate_original(owner)
        owners.append(owner)
        if stage == "allocate":
            raise primary
        return result

    def fail(*args, **kwargs):
        """Raise the authoritative prelaunch interrupt."""
        raise primary

    def cleanup(owner):
        """Record exact cleanup and inject only the invocation failure."""
        if owner in owners:
            cleanups.append(owner)
            if cleanup_mode == "failure":
                return False
            if cleanup_mode == "interrupt":
                raise SystemExit("cleanup")
        return cleanup_original(owner)

    def retain(owner):
        """Fail debt retention only inside registration."""
        if owner in owners and stage == "retain":
            raise secondary
        return retain_original(owner)

    def debts(owner):
        """Fail registration observation without corrupting other owners."""
        if owner in owners and stage == "observe":
            raise secondary
        return debts_original(owner)

    class InterruptedLock:
        """Inject exactly the registration lock boundary."""
        def __enter__(self):
            """Reject this lock acquisition."""
            raise secondary

        def __exit__(self, *args):
            """Provide the context-manager protocol."""
            return False

    def remember(owner):
        """Exercise real helper stages, including completed publication."""
        if stage == "before":
            raise secondary
        if stage == "lock":
            runner._lock = InterruptedLock()
        try:
            remember_original(owner)
        finally:
            runner._lock = lock_original
        if stage == "after":
            raise secondary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(TemporaryStorageOwner, "cleanup", cleanup)
            patch.setattr(TemporaryStorageOwner, "retain_cleanup_debt", retain)
            patch.setattr(TemporaryStorageOwner, "cleanup_debts", debts)
            patch.setattr(runner, "_remember_storage", remember)
            patch.setattr(module, "encode_script_input", fail)
            patch.setattr(runner._backend, "launch_script", lambda **kw: launches.append(kw))
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(),
                    policy=HookScriptExecutionPolicy(), execution_deadline=now + 5,
                    cleanup_deadline=now + 6, output_remaining_bytes=65_536,
                    cancellation=threading.Event(),
                )
            assert caught.value is primary
            traceback = primary.__traceback__
            while traceback.tb_next is not None:
                traceback = traceback.tb_next
            assert traceback.tb_frame.f_code.co_name == ("allocate" if stage == "allocate" else "fail")
            assert cleanups == owners and len(owners) == 1
            assert launches == [] and keep.read_text(encoding="utf-8") == "unchanged"
        seen, pending = set(), [primary]
        while pending:
            error = pending.pop()
            assert id(error) not in seen
            seen.add(id(error))
            if error.__context__ is not None:
                pending.append(error.__context__)
        public = runner.cleanup_debts()
        if cleanup_mode == "success":
            assert public == () and owners[0].cleanup_debts() == ()
        else:
            assert public == owners[0].cleanup_debts() and len(public) == 1
            assert runner.retry_cleanup(public[0].debt_id)
            runner.retry_cleanup(public[0].debt_id)
            assert runner._prelaunch_storage == {}
        assert runner.cleanup_debts() == ()
        assert runner._storage == {} and keep.exists()
    finally:
        runner._lock = lock_original
        for owner in owners:
            cleanup_original(owner)
        cleanup_original(unrelated)


@pytest.mark.parametrize("boundary", range(6))
@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup_mode", ["success", "failure", "interrupt"])
def test_launch_handoff_continuously_armed(
    tmp_path, context, monkeypatch, boundary, primary_type, cleanup_mode,
):
    """Interrupt each handoff statement before launch using genuine storage."""
    import inspect
    import sys

    source, first = inspect.getsourcelines(OwnedHookScriptRunner.execute_entry)
    call = next(i for i, line in enumerate(source) if "spawned = self._backend.launch_script" in line)
    handoff = max(i for i, line in enumerate(source) if "lease = None" in line)
    withdrawal = [i for i, line in enumerate(source[:call]) if "if not custody.pending:" in line or "self._prelaunch_storage.pop" in line]
    # Old withdrawal sites disappear after repair; still probe all new guarded sites.
    candidates = withdrawal + [handoff, call, call + 1, call + 2, call + 3, call + 5]
    target = first + candidates[boundary]
    root = tmp_path / "handoff-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "handoff-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    keep = root / "unrelated"
    keep.mkdir()
    (keep / "keep").write_text("unchanged", encoding="utf-8")
    owners, launches, cleanups = [], [], []
    original_allocate = TemporaryStorageOwner.allocate
    original_cleanup = TemporaryStorageOwner.cleanup
    primary = primary_type("handoff")
    prior = sys.gettrace()
    armed = True

    def allocate(owner):
        """Capture only the real invocation owner."""
        result = original_allocate(owner)
        owners.append(owner)
        return result

    def cleanup(owner):
        """Inject an exact cleanup failure without affecting unrelated storage."""
        cleanups.append(owner)
        if cleanup_mode == "failure":
            return False
        if cleanup_mode == "interrupt":
            raise SystemExit("secondary cleanup")
        return original_cleanup(owner)

    def trace(frame, event, arg):
        """Disarm before interrupting the target frame so recovery can run."""
        nonlocal armed
        if armed and event == "line" and frame.f_code is OwnedHookScriptRunner.execute_entry.__code__ and frame.f_lineno == target:
            armed = False
            raise primary
        return trace

    now = time.monotonic()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(TemporaryStorageOwner, "cleanup", cleanup)
            patch.setattr(runner._backend, "launch_script", lambda **kw: launches.append(kw))
            sys.settrace(trace)
            try:
                with pytest.raises(primary_type) as caught:
                    runner.execute_entry(
                        entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                        context=context, options=HookScriptExecutionOptions(),
                        policy=HookScriptExecutionPolicy(), execution_deadline=now + 5,
                        cleanup_deadline=now + 6, output_remaining_bytes=65_536,
                        cancellation=threading.Event(),
                    )
            finally:
                sys.settrace(prior)
            assert not armed and caught.value is primary and launches == []
            tb = primary.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "trace"
            assert cleanups == owners and len(owners) == 1
        debts = runner.cleanup_debts()
        if cleanup_mode == "success":
            assert debts == () and owners[0].cleanup_debts() == ()
        else:
            assert debts == owners[0].cleanup_debts() and len(debts) == 1
            assert runner.retry_cleanup(debts[0].debt_id)
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        assert runner._storage == {} and (keep / "keep").read_text() == "unchanged"
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(prior)
        for owner in owners:
            original_cleanup(owner)


def test_public_retry_cannot_claim_healthy_launch_storage(tmp_path, context, monkeypatch):
    """Synchronize public recovery against healthy preparation and launch ownership."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "active-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "active-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(_LaunchFailureBackend(temp_root=str(root)))
    owners, errors, results = [], [], []
    reached, proceed = threading.Event(), threading.Event()
    original_allocate = TemporaryStorageOwner.allocate
    original_encode = module.encode_script_input

    def allocate(owner):
        """Observe the genuine invocation owner."""
        result = original_allocate(owner)
        owners.append(owner)
        return result

    def pause():
        """Wait for the public recovery check using events rather than sleeps."""
        reached.set()
        assert proceed.wait(5)
        proceed.clear()

    def encode(**kw):
        """Pause while preparation legitimately owns storage."""
        pause()
        return original_encode(**kw)

    def launch(**kw):
        """Pause inside the launch receiver before returning its normal failure."""
        pause()
        return WorkerResult(status="error", error_category="worker_startup_failed")

    def execute():
        """Run execution on a distinct thread and retain all errors."""
        try:
            now = time.monotonic()
            results.append(runner.execute_entry(
                entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                context=context, options=HookScriptExecutionOptions(),
                policy=HookScriptExecutionPolicy(), execution_deadline=now + 30,
                cleanup_deadline=now + 31, output_remaining_bytes=65_536,
                cancellation=threading.Event(),
            ))
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(TemporaryStorageOwner, "allocate", allocate)
    monkeypatch.setattr(module, "encode_script_input", encode)
    monkeypatch.setattr(runner._backend, "launch_script", launch)
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        for _ in range(2):
            assert reached.wait(5)
            reached.clear()
            debt = owners[0].cleanup_debts()[0]
            assert runner.cleanup_debts() == ()
            runner.retry_cleanup(debt.debt_id)
            assert owners[0].path.exists()
            proceed.set()
        worker.join(5)
        assert not worker.is_alive() and errors == [] and len(results) == 1
        assert results[0].cleanup_confirmed and not results[0].started
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
    finally:
        proceed.set()
        worker.join(5)
        for owner in owners:
            owner.cleanup()


@pytest.mark.parametrize("stage", ["launch", "launch_interrupt", "drain_error", "drain_interrupt"])
def test_handoff_preserves_existing_launch_error_and_process_cleanup(
    tmp_path, context, monkeypatch, stage,
):
    """Exercise ordinary launch mapping and genuine postlaunch process-first cleanup."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "compat-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "compat-script"
    script.write_text("#!/bin/false\n", encoding="utf-8")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    primary = KeyboardInterrupt("host") if stage.endswith("interrupt") else RuntimeError("controlled error")

    def fail(*args, **kwargs):
        """Inject at the real production boundary after ownership is established."""
        raise primary

    monkeypatch.setattr(backend if stage.startswith("launch") else module,
                        "launch_script" if stage.startswith("launch") else "drain_script_process", fail)
    now = time.monotonic()
    kwargs = dict(
        entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
        context=context, options=HookScriptExecutionOptions(),
        policy=HookScriptExecutionPolicy(), execution_deadline=now + 5,
        cleanup_deadline=now + 6, output_remaining_bytes=65_536,
        cancellation=threading.Event(),
    )
    if stage.endswith("interrupt"):
        with pytest.raises(KeyboardInterrupt) as caught:
            runner.execute_entry(**kwargs)
        assert caught.value is primary
        result = runner.current_result(0)
    else:
        result = runner.execute_entry(**kwargs)
    assert result.started is (not stage.startswith("launch"))
    assert result.error_category == ("hook_script_startup_failed" if stage.startswith("launch") else "host_interrupted")
    assert result.cleanup_confirmed and runner.cleanup_debts() == ()
    assert runner._prelaunch_storage == {} and tuple(root.iterdir()) == ()


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("process_pending", [False, True])
@pytest.mark.parametrize("storage_mode", ["success", "failure", "interrupt"])
@pytest.mark.parametrize("publication", ["before", "after", "observe", "retain", "lock", "recovery"])
def test_process_recovery_publication_preserves_exact_custody(
    tmp_path, context, monkeypatch, primary_type, process_pending, storage_mode, publication,
):
    """Cross real process interruption with failed recovery and ordered exact retry."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "process-recovery-root"
    root.mkdir(mode=0o700)
    keep = root / "unrelated"
    keep.mkdir()
    (keep / "keep").write_text("unchanged")
    script = tmp_path / "process-recovery-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    owners, records, cleanup_calls = [], [], []
    original_allocate = TemporaryStorageOwner.allocate
    original_cleanup = TemporaryStorageOwner.cleanup
    original_launch = backend.launch_script
    original_remember = runner._remember_process_storage if process_pending else runner._remember_storage
    primary = primary_type("authoritative drain interruption")
    secondary = SystemExit("secondary recovery interruption")

    def allocate(owner):
        """Capture a genuine temporary storage owner."""
        result = original_allocate(owner)
        owners.append(owner)
        return result

    def launch(**kwargs):
        """Capture the exact backend record with a genuine child."""
        records.append(kwargs["record"])
        return original_launch(**kwargs)

    def drain(*args, **kwargs):
        """Interrupt after actual process ownership has been accepted."""
        raise primary

    def cleanup(owner):
        """Assert ordering and inject exact storage cleanup outcomes."""
        cleanup_calls.append(owner)
        assert records[0].cleanup.termination_confirmed
        if storage_mode == "interrupt":
            raise secondary
        return original_cleanup(owner) if storage_mode == "success" else False

    class FailedLock:
        """Reject the actual runner recovery registration lock."""
        def __enter__(self):
            """Interrupt recovery locking."""
            raise secondary

        def __exit__(self, *args):
            """Provide the lock context protocol."""
            return False

    def remember(*args):
        """Fail before, within or after actual recovery publication."""
        if publication == "lock":
            original_lock = runner._lock
            runner._lock = FailedLock()
            try:
                original_remember(*args)
            finally:
                runner._lock = original_lock
        if publication == "after":
            original_remember(*args)
        raise secondary

    def fail_recovery(*args):
        """Interrupt the receiver before it has cleaned the real process."""
        raise secondary

    def observe(owner):
        """Make genuine owner debt observation temporarily unavailable."""
        raise RuntimeError("debt observation unavailable")

    now = time.monotonic()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(TemporaryStorageOwner, "cleanup", cleanup)
            patch.setattr(backend, "launch_script", launch)
            patch.setattr(module, "drain_script_process", drain)
            if process_pending:
                patch.setattr(backend, "_terminate_record", lambda *args: False)
            if publication == "recovery":
                patch.setattr(runner, "_preserve_interrupted", fail_recovery)
            elif publication == "observe":
                patch.setattr(TemporaryStorageOwner, "cleanup_debts", observe)
            elif publication == "retain":
                patch.setattr(TemporaryStorageOwner, "retain_cleanup_debt", fail_recovery)
            else:
                patch.setattr(runner, "_remember_process_storage" if process_pending else "_remember_storage", remember)
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(),
                    policy=HookScriptExecutionPolicy(), execution_deadline=now + 5,
                    cleanup_deadline=now + 6, output_remaining_bytes=65_536,
                    cancellation=threading.Event(),
                )
            assert caught.value is primary
            tb = primary.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "drain"
            assert len(records) == len(owners) == 1
            assert len(cleanup_calls) == (0 if process_pending or publication == "recovery" else 1)
            if process_pending and publication != "recovery":
                assert not runner.retry_cleanup(records[0].debt_id)
                assert cleanup_calls == []
            if publication == "observe" and not process_pending and storage_mode != "success":
                with pytest.raises(RuntimeError):
                    runner.cleanup_debts()
        debts = runner.cleanup_debts()
        if process_pending or publication == "recovery":
            assert len(debts) == 1 and debts[0].debt_id == records[0].debt_id
            storage_debt = owners[0].cleanup_debts()[0]
            runner.retry_cleanup(storage_debt.debt_id)
            assert owners[0].path.exists()
            with monkeypatch.context() as retry_patch:
                retry_patch.setattr(TemporaryStorageOwner, "cleanup", lambda owner: False)
                assert not runner.retry_cleanup(records[0].debt_id)
            assert runner.retry_cleanup(records[0].debt_id)
        elif storage_mode != "success":
            assert debts == owners[0].cleanup_debts() and len(debts) == 1
            assert runner.retry_cleanup(debts[0].debt_id)
        else:
            assert debts == ()
        assert records[0].process.poll() is not None
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        assert runner._storage == runner._process_storage == {}
        assert (keep / "keep").read_text() == "unchanged"
        seen = set()

        def acyclic(error, ancestors):
            """Check both cause and context edges without rejecting shared leaves."""
            if error is None:
                return
            assert id(error) not in ancestors
            seen.add(id(error))
            acyclic(error.__cause__, ancestors | {id(error)})
            acyclic(error.__context__, ancestors | {id(error)})

        acyclic(primary, set())
    finally:
        for record in records:
            backend.retry_cleanup(record.debt_id)
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
        for owner in owners:
            original_cleanup(owner)


def test_process_recovery_public_retry_waits_for_active_cleanup(tmp_path, context, monkeypatch):
    """Use events to deny concurrent storage removal during real recovery."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "active-recovery-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "active-recovery-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    reached, proceed = threading.Event(), threading.Event()
    owners, errors = [], []
    original_allocate = TemporaryStorageOwner.allocate
    original_remember = runner._remember_storage
    primary = KeyboardInterrupt("drain")

    def allocate(owner):
        """Capture genuine invocation storage."""
        result = original_allocate(owner)
        owners.append(owner)
        return result

    def drain(*args, **kwargs):
        """Interrupt the genuinely launched process."""
        raise primary

    def remember(owner):
        """Pause after partial publication while recovery still owns cleanup."""
        original_remember(owner)
        reached.set()
        assert proceed.wait(5)
        raise SystemExit("publication interrupted")

    def execute():
        """Capture the authoritative interruption on the execution thread."""
        now = time.monotonic()
        try:
            runner.execute_entry(
                entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                execution_deadline=now + 5, cleanup_deadline=now + 6,
                output_remaining_bytes=65_536, cancellation=threading.Event(),
            )
        except BaseException as exc:
            errors.append(exc)

    with monkeypatch.context() as patch:
        patch.setattr(TemporaryStorageOwner, "allocate", allocate)
        patch.setattr(TemporaryStorageOwner, "cleanup", lambda owner: False)
        patch.setattr(module, "drain_script_process", drain)
        patch.setattr(runner, "_remember_storage", remember)
        worker = threading.Thread(target=execute)
        worker.start()
        try:
            assert reached.wait(5)
            debt = owners[0].cleanup_debts()[0]
            assert runner.cleanup_debts() == ()
            record = runner._prelaunch_storage[id(owners[0])].record
            assert not runner.retry_cleanup(record.debt_id)
            runner.retry_cleanup(debt.debt_id)
            assert owners[0].path.exists()
        finally:
            proceed.set()
            worker.join(5)
    assert not worker.is_alive() and errors == [primary]
    assert runner.cleanup_debts() == owners[0].cleanup_debts()
    assert runner.retry_cleanup(debt.debt_id)
    assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
