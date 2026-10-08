"""Public contracts for framework-owned terminal hook-script execution."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from topsailai.hooks.contracts import Binding, HookContext, HookStatus
from topsailai.hooks.hook_script_discovery import HookScriptEntry


@dataclass(frozen=True, slots=True)
class HookScriptBinding:
    """Describe the unique immutable framework-owned terminal binding."""

    binding_id: str
    hook_point: str
    priority: int
    after: tuple[str, ...]
    framework_owned: bool
    terminal: bool
    configured: bool
    entries: tuple[HookScriptEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class HookPointBindingPlan:
    """Return an atomically accepted immutable hook-point binding plan."""

    accepted: bool
    bindings: tuple[Binding | HookScriptBinding, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HookScriptSettlement:
    """Describe metadata-only settlement of the reserved script binding."""

    status: str
    entry_results: tuple[object, ...] = ()
    started: bool = False
    error_category: str | None = None


@dataclass(frozen=True, slots=True)
class HookScriptExecutionOptions:
    """Provide literal, already-admitted process execution options."""

    argv: tuple[str, ...] = ()
    cwd: Path | None = None
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class HookScriptExecutionPolicy:
    """Bound one synchronous script batch and every retained byte stream."""

    entry_timeout_ms: int = 1000
    hook_timeout_ms: int = 1000
    cleanup_timeout_ms: int = 1000
    terminate_grace_ms: int = 100
    stdin_limit_bytes: int = 65536
    stdout_limit_bytes: int = 16384
    stderr_limit_bytes: int = 16384
    output_total_limit_bytes: int = 65536
    max_entries: int = 32
    argument_environment_limit_bytes: int = 65536
    result_limit_bytes: int = 16384


@dataclass(frozen=True, slots=True)
class HookScriptEntryResult:
    """Report bounded execution and cleanup facts for one planned entry."""

    entry_index: int
    basename: str
    status: HookStatus
    started: bool
    exit_code: int | None = None
    duration_ms: int = 0
    error_category: str | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_dropped: int = 0
    stderr_dropped: int = 0
    cleanup_confirmed: bool = True
    cleanup_debt: str | None = None


class HookScriptRunner(Protocol):
    """Define the trusted synchronous adapter boundary used by orchestration."""

    def execute_entry(
        self,
        *,
        entry_index: int,
        entry: HookScriptEntry,
        context: HookContext,
        options: HookScriptExecutionOptions,
        policy: HookScriptExecutionPolicy,
        execution_deadline: float,
        cleanup_deadline: float,
        output_remaining_bytes: int,
        cancellation: threading.Event,
    ) -> HookScriptEntryResult:
        """Execute one admitted entry and return bounded observed facts."""
        ...

    def current_result(self, entry_index: int) -> HookScriptEntryResult:
        """Return the authoritative recovery snapshot for one entry."""
        ...

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return cleanup debts still owned by this runner."""
        ...

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry cleanup for one exact caller-selected debt."""
        ...
