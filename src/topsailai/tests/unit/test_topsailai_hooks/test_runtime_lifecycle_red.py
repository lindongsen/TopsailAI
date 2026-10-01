"""RED regressions for unified Hooks runtime lifecycle and admission."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from topsailai.hooks import HookLimits, HookRuntime, HookSettings
from topsailai.hooks.contracts import DeliveryReceipt
from topsailai.tests.unit.test_topsailai_hooks.red_runtime_helpers import (
    BlockingBackend,
    binding,
    definition,
    event,
    runtime_and_scope,
)


def _join_started(thread: threading.Thread) -> None:
    """Join only an owned thread that was started."""
    if thread.ident is not None:
        thread.join(2)


def test_scope_close_discards_backend_success_that_returns_late(tmp_path: Path) -> None:
    """A closed scope must retain and then discard late backend success."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(tmp_path, backend=backend)
    report_box: list[object] = []
    errors: list[BaseException] = []

    def dispatch() -> None:
        """Capture thread failures for propagation in the owner thread."""
        try:
            report_box.append(runtime.dispatch(event(runtime, scope)))
        except BaseException as exc:
            errors.append(exc)

    dispatch_thread = threading.Thread(target=dispatch)
    pending_at_close: tuple[object, ...] = ()
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        dispatch_thread.start()
        assert backend.started.wait(1)
        close_report = scope.close(deadline_ms=50)
        pending_at_close = tuple(runtime._scheduler._work.values())
        backend.release.set()
        _join_started(dispatch_thread)
        diagnostics = runtime.drain_diagnostics(50)
        failures: list[str] = []
        if close_report.closed_scope_ids != (scope.scope_id,):
            failures.append("scope close did not report the closed scope")
        if not pending_at_close:
            failures.append("scope close forgot the still-running delivery")
        if dispatch_thread.is_alive():
            failures.append("dispatch thread did not settle")
        if errors:
            failures.append(f"dispatch thread errors: {errors!r}")
        if not report_box:
            failures.append("dispatch produced no report")
        else:
            outcome = report_box[0].outcomes[0]
            if outcome.status.value != "cancelled" or outcome.error_category != "closed_scope":
                failures.append("late backend success was not discarded as closed_scope")
            if not outcome.started:
                failures.append("late-result outcome forgot that backend execution started")
        if not any(
            record.get("kind") in ("late_result_discarded", "scope_invalidated")
            and record.get("scope_id") == scope.scope_id
            for record in diagnostics
        ):
            failures.append("late-result diagnostic was not published")
        if runtime._scheduler._work:
            failures.append("scheduler ownership did not reach zero after release")
        if any(key[0] == scope.scope_id for key in runtime._scheduler._binding_slots):
            failures.append("scope binding slots remain after settlement")
        if runtime.cleanup_debts():
            failures.append("unexpected cleanup debt remains")
        assert failures == []
    finally:
        backend.release.set()
        _join_started(dispatch_thread)
        runtime.close(deadline_ms=100)
        assert not dispatch_thread.is_alive()


