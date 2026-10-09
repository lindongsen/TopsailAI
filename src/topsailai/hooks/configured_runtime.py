"""Runtime composition helpers for simple configured Hook registration."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass
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
    released: bool = False
    release_lock: threading.Lock | None = None

    def release(self) -> None:
        """Release the plan exactly once across execution and queue terminals."""
        if self.release_lock is None:
            self.release_lock = threading.Lock()
        with self.release_lock:
            if self.released:
                return
            self.released = True
        self.plan.release()


class _ConfiguredPlan:
    """Own one immutable captured script plan until all readers release it."""

    def __init__(
        self,
        hook_name: str,
        entries: tuple[HookScriptEntry, ...],
        owner: ArtifactCaptureOwner | None,
        fingerprint: object,
    ) -> None:
        self.hook_name = hook_name
        self.entries = entries
        self.owner = owner
        self.fingerprint = fingerprint
        self.options = HookScriptExecutionOptions()
        self.policy = HookScriptExecutionPolicy()
        self._lock = threading.Lock()
        self._readers = 0
        self._retired = False

    def acquire(self) -> bool:
        """Retain this plan for one admitted execution."""
        with self._lock:
            if self._retired:
                return False
            self._readers += 1
            return True

    def release(self) -> None:
        """Release one execution and clean a fully retired plan."""
        owner = None
        with self._lock:
            self._readers -= 1
            if self._retired and self._readers == 0:
                owner, self.owner = self.owner, None
        if owner is not None:
            owner.close()

    def retire(self) -> None:
        """Prevent new use and clean once every admitted reader settles."""
        owner = None
        with self._lock:
            self._retired = True
            if self._readers == 0:
                owner, self.owner = self.owner, None
        if owner is not None:
            owner.close()


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
        ordered_scripts = None if scripts is None else tuple(scripts)
    except TypeError:
        return ConfiguredRegistrationResult(False, errors=("invalid_script_source",))
    platform = _platform_policy(trust)
    discovery = discover_configured_hook_scripts(
        scripts=ordered_scripts, folder=folder, platform_policy=platform
    )
    if not discovery.accepted:
        return ConfiguredRegistrationResult(False, errors=("discovery_rejected",))
    plan, error = _capture_plan(runtime, hook_name, discovery, platform, trust)
    if plan is None:
        return ConfiguredRegistrationResult(False, errors=(error or "artifact_rejected",))
    with runtime._lock:
        if not runtime._owns_open_scope(scope):
            plan.retire()
            return ConfiguredRegistrationResult(False, errors=("scope_closed",))
        changed, _, previous = runtime._registry.publish_configured(
            scope.scope_id, hook_name, plan.fingerprint, plan
        )
    if not changed:
        plan.retire()
        return ConfiguredRegistrationResult(True, script_count=len(discovery.entries))
    if isinstance(previous, _ConfiguredPlan):
        previous.retire()
    return ConfiguredRegistrationResult(
        True, changed=True, script_count=len(discovery.entries)
    )


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


def retire_configured_scope(runtime: HookRuntime, scope_id: str) -> None:
    """Retire every configured plan removed with one closing scope."""
    for plan in runtime._registry.remove_configured_scope(scope_id):
        if isinstance(plan, _ConfiguredPlan):
            plan.retire()


def _platform_policy(trust: ConfiguredTrustPolicy) -> ExecutablePlatformPolicy:
    """Build the existing shell-free discovery policy from Runtime trust."""
    if os.name == "nt":
        return ExecutablePlatformPolicy("windows", native_suffixes=(".exe",))
    return ExecutablePlatformPolicy(
        "posix", allowed_interpreters=tuple(str(path) for path in trust.allowed_interpreters)
    )


def _capture_plan(runtime, hook_name, discovery, platform, trust):
    """Capture discovered sources into one Runtime-owned immutable plan."""
    if not discovery.entries:
        return _ConfiguredPlan(hook_name, (), None, ()), None
    root = Path(runtime._backend.script_temp_root) / "configured-artifacts" / uuid.uuid4().hex
    owner = None
    try:
        root.mkdir(mode=0o700, parents=True)
        owner = ArtifactCaptureOwner(
            artifact_root=str(root), trust=artifact_capture_trust(trust)
        )
        requests = tuple(
            ArtifactCaptureRequest(entry.source_path, "script", entry.basename, platform)
            for entry in discovery.entries
        )
        result = owner.capture(
            requests,
            policy=ArtifactCapturePolicy(max_entries=len(requests)),
        )
        if not result.accepted or result.artifact is None:
            owner.close()
            return None, "artifact_rejected"
        artifact = result.artifact
        entries = tuple(
            HookScriptEntry(
                (artifact.directory / item.relative_path).resolve(strict=True),
                item.logical_name,
            )
            for item in artifact.entries
        )
        return _ConfiguredPlan(hook_name, entries, owner, artifact.identity), None
    except (OSError, RuntimeError, ValueError):
        if owner is not None:
            owner.close()
        return None, "artifact_rejected"


def _admit_configured(runtime, hook_name, event, policy, reject_running_loop):
    """Validate, acquire, and submit one configured plan through the scheduler."""
    rejection = runtime._admission_rejection(event, reject_running_loop=reject_running_loop)
    if rejection is not None:
        return None, rejection
    if not is_valid_hook_name(hook_name):
        return None, runtime._rejected(event, "invalid_hook_name")
    with runtime._lock:
        generation, plan = runtime._registry.configured_plan(event.scope_id, hook_name)
        if not isinstance(plan, _ConfiguredPlan) or not plan.acquire():
            return None, runtime._rejected(event, "unknown_configured_hook")
        timeout_ms = runtime._policy_timeout(policy, runtime._settings)
        admission = _ConfiguredAdmission(event, plan, generation, timeout_ms, time.monotonic())
        deadline = admission.started + timeout_ms / 1000
        work = runtime._scheduler.submit(
            event.scope_id,
            max(1, len(plan.entries)),
            lambda: _execute_configured(runtime, admission),
            cancellation_result=lambda: _terminal_configured(admission, "closed_scope"),
            deadline_seconds=deadline,
            deadline_result=lambda: _terminal_configured(admission, "deadline"),
        )
    if work is None:
        admission.release()
    return work, None


def _execute_configured(runtime, admission):
    """Execute and release one admitted configured plan."""
    try:
        if not admission.plan.entries:
            return DispatchReport(admission.event.event_id, admission.generation)
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
            runner=OwnedHookScriptRunner(runtime._backend),
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
        admission.release()


def _terminal_configured(admission, category):
    """Release a queued plan and return one terminal report."""
    admission.release()
    return DispatchReport(
        admission.event.event_id,
        admission.generation,
        rejection_reason=category,
        deadline_exhausted=category == "deadline",
    )
