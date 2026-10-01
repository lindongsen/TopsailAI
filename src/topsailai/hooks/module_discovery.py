"""Deterministic configured-module discovery with isolated entry probing."""

from __future__ import annotations

import importlib.machinery
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.contracts import HookContext, HookEvent
from topsailai.hooks.process_backend import IsolatedProcessBackend

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
    """Retain exact backend authority for unresolved discovery cleanup."""

    _backend: IsolatedProcessBackend

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return the backend's current cleanup obligations."""
        return self._backend.cleanup_debts()

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry one exact backend-owned cleanup obligation."""
        return self._backend.retry_cleanup(debt_id)


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


def build_module_manifest(module_folder: os.PathLike[str] | str, hook_point: str) -> ModuleManifest:
    """Discover direct module files and validate each entry in an isolated worker."""
    root = _canonical_root(module_folder)
    if root is None or type(hook_point) is not str or not hook_point:
        return ModuleManifest(False, errors=("invalid module configuration",))
    try:
        candidates = _enumerate_candidates(root)
    except OSError:
        return ModuleManifest(False, errors=("module enumeration unavailable",))
    except _CandidatePathEscape:
        return ModuleManifest(False, errors=("module path escapes configured root",))
    names = [logical_name for logical_name, _ in candidates]
    if len(names) != len(set(names)):
        return ModuleManifest(False, errors=("duplicate module identity",))
    if not candidates:
        return ModuleManifest(True)

    backend = IsolatedProcessBackend(temp_root=str(root))
    entries: list[ModuleManifestEntry] = []
    for logical_name, source_path in sorted(candidates, key=lambda item: item[0]):
        try:
            entry, cleanup_confirmed = _probe_candidate(
                backend, root, hook_point, logical_name, source_path
            )
        except BaseException as error:
            if backend.cleanup_debts():
                setattr(
                    error,
                    _INTERRUPTION_RECOVERY_OWNER_ATTRIBUTE,
                    ModuleCleanupOwner(backend),
                )
            raise
        entries.append(entry)
        if not cleanup_confirmed:
            return ModuleManifest(
                True,
                tuple(entries),
                recovery_owner=ModuleCleanupOwner(backend),
            )
    return ModuleManifest(True, tuple(entries))


def _canonical_root(module_folder: os.PathLike[str] | str) -> Path | None:
    """Resolve one existing directory without accepting an invalid path value."""
    if not isinstance(module_folder, (str, os.PathLike)):
        return None
    try:
        root = Path(module_folder).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    return root if root.is_dir() else None


class _CandidatePathEscape(Exception):
    """Reject a candidate observed outside the configured canonical root."""


def _list_children(root: Path) -> tuple[Path, ...]:
    """Enumerate direct children through an observable filesystem boundary."""
    return tuple(root.iterdir())


def _resolve_candidate(candidate: Path) -> Path:
    """Resolve one candidate through an observable filesystem boundary."""
    return candidate.resolve(strict=True)


def _enumerate_candidates(root: Path) -> list[tuple[str, Path]]:
    """Return recognized direct regular-file candidates without following links."""
    candidates: list[tuple[str, Path]] = []
    children = _list_children(root)
    suffixes = tuple(
        sorted(
            importlib.machinery.EXTENSION_SUFFIXES,
            key=len,
            reverse=True,
        )
    )
    for child in children:
        if child.name.startswith(".") or child.is_symlink():
            continue
        try:
            if not child.is_file():
                continue
        except OSError:
            continue
        logical_name = _logical_name(child.name, suffixes)
        if logical_name is None or logical_name == "__init__" or not logical_name.isidentifier():
            continue
        resolved = _resolve_candidate(child)
        if not resolved.is_relative_to(root):
            raise _CandidatePathEscape
        candidates.append((logical_name, resolved))
    return candidates


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
) -> tuple[ModuleManifestEntry, bool]:
    """Probe one candidate and report whether owned cleanup is settled."""
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
        remaining_budget_ms=_PROBE_TIMEOUT_MS,
    )
    result = backend.execute(_PROBE_HANDLER, context, _PROBE_TIMEOUT_MS)
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
    return entry, result.cleanup_confirmed