def test_runtime_close_before_scheduler_execution_reports_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime closure before scheduler execution must preserve pre-start fidelity."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(tmp_path, backend=backend)
    original_execute = runtime._scheduler.execute
    boundary_reached = threading.Event()

    def close_before_execute(*args: object, **kwargs: object):
        """Close at the exact dispatcher-to-scheduler boundary, then continue."""
        boundary_reached.set()
        runtime.close(deadline_ms=0)
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(runtime._scheduler, "execute", close_before_execute)
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        report = runtime.dispatch(event(runtime, scope))
        assert boundary_reached.is_set()
        assert backend.calls == 0
        assert report.outcomes[0].status.value == "cancelled"
        assert report.outcomes[0].error_category == "closed_scope"
        assert not report.outcomes[0].started
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_register_and_scope_close_are_one_owner_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real registry boundary must remain inside the runtime owner transaction."""
    runtime, scope = runtime_and_scope(tmp_path)
    sibling = runtime.open_scope()
    mutation_entered = threading.Event()
    release_mutation = threading.Event()
    close_started = threading.Event()
    registration_box: list[object] = []
    thread_errors: list[BaseException] = []
    observation_failures: list[str] = []
    original_register = runtime._registry.register

    def paused_register(*args: object, **kwargs: object):
        """Pause at the real registry mutation while preserving the original call."""
        mutation_entered.set()
        if not release_mutation.wait(2):
            raise TimeoutError("registry mutation release was not signalled")
        return original_register(*args, **kwargs)

    def register() -> None:
        """Capture registration failures without losing cleanup."""
        try:
            registration_box.append(runtime.register(definition(), binding(), scope))
        except BaseException as exc:
            thread_errors.append(exc)

    def close() -> None:
        """Expose entry into the real close operation and capture failures."""
        close_started.set()
        try:
            scope.close()
        except BaseException as exc:
            thread_errors.append(exc)

    monkeypatch.setattr(runtime._registry, "register", paused_register)
    register_thread = threading.Thread(target=register)
    close_thread = threading.Thread(target=close)
    owner_lock_held = False
    close_returned_before_release = False
    residue: tuple[object, ...] = ()
    scope_present = True
    sequence_present = True
    sibling_accepted = False
    try:
        register_thread.start()
        if not mutation_entered.wait(1):
            observation_failures.append("register did not reach registry mutation")
        else:
            owner_lock_held = not runtime._lock.acquire(blocking=False)
            if not owner_lock_held:
                runtime._lock.release()
        close_thread.start()
        if not close_started.wait(1):
            observation_failures.append("close thread did not start")
        else:
            close_thread.join(0.05)
            close_returned_before_release = not close_thread.is_alive()
    except BaseException as exc:
        observation_failures.append(f"race observation failed: {exc!r}")
    finally:
        release_mutation.set()
        _join_started(register_thread)
        _join_started(close_thread)
        try:
            residue = runtime._registry.snapshot(
                scope.scope_id, "test.red", 1
            ).bindings
        except BaseException as exc:
            observation_failures.append(f"registry snapshot failed: {exc!r}")
        try:
            scope_present = scope.scope_id in runtime._scopes
            sequence_present = scope.scope_id in runtime._sequences
        except BaseException as exc:
            observation_failures.append(f"scope snapshot failed: {exc!r}")
        try:
            sibling_accepted = runtime.register(
                definition(), binding("sibling"), sibling
            ).accepted
        except BaseException as exc:
            observation_failures.append(f"sibling control failed: {exc!r}")
        try:
            runtime.close(deadline_ms=100)
        except BaseException as exc:
            observation_failures.append(f"runtime close failed: {exc!r}")

    if thread_errors:
        observation_failures.append(f"thread errors: {thread_errors!r}")
    if not owner_lock_held:
        observation_failures.append("register mutation lacked runtime owner lock")
    if close_returned_before_release:
        observation_failures.append("close crossed the paused owner transaction")
    if register_thread.is_alive() or close_thread.is_alive():
        observation_failures.append("owned thread remained alive")
    if not registration_box or not registration_box[0].accepted:
        observation_failures.append("registration did not complete successfully")
    if residue:
        observation_failures.append("closed-scope registration residue remains")
    if scope_present or sequence_present:
        observation_failures.append("closed-scope runtime state remains")
    if not sibling_accepted:
        observation_failures.append("sibling scope was not usable before runtime close")
    assert observation_failures == []


def test_close_first_rejects_register_and_make_event_without_state_recreation(
    tmp_path: Path,
) -> None:
    """Operations after close must reject without rebuilding scope-owned state."""
    runtime, scope = runtime_and_scope(tmp_path)
    try:
        scope.close()
        generation = runtime._registry.generation
        registration = runtime.register(definition(), binding(), scope)
        assert not registration.accepted
        assert registration.errors == ("scope is not open in this runtime",)
        with pytest.raises(ValueError, match="scope is not open in this runtime"):
            event(runtime, scope)
        assert runtime._registry.generation == generation
        assert scope.scope_id not in runtime._sequences
        assert runtime._registry.snapshot(scope.scope_id, "test.red", 1).bindings == ()
    finally:
        runtime.close(deadline_ms=100)


def _wait_for_reserved(runtime: HookRuntime, items: int, timeout: float = 1.0) -> bool:
    """Wait for an exact queue reservation under the scheduler condition lock."""
    deadline = time.monotonic() + timeout
    with runtime._scheduler._changed:
        return runtime._scheduler._changed.wait_for(
            lambda: runtime._scheduler._queued_items == items,
            max(0.0, deadline - time.monotonic()),
        )


@pytest.mark.parametrize("close_owner", ["scope", "runtime"])
def test_queued_sync_dispatch_close_returns_terminal_report(
    tmp_path: Path, close_owner: str
) -> None:
    """Lifecycle cancellation must not leak Future cancellation through sync dispatch."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(tmp_path, backend=backend, shutdown_timeout_ms=30)
    reports: dict[str, object] = {}
    errors: list[BaseException] = []
    first_event = event(runtime, scope, 11)
    second_event = event(runtime, scope, 12)

    def dispatch(label: str, hook_event: object) -> None:
        """Capture one public synchronous dispatch result or escaped exception."""
        try:
            reports[label] = runtime.dispatch(hook_event)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=dispatch, args=("first", first_event))
    second = threading.Thread(target=dispatch, args=("second", second_event))
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        first.start()
        assert backend.started.wait(1)
        second.start()
        assert _wait_for_reserved(runtime, 1)
        if close_owner == "scope":
            scope.close(deadline_ms=30)
        else:
            runtime.close(deadline_ms=30)
        _join_started(second)
        assert not second.is_alive()
        assert errors == []
        report = reports["second"]
        assert report.outcomes[0].status.value == "cancelled"
        assert report.outcomes[0].error_category == "closed_scope"
        assert not report.outcomes[0].started
        with runtime._scheduler._lock:
            assert runtime._scheduler._queued_items == 0
            assert runtime._scheduler._queued_bytes == 0
            assert len(runtime._scheduler._waiting) == 0
        backend.release.set()
        _join_started(first)
        assert not first.is_alive()
        assert backend.calls == 1
        assert not backend.second_started.is_set()
    finally:
        backend.release.set()
        _join_started(first)
        _join_started(second)
        runtime.close(deadline_ms=100)


