"""Regression contracts for module-discovery admission and cleanup ownership."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

import topsailai.hooks.module_discovery as discovery_module
from topsailai.hooks.process_state import CleanupDebt, WorkerResult
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    private_temp_root,
    write_module,
)


class _RecordingBackend:
    """Return controlled worker results while retaining exact cleanup authority."""

    instances: list["_RecordingBackend"] = []
    payload_paths: list[str] = []
    result = WorkerResult("success", {"load_status": "ready", "entry_valid": True})

    def __init__(self, *, temp_root: str) -> None:
        """Record construction for zero-probe assertions."""
        self.temp_root = temp_root
        self.calls: list[str] = []
        self.debts = (
            CleanupDebt("debt-1", "process", 123, "owned cleanup not confirmed"),
        ) if not type(self).result.cleanup_confirmed else ()
        type(self).instances.append(self)

    def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
        """Record one candidate and return the configured result."""
        self.calls.append(context.event.payload["logical_name"])
        type(self).payload_paths.append(context.event.payload["source_path"])
        return type(self).result

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Expose retained cleanup obligations."""
        return self.debts

    def retry_cleanup(self, debt_id: str) -> bool:
        """Resolve only the exact retained debt."""
        if debt_id != "debt-1":
            return False
        self.debts = ()
        return True


def _install_backend(monkeypatch: Any, result: WorkerResult) -> None:
    """Install a fresh controlled backend for one test."""
    _RecordingBackend.instances = []
    _RecordingBackend.payload_paths = []
    _RecordingBackend.result = result
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", _RecordingBackend)


def test_unconfirmed_cleanup_stops_probing_and_retains_recovery_owner(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Unsettled cleanup prevents readiness and all later candidate admission."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    _install_backend(
        monkeypatch,
        WorkerResult(
            "success",
            {"load_status": "ready", "entry_valid": True},
            cleanup_confirmed=False,
            cleanup_debt="debt-1",
        ),
    )

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )

    backend = _RecordingBackend.instances[0]
    assert not result.accepted
    assert result.errors == ("module discovery cleanup pending",)
    assert backend.calls == ["alpha"]
    assert [(entry.logical_name, entry.load_status, entry.entry_valid) for entry in result.entries] == [
        ("alpha", "cleanup_pending", False)
    ]
    assert result.recovery_owner is not None
    assert result.recovery_owner.cleanup_debts()[:1] == backend.debts
    assert result.recovery_owner.retry_cleanup("debt-1")
    assert result.recovery_owner.cleanup_debts() == ()
    assert not result.accepted
    assert result.errors == ("module discovery cleanup pending",)


def test_process_debt_keeps_storage_until_process_settlement(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Invocation storage survives until the exact process debt is settled."""
    write_module(tmp_path, "alpha")
    _install_backend(
        monkeypatch,
        WorkerResult(
            "success",
            {"load_status": "ready", "entry_valid": True},
            cleanup_confirmed=False,
            cleanup_debt="debt-1",
        ),
    )
    host_root = private_temp_root(tmp_path)

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(host_root)
    )

    invocation_directories = tuple(host_root.glob("discovery-*"))
    assert len(invocation_directories) == 1
    assert result.recovery_owner is not None
    assert not result.recovery_owner.retry_cleanup("unknown-debt")
    assert invocation_directories[0].is_dir()
    assert result.recovery_owner.retry_cleanup("debt-1")
    assert result.recovery_owner.cleanup_debts() == ()
    assert not invocation_directories[0].exists()


def test_interruption_propagates_with_exact_recovery_owner(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An interrupted probe exposes its exact cleanup owner without losing identity."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    interruption = KeyboardInterrupt("sentinel")

    class InterruptingBackend(_RecordingBackend):
        """Retain one debt before propagating the controlled host interruption."""

        def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
            """Record the first candidate, retain debt, and propagate interruption."""
            self.calls.append(context.event.payload["logical_name"])
            raise interruption

    InterruptingBackend.instances = []
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", InterruptingBackend)

    caught: BaseException | None = None
    try:
        discovery_module.build_module_manifest(
            tmp_path,
            "hook_conversation_started",
            temp_root=str(private_temp_root(tmp_path)),
        )
    except BaseException as error:
        caught = error

    assert caught is interruption
    backend = InterruptingBackend.instances[0]
    assert backend.calls == ["alpha"]
    owner = discovery_module.get_interruption_recovery_owner(caught)
    assert owner is not None
    assert owner.cleanup_debts()[:1] == backend.debts
    assert owner.retry_cleanup("debt-1")
    assert owner.cleanup_debts() == ()


def test_enumeration_failure_rejects_without_backend_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An unavailable enumeration is not published as an empty manifest."""
    _install_backend(monkeypatch, WorkerResult("success"))

    def fail_enumeration(root: Path) -> tuple[Path, ...]:
        raise OSError("sentinel")

    monkeypatch.setattr(discovery_module, "_list_children", fail_enumeration)

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("module enumeration unavailable",)
    assert _RecordingBackend.instances == []


def test_readable_empty_directory_is_accepted(tmp_path: Path, monkeypatch: Any) -> None:
    """A successfully enumerated empty directory remains a valid empty manifest."""
    _install_backend(monkeypatch, WorkerResult("success"))

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )

    assert result.accepted
    assert result.entries == ()
    assert result.errors == ()
    assert _RecordingBackend.instances == []


