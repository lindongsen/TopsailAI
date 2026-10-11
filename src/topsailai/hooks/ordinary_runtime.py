"""Scope-local ordinary source descriptors and exact execution. Author: DawsonLin."""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, fields
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy
from topsailai.hooks.configured_contracts import ConfiguredRegistrationResult, is_valid_hook_name
from topsailai.hooks.configured_runtime import _admit_configured, _platform_policy
from topsailai.hooks.configured_trust import artifact_capture_trust
from topsailai.hooks.hook_point_plan_capture import build_hook_point_candidate
from topsailai.hooks.hook_point_plan_contracts import ModuleSource
from topsailai.hooks.hook_script_discovery import discover_configured_hook_scripts


@dataclass(frozen=True, slots=True)
class _Sources:
    """Retain detached references, never captured or caller-owned candidates."""
    modules: tuple
    scripts: tuple


def register_hook_point(runtime, hook_name, scope, *, modules=(), scripts=()):
    """Register bounded sources without altering the legacy Binding graph."""
    if not is_valid_hook_name(hook_name):
        return ConfiguredRegistrationResult(False, errors=('invalid_hook_name',))
    try:
        if type(modules) not in (tuple, list) or type(scripts) not in (tuple, list):
            raise ValueError('invalid sources')
        if len(modules) + len(scripts) > 128:
            raise ValueError('source capacity')
        if any(type(item) is not ModuleSource for item in modules):
            raise ValueError('invalid module source')
        detached = tuple(ModuleSource(**{f.name: getattr(item, f.name)
            for f in fields(ModuleSource)}) for item in modules)
        paths = tuple(Path(item) for item in scripts)
        if any(not item.is_absolute() for item in paths):
            raise ValueError('relative source')
        if len({item.registered_name for item in detached}) != len(detached):
            raise ValueError('duplicate module')
        sources = _Sources(detached, paths)
    except (TypeError, ValueError):
        return ConfiguredRegistrationResult(False, errors=('invalid_sources',))
    with runtime._lock:
        if runtime._state != 'running':
            return ConfiguredRegistrationResult(False, errors=('runtime_closed',))
        if not runtime._owns_open_scope(scope):
            return ConfiguredRegistrationResult(False, errors=('invalid_scope',))
        key = (scope.scope_id, hook_name)
        if key not in runtime._ordinary_sources and len(runtime._ordinary_sources) >= 128:
            return ConfiguredRegistrationResult(False, errors=('registration_capacity_exceeded',))
        changed = runtime._ordinary_sources.get(key) != sources
        runtime._ordinary_sources[key] = sources
    return ConfiguredRegistrationResult(True, changed=changed, script_count=len(paths))


def dispatch_hook_point(runtime, hook_name, event, policy=None, *, cancellation=None):
    """Fix one deadline before capture, then run the exact immutable publication."""
    started = time.monotonic()
    with runtime._lock:
        deadline = started + runtime._policy_timeout(policy, runtime._settings) / 1000
    rejection = runtime._admission_rejection(event, reject_running_loop=True)
    if rejection is not None:
        return rejection
    if cancellation is not None and not isinstance(cancellation, threading.Event):
        raise ValueError('invalid cancellation')
    cancellation = threading.Event() if cancellation is None else cancellation
    with runtime._lock:
        sources = runtime._ordinary_sources.get((event.scope_id, hook_name))
        trust = runtime._configured_trust
    if sources is None:
        return runtime._rejected(event, 'unknown_hook_point')
    if trust is None:
        return runtime._rejected(event, 'trust_policy_missing')
    return _prepare_and_submit(runtime, hook_name, event, policy, sources, trust,
        deadline, cancellation)


def _prepare_and_submit(runtime, name, event, policy, sources, trust, deadline, cancellation):
    """Journal capture and predecessor disposal before any resource mutation."""
    recovery = runtime._publication_recovery
    reservations = []
    ticket = previous_ticket = None
    previous = None
    work = None
    try:
        ticket = recovery.reserve(reservations)
        previous_ticket = recovery.reserve(reservations) if ticket is not None else None
        if previous_ticket is None:
            return runtime._rejected(event, 'publication_capacity_exceeded')
        if cancellation.is_set() or time.monotonic() >= deadline:
            return runtime._rejected(event, 'cancelled' if cancellation.is_set() else 'deadline')
        platform = _platform_policy(trust)
        discovery = discover_configured_hook_scripts(scripts=sources.scripts,
            folder=None, platform_policy=platform, max_resources=128)
        if cancellation.is_set() or time.monotonic() >= deadline:
            return runtime._rejected(event, 'cancelled' if cancellation.is_set() else 'deadline')
        if not discovery.accepted:
            return runtime._rejected(event, 'discovery_rejected')
        root = Path(runtime._backend.script_temp_root) / 'ordinary-artifacts' / uuid.uuid4().hex
        if sources.modules or discovery.entries:
            root.mkdir(mode=0o700, parents=True)
        candidate = build_hook_point_candidate(name, modules=sources.modules,
            script_discovery=discovery, platform_policy=platform,
            trust=artifact_capture_trust(trust), artifact_root=str(root),
            probe_backend=runtime._backend, policy=ArtifactCapturePolicy(max_entries=128),
            deadline=deadline, receiver=lambda owner: recovery.bind(ticket, owner))
        with runtime._lock:
            if runtime._state != 'running' or not runtime._scope_is_open(event.scope_id):
                return runtime._rejected(event, 'closed_scope')
            if cancellation.is_set() or time.monotonic() >= deadline:
                return runtime._rejected(event, 'cancelled' if cancellation.is_set() else 'deadline')
            _, previous = runtime._registry.configured_plan(event.scope_id, name)
            if previous is not None:
                recovery.bind(previous_ticket, previous)
            published = runtime._registry.publish_hook_point(event.scope_id, name,
                candidate, dispose_loser=False)
            if not published.accepted:
                return runtime._rejected(event, 'artifact_rejected')
            if published.changed:
                recovery.handoff(ticket)
            # Acquire the published reader before another dispatch can replace it.
            work, rejection = _admit_configured(runtime, name, event, policy, True,
                deadline, cancellation)
        if rejection is not None:
            return rejection
    except BaseException as error:
        owner = getattr(error, 'recovery_owner', None)
        if owner is not None:
            recovery.bind(ticket, owner)
        raise
    finally:
        if previous is not None and runtime._registry.owns_hook_point_owner(previous):
            recovery.handoff(previous_ticket)
        for reservation in reservations:
            recovery.settle(reservation)
            recovery.release(reservation)
    return work.future.result()
