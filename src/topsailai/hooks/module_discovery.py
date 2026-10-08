"""Deterministic configured-module discovery with isolated entry probing."""

from __future__ import annotations

import importlib.machinery
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from topsailai.hooks.contracts import HookContext, HookEvent
from topsailai.hooks.module_discovery_policy import (
    DiscoveryBudget,
    ModuleDiscoveryPolicy,
    make_discovery_budget,
    validate_discovery_policy,
)
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import WorkerResult
from topsailai.hooks.temporary_storage import (
    TemporaryStorageOwner,
    validate_temporary_root,
)

_PROBE_HANDLER = "topsailai.hooks.module_discovery_worker:main"
_PROBE_TIMEOUT_MS = 5_000


@dataclass(frozen=True, slots=True)
class ModuleManifestEntry:
    """Describe one stable configured module and its isolated probe result."""

    logical_name: str
    source_path: Path
    stable_identity: tuple[str, str, str]
    entry_name: str
    entry_valid: bool
    load_status: str


@dataclass(frozen=True, slots=True)
class ModuleCleanupOwner:
    """Retain exact backend and storage authority for unresolved cleanup."""

    _backend: IsolatedProcessBackend | None
    _storage: TemporaryStorageOwner

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return current process, channel, and storage cleanup obligations."""
        backend_debts = () if self._backend is None else self._backend.cleanup_debts()
        return backend_debts + self._storage.cleanup_debts()

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry one exact obligation and settle storage only after the backend."""
        backend_debts = () if self._backend is None else self._backend.cleanup_debts()
        if any(debt.debt_id == debt_id for debt in backend_debts):
            if self._backend is None or not self._backend.retry_cleanup(debt_id):
                return False
            if self._backend.cleanup_debts():
                return False
            return self._storage.cleanup()
        if backend_debts:
            return False
        return self._storage.retry_cleanup(debt_id)


_INTERRUPTION_RECOVERY_OWNER_ATTRIBUTE = "__topsailai_module_cleanup_owner__"


def get_interruption_recovery_owner(error: BaseException) -> ModuleCleanupOwner | None:
    """Return the explicit discovery cleanup owner retained on an interruption."""
    owner = getattr(error, _INTERRUPTION_RECOVERY_OWNER_ATTRIBUTE, None)
    return owner if isinstance(owner, ModuleCleanupOwner) else None


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    """Return one immutable, atomically accepted or rejected module manifest."""

    accepted: bool
    entries: tuple[ModuleManifestEntry, ...] = ()
    errors: tuple[str, ...] = ()
    recovery_owner: ModuleCleanupOwner | None = None


def _attach_recovery_owner(error: BaseException, owner: ModuleCleanupOwner) -> None:
    """Attach exact recovery authority when owned cleanup remains unresolved."""
    if owner.cleanup_debts():
        setattr(error, _INTERRUPTION_RECOVERY_OWNER_ATTRIBUTE, owner)


def _cleanup_after_error(error: BaseException, owner: ModuleCleanupOwner) -> None:
    """Settle storage without allowing cleanup interruption to replace the primary."""
    backend = owner._backend
    if backend is not None and backend.cleanup_debts():
        owner._storage.retain_cleanup_debt()
    else:
        try:
            owner._storage.cleanup()
        except BaseException:
            pass
    _attach_recovery_owner(error, owner)


def _cleanup_or_propagate(owner: ModuleCleanupOwner) -> bool:
    """Propagate cleanup interruption with exact recovery authority attached."""
    try:
        return owner._storage.cleanup()
    except BaseException as error:
        _attach_recovery_owner(error, owner)
        raise