def test_resolved_candidate_escape_rejects_without_backend_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A candidate observed outside the canonical root after resolution is rejected."""
    candidate = write_module(tmp_path, "escaped")
    outside = tmp_path.parent / "outside-hook.py"
    outside.write_text("def main():\n    return None\n", encoding="utf-8")
    _install_backend(monkeypatch, WorkerResult("success"))
    original_resolve = discovery_module._resolve_candidate

    def escape_on_resolve(path: Path) -> Path:
        if path == candidate:
            return outside.resolve()
        return original_resolve(path)

    monkeypatch.setattr(discovery_module, "_resolve_candidate", escape_on_resolve)

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("module path escapes configured root",)
    assert _RecordingBackend.instances == []


def test_retry_reports_incomplete_while_another_backend_debt_remains(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Settling one process debt cannot report whole-owner cleanup success."""
    write_module(tmp_path, "alpha")
    host_root = private_temp_root(tmp_path)

    class MultipleDebtBackend(_RecordingBackend):
        def __init__(self, *, temp_root: str) -> None:
            super().__init__(temp_root=temp_root)
            self.debts = (
                CleanupDebt("debt-1", "process", 123, "first"),
                CleanupDebt("debt-2", "process", 124, "second"),
            )

        def retry_cleanup(self, debt_id: str) -> bool:
            if not any(debt.debt_id == debt_id for debt in self.debts):
                return False
            self.debts = tuple(debt for debt in self.debts if debt.debt_id != debt_id)
            return True

    MultipleDebtBackend.instances = []
    MultipleDebtBackend.result = WorkerResult(
        "success",
        {"load_status": "ready", "entry_valid": True},
        cleanup_confirmed=False,
        cleanup_debt="debt-1",
    )
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", MultipleDebtBackend)

    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(host_root)
    )

    assert result.recovery_owner is not None
    assert not result.recovery_owner.retry_cleanup("debt-1")
    assert tuple(debt.debt_id for debt in result.recovery_owner.cleanup_debts()) == (
        "debt-2",
        result.recovery_owner.cleanup_debts()[-1].debt_id,
    )
    assert result.recovery_owner.retry_cleanup("debt-2")
    assert result.recovery_owner.cleanup_debts() == ()
    assert not tuple(host_root.iterdir())


