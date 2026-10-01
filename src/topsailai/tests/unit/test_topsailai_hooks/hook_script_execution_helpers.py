"""Test-only records and runner for hook-script execution RED contracts.

Author: DawsonLin
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from topsailai.hooks import HookContext, HookEvent, HookScriptEntry, HookStatus


@dataclass
class Clock:
    """Provide explicitly controlled monotonic time."""

    value: float = 0.0

    def __call__(self) -> float:
        """Return time without advancing it."""
        return self.value


@dataclass
class CallbackClock(Clock):
    """Set cancellation on the first read armed after an entry returns."""

    callback: Callable[[], None] | None = None
    armed: bool = False
    fired: bool = False

    def __call__(self) -> float:
        """Run the armed callback once and return unchanged time."""
        if self.armed and self.callback is not None:
            callback, self.callback = self.callback, None
            callback()
            self.fired = True
        return self.value


@dataclass(frozen=True, slots=True)
class LocalHookContext:
    """Describe the frozen local HookContext contract."""

    event: HookEvent
    delivery_id: str
    binding_id: str
    registry_generation: int
    remaining_budget_ms: int
    origin: str = "host"
    depth: int = 0


@dataclass(frozen=True, slots=True)
class LocalHookScriptExecutionOptions:
    """Describe the frozen local execution-options contract."""

    argv: tuple[str, ...] = ()
    cwd: Path | None = None
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LocalHookScriptExecutionPolicy:
    """Describe the frozen local execution-policy contract."""

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


@dataclass(frozen=True, slots=True)
class LocalHookScriptEntryResult:
    """Describe the frozen local entry-result contract."""

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


@dataclass(frozen=True, slots=True)
class FakeDebt:
    """Represent one opaque test-owned cleanup debt."""

    debt_id: str


@dataclass
class FakeHookScriptRunner:
    """Implement the exact synchronous runner boundary without process I/O."""

    result_factory: Callable[[LocalHookScriptEntryResult], object]
    clock: Clock
    actions: tuple[Callable[[dict, "FakeHookScriptRunner"], object], ...] = ()
    calls: list[dict] = field(default_factory=list)
    current_calls: list[int] = field(default_factory=list)
    snapshots: dict[int, object] = field(default_factory=dict)
    snapshot_faults: dict[int, object] = field(default_factory=dict)
    debts: tuple[object, ...] = ()
    retry_calls: list[str] = field(default_factory=list)
    recovery_events: list[tuple] = field(default_factory=list)
    active: bool = False

    def execute_entry(
        self,
        *,
        entry_index: int,
        entry: HookScriptEntry,
        context: HookContext,
        options: object,
        policy: object,
        execution_deadline: float,
        cleanup_deadline: float,
        output_remaining_bytes: int,
        cancellation,
    ) -> object:
        """Record an entry call and execute its scripted action."""
        call = {
            "entry_index": entry_index,
            "entry": entry,
            "context": context,
            "options": options,
            "policy": policy,
            "execution_deadline": execution_deadline,
            "cleanup_deadline": cleanup_deadline,
            "output_remaining_bytes": output_remaining_bytes,
            "cancellation": cancellation,
            "observed_start": self.clock.value,
        }
        self.calls.append(call)
        self.snapshots[entry_index] = self.result_factory(
            LocalHookScriptEntryResult(
                entry_index,
                entry.basename,
                HookStatus.ERROR,
                False,
                error_category="hook_script_execution_error",
            )
        )
        self.recovery_events.append(("record", entry_index, False))
        self.active = True
        try:
            action = self.actions[entry_index] if entry_index < len(self.actions) else None
            if action is not None:
                return action(call, self)
            result = self.result_factory(
                LocalHookScriptEntryResult(
                    entry_index,
                    entry.basename,
                    HookStatus.SUCCESS,
                    True,
                    0,
                )
            )
            self.snapshots[entry_index] = result
            return result
        finally:
            self.active = False
            self.recovery_events.append(("return", entry_index))

    def current_result(self, entry_index: int) -> object:
        """Return the authoritative snapshot or its scripted fault."""
        self.current_calls.append(entry_index)
        fault = self.snapshot_faults.get(entry_index)
        if isinstance(fault, BaseException):
            raise fault
        if entry_index in self.snapshot_faults:
            return fault
        return self.snapshots[entry_index]

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return retained debt tokens without copying them."""
        return self.debts

    def retry_cleanup(self, debt_id: str) -> bool:
        """Recover only the debt identified by the supplied exact ID."""
        self.retry_calls.append(debt_id)
        for debt in self.debts:
            if getattr(debt, "debt_id", None) == debt_id:
                self.debts = tuple(item for item in self.debts if item is not debt)
                self.recovery_events.append(("retry", debt_id))
                return True
        return False


LOCAL_FIELDS = {
    LocalHookContext: (
        "event", "delivery_id", "binding_id", "registry_generation",
        "remaining_budget_ms", "origin", "depth",
    ),
    LocalHookScriptExecutionOptions: ("argv", "cwd", "environment"),
    LocalHookScriptExecutionPolicy: (
        "entry_timeout_ms", "hook_timeout_ms", "cleanup_timeout_ms",
        "terminate_grace_ms", "stdin_limit_bytes", "stdout_limit_bytes",
        "stderr_limit_bytes", "output_total_limit_bytes", "max_entries",
        "argument_environment_limit_bytes",
    ),
    LocalHookScriptEntryResult: (
        "entry_index", "basename", "status", "started", "exit_code",
        "duration_ms", "error_category", "stdout", "stderr",
        "stdout_dropped", "stderr_dropped", "cleanup_confirmed",
        "cleanup_debt",
    ),
}
