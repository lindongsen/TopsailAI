"""Bounded discovery policy, inventory, deadline, and cancellation gates."""

from __future__ import annotations

import inspect
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import topsailai.hooks as hooks
import topsailai.hooks.module_discovery as discovery
import topsailai.hooks.module_discovery_policy as policy_module
from topsailai.hooks.module_discovery_policy import DiscoveryBudget, ModuleDiscoveryPolicy
from topsailai.hooks.process_state import WorkerResult
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    private_temp_root,
    write_module,
)


class _Clock:
    """Provide a deterministic monotonic clock for aggregate-budget tests."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _ClosedIterator:
    """Track incremental consumption and explicit close behavior."""

    def __init__(self, values: list[Path]) -> None:
        self.values = iter(values)
        self.next_calls = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self) -> Path:
        self.next_calls += 1
        return next(self.values)

    def close(self) -> None:
        self.closed = True


def _discover(folder: Path, **kwargs: object):
    """Discover one fixture tree with an explicit private host root."""
    return discovery.build_module_manifest(
        folder,
        "hook_conversation_started",
        temp_root=str(private_temp_root(folder)),
        **kwargs,
    )


def test_policy_public_identity_signature_defaults_and_immutability(tmp_path: Path) -> None:
    """The compatible keyword-only API exports one exact immutable policy type."""
    signature = inspect.signature(discovery.build_module_manifest)
    assert signature.parameters["temp_root"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["policy"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["cancellation"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["policy"].default == ModuleDiscoveryPolicy()
    assert signature.parameters["cancellation"].default is None
    assert hooks.ModuleDiscoveryPolicy is ModuleDiscoveryPolicy
    assert "ModuleDiscoveryPolicy" in hooks.__all__
    policy = ModuleDiscoveryPolicy()
    assert (policy.timeout_ms, policy.max_scanned_entries, policy.max_candidates) == (
        10_000,
        4_096,
        1_024,
    )
    assert hasattr(ModuleDiscoveryPolicy, "__slots__")
    with pytest.raises(FrozenInstanceError):
        policy.timeout_ms = 1
    with pytest.raises(TypeError):
        ModuleDiscoveryPolicy(unknown=1)
    with pytest.raises(TypeError):
        discovery.build_module_manifest(tmp_path, "x", "positional")


@pytest.mark.parametrize(
    ("policy", "accepted"),
    [
        (ModuleDiscoveryPolicy(1, 1, 1), True),
        (ModuleDiscoveryPolicy(600_000, 65_536, 4_096), True),
        (ModuleDiscoveryPolicy(0, 1, 1), False),
        (ModuleDiscoveryPolicy(600_001, 1, 1), False),
        (ModuleDiscoveryPolicy(1, 0, 1), False),
        (ModuleDiscoveryPolicy(1, 65_537, 1), False),
        (ModuleDiscoveryPolicy(1, 1, 0), False),
        (ModuleDiscoveryPolicy(1, 4_096, 4_097), False),
        (ModuleDiscoveryPolicy(1, 1, 2), False),
        (ModuleDiscoveryPolicy(True, 1, 1), False),
        (ModuleDiscoveryPolicy(1.0, 1, 1), False),
        (ModuleDiscoveryPolicy("1", 1, 1), False),
        (ModuleDiscoveryPolicy(None, 1, 1), False),
    ],
)
def test_policy_validation_boundaries(
    tmp_path: Path, policy: ModuleDiscoveryPolicy, accepted: bool
) -> None:
    """Policy validation is exact, bounded, and rejects before filesystem access."""
    result = _discover(tmp_path, policy=policy)
    if accepted:
        assert result.accepted
    else:
        assert result.errors == ("invalid discovery policy",)


def test_policy_exact_type_and_cancellation_validation_precede_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed public controls reject without touching the source path."""
    touched = False

    def touch_root(value: object) -> None:
        nonlocal touched
        touched = True
        raise AssertionError

    monkeypatch.setattr(discovery, "_canonical_root", touch_root)

    class DerivedPolicy(ModuleDiscoveryPolicy):
        pass

    for value in (None, {}, DerivedPolicy()):
        assert _discover(tmp_path, policy=value).errors == ("invalid discovery policy",)
    assert _discover(tmp_path, cancellation=object()).errors == (
        "invalid discovery cancellation",
    )
    assert not touched