def test_confirmed_create_claim_entry_interruption_preserves_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    """A confirmed creation remains owned when claim entry is interrupted."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("claim entry")

    def interrupt_claim(self, path: Path) -> None:
        raise interruption

    storage_module = __import__(
        "topsailai.hooks.temporary_storage", fromlist=["TemporaryStorageOwner"]
    )
    monkeypatch.setattr(
        storage_module.TemporaryStorageOwner, "_claim_created_path", interrupt_claim
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    assert discovery_module.get_interruption_recovery_owner(interruption) is None
    assert not tuple(host_root.iterdir())


def test_confirmed_create_before_claim_call_interruption_preserves_cleanup(
    tmp_path: Path,
) -> None:
    """A confirmed creation stays owned across the pre-claim line boundary."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("before claim call")
    storage_module = __import__(
        "topsailai.hooks.temporary_storage", fromlist=["TemporaryStorageOwner"]
    )
    allocate = storage_module.TemporaryStorageOwner.allocate
    source_lines, first_line = inspect.getsourcelines(allocate)
    claim_line = next(
        first_line + index
        for index, line in enumerate(source_lines)
        if line.strip() == "self._claim_created_path(path)"
    )
    previous_trace = sys.gettrace()
    interrupted = False

    def interrupt_before_claim(frame, event: str, arg):
        nonlocal interrupted
        if (
            not interrupted
            and frame.f_code is allocate.__code__
            and event == "line"
            and frame.f_lineno == claim_line
            and frame.f_locals.get("creation_returned") is True
        ):
            interrupted = True
            sys.settrace(previous_trace)
            raise interruption
        return interrupt_before_claim

    sys.settrace(interrupt_before_claim)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            discovery_module.build_module_manifest(
                plugins, "hook_conversation_started", temp_root=str(host_root)
            )
    finally:
        sys.settrace(previous_trace)

    assert interrupted
    assert caught.value is interruption
    assert discovery_module.get_interruption_recovery_owner(interruption) is None
    assert not tuple(host_root.iterdir())


def test_owned_probe_session_stops_successors_after_cleanup_debt(tmp_path: Path) -> None:
    """An owned probe session never launches a successor after unresolved cleanup."""
    class SessionBackend(_RecordingBackend):
        """Provide one unresolved probe cleanup debt for the session seam."""

    backend = SessionBackend(temp_root=str(tmp_path))
    storage = type("Storage", (), {
        "cleanup_debts": lambda self: (),
        "retain_cleanup_debt": lambda self: None,
        "cleanup": lambda self: False,
        "retry_cleanup": lambda self, debt_id: False,
    })()
    owner = discovery_module.ModuleCleanupOwner(backend, storage)
    session = discovery_module.ModuleProbeSession(
        tmp_path.resolve(), "hook_conversation_started", backend, storage, owner=owner
    )
    candidate = discovery_module.ModuleCandidate(
        "alpha", (tmp_path / "alpha.py").resolve(), "python_source"
    )
    type(backend).result = WorkerResult(
        "success", {"load_status": "ready", "entry_valid": True}, cleanup_confirmed=False
    )

    session.probe(candidate, captured_path=candidate.source_path)

    assert session.state == "cleanup_pending"
    assert len(backend.calls) == 1
    with pytest.raises(RuntimeError, match="not open"):
        session.probe(candidate, captured_path=candidate.source_path)
    assert len(backend.calls) == 1


def test_owned_probe_session_requires_explicit_captured_path(tmp_path: Path) -> None:
    """The owned seam rejects implicit source-path probing."""
    backend = _RecordingBackend(temp_root=str(tmp_path))
    storage = type("Storage", (), {
        "cleanup_debts": lambda self: (),
        "retain_cleanup_debt": lambda self: None,
        "cleanup": lambda self: True,
        "retry_cleanup": lambda self, debt_id: False,
    })()
    owner = discovery_module.ModuleCleanupOwner(backend, storage)
    session = discovery_module.ModuleProbeSession(
        tmp_path.resolve(), "hook_conversation_started", backend, storage, owner=owner
    )
    candidate = discovery_module.ModuleCandidate(
        "alpha", (tmp_path / "alpha.py").resolve(), "python_source"
    )

    with pytest.raises(TypeError, match="captured_path"):
        session.probe(candidate, captured_path=None)  # type: ignore[arg-type]
    assert backend.calls == []


def test_owned_enumeration_rejects_malformed_policy_before_timeout_read(tmp_path: Path) -> None:
    """Owned enumeration returns the stable policy token for malformed policy input."""
    result = discovery_module.enumerate_module_candidates_owned(
        tmp_path, policy=None  # type: ignore[arg-type]
    )
    assert not result.accepted
    assert result.errors == ("invalid discovery policy",)


