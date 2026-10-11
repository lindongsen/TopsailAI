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


from topsailai.hooks.script_runner import _StorageCustody

_CANONICAL_CUSTODY_WRITE = _StorageCustody._write_state
_CUSTODY_FAULT_STATES = {}
_RUNNER_OBSERVATION_FAULTS = {}


def _install_custody_state_fault(custody, shadow):
    """Retain only detached test fault data indexed by exact invocation identity."""
    _CUSTODY_FAULT_STATES[id(custody)] = (custody, shadow)


def _fault_custody_write(custody, _retire=(), **changes):
    """Publish fault-side effects through canonical transition even after interruption."""
    entry = _CUSTODY_FAULT_STATES.get(id(custody))
    if entry is None or entry[0] is not custody:
        return _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changes)
    shadow = entry[1]
    before = dict(custody.__dict__)
    dict.update(shadow, before)
    try:
        for name, value in changes.items():
            shadow[name] = value
    finally:
        changed = {name: dict.get(shadow, name) for name in changes
                   if dict.get(shadow, name) is not before.get(name)}
        if changed or _retire:
            _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changed)


@pytest.fixture(autouse=True)
def _isolate_custody_fault_states(monkeypatch):
    """Scope legacy detached fault seams to one test without production switches."""
    native_get = _StorageCustody.__getattr__
    def observe(custody, name):
        """Inject field reads only for this exact registered test shadow."""
        entry = _CUSTODY_FAULT_STATES.get(id(custody))
        if entry is not None and entry[0] is custody:
            value = native_get(custody, name)
            dict.__setitem__(entry[1], name, value)
            return entry[1][name]
        return native_get(custody, name)
    monkeypatch.setattr(_StorageCustody, "_write_state", _fault_custody_write)
    monkeypatch.setattr(_StorageCustody, "__getattr__", observe)
    native_observer = OwnedHookScriptRunner._observe_prelaunch_storage

    def registry_observer(runner):
        """Route trusted test observations by exact identity without production switches."""
        entry = _RUNNER_OBSERVATION_FAULTS.get(id(runner))
        if entry is not None and entry[0] is runner:
            return entry[1]
        return native_observer.__get__(runner, type(runner))

    monkeypatch.setattr(OwnedHookScriptRunner, "_observe_prelaunch_storage", property(registry_observer))
    yield
    _CUSTODY_FAULT_STATES.clear()
    _RUNNER_OBSERVATION_FAULTS.clear()


def _custody_field_write(custody, name, value):
    """Commit legacy fault-fixture fields only through the original legal writer."""
    _fault_custody_write(custody, **{name: value})


def _install_custody_assignment_fault(patch, assign):
    """Translate old attribute interception into controlled field transition interception."""
    def write(custody, _retire=(), **changes):
        """Keep injected before/after exception identity without exposing canonical maps."""
        if _retire:
            _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire)
        for name, value in changes.items():
            assign(custody, name, value)
    patch.setattr(_StorageCustody, "_write_state", write)


def _install_registry_fault(runner, fault):
    """Translate legacy dictionary faults into controlled transition/observation faults."""
    if not hasattr(runner, "_registry_fault_originals"):
        runner._registry_fault_originals = (
            runner._observe_prelaunch_storage, runner._write_prelaunch_storage,
        )
    observe, write = runner._registry_fault_originals
    _RUNNER_OBSERVATION_FAULTS.pop(id(runner), None)
    runner._write_prelaunch_storage = write
    if type(fault) is dict:
        return
    deletion_attempts = {}

    def canonical_write(changes=(), retire=()):
        """Pass the private exact snapshot rather than a detached injected observation."""
        if not runner._transition_prelaunch_storage(observe(), changes, retire):
            raise RuntimeError("test registry transition lost exact snapshot authority")

    def observe_fault():
        """Inject lookup failure against a detached copy, never canonical storage."""
        return type(fault)(observe())

    def write_fault(changes=(), retire=()):
        """Preserve before/after removal faults while committing only through authority."""
        if changes:
            canonical_write(changes, ())
        for identity in retire:
            view = type(fault)(observe())
            try:
                attempt = deletion_attempts.get(identity, 0)
                deletion_attempts[identity] = attempt + 1
                if attempt >= 2:
                    canonical_write(retire=(identity,))
                    return
                if attempt == 1:
                    del view[identity]
                else:
                    view.pop(identity, None)
            finally:
                if identity not in view:
                    canonical_write(retire=(identity,))
            if identity in observe():
                canonical_write(retire=(identity,))

    _RUNNER_OBSERVATION_FAULTS[id(runner)] = (runner, observe_fault)
    runner._write_prelaunch_storage = write_fault


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


@pytest.mark.parametrize("boundary", ["arming", "pending", "receiver", "completion", "accepted", "disarming"])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup_mode", ["success", "failure", "interrupt"])
def test_recovery_state_boundary_preserves_primary(
    tmp_path, context, monkeypatch, boundary, primary_type, cleanup_mode, secondary_type,
):
    """Interrupt real recovery state transitions without losing exact process custody."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module

    source, first = inspect.getsourcelines(OwnedHookScriptRunner.execute_entry)
    markers = {
        "arming": "custody._write_state(recovering=True)",
        "pending": "custody._write_state(pending=True)",
        "receiver": "recovered = self._preserve_interrupted",
        "completion": "custody._write_state(pending=not recovered.cleanup_confirmed)",
        "accepted": "recovery_complete = True",
        "disarming": "custody._write_state(recovering=False)",
    }
    start = next(i for i, line in enumerate(source) if "except (KeyboardInterrupt" in line)
    target = first + next(i for i in range(start, len(source)) if markers[boundary] in source[i])
    root = tmp_path / "state-root"
    root.mkdir(mode=0o700)
    keep = root / "unrelated"
    keep.mkdir()
    script = tmp_path / "state-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    owners, records, paths = [], [], []
    allocate_original, cleanup_original = TemporaryStorageOwner.allocate, TemporaryStorageOwner.cleanup
    launch_original = backend.launch_script
    primary = primary_type("authoritative drain")
    armed = True
    prior = sys.gettrace()

    def allocate(owner):
        """Capture genuine allocation without altering its ownership."""
        result = allocate_original(owner)
        owners.append(owner)
        paths.append(owner.path)
        return result

    def launch(**kwargs):
        """Capture the genuine process record."""
        records.append(kwargs["record"])
        return launch_original(**kwargs)

    def drain(*args, **kwargs):
        """Raise the authoritative exception after process launch."""
        raise primary

    def cleanup(owner):
        """Inject storage outcomes only after exact process settlement."""
        assert records[0].cleanup.termination_confirmed
        if cleanup_mode == "interrupt":
            raise SystemExit("storage secondary")
        return cleanup_original(owner) if cleanup_mode == "success" else False

    def trace(frame, event, arg):
        """Disarm before injecting one secondary host interruption."""
        nonlocal armed
        if frame.f_code is not OwnedHookScriptRunner.execute_entry.__code__:
            return prior(frame, event, arg) if prior is not None else trace
        frame.f_trace = trace
        if armed and event == "line" and frame.f_code is OwnedHookScriptRunner.execute_entry.__code__ and frame.f_lineno == target:
            armed = False
            raise secondary_type("recovery boundary secondary")
        return trace

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(TemporaryStorageOwner, "cleanup", cleanup)
            patch.setattr(backend, "launch_script", launch)
            patch.setattr(module, "drain_script_process", drain)
            sys.settrace(trace)
            try:
                now = time.monotonic()
                with pytest.raises(primary_type) as caught:
                    runner.execute_entry(
                        entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                        options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                        execution_deadline=now + 5, cleanup_deadline=now + 6,
                        output_remaining_bytes=65_536, cancellation=threading.Event(),
                    )
            finally:
                sys.settrace(prior)
            # Failed storage cleanup exits before the completion statement.
            assert not armed or (boundary in ("completion", "accepted") and cleanup_mode == "interrupt")
            assert caught.value is primary
            tb = primary.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "drain"
        assert len(records) == len(owners) == 1
        assert all(not custody.recovering for custody in runner._prelaunch_storage.values())
        for debt in runner.cleanup_debts():
            assert runner.retry_cleanup(debt.debt_id)
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        assert not paths[0].exists() and keep.exists()
        ancestors, error = set(), primary
        while error is not None:
            assert id(error) not in ancestors
            ancestors.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(prior)
        for record in records:
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
        for owner in owners:
            cleanup_original(owner)


def test_partial_storage_publication_waits_for_authoritative_settlement(tmp_path, context, monkeypatch):
    """Mask partial storage authority until exact process settlement can be observed."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "partial-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "partial-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    primary = KeyboardInterrupt("drain")

    def drain(*args, **kwargs):
        """Interrupt the genuine process to leave exact recovery responsibility."""
        raise primary

    def publication(initial, record, storage, started):
        """Publish storage prematurely and fail before process settlement."""
        runner._remember_storage(storage)
        raise SystemExit("partial publication")

    now = time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(module, "drain_script_process", drain)
        patch.setattr(runner, "_preserve_interrupted", publication)
        with pytest.raises(KeyboardInterrupt) as caught:
            runner.execute_entry(
                entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                execution_deadline=now + 5, cleanup_deadline=now + 6,
                output_remaining_bytes=65_536, cancellation=threading.Event(),
            )
        assert caught.value is primary
    custody = next(iter(runner._prelaunch_storage.values()))
    storage_debt = custody.owner.cleanup_debts()[0]
    storage_path = custody.owner.path
    assert runner.cleanup_debts()[0].debt_id == custody.record.debt_id
    with monkeypatch.context() as patch:
        patch.setattr(backend, "retry_cleanup", lambda debt_id: True)
        patch.setattr(backend, "_finish_record", lambda *args: None)
        runner.retry_cleanup(storage_debt.debt_id)
        assert not runner.retry_cleanup(custody.record.debt_id)
        assert custody.owner.path.exists()
        assert runner._prelaunch_storage[id(custody.owner)] is custody
    assert runner.retry_cleanup(custody.record.debt_id)
    assert runner.cleanup_debts() == () and not storage_path.exists()


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_completed_recovery_observation_preserves_primary(tmp_path, context, monkeypatch, primary_type):
    """Retain completed cleanup when the first recovery-result observation interrupts."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "observed-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "observed-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    original = runner._preserve_interrupted
    primary = primary_type("drain primary")

    class InterruptedObservation:
        """Expose the genuine result with one transient observation interruption."""
        def __init__(self, result):
            """Keep the actual completed recovery result."""
            self.result = result
            self.first = True

        @property
        def cleanup_confirmed(self):
            """Interrupt once and then return genuine settlement evidence."""
            if self.first:
                self.first = False
                raise SystemExit("result observation")
            return self.result.cleanup_confirmed

    def recover(*args):
        """Run real process/storage cleanup before injecting observation failure."""
        return InterruptedObservation(original(*args))

    def drain(*args, **kwargs):
        """Interrupt the genuine launched process."""
        raise primary

    monkeypatch.setattr(module, "drain_script_process", drain)
    monkeypatch.setattr(runner, "_preserve_interrupted", recover)
    now = time.monotonic()
    with pytest.raises(primary_type) as caught:
        runner.execute_entry(
            entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
            options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
            execution_deadline=now + 5, cleanup_deadline=now + 6,
            output_remaining_bytes=65_536, cancellation=threading.Event(),
        )
    assert caught.value is primary
    assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
    assert tuple(root.iterdir()) == ()


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("settlement", ["complete", "process", "storage"])
@pytest.mark.parametrize("fallback_boundary", ["observation", "entry", "exit"])
def test_recovery_fallback_persistent_observation(
    tmp_path, context, monkeypatch, primary_type, secondary_type, settlement, fallback_boundary,
):
    """Keep genuine custody reachable without re-reading failed result diagnostics."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "fallback-root"
    root.mkdir(mode=0o700)
    keep = root / "unrelated"
    keep.mkdir()
    script = tmp_path / "fallback-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    original = runner._preserve_interrupted
    cleanup = TemporaryStorageOwner.cleanup
    owners, records, paths, observations = [], [], [], []
    primary = primary_type("authoritative drain")
    allocate_original = TemporaryStorageOwner.allocate
    import inspect
    import sys
    prior = sys.gettrace()
    armed = fallback_boundary != "observation"
    source, first = inspect.getsourcelines(OwnedHookScriptRunner.execute_entry)
    marker = "custody._write_state(recovering=False)" if fallback_boundary == "entry" else "if custody.storage_settled:"
    fallback_start = next(i for i, line in enumerate(source) if "Abandoned recovery" in line)
    target = first + next(i for i in range(fallback_start, len(source)) if marker in source[i])

    def trace(frame, event, arg):
        """Inject after failed observation without racing process cleanup."""
        nonlocal armed
        if armed and event == "line" and frame.f_code is OwnedHookScriptRunner.execute_entry.__code__ and frame.f_lineno == target:
            armed = False
            raise secondary_type("fallback boundary")
        return trace

    def allocate(owner):
        """Capture the actual allocated owner and immutable path."""
        result = allocate_original(owner)
        owners.append(owner)
        paths.append(owner.path)
        return result

    class FailedObservation:
        """Fail every observation after real recovery work."""
        @property
        def cleanup_confirmed(self):
            """Reject repeated diagnostic reads deterministically."""
            observations.append(True)
            if armed:
                frame = sys._getframe(1)
                frame.f_trace = trace
                sys.settrace(trace)
            raise secondary_type("persistent settlement observation")

    def recover(initial, record, storage, started):
        """Run real recovery or leave exact process custody unsettled."""
        records.append(record)
        if settlement == "process":
            runner._remember_storage(storage)
        else:
            original(initial, record, storage, started)
        return FailedObservation()

    def drain(*args, **kwargs):
        """Raise the authoritative exception in the genuine process path."""
        raise primary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "allocate", allocate)
            patch.setattr(module, "drain_script_process", drain)
            patch.setattr(runner, "_preserve_interrupted", recover)
            if settlement == "storage":
                patch.setattr(TemporaryStorageOwner, "cleanup", lambda owner: False)
            now = time.monotonic()
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                    options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65_536, cancellation=threading.Event(),
                )
            sys.settrace(prior)
            assert caught.value is primary
            assert not armed
            assert len(observations) <= 1
            assert all(not c.recovering for c in runner._prelaunch_storage.values())
            tb = primary.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "drain"
        if settlement == "complete":
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        else:
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = records[0].debt_id if settlement == "process" else owners[0].cleanup_debts()[0].debt_id
            assert debts[0].debt_id == expected and paths[0].exists()
            assert runner.retry_cleanup(expected)
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        assert not paths[0].exists() and keep.exists()
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(prior)
        for record in records:
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
        for owner in owners:
            cleanup(owner)


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
def test_recovery_fallback_final_release_interruption(tmp_path, context, monkeypatch, primary_type):
    """A failed final registry release must not hide already-settled custody."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "release-root"
    root.mkdir(mode=0o700)
    script = tmp_path / "release-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    primary = primary_type("drain primary")

    class InterruptedRelease(dict):
        """Reject one exact final release without deleting another owner."""
        def pop(self, key, default=None):
            """Interrupt once before removing the settled exact record."""
            if self:
                raise SystemExit("final release")
            return super().pop(key, default)

    _install_registry_fault(runner, InterruptedRelease())

    def drain(*args, **kwargs):
        """Interrupt after the real process has been launched."""
        raise primary

    monkeypatch.setattr(module, "drain_script_process", drain)
    now = time.monotonic()
    with pytest.raises(primary_type) as caught:
        runner.execute_entry(
            entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
            options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
            execution_deadline=now + 5, cleanup_deadline=now + 6,
            output_remaining_bytes=65_536, cancellation=threading.Event(),
        )
    assert caught.value is primary
    assert runner.cleanup_debts() == ()
    assert runner._prelaunch_storage == {}


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("settlement", ["complete", "process", "storage"])
@pytest.mark.parametrize("fault", ["repair", "release", "pending_release", "repair_method", "released_pop", "released_delete"])
def test_recovery_outer_repair_and_repeated_release(
    tmp_path, context, monkeypatch, primary_type, secondary_type, settlement, fault,
):
    """Keep exact real custody reachable after a second recovery-boundary failure."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module

    root = tmp_path / "outer-root"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "outer-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    original = runner._preserve_interrupted
    primary = primary_type("authoritative drain")
    records, owners, hits = [], [], []
    previous = sys.gettrace()
    source, first = inspect.getsourcelines(OwnedHookScriptRunner.execute_entry)
    outer = next(i for i, line in enumerate(source) if "if primary is not None and lease" in line)
    target = first + next(i for i in range(outer, len(source)) if "custody._write_state(recovering=False)" in source[i])
    if fault == "pending_release":
        target = first + next(i for i in range(outer, len(source)) if "if release_verified and not custody.pending and self._prelaunch_storage.get" in source[i])
    armed = fault in {"repair", "pending_release"}
    repair_armed = fault == "repair_method"
    original_setattr = _custody_field_write

    def fail_repair(custody, name, value):
        """Inject one real local state mutation failure without replacing the tracer."""
        nonlocal repair_armed
        if repair_armed and name == "recovering" and sys._getframe(2).f_lineno == target:
            repair_armed = False
            hits.append("repair")
            raise secondary_type("outer state mutation")
        original_setattr(custody, name, value)

    def trace(frame, event, arg):
        """Interrupt exactly once before outer repair clears recovery exclusion."""
        nonlocal armed
        if armed and event == "line" and frame.f_code is OwnedHookScriptRunner.execute_entry.__code__ and frame.f_lineno == target:
            armed = False
            hits.append("repair")
            raise secondary_type("outer repair")
        return trace

    class FailedRelease(dict):
        """Reject both fallible exact-release attempts without unrelated deletion."""
        def pop(self, key, default=None):
            """Inject the first release interruption."""
            hits.append("pop")
            if fault == "released_pop":
                super().pop(key, default)
            raise secondary_type("release pop")

        def __delitem__(self, key):
            """Inject the second release interruption."""
            hits.append("delete")
            if fault == "released_delete":
                super().__delitem__(key)
            raise secondary_type("release delete")

    class FailedObservation:
        """Force the outer repair after real or explicitly unsettled recovery."""
        @property
        def cleanup_confirmed(self):
            """Fail the first observation and arm target-frame instrumentation."""
            if armed:
                frame = sys._getframe(1)
                frame.f_trace = trace
                sys.settrace(trace)
            raise secondary_type("observation")

    def recover(initial, record, storage, started):
        """Capture exact resources and exercise genuine settlement paths."""
        records.append(record)
        owners.append((storage, storage.path))
        if settlement == "process":
            runner._remember_storage(storage)
        else:
            original(initial, record, storage, started)
        # Leave exclusion armed to simulate interruption of the preceding finally.
        runner._prelaunch_storage[id(storage)]._write_state(recovering=True)
        return FailedObservation()

    def drain(*args, **kwargs):
        """Raise the original interruption after the actual child launch."""
        raise primary

    if fault in {"release", "released_pop", "released_delete"}:
        _install_registry_fault(runner, FailedRelease())
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "drain_script_process", drain)
            patch.setattr(runner, "_preserve_interrupted", recover)
            _install_custody_assignment_fault(patch, fail_repair)
            if settlement == "storage":
                patch.setattr(TemporaryStorageOwner, "cleanup", lambda owner: False)
            now = time.monotonic()
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                    options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65_536, cancellation=threading.Event(),
                )
            sys.settrace(previous)
            assert caught.value is primary
            assert all(not c.recovering for c in runner._prelaunch_storage.values())
            if fault in {"repair", "pending_release", "repair_method"}:
                assert hits == ["repair"]
            elif settlement == "complete":
                assert "pop" in hits
                if fault != "released_pop":
                    assert "delete" in hits
            tb = primary.__traceback__
            while tb.tb_next:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "drain"
        # Restore ordinary registry operations before the public retry.
        _install_registry_fault(runner, dict(runner._prelaunch_storage))
        if settlement == "complete":
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        else:
            debts = runner.cleanup_debts()
            assert len(debts) == 1 and owners[0][1].exists()
            expected = records[0].debt_id if settlement == "process" else owners[0][0].cleanup_debts()[0].debt_id
            assert debts[0].debt_id == expected
            assert runner.retry_cleanup(expected)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert unrelated.exists() and not owners[0][1].exists()
        seen, stack = set(), [primary]
        while stack:
            error = stack.pop()
            assert id(error) not in seen
            seen.add(id(error))
            stack.extend(e for e in (error.__cause__, error.__context__) if e is not None)
    finally:
        sys.settrace(previous)
        _install_registry_fault(runner, dict(runner._prelaunch_storage))
        for record in records:
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
        for owner, path in owners:
            if path.exists():
                print(f"cleanup exact test storage: {path}")
            TemporaryStorageOwner.cleanup(owner)


