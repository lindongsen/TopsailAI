"""RED contracts for operational Hooks settings reload and generation semantics."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from topsailai.hooks import HookLimits, HookSettings
from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
    assert_reload_result,
    binding,
    definition,
    event,
    reload_runtime,
    runtime_scope,
    settings,
)


def report_evidence(report, runtime):
    """Summarize finite outcome metadata and exact remaining cleanup obligations."""
    evidence = {
        "elapsed_ms": report.elapsed_ms, "deadline_exhausted": report.deadline_exhausted,
        "rejection_reason": report.rejection_reason, "remaining_budget_ms": "unknown",
        "outcomes": [(item.binding_id[:128], item.status.value, item.error_category,
            item.duration_ms, item.started) for item in report.outcomes[:16]],
        "outcome_count": len(report.outcomes), "cleanup_debt_count": len(runtime.cleanup_debts()),
    }
    print("HOOK_REPORT_EVIDENCE " + json.dumps(evidence, sort_keys=True))
    return evidence


@pytest.mark.parametrize(
    "candidate",
    [None, object(), HookSettings(enabled="yes"), HookSettings(schema_version=2)],
)
def test_reload_rejects_invalid_candidate_and_preserves_active_state(
    tmp_path: Path, candidate: object
) -> None:
    """Invalid candidates must return structured rejection without partial publication."""
    runtime, scope = runtime_scope(tmp_path, initial=settings(handler_timeout_ms=2250, dispatch_timeout_ms=2500))
    try:
        registration = runtime.register(definition(), binding(timeout_ms=2250), scope)
        assert registration.accepted
        generation = registration.generation
        active_settings = runtime._settings
        result = reload_runtime(runtime, candidate)
        assert_reload_result(result, accepted=False, generation=generation)
        assert result.errors
        assert runtime._settings == active_settings
        report = runtime.dispatch(event(runtime, scope))
        assert report.generation == generation
        assert report.outcomes[0].status.value == "success", report_evidence(report, runtime)
        diagnostics = runtime.drain_diagnostics(50)
        assert any(item.get("kind") == "configuration_rejected" for item in diagnostics)
        assert all(str(candidate) not in repr(item) for item in diagnostics)
    finally:
        runtime.close(deadline_ms=100)


def test_reload_result_is_immutable_and_equal_settings_is_generation_noop(
    tmp_path: Path,
) -> None:
    """An equal candidate must be accepted without advancing runtime generation."""
    initial = settings()
    runtime, scope = runtime_scope(tmp_path, initial=initial)
    try:
        registration = runtime.register(definition(), binding(), scope)
        assert registration.accepted
        result = reload_runtime(runtime, initial)
        assert_reload_result(
            result, accepted=True, generation=registration.generation
        )
        with pytest.raises((FrozenInstanceError, AttributeError)):
            result.accepted = False
    finally:
        runtime.close(deadline_ms=100)


def test_changed_reload_and_registration_share_one_monotonic_generation(
    tmp_path: Path,
) -> None:
    """Settings and registry mutations must publish through one generation authority."""
    runtime, first_scope = runtime_scope(tmp_path)
    second_scope = runtime.open_scope()
    try:
        first = runtime.register(definition(), binding("first"), first_scope)
        assert first.accepted and first.handle is not None
        changed = reload_runtime(runtime, settings(handler_timeout_ms=400))
        assert_reload_result(changed, accepted=True, generation=first.generation + 1)
        second = runtime.register(definition(), binding("second"), second_scope)
        assert second.accepted
        assert second.generation == changed.generation + 1
        closed = second_scope.close()
        assert closed.closed_scope_ids == (second_scope.scope_id,)
        report = runtime.dispatch(event(runtime, first_scope))
        assert report.generation == second.generation + 1
    finally:
        runtime.close(deadline_ms=100)


def test_registration_handle_survives_unrelated_reload_and_mutation(tmp_path: Path) -> None:
    """A historical exact handle must remain valid after unrelated generations."""
    runtime, first_scope = runtime_scope(tmp_path)
    second_scope = runtime.open_scope()
    try:
        first = runtime.register(definition(), binding("first"), first_scope)
        assert first.accepted and first.handle is not None
        reload_result = reload_runtime(runtime, settings(event_bytes=3_000))
        assert_reload_result(reload_result, accepted=True)
        assert runtime.register(
            definition(), binding("second"), second_scope
        ).accepted
        removed = runtime.unregister(first.handle)
        assert removed.accepted
        assert removed.generation > reload_result.generation
        assert runtime._registry.snapshot(
            first_scope.scope_id, "test.reload", 1
        ).bindings == ()
    finally:
        runtime.close(deadline_ms=100)


def test_binding_cap_shrink_is_scope_local_and_preserves_registrations(
    tmp_path: Path,
) -> None:
    """A cap below actual per-scope use must reject without summing independent scopes."""
    runtime, first_scope = runtime_scope(tmp_path)
    second_scope = runtime.open_scope()
    try:
        first = runtime.register(definition(), binding("first"), first_scope)
        second = runtime.register(definition(), binding("second"), first_scope)
        other = runtime.register(definition(), binding("other"), second_scope)
        assert first.accepted and second.accepted and other.accepted
        rejected = reload_runtime(runtime, settings(bindings_per_event=1))
        assert_reload_result(rejected, accepted=False, generation=other.generation)
        assert len(runtime._registry.snapshot(
            first_scope.scope_id, "test.reload", 1
        ).bindings) == 2
        equal_cap = reload_runtime(runtime, settings(bindings_per_event=2))
        assert_reload_result(equal_cap, accepted=True)
        overflow = runtime.register(definition(), binding("overflow"), first_scope)
        assert not overflow.accepted
        permitted = runtime.register(definition(), binding("permitted"), second_scope)
        assert permitted.accepted
    finally:
        runtime.close(deadline_ms=100)


def test_disable_preserves_owned_work_and_registration_then_reenable_restores_use(
    tmp_path: Path,
) -> None:
    """Disable must stop new optional work but retain scope and registration ownership."""
    runtime, scope = runtime_scope(tmp_path)
    try:
        registration = runtime.register(definition(), binding(), scope)
        assert registration.accepted
        disabled = reload_runtime(runtime, settings(enabled=False))
        assert_reload_result(disabled, accepted=True)
        hook_event = event(runtime, scope)
        assert runtime.dispatch(hook_event).rejection_reason == "disabled"
        assert asyncio.run(runtime.adispatch(hook_event)).rejection_reason == "disabled"
        rejected_registration = runtime.register(
            definition(), binding("new"), scope
        )
        assert not rejected_registration.accepted
        assert not scope.closed
        assert len(runtime._registry.snapshot(
            scope.scope_id, "test.reload", 1
        ).bindings) == 1
        enabled = reload_runtime(runtime, settings(enabled=True))
        assert_reload_result(enabled, accepted=True, generation=disabled.generation + 1)
        report = runtime.dispatch(event(runtime, scope, 2))
        assert report.generation == enabled.generation
        assert report.outcomes[0].status.value == "success"
    finally:
        runtime.close(deadline_ms=100)


def test_disable_preserves_inflight_work_and_owner_cleanup(tmp_path: Path) -> None:
    """Disable must preserve admitted settlement while owner cleanup remains available."""
    from topsailai.tests.unit.test_topsailai_hooks.reload_helpers import (
        GatedRecordingBackend,
        invoke_thread,
        join_owned,
    )

    backend = GatedRecordingBackend()
    runtime, scope = runtime_scope(tmp_path, backend=backend)
    dispatch_thread = None
    try:
        registration = runtime.register(definition(), binding(), scope)
        assert registration.accepted
        dispatch_thread, reports, errors = invoke_thread(
            lambda: runtime.dispatch(event(runtime, scope))
        )
        assert backend.started.wait(1)
        disabled = reload_runtime(runtime, settings(enabled=False))
        assert_reload_result(disabled, accepted=True)
        assert runtime.dispatch(event(runtime, scope, 2)).rejection_reason == "disabled"
        backend.release.set()
        join_owned(dispatch_thread)
        assert errors == []
        assert reports[0].generation == registration.generation
        assert reports[0].outcomes[0].status.value == "success"
        close_report = scope.close()
        assert close_report.closed_scope_ids == (scope.scope_id,)
        assert runtime._registry.snapshot(
            scope.scope_id, "test.reload", 1
        ).bindings == ()
    finally:
        backend.release.set()
        if dispatch_thread is not None:
            join_owned(dispatch_thread)
        runtime.close(deadline_ms=100)


@pytest.mark.parametrize("invalid_initial", [False, True])
def test_disabled_or_invalid_initial_runtime_can_recover_without_eager_workers(
    tmp_path: Path, invalid_initial: bool
) -> None:
    """A valid enabling reload must recover worker-free initial disabled states."""
    initial = (
        HookSettings(limits=replace(HookLimits(), workers=0))
        if invalid_initial
        else settings(enabled=False)
    )
    runtime, scope = runtime_scope(tmp_path, initial=initial)
    try:
        assert runtime._scheduler._executor is None
        recovered = reload_runtime(runtime, settings(enabled=True))
        assert_reload_result(recovered, accepted=True)
        assert runtime._scheduler._executor in (None, ())
        registration = runtime.register(definition(), binding(), scope)
        assert registration.accepted
        assert runtime._scheduler._executor in (None, ())
        assert runtime.dispatch(event(runtime, scope)).outcomes[0].status.value == "success"
    finally:
        runtime.close(deadline_ms=100)


def test_reload_after_close_is_structured_and_does_not_resurrect_runtime(
    tmp_path: Path,
) -> None:
    """A closed runtime must reject reload without scheduler or scope resurrection."""
    runtime, scope = runtime_scope(tmp_path)
    registration = runtime.register(definition(), binding(), scope)
    assert registration.accepted
    runtime.close(deadline_ms=100)
    result = reload_runtime(runtime, settings(handler_timeout_ms=300))
    assert_reload_result(result, accepted=False, generation=registration.generation + 1)
    assert result.errors
    assert runtime._state == "closed"
    assert runtime._scheduler._closed
    assert runtime._scopes == {}