def test_direct_session_rejects_successor_after_interrupted_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A host interruption makes the direct session cleanup-pending and non-reentrant."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    interruption = KeyboardInterrupt("probe interrupt")

    class InterruptingBackend(_RecordingBackend):
        def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
            self.calls.append(context.event.payload["logical_name"])
            raise interruption

    InterruptingBackend.instances = []
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", InterruptingBackend)
    session = discovery_module.open_module_probe_session(
        root=tmp_path.resolve(),
        hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path)),
    )
    assert session is not None
    candidates = discovery_module.enumerate_module_candidates_owned(tmp_path).candidates
    with pytest.raises(KeyboardInterrupt) as caught:
        session.probe(candidates[0], captured_path=candidates[0].source_path)
    assert caught.value is interruption
    assert session.state == "cleanup_pending"
    assert discovery_module.get_interruption_recovery_owner(interruption) is session.recovery_owner
    with pytest.raises(RuntimeError):
        session.probe(candidates[1], captured_path=candidates[1].source_path)


def test_direct_session_probe_uses_distinct_captured_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The worker payload contains the supplied captured path, not source_path."""
    write_module(tmp_path, "alpha")
    _install_backend(monkeypatch, WorkerResult("success"))
    captured = tmp_path / "captured-alpha.py"
    captured.write_text("def main():\n    return None\n", encoding="utf-8")
    session = discovery_module.open_module_probe_session(
        root=tmp_path.resolve(),
        hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path)),
    )
    assert session is not None
    candidate = discovery_module.enumerate_module_candidates_owned(tmp_path).candidates[0]
    session.probe(candidate, captured_path=captured)
    backend = _RecordingBackend.instances[0]
    assert _RecordingBackend.payload_paths == [str(captured)]


def test_direct_session_system_exit_attaches_owner_and_blocks_successor(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """SystemExit is preserved while unsettled cleanup blocks later probes."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    interruption = SystemExit("exit interrupt")

    class ExitBackend(_RecordingBackend):
        def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
            self.calls.append(context.event.payload["logical_name"])
            raise interruption

    ExitBackend.instances = []
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", ExitBackend)
    session = discovery_module.open_module_probe_session(
        root=tmp_path.resolve(), hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path)),
    )
    assert session is not None
    candidate = discovery_module.enumerate_module_candidates_owned(tmp_path).candidates[0]
    with pytest.raises(SystemExit) as caught:
        session.probe(candidate, captured_path=candidate.source_path)
    assert caught.value is interruption
    assert discovery_module.get_interruption_recovery_owner(interruption) is session.recovery_owner
    assert session.state == "cleanup_pending"
    with pytest.raises(RuntimeError):
        session.probe(candidate, captured_path=candidate.source_path)