def build_module_manifest(
    module_folder: os.PathLike[str] | str,
    hook_point: str,
    *,
    temp_root: str,
    policy: ModuleDiscoveryPolicy = ModuleDiscoveryPolicy(),
    cancellation: threading.Event | None = None,
) -> ModuleManifest:
    """Discover direct module files within one bounded cooperative operation."""
    if not validate_discovery_policy(policy):
        return ModuleManifest(False, errors=("invalid discovery policy",))
    if cancellation is not None and not isinstance(cancellation, threading.Event):
        return ModuleManifest(False, errors=("invalid discovery cancellation",))
    if not isinstance(module_folder, (str, os.PathLike)) or type(hook_point) is not str or not hook_point:
        return ModuleManifest(False, errors=("invalid module configuration",))

    budget = make_discovery_budget(policy.timeout_ms, cancellation)
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    try:
        root = _canonical_root(module_folder, budget)
    except _DiscoveryRejected as error:
        return _rejected(error.token)
    if root is None:
        return _rejected("invalid module configuration")

    try:
        candidates = _enumerate_candidates(root, policy=policy, budget=budget)
    except _DiscoveryRejected as error:
        return _rejected(error.token)
    names = [logical_name for logical_name, _ in candidates]
    if len(names) != len(set(names)):
        return _rejected("duplicate module identity")
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    ordered_candidates = sorted(candidates, key=lambda item: item[0])
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)

    host_root = validate_temporary_root(temp_root, root)
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    if host_root is None:
        return _rejected("invalid discovery temp root")
    if not ordered_candidates:
        return ModuleManifest(True)

    storage = TemporaryStorageOwner(host_root)
    owner = _make_cleanup_owner(None, storage)
    entries: list[ModuleManifestEntry] = []
    try:
        rejection = budget.rejection()
        if rejection is not None:
            return _finish_rejection(owner, entries, rejection)
        allocated = storage.allocate()
        rejection = budget.rejection()
        if rejection is not None:
            return _finish_rejection(owner, entries, rejection)
        if not allocated:
            token = (
                "module discovery cleanup pending"
                if owner.cleanup_debts()
                else "invalid discovery temp root"
            )
            return _rejected(token, recovery_owner=owner if owner.cleanup_debts() else None)

        backend = IsolatedProcessBackend(temp_root=str(storage.path))
        owner = _make_cleanup_owner(backend, storage)
        rejection = budget.rejection()
        if rejection is not None:
            return _finish_rejection(owner, entries, rejection)
        for logical_name, source_path in ordered_candidates:
            rejection = budget.rejection()
            if rejection is not None:
                return _finish_rejection(owner, entries, rejection)
            remaining_ms = budget.remaining_ms()
            if remaining_ms < 1:
                return _finish_rejection(owner, entries, "module discovery timeout")
            timeout_ms = min(_PROBE_TIMEOUT_MS, remaining_ms)
            aggregate_binding = remaining_ms <= _PROBE_TIMEOUT_MS
            entry, result = _probe_candidate(
                backend,
                root,
                hook_point,
                logical_name,
                source_path,
                timeout_ms,
            )
            _append_manifest_entry(entries, entry)
            if not result.cleanup_confirmed or backend.cleanup_debts():
                storage.retain_cleanup_debt()
                return _rejected(
                    "module discovery cleanup pending",
                    entries,
                    owner,
                )
            rejection = budget.rejection()
            if rejection is not None:
                return _finish_rejection(owner, entries, rejection)
            if result.status == "unsupported_backend":
                return _finish_rejection(
                    owner, entries, "module discovery unsupported blocking io"
                )
            if result.status == "timeout" and aggregate_binding:
                return _finish_rejection(owner, entries, "module discovery timeout")

        if not _cleanup_or_propagate(owner):
            return _rejected("module discovery cleanup pending", entries, owner)
        rejection = budget.rejection()
        if rejection is not None:
            return _rejected(rejection, entries)
        return ModuleManifest(True, tuple(entries))
    except BaseException as error:
        _cleanup_after_error(error, owner)
        raise


def _finish_rejection(
    owner: ModuleCleanupOwner,
    entries: list[ModuleManifestEntry],
    token: str,
) -> ModuleManifest:
    """Settle owned storage and return a complete rejection classification."""
    if not _cleanup_or_propagate(owner):
        return _rejected("module discovery cleanup pending", entries, owner)
    return _rejected(token, entries)


