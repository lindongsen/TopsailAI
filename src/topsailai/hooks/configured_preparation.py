"""Private U09-B configured preparation without publication or dispatch."""

from __future__ import annotations

import importlib.machinery
import os
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy, ArtifactCaptureRequest, ArtifactDisposeResult
from topsailai.hooks.artifact_leases import ArtifactLeaseManager
from topsailai.hooks.configured_contracts import ConfiguredHooks, ConfiguredModuleFailure, ConfiguredPlanSummary, PrepareConfiguredResult
from topsailai.hooks.configured_preparation_ownership import CaptureShard, ConfiguredRootOwner, PreparationOwnership
from topsailai.hooks.configured_trust import artifact_capture_trust
from topsailai.hooks.contracts import Binding
from topsailai.hooks.hook_script import build_hook_point_binding_plan_from_discovery
from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry, discover_hook_script_entries
from topsailai.hooks.module_discovery import ModuleCandidate, ModuleCleanupOwner, _DiscoveryRejected, _make_cleanup_owner, _run_with_module_probe_session, enumerate_module_candidates_owned
from topsailai.hooks.module_discovery_policy import ModuleDiscoveryPolicy, make_discovery_budget_for_deadline
from topsailai.hooks.temporary_storage import TemporaryStorageOwner, validate_temporary_root

_MAX_CAPTURE_ENTRIES = 128
_MAX_CAPTURE_SHARDS = 8
_PREPARATION_RECOVERY_OWNER_ATTRIBUTE = "__topsailai_preparation_recovery_owner__"


def get_preparation_recovery_owner(error: BaseException):
    """Return aggregate recovery authority retained on an interruption."""
    return getattr(error, _PREPARATION_RECOVERY_OWNER_ATTRIBUTE, None)


def _ownership_requires_recovery(ownership) -> bool:
    """Return recovery state while preserving lightweight test doubles."""
    predicate = getattr(ownership, "requires_recovery", None)
    return bool(predicate() if predicate is not None else ownership.cleanup_debts())


def _attach_preparation_recovery_owner(error: BaseException, ownership) -> None:
    """Attach aggregate authority only while cleanup remains pending."""
    if ownership is not None:
        if _ownership_requires_recovery(ownership):
            setattr(error, _PREPARATION_RECOVERY_OWNER_ATTRIBUTE, ownership)


class _PreparationRejected(Exception):
    """Carry one stable private preparation rejection."""

    def __init__(self, token: str) -> None:
        """Store a non-sensitive token."""
        super().__init__(token)
        self.token = token



class _PreparationCleanupPending(Exception):
    """Carry a stable rejection token while retaining aggregate recovery authority."""

    def __init__(self, token: str) -> None:
        """Store only the stable public-safe token."""
        super().__init__(token)
        self.token = token


def _settle_failed_preparation(
    generation: int,
    token: str,
    ownership,
):
    """Settle failed preparation or raise with exact pending recovery authority."""
    if ownership is None:
        return PrepareConfiguredResult(False, generation, errors=(token,))
    ownership.mark_pending()
    try:
        settled = ownership.settle()
    except (KeyboardInterrupt, SystemExit) as error:
        _attach_preparation_recovery_owner(error, ownership)
        raise
    except Exception:
        pending = _PreparationCleanupPending(token)
        _attach_preparation_recovery_owner(pending, ownership)
        raise pending from None
    if settled and not _ownership_requires_recovery(ownership):
        return PrepareConfiguredResult(False, generation, errors=(token,))
    pending = _PreparationCleanupPending(token)
    _attach_preparation_recovery_owner(pending, ownership)
    raise pending


def _recover_constructor_owner(error: BaseException):
    """Retrieve exact root authority retained by constructor failure."""
    from topsailai.hooks.configured_preparation_ownership import get_configured_root_recovery_owner

    return get_configured_root_recovery_owner(error)