def test_scan_limit_counts_non_candidates_and_closes_after_one_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every yielded child counts and the first extra child ends the scan."""
    values = [tmp_path / name for name in ("note.txt", ".hidden.py", "third.txt", "fourth.txt")]
    iterator = _ClosedIterator(values)
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)

    result = _discover(
        tmp_path,
        policy=ModuleDiscoveryPolicy(max_scanned_entries=2, max_candidates=2),
    )

    assert result.errors == ("module discovery scanned entry limit exceeded",)
    assert iterator.next_calls == 3
    assert iterator.closed


def test_candidate_limit_precedes_resolution_of_overflow_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the bounded admitted candidate inventory is resolved and retained."""
    write_module(tmp_path, "first")
    write_module(tmp_path, "second")
    yielded = [tmp_path / "first.py", tmp_path / "second.py"]
    monkeypatch.setattr(discovery, "_list_children", lambda root: iter(yielded))
    resolved: list[Path] = []
    original = discovery._resolve_candidate

    def record(candidate: Path) -> Path:
        resolved.append(candidate)
        return original(candidate)

    monkeypatch.setattr(discovery, "_resolve_candidate", record)
    result = _discover(
        tmp_path,
        policy=ModuleDiscoveryPolicy(max_scanned_entries=2, max_candidates=1),
    )

    assert result.errors == ("module discovery candidate limit exceeded",)
    assert resolved == [yielded[0]]
    assert result.entries == ()


def test_pre_set_cancellation_latches_before_root_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-set event rejects before source resolution and cannot be revived."""
    event = threading.Event()
    event.set()
    monkeypatch.setattr(
        discovery,
        "_canonical_root",
        lambda value: (_ for _ in ()).throw(AssertionError("root touched")),
    )
    result = _discover(tmp_path, cancellation=event)
    event.clear()
    assert result.errors == ("module discovery cancelled",)


def test_budget_latches_cancellation_and_uses_floor_and_equality() -> None:
    """The internal budget uses one absolute deadline and floor milliseconds."""
    clock = _Clock(10.0)
    event = threading.Event()
    budget = DiscoveryBudget(1_001, event, clock)
    assert budget.deadline == pytest.approx(11.001)
    clock.now = 10.0011
    assert budget.remaining_ms() == 999
    event.set()
    assert budget.rejection() == "module discovery cancelled"
    event.clear()
    assert budget.rejection() == "module discovery cancelled"

    second = DiscoveryBudget(1_000, None, clock)
    clock.now = second.deadline
    assert second.rejection() == "module discovery timeout"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unsupported_backend", "module discovery unsupported blocking io"),
        ("timeout", "module discovery timeout"),
    ],
)
def test_probe_classification_is_preserved_before_load_error_collapse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: str,
) -> None:
    """Aggregate timeout and unsupported backend remain terminal classifications."""
    write_module(tmp_path, "candidate")

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            return WorkerResult(status)

        def cleanup_debts(self) -> tuple[object, ...]:
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=100))
    assert not result.accepted
    assert result.errors == (expected,)
    assert len(result.entries) == 1


def test_per_probe_timeout_remains_load_error_and_successor_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixed 5000 ms probe ceiling is not mistaken for aggregate expiry."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    calls: list[tuple[str, int]] = []

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            calls.append((context.event.payload["logical_name"], timeout_ms))
            return WorkerResult("timeout") if len(calls) == 1 else WorkerResult(
                "success", {"load_status": "ready", "entry_valid": True}
            )

        def cleanup_debts(self) -> tuple[object, ...]:
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=10_000))
    assert result.accepted
    assert calls == [("alpha", 5_000), ("beta", 5_000)]
    assert [entry.load_status for entry in result.entries] == ["load_error", "ready"]


def test_probe_handler_patch_reaches_backend_with_explicit_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module-local handler seam and explicit timeout reach backend execution."""
    captured: list[tuple[str, int]] = []

    class Backend:
        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            captured.append((handler_ref, timeout_ms))
            return WorkerResult("success", {"load_status": "ready", "entry_valid": True})

    handler = "tests.module_discovery.sentinel"
    monkeypatch.setattr(discovery, "_PROBE_HANDLER", handler)
    discovery._probe_candidate(
        Backend(),
        tmp_path,
        "hook_conversation_started",
        "candidate",
        tmp_path / "candidate.py",
        137,
    )

    assert captured == [(handler, 137)]


