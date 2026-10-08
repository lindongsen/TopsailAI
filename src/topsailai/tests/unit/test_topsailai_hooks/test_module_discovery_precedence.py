"""Rejection precedence and terminal-completeness gates for bounded discovery."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import topsailai.hooks.module_discovery as discovery
from topsailai.hooks.module_discovery_policy import DiscoveryBudget, ModuleDiscoveryPolicy
from topsailai.hooks.process_state import CleanupDebt, WorkerResult
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    private_temp_root,
    write_module,
)


class _Clock:
    """Provide a deterministic monotonic clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _discover(folder: Path, **kwargs: object):
    """Run discovery with explicit private storage."""
    return discovery.build_module_manifest(
        folder,
        "conversation.started",
        temp_root=str(private_temp_root(folder)),
        **kwargs,
    )


def test_invalid_input_precedes_pre_set_cancellation(tmp_path: Path) -> None:
    """Input validation wins before the first liveness observation."""
    cancellation = threading.Event()
    cancellation.set()

    result = discovery.build_module_manifest(
        tmp_path,
        "",
        temp_root=str(private_temp_root(tmp_path)),
        cancellation=cancellation,
    )

    assert result.errors == ("invalid module configuration",)


@pytest.mark.parametrize(
    ("cancel", "expected"),
    [
        (True, "module discovery cancelled"),
        (False, "module discovery timeout"),
    ],
)
def test_post_error_liveness_precedes_enumeration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    expected: str,
) -> None:
    """Cancellation then deadline supersede an ordinary iterator error."""
    clock = _Clock()
    cancellation = threading.Event()

    class FailingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            if cancel:
                cancellation.set()
            else:
                clock.now = 1.0
            raise OSError("sentinel")

        def close(self) -> None:
            pass

    monkeypatch.setattr(discovery, "_list_children", lambda root: FailingIterator())
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, event: DiscoveryBudget(timeout_ms, event, clock),
    )

    result = _discover(
        tmp_path,
        policy=ModuleDiscoveryPolicy(timeout_ms=1_000),
        cancellation=cancellation,
    )

    assert result.errors == (expected,)


@pytest.mark.parametrize("liveness", ["cancelled", "timeout"])
def test_cleanup_debt_dominates_post_probe_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    liveness: str,
) -> None:
    """Unsettled cleanup wins over simultaneous cancellation or timeout."""
    write_module(tmp_path, "alpha")
    cancellation = threading.Event()
    clock = _Clock()

    class DebtBackend:
        def __init__(self, *, temp_root: str) -> None:
            self.debt = CleanupDebt("debt-1", "process", 123, "sentinel")

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            if liveness == "cancelled":
                cancellation.set()
            else:
                clock.now = 1.0
            return WorkerResult(
                "timeout",
                cleanup_confirmed=False,
                cleanup_debt=self.debt.debt_id,
            )

        def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
            return (self.debt,)

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", DebtBackend)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, event: DiscoveryBudget(timeout_ms, event, clock),
    )

    result = _discover(
        tmp_path,
        policy=ModuleDiscoveryPolicy(timeout_ms=1_000),
        cancellation=cancellation,
    )

    assert not result.accepted
    assert result.errors == ("module discovery cleanup pending",)
    assert len(result.entries) == 1
    assert result.entries[0].load_status == "cleanup_pending"
    assert result.recovery_owner is not None