class _PreparationBudget:
    """Aggregate bounded preparation counters across all configured Hooks."""

    __slots__ = ("max_scanned_entries", "max_candidates", "max_artifact_bytes", "scanned_entries", "candidates", "artifact_bytes")

    def __init__(self, *, max_scanned_entries: int, max_candidates: int, max_artifact_bytes: int) -> None:
        """Create one aggregate budget."""
        self.max_scanned_entries = max_scanned_entries
        self.max_candidates = max_candidates
        self.max_artifact_bytes = max_artifact_bytes
        self.scanned_entries = self.candidates = self.artifact_bytes = 0

    def add_scan(self, count: int = 1) -> None:
        """Account scanned entries."""
        self.scanned_entries += count
        if self.scanned_entries > self.max_scanned_entries:
            raise _PreparationRejected("capacity_exceeded")

    def add_candidate(self, count: int = 1) -> None:
        """Account discovered candidates."""
        self.candidates += count
        if self.candidates > self.max_candidates:
            raise _PreparationRejected("capacity_exceeded")

    def add_bytes(self, count: int) -> None:
        """Account captured bytes."""
        self.artifact_bytes += count
        if self.artifact_bytes > self.max_artifact_bytes:
            raise _PreparationRejected("capacity_exceeded")


@dataclass(frozen=True, slots=True)
class _PrivatePlan:
    """Hold one immutable unpublished configured plan summary."""

    summary: ConfiguredPlanSummary
    module_args: tuple[object, ...] = ()
    module_kwargs: tuple[tuple[str, object], ...] = ()
    script_artifact_identities: tuple[str, ...] = ()
    executable: object = None
    inject_hook_context: bool = False

    @property
    def hook_point(self):
        """Expose the passive hook identity."""
        return self.summary.hook_point

    def __getattr__(self, name):
        """Delegate passive summary fields."""
        return getattr(self.summary, name)


@dataclass(frozen=True, slots=True)
class _ModuleWork:
    """Bind one Hook module to its original candidate."""

    hook_index: int
    point: object
    inventory_root: Path
    candidate: ModuleCandidate


@dataclass(frozen=True, slots=True)
class _ScriptWork:
    """Bind one terminal Hook script to its capture request."""

    hook_index: int
    point: object
    entry: HookScriptEntry


@dataclass(frozen=True, slots=True)
class _CapturedWork:
    """Bind one work item to its exact sealed path."""

    work: _ModuleWork | _ScriptWork
    lease: object
    captured_path: Path


class PrivatePreparationImage:
    """Own one unpublished preparation aggregate until close."""

    __slots__ = ("accepted", "generation", "plans", "_ownership", "_adoption_lock", "_executable")

    def __init__(self, generation, ownership: PreparationOwnership, plans, *, executable=False) -> None:
        """Create an image after aggregate transfer."""
        self.accepted = True
        self.generation = generation
        self.plans = tuple(plans)
        self._ownership = ownership
        self._adoption_lock = threading.Lock()
        self._executable = executable

    def adopt(self, backend, *, receiver=None):
        """Move the exact prepared aggregate into one candidate without new I/O."""
        from topsailai.hooks.hook_point_plan_ownership import HookPointCandidate

        with self._adoption_lock:
            if not self._executable or self._ownership is None or len(self.plans) != 1:
                raise RuntimeError("prepared image is not adoptable")
            candidate = HookPointCandidate(backend)
            candidate._plan = self.plans[0].executable
            candidate._capture_owner = _PreparedCaptureOwner(self._ownership)
            if receiver is not None and not receiver(candidate):
                raise RuntimeError("candidate recovery handoff rejected")
            self._ownership = None
            return candidate

    def cleanup_debts(self):
        """Observe only still-owned preparation recovery debt."""
        with self._adoption_lock:
            return () if self._ownership is None else self._ownership.cleanup_debts()

    def retry_cleanup(self, debt_id):
        """Keep image retry authority only before candidate adoption."""
        with self._adoption_lock:
            if self._ownership is None:
                return False
            return (self._ownership.retry_prepared_cleanup(debt_id) if self._executable
                    else self._ownership.retry_cleanup(debt_id))

    def close(self):
        """Close idempotently through the aggregate authority."""
        with self._adoption_lock:
            if self._ownership is None:
                return ArtifactDisposeResult(True, True)
            settled = (self._ownership.settle_prepared_cleanup() if self._executable
                       else self._ownership.settle())
            return ArtifactDisposeResult(settled, False, not settled,
                () if settled else ("cleanup_pending",))


