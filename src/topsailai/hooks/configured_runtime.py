"""Runtime composition helpers for simple configured Hook registration."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
)
from topsailai.hooks.artifact_store import ArtifactCaptureOwner
from topsailai.hooks.configured_contracts import (
    ConfiguredHooks,
    ConfiguredRegistrationResult,
    ConfiguredTrustPolicy,
    PrepareConfiguredResult,
    is_valid_hook_name,
)
from topsailai.hooks.configured_trust import artifact_capture_trust
from topsailai.hooks.contracts import (
    DeliveryReceipt,
    DispatchReport,
    HookContext,
    HookEvent,
    HookOutcome,
    HookStatus,
)
from topsailai.hooks.hook_script import execute_configured_hook_script
from topsailai.hooks.hook_script_contracts import (
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import (
    ExecutablePlatformPolicy,
    HookScriptDiscoveryResult,
    HookScriptEntry,
    discover_configured_hook_scripts,
)
from topsailai.hooks.script_runner import OwnedHookScriptRunner
from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
from topsailai.hooks.hook_point_plan_capture import build_hook_point_candidate
from topsailai.hooks.hook_point_plan_ownership import (
    HookPointCandidate, HookPointOwner, _preserve_body_diagnosis,
)

_ConfiguredPlan = HookPointCandidate

if TYPE_CHECKING:
    from topsailai.hooks.runtime import HookRuntime, HookScope


@dataclass(slots=True)
class _ConfiguredAdmission:
    """Hold one acquired immutable configured plan execution."""

    event: HookEvent
    plan: "_ConfiguredPlan"
    generation: int
    timeout_ms: int
    started: float
    reader: object = None
    registry: object = None
    released: bool = False
    release_lock: threading.Lock | None = None

    def release(self) -> None:
        """Release the plan exactly once across execution and queue terminals."""
        if self.release_lock is None:
            self.release_lock = threading.Lock()
        with self.release_lock:
            if self.released:
                return
            self.registry.release_hook_point(self.reader)
            self.released = True



def detach_configured_trust(
    configured_trust: ConfiguredTrustPolicy | None,
) -> ConfiguredTrustPolicy | None:
    """Validate and detach configured authority before resource allocation."""
    if configured_trust is None:
        return None
    if type(configured_trust) is not ConfiguredTrustPolicy:
        raise ValueError("invalid configured trust policy")
    return ConfiguredTrustPolicy(
        source_roots=tuple(configured_trust.source_roots),
        allowed_interpreters=tuple(configured_trust.allowed_interpreters),
        allow_native_scripts=configured_trust.allow_native_scripts,
        closure_assertions=tuple(configured_trust.closure_assertions),
        python_runtime=configured_trust.python_runtime,
    )


def get_configured_trust(runtime: HookRuntime) -> ConfiguredTrustPolicy | None:
    """Return the immutable detached configured trust authority."""
    return runtime._configured_trust


def prepare_configured(
    runtime: HookRuntime,
    configuration: ConfiguredHooks,
    scope: HookScope,
    *,
    cancellation: threading.Event | None = None,
) -> PrepareConfiguredResult:
    """Retain the superseded fail-closed U09-A compatibility boundary."""
    from topsailai.hooks.runtime import HookScope

    with runtime._lock:
        generation = runtime._registry.generation
        if type(configuration) is not ConfiguredHooks:
            return PrepareConfiguredResult(False, generation, errors=("invalid_configuration",))
        if type(scope) is not HookScope or scope._runtime is not runtime:
            return PrepareConfiguredResult(False, generation, errors=("invalid_scope",))
        if cancellation is not None and type(cancellation) is not threading.Event:
            return PrepareConfiguredResult(False, generation, errors=("invalid_configuration",))
        if runtime._state != "running":
            return PrepareConfiguredResult(False, generation, errors=("runtime_closed",))
        if not runtime._owns_open_scope(scope):
            return PrepareConfiguredResult(False, generation, errors=("scope_closed",))
        if runtime._configured_trust is None:
            return PrepareConfiguredResult(False, generation, errors=("trust_policy_missing",))
        if cancellation is not None and cancellation.is_set():
            return PrepareConfiguredResult(False, generation, errors=("cancelled",))
        return PrepareConfiguredResult(False, generation, errors=("internal_error",))


def register_configured(
    runtime: HookRuntime,
    hook_name: str,
    scope: HookScope,
    *,
    scripts: Sequence[str | os.PathLike[str]] | None = None,
    folder: str | os.PathLike[str] | None = None,
) -> ConfiguredRegistrationResult:
    """Discover, capture, and atomically publish one scope-local script plan."""
    if not is_valid_hook_name(hook_name):
        return ConfiguredRegistrationResult(False, errors=("invalid_hook_name",))
    if (scripts is None) == (folder is None):
        return ConfiguredRegistrationResult(False, errors=("invalid_script_source",))
    with runtime._lock:
        if runtime._state != "running":
            return ConfiguredRegistrationResult(False, errors=("runtime_closed",))
        if not runtime._owns_open_scope(scope):
            return ConfiguredRegistrationResult(False, errors=("invalid_scope",))
        trust = runtime._configured_trust
    if trust is None:
        return ConfiguredRegistrationResult(False, errors=("trust_policy_missing",))
    try:
        ordered_scripts = None if scripts is None else tuple(islice(scripts, 129))
    except TypeError:
        return ConfiguredRegistrationResult(False, errors=("invalid_script_source",))
    if ordered_scripts is not None and len(ordered_scripts) > 128:
        return ConfiguredRegistrationResult(False, errors=("registration_capacity_exceeded",))
    platform = _platform_policy(trust)
    discovery = discover_configured_hook_scripts(
        scripts=ordered_scripts, folder=folder, platform_policy=platform, max_resources=128
    )
    if not discovery.accepted:
        error = ("registration_capacity_exceeded" if discovery.errors ==
                 ("registration_capacity_exceeded",) else "discovery_rejected")
        return ConfiguredRegistrationResult(False, errors=(error,))
    if len(discovery.entries) > 128:
        return ConfiguredRegistrationResult(False, errors=("registration_capacity_exceeded",))
    recovery = runtime._publication_recovery
    reservations = []
    ticket = previous_ticket = None
    plan = None
    previous_owner = None
    try:
        ticket = recovery.reserve(reservations)
        previous_ticket = recovery.reserve(reservations) if ticket is not None else None
        if ticket is None or previous_ticket is None:
            return ConfiguredRegistrationResult(False, errors=("publication_capacity_exceeded",))
        plan, error = _capture_plan(runtime, hook_name, discovery, platform, trust, recovery, ticket)
        if plan is None:
            return ConfiguredRegistrationResult(False, errors=(error or "artifact_rejected",))
        recovery.bind(ticket, plan)
        rejection = None
        with runtime._lock:
            if runtime._state != "running":
                rejection = "runtime_closed"
            elif not runtime._owns_open_scope(scope):
                rejection = "scope_closed"
            else:
                _, previous_owner = runtime._registry.configured_plan(scope.scope_id, hook_name)
                if previous_owner is not None:
                    recovery.bind(previous_ticket, previous_owner)
                result = runtime._registry.publish_hook_point(
                    scope.scope_id, hook_name, plan, dispose_loser=False)
                if result.changed:
                    recovery.handoff(ticket)
                elif not result.accepted:
                    rejection = "artifact_rejected"
        if rejection is not None:
            recovery.settle(ticket)
            return ConfiguredRegistrationResult(False, errors=(rejection,))
        if not result.changed:
            recovery.settle(ticket)
        elif result.previous is not None:
            recovery.settle(previous_ticket)
        return ConfiguredRegistrationResult(True, changed=result.changed,
            script_count=len(discovery.entries))
    except BaseException as error:
        owner = getattr(error, "recovery_owner", None)
        if owner is not None:
            recovery.bind(ticket, owner)
        if not isinstance(error, Exception):
            raise
        return ConfiguredRegistrationResult(False, errors=("artifact_rejected",))
    finally:
        if previous_owner is not None and runtime._registry.owns_hook_point_owner(previous_owner):
            recovery.handoff(previous_ticket)
        for reservation in reservations:
            recovery.release(reservation)


def dispatch_configured(
    runtime: HookRuntime, hook_name: str, event: HookEvent, policy: Any = None
) -> DispatchReport:
    """Synchronously execute one exact configured plan."""
    work, rejection = _admit_configured(runtime, hook_name, event, policy, True)
    if rejection is not None:
        return rejection
    assert work is not None
    return work.future.result()


async def adispatch_configured(
    runtime: HookRuntime, hook_name: str, event: HookEvent, policy: Any = None
) -> DispatchReport:
    """Asynchronously execute one exact configured plan."""
    work, rejection = _admit_configured(runtime, hook_name, event, policy, False)
    if rejection is not None:
        return rejection
    assert work is not None
    return await asyncio.shield(asyncio.wrap_future(work.future))


def emit_configured(
    runtime: HookRuntime, hook_name: str, event: HookEvent, policy: Any = None
) -> DeliveryReceipt:
    """Admit one configured execution without waiting for completion."""
    work, rejection = _admit_configured(runtime, hook_name, event, policy, False)
    event_id = event.event_id if type(event) is HookEvent else ""
    if rejection is not None:
        return DeliveryReceipt(False, event_id, rejection.rejection_reason)
    if work is None:
        return DeliveryReceipt(False, event_id, "rejected_capacity")
    work.future.add_done_callback(
        lambda completed: runtime._observe_background_completion(work, completed)
    )
    return DeliveryReceipt(True, event_id)

def retire_configured(runtime: HookRuntime, hook_name: str, scope: HookScope) -> bool:
    """Reserve recovery before removing an exact point from active membership."""
    if not is_valid_hook_name(hook_name):
        return False
    recovery = runtime._publication_recovery
    reservations = []
    try:
        with runtime._lock:
            if not runtime._owns_open_scope(scope):
                return False
            ticket = recovery.reserve(reservations)
            if ticket is None:
                return False
            _, plan = runtime._registry.configured_plan(scope.scope_id, hook_name)
            if plan is None:
                return False
            recovery.bind(ticket, plan)
            try:
                runtime._registry.remove_configured(scope.scope_id, hook_name)
            finally:
                if runtime._registry.owns_hook_point_owner(plan):
                    recovery.handoff(ticket)
        recovery.settle(ticket)
        return True
    finally:
        for reservation in reservations:
            recovery.release(reservation)


def retire_configured_scope(runtime: HookRuntime, scope_id: str) -> bool:
    """Advance a fixed batch of explicitly deferred owners outside cleanup locks."""
    recovery = runtime._publication_recovery
    with runtime._lock:
        runtime._registry.defer_configured_scope(scope_id)
    for _ in range(recovery.capacity):
        with runtime._lock:
            ticket = runtime._registry.handoff_deferred_scope(scope_id, recovery)
        if ticket is None:
            break
        recovery.settle(ticket)
    return runtime._registry.deferred_scope_count(scope_id) == 0


def _platform_policy(trust: ConfiguredTrustPolicy) -> ExecutablePlatformPolicy:
    """Build the existing shell-free discovery policy from Runtime trust."""
    if os.name == "nt":
        return ExecutablePlatformPolicy("windows", native_suffixes=(".exe",))
    return ExecutablePlatformPolicy(
        "posix", allowed_interpreters=tuple(str(path) for path in trust.allowed_interpreters)
    )


def _capture_plan(runtime, hook_name, discovery, platform, trust, recovery=None, ticket=None):
    """Build a complete zero-Module candidate through the sealed U05A path."""
    if len(discovery.entries) > 128:
        return None, "registration_capacity_exceeded"
    root = Path(runtime._backend.script_temp_root) / "configured-artifacts" / uuid.uuid4().hex
    try:
        if discovery.entries:
            root.mkdir(mode=0o700, parents=True)
        return build_hook_point_candidate(hook_name, script_discovery=discovery,
            platform_policy=platform, trust=artifact_capture_trust(trust),
            artifact_root=str(root), probe_backend=runtime._backend,
            policy=ArtifactCapturePolicy(max_entries=128),
            receiver=None if recovery is None else lambda candidate: recovery.bind(ticket, candidate)), None
    except (OSError, RuntimeError, ValueError):
        raise


def _admit_configured(runtime, hook_name, event, policy, reject_running_loop):
    """Validate, acquire, and submit one configured plan through the scheduler."""
    rejection = runtime._admission_rejection(event, reject_running_loop=reject_running_loop)
    if rejection is not None:
        return None, rejection
    if not is_valid_hook_name(hook_name):
        return None, runtime._rejected(event, "invalid_hook_name")
    receiver = []
    work = None
    rejection = None
    admission = None
    try:
        with runtime._lock:
            generation = runtime._registry.generation
            reader = runtime._registry.acquire_hook_point(event.scope_id, hook_name, receiver)
            if reader is None:
                rejection = runtime._rejected(event, "unknown_configured_hook")
            elif reader.snapshot.plan.modules:
                rejection = runtime._rejected(event, "mixed_plan_unavailable")
            else:
                plan = reader.owner
                timeout_ms = runtime._policy_timeout(policy, runtime._settings)
                admission = _ConfiguredAdmission(event, plan, generation, timeout_ms,
                    time.monotonic(), reader=reader, registry=runtime._registry)
                deadline = admission.started + timeout_ms / 1000
                work = runtime._scheduler.submit(
                    event.scope_id,
                    max(1, len(plan.entries)),
                    lambda: _execute_configured(runtime, admission),
                    cancellation_result=lambda: _terminal_configured(admission, "closed_scope"),
                    deadline_seconds=deadline,
                    deadline_result=lambda: _terminal_configured(admission, "deadline"),
                )
    except BaseException as primary:
        for retained in receiver:
            try:
                runtime._registry.release_hook_point(retained)
            except BaseException as cleanup:
                if isinstance(primary, Exception) and not isinstance(cleanup, Exception):
                    _preserve_body_diagnosis(primary, cleanup)
                    raise
                _preserve_body_diagnosis(cleanup, primary)
        raise
    if work is None:
        if admission is not None:
            admission.release()
        else:
            for retained in receiver:
                runtime._registry.release_hook_point(retained)
    return work, rejection


def _execute_configured(runtime, admission):
    """Execute and release one admitted configured plan."""
    recovery = runtime._publication_recovery
    ticket = None
    reservations = []
    custody = None
    try:
        if not admission.plan.entries:
            return DispatchReport(admission.event.event_id, admission.generation)
        ticket = recovery.reserve(reservations)
        if ticket is None:
            return DispatchReport(admission.event.event_id, admission.generation,
                rejection_reason="registration_capacity_exceeded")
        custody = ExecutionCleanupCustody(admission.registry, None)
        recovery.bind(ticket, custody)
        admission.registry.retain_hook_point_cleanup(admission.reader, custody)
        custody.runner = OwnedHookScriptRunner(runtime._backend)
        context = HookContext(
            admission.event,
            uuid.uuid4().hex,
            "hook_script",
            admission.generation,
            admission.timeout_ms,
        )
        settlement = execute_configured_hook_script(
            hook_point=admission.plan.hook_name,
            module_bindings=(),
            bindings_per_event=runtime._settings.limits.bindings_per_event,
            discovery_result=HookScriptDiscoveryResult(True, admission.plan.entries),
            context=context,
            options=admission.plan.options,
            policy=admission.plan.policy,
            runner=custody.runner,
            dispatch_deadline=admission.started + admission.timeout_ms / 1000,
            cancellation=threading.Event(),
            clock=time.monotonic,
        )
        status = HookStatus(settlement.status)
        outcome = HookOutcome(
            context.delivery_id,
            "hook_script",
            status,
            duration_ms=int((time.monotonic() - admission.started) * 1000),
            error_category=settlement.error_category,
            started=settlement.started,
        )
        return DispatchReport(
            admission.event.event_id,
            admission.generation,
            (outcome,),
            elapsed_ms=outcome.duration_ms,
        )
    finally:
        retained = reservations[0] if reservations else ticket
        _finish_configured_execution(recovery, retained, custody, admission, sys.exc_info()[1])


def _finish_configured_execution(recovery, ticket, custody, admission, primary):
    """Attempt both cleanups without replacing primary identity or native evidence."""
    selected = primary
    selected_traceback = None if primary is None else primary.__traceback__
    for operation in ("custody", "reader"):
        try:
            if operation == "reader":
                admission.release()
            elif custody is not None:
                custody.completed = True
                recovery.settle(ticket)
            elif ticket is not None:
                recovery.release(ticket)
        except BaseException as cleanup:
            if selected is None:
                selected, selected_traceback = cleanup, cleanup.__traceback__
            elif isinstance(selected, Exception) and not isinstance(cleanup, Exception):
                _preserve_body_diagnosis(selected, cleanup)
                selected, selected_traceback = cleanup, cleanup.__traceback__
            else:
                _preserve_body_diagnosis(cleanup, selected)
    if selected is not None and selected is not primary:
        raise selected.with_traceback(selected_traceback)


def _terminal_configured(admission, category):
    """Release a queued plan and return one terminal report."""
    admission.release()
    return DispatchReport(
        admission.event.event_id,
        admission.generation,
        rejection_reason=category,
        deadline_exhausted=category == "deadline",
    )