def test_direct_close_interruption_attaches_owner_and_retries(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Close preserves a host interruption and remains retryable."""
    write_module(tmp_path, "alpha")
    _install_backend(monkeypatch, WorkerResult("success"))
    session = discovery_module.open_module_probe_session(
        root=tmp_path.resolve(), hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path)),
    )
    assert session is not None
    storage = session._storage
    session._backend.debts = ()
    interruption = KeyboardInterrupt("close interrupt")
    original_cleanup = storage.cleanup
    calls = 0

    def interrupt_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise interruption
        return original_cleanup()

    monkeypatch.setattr(storage, "cleanup", interrupt_once)
    with pytest.raises(KeyboardInterrupt) as caught:
        session.close()
    assert caught.value is interruption
    assert discovery_module.get_interruption_recovery_owner(interruption) is session.recovery_owner
    assert session.state == "cleanup_pending"
    monkeypatch.setattr(storage, "cleanup", original_cleanup)
    assert session.close()
    assert session.state == "closed"


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, SystemExit))
@pytest.mark.parametrize("cleanup_pending", (False, True))
def test_continuation_preserves_exception_and_exact_owner(
    tmp_path: Path, monkeypatch: Any, interruption_type: type[BaseException], cleanup_pending: bool
) -> None:
    """The ownership-bearing continuation preserves host exceptions and retry authority."""
    host_root = private_temp_root(tmp_path)
    debt = CleanupDebt("handoff-debt", "process", 123, "handoff pending")

    class HandoffBackend:
        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root
            self.debts = (debt,) if cleanup_pending else ()

        def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
            return self.debts

        def retry_cleanup(self, debt_id: str) -> bool:
            if debt_id != debt.debt_id or not self.debts:
                return False
            self.debts = ()
            return True

    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", HandoffBackend)
    storage = discovery_module.TemporaryStorageOwner(host_root)
    owner = discovery_module.ModuleCleanupOwner(None, storage)
    interruption = interruption_type("continuation interruption")
    captured: list[discovery_module.ModuleProbeSession] = []

    def operation(session: discovery_module.ModuleProbeSession) -> object:
        captured.append(session)
        raise interruption

    with pytest.raises(interruption_type) as caught:
        discovery_module._run_with_module_probe_session(
            root=tmp_path.resolve(), hook_name="hook_conversation_started",
            temp_root=str(host_root), owner=owner, operation=operation
        )
    assert caught.value is interruption
    assert captured[0].recovery_owner is owner
    attached = discovery_module.get_interruption_recovery_owner(interruption)
    if cleanup_pending:
        assert attached is owner
        assert attached is captured[0].recovery_owner
        assert attached.retry_cleanup(debt.debt_id)
        assert attached.cleanup_debts() == ()
    else:
        assert attached is None
    assert not tuple(host_root.iterdir())


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, SystemExit))
@pytest.mark.parametrize("cleanup_pending", (False, True))
def test_public_manifest_helper_return_interruption_has_exact_owner(
    tmp_path: Path,
    monkeypatch: Any,
    interruption_type: type[BaseException],
    cleanup_pending: bool,
) -> None:
    """A post-helper interruption retains one exact owner or completes cleanup."""
    write_module(tmp_path, "alpha")
    host_root = private_temp_root(tmp_path)
    interruption = interruption_type("helper return interruption")
    original_helper = discovery_module._run_with_module_probe_session
    original_factory = discovery_module._make_cleanup_owner
    original_build = discovery_module._build_manifest_with_session
    created: list[discovery_module.ModuleCleanupOwner] = []
    captured: list[discovery_module.ModuleProbeSession] = []

    class ReturnBackend:
        instances: list["ReturnBackend"] = []

        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root
            self.debts = (
                (CleanupDebt("return-debt", "process", 123, "pending"),)
                if cleanup_pending else ()
            )
            type(self).instances.append(self)

        def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
            return self.debts

        def retry_cleanup(self, debt_id: str) -> bool:
            if not self.debts or debt_id != self.debts[0].debt_id:
                return False
            self.debts = ()
            return True

    def make_owner(backend: Any, storage: Any) -> discovery_module.ModuleCleanupOwner:
        owner = original_factory(backend, storage)
        created.append(owner)
        return owner

    def build_without_close(session: discovery_module.ModuleProbeSession, **kwargs: Any) -> object:
        captured.append(session)
        return discovery_module.ModuleManifest(True)

    def wrapped(**kwargs: Any) -> object:
        result = original_helper(**kwargs)
        raise interruption

    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", ReturnBackend)
    monkeypatch.setattr(discovery_module, "_make_cleanup_owner", make_owner)
    monkeypatch.setattr(discovery_module, "_build_manifest_with_session", build_without_close)
    monkeypatch.setattr(discovery_module, "_run_with_module_probe_session", wrapped)

    with pytest.raises(interruption_type) as caught:
        discovery_module.build_module_manifest(
            tmp_path, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    assert len(created) == 1
    assert len(captured) == 1
    assert captured[0].recovery_owner is created[0]
    attached = discovery_module.get_interruption_recovery_owner(interruption)
    if cleanup_pending:
        assert attached is created[0]
        debt_id = attached.cleanup_debts()[0].debt_id
        assert attached.retry_cleanup(debt_id)
        assert attached.cleanup_debts() == ()
    else:
        assert attached is None
    assert not tuple(host_root.iterdir())


class _ControlledStorage:
    """Control allocation, debt, and cleanup without filesystem ambiguity."""

    instances: list["_ControlledStorage"] = []
    allocation_result = True
    allocation_debts: tuple[CleanupDebt, ...] = ()
    cleanup_result = True

    def __init__(self, host_root: Path) -> None:
        """Record one storage owner and retain configured obligations."""
        self._path = host_root / "controlled-discovery"
        self._debts = type(self).allocation_debts
        self.cleaned = False
        type(self).instances.append(self)

    @property
    def path(self) -> Path:
        """Return a stable fake invocation path."""
        return self._path

    def allocate(self) -> bool:
        """Return the configured allocation outcome and count the real call."""
        self.allocate_calls = getattr(self, "allocate_calls", 0) + 1
        _SequenceBudget.allocation_seen = True
        return type(self).allocation_result

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Return configured storage debt."""
        return self._debts

    def retain_cleanup_debt(self) -> None:
        """Keep the configured debt unchanged."""

    def cleanup(self) -> bool:
        """Return the configured cleanup outcome."""
        self.cleaned = True
        return type(self).cleanup_result

    def retry_cleanup(self, debt_id: str) -> bool:
        """Settle one exact fake storage debt."""
        if not any(debt.debt_id == debt_id for debt in self._debts):
            return False
        self._debts = ()
        self.cleaned = True
        return True


def _install_controlled_storage(monkeypatch: Any, *, allocated: bool, debts: tuple[CleanupDebt, ...] = ()) -> None:
    """Install a deterministic storage seam for acquisition classification tests."""
    _ControlledStorage.instances = []
    _ControlledStorage.allocation_result = allocated
    _ControlledStorage.allocation_debts = debts
    monkeypatch.setattr(discovery_module, "TemporaryStorageOwner", _ControlledStorage)


class _SequenceBudget:
    """Return stable liveness outcomes at deterministic acquisition boundaries."""

    allocation_seen = False

    def __init__(self, rejection: str) -> None:
        """Delay one rejection until after storage allocation."""
        self._rejection = rejection
        self._checks = 0

    def rejection(self) -> str | None:
        """Allow validation and allocation, then reject the handoff."""
        self._checks += 1
        return self._rejection if type(self).allocation_seen else None

    def remaining_ms(self) -> int:
        """Provide a usable probe budget before the rejection boundary."""
        return 1_000


def _use_sequence_budget(monkeypatch: Any, rejection: str) -> None:
    """Make the public manifest path reject immediately after allocation."""
    _SequenceBudget.allocation_seen = False
    monkeypatch.setattr(
        discovery_module, "make_discovery_budget",
        lambda timeout_ms, cancellation: _SequenceBudget(rejection),
    )


def test_allocation_success_then_cancellation_is_stable_and_clean(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Public manifest reports cancellation after real allocation and cleans storage."""
    write_module(tmp_path, "alpha")
    original_allocate = discovery_module.TemporaryStorageOwner.allocate
    allocated: list[discovery_module.TemporaryStorageOwner] = []

    def allocate(storage: discovery_module.TemporaryStorageOwner) -> bool:
        result = original_allocate(storage)
        assert result
        assert storage.path.exists()
        _SequenceBudget.allocation_seen = True
        allocated.append(storage)
        return result

    monkeypatch.setattr(discovery_module.TemporaryStorageOwner, "allocate", allocate)
    _install_backend(monkeypatch, WorkerResult("success"))
    _use_sequence_budget(monkeypatch, "module discovery cancelled")
    host_root = private_temp_root(tmp_path)
    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(host_root)
    )
    assert not result.accepted
    assert result.errors == ("module discovery cancelled",)
    assert len(allocated) == 1
    assert _RecordingBackend.instances == []
    assert not tuple(host_root.iterdir())


def test_allocation_success_then_timeout_is_stable_and_clean(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Public manifest reports timeout after real allocation and cleans storage."""
    write_module(tmp_path, "alpha")
    original_allocate = discovery_module.TemporaryStorageOwner.allocate
    allocated: list[discovery_module.TemporaryStorageOwner] = []

    def allocate(storage: discovery_module.TemporaryStorageOwner) -> bool:
        result = original_allocate(storage)
        assert result
        assert storage.path.exists()
        _SequenceBudget.allocation_seen = True
        allocated.append(storage)
        return result

    monkeypatch.setattr(discovery_module.TemporaryStorageOwner, "allocate", allocate)
    _install_backend(monkeypatch, WorkerResult("success"))
    _use_sequence_budget(monkeypatch, "module discovery timeout")
    host_root = private_temp_root(tmp_path)
    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(host_root)
    )
    assert not result.accepted
    assert result.errors == ("module discovery timeout",)
    assert len(allocated) == 1
    assert _RecordingBackend.instances == []
    assert not tuple(host_root.iterdir())


def test_allocation_false_classifies_cancellation_without_debt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Public manifest reports cancellation after a false allocation result."""
    write_module(tmp_path, "alpha")
    _install_controlled_storage(monkeypatch, allocated=False)
    _use_sequence_budget(monkeypatch, "module discovery cancelled")
    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )
    assert not result.accepted
    assert result.errors == ("module discovery cancelled",)
    assert _ControlledStorage.instances[0].allocate_calls == 1


def test_allocation_false_classifies_timeout_without_debt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Public manifest reports timeout after a false allocation result."""
    write_module(tmp_path, "alpha")
    _install_controlled_storage(monkeypatch, allocated=False)
    _use_sequence_budget(monkeypatch, "module discovery timeout")
    result = discovery_module.build_module_manifest(
        tmp_path, "hook_conversation_started", temp_root=str(private_temp_root(tmp_path))
    )
    assert not result.accepted
    assert result.errors == ("module discovery timeout",)
    assert _ControlledStorage.instances[0].allocate_calls == 1


def test_allocation_false_retains_exact_owner_and_debt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Failed allocation with debt exposes the exact retryable owner."""
    debt = CleanupDebt("storage-debt", "storage", None, "pending")
    _install_controlled_storage(monkeypatch, allocated=False, debts=(debt,))
    session = discovery_module.open_module_probe_session(
        root=tmp_path, hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path))
    )
    assert session is not None
    assert session.state == "cleanup_pending"
    assert session.recovery_owner.cleanup_debts() == (debt,)
    assert session.recovery_owner.retry_cleanup("storage-debt")


def test_class_result_alone_causes_cleanup_pending_without_backend_debt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The class-level result seam alone controls cleanup-pending admission."""
    _install_backend(
        monkeypatch,
        WorkerResult("success", {"load_status": "ready", "entry_valid": True}, cleanup_confirmed=False),
    )
    backend = _RecordingBackend
    backend.instances = []
    session = discovery_module.open_module_probe_session(
        root=tmp_path, hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path))
    )
    assert session is not None
    session._backend.debts = ()
    path = write_module(tmp_path, "alpha")
    candidate = discovery_module.ModuleCandidate("alpha", path, "python_source")
    _, result = session.probe(candidate, captured_path=path)
    assert not result.cleanup_confirmed
    assert session.state == "cleanup_pending"