def prepare_private(runtime, configuration: ConfiguredHooks, scope, *, cancellation=None, _executable=False):
    """Discover, capture, probe, and plan configured modules without publication."""
    from topsailai.hooks.runtime import HookScope

    with runtime._lock:
        generation = runtime._registry.generation
        if type(configuration) is not ConfiguredHooks:
            return PrepareConfiguredResult(False, generation, errors=("invalid_configuration",))
        if type(scope) is not HookScope or scope._runtime is not runtime:
            return PrepareConfiguredResult(False, generation, errors=("invalid_scope",))
        if runtime._state != "running" or not runtime._owns_open_scope(scope):
            return PrepareConfiguredResult(False, generation, errors=("scope_closed",))
        trust = runtime._configured_trust
        if trust is None:
            return PrepareConfiguredResult(False, generation, errors=("trust_policy_missing",))
        if cancellation is not None and type(cancellation) is not threading.Event:
            return PrepareConfiguredResult(False, generation, errors=("invalid_configuration",))
        if cancellation is not None and cancellation.is_set():
            return PrepareConfiguredResult(False, generation, errors=("cancelled",))
        temp_root = Path(runtime._backend.script_temp_root)

    if not sys.platform.startswith("linux"):
        return PrepareConfiguredResult(False, generation, errors=("unsupported_platform",))
    operation = _Operation(configuration.policy.timeout_ms, cancellation)
    budget = _PreparationBudget(max_scanned_entries=configuration.policy.max_scanned_entries, max_candidates=configuration.policy.max_candidates, max_artifact_bytes=configuration.policy.max_artifact_bytes)
    if not configuration.hook_points:
        ownership = PreparationOwnership(None, operation.deadline, **({"retirement_cleanup_timeout_ms": configuration.policy.retirement_cleanup_timeout_ms} if _executable else {}))
        ownership.transfer_to_image()
        return PrivatePreparationImage(generation, ownership, ())
    ownership = None
    root_owner = None
    try:
        operation.checkpoint()
        ownership = PreparationOwnership(None, operation.deadline, **({"retirement_cleanup_timeout_ms": configuration.policy.retirement_cleanup_timeout_ms} if _executable else {}))
        if not trust.source_roots:
            raise _PreparationRejected("trust_rejected")
        temp_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        status = temp_root.lstat()
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.geteuid() or stat.S_IMODE(status.st_mode) != 0o700:
            raise _PreparationRejected("trust_rejected")
        host_root = validate_temporary_root(str(temp_root), Path(trust.source_roots[0]))
        if host_root is None:
            raise _PreparationRejected("trust_rejected")
        root_owner = ConfiguredRootOwner(host_root, ownership)
        artifact_root = root_owner.child("configured-artifacts")
        discovery_root = root_owner.child("configured-discovery")
        works = _build_work_sequence(configuration, operation, budget)
        if len(works) > _MAX_CAPTURE_ENTRIES * _MAX_CAPTURE_SHARDS:
            raise _PreparationRejected("capacity_exceeded")
        captured = _capture_work_sequence(works, ownership, artifact_root, operation, budget, trust, cancellation)
        plans = _probe_and_plan(configuration, captured, ownership, discovery_root, operation, budget, cancellation, **({"executable": True} if _executable else {}))
        operation.checkpoint()
        root_owner.revalidate()
        ownership.transfer_to_image()
        return PrivatePreparationImage(generation, ownership, plans, executable=_executable)
    except _PreparationRejected as exc:
        return _settle_failed_preparation(
            generation, exc.token, ownership
        )
    except (KeyboardInterrupt, SystemExit) as exc:
        constructor_owner = _recover_constructor_owner(exc)
        if ownership is not None and ownership.root_owner is None and constructor_owner is not None:
            ownership.adopt_root(constructor_owner)
        if ownership is not None:
            ownership.mark_pending()
            try:
                settled = ownership.settle()
            except BaseException:
                settled = False
            if not settled or _ownership_requires_recovery(ownership):
                _attach_preparation_recovery_owner(exc, ownership)
        raise
    except ValueError as exc:
        constructor_owner = _recover_constructor_owner(exc)
        if ownership is not None and ownership.root_owner is None and constructor_owner is not None:
            ownership.adopt_root(constructor_owner)
        token = "trust_rejected" if str(exc) == "trust_rejected" else "internal_error"
        return _settle_failed_preparation(
            generation, token, ownership
        )
    except Exception as exc:
        constructor_owner = _recover_constructor_owner(exc)
        if ownership is not None and ownership.root_owner is None and constructor_owner is not None:
            ownership.adopt_root(constructor_owner)
        return _settle_failed_preparation(
            generation, "internal_error", ownership
        )


