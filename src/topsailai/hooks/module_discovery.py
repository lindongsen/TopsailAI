"""Deterministic configured-module discovery with isolated entry probing."""

from __future__ import annotations

import importlib.machinery
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal

from topsailai.hooks.module_discovery_probe import (
    ModuleManifestEntry,
    PROBE_HANDLER as _PROBE_HANDLER,
    PROBE_TIMEOUT_MS as _PROBE_TIMEOUT_MS,
    probe_candidate as _probe_candidate_impl,
)
from topsailai.hooks.configured_contracts import is_valid_hook_name
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


def _probe_candidate(
    backend: IsolatedProcessBackend,
    root: Path,
    hook_name: str,
    logical_name: str,
    source_path: Path,
    timeout_ms: int = _PROBE_TIMEOUT_MS,
) -> tuple[ModuleManifestEntry, WorkerResult]:
    """Probe one candidate through the module-local compatibility seam."""
    return _probe_candidate_impl(
        backend,
        root,
        hook_name,
        logical_name,
        source_path,
        timeout_ms,
        handler_ref=_PROBE_HANDLER,
    )

@dataclass(frozen=True, slots=True)
class ModuleCandidate:
    """Describe one bounded module candidate before isolated probing."""

    logical_name: str
    source_path: Path
    kind: Literal["python_source", "python_extension"]