def test_direct_close_system_exit_preserves_owner_and_retries(tmp_path: Path, monkeypatch: Any) -> None:
    """Direct close preserves SystemExit, blocks successors, and retries."""
    _install_backend(monkeypatch, WorkerResult("success"))
    session = discovery_module.open_module_probe_session(
        root=tmp_path, hook_name="hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path))
    )
    assert session is not None
    storage = session._storage
    session._backend.debts = ()
    original_cleanup = storage.cleanup
    interruption = SystemExit("close system exit")
    called = False

    def interrupt_once() -> bool:
        nonlocal called
        if not called:
            called = True
            raise interruption
        return original_cleanup()

    monkeypatch.setattr(storage, "cleanup", interrupt_once)
    with pytest.raises(SystemExit) as caught:
        session.close()
    assert caught.value is interruption
    assert session.state == "cleanup_pending"
    assert discovery_module.get_interruption_recovery_owner(interruption) is session.recovery_owner
    monkeypatch.setattr(storage, "cleanup", original_cleanup)
    assert session.close()


def test_deadline_constructor_and_cancellation_latch() -> None:
    """Deadline constructors preserve identity and cancellation remains latched."""
    from topsailai.hooks.module_discovery_policy import (
        DiscoveryBudget, make_discovery_budget_for_deadline,
    )
    import threading

    event = threading.Event()
    clock = lambda: 10.0
    budget = DiscoveryBudget.from_deadline(25.0, event, clock=clock)
    shared = make_discovery_budget_for_deadline(25.0, event)
    assert budget.deadline == 25.0
    assert shared.deadline == 25.0
    event.set()
    assert budget.rejection() == "module discovery cancelled"
    event.clear()
    assert budget.rejection() == "module discovery cancelled"