def _build_work_sequence(configuration, operation, budget):
    """Enumerate every Hook before capture in deterministic module/script order."""
    works: list[_ModuleWork | _ScriptWork] = []
    for hook_index, point in enumerate(configuration.hook_points):
        operation.checkpoint()
        if point.module_folder is not None:
            inventory = _discover(point, operation, configuration, budget)
            budget.add_candidate(len(inventory.candidates))
            works.extend(_ModuleWork(hook_index, point, inventory.root, candidate) for candidate in inventory.candidates)
        if point.script is not None:
            result = discover_hook_script_entries(point.script.target, point.script.platform_policy)
            operation.checkpoint()
            if not result.accepted or len(result.entries) != 1:
                raise _PreparationRejected("binding_conflict" if result.accepted else "trust_rejected")
            works.append(_ScriptWork(hook_index, point, result.entries[0]))
            budget.add_candidate()
    return tuple(works)


def _capture_work_sequence(works, ownership, artifact_root, operation, budget, trust, cancellation):
    """Capture consecutive global batches using independent U07 shards."""
    if len(works) > _MAX_CAPTURE_ENTRIES * _MAX_CAPTURE_SHARDS:
        raise _PreparationRejected("capacity_exceeded")
    captured: list[_CapturedWork] = []
    for shard_index, start in enumerate(range(0, len(works), _MAX_CAPTURE_ENTRIES)):
        if shard_index >= _MAX_CAPTURE_SHARDS:
            raise _PreparationRejected("capacity_exceeded")
        operation.checkpoint()
        ownership.root_owner.revalidate()
        manager = ArtifactLeaseManager(artifact_root=str(artifact_root), trust=artifact_capture_trust(trust))
        candidate = manager.begin_candidate(deadline=operation.deadline)
        if not candidate.accepted or candidate.group is None:
            manager.close(deadline=operation.deadline)
            raise _PreparationRejected("capacity_exceeded")
        shard = CaptureShard(shard_index, manager, candidate.group)
        ownership.register_shard(shard)
        batch = works[start:start + _MAX_CAPTURE_ENTRIES]
        requests = tuple(_request_for_work(work) for work in batch)
        remaining = budget.max_artifact_bytes - budget.artifact_bytes
        if remaining <= 0:
            raise _PreparationRejected("capacity_exceeded")
        ownership.root_owner.revalidate()
        result = manager.capture(candidate.group, requests, policy=ArtifactCapturePolicy(timeout_ms=_remaining_ms(operation), max_entries=len(batch), max_total_bytes=remaining), cancellation=cancellation, deadline=operation.deadline)
        operation.checkpoint()
        ownership.root_owner.revalidate()
        if not result.accepted or result.lease is None:
            raise _PreparationRejected(_capture_token(result.errors))
        lease = result.lease
        shard.leases.append(lease)
        budget.add_bytes(lease.total_bytes)
        ownership.root_owner.revalidate()
        captured.extend(_map_capture_batch(batch, lease))
    return tuple(captured)