def test_repeated_queued_expiry_does_not_retain_waiting_payloads(tmp_path: Path) -> None:
    """Expired queued work must be removed rather than accumulate behind a worker."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(
        tmp_path, backend=backend, queue_items=1, dispatch_timeout_ms=1_000
    )
    first_report: list[object] = []
    first = threading.Thread(
        target=lambda: first_report.append(runtime.dispatch(event(runtime, scope, 20)))
    )
    try:
        assert runtime.register(definition(), binding(), scope).accepted
        first.start()
        assert backend.started.wait(1)
        for value in range(21, 31):
            report = runtime.dispatch(event(runtime, scope, value), {"timeout_ms": 20})
            assert report.outcomes[0].status.value == "skipped_deadline"
            with runtime._scheduler._lock:
                assert runtime._scheduler._queued_items == 0
                assert runtime._scheduler._queued_bytes == 0
                assert len(runtime._scheduler._waiting) == 0
                assert len(runtime._scheduler._work) == 1
        backend.release.set()
        _join_started(first)
        assert not first.is_alive()
        assert backend.calls == 1
        assert not backend.second_started.is_set()
        with runtime._scheduler._lock:
            assert runtime._scheduler._work == {}
    finally:
        backend.release.set()
        _join_started(first)
        runtime.close(deadline_ms=100)


@pytest.mark.parametrize("invalid", [None, object(), {"event_id": "forged"}])
def test_invalid_emit_is_a_structured_side_effect_free_rejection(
    tmp_path: Path, invalid: object
) -> None:
    """Each invalid exact type must be rejected without attribute access."""
    backend = BlockingBackend()
    runtime, _ = runtime_and_scope(tmp_path, backend=backend)
    try:
        queued_before = (runtime._scheduler._queued_items, runtime._scheduler._queued_bytes)
        assert runtime.emit(invalid) == DeliveryReceipt(False, "", "invalid_event")
        assert runtime.dispatch(invalid).rejection_reason == "invalid_event"
        assert (runtime._scheduler._queued_items, runtime._scheduler._queued_bytes) == queued_before
        assert backend.calls == 0
        assert len(runtime.drain_diagnostics(20)) <= 1
    finally:
        runtime.close(deadline_ms=100)


@pytest.mark.parametrize("invalid", [None, object(), {"event_id": "forged"}])
def test_invalid_adispatch_is_a_structured_side_effect_free_rejection(
    tmp_path: Path, invalid: object
) -> None:
    """Async admission must apply the same exact-type rejection contract."""
    backend = BlockingBackend()
    runtime, _ = runtime_and_scope(tmp_path, backend=backend)

    async def exercise() -> None:
        report = await runtime.adispatch(invalid)
        assert report.event_id == ""
        assert report.rejection_reason == "invalid_event"

    try:
        asyncio.run(exercise())
        assert backend.calls == 0
        assert runtime._scheduler._work == {}
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


@pytest.mark.parametrize(
    "invalid_settings",
    [None, HookSettings(limits=replace(HookLimits(), workers=0))],
)
def test_invalid_initial_configuration_creates_disabled_bounded_runtime(
    tmp_path: Path, invalid_settings: object
) -> None:
    """Invalid settings must create an observable worker-free disabled runtime."""
    backend = BlockingBackend()
    observed: list[dict[str, object]] = []
    started = time.monotonic()
    runtime = HookRuntime(
        invalid_settings,
        temp_root=str(tmp_path),
        process_backend=backend,
        diagnostic_observer=lambda record: observed.append(record),
    )
    try:
        assert runtime._settings.enabled is False
        assert runtime._scheduler._executor is None
        assert runtime._diagnostics._thread is None
        scope = runtime.open_scope()
        invalid_runtime_event = event(runtime, scope)
        assert runtime.dispatch(invalid_runtime_event).rejection_reason == "disabled"
        assert runtime.emit(invalid_runtime_event).rejection_reason == "disabled"

        async def reject_async() -> None:
            report = await runtime.adispatch(invalid_runtime_event)
            assert report.rejection_reason == "disabled"

        asyncio.run(reject_async())
        records = runtime.drain_diagnostics(20)
        assert any(record.get("kind") == "configuration_rejected" for record in records)
        first = runtime.close(deadline_ms=50)
        second = runtime.close(deadline_ms=50)
        assert time.monotonic() - started < 1
        assert not first.already_closed
        assert second.already_closed
        assert backend.calls == 0
        assert observed == []
        assert runtime._scheduler._work == {}
        assert runtime.cleanup_debts() == ()
    finally:
        backend.release.set()
        runtime.close(deadline_ms=50)