def test_storage_settlement_without_backup(tmp_path):
    """Successful exact cleanup must support an already-released backup."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    runner = OwnedHookScriptRunner(backend)
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    result = HookScriptEntryResult(0, "standalone", HookStatus.ERROR, True)
    assert runner._settle_storage(result, owner) is result
    assert runner._prelaunch_storage == {}


def test_final_release_without_primary_propagates(tmp_path, context, monkeypatch):
    """An ordinary final registry failure is not disguised as host recovery."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    failure = RuntimeError("ordinary release")

    class FailedRelease(dict):
        """Fail the final release even when allocation was rejected."""
        def pop(self, key, default=None):
            """Raise the same ordinary failure for the caller."""
            raise failure

    _install_registry_fault(runner, FailedRelease())
    monkeypatch.setattr(TemporaryStorageOwner, "allocate", lambda owner: False)
    script = tmp_path / "ordinary-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    now = time.monotonic()
    with pytest.raises(RuntimeError) as caught:
        runner.execute_entry(
            entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
            options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
            execution_deadline=now + 5, cleanup_deadline=now + 6,
            output_remaining_bytes=65_536, cancellation=threading.Event(),
        )
    assert caught.value is failure


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("fault", ["lookup", "journal_before", "journal_after", "storage_fail", "storage_interrupt", "process"])
def test_storage_settlement_journal_exact_handoff(
    tmp_path, context, monkeypatch, primary_type, secondary_type, fault,
):
    """Transfer real cleanup facts without post-destruction registry authority."""
    import sys
    import topsailai.hooks.script_runner as module

    root = tmp_path / "journal-root"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "journal-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    original = runner._preserve_interrupted
    cleanup = TemporaryStorageOwner.cleanup
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    captured, hits, cleanups = [], [], []
    primary = primary_type("authoritative drain")

    class FailedLookup(dict):
        """Continuously reject only the exact settlement lookup."""
        def get(self, key, default=None):
            """Fail before any destructive cleanup may obtain custody."""
            if sys._getframe(1).f_code is OwnedHookScriptRunner._settle_storage.__code__:
                hits.append("lookup")
                raise secondary_type("journal lookup")
            return super().get(key, default)

    def set_fact(custody, name, value):
        """Interrupt publication before or after its native mutation."""
        if name == "storage_settled" and value is True and fault.startswith("journal") and not hits:
            hits.append("journal")
            if fault == "journal_after":
                native_set(custody, name, value)
            raise secondary_type("journal write")
        native_set(custody, name, value)

    def remove(owner):
        """Exercise actual cleanup or retain the exact unsettled directory."""
        cleanups.append(owner)
        if fault == "storage_fail":
            return False
        if fault == "storage_interrupt":
            raise secondary_type("storage cleanup")
        return cleanup(owner)

    def recover(initial, record, owner, started):
        """Capture exact real resources and optionally leave process unsettled."""
        captured.append((record, owner, owner.path))
        if fault == "process":
            runner._remember_storage(owner)
            result = HookScriptEntryResult(0, script.name, HookStatus.WORKER_LOST, True,
                                          cleanup_confirmed=False, cleanup_debt=record.debt_id)
            return runner._settle_storage(result, owner)
        return original(initial, record, owner, started)

    def drain(*args, **kwargs):
        """Raise the primary only after the production child has launched."""
        raise primary

    try:
        with monkeypatch.context() as patch:
            if fault == "lookup":
                _install_registry_fault(runner, FailedLookup())
            _install_custody_assignment_fault(patch, set_fact)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            patch.setattr(runner, "_preserve_interrupted", recover)
            patch.setattr(module, "drain_script_process", drain)
            now = time.monotonic()
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                    options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65_536, cancellation=threading.Event(),
                )
            assert caught.value is primary
            tb = primary.__traceback__
            while tb.tb_next is not None:
                tb = tb.tb_next
            assert tb.tb_frame.f_code.co_name == "drain"
            assert all(not c.recovering for c in runner._prelaunch_storage.values())
            record, owner, path = captured[0]
            if fault.startswith("journal"):
                assert hits == ["journal"] and cleanups == [owner]
                assert not path.exists() and owner.cleanup_debts() == ()
                assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            else:
                assert path.exists()
                if fault in {"lookup", "process"}:
                    assert cleanups == []
                if fault == "lookup":
                    assert hits == ["lookup"]
                assert len(runner._prelaunch_storage) == 1
            seen, error = set(), primary
            while error is not None:
                assert id(error) not in seen
                seen.add(id(error))
                error = error.__context__
        _install_registry_fault(runner, dict(runner._prelaunch_storage))
        if not fault.startswith("journal"):
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            assert runner.retry_cleanup(debts[0].debt_id)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert not path.exists() and unrelated.exists()
    finally:
        _install_registry_fault(runner, dict(runner._prelaunch_storage))
        for record, owner, path in captured:
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
            if path.exists():
                print(f"cleanup exact journal owner: {path}")
            cleanup(owner)


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["entry", "fallback_entry", "fallback_write", "fallback_exit"])
def test_storage_settlement_journal_protection_entry(tmp_path, context, monkeypatch, primary_type, secondary_type, boundary):
    """Interrupt after real cleanup returns but before journal protection enters."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module

    root = tmp_path / "journal-entry-root"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "journal-entry-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    original = runner._preserve_interrupted
    cleanup = TemporaryStorageOwner.cleanup
    captured, hits = [], []
    primary = primary_type("authoritative drain")
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._settle_storage)
    if boundary == "entry":
        target = first + next(i for i, line in enumerate(source) if "if custody is not None:" in line)
    elif boundary == "fallback_entry":
        target = first + next(i for i, line in enumerate(source) if "if journal is not None and all" in line)
    elif boundary == "fallback_write":
        target = first + next(i for i, line in enumerate(source) if 'custody._write_state(storage_settled=True)' in line)
    else:
        target = first + next(i for i, line in enumerate(source) if 'custody._write_state(storage_settled=True)' in line)
    previous = sys.gettrace()
    armed = True

    def trace(frame, event, arg):
        """Inject once at the exact journal boundary, not during cleanup."""
        nonlocal armed
        target_event = "return" if boundary == "fallback_exit" else "line"
        if armed and event == target_event and frame.f_code is OwnedHookScriptRunner._settle_storage.__code__ and (boundary == "fallback_exit" or frame.f_lineno == target):
            armed = False
            hits.append("entry")
            raise secondary_type("journal protection entry")
        return trace

    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner

    def interrupt_journal(custody, name, value):
        """Require fallback to publish the already-completed exact cleanup fact."""
        if boundary.startswith("fallback") and name == "storage_settled" and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type("initial journal publication")
        native_set(custody, name, value)

    def recover(initial, record, owner, started):
        """Capture exact production resources before genuine recovery."""
        captured.append((record, owner, owner.path))
        return original(initial, record, owner, started)

    def drain(*args, **kwargs):
        """Arm only the settlement frame after the real process launch."""
        sys.settrace(trace)
        raise primary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "drain_script_process", drain)
            patch.setattr(runner, "_preserve_interrupted", recover)
            _install_custody_assignment_fault(patch, interrupt_journal)
            now = time.monotonic()
            with pytest.raises(primary_type) as caught:
                runner.execute_entry(
                    entry_index=0, entry=HookScriptEntry(script.resolve(), script.name), context=context,
                    options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65_536, cancellation=threading.Event(),
                )
            sys.settrace(previous)
            record, owner, path = captured[0]
            assert caught.value is primary and hits == ["entry"]
            assert not path.exists() and owner.cleanup_debts() == ()
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            assert unrelated.exists()
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                                   {"stdout": 0, "stderr": 0}, "test_cleanup")
            if path.exists():
                print(f"cleanup exact journal entry owner: {path}")
            cleanup(owner)


@pytest.mark.parametrize('primary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('secondary_type', [KeyboardInterrupt, SystemExit])
def test_repeated_outer_observation_preserves_primary(tmp_path, monkeypatch, primary_type, secondary_type):
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits = [], []
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        return recover(initial, record, owner, started)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        record, owner, path = captured[0]
        assert hits and hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert record.process.poll() is not None
        assert record.cleanup.debt_state == 'settled'
        assert not path.exists() and owner.cleanup_debts() == ()
        assert runner._prelaunch_storage == {}
        assert runner.cleanup_debts() == () and backend.cleanup_debts() == ()
        assert unrelated.exists()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize('primary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('secondary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('boundary', ['condition', 'write', 'exit', 'native'])
@pytest.mark.parametrize('settlement', ['complete', 'process', 'storage'])
def test_outer_native_reconciliation_boundary(tmp_path, monkeypatch, primary_type, secondary_type, boundary, settlement):
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    source, first = inspect.getsourcelines(module.OwnedHookScriptRunner.execute_entry)
    marker = 'if (owner_state["_path"]' if boundary == 'condition' else 'custody._write_state(pending=not custody.storage_settled)'
    if boundary in {'exit', 'native'}:
        marker = 'break'
    fallback = next(i for i, line in enumerate(source) if 'Read prebound native authority' in line)
    target = first + next(i for i in range(fallback, len(source)) if marker in source[i])
    previous = sys.gettrace()
    armed = boundary != 'native'
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == 'line' and frame.f_code is runner.execute_entry.__func__.__code__ and frame.f_lineno == target:
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and not native_hits
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        if boundary != 'native':
            sys.settrace(trace)
            sys._getframe(1).f_trace = trace
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            if boundary == 'native':
                patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed
        if boundary == 'native':
            assert native_hits == ['_path']
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete':
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete':
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            assert runner._prelaunch_storage == {}
            assert runner.cleanup_debts() == () and backend.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = record.debt_id if settlement == 'process' else owner.cleanup_debts()[0].debt_id
            assert debts[0].debt_id == expected
            if settlement == 'process':
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            assert runner.retry_cleanup(expected)
        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize('primary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('secondary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('boundary', ['native', 'exhaustion'])
@pytest.mark.parametrize('settlement', ['complete'])
def test_outer_reconciliation_handler_interruption(tmp_path, monkeypatch, primary_type, secondary_type, boundary, settlement):
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    source, first = inspect.getsourcelines(module.OwnedHookScriptRunner.execute_entry)
    marker = 'if (owner_state["_path"]' if boundary == 'condition' else 'custody._write_state(pending=not custody.storage_settled)'
    if boundary in {'exit', 'native'}:
        marker = 'continue'
    fallback = next(i for i, line in enumerate(source) if 'Read prebound native authority' in line)
    target = first + next(i for i in range(fallback, len(source)) if marker in source[i])
    previous = sys.gettrace()
    armed = True
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == 'line' and frame.f_code is runner.execute_entry.__func__.__code__ and frame.f_lineno == target:
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and len(native_hits) < (3 if boundary == 'exhaustion' else 1)
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                if boundary != 'exhaustion':
                    sys.settrace(trace)
                    sys._getframe(1).f_trace = trace
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        if boundary not in {'native', 'exhaustion'}:
            sys.settrace(trace)
            sys._getframe(1).f_trace = trace
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            if boundary in {'native', 'exhaustion'}:
                patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed or boundary == 'exhaustion'
        if boundary == 'exhaustion':
            assert native_hits == ['_path'] * 3
        if boundary == 'native':
            assert native_hits == ['_path']
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete':
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete':
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            assert runner._prelaunch_storage == {}
            assert runner.cleanup_debts() == () and backend.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = record.debt_id if settlement == 'process' else owner.cleanup_debts()[0].debt_id
            assert debts[0].debt_id == expected
            if settlement == 'process':
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            assert runner.retry_cleanup(expected)
        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize("missing_name", ["_path", "_uncertain_path", "_debt"])
def test_unresolved_custody_observation_is_public_and_bounded(tmp_path, missing_name):
    """Missing exact terminal facts retain bounded public recovery without cleanup."""
    import topsailai.hooks.script_runner as module
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("exact-reconciliation"))
    runner._write_prelaunch_storage(((id(owner), custody),))
    assert owner.cleanup()
    value = owner.__dict__.pop(missing_name)
    try:
        runner._reconcile_custody(custody)
        debts = runner.cleanup_debts()
        assert len(debts) == 1 and debts[0].debt_id == custody.record.debt_id
        assert not runner.retry_cleanup(custody.record.debt_id)
        assert runner._prelaunch_storage[id(owner)] is custody
        owner.__dict__[missing_name] = value
        assert runner.retry_cleanup(custody.record.debt_id)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
    finally:
        owner.__dict__[missing_name] = value
        owner.cleanup()


def test_restored_incomplete_observation_must_not_release_owner(tmp_path):
    """Restored fields are not proof that an outstanding owner settled."""
    import topsailai.hooks.script_runner as module
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    path = owner.path
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("exact-incomplete-observation"))
    runner._write_prelaunch_storage(((id(owner), custody),))
    value = owner.__dict__.pop("_uncertain_path")
    try:
        runner._reconcile_custody(custody)
        owner.__dict__["_uncertain_path"] = value
        assert runner.retry_cleanup(custody.record.debt_id)
        assert not path.exists()
        assert owner.cleanup_debts() == ()
    finally:
        owner.__dict__["_uncertain_path"] = value
        owner.cleanup()


@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["entry", "arming", "pending", "condition", "publication", "exit", "disarm", "return"])
@pytest.mark.parametrize("committed", [False, True])
def test_final_reconciliation_interruption_is_public(tmp_path, secondary_type, boundary, committed):
    """A real settled owner must not disappear behind interrupted publication."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    runner = module.OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    path = owner.path
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("exact-helper-interruption"))
    runner._write_prelaunch_storage(((id(owner), custody),))
    assert owner.cleanup()
    custody._write_state(storage_settled=committed)
    custody._write_state(pending=not committed)
    custody._write_state(reconciliation_pending=not committed)
    source, first = inspect.getsourcelines(runner._reconcile_custody)
    marker = {"entry": 'state = custody', "arming": 'custody._write_state(reconciliation_pending=True)',
              "pending": 'custody._write_state(pending=True)', "disarm": 'custody._write_state(reconciliation_pending=False)',
              "return": 'custody._write_state(reconciliation_pending=False)', "condition": "if any(owner[name]", "publication": 'custody._write_state(storage_settled=True)',
              "exit": 'custody._write_state(pending=False)'}[boundary]
    target = first + max(i for i, line in enumerate(source) if marker in line)
    previous = sys.gettrace()
    fired = []
    def trace(frame, event, arg):
        """Disarm before raising so exact recovery is not interrupted again."""
        if not fired and event == ("return" if boundary == "return" else "line") and frame.f_code is runner._reconcile_custody.__func__.__code__ and (boundary == "return" or frame.f_lineno == target):
            fired.append(target)
            raise secondary_type("helper interruption")
        return trace
    try:
        sys.settrace(trace)
        with pytest.raises(secondary_type):
            runner._reconcile_custody(custody)
        sys.settrace(previous)
        assert fired
        assert not path.exists() and owner.cleanup_debts() == ()
        debts = runner.cleanup_debts()
        if custody.pending:
            assert len(debts) == 1 and debts[0].debt_id == custody.record.debt_id
        else:
            assert debts == ()
        assert not custody.recovering
        if custody.pending:
            assert runner.retry_cleanup(custody.record.debt_id)
        else:
            # Match execute_entry final identity-checked release after completion.
            assert runner._prelaunch_storage[id(owner)] is custody
            runner._write_prelaunch_storage(retire=(id(owner),))
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert unrelated.exists()
    finally:
        sys.settrace(previous)
        owner.cleanup()


@pytest.mark.parametrize('primary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('secondary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('boundary', ['native', 'helper_entry', 'helper_pending', 'helper_disarm', 'helper_return'])
@pytest.mark.parametrize('settlement', ['complete', 'process', 'storage'])
def test_public_obligation_arming_preserves_primary(tmp_path, monkeypatch, primary_type, secondary_type, boundary, settlement):
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    source, first = inspect.getsourcelines(runner._reconcile_custody)
    marker = {"native": 'custody._write_state(reconciliation_pending=True)',
              "helper_entry": 'state = custody',
              "helper_pending": 'custody._write_state(pending=True)',
              "helper_disarm": 'custody._write_state(reconciliation_pending=False)',
              "helper_return": 'custody._write_state(reconciliation_pending=False)'}[boundary]
    matches = [i for i, line in enumerate(source) if marker in line]
    target = first + (min(matches) if settlement != "complete" and boundary == "helper_disarm" else max(matches))
    previous = sys.gettrace()
    armed = True
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == ('return' if boundary == 'helper_return' else 'line') and frame.f_code is runner._reconcile_custody.__func__.__code__ and (boundary == 'helper_return' or frame.f_lineno == target):
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and not native_hits
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                sys.settrace(trace)
                sys._getframe(1).f_trace = trace
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed
        assert native_hits == ['_path']
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete':
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete':
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            debts = runner.cleanup_debts()
            if runner._prelaunch_storage:
                assert len(debts) == 1 and debts[0].debt_id == record.debt_id
                assert runner.retry_cleanup(debts[0].debt_id)
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = debts[0].debt_id
            assert expected in {record.debt_id, *(d.debt_id for d in owner.cleanup_debts())}
            assert debts[0].debt_id == expected
            if settlement == 'process':
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            assert runner.retry_cleanup(expected)
        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize('primary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('secondary_type', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('boundary,settlement', [(b, s) for b in ['native', 'helper_entry', 'helper_pending', 'helper_disarm', 'helper_return', 'precleanup_arming', 'precleanup_try'] for s in ['complete', 'process', 'storage'] if not (s == 'process' and b.startswith('precleanup'))])
def test_precleanup_obligation_survives_exhaustion(tmp_path, monkeypatch, primary_type, secondary_type, boundary, settlement):
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    target_code = runner._reconcile_custody.__func__.__code__
    source, first = inspect.getsourcelines(runner._reconcile_custody)
    if boundary.startswith('precleanup'):
        target_code = runner._settle_storage.__func__.__code__
        source, first = inspect.getsourcelines(runner._settle_storage)
    marker = {"precleanup_arming": 'custody._write_state(reconciliation_pending=True)',
              "precleanup_try": '        try:', "native": 'custody._write_state(reconciliation_pending=True)',
              "helper_entry": 'state = custody',
              "helper_pending": 'custody._write_state(pending=True)',
              "helper_disarm": 'custody._write_state(reconciliation_pending=False)',
              "helper_return": 'custody._write_state(reconciliation_pending=False)'}[boundary]
    matches = [i for i, line in enumerate(source) if marker in line]
    target = first + (min(matches) if settlement != "complete" and boundary == "helper_disarm" else max(matches))
    previous = sys.gettrace()
    armed = True
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == ('return' if boundary == 'helper_return' else 'line') and frame.f_code is target_code and (boundary == 'helper_return' or frame.f_lineno == target):
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and len(native_hits) < 3
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                sys.settrace(trace)
                sys._getframe(1).f_trace = trace
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        if boundary.startswith('precleanup'):
            sys.settrace(trace)
            sys._getframe(1).f_trace = trace
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        custody = runner._prelaunch_storage[id(owner)]
        assert custody.reconciliation_pending
        assert custody.recovering
        assert not runner.retry_cleanup(custody.record.debt_id)
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed
        assert native_hits == ['_path'] * 3
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            debts = runner.cleanup_debts()
            if runner._prelaunch_storage:
                assert len(debts) == 1 and debts[0].debt_id == record.debt_id
                assert runner.retry_cleanup(debts[0].debt_id)
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = debts[0].debt_id
            assert expected in {record.debt_id, *(d.debt_id for d in owner.cleanup_debts())}
            assert debts[0].debt_id == expected
            if settlement == 'process' or boundary.startswith('precleanup'):
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            assert runner.retry_cleanup(expected)
        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
def test_retry_exclusion_real_interrupt_reentry(tmp_path, monkeypatch, primary_type, secondary_type):
    boundary, settlement = "helper_entry", "storage"
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    target_code = runner._reconcile_custody.__func__.__code__
    source, first = inspect.getsourcelines(runner._reconcile_custody)
    if boundary.startswith('precleanup'):
        target_code = runner._settle_storage.__func__.__code__
        source, first = inspect.getsourcelines(runner._settle_storage)
    marker = {"precleanup_arming": 'custody._write_state(reconciliation_pending=True)',
              "precleanup_try": '        try:', "native": 'custody._write_state(reconciliation_pending=True)',
              "helper_entry": 'state = custody',
              "helper_pending": 'custody._write_state(pending=True)',
              "helper_disarm": 'custody._write_state(reconciliation_pending=False)',
              "helper_return": 'custody._write_state(reconciliation_pending=False)'}[boundary]
    matches = [i for i, line in enumerate(source) if marker in line]
    target = first + (min(matches) if settlement != "complete" and boundary == "helper_disarm" else max(matches))
    previous = sys.gettrace()
    armed = True
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == ('return' if boundary == 'helper_return' else 'line') and frame.f_code is target_code and (boundary == 'helper_return' or frame.f_lineno == target):
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and len(native_hits) < 3
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                sys.settrace(trace)
                sys._getframe(1).f_trace = trace
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        if boundary.startswith('precleanup'):
            sys.settrace(trace)
            sys._getframe(1).f_trace = trace
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        custody = runner._prelaunch_storage[id(owner)]
        assert custody.reconciliation_pending
        assert custody.recovering
        assert not runner.retry_cleanup(custody.record.debt_id)
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed
        assert native_hits == ['_path'] * 3
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            debts = runner.cleanup_debts()
            if runner._prelaunch_storage:
                assert len(debts) == 1 and debts[0].debt_id == record.debt_id
                assert runner.retry_cleanup(debts[0].debt_id)
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = debts[0].debt_id
            assert expected in {record.debt_id, *(d.debt_id for d in owner.cleanup_debts())}
            assert debts[0].debt_id == expected
            if settlement == 'process' or boundary.startswith('precleanup'):
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            attempts = []
            nested = []
            active = True
            real_cleanup = TemporaryStorageOwner.cleanup
            def reenter(value):
                """Try the same public ID at the real removal boundary without races."""
                nonlocal active
                attempts.append(value)
                if active:
                    active = False
                    alias = owner.cleanup_debts()[0].debt_id
                    assert alias not in runner._storage
                    nested.append(runner.retry_cleanup(expected))
                    nested.append(runner.retry_cleanup(alias))
                    assert runner._prelaunch_storage[id(owner)].owner is owner
                return real_cleanup(value)
            with monkeypatch.context() as retry_patch:
                retry_patch.setattr(TemporaryStorageOwner, "cleanup", reenter)
                assert runner.retry_cleanup(expected)
            assert nested == [False, False]
            assert attempts == [owner]

        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("alias", ["record", "storage"])
@pytest.mark.parametrize("mode", ["nested", "concurrent", "failure"])
def test_retry_exclusion_alias_and_concurrency(tmp_path, monkeypatch, alias, mode, registered):
    """Hold one exact real owner across record/storage aliases and event handoff."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    owner.retain_cleanup_debt()
    storage_id = owner.cleanup_debts()[0].debt_id
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("exact-retry-alias"))
    custody._write_state(pending=True)
    runner._write_prelaunch_storage(((id(owner), custody),))
    if registered:
        runner._storage[storage_id] = owner
    ids = (custody.record.debt_id, storage_id)
    selected = ids[alias == "storage"]
    cleanup = TemporaryStorageOwner.cleanup
    attempts, results = [], []
    entered, finished = threading.Event(), threading.Event()

    def competitor():
        """Wait for the first cleanup callback without a sleep race."""
        assert entered.wait(5)
        results.extend(runner.retry_cleanup(value) for value in ids)
        finished.set()

    def remove(value):
        """Observe exclusion before one genuine removal or one failed attempt."""
        attempts.append(value)
        assert custody.retry_owner is not None
        assert runner._prelaunch_storage[id(owner)] is custody
        token = custody.retry_owner
        if mode == "concurrent":
            entered.set()
            assert finished.wait(5)
        else:
            results.extend(runner.retry_cleanup(value) for value in ids)
        assert runner._prelaunch_storage[id(owner)] is custody
        assert custody.retry_owner is token
        assert results == [False, False]
        return False if mode == "failure" else cleanup(value)

    thread = threading.Thread(target=competitor) if mode == "concurrent" else None
    try:
        if thread is not None:
            thread.start()
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            assert runner.retry_cleanup(selected) is (mode != "failure")
        if thread is not None:
            thread.join(5)
            assert not thread.is_alive()
        assert results == [False, False]
        assert attempts == [owner]
        assert custody.retry_owner is None
        if mode == "failure":
            assert runner.cleanup_debts()[0].debt_id == storage_id
            assert runner.retry_cleanup(storage_id)
        assert runner.cleanup_debts() == ()
        assert runner._prelaunch_storage == {}
    finally:
        entered.set()
        if thread is not None:
            thread.join(5)
        cleanup(owner)


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["acquire_before", "acquire_after", "helper", "cleanup", "release", "disarm"])
def test_retry_exclusion_interruption_handoff(tmp_path, monkeypatch, exception_type, boundary):
    """Finite retry handoff interruptions retain public debt and exact convergence."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    owner.retain_cleanup_debt()
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("exact-retry-interruption"))
    custody._write_state(pending=True)
    custody._write_state(reconciliation_pending=True)
    runner._write_prelaunch_storage(((id(owner), custody),))
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    helper, forget = runner._reconcile_custody, runner._forget_storage
    cleanup = TemporaryStorageOwner.cleanup
    interrupted = exception_type("retry handoff")
    armed = True

    def setter(value, name, item):
        """Interrupt before/after acquiring or before withdrawing the exact token."""
        nonlocal armed
        hit = name == "retry_owner" and (
            (item is not None and boundary.startswith("acquire"))
            or (item is None and boundary == "disarm"))
        if armed and hit:
            armed = False
            if boundary == "acquire_after":
                native_token_write(value, item) if name == "retry_owner" else native_set(value, name, item)
            raise interrupted
        native_token_write(value, item) if name == "retry_owner" else native_set(value, name, item)

    def reconcile(value):
        """Try both aliases while helper still owns active retry exclusion."""
        nonlocal armed
        helper(value)
        assert not runner.retry_cleanup(custody.record.debt_id)
        if armed and boundary == "helper":
            armed = False
            raise interrupted

    def remove(value):
        """Retain a real incomplete owner when removal is interrupted."""
        nonlocal armed
        if armed and boundary == "cleanup":
            armed = False
            raise interrupted
        return cleanup(value)

    def release(value):
        """Interrupt after real removal but before exact registry release."""
        nonlocal armed
        if armed and boundary == "release":
            armed = False
            raise interrupted
        return forget(value)

    try:
        with monkeypatch.context() as patch:
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module._StorageCustody, "_write_retry_owner", lambda value, item: setter(value, "retry_owner", item))
            patch.setattr(runner, "_reconcile_custody", reconcile)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            patch.setattr(runner, "_forget_storage", release)
            with pytest.raises(exception_type) as caught:
                runner.retry_cleanup(custody.record.debt_id)
        assert caught.value is interrupted
        assert not armed
        assert custody.retry_owner is None
        if runner._prelaunch_storage:
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            assert runner.retry_cleanup(debts[0].debt_id)
        assert runner._prelaunch_storage == {}
        assert runner.cleanup_debts() == ()
    finally:
        cleanup(owner)


