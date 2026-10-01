"""RED contracts for atomic Hooks reload publication and admission snapshots."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
    GatedRecordingBackend,
    assert_reload_result,
    binding,
    definition,
    event,
    invoke_thread,
    join_owned,
    reload_runtime,
    runtime_scope,
    settings,
)


def test_reload_waits_for_atomic_admission_snapshot_and_publishes_whole_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admission must capture registry and settings in one owner transaction."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    assert runtime.register(definition(), binding(), scope).accepted
    snapshot_entered = threading.Event()
    release_snapshot = threading.Event()
    reload_entered = threading.Event()
    original_snapshot = runtime._registry.snapshot

    def paused_snapshot(*args: object, **kwargs: object) -> Any:
        """Pause at the existing real registry snapshot boundary."""
        snapshot_entered.set()
        assert release_snapshot.wait(2)
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(runtime._registry, "snapshot", paused_snapshot)
    dispatch_thread, reports, dispatch_errors = invoke_thread(
        lambda: runtime.dispatch(event(runtime, scope, 1))
    )

    def perform_reload() -> Any:
        """Record reload entry before invoking the public boundary."""
        reload_entered.set()
        return reload_runtime(
            runtime,
            settings(handler_timeout_ms=200, dispatch_timeout_ms=300),
        )

    reload_thread: threading.Thread | None = None
    reload_results: list[Any] = []
    reload_errors: list[BaseException] = []
    try:
        assert snapshot_entered.wait(1)
        reload_thread, reload_results, reload_errors = invoke_thread(perform_reload)
        assert reload_entered.wait(1)
        assert reload_thread.is_alive(), "reload crossed an admission owner transaction"
        release_snapshot.set()
        assert backend.started.wait(1)
        backend.release.set()
        join_owned(dispatch_thread)
        join_owned(reload_thread)
        assert dispatch_errors == []
        assert reload_errors == []
        assert_reload_result(reload_results[0], accepted=True)
        old_report = reports[0]
        old_context, old_timeout = backend.calls[0]
        assert old_report.generation < reload_results[0].generation
        assert old_context.registry_generation == old_report.generation
        assert old_timeout > 200
        new_report = runtime.dispatch(event(runtime, scope, 2))
        new_context, new_timeout = backend.calls[1]
        assert new_report.generation == reload_results[0].generation
        assert new_context.registry_generation == new_report.generation
        assert new_timeout <= 200
    finally:
        release_snapshot.set()
        backend.release.set()
        join_owned(dispatch_thread)
        if reload_thread is not None:
            join_owned(reload_thread)
        runtime.close(deadline_ms=100)


def test_admitted_dispatch_retains_old_generation_and_handler_budget(tmp_path: Path) -> None:
    """A blocked admitted dispatch must retain its complete old settings snapshot."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    try:
        registration = runtime.register(
            definition(), binding(timeout_ms=700), scope
        )
        assert registration.accepted
        thread, reports, errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 1), {"timeout_ms": 900})
        )
        assert backend.started.wait(1)
        old_context, old_timeout = backend.calls[0]
        changed = reload_runtime(
            runtime,
            settings(handler_timeout_ms=150, dispatch_timeout_ms=250),
        )
        assert_reload_result(changed, accepted=True)
        backend.release.set()
        join_owned(thread)
        assert errors == []
        assert reports[0].generation == registration.generation
        assert old_context.registry_generation == registration.generation
        assert 0 < old_timeout <= 700
        backend.release.clear()
        later_thread, later_reports, later_errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 2))
        )
        assert backend.wait_calls(2)
        new_context, new_timeout = backend.calls[1]
        backend.release.set()
        join_owned(later_thread)
        assert later_errors == []
        assert later_reports[0].generation == changed.generation
        assert new_context.registry_generation == changed.generation
        assert new_timeout <= 150
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_adispatch_and_emit_capture_generation_and_old_budget_before_reload(
    tmp_path: Path,
) -> None:
    """Async and background admission paths must retain their captured generations."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    assert runtime.register(definition(), binding(), scope).accepted

    async def exercise() -> None:
        async_task = asyncio.create_task(runtime.adispatch(event(runtime, scope, 1)))
        assert await asyncio.to_thread(backend.started.wait, 1)
        changed = reload_runtime(runtime, settings(handler_timeout_ms=120))
        assert_reload_result(changed, accepted=True)
        backend.release.set()
        async_report = await asyncio.wait_for(async_task, 1)
        first_context, first_timeout = backend.calls[0]
        assert async_report.generation < changed.generation
        assert first_context.registry_generation == async_report.generation
        assert first_timeout > 120

        backend.release.clear()
        receipt = runtime.emit(event(runtime, scope, 2))
        assert receipt.admitted
        assert await asyncio.to_thread(backend.wait_calls, 2, 1)
        second_context, second_timeout = backend.calls[1]
        assert second_context.registry_generation == changed.generation
        assert second_timeout <= 120
        backend.release.set()

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_event_byte_limit_changes_only_future_admissions(tmp_path: Path) -> None:
    """A lower event budget must not retroactively invalidate admitted work."""
    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    try:
        registration = runtime.register(definition(), binding(), scope)
        assert registration.accepted
        thread, reports, errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope, 1))
        )
        assert backend.started.wait(1)
        changed = reload_runtime(runtime, settings(event_bytes=64))
        assert_reload_result(changed, accepted=True)
        rejected = runtime.dispatch(event(runtime, scope, 2))
        assert rejected.rejection_reason == "invalid_event"
        assert len(backend.calls) == 1
        backend.release.set()
        join_owned(thread)
        assert errors == []
        assert reports[0].outcomes[0].status.value == "success"
        assert reports[0].generation == registration.generation
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_reload_racing_close_is_wholly_published_or_wholly_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reload and close must linearize without scheduler resurrection or partial state."""
    runtime, scope = runtime_scope(tmp_path)
    assert runtime.register(definition(), binding(), scope).accepted
    close_boundary = threading.Event()
    release_close = threading.Event()
    original_close = runtime._scheduler.close

    def paused_close(timeout_seconds: float) -> Any:
        """Pause at the existing scheduler close boundary."""
        close_boundary.set()
        assert release_close.wait(2)
        return original_close(timeout_seconds)

    monkeypatch.setattr(runtime._scheduler, "close", paused_close)
    close_thread, _, close_errors = invoke_thread(lambda: runtime.close(deadline_ms=200))
    reload_thread: threading.Thread | None = None
    reload_results: list[Any] = []
    reload_errors: list[BaseException] = []
    try:
        assert close_boundary.wait(1)
        reload_thread, reload_results, reload_errors = invoke_thread(
            lambda: reload_runtime(runtime, settings(enabled=False))
        )
        release_close.set()
        join_owned(close_thread)
        join_owned(reload_thread)
        assert close_errors == []
        assert reload_errors == []
        assert_reload_result(reload_results[0], accepted=False)
        assert runtime._state == "closed"
        assert runtime._scheduler._closed
        assert runtime._scopes == {}
    finally:
        release_close.set()
        join_owned(close_thread)
        if reload_thread is not None:
            join_owned(reload_thread)
        runtime.close(deadline_ms=100)