@dataclass(frozen=True, slots=True)
class ModuleCandidateInventory:
    """Return an immutable, atomically accepted candidate inventory."""

    accepted: bool
    root: Path | None = None
    candidates: tuple[ModuleCandidate, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(slots=True)
class ModuleCleanupOwner:
    """Retain exact backend and storage authority for unresolved cleanup."""

    _backend: IsolatedProcessBackend | None
    _storage: TemporaryStorageOwner

    def bind_backend(self, backend: IsolatedProcessBackend) -> None:
        """Bind the one backend to this stable cleanup owner exactly once."""
        if self._backend is not None:
            raise RuntimeError("module cleanup backend is already bound")
        self._backend = backend

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


class ModuleProbeSession:
    """Own one isolated probe lifecycle and forbid successors after cleanup debt."""

    __slots__ = ("_root", "_hook_name", "_backend", "_storage", "_owner", "_state")

    def __init__(
        self,
        root: Path,
        hook_name: str,
        backend: IsolatedProcessBackend | None,
        storage: TemporaryStorageOwner,
        *,
        owner: ModuleCleanupOwner,
    ) -> None:
        """Capture the caller-owned cleanup authority without constructing a fallback."""
        if owner._storage is not storage or owner._backend is not backend:
            raise ValueError("module probe session owner does not match resources")
        self._root = root
        self._hook_name = hook_name
        self._backend = backend
        self._storage = storage
        self._owner = owner
        self._state = "open"

    @property
    def recovery_owner(self) -> ModuleCleanupOwner:
        """Return the sole cleanup authority for this session."""
        return self._owner

    @property
    def state(self) -> str:
        """Return the owned session lifecycle state."""
        return self._state

    def probe(
        self,
        candidate: ModuleCandidate,
        *,
        captured_path: Path,
        timeout_ms: int = _PROBE_TIMEOUT_MS,
    ) -> tuple[ModuleManifestEntry, WorkerResult]:
        """Probe only the explicitly supplied captured path."""
        if self._state != "open":
            raise RuntimeError("module probe session is not open")
        if not isinstance(captured_path, Path):
            raise TypeError("captured_path must be a Path")
        path = captured_path
        if self._backend is None:
            raise RuntimeError("module probe session has pending cleanup")
        try:
            entry, result = _probe_candidate(
                self._backend,
                self._root,
                self._hook_name,
                candidate.logical_name,
                path,
                timeout_ms,
            )
        except BaseException as error:
            self._storage.retain_cleanup_debt()
            self._state = "cleanup_pending"
            _attach_recovery_owner(error, self._owner)
            raise
        if not result.cleanup_confirmed or self._backend.cleanup_debts():
            self._storage.retain_cleanup_debt()
            self._state = "cleanup_pending"
        return entry, result

    def close(self) -> bool:
        """Settle storage only after all backend cleanup is confirmed."""
        if self._state == "closed":
            return True
        try:
            if self._backend is not None and self._backend.cleanup_debts():
                self._storage.retain_cleanup_debt()
                self._state = "cleanup_pending"
                return False
            settled = self._storage.cleanup()
        except BaseException as error:
            self._storage.retain_cleanup_debt()
            self._state = "cleanup_pending"
            _attach_recovery_owner(error, self._owner)
            raise
        if settled:
            self._state = "closed"
        else:
            self._state = "cleanup_pending"
        return settled


def _run_with_module_probe_session(
    *,
    root: Path,
    hook_name: str,
    temp_root: str,
    owner: ModuleCleanupOwner,
    operation: Callable[[ModuleProbeSession], object],
    budget: DiscoveryBudget | None = None,
) -> object | None:
    """Acquire resources and run all ownership-sensitive work in one continuation."""
    storage = owner._storage
    try:
        if budget is not None:
            _checkpoint(budget)
        allocated = storage.allocate()
        if budget is not None:
            _checkpoint(budget)
        if not allocated:
            if not storage.cleanup_debts():
                return None
            session = ModuleProbeSession(root, hook_name, None, storage, owner=owner)
            session._state = "cleanup_pending"
            return operation(session)
        backend = IsolatedProcessBackend(temp_root=str(storage.path))
        owner.bind_backend(backend)
        if budget is not None:
            _checkpoint(budget)
        session = ModuleProbeSession(root, hook_name, backend, storage, owner=owner)
        return operation(session)
    except BaseException as error:
        _cleanup_after_error(error, owner)
        raise


def open_module_probe_session(
    *,
    root: Path,
    hook_name: str,
    temp_root: str,
    budget: DiscoveryBudget | None = None,
) -> ModuleProbeSession | None:
    """Open a compatible session; ownership-sensitive callers use the continuation API."""
    host_root = validate_temporary_root(temp_root, root)
    if budget is not None:
        _checkpoint(budget)
    if host_root is None:
        return None
    storage = TemporaryStorageOwner(host_root)
    owner = _make_cleanup_owner(None, storage)
    result = _run_with_module_probe_session(
        root=root, hook_name=hook_name, temp_root=temp_root, owner=owner,
        operation=lambda session: session, budget=budget,
    )
    return result if isinstance(result, ModuleProbeSession) else None


def _build_manifest_with_session(
    session: ModuleProbeSession,
    *,
    inventory: ModuleCandidateInventory,
    budget: DiscoveryBudget,
) -> ModuleManifest:
    """Build the manifest while the acquisition owner remains continuously reachable."""
    entries: list[ModuleManifestEntry] = []
    owner = session.recovery_owner
    if session.state == "cleanup_pending":
        return _rejected("module discovery cleanup pending", recovery_owner=owner)
    for candidate in inventory.candidates:
        rejection = budget.rejection()
        if rejection is not None:
            if not session.close():
                return _rejected("module discovery cleanup pending", entries, owner)
            return _rejected(rejection, entries)
        remaining_ms = budget.remaining_ms()
        if remaining_ms < 1:
            if not session.close():
                return _rejected("module discovery cleanup pending", entries, owner)
            return _rejected("module discovery timeout", entries)
        timeout_ms = min(_PROBE_TIMEOUT_MS, remaining_ms)
        aggregate_binding = remaining_ms <= _PROBE_TIMEOUT_MS
        entry, result = session.probe(
            candidate, captured_path=candidate.source_path, timeout_ms=timeout_ms
        )
        _append_manifest_entry(entries, entry)
        if session.state == "cleanup_pending":
            return _rejected("module discovery cleanup pending", entries, owner)
        rejection = budget.rejection()
        if rejection is not None:
            if not session.close():
                return _rejected("module discovery cleanup pending", entries, owner)
            return _rejected(rejection, entries)
        if result.status == "unsupported_backend":
            if not session.close():
                return _rejected("module discovery cleanup pending", entries, owner)
            return _rejected("module discovery unsupported blocking io", entries)
        if result.status == "timeout" and aggregate_binding:
            if not session.close():
                return _rejected("module discovery cleanup pending", entries, owner)
            return _rejected("module discovery timeout", entries)
    if not session.close():
        return _rejected("module discovery cleanup pending", entries, owner)
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection, entries)
    return ModuleManifest(True, tuple(entries))