@pytest.mark.parametrize("process_settled", [False, True])
def test_retry_exclusion_unbound_fallback_remains_incomplete(tmp_path, monkeypatch, process_settled):
    """Preserve legacy backend fallback failure and storage debt mapping."""
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = OwnedHookScriptRunner(backend)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    runner._process_storage["legacy-process"] = owner
    cleanup = TemporaryStorageOwner.cleanup
    try:
        with monkeypatch.context() as patch:
            patch.setattr(backend, "retry_cleanup", lambda debt_id: process_settled)
            patch.setattr(TemporaryStorageOwner, "cleanup", lambda value: False)
            assert not runner.retry_cleanup("legacy-process")
        assert runner._process_storage["legacy-process"] is owner
        if process_settled:
            debt = runner.cleanup_debts()[0]
            assert debt.debt_id == owner.cleanup_debts()[0].debt_id
            assert runner.retry_cleanup(debt.debt_id)
    finally:
        cleanup(owner)


@pytest.mark.parametrize("active", ["recovering", "retry", "idle"])
@pytest.mark.parametrize("debt_kind", ["exact", "other", "none"])
def test_retry_exclusion_retained_alias_authority(tmp_path, monkeypatch, active, debt_kind):
    """Only exact active owner authority blocks backend fallback without owner locks."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    if debt_kind != "none":
        owner.retain_cleanup_debt()
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("active-process"))
    custody._write_state(recovering=active == "recovering")
    token = object() if active == "retry" else None
    custody._write_retry_owner(token)
    runner._write_prelaunch_storage(((id(owner), custody),))
    debt_id = owner.cleanup_debts()[0].debt_id if debt_kind == "exact" else "other-debt"
    calls = []

    def backend_retry(value):
        """Record fallback and refuse completion for unrelated recovery authority."""
        calls.append(value)
        return False

    try:
        with monkeypatch.context() as patch:
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            with owner._lock:
                assert not runner.retry_cleanup(debt_id)
        assert calls == ([] if active != "idle" and debt_kind == "exact" else [debt_id])
        assert custody.retry_owner is token
        assert runner._prelaunch_storage[id(owner)] is custody
        assert owner.path.exists()
    finally:
        TemporaryStorageOwner.cleanup(owner)


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary_type", [KeyboardInterrupt, SystemExit])
def test_retry_exclusion_stable_alias_real_interrupt(tmp_path, monkeypatch, primary_type, secondary_type):
    boundary, settlement = "helper_entry", "storage"
    """Preserve exact settlement and primary across repeated observer failures."""
    import builtins
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    backend = IsolatedProcessBackend(temp_root=str(root))
    runner = module.OwnedHookScriptRunner(backend)
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    primary = primary_type('drain primary')
    secondary = secondary_type('repeated terminal observation')
    captured, hits, cleanups = [], [], []
    cleanup = TemporaryStorageOwner.cleanup
    target_code = runner._reconcile_custody.__func__.__code__
    source, first = inspect.getsourcelines(runner._reconcile_custody)
    if boundary.startswith('precleanup'):
        target_code = runner._settle_storage.__func__.__code__
        source, first = inspect.getsourcelines(runner._settle_storage)
    marker = {"precleanup_arming": 'custody._write_state(reconciliation_pending=True)',
              "precleanup_try": '        try:', "native": 'custody._write_state(reconciliation_pending=True)',
              "helper_entry": 'state = custody',
              "helper_pending": 'custody._write_state(pending=True)',
              "helper_disarm": 'custody._write_state(reconciliation_pending=False)',
              "helper_return": 'custody._write_state(reconciliation_pending=False)'}[boundary]
    matches = [i for i, line in enumerate(source) if marker in line]
    target = first + (min(matches) if settlement != "complete" and boundary == "helper_disarm" else max(matches))
    previous = sys.gettrace()
    armed = True
    native_hits = []
    def trace(frame, event, arg):
        """Interrupt the new native fallback once after real cleanup."""
        nonlocal armed
        if armed and event == ('return' if boundary == 'helper_return' else 'line') and frame.f_code is target_code and (boundary == 'helper_return' or frame.f_lineno == target):
            armed = False
            raise secondary_type('outer fallback boundary')
        return trace
    class AuthorityView:
        """Forward exact live owner fields with one controlled read failure."""
        def __init__(self, state):
            """Retain the real owner's dictionary rather than a snapshot."""
            self.state = state
        def __getitem__(self, name):
            """Interrupt only the direct outer read, then permit convergence."""
            if (name == '_path' and len(native_hits) < 3
                    and sys._getframe(1).f_code is runner.execute_entry.__func__.__code__):
                native_hits.append(name)
                sys.settrace(trace)
                sys._getframe(1).f_trace = trace
                raise secondary_type('native authority read')
            return self.state[name]
    class ObjectView:
        """Inject only this consumer's already-held exact owner observation."""
        @staticmethod
        def __getattribute__(value, name):
            """Leave custody and all other native attribute access unchanged."""
            state = builtins.object.__getattribute__(value, name)
            if isinstance(value, TemporaryStorageOwner) and name == '__dict__':
                return AuthorityView(state)
            return state
    recover = runner._preserve_interrupted
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    def drain(*args, **kwargs):
        """Raise the original interrupt after a real process launch."""
        if boundary.startswith('precleanup'):
            sys.settrace(trace)
            sys._getframe(1).f_trace = trace
        raise primary
    def recovery(initial, record, owner, started):
        """Hold the exact production resources for assertions and cleanup."""
        captured.append((record, owner, owner.path))
        if settlement == 'process':
            runner._remember_storage(owner)
            raise secondary_type('process recovery interrupted')
        return recover(initial, record, owner, started)
    def remove(owner):
        """Retain incomplete storage or genuinely remove the exact owner once."""
        custody = runner._prelaunch_storage[id(owner)]
        assert custody.reconciliation_pending
        assert custody.recovering
        assert not runner.retry_cleanup(custody.record.debt_id)
        cleanups.append(owner)
        if settlement == 'storage':
            raise secondary_type('storage cleanup interrupted')
        return cleanup(owner)
    def setter(custody, name, value):
        """Prevent initial journal publication after genuine cleanup."""
        if name == 'storage_settled' and value is True and sys._getframe(2).f_code is OwnedHookScriptRunner._settle_storage.__code__:
            raise secondary_type('journal interrupted')
        native_set(custody, name, value)
    def observe(values):
        """Repeatedly interrupt the existing terminal predicate at each level."""
        caller = sys._getframe(1).f_code
        if caller in (runner.execute_entry.__func__.__code__, runner._settle_storage.__func__.__code__):
            hits.append(caller.co_name)
            raise secondary
        return builtins.all(values)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, 'object', ObjectView, raising=False)
            patch.setattr(module, 'drain_script_process', drain)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            patch.setattr(runner, '_preserve_interrupted', recovery)
            _install_custody_assignment_fault(patch, setter)
            patch.setattr(module, 'all', observe, raising=False)
            now = time.monotonic()
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script.resolve(), script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=now + 5, cleanup_deadline=now + 6,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.settrace(previous)
        assert not armed
        assert native_hits == ['_path'] * 3
        record, owner, path = captured[0]
        assert hits
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert hits[0] == '_settle_storage'
        assert caught.value is primary
        tb = primary.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        assert tb.tb_frame.f_code is drain.__code__
        assert all(not c.recovering for c in runner._prelaunch_storage.values())
        if settlement == 'complete' and not boundary.startswith('precleanup'):
            assert record.process.poll() is not None
            assert record.cleanup.debt_state == 'settled'
            assert not path.exists() and owner.cleanup_debts() == ()
            debts = runner.cleanup_debts()
            if runner._prelaunch_storage:
                assert len(debts) == 1 and debts[0].debt_id == record.debt_id
                assert runner.retry_cleanup(debts[0].debt_id)
            assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
            assert cleanups == [owner]
        else:
            assert path.exists()
            debts = runner.cleanup_debts()
            assert len(debts) == 1
            expected = debts[0].debt_id
            assert expected in {record.debt_id, *(d.debt_id for d in owner.cleanup_debts())}
            assert debts[0].debt_id == expected
            if settlement == 'process' or boundary.startswith('precleanup'):
                assert cleanups == []
            else:
                assert cleanups == [owner]
            assert not runner.retry_cleanup('unrelated-debt') or path.exists()
            assert path.exists()
            attempts = []
            nested = []
            active = True
            real_cleanup = TemporaryStorageOwner.cleanup
            def reenter(value):
                """Probe exact aliases after real removal before registry release."""
                nonlocal active
                attempts.append(value)
                alias = owner.cleanup_debts()[0].debt_id
                assert alias not in runner._storage
                result = real_cleanup(value)
                assert result and not path.exists()
                assert owner.cleanup_debts() == ()
                custody = runner._prelaunch_storage[id(owner)]
                token = custody.retry_owner
                assert token is not None
                backend_calls = []
                backend_retry = backend.retry_cleanup
                def observe_backend(debt_id):
                    """Observe forbidden fallback without changing backend behavior."""
                    backend_calls.append(debt_id)
                    return backend_retry(debt_id)
                with monkeypatch.context() as observe_patch:
                    observe_patch.setattr(backend, "retry_cleanup", observe_backend)
                    nested.append(runner.retry_cleanup(expected))
                    nested.append(runner.retry_cleanup(alias))
                assert backend_calls == []
                assert custody.retry_owner is token
                assert runner._prelaunch_storage[id(owner)] is custody
                return result
            with monkeypatch.context() as retry_patch:
                retry_patch.setattr(TemporaryStorageOwner, "cleanup", reenter)
                assert runner.retry_cleanup(expected)
            assert nested == [False, False]
            assert attempts == [owner]

        assert unrelated.exists()
        assert not path.exists()
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(record.debt_id)
        assert runner._prelaunch_storage == {}
        seen, error = set(), primary
        while error is not None:
            assert id(error) not in seen
            seen.add(id(error))
            error = error.__context__
    finally:
        sys.settrace(previous)
        for record, owner, path in captured:
            backend._finish_record(record, 'worker_lost', {'stdout': bytearray(), 'stderr': bytearray()},
                {'stdout': 0, 'stderr': 0}, 'review_cleanup')
            TemporaryStorageOwner.cleanup(owner)




@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("mode", ["nested", "concurrent", "interrupt", "partial_release", "released", "disarm"])
def test_retry_exclusion_stable_alias_after_cleanup(tmp_path, monkeypatch, registered, mode):
    """Retain exact alias through real debt clearing and incomplete publication."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    owner = TemporaryStorageOwner(root)
    assert owner.allocate()
    path = owner.path
    storage_id = owner.cleanup_debts()[0].debt_id
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    custody = module._StorageCustody(owner)
    custody._write_state(record=LaunchRecord("stable-alias-record"))
    custody._write_state(pending=True)
    runner._write_prelaunch_storage(((id(owner), custody),))
    if registered:
        runner._storage[storage_id] = owner
    cleanup = TemporaryStorageOwner.cleanup
    forget = runner._forget_storage
    native_set = _custody_field_write
    native_token_write = module._StorageCustody._write_retry_owner
    entered, finished = threading.Event(), threading.Event()
    results, backend_calls, attempts, errors = [], [], [], []
    interruption = KeyboardInterrupt("after genuine cleanup")

    def backend_retry(value):
        """Record unrelated fallback without allowing exact alias fallback."""
        backend_calls.append(value)
        return True

    def observe():
        """Verify alias exclusion while preserving invocation identity."""
        token = custody.retry_owner
        assert token is not None
        results.extend(runner.retry_cleanup(value) for value in (custody.record.debt_id, storage_id))
        assert runner.retry_cleanup("unrelated-alias")
        assert custody.retry_owner is token
        assert runner._prelaunch_storage[id(owner)] is custody

    def competitor():
        """Coordinate actual concurrency by events rather than sleeping."""
        try:
            assert entered.wait(5)
            observe()
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    def remove(value):
        """Clear genuine owner debt before probing the active recovery window."""
        attempts.append(value)
        assert cleanup(value)
        assert not path.exists() and owner.cleanup_debts() == ()
        if mode in {"partial_release", "released"}:
            return True
        if mode == "concurrent":
            entered.set()
            assert finished.wait(5)
            assert not errors
        else:
            observe()
        if mode == "interrupt":
            raise interruption
        return True

    def partial_release(value):
        """Interrupt after exact storage registration removal, before custody release."""
        if mode == "partial_release":
            runner._storage.pop(storage_id, None)
        else:
            forget(value)
            assert custody.release_complete
        observe()
        if mode != "released":
            raise interruption

    def setter(value, name, item):
        """Interrupt token withdrawal once after checking both active aliases."""
        if value is custody and name == "retry_owner" and item is None:
            assert custody.storage_alias.debt_id == storage_id
            assert custody.retry_owner is not None
            raise interruption
        native_token_write(value, item) if name == "retry_owner" else native_set(value, name, item)

    thread = threading.Thread(target=competitor) if mode == "concurrent" else None
    try:
        if thread:
            thread.start()
        with monkeypatch.context() as patch:
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            if mode in {"partial_release", "released"}:
                patch.setattr(runner, "_forget_storage", partial_release)
            if mode == "disarm":
                _install_custody_assignment_fault(patch, setter)
                patch.setattr(module._StorageCustody, "_write_retry_owner", lambda value, item: setter(value, "retry_owner", item))
            if mode in {"interrupt", "partial_release", "disarm"}:
                with pytest.raises(KeyboardInterrupt) as caught:
                    runner.retry_cleanup(custody.record.debt_id)
                assert caught.value is interruption
            else:
                assert runner.retry_cleanup(custody.record.debt_id)
        assert results == [False, False]
        assert backend_calls == ["unrelated-alias"]
        assert attempts == [owner] and custody.retry_owner is None
        if mode in {"interrupt", "partial_release", "disarm"}:
            assert runner.cleanup_debts()[0].debt_id == custody.record.debt_id
            assert runner.retry_cleanup(storage_id)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
    finally:
        entered.set()
        if thread:
            thread.join(5)
            assert not thread.is_alive()
        cleanup(owner)


@pytest.mark.parametrize('kind', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('after', [False, True])
def test_prelaunch_recovery_alias_assignment_exclusion(tmp_path, monkeypatch, kind, after):
    """Exclude nested exact cleanup during interrupted prelaunch recovery."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    unrelated = root / 'unrelated'
    unrelated.mkdir()
    script = tmp_path / 'script'
    script.write_text('#!/bin/false\n')
    script.chmod(0o700)
    runner = module.OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    event = HookEvent('review', 'u06.arbitration', 1, 'owner', 'scope', 'op', None, 1,
                      '2026-10-10T00:00:00Z', 'test', 'review', {})
    context = HookContext(event, 'review-delivery', 'hook_script', 1, 5000)
    original = kind('stable alias write')
    setter = _custody_field_write
    cleanup = TemporaryStorageOwner.cleanup
    armed = True
    attempts, nested, observation = [], [], []
    def assign(value, name, item):
        """Interrupt exactly once around the new authority assignment."""
        nonlocal armed
        if armed and name == 'storage_alias' and item is not None:
            armed = False
            if after:
                setter(value, name, item)
            raise original
        setter(value, name, item)
    def remove(owner):
        """Reenter only before the first real cleanup removes its directory."""
        attempts.append(owner)
        if len(attempts) == 1:
            custody = runner._prelaunch_storage[id(owner)]
            path = owner.path
            alias = owner.cleanup_debts()[0].debt_id
            assert path.exists() and custody.pending
            nested.append(runner.retry_cleanup(alias))
            observation.append(id(owner) not in runner._prelaunch_storage)
            assert path.exists()
        return cleanup(owner)
    try:
        with monkeypatch.context() as patch:
            _install_custody_assignment_fault(patch, assign)
            patch.setattr(TemporaryStorageOwner, 'cleanup', remove)
            with pytest.raises(kind) as caught:
                runner.execute_entry(entry_index=0,
                    entry=HookScriptEntry(script, script.name), context=context,
                    options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
            assert caught.value is original
        assert nested == [False] and observation == [False]
        assert len(attempts) == 1
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert unrelated.exists()
        frames=[]
        tb=original.__traceback__
        while tb:
            frames.append(tb.tb_frame.f_code.co_name)
            tb=tb.tb_next
        assert 'assign' in frames
    finally:
        for owner in attempts:
            cleanup(owner)


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("boundary", ["admission", "cleared", "failure", "partial", "release", "teardown", "teardown_after", "failure_teardown"])
def test_prelaunch_recovery_event_windows(tmp_path, monkeypatch, after, boundary):
    """Keep exact exclusion through real removal, publication and interrupted release."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    event = HookEvent("review", "u06.arbitration", 1, "owner", "scope", "op", None, 1,
                      "2026-10-10T00:00:00Z", "test", "review", {})
    context = HookContext(event, "review-delivery", "hook_script", 1, 5000)
    original = KeyboardInterrupt("alias assignment")
    secondary = SystemExit("recovery boundary")
    setter = _custody_field_write
    cleanup = TemporaryStorageOwner.cleanup
    forget = runner._forget_storage
    entered, completed = threading.Event(), threading.Event()
    armed = True
    captured, results, errors, backend_calls, attempts = [], [], [], [], []

    def assign(value, name, item):
        """Interrupt one alias write without interrupting later reconciliation."""
        nonlocal armed
        if armed and name == "storage_alias" and item is not None:
            armed = False
            if after:
                setter(value, name, item)
            raise original
        setter(value, name, item)

    def observe():
        """Exercise accurate and unrelated aliases in a distinct thread."""
        try:
            assert entered.wait(5)
            owner, custody, alias = captured[0]
            token = custody.execution_owner
            assert token is not None and custody.retry_owner is None
            results.append(runner.retry_cleanup(alias))
            assert runner.retry_cleanup("unrelated-prelaunch")
            assert custody.execution_owner is token and custody.retry_owner is None
            assert runner._prelaunch_storage[id(owner)] is custody
            assert runner.cleanup_debts() == ()
        except BaseException as error:
            errors.append(error)
        finally:
            completed.set()

    def probe():
        """Synchronize the observation while no runner or owner lock is held."""
        entered.set()
        assert completed.wait(5)
        assert not errors

    def remove(owner):
        """Use real owner deletion and interrupt at one selected boundary."""
        attempts.append(owner)
        custody = runner._prelaunch_storage[id(owner)]
        captured.append((owner, custody, custody.storage_alias.debt_id))
        if boundary in {"admission", "failure", "failure_teardown"}:
            probe()
        if boundary in {"failure", "failure_teardown"}:
            raise secondary
        assert cleanup(owner)
        if boundary == "cleared":
            probe()
            raise secondary
        return True

    def release(owner):
        """Observe before and after identity registry release without synthetic cleanup."""
        if boundary == "partial":
            runner._storage.pop(captured[0][2], None)
            probe()
            raise secondary
        forget(owner)
        if boundary in {"release", "teardown", "teardown_after"}:
            probe()
        if boundary == "release":
            raise secondary

    class State(dict):
        """Inject one native execution-token withdrawal interruption."""
        def __setitem__(self, name, value):
            """Raise once before withdrawal, allowing the native fallback to finish."""
            if name == "execution_owner" and value is None and self.get(name) is not None:
                dict.__setitem__(self, "teardown_hit", True)
                if not self.get("teardown_raised"):
                    dict.__setitem__(self, "teardown_raised", True)
                    if boundary == "teardown_after":
                        dict.__setitem__(self, name, value)
                    raise secondary
            dict.__setitem__(self, name, value)

    native_init = module._StorageCustody.__init__
    def initialize(value, owner):
        """Install a one-shot native state seam only for teardown testing."""
        native_init(value, owner)
        if boundary in {"teardown", "teardown_after", "failure_teardown"}:
            _install_custody_state_fault(value, State(value.__dict__))

    thread = threading.Thread(target=observe)
    thread.start()
    try:
        with monkeypatch.context() as patch:
            _install_custody_assignment_fault(patch, assign)
            patch.setattr(module._StorageCustody, "__init__", initialize)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            patch.setattr(runner, "_forget_storage", release)
            def backend_retry(alias):
                """Record only unrelated backend completion requests."""
                backend_calls.append(alias)
                return True
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        assert caught.value is original
        assert results == [False] and backend_calls == ["unrelated-prelaunch"]
        assert len(attempts) == 1
        owner, custody, alias = captured[0]
        assert custody.execution_owner is None and custody.retry_owner is None
        if boundary in {"failure", "cleared", "partial", "failure_teardown"}:
            assert [d.debt_id for d in runner.cleanup_debts()] == [alias]
            assert runner.retry_cleanup(alias)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert unrelated.exists()
    finally:
        entered.set()
        thread.join(5)
        assert not thread.is_alive()
        for owner in attempts:
            cleanup(owner)



def test_prelaunch_recovery_unowned_finalizer_interruption(tmp_path, monkeypatch):
    """Propagate an unowned finalizer interruption without withdrawing foreign tokens."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    native_init = module._StorageCustody.__init__
    interruption = SystemExit("unowned finalizer")
    states = []
    class State(dict):
        """Fail one native authority observation before any recovery is owned."""
        def __getitem__(self, name):
            """Disarm the observation interruption before raising."""
            if name == "execution_owner" and not self.get("hit"):
                dict.__setitem__(self, "hit", True)
                raise interruption
            return dict.__getitem__(self, name)
    def initialize(value, owner):
        """Retain the real custody with an isolated state observation seam."""
        native_init(value, owner)
        _install_custody_state_fault(value, State(value.__dict__))
        states.append(value)
    event = HookEvent("review", "u06.arbitration", 1, "owner", "scope", "op", None, 1,
                      "2026-10-10T00:00:00Z", "test", "review", {})
    script = tmp_path / "script"
    script.write_text("unused")
    script.chmod(0o700)
    with monkeypatch.context() as patch:
        patch.setattr(module._StorageCustody, "__init__", initialize)
        patch.setattr(TemporaryStorageOwner, "allocate", lambda owner: False)
        with pytest.raises(SystemExit) as caught:
            runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                context=HookContext(event, "delivery", "hook_script", 1, 5000),
                options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                output_remaining_bytes=65536, cancellation=threading.Event())
    assert caught.value is interruption
    assert states[0].execution_owner is None and states[0].retry_owner is None
    assert runner._prelaunch_storage == {}