def _rejected(
    token: str,
    entries: list[ModuleManifestEntry] | tuple[ModuleManifestEntry, ...] = (),
    recovery_owner: ModuleCleanupOwner | None = None,
) -> ModuleManifest:
    """Build one stable rejected manifest with a bounded diagnostic prefix."""
    return ModuleManifest(False, tuple(entries), (token,), recovery_owner)


def _make_cleanup_owner(
    backend: IsolatedProcessBackend | None,
    storage: TemporaryStorageOwner,
) -> ModuleCleanupOwner:
    """Create the exact owner used across one discovery lifecycle."""
    return ModuleCleanupOwner(backend, storage)


def _append_manifest_entry(
    entries: list[ModuleManifestEntry], entry: ModuleManifestEntry
) -> None:
    """Append one probed entry inside the protected discovery lifecycle."""
    entries.append(entry)


def _canonical_root(
    module_folder: os.PathLike[str] | str,
    budget: DiscoveryBudget,
) -> Path | None:
    """Resolve one existing directory with checks at each filesystem boundary."""
    try:
        root = Path(module_folder).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        _checkpoint(budget)
        return None
    _checkpoint(budget)
    try:
        is_directory = root.is_dir()
    except OSError:
        _checkpoint(budget)
        return None
    _checkpoint(budget)
    return root if is_directory else None


class _DiscoveryRejected(Exception):
    """Carry one stable pre-probe discovery rejection."""

    def __init__(self, token: str) -> None:
        """Store the non-sensitive stable token."""
        self.token = token


class _CandidatePathEscape(Exception):
    """Reject a candidate observed outside the configured canonical root."""


def _list_children(root: Path) -> Iterator[Path]:
    """Open an incremental direct-child iterator at an observable boundary."""
    return root.iterdir()


@contextmanager
def _opening_iterator(
    root: Path, budget: DiscoveryBudget
) -> Iterator[Iterator[Path]]:
    """Acquire and transfer one iterator under continuous cleanup protection."""
    children: Iterator[Path] | None = None
    iterator: Iterator[Path] | None = None
    body_failed = False
    try:
        try:
            children = _list_children(root)
        except OSError as error:
            _checkpoint(budget)
            raise _DiscoveryRejected("module enumeration unavailable") from error
        try:
            iterator = iter(children)
        except OSError as error:
            _checkpoint(budget)
            raise _DiscoveryRejected("module enumeration unavailable") from error
        _checkpoint(budget)
        yield iterator
    except BaseException:
        body_failed = True
        raise
    finally:
        close_target = iterator if iterator is not None else children
        close = getattr(close_target, "close", None)
        if close is not None:
            try:
                close()
            except OSError as error:
                if not body_failed:
                    _checkpoint(budget)
                    raise _DiscoveryRejected("module enumeration unavailable") from error
        if not body_failed:
            _checkpoint(budget)


def _resolve_candidate(candidate: Path) -> Path:
    """Resolve one candidate through an observable filesystem boundary."""
    return candidate.resolve(strict=True)


def _checkpoint(budget: DiscoveryBudget) -> None:
    """Raise the current cooperative liveness rejection at one boundary."""
    rejection = budget.rejection()
    if rejection is not None:
        raise _DiscoveryRejected(rejection)


def _enumerate_candidates(
    root: Path,
    *,
    policy: ModuleDiscoveryPolicy | None = None,
    budget: DiscoveryBudget | None = None,
) -> list[tuple[str, Path]]:
    """Incrementally return a bounded direct regular-file candidate inventory."""
    active_policy = policy or ModuleDiscoveryPolicy()
    active_budget = budget or make_discovery_budget(active_policy.timeout_ms, None)
    candidates: list[tuple[str, Path]] = []
    suffixes = tuple(
        sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True)
    )
    _checkpoint(active_budget)
    with _opening_iterator(root, active_budget) as iterator:
        _scan_candidates(
            iterator,
            root,
            active_policy,
            active_budget,
            suffixes,
            candidates,
        )
    return candidates