def _probe_and_plan(configuration, captured, ownership, discovery_root, operation, budget, cancellation, *, executable=False):
    """Probe captured module work by Hook and build passive plans."""
    by_hook: dict[int, list[_CapturedWork]] = {index: [] for index in range(len(configuration.hook_points))}
    for item in captured:
        by_hook[item.work.hook_index].append(item)
    plans = []
    for hook_index, point in enumerate(configuration.hook_points):
        operation.checkpoint()
        modules = [item for item in by_hook[hook_index] if isinstance(item.work, _ModuleWork)]
        scripts = [item for item in by_hook[hook_index] if isinstance(item.work, _ScriptWork)]
        entries = []
        if modules:
            storage = TemporaryStorageOwner(discovery_root)
            owner = _make_cleanup_owner(None, storage)
            ownership.register_module_owner(owner, point.hook_name)
            def probe_hook(session):
                """Probe all module candidates through one owned session."""
                result_entries = []
                for item in modules:
                    operation.checkpoint()
                    entry, result = session.probe(item.work.candidate, captured_path=item.captured_path, timeout_ms=_remaining_ms(operation))
                    operation.checkpoint()
                    if not result.cleanup_confirmed or session.state == "cleanup_pending":
                        raise _PreparationRejected("cleanup_pending")
                    if executable and (not entry.entry_valid or entry.load_status != "ready"
                            or result.status != "success" or entry.source_path != item.captured_path
                            or entry.logical_name != item.work.candidate.logical_name):
                        raise _PreparationRejected("binding_conflict")
                    result_entries.append((entry, item.lease.identity))
                if not session.close():
                    raise _PreparationRejected("cleanup_pending")
                return tuple(result_entries)
            root_owner = getattr(ownership, "root_owner", None)
            if root_owner is not None:
                root_owner.revalidate()
            result = _run_with_module_probe_session(root=modules[0].work.inventory_root, hook_name=point.hook_name, temp_root=str(discovery_root), owner=owner, operation=probe_hook, budget=make_discovery_budget_for_deadline(operation.deadline, cancellation))
            if result is None:
                raise _PreparationRejected("trust_rejected")
            entries.extend(result)
        failures = tuple(ConfiguredModuleFailure(f"{point.hook_name}:{entry.logical_name}", "invalid_entry" if entry.load_status == "invalid_entry" else "load_error") for entry, _ in entries if not entry.entry_valid)
        module_bindings = tuple(Binding(binding_id=f"module:{entry.logical_name}", event_name=point.definition.name, event_version=point.definition.major_version, handler_ref=f"{entry.logical_name}:main", max_concurrency=point.max_concurrency) for entry, _ in entries)
        script_result = None
        script_ids = tuple(item.lease.identity for item in scripts)
        if scripts:
            item = scripts[0]
            script_result = HookScriptDiscoveryResult(True, (HookScriptEntry(item.captured_path, item.work.entry.basename),))
        plan = build_hook_point_binding_plan_from_discovery(hook_point=point.hook_name, module_bindings=module_bindings, bindings_per_event=configuration.settings.limits.bindings_per_event, hook_script_configured=point.script is not None, discovery_result=script_result)
        if not plan.accepted:
            raise _PreparationRejected("binding_conflict")
        binding_ids = tuple(f"{point.hook_name}:{entry.logical_name}" for entry, _ in entries)
        if scripts:
            binding_ids += ("hook_script",)
        summary = ConfiguredPlanSummary(point.hook_name, point.definition.name, point.definition.major_version, binding_ids, tuple(sorted(set([identity for _, identity in entries] + list(script_ids)))), failures)
        complete = _build_executable_plan(point, by_hook[hook_index]) if executable else None
        plans.append(_PrivatePlan(summary, point.module_args, tuple(sorted(point.module_kwargs.items())), script_ids, complete, point.inject_hook_context))
    return tuple(plans)


