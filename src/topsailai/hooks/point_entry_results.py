"""Project direct-entry observations into the shared public result contracts.

Author: DawsonLin
"""
import time
from uuid import uuid4

from topsailai.hooks.result_contracts import (
    HandlerIdentity, HandlerResult, HookPointResult, ResultCleanup,
    ResultDiagnostic, ResultTiming,
)


def elapsed(start):
    """Measure duration without depending on wall-clock adjustments."""
    return ResultTiming(elapsed_ms=max(0, int((time.monotonic() - start) * 1000)))


def unavailable_result(name, reason, *, start=None, execution_id=None):
    """Return a distinguishable unavailable observation without raw exception text."""
    return HookPointResult(
        execution_id or uuid4().hex, name, 0, status="unavailable",
        timing=elapsed(start) if start is not None else ResultTiming(),
        cleanup=ResultCleanup(diagnostic=ResultDiagnostic(reason, "Hook Point unavailable")),
    )


def handler_result(execution_id, name, kind, filename, entry, timing):
    """Wrap one observation without interpreting or copying its opaque value."""
    status = entry.status
    pending = status == "cleanup_failed"
    unrun = not entry.started
    return HandlerResult(
        execution_id, name, 0, HandlerIdentity(f"{kind}:{filename}", filename, kind),
        status="not_run" if unrun else "error" if pending else status,
        not_run_reason=status if unrun else None,
        returned=entry.returned,
        error=ResultDiagnostic(status, f"Script exited with code {entry.exit_code}"
                               if entry.exit_code is not None else
                               "Hook resource did not complete successfully")
        if not unrun and status in ("error", "cleanup_failed") else None,
        timing=timing,
        cleanup=ResultCleanup("pending" if pending else "safe"),
    )


def point_result(execution_id, name, modules, scripts, start, script_start, stop_reason):
    """Append one terminal Script grouping and derive report-only aggregate state."""
    all_entries = tuple(modules) + tuple(scripts)
    pending = any(item.cleanup.state == "pending" for item in all_entries)
    timed_out = stop_reason == "timeout"
    failed = any(item.status != "success" for item in all_entries)
    cleanup = ResultCleanup("pending" if pending else "safe")
    terminal = HandlerResult(
        execution_id, name, 0, HandlerIdentity("hook_script", "hook_script", "default_script_hook"),
        status="not_run" if stop_reason and script_start is None else
               "timeout" if timed_out else "completed_with_errors" if any(
                   item.status != "success" for item in scripts) else "success",
        not_run_reason=stop_reason if stop_reason and script_start is None else None,
        children=tuple(scripts), cleanup=cleanup,
        timing=elapsed(script_start) if script_start is not None else ResultTiming(),
    )
    return HookPointResult(
        execution_id, name, 0,
        status="timeout" if timed_out else "completed_with_errors" if failed else "success",
        handlers=tuple(modules) + (terminal,), timing=elapsed(start), cleanup=cleanup,
    )
