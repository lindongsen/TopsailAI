"""Private isolated module probe implementation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.contracts import HookContext, HookEvent
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import WorkerResult

PROBE_HANDLER = "topsailai.hooks.module_discovery_worker:main"
PROBE_TIMEOUT_MS = 5_000


@dataclass(frozen=True, slots=True)
class ModuleManifestEntry:
    """Describe one stable configured module and its isolated probe result."""

    logical_name: str
    source_path: Path
    stable_identity: tuple[str, str, str]
    entry_name: str
    entry_valid: bool
    load_status: str


def probe_candidate(
    backend: IsolatedProcessBackend,
    root: Path,
    hook_name: str,
    logical_name: str,
    source_path: Path,
    timeout_ms: int = PROBE_TIMEOUT_MS,
    *,
    handler_ref: str = PROBE_HANDLER,
) -> tuple[ModuleManifestEntry, WorkerResult]:
    """Probe one candidate while preserving the original worker classification."""
    identity = (hook_name, str(root), logical_name)
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
    result = backend.execute(handler_ref, context, timeout_ms)
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