def _request_for_work(work):
    """Convert a work record to one exact U07 request."""
    if isinstance(work, _ModuleWork):
        return ArtifactCaptureRequest(work.candidate.source_path, work.candidate.kind, work.candidate.logical_name)
    return ArtifactCaptureRequest(work.entry.source_path, "script", work.entry.basename, work.point.script.platform_policy)


def _map_capture_batch(batch, lease):
    """Map requests to captured paths positionally with complete validation."""
    if len(lease.entries) != len(batch):
        raise _PreparationRejected("artifact_rejected")
    root = lease.directory.resolve(strict=True)
    result = []
    for index, (work, request, entry) in enumerate(zip(batch, (_request_for_work(item) for item in batch), lease.entries, strict=True)):
        if entry.index != index or entry.kind != request.kind or entry.logical_name != request.logical_name or entry.validation.source_path != request.source_path:
            raise _PreparationRejected("artifact_rejected")
        relative = Path(entry.relative_path)
        if relative.is_absolute():
            raise _PreparationRejected("artifact_rejected")
        captured_path = lease.directory / relative
        try:
            resolved = captured_path.resolve(strict=True)
        except OSError as exc:
            raise _PreparationRejected("artifact_rejected") from exc
        if not resolved.is_relative_to(root):
            raise _PreparationRejected("artifact_rejected")
        result.append(_CapturedWork(work, lease, resolved))
    return tuple(result)


def _discover(point, operation, configuration, preparation_budget):
    """Purely enumerate one immutable U03 candidate inventory."""
    operation.checkpoint()
    policy = ModuleDiscoveryPolicy(timeout_ms=_remaining_ms(operation), max_scanned_entries=configuration.policy.max_scanned_entries, max_candidates=min(configuration.policy.max_candidates, configuration.policy.max_scanned_entries))
    try:
        inventory = enumerate_module_candidates_owned(Path(point.module_folder).resolve(strict=True), policy=policy, budget=make_discovery_budget_for_deadline(operation.deadline, operation.cancellation), scan_counter=preparation_budget.add_scan)
    except _DiscoveryRejected as exc:
        raise _PreparationRejected(_discovery_token(exc.token)) from None
    if not inventory.accepted:
        raise _PreparationRejected(_discovery_token(inventory.errors[0] if inventory.errors else "discovery_rejected"))
    operation.checkpoint()
    return inventory