def build_module_manifest(
    module_folder: os.PathLike[str] | str,
    hook_name: str,
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
    if not isinstance(module_folder, (str, os.PathLike)):
        return ModuleManifest(False, errors=("invalid module configuration",))
    if not is_valid_hook_name(hook_name):
        return ModuleManifest(False, errors=("invalid hook name",))
    budget = make_discovery_budget(policy.timeout_ms, cancellation)
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    inventory = enumerate_module_candidates_owned(module_folder, policy=policy, budget=budget)
    if not inventory.accepted:
        return _rejected(inventory.errors[0] if inventory.errors else "invalid module configuration")
    root = inventory.root
    if root is None:
        return _rejected("invalid module configuration")
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    host_root = validate_temporary_root(temp_root, root)
    rejection = budget.rejection()
    if rejection is not None:
        return _rejected(rejection)
    if host_root is None:
        return _rejected("invalid discovery temp root")
    if not inventory.candidates:
        return ModuleManifest(True)
    owner = _make_cleanup_owner(None, TemporaryStorageOwner(host_root))
    try:
        result = _run_with_module_probe_session(
            root=root, hook_name=hook_name, temp_root=temp_root, owner=owner,
            operation=lambda session: _build_manifest_with_session(
                session, inventory=inventory, budget=budget
            ), budget=budget,
        )
        if result is None:
            return _rejected("invalid discovery temp root")
        return result  # type: ignore[return-value]
    except _DiscoveryRejected as error:
        if owner.cleanup_debts():
            _cleanup_after_error(error, owner)
            return _rejected("module discovery cleanup pending", recovery_owner=owner)
        return _rejected(error.token)
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
    scan_counter: Callable[[], None] | None = None,
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
            scan_counter=scan_counter,
        )
    return candidates


def enumerate_module_candidates_owned(
    module_folder: os.PathLike[str] | str,
    *,
    policy: ModuleDiscoveryPolicy = ModuleDiscoveryPolicy(),
    budget: DiscoveryBudget | None = None,
    scan_counter: Callable[[], None] | None = None,
) -> ModuleCandidateInventory:
    """Enumerate a canonical bounded module inventory without probing candidates."""
    if not validate_discovery_policy(policy):
        return ModuleCandidateInventory(False, errors=("invalid discovery policy",))
    active_budget = budget or make_discovery_budget(policy.timeout_ms, None)
    try:
        root = _canonical_root(module_folder, active_budget)
        if root is None:
            return ModuleCandidateInventory(False, errors=("invalid module configuration",))
        candidates = _enumerate_candidates(
            root, policy=policy, budget=active_budget, scan_counter=scan_counter
        )
    except _DiscoveryRejected as error:
        return ModuleCandidateInventory(False, errors=(error.token,))
    names = [logical_name for logical_name, _ in candidates]
    if len(names) != len(set(names)):
        return ModuleCandidateInventory(False, root=root, errors=("duplicate module identity",))
    ordered = tuple(
        ModuleCandidate(logical_name, source_path, _candidate_kind(source_path))
        for logical_name, source_path in sorted(candidates, key=lambda item: item[0])
    )
    return ModuleCandidateInventory(True, root=root, candidates=ordered)


def _candidate_kind(source_path: Path) -> Literal["python_source", "python_extension"]:
    """Return the existing U03 kind vocabulary for one recognized candidate."""
    if source_path.name.endswith(".py"):
        return "python_source"
    suffixes = tuple(sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True))
    if any(source_path.name.endswith(suffix) for suffix in suffixes):
        return "python_extension"
    raise ValueError("unrecognized module candidate suffix")


def _scan_candidates(
    iterator: Iterator[Path],
    root: Path,
    policy: ModuleDiscoveryPolicy,
    budget: DiscoveryBudget,
    suffixes: tuple[str, ...],
    candidates: list[tuple[str, Path]],
    *,
    scan_counter: Callable[[], None] | None = None,
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
        if scan_counter is not None:
            scan_counter()
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