def test_prelaunch_recovery_unrelated_reconciliation_alias(tmp_path):
    """Do not select an unrelated alias from an exact process reconciliation obligation."""
    import topsailai.hooks.script_runner as module

    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    custody = module._StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(reconciliation_pending=True)
    custody._write_state(record=LaunchRecord("reconciliation-record"))
    custody._write_state(storage_alias=owner.cleanup_debts()[0])
    runner._write_prelaunch_storage(((id(owner), custody),))
    try:
        assert runner.retry_cleanup("unrelated-reconciliation")
        assert owner.path.exists() and custody.pending
        assert runner.retry_cleanup(custody.record.debt_id)
        assert runner._prelaunch_storage == {}
    finally:
        owner.cleanup()



def test_prelaunch_recovery_registered_owner_exclusion(tmp_path):
    """Reject an exact registered active owner even when its alias journal differs."""
    import topsailai.hooks.script_runner as module

    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    custody = module._StorageCustody(owner)
    token = object()
    custody._write_state(execution_owner=token)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=owner.cleanup_debts()[0])
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage["retained-registration"] = owner
    try:
        assert not runner.retry_cleanup("retained-registration")
        assert custody.execution_owner is token and custody.retry_owner is None
        assert runner._prelaunch_storage[id(owner)] is custody
        assert owner.path.exists()
    finally:
        custody._write_state(execution_owner=None)
        owner.cleanup()
        runner._forget_storage(owner)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("write", ["execution_owner", "pending", "storage_alias"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("failed_cleanup", [False, True])
def test_prelaunch_recovery_protected_arming(
    tmp_path, monkeypatch, context, kind, write, after, failed_cleanup
):
    """Keep real custody and exact exclusion across each interrupted arming write."""
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    primary = kind("original alias interruption")
    secondary = SystemExit("arming") if kind is KeyboardInterrupt else KeyboardInterrupt("arming")
    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    cleanup = TemporaryStorageOwner.cleanup
    entered, attempted, completed = threading.Event(), threading.Event(), threading.Event()
    captured, concurrent, nested, errors, backend_calls, removals = [], [], [], [], [], []
    alias_armed = True

    class State(dict):
        """Interrupt exactly one ordinary native-state arming assignment."""
        def __setitem__(self, name, value):
            """Coordinate a retry attempt while the runner lock still owns arming."""
            if name == write and value is not None and not self.get("hit"):
                dict.__setitem__(self, "hit", True)
                if after:
                    dict.__setitem__(self, name, value)
                entered.set()
                assert attempted.wait(5)
                raise secondary
            dict.__setitem__(self, name, value)

    def init(custody, owner):
        """Capture the real owner without synthesizing or deleting registry entries."""
        initialize(custody, owner)
        _install_custody_state_fault(custody, State(custody.__dict__))
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Interrupt the initial alias assignment once after real allocation."""
        nonlocal alias_armed
        if alias_armed and name == "storage_alias" and value is not None:
            alias_armed = False
            raise primary
        setter(custody, name, value)

    def observe():
        """Attempt exact retry concurrently and preserve unrelated backend behavior."""
        try:
            assert entered.wait(5)
            custody, owner = captured[0]
            alias = owner.cleanup_debts()[0].debt_id
            attempted.set()
            concurrent.append(runner.retry_cleanup(alias))
            assert runner.retry_cleanup("unrelated-protected-arming")
        except BaseException as error:
            errors.append(error)
        finally:
            completed.set()

    def remove(owner):
        """Probe nested admission and either remove real storage or leave exact debt."""
        removals.append(owner)
        custody = runner._prelaunch_storage[id(owner)]
        token = custody.execution_owner
        assert token is not None and custody.pending and custody.retry_owner is None
        alias = owner.cleanup_debts()[0].debt_id
        nested.append(runner.retry_cleanup(alias))
        assert completed.wait(5) and not errors
        assert custody.execution_owner is token and custody.retry_owner is None
        assert runner.cleanup_debts() == () and owner.path.exists()
        if failed_cleanup:
            raise secondary
        return cleanup(owner)

    def backend_retry(alias):
        """Record unrelated completion without accepting the exact storage alias."""
        backend_calls.append(alias)
        return True

    thread = threading.Thread(target=observe)
    thread.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module._StorageCustody, "__init__", init)
            _install_custody_assignment_fault(patch, assign)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        assert caught.value is primary
        frames = []
        tb = primary.__traceback__
        while tb:
            frames.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert "assign" in frames and primary.__cause__ is None
        assert concurrent == [False] and nested == [False] and not errors
        assert backend_calls == ["unrelated-protected-arming"]
        custody, owner = captured[0]
        assert _CUSTODY_FAULT_STATES[id(custody)][1]["hit"] and custody.execution_owner is None
        assert custody.retry_owner is None and removals == [owner]
        if failed_cleanup:
            alias = custody.storage_alias.debt_id
            assert owner.path.exists() and custody.pending
            assert runner._prelaunch_storage[id(owner)] is custody
            assert [debt.debt_id for debt in runner.cleanup_debts()] == [alias]
            assert runner.retry_cleanup(alias)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert unrelated.exists()
    finally:
        entered.set()
        attempted.set()
        thread.join(5)
        assert not thread.is_alive()
        for custody, owner in captured:
            print("exact test cleanup", owner.__dict__.get("_path"))
            cleanup(owner)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("failed_cleanup", [False, True])
def test_prelaunch_first_publication_boundary(
    tmp_path, monkeypatch, context, kind, after, fallback, failed_cleanup
):
    """Protect first native publication and a second fallback interruption."""
    import dis
    import sys
    import topsailai.hooks.script_runner as module

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(root)))
    primary = kind("original alias assignment")
    secondary = SystemExit("publication") if kind is KeyboardInterrupt else KeyboardInterrupt("publication")
    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    cleanup = TemporaryStorageOwner.cleanup
    captured, hits, removals = [], [], []
    alias_armed = True
    source = Path(module.__file__).read_text().splitlines()
    publication_start = next(number for number, line in enumerate(source, 1)
                             if "Publish responsibility before interruptible recovery authority writes" in line)
    lines = {number for number, line in enumerate(source, 1)
             if 'custody._write_state(pending=True)' in line
             and publication_start <= number
             < OwnedHookScriptRunner._reconcile_custody.__code__.co_firstlineno}
    instructions = list(dis.get_instructions(OwnedHookScriptRunner.execute_entry))
    targets = set()
    for index, instruction in enumerate(instructions):
        if instruction.opname in ("CALL", "CALL_KW") and instruction.positions.lineno in lines:
            targets.add(instructions[index + 1].offset if after else instruction.offset)
    fallback_lines = {number for number, line in enumerate(source, 1)
                      if 'custody._write_state(pending=True, execution_owner=' in line}
    fallback_targets = set()
    for index, instruction in enumerate(instructions):
        if instruction.opname in ("CALL", "CALL_KW") and instruction.positions.lineno in fallback_lines:
            fallback_targets.add(instructions[index + 1].offset if after else instruction.offset)
    previous = sys.gettrace()
    previous_profile = sys.getprofile()
    budget = 2 if fallback else 1

    def trace(frame, event, arg):
        """Rearm once inside fallback, disarming before each raised interruption."""
        if frame.f_code is OwnedHookScriptRunner.execute_entry.__code__:
            frame.f_trace_opcodes = True
            selected = targets if not hits else fallback_targets
            if event == "opcode" and frame.f_lasti in selected and len(hits) < budget:
                hits.append(frame.f_lasti)
                sys.settrace(None)
                frame.f_trace = None
                raise secondary
            return trace
        return None

    def profile(frame, event, arg):
        """Rearm a second one-shot opcode probe only inside the fallback."""
        if (fallback and len(hits) == 1 and event == "call"
                and frame.f_back is not None
                and frame.f_back.f_code is OwnedHookScriptRunner.execute_entry.__code__
                and frame.f_back.f_lineno in fallback_lines):
            sys.settrace(trace)
            frame.f_back.f_trace = trace
            frame.f_back.f_trace_opcodes = True

    def init(custody, owner):
        """Capture actual custody and preserve exact native state."""
        initialize(custody, owner)
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Trigger recovery only after genuine allocation."""
        nonlocal alias_armed
        if alias_armed and name == "storage_alias" and value is not None:
            alias_armed = False
            raise primary
        setter(custody, name, value)

    def remove(owner):
        """Check active exact exclusion before genuine cleanup or retained failure."""
        removals.append(owner)
        alias = owner.cleanup_debts()[0].debt_id
        assert not runner.retry_cleanup(alias)
        if failed_cleanup:
            raise secondary
        return cleanup(owner)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module._StorageCustody, "__init__", init)
            _install_custody_assignment_fault(patch, assign)
            patch.setattr(TemporaryStorageOwner, "cleanup", remove)
            sys.settrace(trace)
            controlled = module._StorageCustody._write_state
            def fallback_write(custody, _retire=(), **changes):
                """Inject the second interruption at the exact controlled fallback commit."""
                if fallback and len(hits) == 1 and "execution_owner" in changes:
                    hits.append("controlled-fallback")
                    if after:
                        controlled(custody, _retire=_retire, **changes)
                    raise secondary
                return controlled(custody, _retire=_retire, **changes)
            patch.setattr(module._StorageCustody, "_write_state", fallback_write)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        sys.setprofile(previous_profile)
        sys.settrace(previous)
        assert runner._lock.acquire(blocking=False), "publication leaked runner lock"
        runner._lock.release()
        assert caught.value is primary
        assert len(hits) == budget
        tb = primary.__traceback__
        frames = []
        while tb:
            frames.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert "assign" in frames and primary.__cause__ is None
        custody, owner = captured[0]
        assert custody.execution_owner is None and custody.retry_owner is None
        if owner.__dict__["_path"] is not None:
            alias = owner.cleanup_debts()[0].debt_id
            assert custody.pending and runner._prelaunch_storage[id(owner)] is custody
            assert [debt.debt_id for debt in runner.cleanup_debts()] == [alias]
            assert runner.retry_cleanup("unrelated-first-publication")
            assert runner.retry_cleanup(alias)
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        assert unrelated.exists()
    finally:
        sys.setprofile(previous_profile)
        sys.settrace(previous)
        for custody, owner in captured:
            print("exact boundary cleanup", owner.__dict__.get("_path"))
            cleanup(owner)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_prelaunch_first_publication_native_fallback_failure(tmp_path, monkeypatch, context, kind):
    """Cover bounded fallback handler without replacing the coverage tracer."""
    import topsailai.hooks.script_runner as module

    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    primary = kind("original allocation handoff")
    captured = []
    native = dict
    armed = True

    class NativeDict(dict):
        """Reject one fallback update while preserving real native ownership writes."""
        @staticmethod
        def update(state, **values):
            """Inject fallback failure only during execution authority publication."""
            if "execution_owner" in values:
                raise SystemExit("native fallback")
            native.update(state, **values)

    class State(dict):
        """Reject the ordinary arming write before native fallback."""
        def __setitem__(self, name, value):
            """Keep all writes except one execution arming assignment unchanged."""
            if name == "execution_owner" and value is not None:
                raise KeyboardInterrupt("ordinary arming")
            native.__setitem__(self, name, value)

    def init(custody, owner):
        """Capture the actual owner and isolate state injection to this custody."""
        initialize(custody, owner)
        _install_custody_state_fault(custody, State(custody.__dict__))
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Start recovery after genuine allocation with the original exception."""
        nonlocal armed
        if armed and name == "storage_alias" and value is not None:
            armed = False
            raise primary
        setter(custody, name, value)

    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "dict", NativeDict, raising=False)
            patch.setattr(module._StorageCustody, "__init__", init)
            _install_custody_assignment_fault(patch, assign)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        assert caught.value is primary and primary.__cause__ is None
        custody, owner = captured[0]
        assert owner.path.exists() and custody.pending and custody.execution_owner is None
        alias = owner.cleanup_debts()[0].debt_id
        assert [debt.debt_id for debt in runner.cleanup_debts()] == [alias]
        assert runner.retry_cleanup(alias)
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
    finally:
        for custody, owner in captured:
            print("exact fallback cleanup", owner.__dict__.get("_path"))
            owner.cleanup()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("fallback_after", [False, True])
@pytest.mark.parametrize("teardown", ["none", "before", "after"])
def test_incomplete_arming_invocation_exclusion(tmp_path, monkeypatch, context, kind, fallback_after, teardown):
    """Cover bounded fallback handler without replacing the coverage tracer."""
    import topsailai.hooks.script_runner as module

    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    primary = kind("original allocation handoff")
    captured = []
    observed = []
    fallback_failed = False
    native = dict
    armed = True
    backend_calls = []
    native_list = list
    teardown_hit = False

    def write(custody, _retire=(), **changes):
        """Interrupt exact normal, fallback and lease commits at reachable boundaries."""
        nonlocal fallback_failed, teardown_hit
        if "execution_owner" in changes and changes["execution_owner"] is not None:
            if len(changes) == 1:
                raise KeyboardInterrupt("ordinary arming")
            fallback_failed = True
            if fallback_after:
                _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changes)
            raise SystemExit("native fallback")
        if captured and custody is captured[0][0] and changes.get("execution_lease") == (None,) and teardown != "none" and not teardown_hit:
            teardown_hit = True
            if teardown == "after":
                _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changes)
            raise SystemExit("lease teardown")
        if _retire:
            _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire)
        for name, value in changes.items():
            assign(custody, name, value)

    def init(custody, owner):
        """Capture the actual owner and isolate state injection to this custody."""
        initialize(custody, owner)
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Start recovery after genuine allocation with the original exception."""
        nonlocal armed
        if armed and name == "storage_alias" and value is not None:
            armed = False
            raise primary
        setter(custody, name, value)

    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    original_lock = runner._lock
    class ReleaseSeam:
        """Observe exact retry only after recovery lock release before finalizer."""
        def __enter__(self):
            original_lock.acquire()
            return self
        def __exit__(self, *args):
            nonlocal fallback_failed
            original_lock.release()
            if fallback_failed:
                fallback_failed = False
                custody, owner = captured[0]
                alias = owner.cleanup_debts()[0].debt_id
                path = owner.path
                assert custody.pending
                result = runner.retry_cleanup(alias)
                concurrent = []
                started = threading.Event()
                def retry():
                    """Run exact and unrelated retries after the real lock is released."""
                    started.set()
                    concurrent.append(runner.retry_cleanup(alias))
                    concurrent.append(runner.retry_cleanup("unrelated-incomplete-arming"))
                thread = threading.Thread(target=retry)
                thread.start()
                assert started.wait(5)
                thread.join(5)
                assert not thread.is_alive() and concurrent == [False, True]
                observed.append((result, path.exists(), id(owner) in runner._prelaunch_storage))
    runner._lock = ReleaseSeam()

    def backend_retry(alias):
        """Accept only the unrelated alias at the observed handoff."""
        backend_calls.append(alias)
        return True

    try:
        with monkeypatch.context() as patch:
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            patch.setattr(module._StorageCustody, "__init__", init)
            patch.setattr(module._StorageCustody, "_write_state", write)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        assert caught.value is primary and primary.__cause__ is None
        custody, owner = captured[0]
        assert observed == [(False, True, True)]
        assert backend_calls == ["unrelated-incomplete-arming"]
        assert custody.execution_lease == (None,)
        assert teardown_hit == (teardown != "none")
        frames = []
        tb = caught.value.__traceback__
        while tb is not None:
            frames.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert "assign" in frames
        alias = owner.cleanup_debts()[0].debt_id
        assert [debt.debt_id for debt in runner.cleanup_debts()] == [alias]
        assert runner.retry_cleanup(alias)
        assert custody.retry_owner is None and custody.execution_owner is None
        assert runner.cleanup_debts() == () and runner._prelaunch_storage == {}
        print("exact retry excluded until invocation handback", observed)

    finally:
        for custody, owner in captured:
            print("exact fallback cleanup", owner.__dict__.get("_path"))
            owner.cleanup()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_terminal_invocation_lease_handoff(tmp_path, monkeypatch, context, kind):
    """Keep exact aliases excluded until terminal lease and custody hand off together."""
    import topsailai.hooks.script_runner as module

    captured = []
    observations = []
    backend_calls = []
    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    primary = kind("terminal original interruption")
    armed = True

    def init(custody, owner):
        """Capture the exact real owner without changing its state."""
        initialize(custody, owner)
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Interrupt the first stable alias publication after genuine allocation."""
        nonlocal armed
        if armed and name == "storage_alias" and value is not None:
            armed = False
            captured.append((value.debt_id, custody.owner.path))
            raise primary
        setter(custody, name, value)

    script = tmp_path / "terminal-script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    lock = runner._lock
    observing = False

    class ReleaseSeam:
        """Observe only after actual unlock and never recursively intercept retry."""
        def __enter__(self):
            """Acquire the actual runner lock."""
            lock.acquire()
            return self

        def __exit__(self, *args):
            """Inspect active terminal authority outside the critical section."""
            nonlocal observing
            lock.release()
            if observing or len(captured) != 2:
                return
            custody, owner = captured[0]
            if custody.execution_lease[0] is None:
                return
            observing = True
            try:
                alias, path = captured[1]
                reachable = runner._prelaunch_storage.get(id(owner)) is custody
                result = runner.retry_cleanup(alias)
                other = runner.retry_cleanup("unrelated-terminal")
                observations.append((reachable, result, other, path.exists()))
            finally:
                observing = False

    def backend_retry(alias):
        """Record whether an exact alias incorrectly falls through to backend."""
        backend_calls.append(alias)
        return True

    runner._lock = ReleaseSeam()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module._StorageCustody, "__init__", init)
            _install_custody_assignment_fault(patch, assign)
            patch.setattr(runner._backend, "retry_cleanup", backend_retry)
            with pytest.raises(BaseException) as caught:
                runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                    context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                    execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                    output_remaining_bytes=65536, cancellation=threading.Event())
        custody, owner = captured[0]
        alias, path = captured[1]
        assert caught.value is primary
        frames = []
        tb = primary.__traceback__
        while tb is not None:
            frames.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert "assign" in frames and primary.__cause__ is None
        assert observations and all(row[:3] == (True, False, True) for row in observations)
        assert alias not in backend_calls and unrelated.exists()
        assert not path.exists() and custody.execution_lease == (None,)
        assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()
        assert runner.retry_cleanup(alias)
        print("terminal real resource observations", observations)
    finally:
        if captured:
            print("exact terminal owner cleanup", captured[0][1].__dict__.get("_path"))
            captured[0][1].cleanup()


def test_forget_storage_retains_independent_execution_lease(tmp_path):
    """Keep settled exact custody reachable while its independent invocation is active."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    custody = _StorageCustody(owner)
    custody._write_state(storage_alias=owner.cleanup_debts()[0])
    token = object()
    custody._write_state(execution_lease=(token,))
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._remember_storage(owner)
    try:
        assert owner.cleanup() and not path.exists()
        runner._forget_storage(owner)
        assert runner._prelaunch_storage.get(id(owner)) is custody
        assert custody.execution_lease[0] is token and custody.release_complete
        assert runner.retry_cleanup(custody.storage_alias.debt_id) is False
    finally:
        print("exact settled lease owner cleanup", owner.__dict__.get("_path"))
        owner.cleanup()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_execution_lease_mismatch_retains_exact_custody(tmp_path, monkeypatch, context, kind):
    """Never release a foreign invocation token or its reachable exact custody."""
    import topsailai.hooks.script_runner as module

    initialize = module._StorageCustody.__init__
    setter = _custody_field_write
    cleanup = TemporaryStorageOwner.cleanup
    primary = kind("original alias handoff")
    foreign = object()
    captured = []
    armed = True

    def init(custody, owner):
        """Capture only the actual invocation custody."""
        initialize(custody, owner)
        captured.append((custody, owner))

    def assign(custody, name, value):
        """Interrupt after allocation without altering the original traceback."""
        nonlocal armed
        if armed and name == "storage_alias" and value is not None:
            armed = False
            raise primary
        setter(custody, name, value)

    def remove(owner):
        """Replace authority before genuine cleanup to test exact release ownership."""
        captured[0][0]._write_state(execution_lease=(foreign,))
        return cleanup(owner)

    script = tmp_path / "script"
    script.write_text("#!/bin/false\n")
    script.chmod(0o700)
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    with monkeypatch.context() as patch:
        patch.setattr(module._StorageCustody, "__init__", init)
        _install_custody_assignment_fault(patch, assign)
        patch.setattr(TemporaryStorageOwner, "cleanup", remove)
        with pytest.raises(BaseException) as caught:
            runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                output_remaining_bytes=65536, cancellation=threading.Event())
    custody, owner = captured[0]
    assert caught.value is primary and primary.__cause__ is None
    assert custody.execution_lease[0] is foreign
    assert runner._prelaunch_storage.get(id(owner)) is custody
    assert custody.release_complete
    assert not runner.retry_cleanup(custody.storage_alias.debt_id)
    assert runner.retry_cleanup("unrelated-foreign-lease")
    assert custody.execution_lease[0] is foreign
    # The simulated foreign owner alone hands back its own authority.
    custody._write_state(execution_lease=(None,))
    custody._write_state(pending=True)
    assert runner.retry_cleanup(custody.storage_alias.debt_id)
    assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()


@pytest.mark.parametrize("allocation_state", ["empty", "debt", "missing", "malformed"])
def test_allocation_false_requires_verified_no_resource(tmp_path, monkeypatch, allocation_state):
    """Trust false allocation only with complete evidence and retain contradictory real debt."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    native_allocate = TemporaryStorageOwner.allocate
    owners = []
    custodies = []
    native_init = module._StorageCustody.__init__

    def initialize(custody, owner):
        """Capture exact custody without changing invocation authority."""
        native_init(custody, owner)
        custodies.append(custody)

    def allocate(owner):
        """Return false with verified emptiness, actual debt, or unprovable state."""
        owners.append(owner)
        if allocation_state == "debt":
            assert native_allocate(owner)
        elif allocation_state == "missing":
            del owner.__dict__["_candidate_path"]
        elif allocation_state == "malformed":
            owner.__dict__["_candidate_path"] = object()
        return False

    script = tmp_path / "script"
    script.write_text("unused")
    script.chmod(0o700)
    event = HookEvent("review", "u06.arbitration", 1, "owner", "scope", "op", None, 1,
                      "2026-10-10T00:00:00Z", "test", "review", {})
    with monkeypatch.context() as patch:
        patch.setattr(module._StorageCustody, "__init__", initialize)
        patch.setattr(TemporaryStorageOwner, "allocate", allocate)
        result = runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
            context=HookContext(event, "delivery", "hook_script", 1, 5000),
            options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
            execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
            output_remaining_bytes=65536, cancellation=threading.Event())
    assert result.status is HookStatus.ERROR
    custody = custodies[0]
    owner = owners[0]
    assert custody.execution_lease == (None,)
    assert custody.storage_settled is (allocation_state == "empty")
    assert runner.retry_cleanup("unrelated-false-allocation")
    if allocation_state == "empty":
        assert runner._prelaunch_storage == {}
    else:
        assert runner._prelaunch_storage[id(owner)] is custody
        assert custody.pending
    if allocation_state == "debt":
        path = owner.path
        assert path.exists()
        alias = owner.cleanup_debts()[0].debt_id
        assert [debt.debt_id for debt in runner.cleanup_debts()] == [alias]
        assert runner.retry_cleanup(alias)
        assert not path.exists() and runner._prelaunch_storage == {}


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("release_failure", ["none", "before", "after", "fallback"])
def test_verified_empty_allocation_teardown_interruption(tmp_path, monkeypatch, context, after, release_failure):
    """Propagate teardown failure without leaving settled custody hidden after lease withdrawal."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    initialize = module._StorageCustody.__init__
    captured = []
    native_list = list
    interruption = SystemExit("empty allocation lease teardown")
    release_error = KeyboardInterrupt("terminal registry release")

    class Registry(dict):
        """Interrupt exact terminal removal without changing identity authority."""
        def pop(self, key, default=None):
            """Exercise before/after release while preserving the teardown primary."""
            if release_failure == "none":
                return super().pop(key, default)
            if release_failure == "after":
                super().pop(key, default)
            raise release_error

        def __delitem__(self, key):
            """Force the native exact-identity fallback only when requested."""
            if release_failure == "fallback":
                raise release_error
            super().__delitem__(key)

    _install_registry_fault(runner, Registry())

    hit = []
    def write(custody, _retire=(), **changes):
        """Interrupt one lease withdrawal while allowing exact fallback convergence."""
        if captured and custody is captured[0] and changes.get("execution_lease") == (None,) and not hit:
            hit.append(True)
            if after:
                _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changes)
            raise interruption
        _CANONICAL_CUSTODY_WRITE(custody, _retire=_retire, **changes)

    def init(custody, owner):
        """Retain exact custody for settlement and authority assertions."""
        initialize(custody, owner)
        captured.append(custody)

    script = tmp_path / "script"
    script.write_text("unused")
    script.chmod(0o700)
    with monkeypatch.context() as patch:
        patch.setattr(module._StorageCustody, "_write_state", write)
        patch.setattr(module._StorageCustody, "__init__", init)
        patch.setattr(TemporaryStorageOwner, "allocate", lambda owner: False)
        with pytest.raises(SystemExit) as caught:
            runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
                context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
                execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
                output_remaining_bytes=65536, cancellation=threading.Event())
    assert caught.value is interruption and interruption.__cause__ is None
    frames = []
    traceback = interruption.__traceback__
    while traceback is not None:
        frames.append(traceback.tb_frame.f_code.co_name)
        traceback = traceback.tb_next
    assert "write" in frames
    assert interruption.__context__ is None
    assert captured[0].storage_settled and captured[0].execution_lease == (None,)
    assert runner.cleanup_debts() == ()
    assert runner.retry_cleanup("unrelated-empty-teardown")
    assert runner._prelaunch_storage == {}