def _batches(items, size):
    """Yield deterministic bounded batches."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _remaining_ms(operation):
    """Return remaining positive milliseconds."""
    remaining = int((operation.deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise _PreparationRejected("prepare_timeout")
    return remaining


def _capture_token(errors):
    """Map U07 capture errors to configured preparation tokens."""
    token = errors[0] if errors else "artifact_rejected"
    return {"artifact_capture_cancelled": "cancelled", "artifact_capture_timeout": "prepare_timeout", "artifact_capacity_exceeded": "capacity_exceeded", "unsupported_platform": "unsupported_platform"}.get(token, "artifact_rejected")


def _discovery_token(token):
    """Map U03 discovery classifications without exposing details."""
    if "timeout" in token:
        return "prepare_timeout"
    if "cancel" in token:
        return "cancelled"
    if any(value in token for value in ("capacity", "limit", "scanned entry", "candidate")):
        return "capacity_exceeded"
    if "cleanup" in token:
        return "cleanup_pending"
    return "discovery_rejected"


class _Operation:
    """Share one absolute deadline and latched cancellation."""

    def __init__(self, timeout_ms: int, cancellation: threading.Event | None) -> None:
        """Start one bounded operation."""
        self.deadline = time.monotonic() + timeout_ms / 1000
        self.cancellation = cancellation
        self.cancelled = False

    def checkpoint(self) -> None:
        """Reject cancellation or expiry."""
        self.cancelled = self.cancelled or bool(self.cancellation and self.cancellation.is_set())
        if self.cancelled:
            raise _PreparationRejected("cancelled")
        if time.monotonic() >= self.deadline:
            raise _PreparationRejected("prepare_timeout")


class _PreparedCaptureOwner:
    """Adapt exact aggregate custody to the candidate disposal protocol."""

    def __init__(self, ownership, *, prepared=True):
        """Retain the original aggregate, never reconstruct captured leases."""
        self._ownership = ownership
        self._prepared = prepared

    def close(self):
        """Start one bounded prepared retirement attempt."""
        settled = (self._ownership.settle_prepared_cleanup() if self._prepared
                   else self._ownership.settle())
        return ArtifactDisposeResult(settled, False, not settled,
            () if settled else ("cleanup_pending",))

    def cleanup_debts(self):
        """Expose exact aggregate-issued debt identities."""
        return self._ownership.cleanup_debts()

    def retry_cleanup(self, debt_id):
        """Retry only the exact debt with a fresh finite cleanup budget."""
        return (self._ownership.retry_prepared_cleanup(debt_id) if self._prepared
                else self._ownership.retry_cleanup(debt_id))


def _build_executable_plan(point, captured):
    """Build complete semantics solely from correlated original capture records."""
    from topsailai.hooks.hook_point_plan_contracts import (
        CapturedModule, CapturedScript, DefaultScriptHook, HookPointPlan, ModuleSource,
    )
    from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
    from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
    from topsailai.hooks.module_invocation_protocol import ModuleInvocation
    from topsailai.hooks.result_contracts import HandlerIdentity

    if len(captured) > 128 or (captured and len({item.lease.identity for item in captured}) != 1):
        raise _PreparationRejected("binding_conflict")
    modules, scripts = [], []
    for index, item in enumerate(captured):
        entry = item.lease.entries[index]
        work = item.work
        request = _request_for_work(work)
        if (entry.index, entry.kind, entry.logical_name, entry.validation.source_path) != (
                index, request.kind, request.logical_name, request.source_path):
            raise _PreparationRejected("artifact_rejected")
        if isinstance(work, _ModuleWork):
            logical = work.candidate.logical_name
            source = ModuleSource(f"{point.hook_name}:{logical}", work.candidate.source_path,
                logical, work.candidate.kind, f"{logical}:main",
                ModuleInvocation(point.module_args, dict(point.module_kwargs),
                                 inject_hook_context=point.inject_hook_context))
            modules.append(CapturedModule(HandlerIdentity(f"module-{index}", source.registered_name, "module"),
                source, item.lease.identity, index, entry.relative_path, item.captured_path,
                entry.content_sha256, entry.validation.deployment_sha256))
        else:
            scripts.append(CapturedScript(HandlerIdentity(f"script-{index}", "hook_script", "script"),
                item.lease.identity, index, work.entry.source_path, work.entry.basename,
                entry.relative_path, item.captured_path, entry.content_sha256, entry.validation.deployment_sha256))
    return HookPointPlan(point.hook_name, tuple(modules), DefaultScriptHook(tuple(scripts), point.script is not None),
        point.script.options if point.script else HookScriptExecutionOptions(),
        point.script.policy if point.script else HookScriptExecutionPolicy(),
        ArtifactCapturePolicy(max_entries=max(1, len(captured))),
        platform_policy=point.script.platform_policy if point.script else ExecutablePlatformPolicy("posix"))