def test_final_cleanup_deadline_prevents_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expiry first observed during final cleanup rejects provisional success."""
    write_module(tmp_path, "alpha")
    clock = _Clock()
    storage_type = discovery.TemporaryStorageOwner
    original_cleanup = storage_type.cleanup

    def expire_then_cleanup(self) -> bool:
        clock.now = 1.0
        return original_cleanup(self)

    monkeypatch.setattr(storage_type, "cleanup", expire_then_cleanup)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, event: DiscoveryBudget(timeout_ms, event, clock),
    )

    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=1_000))

    assert not result.accepted
    assert result.errors == ("module discovery timeout",)


@pytest.mark.parametrize(
    ("liveness", "expected"),
    [
        ("cancelled", "module discovery cancelled"),
        ("timeout", "module discovery timeout"),
    ],
)
def test_iterator_acquisition_return_liveness_closes_before_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    liveness: str,
    expected: str,
) -> None:
    """Liveness selected as acquisition returns closes the exact source before scanning."""
    clock = _Clock()
    cancellation = threading.Event()

    class AcquiredIterator:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration

        def close(self) -> None:
            self.closed = True

    iterator = AcquiredIterator()

    def acquire(root: Path):
        if liveness == "cancelled":
            cancellation.set()
        else:
            clock.now = 1.0
        return iterator

    monkeypatch.setattr(discovery, "_list_children", acquire)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, event: DiscoveryBudget(timeout_ms, event, clock),
    )
    monkeypatch.setattr(
        discovery,
        "_scan_candidates",
        lambda *args: (_ for _ in ()).throw(AssertionError("scan started")),
    )

    result = _discover(
        tmp_path,
        policy=ModuleDiscoveryPolicy(timeout_ms=1_000),
        cancellation=cancellation,
    )

    assert result.errors == (expected,)
    assert iterator.closed


def test_iterator_acquisition_handoff_interruption_closes_exact_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interruption after acquisition and before conversion retains cleanup ownership."""
    import inspect
    import sys

    interruption = KeyboardInterrupt("iterator acquisition handoff")

    class AcquiredIterator:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration

        def close(self) -> None:
            self.closed = True

    iterator = AcquiredIterator()
    opening = discovery._opening_iterator.__wrapped__
    source_lines, first_line = inspect.getsourcelines(opening)
    conversion_line = next(
        first_line + index
        for index, line in enumerate(source_lines)
        if line.strip() == "iterator = iter(children)"
    )
    previous_trace = sys.gettrace()
    interrupted = False

    def interrupt_before_conversion(frame, event: str, arg):
        nonlocal interrupted
        if (
            not interrupted
            and frame.f_code is opening.__code__
            and event == "line"
            and frame.f_lineno == conversion_line
            and frame.f_locals.get("children") is iterator
        ):
            interrupted = True
            sys.settrace(previous_trace)
            raise interruption
        return interrupt_before_conversion

    monkeypatch.setattr(discovery, "_list_children", lambda root: iterator)
    monkeypatch.setattr(
        discovery,
        "_scan_candidates",
        lambda *args: (_ for _ in ()).throw(AssertionError("scan started")),
    )
    sys.settrace(interrupt_before_conversion)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            discovery._enumerate_candidates(tmp_path)
    finally:
        sys.settrace(previous_trace)

    assert interrupted
    assert caught.value is interruption
    assert iterator.closed


def test_iterator_conversion_error_closes_exact_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ordinary conversion failure closes the acquired source before rejection."""

    class AcquiredSource:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            raise OSError("sentinel")

        def close(self) -> None:
            self.closed = True

    source = AcquiredSource()
    monkeypatch.setattr(discovery, "_list_children", lambda root: source)
    monkeypatch.setattr(
        discovery,
        "_scan_candidates",
        lambda *args: (_ for _ in ()).throw(AssertionError("scan started")),
    )

    result = _discover(tmp_path)

    assert result.errors == ("module enumeration unavailable",)
    assert source.closed

def test_successor_is_not_launched_after_shared_budget_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first probe can exhaust the shared deadline without granting a successor budget."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    clock = _Clock()
    calls: list[tuple[str, int, int]] = []

    class Backend:
        def __init__(self, *, temp_root: str) -> None:
            clock.now = 0.5004

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> WorkerResult:
            calls.append(
                (context.event.payload["logical_name"], timeout_ms, context.remaining_budget_ms)
            )
            clock.now = 3.0
            return WorkerResult(
                "success", {"load_status": "ready", "entry_valid": True}
            )

        def cleanup_debts(self):
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", Backend)
    monkeypatch.setattr(
        discovery,
        "make_discovery_budget",
        lambda timeout_ms, event: DiscoveryBudget(timeout_ms, event, clock),
    )

    result = _discover(tmp_path, policy=ModuleDiscoveryPolicy(timeout_ms=3_000))

    assert result.errors == ("module discovery timeout",)
    assert calls == [("alpha", 2_499, 2_499)]