@pytest.mark.parametrize("malformed", [None, [], [None, None], (None,), {}, "missing", [False], [object()]])
def test_malformed_execution_lease_preserves_unrelated_retry(tmp_path, monkeypatch, context, malformed):
    """Retain unprovable authority without crashing unrelated public recovery."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    initialize = module._StorageCustody.__init__
    captured = []

    def init(custody, owner):
        """Capture the exact invocation custody before allocation."""
        initialize(custody, owner)
        captured.append(custody)

    def allocate(owner):
        """Invalidate only lease shape without inventing resource settlement."""
        if malformed == "missing":
            captured[0]._write_state(_retire=("execution_lease",))
        else:
            captured[0]._write_state(execution_lease=malformed)
        return False

    script = tmp_path / "script"
    script.write_text("unused")
    script.chmod(0o700)
    with monkeypatch.context() as patch:
        patch.setattr(module._StorageCustody, "__init__", init)
        patch.setattr(TemporaryStorageOwner, "allocate", allocate)
        result = runner.execute_entry(entry_index=0, entry=HookScriptEntry(script, script.name),
            context=context, options=HookScriptExecutionOptions(), policy=HookScriptExecutionPolicy(),
            execution_deadline=time.monotonic()+5, cleanup_deadline=time.monotonic()+5,
            output_remaining_bytes=65536, cancellation=threading.Event())
    assert result.status is HookStatus.ERROR
    assert runner._prelaunch_storage
    if malformed == "missing":
        assert "execution_lease" not in captured[0].__dict__
    else:
        snapshot = module._observe_retry_owner(captured[0])
        assert captured[0].execution_lease is snapshot["execution_lease"]
        assert type(malformed) not in (list, dict) or captured[0].execution_lease is not malformed
    assert runner.retry_cleanup("unrelated-malformed-lease")
    if malformed != "missing":
        assert module._observe_retry_owner(captured[0]) is snapshot


@pytest.mark.parametrize("shape", ["none", "empty", "long", "tuple", "mapping", "string", "wrong-token", "missing", "foreign"])
def test_execution_lease_shape_exact_custody_handback(tmp_path, shape):
    """Block only exact unsafe authority and converge after its legitimate handback."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    alias = owner.cleanup_debts()[0].debt_id
    custody = module._StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=owner.cleanup_debts()[0])
    foreign = object()
    values = {"none": None, "empty": [], "long": [None, None], "tuple": ((None,),),
              "mapping": {0: None}, "string": "x", "wrong-token": [False], "foreign": [foreign]}
    if shape == "missing":
        custody._write_state(_retire=("execution_lease",))
    else:
        custody._write_state(execution_lease=values[shape])
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[alias] = owner
    state = custody.__dict__.copy()
    assert runner.retry_cleanup("unrelated-shape")
    assert not runner.retry_cleanup(alias)
    assert path.exists() and runner._prelaunch_storage[id(owner)] is custody
    assert custody.__dict__ == state
    assert runner.cleanup_debts() == ()
    # The legitimate authority alone repairs and hands back its exact obligation.
    custody._write_state(execution_lease=[None])
    assert runner.retry_cleanup(alias)
    assert not path.exists() and runner._prelaunch_storage == {}
    assert runner.cleanup_debts() == ()


@pytest.mark.parametrize("lease", [None, [], [None, None], ((None,),), [False], [object()]])
def test_forget_storage_retains_unprovable_lease(tmp_path, lease):
    """Keep exact settled custody reachable until authority is safely handed back."""
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    custody = module._StorageCustody(owner)
    custody._write_state(execution_lease=lease)
    runner._write_prelaunch_storage(((id(owner), custody),))
    assert owner.cleanup()
    runner._forget_storage(owner)
    assert runner._prelaunch_storage[id(owner)] is custody
    assert custody.execution_lease is module._immutable_lease(custody.execution_lease) and custody.release_complete
    assert type(lease) is not list or custody.execution_lease is not lease
    assert runner.retry_cleanup("unrelated-forget-shape")
    custody._write_state(execution_lease=[None])
    runner._forget_storage(owner)
    assert runner._prelaunch_storage == {}


@pytest.mark.parametrize('replacement', ['foreign', 'malformed'])
def test_retry_finalizer_preserves_replacement_authority(tmp_path, monkeypatch, replacement):
    """Retain exact custody when cleanup handoff introduces unowned authority."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    foreign = object()
    authority = (foreign,) if replacement == 'foreign' else ()
    native = TemporaryStorageOwner.retry_cleanup
    captured = {}
    def cleanup(storage, alias):
        """Complete real cleanup then install exact replacement authority outside runner lock."""
        result = native(storage, alias)
        assert result and not path.exists()
        captured['retry_token'] = custody.retry_owner
        assert captured['retry_token'] is not None
        custody._write_state(execution_lease=authority)
        assert runner.retry_cleanup(debt.debt_id) is False
        assert runner.retry_cleanup('unrelated-during-retry') is True
        assert custody.retry_owner is captured['retry_token']
        return result
    with monkeypatch.context() as patch:
        patch.setattr(TemporaryStorageOwner, 'retry_cleanup', cleanup)
        result = runner.retry_cleanup(debt.debt_id)
    captured.update(result=result, custody_reachable=runner._prelaunch_storage.get(id(owner)) is custody,
                    foreign_unchanged=custody.execution_lease is authority,
                    exact_after=runner.retry_cleanup(debt.debt_id),
                    unrelated_after=runner.retry_cleanup('unrelated-after-retry'), directory_exists=path.exists())
    print(captured)
    assert result is False
    assert custody.execution_lease is authority
    assert custody.retry_owner is None
    assert custody.release_complete
    assert runner._prelaunch_storage.get(id(owner)) is custody
    assert runner.retry_cleanup(debt.debt_id) is False
    assert runner.retry_cleanup('unrelated-after-retry') is True
    # Only the legitimate authority owner hands back the exact obligation.
    custody._write_state(execution_lease=[None])
    custody._write_state(pending=True)
    assert runner.retry_cleanup(debt.debt_id)
    assert runner._prelaunch_storage == {} and runner.cleanup_debts() == ()


@pytest.mark.parametrize("shape", ["foreign", "missing", "none", "empty", "long", "tuple", "wrong-token"])
@pytest.mark.parametrize("boundary", ["cleanup-before", "cleanup-after", "forget-before", "forget-after"])
@pytest.mark.parametrize("outcome", ["success", "false", "raise"])
def test_retry_finalizer_authority_matrix(tmp_path, monkeypatch, shape, boundary, outcome):
    """Keep replacement authority reachable through cleanup and forget outcomes."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    authority = {"foreign": (object(),), "none": None, "empty": (), "long": (None, None),
                 "tuple": ((None,),), "wrong-token": (False,)}.get(shape)
    interruption = SystemExit("retry cleanup boundary")
    native_cleanup = TemporaryStorageOwner.retry_cleanup
    native_forget = OwnedHookScriptRunner._forget_storage
    captured = []

    def replace_authority():
        """Install foreign state outside the runner lock and observe exact exclusion."""
        token = custody.retry_owner
        assert token is not None
        captured.append(token)
        if shape == "missing":
            custody._write_state(_retire=("execution_lease",))
        else:
            custody._write_state(execution_lease=authority)
        assert runner.retry_cleanup(debt.debt_id) is False
        assert runner.retry_cleanup("unrelated-matrix") is True
        assert custody.retry_owner is token

    def cleanup(storage, alias):
        """Inject before or after the exact native cleanup without sleep races."""
        if boundary == "cleanup-before":
            replace_authority()
        result = native_cleanup(storage, alias) if outcome == "success" or boundary.startswith("forget") else False
        if boundary == "cleanup-after":
            replace_authority()
        if boundary.startswith("cleanup") and outcome == "raise":
            raise interruption
        return result

    def forget(instance, storage):
        """Inject the same authority handoff on either side of the exact forget."""
        if boundary == "forget-before":
            replace_authority()
        native_forget(instance, storage)
        if boundary == "forget-after":
            replace_authority()
        if boundary.startswith("forget") and outcome == "raise":
            raise interruption

    with monkeypatch.context() as patch:
        patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        patch.setattr(OwnedHookScriptRunner, "_forget_storage", forget)
        if outcome == "raise":
            with pytest.raises(SystemExit) as caught:
                runner.retry_cleanup(debt.debt_id)
            assert caught.value is interruption and interruption.__cause__ is None
            assert interruption.__context__ is None
            assert any(frame.name == ("cleanup" if boundary.startswith("cleanup") else "forget") for frame in caught.traceback)
        else:
            assert runner.retry_cleanup(debt.debt_id) is False
    assert custody.retry_owner is None
    assert runner._prelaunch_storage[id(owner)] is custody
    assert custody.pending
    if captured:
        if shape == "missing":
            assert "execution_lease" not in custody.__dict__
        else:
            assert custody.execution_lease is authority
        assert runner.retry_cleanup(debt.debt_id) is False
    assert runner.retry_cleanup("unrelated-after-matrix") is True
    # Only the actual authority owner repairs and hands back this obligation.
    custody._write_state(execution_lease=[None])
    assert runner.retry_cleanup(debt.debt_id)
    assert not path.exists() and runner._prelaunch_storage == {}
    assert runner.cleanup_debts() == ()


@pytest.mark.parametrize("primary_type", [RuntimeError, SystemExit, KeyboardInterrupt])
@pytest.mark.parametrize("secondary_type", [RuntimeError, SystemExit, KeyboardInterrupt])
@pytest.mark.parametrize("boundary", ["lock-enter", "lock-exit", "disarm-before", "disarm-after"])
def test_retry_primary_preserved_across_finalizer(tmp_path, monkeypatch, primary_type, secondary_type, boundary):
    """Preserve exact primary and source frames through bounded finalizer interruptions."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    debt = owner.cleanup_debts()[0]
    primary = primary_type("cleanup primary")
    secondary = secondary_type("finalizer secondary")
    failed = []
    hits = []
    native_lock = threading.Lock()

    class Custody(_StorageCustody):
        """Interrupt the normal token withdrawal without interfering with native fallback."""
        def _write_retry_owner(self, value):
            """Inject exactly once before or after the owned disarm mutation."""
            name = "retry_owner"
            if name == "retry_owner" and value is None and failed and not hits and boundary.startswith("disarm"):
                hits.append(boundary)
                if boundary == "disarm-after":
                    _StorageCustody._write_retry_owner(self, value) if name == "retry_owner" else object.__setattr__(self, name, value)
                raise secondary
            _StorageCustody._write_retry_owner(self, value) if name == "retry_owner" else object.__setattr__(self, name, value)

    class Lock:
        """Keep deterministic lock interruption outside nested public recovery."""
        def __enter__(self):
            """Fail before acquire or acquire the real non-reentrant lock."""
            if failed and not hits and boundary == "lock-enter":
                hits.append(boundary)
                raise secondary
            native_lock.acquire()
            return self

        def __exit__(self, kind, error, tb):
            """Release the real lock before the injected exit failure."""
            native_lock.release()
            if failed and not hits and boundary == "lock-exit":
                hits.append(boundary)
                raise secondary

    custody = Custody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    tokens = []

    def cleanup(storage, alias):
        """Observe exact exclusion outside lock then emit the precise source exception."""
        tokens.append(custody.retry_owner)
        assert tokens[-1] is not None
        assert runner.retry_cleanup(alias) is False
        assert runner.retry_cleanup("unrelated-primary-matrix") is True
        assert custody.retry_owner is tokens[-1]
        failed.append(True)
        raise primary

    with monkeypatch.context() as patch:
        runner._lock = Lock()
        patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
    runner._lock = native_lock
    assert caught.value is primary
    assert any(frame.name == "cleanup" for frame in caught.traceback)
    assert primary.__cause__ is None and primary.__context__ is None
    assert hits == [boundary]
    assert len(primary.__notes__) == 1
    assert runner._prelaunch_storage[id(owner)] is custody
    assert custody.retry_owner is None and path.exists()
    assert runner.retry_cleanup("unrelated-after-primary") is True
    assert runner.retry_cleanup(debt.debt_id) is True
    assert not path.exists() and runner._prelaunch_storage == {}
    assert runner.cleanup_debts() == ()


def test_retry_double_disarm_preserves_public_convergence(tmp_path, monkeypatch):
    """Retain a convergent public obligation when both withdrawal boundaries interrupt."""
    import inspect
    import sys
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    primary = SystemExit("cleanup primary")
    secondary = KeyboardInterrupt("normal disarm")
    fallback = RuntimeError("native fallback")
    armed = []
    hit = []

    class Custody(_StorageCustody):
        """Interrupt normal exact withdrawal once after cleanup failed."""
        def _write_retry_owner(self, value):
            """Leave the original token armed at the interrupted mutation."""
            name = "retry_owner"
            if name == "retry_owner" and value is None and armed:
                armed.clear()
                raise secondary
            _StorageCustody._write_retry_owner(self, value) if name == "retry_owner" else object.__setattr__(self, name, value)

    custody = Custody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._retry_cleanup_invocation)
    target = first + next(i for i, line in enumerate(source) if '_commit_retry_owner(selected, None)' in line)

    def trace(frame, event, arg):
        """Interrupt native fallback before mutation without entering runner lock."""
        if event == "line" and frame.f_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__ and frame.f_lineno == target and not hit:
            hit.append(True)
            raise fallback
        return trace

    def cleanup(storage, alias):
        """Raise the precise primary while keeping the owned real directory."""
        armed.append(True)
        raise primary

    previous = sys.gettrace()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
            sys.settrace(trace)
            with pytest.raises(BaseException) as caught:
                runner.retry_cleanup(debt.debt_id)
            sys.settrace(previous)
        assert caught.value is primary
        assert hit and runner._prelaunch_storage[id(owner)] is custody
        print("retry token retained:", custody.retry_owner is not None)
        assert runner.retry_cleanup("unrelated-double-disarm") is True
        assert runner.retry_cleanup(debt.debt_id) is True
        assert runner._prelaunch_storage == {}
    finally:
        sys.settrace(previous)
        assert owner.cleanup()


def test_retry_terminal_identity_interruption_preserves_convergence(tmp_path, monkeypatch):
    """Retain a convergent public obligation when both withdrawal boundaries interrupt."""
    import sys
    import inspect
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    primary = SystemExit("cleanup primary")
    secondary = KeyboardInterrupt("normal disarm")
    fallback = RuntimeError("native fallback")
    armed = []
    hit = []

    class Custody(_StorageCustody):
        """Interrupt normal exact withdrawal once after cleanup failed."""
        def _write_retry_owner(self, value):
            """Leave the original token armed at the interrupted mutation."""
            name = "retry_owner"
            if name == "retry_owner" and value is None and armed:
                armed.clear()
                raise secondary
            _StorageCustody._write_retry_owner(self, value) if name == "retry_owner" else object.__setattr__(self, name, value)

    custody = Custody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    class Registry(dict):
        """Interrupt the final exact identity observation once without mutating custody."""
        def get(self, key, default=None):
            """Fail only after the native disarm fallback has been interrupted."""
            if hit and not terminal_hit:
                terminal_hit.append(True)
                raise KeyboardInterrupt("terminal identity observation")
            return super().get(key, default)

    terminal_hit = []
    _install_registry_fault(runner, Registry())
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._retry_cleanup_invocation)
    target = first + next(i for i, line in enumerate(source) if '_commit_retry_owner(selected, None)' in line)

    def trace(frame, event, arg):
        """Interrupt native fallback before mutation without entering runner lock."""
        if event == "line" and frame.f_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__ and frame.f_lineno == target and not hit:
            hit.append(True)
            raise fallback
        return trace

    def cleanup(storage, alias):
        """Raise the precise primary while keeping the owned real directory."""
        armed.append(True)
        raise primary

    previous = sys.gettrace()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
            sys.settrace(trace)
            with pytest.raises(BaseException) as caught:
                runner.retry_cleanup(debt.debt_id)
            sys.settrace(previous)
        assert caught.value is primary
        assert hit and runner._prelaunch_storage[id(owner)] is custody
        print("retry token retained:", custody.retry_owner is not None)
        assert runner.retry_cleanup("unrelated-double-disarm") is True
        assert runner.retry_cleanup(debt.debt_id) is True
        assert runner._prelaunch_storage == {}
    finally:
        sys.settrace(previous)
        assert owner.cleanup()


def test_foreign_closed_invocation_cannot_authorize_token_withdrawal(tmp_path):
    """A different closed invocation cannot prove this token has ended."""
    from topsailai.hooks.script_runner import _StorageCustody
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    foreign_token = object()
    custody._write_retry_owner(foreign_token)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    other = runner._retry_cleanup_invocation("unrelated-closed-invocation")
    next(other)
    try:
        other.send(other)
    except StopIteration as done:
        assert done.value is True
    assert other.gi_frame is None
    custody._write_handback((custody, foreign_token, other))
    try:
        assert runner.retry_cleanup(debt.debt_id) is False
        assert custody.retry_owner is foreign_token
        assert runner._prelaunch_storage[id(owner)] is custody
    finally:
        assert owner.cleanup()


@pytest.mark.parametrize("replacement", ["copy", "list", "dict", "missing", "foreign-token", "foreign-generator", "foreign-custody"])
def test_retry_receipt_requires_exact_provenance(tmp_path, monkeypatch, replacement):
    """Reject substitutions without stealing the original invocation authority."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("receipt source")

    def cleanup(storage, alias):
        """Capture a genuine receipt while preserving the exact directory."""
        raise primary

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
            with pytest.raises(SystemExit) as caught:
                runner.retry_cleanup(debt.debt_id)
        assert caught.value is primary
        receipt = custody.retry_handback
        assert runner._retry_receipts[id(custody)] is receipt
        assert receipt[2].gi_frame is None
        custody._write_retry_owner(receipt[1])
        proof = tuple(list(receipt))
        other = runner._retry_cleanup_invocation("other-receipt")
        next(other)
        with pytest.raises(StopIteration):
            other.send(other)
        if replacement == "list":
            proof = list(receipt)
        elif replacement == "dict":
            proof = {"custody": custody, "token": receipt[1], "invocation": receipt[2]}
        elif replacement == "missing":
            proof = None
        elif replacement == "foreign-token":
            custody._write_retry_owner(object())
            proof = receipt
        elif replacement == "foreign-generator":
            proof = (custody, receipt[1], other)
        elif replacement == "foreign-custody":
            proof = (_StorageCustody(owner), receipt[1], receipt[2])
        custody._write_handback(proof)
        token = custody.retry_owner
        assert runner.retry_cleanup(debt.debt_id) is False
        assert custody.retry_owner is token
        assert runner._prelaunch_storage[id(owner)] is custody
        assert runner.retry_cleanup("unrelated-receipt") is True
        custody._write_handback(receipt)
        custody._write_retry_owner(receipt[1])
        assert runner.retry_cleanup(debt.debt_id) is True
        assert runner._prelaunch_storage == {}
        assert runner._retry_receipts == {}
    finally:
        assert owner.cleanup()


def test_retry_lifecycle_rejects_foreign_driver(tmp_path):
    """Reject compatible closed generators before publishing any authority."""
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    foreign = runner._retry_cleanup_invocation("foreign")
    next(foreign)
    with pytest.raises(StopIteration):
        foreign.send(foreign)
    invocation = runner._retry_cleanup_invocation("exact")
    next(invocation)
    with pytest.raises(ValueError, match="exact invocation"):
        invocation.send(foreign)
    assert runner._retry_receipts == {}


@pytest.mark.parametrize("observation", ["native", "view", "missing", "malformed", "interrupt"])
@pytest.mark.parametrize("alias_kind", ["storage", "record"])
def test_active_exact_retry_precedes_owner_observation(tmp_path, monkeypatch, observation, alias_kind):
    """Known exact aliases remain excluded despite unavailable owner observations."""
    import builtins
    from topsailai.hooks import script_runner as module
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    token = object()
    custody._write_retry_owner(token)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    alias = debt.debt_id
    if alias_kind == "record":
        from topsailai.hooks.process_state import LaunchRecord
        custody._write_state(record=LaunchRecord("exact-record-observation"))
        custody._write_state(execution_owner=object())
        alias = custody.record.debt_id
    hits = []

    class ObjectView:
        """Expose bounded invalid observation without modifying shared builtins."""
        @staticmethod
        def __getattribute__(value, name):
            """Only alter the exact owner's state observation."""
            state = builtins.object.__getattribute__(value, name)
            if value is not owner or name != "__dict__" or observation == "native":
                return state
            hits.append(True)
            if observation == "interrupt":
                raise KeyboardInterrupt("owner observation")
            if observation == "missing":
                return {}
            if observation == "malformed":
                return None
            return type("AuthorityView", (), {})()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "object", ObjectView, raising=False)
            assert runner.retry_cleanup(alias) is False
            assert hits == []
            assert runner.retry_cleanup("unrelated-owner-observation") is True
        assert custody.retry_owner is token
        assert runner._prelaunch_storage[id(owner)] is custody
        assert owner.path.exists()
        custody._write_retry_owner(None)
        custody._write_state(execution_owner=None)
        assert runner.retry_cleanup(debt.debt_id) is True
        assert runner._prelaunch_storage == {}
    finally:
        assert owner.cleanup()