def _scan_candidates(
    iterator: Iterator[Path],
    root: Path,
    policy: ModuleDiscoveryPolicy,
    budget: DiscoveryBudget,
    suffixes: tuple[str, ...],
    candidates: list[tuple[str, Path]],
) -> None:
    """Consume one bounded direct-child iterator into a candidate inventory."""
    scanned = 0
    while True:
        _checkpoint(budget)
        try:
            child = next(iterator)
        except StopIteration:
            return
        except OSError as error:
            _checkpoint(budget)
            raise _DiscoveryRejected("module enumeration unavailable") from error
        _checkpoint(budget)
        scanned += 1
        if scanned > policy.max_scanned_entries:
            raise _DiscoveryRejected("module discovery scanned entry limit exceeded")
        if child.name.startswith("."):
            continue
        try:
            is_symlink = child.is_symlink()
        except OSError:
            _checkpoint(budget)
            continue
        _checkpoint(budget)
        if is_symlink:
            continue
        try:
            is_file = child.is_file()
        except OSError:
            _checkpoint(budget)
            continue
        _checkpoint(budget)
        if not is_file:
            continue
        logical_name = _logical_name(child.name, suffixes)
        if logical_name is None or logical_name == "__init__" or not logical_name.isidentifier():
            continue
        if len(candidates) >= policy.max_candidates:
            raise _DiscoveryRejected("module discovery candidate limit exceeded")
        try:
            resolved = _resolve_candidate(child)
        except OSError as error:
            _checkpoint(budget)
            raise _DiscoveryRejected("module enumeration unavailable") from error
        _checkpoint(budget)
        if not resolved.is_relative_to(root):
            raise _DiscoveryRejected("module path escapes configured root")
        candidates.append((logical_name, resolved))


def _logical_name(filename: str, extension_suffixes: tuple[str, ...]) -> str | None:
    """Remove one complete recognized source or interpreter extension suffix."""
    if filename.endswith(".py"):
        return filename[:-3]
    for suffix in extension_suffixes:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return None


def _probe_candidate(
    backend: IsolatedProcessBackend,
    root: Path,
    hook_point: str,
    logical_name: str,
    source_path: Path,
    timeout_ms: int = _PROBE_TIMEOUT_MS,
) -> tuple[ModuleManifestEntry, WorkerResult]:
    """Probe one candidate while preserving the original worker classification."""
    identity = (hook_point, str(root), logical_name)
    context = HookContext(
        event=HookEvent(
            event_id=uuid.uuid4().hex,
            name="hooks.module_discovery.probe",
            major_version=1,
            owner_id="module_discovery",
            scope_id="module_discovery",
            operation_id=uuid.uuid4().hex,
            parent_operation_id=None,
            sequence=0,
            timestamp="",
            layer="hooks",
            purpose="entry_validation",
            payload={"source_path": str(source_path), "logical_name": logical_name},
        ),
        delivery_id=uuid.uuid4().hex,
        binding_id="module_discovery",
        registry_generation=0,
        remaining_budget_ms=timeout_ms,
    )
    result = backend.execute(_PROBE_HANDLER, context, timeout_ms)
    load_status = "load_error"
    entry_valid = False
    if result.cleanup_confirmed and result.status == "success" and hasattr(result.value, "get"):
        reported_status = result.value.get("load_status")
        reported_valid = result.value.get("entry_valid")
        if reported_status in ("ready", "invalid_entry", "load_error"):
            load_status = reported_status
        if type(reported_valid) is bool:
            entry_valid = reported_valid
    if not result.cleanup_confirmed:
        load_status = "cleanup_pending"
        entry_valid = False
    entry = ModuleManifestEntry(
        logical_name=logical_name,
        source_path=source_path,
        stable_identity=identity,
        entry_name="main",
        entry_valid=entry_valid,
        load_status=load_status,
    )
    return entry, result