def test_delayed_iterator_result_rejects_without_probe_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cooperative host I/O rejects a result returned after the deadline."""
    clock = _Clock()
    candidate = write_module(tmp_path, "candidate")

    class DelayedIterator(_ClosedIterator):
        def __next__(self) -> Path:
            value = super().__next__()
            clock.now = 1.0
            return value

    iterator = DelayedIterator([candidate])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    monkeypatch.setattr(
        policy_module,
        "make_discovery_budget",
        lambda timeout_ms, cancellation: DiscoveryBudget(timeout_ms, cancellation, clock),
    )
    monkeypatch.setattr(discovery, "make_discovery_budget", policy_module.make_discovery_budget)
    monkeypatch.setattr(
        discovery,
        "_probe_candidate",
        lambda *args: (_ for _ in ()).throw(AssertionError("probe launched")),
    )

    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=1_000))
    assert result.errors == ("module discovery timeout",)
    assert iterator.closed


def test_empty_inventory_validates_storage_without_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid empty scan requires storage admission but no managed backend."""
    monkeypatch.setattr(
        discovery,
        "IsolatedProcessBackend",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("backend created")),
    )
    assert _discover(tmp_path).accepted




def test_empty_inventory_rejects_invalid_storage_root(tmp_path: Path) -> None:
    """An empty scan still rejects an invalid explicit storage root."""
    result = discovery.build_module_manifest(
        tmp_path,
        "hook_conversation_started",
        temp_root=str(tmp_path / "missing-private-root"),
    )
    assert not result.accepted
    assert result.errors == ("invalid discovery temp root",)


@pytest.mark.parametrize("trigger", ["cancellation", "timeout"])
@pytest.mark.parametrize("valid_root", [True, False])
def test_temp_root_validation_rechecks_budget_after_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str, valid_root: bool
) -> None:
    """Validation-time cancellation or timeout wins over root classification."""
    event = threading.Event()
    clock = _Clock()
    original_validate = discovery.validate_temporary_root
    root = private_temp_root(tmp_path) if valid_root else tmp_path / "missing-private-root"

    def validate_then_trigger(temp_root: str, module_root: Path):
        result = original_validate(temp_root, module_root)
        if trigger == "cancellation":
            event.set()
        else:
            clock.now = 1.0
        return result

    monkeypatch.setattr(discovery, "validate_temporary_root", validate_then_trigger)
    monkeypatch.setattr(
        policy_module,
        "make_discovery_budget",
        lambda timeout_ms, cancellation: DiscoveryBudget(timeout_ms, cancellation, clock),
    )
    monkeypatch.setattr(discovery, "make_discovery_budget", policy_module.make_discovery_budget)

    result = discovery.build_module_manifest(
        tmp_path,
        "hook_conversation_started",
        temp_root=str(root),
        policy=ModuleDiscoveryPolicy(timeout_ms=1_000),
        cancellation=event,
    )

    expected = ("module discovery cancelled",) if trigger == "cancellation" else ("module discovery timeout",)
    assert result.errors == expected


def test_iterator_close_error_maps_to_enumeration_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close failure maps to the stable enumeration token after a clean scan."""

    class CloseErrorIterator(_ClosedIterator):
        def close(self) -> None:
            self.closed = True
            raise OSError("close failed")

    iterator = CloseErrorIterator([])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)

    result = _discover(tmp_path)

    assert result.errors == ("module enumeration unavailable",)
    assert iterator.closed


def test_iterator_close_error_preserves_selected_scan_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Iterator close cannot replace the rejection selected by the scan body."""

    class ScanAndCloseErrorIterator(_ClosedIterator):
        def __next__(self) -> Path:
            raise OSError("scan failed")

        def close(self) -> None:
            self.closed = True
            raise OSError("close failed")

    iterator = ScanAndCloseErrorIterator([])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)

    result = _discover(tmp_path)

    assert result.errors == ("module enumeration unavailable",)
    assert iterator.closed