@pytest.mark.parametrize("registry_state", ["replacement", "missing"])
def test_retry_registry_replacement_retains_exact_token_until_restoration(
    tmp_path, monkeypatch, registry_state,
):
    """Detached invocation authority survives until the exact owner restores identity."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    owned_path = owner.path
    debt = owner.cleanup_debts()[0]
    original = _StorageCustody(owner)
    original._write_state(pending=True, storage_alias=debt)
    replacement = _StorageCustody(owner)
    replacement._write_state(pending=True, storage_alias=debt)
    foreign = object()
    replacement._write_retry_owner(foreign)
    runner._write_prelaunch_storage(((id(owner), original),))
    runner._storage[debt.debt_id] = owner
    captured = []

    def cleanup(storage, alias):
        """Replace only registry authority without deleting any owned resource."""
        captured.append(original.retry_owner)
        if registry_state == "replacement":
            runner._write_prelaunch_storage(((id(owner), replacement),))
            assert runner.retry_cleanup(alias) is False
        else:
            runner._write_prelaunch_storage(retire=(id(owner),))
        assert runner.retry_cleanup("unrelated-replacement") is True
        return False

    try:
        with monkeypatch.context() as patch:
            patch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
            assert runner.retry_cleanup(debt.debt_id) is False
        assert original.retry_owner is captured[0]
        assert replacement.retry_owner is foreign
        assert owner.path.exists()
        receipt = runner._retry_receipts[id(original)]
        assert receipt is original.retry_handback
        assert receipt[2].gi_frame is None
        runner._write_prelaunch_storage(((id(owner), original),))
        assert runner.retry_cleanup(debt.debt_id) is True
        assert original.retry_owner is None
        assert replacement.retry_owner is foreign
        assert id(owner) not in runner._prelaunch_storage
        assert id(original) not in runner._retry_receipts
        assert not owned_path.exists()
    finally:
        assert owner.cleanup()


def test_retry_native_finalizer_exit_retains_exact_lock_release_responsibility(tmp_path, monkeypatch):
    """A one-shot exit interruption must not strand global recovery exclusion."""
    import dis
    import sys
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    code = OwnedHookScriptRunner._retry_cleanup_invocation.__code__
    instructions = list(dis.get_instructions(code))
    targets = {i.offset for n, i in enumerate(instructions) if i.opname == 'CALL'
               and n >= 3 and all(x.opname == 'LOAD_CONST' and x.argval is None
                                  for x in instructions[n-3:n])}
    assert targets
    failure = KeyboardInterrupt('finalizer-exit-one-shot')
    armed = []
    hits = []

    def cleanup(storage, alias):
        """Arm after retry admission without releasing real storage."""
        armed.append(True)
        return False

    def trace(frame, event, arg):
        """Interrupt normal context exit only after actual token withdrawal."""
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            if (event == 'opcode' and frame.f_lasti in targets and armed
                    and frame.f_locals.get('selected') is custody
                    and custody.retry_owner is None):
                armed.clear()
                hits.append(frame.f_lasti)
                assert runner._lock.locked()
                raise failure
        return trace

    previous = sys.gettrace()
    try:
        monkeypatch.setattr(TemporaryStorageOwner, 'retry_cleanup', cleanup)
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(previous)
        assert caught.value is failure
        assert len(hits) == 1
        available = runner._lock.acquire(False)
        if available:
            runner._lock.release()
        print('exit_opcode=', hits[0], 'lock_available=', available,
              'token_withdrawn=', custody.retry_owner is None)
        assert available, 'finalizer exit interruption stranded runner exclusion'
    finally:
        sys.settrace(previous)
        if runner._lock.locked():
            runner._lock.release()
        print('Deleting probe-owned storage:', path)
        assert owner.cleanup()


def test_reused_primary_diagnostics_do_not_accumulate_duplicate_finalizer_notes(tmp_path, monkeypatch):
    """Repeated exact finalizer diagnostics must not grow an identical primary forever."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    path = owner.path
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit('reused cleanup primary')
    secondary = KeyboardInterrupt('repeated finalizer secondary')
    native = runner._lock
    armed = []
    counts = []

    class Lock:
        """Release native exclusion before each one-shot finalizer exception."""
        def __enter__(self):
            """Acquire the exact probe-owned native lock."""
            native.acquire()
            return self

        def __exit__(self, kind, error, tb):
            """Hand back exclusion before emitting the bounded source failure."""
            native.release()
            if armed:
                armed.clear()
                raise secondary

    def cleanup(storage, alias):
        """Repeat the exact primary object without replacing real resource debt."""
        armed.append(True)
        raise primary

    try:
        runner._lock = Lock()
        monkeypatch.setattr(TemporaryStorageOwner, 'retry_cleanup', cleanup)
        for _ in range(8):
            with pytest.raises(SystemExit) as caught:
                runner.retry_cleanup(debt.debt_id)
            assert caught.value is primary
            assert any(frame.name == 'cleanup' for frame in caught.traceback)
            assert primary.__cause__ is None and primary.__context__ is None
            assert custody.retry_owner is None
            counts.append(len(primary.__notes__))
        print('diagnostic_counts=', counts, 'unique_notes=', len(set(primary.__notes__)))
        assert len(primary.__notes__) == len(set(primary.__notes__)), 'identical finalizer diagnostics accumulate without bound'
    finally:
        runner._lock = native
        print('Deleting exact diagnostic probe storage:', path)
        assert owner.cleanup()


@pytest.mark.parametrize("phase", ["finalizer", "terminal handback"])
def test_retry_secondary_notes_bound_runner_owned_diagnostics(phase):
    """Keep caller notes and cap distinct runner diagnostics across recovery attempts."""
    from topsailai.hooks.script_runner import _note_retry_interruption

    primary = SystemExit("cleanup")
    primary.add_note("caller note")
    for index in range(12):
        kind = type("Secondary" + str(index), (BaseException,), {})
        secondary = kind("unbounded text " * 500)
        _note_retry_interruption(primary, phase, secondary)
        _note_retry_interruption(primary, phase, secondary)
    assert primary.__notes__[0] == "caller note"
    assert len(primary.__notes__) == 5
    assert len(set(primary.__notes__)) == 5
    assert all(len(note) < 100 for note in primary.__notes__)
    assert primary.__cause__ is None and primary.__context__ is None


@pytest.mark.parametrize("notes", [None, "not a list", [object()]])
def test_retry_secondary_notes_preserve_malformed_caller_state(notes):
    """Malformed diagnostics must neither replace caller state nor escape as success."""
    from topsailai.hooks.script_runner import _note_retry_interruption

    primary = SystemExit("cleanup")
    primary.__notes__ = notes
    _note_retry_interruption(primary, "finalizer", KeyboardInterrupt("secondary"))
    assert primary.__notes__ is notes


def test_retry_secondary_notes_missing_and_failed_write():
    """Missing notes initialize while a rejected write cannot replace primary failure."""
    from topsailai.hooks.script_runner import _note_retry_interruption

    class RejectNotes(SystemExit):
        """Reject diagnostic storage without changing the cleanup exception object."""
        def __setattr__(self, name, value):
            """Refuse only notes publication."""
            if name == "__notes__":
                raise RuntimeError("notes write denied")
            super().__setattr__(name, value)

    primary = SystemExit("cleanup")
    _note_retry_interruption(primary, "finalizer", KeyboardInterrupt("a"))
    _note_retry_interruption(primary, "finalizer", KeyboardInterrupt("b"))
    _note_retry_interruption(primary, "terminal handback", KeyboardInterrupt("c"))
    assert primary.__notes__ == ["Retry finalizer interrupted: KeyboardInterrupt",
                                 "Retry terminal handback interrupted: KeyboardInterrupt"]
    rejected = RejectNotes("original")
    _note_retry_interruption(rejected, "finalizer", KeyboardInterrupt())
    assert not hasattr(rejected, "__notes__")
    assert rejected.args == ("original",)



def test_retry_secondary_notes_share_budget_without_owning_caller_text():
    """Both phases share one budget without claiming identical caller-authored text."""
    from topsailai.hooks.script_runner import _note_retry_interruption, _RetryInterruptionNote

    primary = SystemExit("cleanup")
    caller = "Retry finalizer interrupted: KeyboardInterrupt"
    primary.add_note(caller)
    for index in range(12):
        phase = "finalizer" if index % 2 else "terminal handback"
        kind = type("Distinct" + str(index), (BaseException,), {})
        _note_retry_interruption(primary, phase, kind())
    assert primary.__notes__[0] is caller
    assert sum(type(note) is _RetryInterruptionNote for note in primary.__notes__) == 4
    assert len(primary.__notes__) == 5


def test_retry_secondary_notes_read_failure_keeps_primary():
    """A hostile diagnostic read must not escape instead of the cleanup failure."""
    from topsailai.hooks.script_runner import _note_retry_interruption

    class RejectRead(SystemExit):
        """Reject only diagnostic reads."""
        def __getattribute__(self, name):
            """Keep failure state available while denying notes observation."""
            if name == "__notes__":
                raise KeyboardInterrupt("notes read denied")
            return super().__getattribute__(name)

    primary = RejectRead("original")
    _note_retry_interruption(primary, "finalizer", KeyboardInterrupt())
    assert primary.args == ("original",)


@pytest.mark.parametrize("override_mode", ["return", "raise", "malformed"])
@pytest.mark.parametrize("finalizer_failure", [False, True])
def test_retry_native_traceback_dispatch_preserves_cleanup_primary(tmp_path, monkeypatch, override_mode, finalizer_failure):
    """Native rethrow must retain cleanup identity and source despite subclass overrides."""
    from topsailai.hooks.script_runner import _StorageCustody

    calls = []
    foreign = RuntimeError("foreign traceback error")

    class Primary(SystemExit):
        """Expose public exception dispatch without mutating private authority."""
        def with_traceback(self, tb):
            """Return or raise a foreign exception if dynamic dispatch occurs."""
            calls.append(tb)
            if override_mode == "raise":
                raise foreign
            return foreign

        def __getattribute__(self, name):
            """Expose malformed traceback observation only in the designated case."""
            if name == "__traceback__" and override_mode == "malformed":
                return object()
            return super().__getattribute__(name)

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = Primary("exact cleanup primary")
    primary.add_note("caller diagnostic")
    native = runner._lock
    armed = []

    class Lock:
        """Hand back native exclusion before a secondary finalizer failure."""
        def __enter__(self):
            """Acquire only the exact test lock."""
            native.acquire()
            return self

        def __exit__(self, kind, error, tb):
            """Release before raising so this test isolates primary dispatch."""
            native.release()
            if armed and finalizer_failure:
                armed.clear()
                raise KeyboardInterrupt("secondary finalizer")

    def cleanup(storage, alias):
        """Raise the exact cleanup source and arm an optional secondary."""
        armed.append(True)
        raise primary

    try:
        runner._lock = Lock()
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert not calls
        assert primary.__cause__ is None and primary.__context__ is None
        assert primary.__notes__[0] == "caller diagnostic"
        assert len(primary.__notes__) <= 2
        assert custody.retry_owner is None
    finally:
        runner._lock = native
        print("Deleting exact native traceback test storage:", owner.path)
        assert owner.cleanup()


@pytest.mark.parametrize("kind", [StopIteration, StopAsyncIteration, GeneratorExit, SystemExit, KeyboardInterrupt, RuntimeError])
@pytest.mark.parametrize("secondary", [False, True])
def test_retry_lifecycle_preserves_exact_cleanup_failure(tmp_path, monkeypatch, kind, secondary):
    """Transport cleanup failures separately from successful generator completion."""
    from topsailai.hooks.script_runner import _StorageCustody

    class Primary(kind):
        """Reject overridable traceback dispatch for every failure category."""
        def with_traceback(self, tb):
            """Fail if the runner dispatches through this override."""
            raise AssertionError("dynamic traceback dispatch")

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = Primary("exact cleanup failure")
    primary.add_note("caller note")
    native = runner._lock
    armed = []

    class Lock:
        """Inject finalizer failure only after releasing the exact native lock."""
        def __enter__(self):
            """Acquire the test-owned exclusion."""
            native.acquire()
            return self

        def __exit__(self, kind, error, tb):
            """Release exclusion before the optional bounded secondary."""
            native.release()
            if secondary and armed:
                armed.clear()
                raise KeyboardInterrupt("finalizer secondary")

    def cleanup(storage, alias):
        """Raise the accurate primary from the actual storage boundary."""
        armed.append(True)
        raise primary

    try:
        runner._lock = Lock()
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert primary.__cause__ is None and primary.__context__ is None
        assert primary.__notes__[0] == "caller note"
        assert len(primary.__notes__) <= 2
        assert custody.retry_owner is None
        assert native.acquire(False)
        native.release()
    finally:
        runner._lock = native
        print("Deleting exact lifecycle regression storage:", owner.path)
        assert owner.cleanup()


@pytest.mark.parametrize("kind", [StopIteration, StopAsyncIteration, GeneratorExit, SystemExit, KeyboardInterrupt, RuntimeError])
@pytest.mark.parametrize("phase", ["finalizer", "terminal"])
@pytest.mark.parametrize("cleanup_primary", [False, True])
@pytest.mark.parametrize("hostile", [False, True])
def test_retry_exit_origin_preserves_exact_failure(tmp_path, monkeypatch, kind, phase, cleanup_primary, hostile):
    """Preserve exit-origin failures even when a normal completion is already pending."""
    import inspect
    import sys
    from topsailai.hooks.script_runner import _StorageCustody

    calls = []

    class ExitFailure(kind):
        """Reject dynamic traceback dispatch and malformed public observation."""
        def with_traceback(self, tb):
            """Fail if an overridable method is used for lifecycle transport."""
            calls.append(tb)
            raise AssertionError("dynamic exit traceback dispatch")

        def __getattribute__(self, name):
            """Expose a malformed observation without modifying the native traceback."""
            if name == "__traceback__":
                return object()
            return super().__getattribute__(name)

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    secondary = (ExitFailure if hostile else kind)("exact exit failure")
    original = SystemExit("exact cleanup primary") if cleanup_primary else secondary
    original.add_note("caller exit note")
    native = runner._lock
    armed = []
    old_trace = sys.gettrace()
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._retry_cleanup_invocation)
    terminal_line = first + next(index for index, line in enumerate(source)
                                if "terminal_state = object.__getattribute__" in line)

    class Lock:
        """Inject only after releasing the exact native exclusion."""
        def __enter__(self):
            """Acquire the test's native lock."""
            native.acquire()
            return self

        def __exit__(self, kind, error, tb):
            """Hand back exclusion before the finalizer-origin failure."""
            native.release()
            if phase == "finalizer" and armed:
                armed.clear()
                raise secondary

    def trace(frame, event, arg):
        """Raise once inside terminal recovery without altering authority state."""
        if (phase == "terminal" and event == "line" and armed
                and frame.f_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__
                and frame.f_lineno == terminal_line):
            armed.clear()
            raise secondary
        return trace

    def cleanup(storage, alias):
        """Arm exit injection and optionally establish cleanup precedence."""
        armed.append(True)
        if cleanup_primary:
            raise original
        return False

    try:
        runner._lock = Lock()
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        sys.settrace(trace)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(old_trace)
        assert caught.value is original
        expected_source = "cleanup" if cleanup_primary else ("trace" if phase == "terminal" else "__exit__")
        assert any(frame.name == expected_source for frame in caught.traceback)
        assert not calls
        assert original.__cause__ is None and original.__context__ is None
        assert original.__notes__[0] == "caller exit note"
        assert len(original.__notes__) == (2 if cleanup_primary else 1)
        assert custody.retry_owner is None
        assert native.acquire(False)
        native.release()
    finally:
        sys.settrace(old_trace)
        runner._lock = native
        print("Deleting exact exit-origin regression storage:", owner.path)
        assert owner.cleanup()


def test_captured_primary_survives_failure_carrier_handoff(tmp_path, monkeypatch):
    """A genuine handoff interruption must not replace the captured cleanup primary."""
    import inspect
    import sys
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("accurate cleanup source")
    secondary = KeyboardInterrupt("failure carrier handoff")
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._retry_cleanup_invocation)
    target = first + next(i for i, line in enumerate(source)
                          if "return _RetryFailure(primary, primary_traceback)" in line)
    hits = []

    def cleanup(storage, alias):
        """Establish the exact main failure through the public storage boundary."""
        raise primary

    def trace(frame, event, arg):
        """Interrupt once without modifying private state or frame locals."""
        if (frame.f_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__
                and event == "line" and frame.f_lineno == target and not hits):
            hits.append(target)
            raise secondary
        return trace

    previous = sys.gettrace()
    try:
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        sys.settrace(trace)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(previous)
        assert hits == [target]
        assert custody.retry_owner is None
        assert runner._lock.acquire(False)
        runner._lock.release()
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert primary.__cause__ is None and primary.__context__ is None
    finally:
        sys.settrace(previous)
        print("Deleting exact failure-carrier probe storage:", owner.path)
        assert owner.cleanup()


@pytest.mark.parametrize("window", ["carrier", "completion_value", "driver_observation", "driver_rethrow", "recovery_rethrow"])
def test_private_failure_custody_delivery_windows(tmp_path, monkeypatch, window):
    """A genuine handoff interruption must not replace the captured cleanup primary."""
    import inspect
    import sys
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("accurate cleanup source")
    secondary = KeyboardInterrupt("failure carrier handoff")
    function = (OwnedHookScriptRunner._retry_cleanup_invocation
                if window in ("carrier", "capture_publication") else OwnedHookScriptRunner.retry_cleanup)
    marker = {"capture_publication": "failure_custody[0] = (invocation, primary, primary_traceback)",
              "recovery_rethrow": "prepared = BaseException.with_traceback(evidence[1], evidence[2])",
              "carrier": "return _RetryFailure(primary, primary_traceback)",
              "completion_value": "outcome = completed.value",
              "driver_observation": "evidence = failure_custody[0]",
              "driver_rethrow": "prepared = BaseException.with_traceback(evidence[1], evidence[2])"}[window]
    source, first = inspect.getsourcelines(function)
    matches = [first + i for i, line in enumerate(source) if marker in line]
    target = matches[-1] if window == "recovery_rethrow" else matches[0]
    hits = []
    captured = []

    def cleanup(storage, alias):
        """Establish the exact main failure through the public storage boundary."""
        captured.append(True)
        raise primary

    preparatory_hits = []

    def trace(frame, event, arg):
        """Interrupt once without modifying private state or frame locals."""
        if (window == "recovery_rethrow" and frame.f_code is function.__code__
                and event == "line" and frame.f_lineno == matches[0] and not preparatory_hits):
            preparatory_hits.append(True)
            raise secondary
        if (frame.f_code is function.__code__
                and event == "line" and frame.f_lineno == target and not hits
                and (window != "driver_observation" or captured)):
            hits.append(target)
            raise secondary
        return trace

    previous = sys.gettrace()
    try:
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        if window == "recovery_rethrow":
            import topsailai.hooks.script_runner as module
            original_note = module._note_retry_interruption

            def rearm_note(*args):
                """Rearm the one-shot tracer only for the second recovery boundary."""
                original_note(*args)
                sys.settrace(trace)
                sys._getframe(1).f_trace = trace

            monkeypatch.setattr(module, "_note_retry_interruption", rearm_note)
        sys.settrace(trace)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(previous)
        assert hits == [target]
        assert custody.retry_owner is None
        assert runner._lock.acquire(False)
        runner._lock.release()
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert primary.__cause__ is None and primary.__context__ is None
    finally:
        sys.settrace(previous)
        print("Deleting exact failure-carrier probe storage:", owner.path)
        assert owner.cleanup()