def test_candidate_resolution_error_maps_to_enumeration_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recognized candidate resolution failure rejects the whole inventory."""
    candidate = write_module(tmp_path, "candidate")
    monkeypatch.setattr(discovery, "_list_children", lambda root: iter([candidate]))
    monkeypatch.setattr(
        discovery,
        "_resolve_candidate",
        lambda path: (_ for _ in ()).throw(OSError("resolve failed")),
    )

    result = _discover(tmp_path)

    assert result.errors == ("module enumeration unavailable",)
    assert result.entries == ()


def _budget(clock: _Clock, timeout_ms: int = 1_000, event: threading.Event | None = None) -> DiscoveryBudget:
    """Build one deterministic discovery budget for boundary tests."""
    return DiscoveryBudget(timeout_ms, event, clock)


@pytest.mark.parametrize(("count", "rejected"), [(1, False), (2, False), (3, True)])
def test_raw_scan_cap_minus_one_cap_and_cap_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    rejected: bool,
) -> None:
    """Raw inventory accepts cap-minus-one and cap, then rejects exactly cap-plus-one."""
    values = [tmp_path / f"ignored-{index}.txt" for index in range(count)]
    iterator = _ClosedIterator(values)
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    if rejected:
        with pytest.raises(discovery._DiscoveryRejected) as caught:
            discovery._enumerate_candidates(
                tmp_path,
                policy=ModuleDiscoveryPolicy(1_000, 2, 2),
                budget=_budget(_Clock()),
            )
        assert caught.value.token == "module discovery scanned entry limit exceeded"
        assert iterator.next_calls == 3
    else:
        assert discovery._enumerate_candidates(
            tmp_path,
            policy=ModuleDiscoveryPolicy(1_000, 2, 2),
            budget=_budget(_Clock()),
        ) == []
    assert iterator.closed


@pytest.mark.parametrize(("count", "rejected"), [(1, False), (2, False), (3, True)])
def test_candidate_cap_minus_one_cap_and_cap_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, rejected: bool
) -> None:
    """Candidate inventory stores at most the cap and observes one overflow candidate."""
    values = [write_module(tmp_path, f"candidate_{index}") for index in range(count)]
    iterator = _ClosedIterator(values)
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    if rejected:
        with pytest.raises(discovery._DiscoveryRejected) as caught:
            discovery._enumerate_candidates(
                tmp_path,
                policy=ModuleDiscoveryPolicy(1_000, 3, 2),
                budget=_budget(_Clock()),
            )
        assert caught.value.token == "module discovery candidate limit exceeded"
    else:
        assert len(discovery._enumerate_candidates(
            tmp_path,
            policy=ModuleDiscoveryPolicy(1_000, 3, 2),
            budget=_budget(_Clock()),
        )) == count
    assert iterator.closed


def test_iterator_conversion_deadline_closes_exact_iterator_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup is armed before iterator conversion and its post-create checkpoint."""
    clock = _Clock()

    class DelayedConversion(_ClosedIterator):
        def __iter__(self):
            clock.now = 1.0
            return self

    iterator = DelayedConversion([])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    monkeypatch.setattr(
        policy_module,
        "make_discovery_budget",
        lambda timeout_ms, cancellation: DiscoveryBudget(timeout_ms, cancellation, clock),
    )
    monkeypatch.setattr(discovery, "make_discovery_budget", policy_module.make_discovery_budget)
    monkeypatch.setattr(
        discovery,
        "_probe_candidate",
        lambda *args: (_ for _ in ()).throw(AssertionError("probe launched")),
    )
    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=1_000))
    assert result.errors == ("module discovery timeout",)
    assert iterator.closed


def test_iterator_conversion_interruption_closes_and_preserves_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Iterator conversion interruption closes the source and propagates unchanged."""
    interruption = KeyboardInterrupt("iterator conversion")

    class InterruptingConversion(_ClosedIterator):
        def __iter__(self):
            raise interruption

    iterator = InterruptingConversion([])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    with pytest.raises(KeyboardInterrupt) as caught:
        _discover(tmp_path)
    assert caught.value is interruption
    assert iterator.closed


def test_resolution_deadline_prevents_directory_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late canonical resolution cannot start the following directory probe."""
    clock = _Clock()

    class FakeRoot:
        def resolve(self, *, strict: bool):
            clock.now = 1.0
            return self

        def is_dir(self) -> bool:
            raise AssertionError("directory metadata started")

    monkeypatch.setattr(discovery, "Path", lambda value: FakeRoot())
    with pytest.raises(discovery._DiscoveryRejected) as caught:
        discovery._canonical_root("ignored", _budget(clock))
    assert caught.value.token == "module discovery timeout"


def test_symlink_metadata_deadline_prevents_file_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late symlink check cannot start the following regular-file check."""
    clock = _Clock()

    class FakeChild:
        name = "candidate.py"

        def is_symlink(self) -> bool:
            clock.now = 1.0
            return False

        def is_file(self) -> bool:
            raise AssertionError("file metadata started")

    iterator = _ClosedIterator([FakeChild()])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    with pytest.raises(discovery._DiscoveryRejected) as caught:
        discovery._enumerate_candidates(
            tmp_path,
            policy=ModuleDiscoveryPolicy(1_000, 1, 1),
            budget=_budget(clock),
        )
    assert caught.value.token == "module discovery timeout"
    assert iterator.closed


def test_sub_millisecond_budget_prevents_probe_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A positive sub-millisecond remainder grants no worker execution."""
    write_module(tmp_path, "candidate")
    clock = _Clock()
    created = False

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            nonlocal created
            created = True
            clock.now = 0.9995

        def execute(self, handler_ref: str, context: object, timeout_ms: int):
            raise AssertionError("probe launched")

        def cleanup_debts(self):
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, cancellation: DiscoveryBudget(timeout_ms, cancellation, clock),
    )
    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=1_000))
    assert created
    assert result.errors == ("module discovery timeout",)


def test_probe_receives_same_remaining_budget_and_successor_does_not_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend and HookContext share one decreasing aggregate budget."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    clock = _Clock()
    calls: list[tuple[int, int]] = []

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            clock.now = 0.5004

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            calls.append((timeout_ms, context.remaining_budget_ms))
            clock.now += 1.0
            return WorkerResult("success", {"load_status": "ready", "entry_valid": True})

        def cleanup_debts(self):
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, cancellation: DiscoveryBudget(timeout_ms, cancellation, clock),
    )
    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=4_000))
    assert result.accepted
    assert calls == [(3_499, 3_499), (2_499, 2_499)]
    assert clock.now == 2.5004


def test_cancellation_during_scan_storage_and_probe_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation observed in each active stage prevents acceptance."""
    event = threading.Event()
    candidate = write_module(tmp_path, "candidate")

    class CancellingIterator(_ClosedIterator):
        def __next__(self):
            value = super().__next__()
            event.set()
            return value

    iterator = CancellingIterator([candidate])
    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    assert _discover(tmp_path, cancellation=event).errors == ("module discovery cancelled",)
    assert iterator.closed

    event.clear()
    original_validate = discovery.validate_temporary_root

    def cancel_storage(temp_root: str, root: Path):
        result = original_validate(temp_root, root)
        event.set()
        return result

    monkeypatch.setattr(discovery, "_list_children", lambda root: iter([candidate]))
    monkeypatch.setattr(discovery, "validate_temporary_root", cancel_storage)
    assert _discover(tmp_path, cancellation=event).errors == ("module discovery cancelled",)

    event.clear()
    monkeypatch.setattr(discovery, "validate_temporary_root", original_validate)

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            pass

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            event.set()
            return WorkerResult("worker_lost", error_category="sentinel")

        def cleanup_debts(self):
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    assert _discover(tmp_path, cancellation=event).errors == ("module discovery cancelled",)


def test_final_cleanup_cancellation_prevents_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation first observed during normal final cleanup rejects success."""
    event = threading.Event()
    write_module(tmp_path, "candidate")
    storage_type = discovery.TemporaryStorageOwner
    original_cleanup = storage_type.cleanup

    def cancel_then_cleanup(self) -> bool:
        event.set()
        return original_cleanup(self)

    monkeypatch.setattr(storage_type, "cleanup", cancel_then_cleanup)
    result = _discover(tmp_path, cancellation=event)
    assert result.errors == ("module discovery cancelled",)
    assert not result.accepted