def test_published_primary_survives_interrupted_recovery_bookkeeping(tmp_path, monkeypatch):
    """Retain published primary when a finite second fault interrupts recovery bookkeeping."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("exact published cleanup primary")
    carrier_error = KeyboardInterrupt("carrier interruption")
    diagnostic_error = KeyboardInterrupt("diagnostic interruption")
    bookkeeping_error = KeyboardInterrupt("recovery bookkeeping interruption")
    driver = OwnedHookScriptRunner.retry_cleanup
    source, first = inspect.getsourcelines(driver)
    bookkeeping = [first + i for i, line in enumerate(source)
                   if "evidence = failure_custody[0]" in line][0]
    source, first = inspect.getsourcelines(OwnedHookScriptRunner._retry_cleanup_invocation)
    carrier = first + next(i for i, line in enumerate(source)
                           if "return _RetryFailure(primary, primary_traceback)" in line)
    hits = []
    armed = []
    previous = sys.gettrace()

    def cleanup(storage, alias):
        """Publish the genuine failure through the actual storage boundary."""
        raise primary

    def trace(frame, event, arg):
        """Inject once at each legal intermediate boundary without changing frame state."""
        if event != "line":
            return trace
        if (frame.f_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__
                and frame.f_lineno == carrier and not hits):
            hits.append("carrier")
            raise carrier_error
        if (armed and frame.f_code is driver.__code__ and frame.f_lineno == bookkeeping):
            armed.clear()
            hits.append("bookkeeping")
            raise bookkeeping_error
        return trace

    def interrupted_note(*args):
        """Interrupt diagnostics once and arm a fault at protected custody observation."""
        if "bookkeeping" in hits:
            return
        armed.append(True)
        sys.settrace(trace)
        sys._getframe(1).f_trace = trace
        raise diagnostic_error

    try:
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        monkeypatch.setattr(module, "_note_retry_interruption", interrupted_note)
        sys.settrace(trace)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(previous)
        assert hits == ["carrier", "bookkeeping"]
        assert custody.retry_owner is None
        assert runner._lock.acquire(False)
        runner._lock.release()
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert primary.__cause__ is None and primary.__context__ is None
    finally:
        sys.settrace(previous)
        print("Deleting exact recovery-bookkeeping regression storage:", owner.path)
        assert owner.cleanup()


def test_published_primary_survives_initial_delivery_recovery(tmp_path, monkeypatch):
    """Preserve published cleanup primary across the first interrupted driver handler."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = _StorageCustody(owner)
    custody._write_state(pending=True)
    custody._write_state(storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("exact initial recovery primary")
    carrier_error = KeyboardInterrupt("carrier construction interruption")
    recovery_error = KeyboardInterrupt("initial recovery registration interruption")
    driver = OwnedHookScriptRunner.retry_cleanup
    source, first = inspect.getsourcelines(driver)
    target = first + next(i for i, line in enumerate(source)
                          if "evidence = failure_custody[0]" in line)
    hits = []
    previous = sys.gettrace()

    def cleanup(storage, alias):
        """Capture the genuine source exception through storage cleanup."""
        raise primary

    def trace(frame, event, arg):
        """Interrupt one exact handler line without changing private execution state."""
        if (frame.f_code is driver.__code__ and event == "line"
                and frame.f_lineno == target and hits == ["carrier"]):
            hits.append("initial recovery")
            raise recovery_error
        return trace

    def interrupted_carrier(*args):
        """Arm the legal intermediate interruption before failing carrier construction."""
        hits.append("carrier")
        sys.settrace(trace)
        sys._getframe(1).f_back.f_trace = trace
        raise carrier_error

    try:
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
        monkeypatch.setattr(module, "_RetryFailure", interrupted_carrier)
        with pytest.raises(BaseException) as caught:
            runner.retry_cleanup(debt.debt_id)
        sys.settrace(previous)
        assert hits == ["carrier", "initial recovery"]
        assert custody.retry_owner is None
        assert runner._lock.acquire(False)
        runner._lock.release()
        assert caught.value is primary
        assert any(frame.name == "cleanup" for frame in caught.traceback)
        assert primary.__cause__ is None and primary.__context__ is None
    finally:
        sys.settrace(previous)
        print("Deleting exact initial-recovery regression storage:", owner.path)
        assert owner.cleanup()


@pytest.mark.parametrize("operation", ["acquire", "release"])
@pytest.mark.parametrize("side", ["before", "after"])
def test_production_retry_lock_native_boundary_converges(operation, side):
    """Recover an exact published scope around both native lock transitions."""
    import dis
    import sys
    from topsailai.hooks.script_runner import _RecoverableRunnerLock, _RetryLockScope

    lock = _RecoverableRunnerLock()
    scope = _RetryLockScope(lock, object())
    code = lock._acquire_scope.__func__.__code__ if operation == "acquire" else scope.recover.__func__.__code__
    instructions = list(dis.get_instructions(code))
    method = next(n for n, i in enumerate(instructions)
                  if i.opname in ("LOAD_ATTR", "LOAD_METHOD") and i.argval == operation)
    call = next(n for n in range(method, len(instructions)) if instructions[n].opname == "CALL")
    target = instructions[call if side == "before" else call + 1].offset
    failure = KeyboardInterrupt("native transition")
    hits = []

    def trace(frame, event, arg):
        """Inject once without writing private authority or execution frames."""
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            if event == "opcode" and frame.f_lasti == target and not hits:
                hits.append(target)
                raise failure
        return trace

    if operation == "release":
        scope.__enter__()
    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.__enter__() if operation == "acquire" else scope.recover()
    finally:
        sys.settrace(previous)
        assert scope.recover()
    assert caught.value is failure and hits == [target]
    assert not lock.locked()
    assert lock.acquire(False)
    lock.release()


def test_production_retry_lock_foreign_and_nested_scope_cannot_release():
    """Foreign and rejected nested scopes cannot borrow a live owner's ticket."""
    import threading
    from topsailai.hooks.script_runner import _RecoverableRunnerLock, _RetryLockScope

    lock = _RecoverableRunnerLock()
    entered, finish = threading.Event(), threading.Event()
    observed = []

    # Scope identity must be created in its actual owning thread.
    def actual_owner():
        """Create and expose a real thread-owned scope without mutating its fields."""
        local_scope = _RetryLockScope(lock, object())
        observed.append(local_scope)
        with local_scope:
            entered.set()
            assert finish.wait(5)
            observed.append(lock.locked())

    worker = threading.Thread(target=actual_owner)
    worker.start()
    try:
        assert entered.wait(5)
        exact = observed[0]
        assert exact.recover() is False
        assert lock.acquire(False) is False
        assert lock.locked()
    finally:
        finish.set()
        worker.join(5)
    assert not worker.is_alive() and observed[1] is True
    assert not lock.locked()
    with lock:
        nested = _RetryLockScope(lock, object())
        with pytest.raises(RuntimeError, match="nonrecursive"):
            nested.__enter__()
        assert nested.recover()
        assert lock.locked()
    assert not lock.locked()


@pytest.mark.parametrize("side", ["before", "after"])
def test_production_retry_lock_finite_repeated_release_retains_ticket(side):
    """A retained scope converges after multiple finite native release interruptions."""
    import dis
    import sys
    from topsailai.hooks.script_runner import _RecoverableRunnerLock, _RetryLockScope

    lock = _RecoverableRunnerLock()
    scope = _RetryLockScope(lock, object())
    scope.__enter__()
    code = scope.recover.__func__.__code__
    instructions = list(dis.get_instructions(code))
    method = next(n for n, i in enumerate(instructions)
                  if i.opname in ("LOAD_ATTR", "LOAD_METHOD") and i.argval == "release")
    call = next(n for n in range(method, len(instructions)) if instructions[n].opname == "CALL")
    target = instructions[call if side == "before" else call + 1].offset
    hits = []
    failures = [KeyboardInterrupt("release first"), SystemExit("release second")]

    def trace(frame, event, arg):
        """Interrupt each separately armed recovery without changing its ticket."""
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            if event == "opcode" and frame.f_lasti == target:
                hits.append(target)
                raise failures[len(hits) - 1]
        return trace

    previous = sys.gettrace()
    try:
        attempts = 2 if side == "before" else 1
        for index in range(attempts):
            sys.settrace(trace)
            with pytest.raises(BaseException) as caught:
                scope.recover()
            sys.settrace(previous)
            assert caught.value is failures[index]
        assert scope.recover()
        assert len(hits) == attempts and not lock.locked()
        with lock:
            assert scope.recover()
            assert lock.locked(), "retired scope released an unrelated later ticket"
    finally:
        sys.settrace(previous)
        scope.recover()
    assert not lock.locked()


def test_production_retry_lock_postrelease_foreign_owner_is_not_released():
    """An unacknowledged native release cannot authorize release of a new owner."""
    import dis
    import sys
    import threading
    from topsailai.hooks.script_runner import _RecoverableRunnerLock, _RetryLockScope

    lock = _RecoverableRunnerLock()
    scope = _RetryLockScope(lock, object())
    scope.__enter__()
    code = scope.recover.__func__.__code__
    instructions = list(dis.get_instructions(code))
    method = next(n for n, i in enumerate(instructions)
                  if i.opname in ("LOAD_ATTR", "LOAD_METHOD") and i.argval == "release")
    call = next(n for n in range(method, len(instructions)) if instructions[n].opname == "CALL")
    target = instructions[call + 1].offset
    ready, finish = threading.Event(), threading.Event()
    observed, hits = [], []
    failure = KeyboardInterrupt("release acknowledgement")

    def foreign():
        """Own native exclusion until exact historical recovery is checked."""
        with lock:
            ready.set()
            assert finish.wait(5)
            observed.append(lock.locked())

    worker = threading.Thread(target=foreign)

    def trace(frame, event, arg):
        """Transfer only after native release then interrupt acknowledgement once."""
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            if event == "opcode" and frame.f_lasti == target and not hits:
                hits.append(target)
                worker.start()
                assert ready.wait(5)
                raise failure
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            scope.recover()
        sys.settrace(previous)
        assert caught.value is failure and hits == [target]
        assert scope.recover()
        assert lock.acquire(False) is False
    finally:
        sys.settrace(previous)
        finish.set()
        if worker.ident is not None:
            worker.join(5)
        scope.recover()
    assert not worker.is_alive() and observed == [True]
    assert not lock.locked()


def test_production_retry_lock_foreign_scope_entry_fails_before_acquisition():
    """Reject a foreign scope before native acquire can create unowned debt."""
    import threading
    from topsailai.hooks.script_runner import _RecoverableRunnerLock, _RetryLockScope

    lock = _RecoverableRunnerLock()
    scope = _RetryLockScope(lock, object())
    failures = []

    def foreign():
        """Attempt an actual foreign-thread entry without changing the scope."""
        try:
            scope.__enter__()
        except RuntimeError as failure:
            failures.append(failure)

    worker = threading.Thread(target=foreign)
    worker.start()
    worker.join(5)
    assert not worker.is_alive() and len(failures) == 1
    assert not lock.locked()
    with scope:
        assert lock.locked()
    assert not lock.locked()


@pytest.mark.parametrize("surface", ["registry", "receipt", "custody", "attribute", "lease", "proof"])
def test_authority_compatibility_raw_bypass_is_rejected(tmp_path, surface):
    """Reject native compatibility writes without changing exact active authority."""
    from topsailai.hooks.script_runner import _StorageCustody

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    custody = _StorageCustody(owner)
    token = object()
    custody._write_retry_owner(token)
    custody._write_state(execution_lease=(token,))
    receipt = (custody, token, object())
    custody._write_handback(receipt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._write_retry_receipts(((id(custody), receipt),))
    operations = {
        "registry": lambda: dict.__setitem__(runner._prelaunch_storage, id(owner), object()),
        "receipt": lambda: dict.__setitem__(runner._retry_receipts, id(custody), tuple(list(receipt))),
        "custody": lambda: dict.__setitem__(custody.__dict__, "retry_owner", None),
        "attribute": lambda: object.__setattr__(custody, "retry_owner", None),
        "lease": lambda: list.__setitem__(custody.execution_lease, 0, None),
        "proof": lambda: object.__setattr__(custody, "retry_handback", tuple(list(receipt))),
    }
    with pytest.raises((TypeError, AttributeError)):
        operations[surface]()
    assert runner._prelaunch_storage[id(owner)] is custody
    assert runner._retry_receipts[id(custody)] is receipt
    assert custody.retry_owner is token
    assert custody.execution_lease[0] is token
    assert custody.retry_handback is receipt


@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_exact_snapshot_transition(tmp_path, authority):
    """Reject stale snapshots and preserve detached exact receipt identities."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    initial = getattr(runner, projection)
    receipt = (object(), object(), object())
    assert getattr(runner, transition_name)(initial, ((1, receipt),))
    published = getattr(runner, projection)
    assert published[1] is receipt and dict(initial) == {}
    assert not getattr(runner, transition_name)(initial, ((1, object()),))
    assert getattr(runner, projection) is published
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(runner, projection, {})
    assert getattr(runner, transition_name)(published, retire=(1,))
    assert dict(getattr(runner, projection)) == {} and published[1] is receipt


@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_concurrent_expected_snapshot(tmp_path, authority):
    """Permit at most one concurrent writer for one exact immutable snapshot."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    expected = getattr(runner, projection)
    ready = threading.Barrier(3)
    outcomes = []

    def publish(identity):
        """Race legal transitions without sharing mutable canonical containers."""
        ready.wait()
        outcomes.append(getattr(runner, transition_name)(expected, ((identity, identity),)))

    workers = [threading.Thread(target=publish, args=(identity,)) for identity in (1, 2)]
    for worker in workers:
        worker.start()
    ready.wait()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()
    assert sorted(outcomes) == [False, True]
    assert len(getattr(runner, projection)) == 1 and dict(expected) == {}


@pytest.mark.parametrize("phase", ["acquire", "before_commit", "after_commit"])
@pytest.mark.parametrize("retirement", [False, True])
@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_interrupted_transition_converges(tmp_path, monkeypatch, phase, retirement, authority):
    """Keep exact immutable authority and lock responsibility across finite interruptions."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    import inspect
    import sys
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    receipt = (object(), object(), object())
    if retirement:
        getattr(runner, write_name)(((1, receipt),))
    expected = getattr(runner, projection)
    changes = () if retirement else ((1, receipt),)
    retire = (1,) if retirement else ()
    failure = KeyboardInterrupt("exact receipt transition interruption")
    hits = []
    previous = sys.gettrace()
    acquire = module._RecoverableRunnerLock._acquire_scope
    source, first = inspect.getsourcelines(module._private_mapping_authority)
    marker = "snapshot = types.MappingProxyType(replacement)" if phase == "before_commit" else "return True"
    target = first + next(i for i, line in enumerate(source) if marker in line)

    def interrupted_acquire(lock, scope, blocking=True, timeout=-1):
        """Interrupt after the native acquisition while exact responsibility remains armed."""
        result = acquire(lock, scope, blocking, timeout)
        if not hits:
            hits.append(phase)
            raise failure
        return result

    def trace(frame, event, arg):
        """Inject only at the selected production line without altering closure state."""
        if (event == "line" and frame.f_code.co_name == "transition"
                and frame.f_code.co_filename == module.__file__
                and frame.f_lineno == target and not hits):
            hits.append(phase)
            raise failure
        return trace

    try:
        if phase == "acquire":
            monkeypatch.setattr(module._RecoverableRunnerLock, "_acquire_scope", interrupted_acquire)
        else:
            sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            getattr(runner, transition_name)(expected, changes, retire)
        sys.settrace(previous)
        assert hits == [phase] and caught.value is failure
        current = getattr(runner, projection)
        if phase == "after_commit":
            assert current is not expected
            assert not getattr(runner, transition_name)(expected, changes, retire)
        else:
            assert current is expected
        assert dict(expected) == ({1: receipt} if retirement else {})
        assert getattr(runner, transition_name)(current, changes, retire)
        assert dict(getattr(runner, projection)) == ({} if retirement else {1: receipt})
        assert failure.__cause__ is None and failure.__context__ is None
    finally:
        sys.settrace(previous)


@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_foreign_and_copied_snapshots(tmp_path, authority):
    """Reject foreign and equal copied evidence without minting publication authority."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    other = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    expected = getattr(runner, projection)
    for foreign in (getattr(other, projection), dict(expected), None, (), object()):
        assert not getattr(runner, transition_name)(foreign, ((1, object()),))
        assert getattr(runner, projection) is expected
    assert getattr(runner, transition_name)(expected, ((1, object()),))


@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_finite_repeated_acquire_interruption(tmp_path, monkeypatch, authority):
    """Recover the exact scope after each bounded interruption and eventually publish."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    original = module._RecoverableRunnerLock._acquire_scope
    failures = [KeyboardInterrupt("receipt acquire " + str(i)) for i in range(3)]
    remaining = list(failures)
    expected = getattr(runner, projection)
    receipt = (object(), object(), object())

    def acquire(lock, scope, blocking=True, timeout=-1):
        """Consume a finite interruption after native ownership becomes observable."""
        result = original(lock, scope, blocking, timeout)
        if remaining:
            raise remaining.pop(0)
        return result

    monkeypatch.setattr(module._RecoverableRunnerLock, "_acquire_scope", acquire)
    for failure in failures:
        with pytest.raises(KeyboardInterrupt) as caught:
            getattr(runner, transition_name)(expected, ((1, receipt),))
        assert caught.value is failure and getattr(runner, projection) is expected
    assert getattr(runner, transition_name)(expected, ((1, receipt),))
    assert getattr(runner, projection)[1] is receipt


@pytest.mark.parametrize("after_release", [False, True])
@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_receipt_authority_native_release_interruption(tmp_path, monkeypatch, after_release, authority):
    """Retain exact scope through one interrupted native release and converge safely."""
    projection = "_" + authority
    transition_name = "_transition_" + authority
    write_name = "_write_" + authority
    import topsailai.hooks.script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    expected = getattr(runner, projection)
    receipt = (object(), object(), object())
    original = module._RetryLockScope.recover
    failure = SystemExit("exact receipt release interruption")
    hits = []

    def recover(scope):
        """Interrupt once before or after release without changing ticket ownership."""
        if hits:
            return original(scope)
        hits.append(after_release)
        if after_release:
            original(scope)
        raise failure

    monkeypatch.setattr(module._RetryLockScope, "recover", recover)
    with pytest.raises(SystemExit) as caught:
        getattr(runner, transition_name)(expected, ((1, receipt),))
    assert caught.value is failure and hits == [after_release]
    published = getattr(runner, projection)
    assert published is not expected and published[1] is receipt
    assert getattr(runner, transition_name)(published, retire=(1,))
    assert getattr(runner, projection) == {}
    assert failure.__cause__ is None and failure.__context__ is None


@pytest.mark.parametrize("replacement", [None, object(), (), (object(), object(), object())])
def test_handback_authority_exact_snapshot_and_raw_shadow(tmp_path, replacement):
    """Reject stale proof writers and ignore forged compatibility dictionary shadows."""
    from topsailai.hooks.script_runner import _StorageCustody

    custody = _StorageCustody(TemporaryStorageOwner(tmp_path))
    initial = custody._observe_handback()
    proof = (custody, object(), object())
    custody._write_handback(proof)
    published = custody._observe_handback()
    assert custody.retry_handback is proof and initial["proof"] is None
    assert not custody._transition_handback(initial, (("proof", replacement),))
    assert custody._observe_handback() is published
    with pytest.raises(TypeError):
        custody.__dict__["retry_handback"] = replacement
    assert custody.retry_handback is proof
    with pytest.raises(AttributeError):
        object.__setattr__(custody, "retry_handback", replacement)
    with pytest.raises(TypeError):
        dict.__setitem__(published, "proof", replacement)
    assert custody.retry_handback is proof
    custody._write_handback(None)
    assert custody.retry_handback is None and published["proof"] is proof


@pytest.mark.parametrize("phase", ["acquire", "before_commit", "after_commit", "release_before", "release_after"])
def test_handback_authority_interruption_converges(tmp_path, monkeypatch, phase):
    """Preserve committed proof identity and exact release responsibility at writer boundaries."""
    import inspect
    import sys
    import topsailai.hooks.script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    expected = custody._observe_handback()
    proof = (custody, object(), object())
    failure = KeyboardInterrupt("proof writer " + phase)
    hits = []
    previous = sys.gettrace()
    acquire = module._RecoverableRunnerLock._acquire_scope
    recover = module._RetryLockScope.recover
    source, first = inspect.getsourcelines(module._private_mapping_authority)
    target = first + next(i for i, line in enumerate(source)
                          if ("snapshot = types.MappingProxyType(replacement)" if phase == "before_commit"
                              else "return True") in line)

    def interrupted_acquire(lock, scope, blocking=True, timeout=-1):
        """Interrupt once after the exact native acquire without changing its ticket."""
        result = acquire(lock, scope, blocking, timeout)
        if not hits:
            hits.append(phase)
            raise failure
        return result

    def interrupted_recover(scope):
        """Keep a single release interruption bounded and preserve native ownership."""
        if hits:
            return recover(scope)
        hits.append(phase)
        if phase == "release_after":
            recover(scope)
        raise failure

    def trace(frame, event, arg):
        """Target only the production writer line without accessing closure cells."""
        if (event == "line" and frame.f_code.co_name == "transition"
                and frame.f_code.co_filename == module.__file__
                and frame.f_lineno == target and not hits):
            hits.append(phase)
            raise failure
        return trace

    try:
        if phase == "acquire":
            monkeypatch.setattr(module._RecoverableRunnerLock, "_acquire_scope", interrupted_acquire)
        elif phase.startswith("release"):
            monkeypatch.setattr(module._RetryLockScope, "recover", interrupted_recover)
        else:
            sys.settrace(trace)
        with pytest.raises(KeyboardInterrupt) as caught:
            custody._transition_handback(expected, (("proof", proof),))
        sys.settrace(previous)
        assert caught.value is failure and hits == [phase]
        current = custody._observe_handback()
        if phase in ("after_commit", "release_before", "release_after"):
            assert current is not expected and custody.retry_handback is proof
            assert not custody._transition_handback(expected, (("proof", None),))
        else:
            assert current is expected and custody.retry_handback is None
        assert custody._transition_handback(current, (("proof", None),))
        assert custody.retry_handback is None
        assert failure.__cause__ is None and failure.__context__ is None
    finally:
        sys.settrace(previous)


def test_handback_authority_concurrent_foreign_and_copied_snapshots(tmp_path):
    """Allow one exact concurrent writer and reject copied or transplanted snapshot evidence."""
    from topsailai.hooks.script_runner import _StorageCustody

    custody = _StorageCustody(TemporaryStorageOwner(tmp_path))
    other = _StorageCustody(TemporaryStorageOwner(tmp_path))
    expected = custody._observe_handback()
    for foreign in (other._observe_handback(), dict(expected), None, (), object()):
        assert not custody._transition_handback(foreign, (("proof", object()),))
        assert custody._observe_handback() is expected
    barrier = threading.Barrier(3)
    results = []
    proofs = [(custody, object(), object()), (custody, object(), object())]

    def write(proof):
        """Race controlled writers without replacing capability or closure state."""
        barrier.wait()
        results.append((proof, custody._transition_handback(expected, (("proof", proof),))))

    workers = [threading.Thread(target=write, args=(proof,)) for proof in proofs]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()
    assert sum(success for proof, success in results) == 1
    winner = next(proof for proof, success in results if success)
    assert custody.retry_handback is winner
    assert other.retry_handback is None and expected["proof"] is None


@pytest.mark.parametrize("attack", ["attribute", "shadow", "accessor"])
def test_retry_token_private_authority_compatibility_isolation(tmp_path, attack):
    """Reject attribute writes and ignore compatibility shadows or accessor substitutions."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    token = object()
    custody._write_retry_owner(token)
    if attack == "attribute":
        with pytest.raises(AttributeError):
            object.__setattr__(custody, "retry_owner", None)
    elif attack == "shadow":
        with pytest.raises(TypeError):
            dict.__setitem__(custody.__dict__, "retry_owner", None)
    else:
        with pytest.raises(AttributeError):
            custody._observe_retry_owner = lambda: {"token": None}
        with pytest.raises(AttributeError):
            custody._transition_retry_owner = lambda *args: True
    assert custody.retry_owner is token
    custody._write_retry_owner(None)
    assert custody.retry_owner is None


@pytest.mark.parametrize("expected_kind", ["stale", "copied", "foreign", "malformed"])
def test_retry_token_transition_requires_exact_snapshot(tmp_path, expected_kind):
    """Fail closed on lookalike snapshots while preserving exact immutable token identity."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    initial = module._observe_retry_owner(custody)
    token = object()
    custody._write_retry_owner(token)
    current = module._observe_retry_owner(custody)
    foreign = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    expected = {"stale": initial, "copied": dict(current),
                "foreign": module._observe_retry_owner(foreign), "malformed": None}[expected_kind]
    assert not module._transition_retry_owner(custody, expected, (("token", None),))
    assert module._observe_retry_owner(custody) is current
    assert custody.retry_owner is token and initial["token"] is None
    assert module._transition_retry_owner(custody, current, (("token", None),))
    assert custody.retry_owner is None and current["token"] is token


def test_retry_token_authority_does_not_retain_retired_custody(tmp_path):
    """Allow custody collection after token retirement without authority-table ownership leaks."""
    import gc
    import weakref
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    custody._write_retry_owner(object())
    custody._write_retry_owner(None)
    reference = weakref.ref(custody)
    del custody
    gc.collect()
    assert reference() is None


@pytest.mark.parametrize("kind", ["unhashable", "hostile", "equal"])
def test_retry_token_authority_uses_referent_identity_not_hooks(tmp_path, kind):
    """Keep exact and unrelated token authorities isolated from custody equality/hash hooks."""
    from topsailai.hooks import script_runner as module

    class Custody(module._StorageCustody):
        """Provide hostile identity lookalikes without changing the trusted writer seam."""
        def __eq__(self, other):
            """Equality must never be invoked by authority lookup or retirement."""
            if kind == "hostile":
                raise AssertionError("authority invoked equality")
            return True

        def __hash__(self):
            """Hashing must never be invoked by authority lookup or retirement."""
            if kind == "hostile":
                raise AssertionError("authority invoked hashing")
            return 1

    if kind == "unhashable":
        Custody.__hash__ = None
    first = Custody(TemporaryStorageOwner(tmp_path))
    second = Custody(TemporaryStorageOwner(tmp_path))
    token = object()
    first._write_retry_owner(token)
    assert first.retry_owner is token and second.retry_owner is None
    assert not module._transition_retry_owner(second, module._observe_retry_owner(first), (("token", token),))
    second._write_retry_owner(object())
    assert first.retry_owner is token
    first._write_retry_owner(None)
    assert second.retry_owner is not None



def test_retry_token_authority_concurrent_exact_snapshot(tmp_path):
    """Allow only one competing writer for the same exact token snapshot."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    expected = module._observe_retry_owner(custody)
    barrier = threading.Barrier(3)
    outcomes = []
    failures = []

    def writer(token):
        """Compete through the production transition without sharing mutable authority."""
        try:
            barrier.wait()
            outcomes.append((token, module._transition_retry_owner(custody, expected, (("token", token),))))
        except BaseException as failure:
            failures.append(failure)

    threads = [threading.Thread(target=writer, args=(object(),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads) and not failures
    winners = [token for token, accepted in outcomes if accepted]
    assert len(winners) == 1 and custody.retry_owner is winners[0]
    custody._write_retry_owner(None)


def test_retry_token_authority_repeated_acquire_interruption(tmp_path, monkeypatch):
    """Preserve exact token state and scope responsibility across finite repeated acquire faults."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    expected = module._observe_retry_owner(custody)
    original = module._RecoverableRunnerLock._acquire_scope
    failures = [KeyboardInterrupt("token acquire " + str(i)) for i in range(3)]
    remaining = list(failures)
    token = object()

    def acquire(lock, scope, blocking=True, timeout=-1):
        """Interrupt only after native acquisition and consume each fault before recovery."""
        result = original(lock, scope, blocking, timeout)
        if remaining:
            raise remaining.pop(0)
        return result

    monkeypatch.setattr(module._RecoverableRunnerLock, "_acquire_scope", acquire)
    for failure in failures:
        with pytest.raises(KeyboardInterrupt) as caught:
            module._transition_retry_owner(custody, expected, (("token", token),))
        assert caught.value is failure
        assert module._observe_retry_owner(custody) is expected and custody.retry_owner is None
        assert failure.__cause__ is None and failure.__context__ is None
    assert module._transition_retry_owner(custody, expected, (("token", token),))
    assert custody.retry_owner is token
    custody._write_retry_owner(None)


@pytest.mark.parametrize("field", ["pending", "owner", "execution_lease", "_observe_handback", "_transition_handback"])
def test_custody_private_snapshot_raw_accessor_rejection(tmp_path, field):
    """Reject native attributes and dictionary attacks without canonical changes."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    before = module._observe_retry_owner(custody)
    with pytest.raises(AttributeError):
        object.__setattr__(custody, field, object())
    with pytest.raises(TypeError):
        dict.__setitem__(custody.__dict__, field, object())
    assert module._observe_retry_owner(custody) is before


def test_custody_deep_lease_detachment_and_exact_snapshot(tmp_path):
    """Detach nested native containers and reject stale or transplanted writes."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    other = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    token = object()
    nested = [token, {"nested": [None]}]
    custody._write_state(execution_lease=nested)
    snapshot = module._observe_retry_owner(custody)
    lease = custody.execution_lease
    nested[0] = None
    nested[1]["nested"][0] = token
    assert lease[0] is token and lease[1]["nested"] == (None,)
    with pytest.raises(TypeError):
        lease[1]["nested"] = ()
    with pytest.raises(TypeError):
        list.__setitem__(lease, 0, None)
    assert not module._transition_retry_owner(other, snapshot, (("pending", True),))
    custody._write_state(execution_lease=(None,))
    assert not module._transition_retry_owner(custody, snapshot, (("pending", True),))
    assert snapshot["execution_lease"] is lease
    assert module._execution_lease_inactive(custody)


@pytest.mark.parametrize("shape", ["cycle", "mapping-cycle", "depth", "budget"])
def test_custody_lease_invalid_graph_preserves_snapshot(tmp_path, shape):
    """Reject excessive or cyclic native graphs before canonical state can change."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    before = module._observe_retry_owner(custody)
    value = []
    if shape == "cycle":
        value.append(value)
    elif shape == "mapping-cycle":
        value = {}
        value["self"] = value
    elif shape == "depth":
        for _ in range(34):
            value = [value]
    else:
        value = [None] * 4096
    with pytest.raises(ValueError):
        custody._write_state(execution_lease=value)
    assert module._observe_retry_owner(custody) is before
    assert module._execution_lease_inactive(custody)


@pytest.mark.parametrize("shape", ["self", "linked"])
def test_retired_proof_authority_releases_exact_custody(tmp_path, shape):
    """Retire proof-bearing custody without retaining its self or linked authority graph."""
    import gc
    import weakref
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    neighbor = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    neighbor_token = object()
    neighbor._write_retry_owner(neighbor_token)
    peer = module._StorageCustody(TemporaryStorageOwner(tmp_path)) if shape == "linked" else custody
    custody._write_handback((peer, object(), object()))
    if peer is not custody:
        peer._write_handback((custody, object(), object()))
        runner._write_prelaunch_storage(((id(peer.owner), peer),))
    runner._write_prelaunch_storage(((id(custody.owner), custody),))
    references = (weakref.ref(custody), weakref.ref(peer))
    runner._forget_storage(custody.owner)
    if peer is not custody:
        runner._forget_storage(peer.owner)
    assert not runner._prelaunch_storage
    del custody, peer
    gc.collect()
    assert all(reference() is None for reference in references)
    assert neighbor.retry_owner is neighbor_token
    expected = module._observe_retry_owner(neighbor)
    assert module._transition_retry_owner(neighbor, expected, (("token", None),))


def test_custody_authority_unknown_and_duplicate_identity_rejection(tmp_path):
    """Reject unknown fields and duplicate or absent exact custody registration."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    before = module._observe_retry_owner(custody)
    with pytest.raises(AttributeError, match="unknown_authority"):
        getattr(custody, "unknown_authority")
    with pytest.raises(RuntimeError, match="already initialized"):
        module._initialize_retry_owner(custody)
    with pytest.raises(RuntimeError, match="no exact custody"):
        module._observe_retry_owner(object())
    assert module._observe_retry_owner(custody) is before


@pytest.mark.parametrize("writer", ["state", "token", "receipt", "registry"])
def test_controlled_writer_rejection_preserves_authority(tmp_path, monkeypatch, writer):
    """Surface denied transitions without silently mutating any canonical snapshot."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    before = module._observe_retry_owner(custody)
    receipts, registry = runner._retry_receipts, runner._prelaunch_storage

    def deny(*args, **kwargs):
        """Model rejection at the trusted controlled-writer seam only."""
        return False

    if writer in ("state", "token"):
        monkeypatch.setattr(module, "_transition_retry_owner", deny)
        operation = (lambda: custody._write_state(pending=True)) if writer == "state" else (lambda: custody._write_retry_owner(object()))
    else:
        seam = "_transition_retry_receipts" if writer == "receipt" else "_transition_prelaunch_storage"
        original = getattr(OwnedHookScriptRunner, seam)

        def denied(selected):
            """Deny only this exact runner through the trusted class-level test seam."""
            return deny if selected is runner else original.__get__(selected, type(selected))

        monkeypatch.setattr(OwnedHookScriptRunner, seam, property(denied))
        operation = runner._write_retry_receipts if writer == "receipt" else runner._write_prelaunch_storage
    with pytest.raises(RuntimeError, match="lost exact snapshot authority"):
        operation()
    assert module._observe_retry_owner(custody) is before
    assert runner._retry_receipts is receipts and runner._prelaunch_storage is registry


def test_retry_lock_nonblocking_competition_and_foreign_release():
    """Clear failed acquire tickets and deny foreign release of a live exact owner."""
    from topsailai.hooks import script_runner as module

    lock = module._RecoverableRunnerLock()
    scope = module._RetryLockScope(lock, object())
    outcomes = []
    with scope:
        def compete():
            """Exercise native contention without inheriting the owner's thread ticket."""
            assert not lock.acquire(False)
            assert getattr(lock._local, "ticket", None) is None
            with pytest.raises(RuntimeError, match="no exact owner"):
                lock.release()
            assert not scope.recover()
            outcomes.append(True)
        worker = threading.Thread(target=compete)
        worker.start()
        worker.join(5)
        assert not worker.is_alive() and outcomes == [True] and lock.locked()
    assert not lock.locked()


@pytest.mark.parametrize("mode", ["yield", "carrier", "malformed", "foreign-scope"])
def test_retry_outer_failure_delivery_rejects_invalid_invocation(tmp_path, monkeypatch, mode):
    """Fail closed at the outer delivery boundary without accepting foreign custody evidence."""
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))

    def invocation(debt_id, failure_custody, lock_custody):
        """Model malformed outcomes at the protected invocation interface only."""
        driver = yield
        if mode == "malformed":
            failure_custody[0] = (object(), RuntimeError("foreign"), None)
            return False
        if mode == "foreign-scope":
            scope = module._RetryLockScope(runner._lock, driver)
            lock_custody[0] = scope

            def reject_once(current):
                """Withdraw the injection before rejecting the one exact recovery attempt."""
                lock_custody[0] = None
                return False

            monkeypatch.setattr(module._RetryLockScope, "recover", reject_once)
            failure_custody[0] = (object(), RuntimeError("foreign"), None)
            return False
        if mode == "carrier":
            return module._RetryFailure(RuntimeError("unregistered"), None)
        yield object()

    monkeypatch.setattr(runner, "_retry_cleanup_invocation", invocation)
    with pytest.raises(RuntimeError, match="retry (invocation yielded unexpectedly|failure has no exact invocation custody)"):
        runner.retry_cleanup("outer-invalid")
    assert not runner._lock.locked()


def test_custody_deep_lease_set_projection(tmp_path):
    """Detach native sets into immutable members without losing exact token identities."""
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    token = object()
    value = {token}
    custody._write_state(execution_lease=[value])
    value.clear()
    assert custody.execution_lease == (frozenset({token}),)


def test_retry_lock_nested_native_depth_denies_scope_exit():
    """Reject depth mismatch without releasing an inner acquisition as an outer ticket."""
    from topsailai.hooks import script_runner as module

    lock = module._RecoverableRunnerLock()
    scope = module._RetryLockScope(lock, object())
    scope.__enter__()
    lock._native.acquire()
    try:
        assert not scope.recover()
        with pytest.raises(RuntimeError, match="no exact owner"):
            scope.__exit__(None, None, None)
        assert lock._native._recursion_count() == 2
        assert lock._local.ticket is scope
    finally:
        lock._native.release()
        assert scope.recover()
    assert not lock.locked()


def test_retry_native_acquire_error_recovers_ticket():
    """Remove exact preacquisition responsibility after native parameter rejection."""
    from topsailai.hooks import script_runner as module

    lock = module._RecoverableRunnerLock()
    with pytest.raises(ValueError):
        lock.acquire(False, 1)
    assert getattr(lock._local, "ticket", None) is None and not lock.locked()
    assert lock.acquire(False)
    lock.release()


def test_retry_settled_proof_retirement_releases_receipt_and_custody(tmp_path):
    """Retire the real published retry proof after exact token withdrawal and collection."""
    import gc
    import weakref
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = module._StorageCustody(owner)
    custody._write_state(pending=True, storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    reference = weakref.ref(custody)
    assert runner.retry_cleanup(debt.debt_id)
    assert custody.retry_owner is None and custody.retry_handback is None
    assert not runner._prelaunch_storage and not runner._retry_receipts
    del custody
    gc.collect()
    assert reference() is None
    assert runner.retry_cleanup(debt.debt_id)


def test_retry_failure_delivery_finite_repeated_interruptions(tmp_path, monkeypatch):
    """Deliver one captured primary after finite repeated recover faults without graph cycles."""
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    primary = SystemExit("registered cleanup primary")
    faults = [KeyboardInterrupt("delivery " + str(index)) for index in range(3)]
    remaining = list(faults)
    frames = []

    def invocation(debt_id, failure_custody, lock_custody):
        """Register native captured evidence before exposing fallible delivery recovery."""
        driver = yield
        scope = module._RetryLockScope(runner._lock, driver)
        lock_custody[0] = scope
        try:
            raise primary
        except BaseException as captured:
            traceback = BaseException.__traceback__.__get__(captured)
            frames.append(traceback)
            failure_custody[0] = (driver, captured, traceback)
        return False

    recover = module._RetryLockScope.recover

    def interrupt(scope):
        """Consume each finite fault before raising so later reentry can converge."""
        if remaining:
            raise remaining.pop(0)
        return recover(scope)

    monkeypatch.setattr(runner, "_retry_cleanup_invocation", invocation)
    monkeypatch.setattr(module._RetryLockScope, "recover", interrupt)
    with pytest.raises(SystemExit) as caught:
        runner.retry_cleanup("finite-delivery")
    assert caught.value is primary and not remaining
    traceback = BaseException.__traceback__.__get__(primary)
    while traceback is not None and traceback is not frames[0]:
        traceback = traceback.tb_next
    assert traceback is frames[0]
    assert primary.__cause__ is None and primary.__context__ is None
    assert len([note for note in primary.__notes__ if "failure delivery" in note]) == 1
    assert not runner._lock.locked()


@pytest.mark.parametrize("after_release", [False, True])
@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_authority_inner_outer_finite_release_converges(tmp_path, monkeypatch, after_release, authority):
    """Prove distinct inner and outer finite release faults retain one exact scope."""
    import sys
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    projection = "_" + authority
    transition = getattr(runner, "_transition_" + authority)
    expected = getattr(runner, projection)
    receipt = (object(), object(), object())
    recover = module._RetryLockScope.recover
    faults = {"transition": [KeyboardInterrupt("inner first"), SystemExit("inner second")],
              "controlled_transition": [GeneratorExit("outer first"), KeyboardInterrupt("outer second")]}
    remaining = {name: list(values) for name, values in faults.items()}
    scopes = []
    callers = []

    def interrupted(scope):
        """Route faults by the actual caller, never by a guessed invocation count."""
        caller = sys._getframe(2).f_code.co_name
        if caller in remaining and remaining[caller]:
            scopes.append(scope)
            callers.append(caller)
            fault = remaining[caller].pop(0)
            if after_release:
                recover(scope)
            raise fault
        return recover(scope)

    monkeypatch.setattr(module._RetryLockScope, "recover", interrupted)
    try:
        with pytest.raises(GeneratorExit) as caught:
            transition(expected, ((1, receipt),))
        assert caught.value is faults["controlled_transition"][0]
        assert all(not values for values in remaining.values())
        assert callers == ["transition", "transition", "controlled_transition", "controlled_transition"]
        assert len(scopes) == 4 and all(scope is scopes[0] for scope in scopes)
        assert scopes[0].lock._local.ticket is None
        assert not scopes[0].lock.locked()
        current = getattr(runner, projection)
        assert current is not expected and current[1] is receipt
        assert transition(current, retire=(1,)), "finite exit faults stranded the old exact scope"
        assert not getattr(runner, projection)
    finally:
        monkeypatch.setattr(module._RetryLockScope, "recover", recover)
        for scope in scopes:
            assert recover(scope)


@pytest.mark.parametrize("authority", ["retry_receipts", "prelaunch_storage"])
def test_authority_native_finally_return_gap_outer_recovery(tmp_path, monkeypatch, authority):
    """Observe actual inner RETURN_VALUE and prove outer recovery after each finite gap."""
    import dis
    import sys
    import types
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    transition = getattr(runner, "_transition_" + authority)
    projection = "_" + authority
    code = next(item for item in module._private_mapping_authority.__code__.co_consts
                if isinstance(item, types.CodeType) and item.co_name == "transition")
    targets = {item.offset for item in dis.get_instructions(code)
               if item.opname in ("RETURN_VALUE", "RETURN_CONST")}
    assert targets, "native-finally return instruction was not identified"
    recover = module._RetryLockScope.recover
    scopes = []
    callers = []
    hits = []
    previous = sys.gettrace()
    active = [None]

    def observe(scope):
        """Record exact responsibility at each real inner or outer finish entry."""
        callers.append(sys._getframe(2).f_code.co_name)
        scopes.append(scope)
        return recover(scope)

    def trace(frame, event, arg):
        """Inject at the native-finally return opcode without editing trusted state."""
        if frame.f_code is code:
            frame.f_trace_opcodes = True
            if event == "opcode" and frame.f_lasti in targets and active[0] is not None:
                failure = active[0]
                active[0] = None
                hits.append((frame.f_lasti, frame.f_back.f_code.co_name))
                raise failure
            return trace
        if previous is not None:
            return previous(frame, event, arg)
        return trace

    monkeypatch.setattr(module._RetryLockScope, "recover", observe)
    try:
        for index in range(3):
            failure = KeyboardInterrupt("native-finally gap " + str(index))
            active[0] = failure
            start = len(callers)
            expected = getattr(runner, projection)
            receipt = (object(), object(), object())
            sys.settrace(trace)
            try:
                with pytest.raises(KeyboardInterrupt) as caught:
                    transition(expected, ((index, receipt),))
            finally:
                sys.settrace(previous)
            assert caught.value is failure and active[0] is None
            assert callers[start:] == ["transition", "controlled_transition"]
            assert scopes[-1] is scopes[-2]
            assert scopes[-1].lock._local.ticket is None and not scopes[-1].lock.locked()
            assert getattr(runner, projection)[index] is receipt
            assert caught.value.__cause__ is None and caught.value.__context__ is None
            traceback = caught.value.__traceback__
            origins = []
            while traceback is not None:
                origins.append(traceback.tb_frame.f_code)
                traceback = traceback.tb_next
            assert code in origins
        assert len(hits) == 3 and all(caller == "controlled_transition" for _, caller in hits)
        assert transition(getattr(runner, projection), retire=(0, 1, 2))
        assert not getattr(runner, projection)
    finally:
        sys.settrace(previous)
        monkeypatch.setattr(module._RetryLockScope, "recover", recover)
        for scope in scopes:
            assert recover(scope)


@pytest.mark.parametrize("cleanup_primary", [False, True])
@pytest.mark.parametrize("journal", [False, True])
def test_terminal_handback_repeated_fault_preserves_exact_authority(tmp_path, monkeypatch, cleanup_primary, journal):
    """Preserve captured primary and exact token across finite disarm and terminal faults."""
    from topsailai.hooks import script_runner as module

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    debt = owner.cleanup_debts()[0]
    custody = module._StorageCustody(owner)
    custody._write_state(pending=True, storage_alias=debt)
    runner._write_prelaunch_storage(((id(owner), custody),))
    runner._storage[debt.debt_id] = owner
    primary = SystemExit("cleanup primary")
    faults = [KeyboardInterrupt("ordinary disarm"), RuntimeError("fallback disarm"),
              GeneratorExit("terminal handback")]
    remaining = list(faults)
    commit = module._commit_retry_owner
    retry = TemporaryStorageOwner.retry_cleanup
    journal_state = [None] if journal else None
    lock_state = [None]

    def cleanup(storage, alias):
        """Establish the requested real cleanup origin without changing custody authority."""
        if cleanup_primary:
            raise primary
        return False

    def interrupted(selected, token):
        """Consume finite exact-custody withdrawal faults before allowing recovery."""
        if selected is custody and token is None and remaining:
            raise remaining.pop(0)
        return commit(selected, token)

    invocation = runner._retry_cleanup_invocation(debt.debt_id, journal_state, lock_state)
    next(invocation)
    monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", cleanup)
    monkeypatch.setattr(module, "_commit_retry_owner", interrupted)
    try:
        with pytest.raises(StopIteration) as completed:
            invocation.send(invocation)
        result = completed.value.value
        assert type(result) is module._RetryFailure and not remaining
        expected = primary if cleanup_primary else faults[1]
        assert result.primary is expected
        assert result.traceback is BaseException.__traceback__.__get__(expected)
        assert custody.retry_owner is not None
        assert not runner._lock.locked()
        seen = set()
        current = expected
        while current is not None:
            assert id(current) not in seen
            seen.add(id(current))
            current = current.__context__
        with pytest.raises(BaseException) as delivered:
            raise BaseException.with_traceback(result.primary, result.traceback) from None
        assert delivered.value is expected and expected.__cause__ is None
        if journal:
            assert journal_state[0][0] is invocation and journal_state[0][1] is expected
        if cleanup_primary:
            assert len(expected.__notes__) == 2
        monkeypatch.setattr(module, "_commit_retry_owner", commit)
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", retry)
        assert runner.retry_cleanup(debt.debt_id)
        assert custody.retry_owner is None and not runner._prelaunch_storage
    finally:
        monkeypatch.setattr(module, "_commit_retry_owner", commit)
        monkeypatch.setattr(TemporaryStorageOwner, "retry_cleanup", retry)
        invocation.close()
        if owner._path is not None:
            print("Deleting exact terminal handback regression storage:", owner.path)
            assert owner.cleanup()


@pytest.mark.parametrize("surface", ["prelaunch_storage", "retry_receipts"])
@pytest.mark.parametrize("accessor", ["observe", "transition"])
def test_runner_authority_accessors_reject_native_replacement(tmp_path, surface, accessor):
    """Native attribute and dict shadows cannot replace exact canonical observation or writer."""
    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    name = "_" + accessor + "_" + surface
    projection = "_" + surface
    expected = getattr(runner, projection)
    original = getattr(runner, name)
    forged = lambda *args: False
    with pytest.raises(AttributeError):
        object.__setattr__(runner, name, forged)
    dict.__setitem__(runner.__dict__, name, forged)
    assert getattr(runner, name) is original
    assert getattr(runner, projection) is expected
    transition = getattr(runner, "_transition_" + surface)
    receipt = (object(), object(), object())
    assert transition(expected, ((1, receipt),))
    assert getattr(runner, projection)[1] is receipt
    assert transition(getattr(runner, projection), retire=(1,))


@pytest.mark.parametrize("hostile", [False, True])
def test_runner_authority_exact_identity_and_retirement(tmp_path, hostile):
    """Retire exact runner authority without equality hooks or neighbor authority loss."""
    import gc
    import weakref
    from topsailai.hooks import script_runner as module

    class Runner(OwnedHookScriptRunner):
        """Represent equal or hostile lookalikes outside trusted identity storage."""
        def __eq__(self, other):
            """Authority lookup must never call equality."""
            if hostile:
                raise AssertionError("runner authority invoked equality")
            return True

        __hash__ = None

    runner = Runner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    neighbor = Runner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    receipt = (object(), object(), object())
    neighbor._write_retry_receipts(((1, receipt),))
    runner._write_prelaunch_storage(((1, object()),))
    with pytest.raises(RuntimeError, match="already initialized"):
        module._initialize_runner_authority(runner)
    with pytest.raises(RuntimeError, match="no exact owner"):
        module._access_runner_authority(object(), False)
    assert neighbor._retry_receipts[1] is receipt
    runner._write_prelaunch_storage(retire=(1,))
    reference = weakref.ref(runner)
    del runner
    gc.collect()
    assert reference() is None
    assert neighbor._retry_receipts[1] is receipt
    assert neighbor._transition_retry_receipts(neighbor._retry_receipts, retire=(1,))


@pytest.mark.parametrize("cycle", [False, True])
def test_custody_mapping_proxy_lease_detaches_or_rejects_cycle(tmp_path, cycle):
    """A read-only native wrapper must not retain mutable backing lease authority."""
    from types import MappingProxyType
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    before = module._observe_retry_owner(custody)
    child = [None]
    backing = {"child": child}
    proxy = MappingProxyType(backing)
    if cycle:
        child.append(proxy)
        with pytest.raises(ValueError, match="cycle"):
            custody._write_state(execution_lease=(proxy,))
        assert module._observe_retry_owner(custody) is before
        return
    custody._write_state(execution_lease=(proxy,))
    published = module._observe_retry_owner(custody)
    lease = custody.execution_lease
    token = object()
    child[0] = token
    backing["child"] = [token]
    assert module._observe_retry_owner(custody) is published
    assert lease[0] is not proxy
    assert lease[0]["child"] == (None,)
    with pytest.raises(TypeError):
        lease[0]["child"] = ()


def test_custody_mapping_proxy_backing_replacement_is_detached(tmp_path):
    """Even immutable child values cannot authorize sharing a mutable backing mapping."""
    from types import MappingProxyType
    from topsailai.hooks import script_runner as module

    custody = module._StorageCustody(TemporaryStorageOwner(tmp_path))
    token = object()
    backing = {"token": token}
    proxy = MappingProxyType(backing)
    custody._write_state(execution_lease=(proxy,))
    snapshot = module._observe_retry_owner(custody)
    backing["token"] = None
    assert custody.execution_lease[0] is not proxy
    assert custody.execution_lease[0]["token"] is token
    assert module._observe_retry_owner(custody) is snapshot
