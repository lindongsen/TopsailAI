"""Framework-owned terminal hook_script binding plan contracts."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from topsailai.hooks.contracts import Binding, HookContext, HookEvent, HookStatus
from topsailai.hooks.hook_script_contracts import (
    HookPointBindingPlan,
    HookScriptBinding,
    HookScriptEntryResult,
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
    HookScriptRunner,
    HookScriptSettlement,
)
from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry

_RESERVED_BINDING_ID = "hook_script"
_CLEANUP_SAFE_TERMINAL_STATUSES = frozenset(
    {
        "success",
        "error",
        "timeout",
        "invalid_output",
        "worker_lost",
        "cancelled",
        "skipped_dependency",
        "skipped_disabled",
        "skipped_deadline",
        "rejected_capacity",
    }
)


def execute_configured_hook_script(
    *,
    hook_point: str,
    module_bindings: tuple[Binding, ...],
    bindings_per_event: int,
    discovery_result: HookScriptDiscoveryResult | None,
    context: HookContext,
    options: HookScriptExecutionOptions,
    policy: HookScriptExecutionPolicy,
    runner: HookScriptRunner,
    dispatch_deadline: float,
    cancellation: threading.Event,
    clock: Callable[[], float],
) -> HookScriptSettlement:
    """Execute one accepted non-empty script plan through a trusted runner."""
    plan = build_hook_point_binding_plan_from_discovery(
        hook_point=hook_point,
        module_bindings=module_bindings,
        bindings_per_event=bindings_per_event,
        hook_script_configured=True,
        discovery_result=discovery_result,
    )
    if not plan.accepted:
        return _execution_rejection("hook_script_plan_rejected")
    terminal = plan.bindings[-1]
    if not terminal.entries:
        return _execution_rejection("hook_script_empty_entries")
    entries = terminal.entries
    if not _valid_execution_inputs(
        hook_point, entries, context, options, policy, dispatch_deadline, cancellation, clock
    ):
        return _execution_rejection("hook_script_invalid_execution_input")

    now = clock()
    group_deadline = min(dispatch_deadline, now + policy.hook_timeout_ms / 1000)
    cleanup_deadline = group_deadline + policy.cleanup_timeout_ms / 1000
    if cancellation.is_set():
        raise asyncio.CancelledError()
    if now >= group_deadline:
        results = tuple(
            _skipped_result(index, entry, HookStatus.SKIPPED_DEADLINE, "hook_script_deadline")
            for index, entry in enumerate(entries)
        )
        return _settle_results(results)

    results: list[HookScriptEntryResult] = []
    retained_bytes = 0
    for index, entry in enumerate(entries):
        now = clock()
        if cancellation.is_set():
            raise asyncio.CancelledError()
        if now >= group_deadline:
            results.extend(_remaining_results(entries, index, HookStatus.SKIPPED_DEADLINE, "hook_script_deadline"))
            break
        execution_deadline = min(
            group_deadline,
            now + policy.entry_timeout_ms / 1000,
        )
        remaining = max(0, policy.output_total_limit_bytes - retained_bytes)
        try:
            candidate = runner.execute_entry(
                entry_index=index,
                entry=entry,
                context=context,
                options=options,
                policy=policy,
                execution_deadline=execution_deadline,
                cleanup_deadline=cleanup_deadline,
                output_remaining_bytes=remaining,
                cancellation=cancellation,
            )
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            snapshot = _trusted_snapshot(runner, index, entry, policy, remaining)
            current = _override_result(snapshot, HookStatus.ERROR, "hook_script_execution_error")
        else:
            current = _accepted_runner_result(candidate, runner, index, entry, policy, remaining)

        observed = clock()
        if cancellation.is_set():
            raise asyncio.CancelledError()
        if not current.cleanup_confirmed:
            current = _override_result(current, HookStatus.ERROR, "hook_script_cleanup_pending")
        elif current.status is HookStatus.SUCCESS and observed >= execution_deadline:
            current = _override_result(current, HookStatus.TIMEOUT, "hook_script_timeout")
        results.append(current)
        retained_bytes += len(current.stdout) + len(current.stderr)

        stop_token = _stopping_token(current)
        if stop_token is not None:
            results.extend(_remaining_results(entries, index + 1, HookStatus.SKIPPED_DEPENDENCY, stop_token))
            break
        if observed >= group_deadline:
            results.extend(_remaining_results(entries, index + 1, HookStatus.SKIPPED_DEADLINE, "hook_script_deadline"))
            break
    return _settle_results(tuple(results))


def _execution_rejection(token: str) -> HookScriptSettlement:
    """Build one fixed pre-execution rejection settlement."""
    return HookScriptSettlement("error", error_category=token)


def _valid_execution_inputs(
    hook_point: object,
    entries: object,
    context: object,
    options: object,
    policy: object,
    dispatch_deadline: object,
    cancellation: object,
    clock: object,
) -> bool:
    """Validate execution-only inputs without invoking external dependencies."""
    if type(context) is not HookContext or type(options) is not HookScriptExecutionOptions:
        return False
    if type(policy) is not HookScriptExecutionPolicy or type(cancellation) is not threading.Event:
        return False
    if not callable(clock) or type(dispatch_deadline) not in (int, float):
        return False
    if type(dispatch_deadline) is bool or not math.isfinite(dispatch_deadline):
        return False
    if type(context.event) is not HookEvent or context.binding_id != _RESERVED_BINDING_ID:
        return False
    if not _valid_policy(policy) or not _valid_options(options, policy):
        return False
    if type(entries) is not tuple or not entries or len(entries) > policy.max_entries:
        return False
    if not _valid_entries(entries):
        return False
    return _context_encoded_size(context) <= policy.stdin_limit_bytes


def _valid_options(options: HookScriptExecutionOptions, policy: HookScriptExecutionPolicy) -> bool:
    """Validate literal argv, cwd, and frozen environment values."""
    if type(options.argv) is not tuple or any(
        type(value) is not str or "\0" in value for value in options.argv
    ):
        return False
    if options.cwd is not None and (
        not isinstance(options.cwd, Path) or not options.cwd.is_absolute()
    ):
        return False
    if type(options.environment) is not tuple:
        return False
    names: set[str] = set()
    try:
        encoded = sum(len(value.encode("utf-8")) for value in options.argv)
        for pair in options.environment:
            if type(pair) is not tuple or len(pair) != 2:
                return False
            name, value = pair
            if type(name) is not str or type(value) is not str:
                return False
            if not name or "=" in name or "\0" in name or "\0" in value or name in names:
                return False
            names.add(name)
            encoded += len(name.encode("utf-8")) + len(value.encode("utf-8"))
    except UnicodeEncodeError: return False
    return encoded <= policy.argument_environment_limit_bytes


def _valid_policy(policy: HookScriptExecutionPolicy) -> bool:
    """Validate exact v1 policy domains, maxima, and cleanup ordering."""
    durations = (
        policy.entry_timeout_ms,
        policy.hook_timeout_ms,
        policy.cleanup_timeout_ms,
        policy.terminate_grace_ms,
    )
    byte_limits = (
        policy.stdin_limit_bytes,
        policy.stdout_limit_bytes,
        policy.stderr_limit_bytes,
        policy.output_total_limit_bytes,
        policy.argument_environment_limit_bytes,
        policy.result_limit_bytes,
    )
    return (
        all(type(value) is int and 0 < value <= 600_000 for value in durations)
        and all(type(value) is int and 0 < value <= 1_048_576 for value in byte_limits)
        and type(policy.max_entries) is int
        and 0 < policy.max_entries <= 32
        and policy.terminate_grace_ms <= policy.cleanup_timeout_ms
    )


def _valid_entries(entries: tuple[HookScriptEntry, ...]) -> bool:
    """Require unique absolute execution metadata in its already planned order."""
    paths: set[Path] = set()
    names: set[str] = set()
    for entry in entries:
        if type(entry) is not HookScriptEntry or not isinstance(entry.source_path, Path):
            return False
        if not entry.source_path.is_absolute() or type(entry.basename) is not str or not entry.basename:
            return False
        if "/" in entry.basename or "\\" in entry.basename:
            return False
        if entry.registered_name is not None and type(entry.registered_name) is not str:
            return False
        if entry.source_path in paths or entry.final_registered_name in names:
            return False
        paths.add(entry.source_path)
        names.add(entry.final_registered_name)
    return True


def _context_encoded_size(context: HookContext) -> int:
    """Return the deterministic UTF-8 JSON size of detached context data."""
    def plain(value: Any) -> Any:
        if hasattr(value, "items"):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [plain(item) for item in value]
        if hasattr(value, "__dataclass_fields__"):
            return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
        return value

    try:
        return len(json.dumps(plain(context), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError):
        return 2**63 - 1


def _valid_result(
    value: object,
    index: int,
    entry: HookScriptEntry,
    policy: HookScriptExecutionPolicy,
    remaining: int,
) -> bool:
    """Validate one runner result and all bounded retained facts."""
    if type(value) is not HookScriptEntryResult:
        return False
    if (type(value.entry_index) is not int or value.entry_index != index
            or type(value.basename) is not str or value.basename != entry.basename):
        return False
    if type(value.status) is not HookStatus or type(value.started) is not bool:
        return False
    if value.exit_code is not None and type(value.exit_code) is not int:
        return False
    if type(value.duration_ms) is not int or value.duration_ms < 0:
        return False
    if value.error_category is not None and type(value.error_category) is not str:
        return False
    if type(value.stdout) is not bytes or type(value.stderr) is not bytes:
        return False
    if type(value.stdout_dropped) is not int or value.stdout_dropped < 0:
        return False
    if type(value.stderr_dropped) is not int or value.stderr_dropped < 0:
        return False
    if type(value.cleanup_confirmed) is not bool:
        return False
    if value.cleanup_debt is not None and type(value.cleanup_debt) is not str:
        return False
    if len(value.stdout) > policy.stdout_limit_bytes or len(value.stderr) > policy.stderr_limit_bytes:
        return False
    return len(value.stdout) + len(value.stderr) <= remaining


def _trusted_snapshot(
    runner: HookScriptRunner,
    index: int,
    entry: HookScriptEntry,
    policy: HookScriptExecutionPolicy,
    remaining: int,
) -> HookScriptEntryResult:
    """Load a trustworthy bounded recovery snapshot or fail closed."""
    try:
        snapshot = runner.current_result(index)
    except Exception:
        raise RuntimeError("hook_script_runner_error") from None
    if not _valid_result(snapshot, index, entry, policy, remaining):
        raise RuntimeError("hook_script_runner_error")
    return snapshot


def _accepted_runner_result(
    candidate: object,
    runner: HookScriptRunner,
    index: int,
    entry: HookScriptEntry,
    policy: HookScriptExecutionPolicy,
    remaining: int,
) -> HookScriptEntryResult:
    """Accept a valid result or preserve trustworthy recovery facts."""
    if _valid_result(candidate, index, entry, policy, remaining):
        return candidate
    snapshot = _trusted_snapshot(runner, index, entry, policy, remaining)
    if not snapshot.cleanup_confirmed:
        return _override_result(snapshot, HookStatus.ERROR, "hook_script_cleanup_pending")
    return _override_result(snapshot, HookStatus.INVALID_OUTPUT, "hook_script_invalid_result")


def _override_result(
    result: HookScriptEntryResult,
    status: HookStatus,
    token: str,
) -> HookScriptEntryResult:
    """Replace classification while retaining all observed execution facts."""
    return replace(result, status=status, error_category=token)


def _skipped_result(
    index: int,
    entry: HookScriptEntry,
    status: HookStatus,
    token: str,
) -> HookScriptEntryResult:
    """Build a complete result for one entry that created no resources."""
    return HookScriptEntryResult(index, entry.basename, status, False, error_category=token)


def _remaining_results(
    entries: tuple[HookScriptEntry, ...],
    start: int,
    status: HookStatus,
    token: str,
) -> tuple[HookScriptEntryResult, ...]:
    """Build complete skipped records for every remaining planned entry."""
    return tuple(_skipped_result(index, entries[index], status, token) for index in range(start, len(entries)))


def _stopping_token(result: HookScriptEntryResult) -> str | None:
    """Return the dependency token for classifications that stop the batch."""
    if result.error_category in (
        "hook_script_invalid_result",
        "hook_script_unsupported_backend",
        "hook_script_cleanup_pending",
        "hook_script_runner_error",
    ):
        return result.error_category
    return None


def _settle_results(results: tuple[HookScriptEntryResult, ...]) -> HookScriptSettlement:
    """Aggregate in plan order without allowing later success to mask failure."""
    started = any(result.started for result in results)
    first_failure = next((result for result in results if result.status is not HookStatus.SUCCESS), None)
    if first_failure is None:
        return HookScriptSettlement("success", results, started, None)
    return HookScriptSettlement(
        first_failure.status.value,
        results,
        started,
        first_failure.error_category,
    )

def build_hook_point_binding_plan(
    *,
    hook_point: str,
    module_bindings: tuple[Binding, ...],
    bindings_per_event: int,
    hook_script_configured: bool = False,
) -> HookPointBindingPlan:
    """Compile modules and one terminal script binding without executing either."""
    errors = _validate_plan_inputs(
        hook_point,
        module_bindings,
        bindings_per_event,
        hook_script_configured,
    )
    if errors:
        return HookPointBindingPlan(False, errors=errors)

    ordered_modules = sorted(module_bindings, key=lambda binding: binding.binding_id[7:])
    compiled_modules: list[Binding] = []
    previous_id: str | None = None
    for binding in ordered_modules:
        after = () if previous_id is None else (previous_id,)
        compiled = replace(binding, after=after)
        compiled_modules.append(compiled)
        previous_id = compiled.binding_id

    predecessor_ids = tuple(binding.binding_id for binding in compiled_modules)
    terminal = HookScriptBinding(
        binding_id=_RESERVED_BINDING_ID,
        hook_point=hook_point,
        priority=2_147_483_647,
        after=predecessor_ids,
        framework_owned=True,
        terminal=True,
        configured=hook_script_configured,
    )
    return HookPointBindingPlan(True, (*compiled_modules, terminal))


def build_hook_point_binding_plan_from_discovery(
    *,
    hook_point: str,
    module_bindings: tuple[Binding, ...],
    bindings_per_event: int,
    hook_script_configured: bool,
    discovery_result: HookScriptDiscoveryResult | None,
) -> HookPointBindingPlan:
    """Attach an admitted executable snapshot to the existing terminal plan."""
    discovery_error = _validate_discovery_plan_input(
        hook_script_configured,
        discovery_result,
    )
    if discovery_error:
        return HookPointBindingPlan(False, errors=(discovery_error,))
    if discovery_result is not None and not discovery_result.accepted:
        return HookPointBindingPlan(False, errors=discovery_result.errors)

    plan = build_hook_point_binding_plan(
        hook_point=hook_point,
        module_bindings=module_bindings,
        bindings_per_event=bindings_per_event,
        hook_script_configured=hook_script_configured,
    )
    if not plan.accepted or discovery_result is None:
        return plan
    if len(module_bindings) + len(discovery_result.entries) > 128:
        return HookPointBindingPlan(False, errors=("registration capacity limit exceeded",))

    entries = tuple(
        HookScriptEntry(entry.source_path, entry.basename, entry.registered_name)
        for entry in sorted(discovery_result.entries, key=lambda entry: entry.final_registered_name)
    )
    terminal = replace(plan.bindings[-1], entries=entries)
    return replace(plan, bindings=(*plan.bindings[:-1], terminal))


def hook_script_ready(
    terminal: HookScriptBinding,
    predecessor_statuses: Mapping[str, str],
) -> bool:
    """Return whether every explicit predecessor is cleanup-safe and terminal."""
    if type(terminal) is not HookScriptBinding or not terminal.framework_owned:
        return False
    if terminal.binding_id != _RESERVED_BINDING_ID or not terminal.terminal:
        return False
    if not isinstance(predecessor_statuses, Mapping):
        return False
    return all(
        predecessor_statuses.get(binding_id) in _CLEANUP_SAFE_TERMINAL_STATUSES
        for binding_id in terminal.after
    )


def settle_unconfigured_hook_script(
    terminal: HookScriptBinding,
) -> HookScriptSettlement:
    """Settle an unconfigured reserved binding as a successful zero-entry no-op."""
    if (
        type(terminal) is not HookScriptBinding
        or terminal.binding_id != _RESERVED_BINDING_ID
        or not terminal.framework_owned
        or not terminal.terminal
        or terminal.configured
    ):
        return HookScriptSettlement("error", error_category="hook_script_not_unconfigured")
    if terminal.entries != ():
        return HookScriptSettlement(
            "error",
            entry_results=(),
            started=False,
            error_category="hook_script_nonempty_entries",
        )
    return HookScriptSettlement("success")


def settle_configured_empty_hook_script(
    *,
    hook_point: str,
    module_bindings: tuple[Binding, ...],
    bindings_per_event: int,
    discovery_result: HookScriptDiscoveryResult | None,
) -> HookScriptSettlement:
    """Settle admitted configured empty script metadata without executing scripts."""
    plan = build_hook_point_binding_plan_from_discovery(
        hook_point=hook_point,
        module_bindings=module_bindings,
        bindings_per_event=bindings_per_event,
        hook_script_configured=True,
        discovery_result=discovery_result,
    )
    if not plan.accepted:
        return HookScriptSettlement(
            "error",
            entry_results=(),
            started=False,
            error_category="hook_script_plan_rejected",
        )

    terminal = plan.bindings[-1]
    if terminal.entries != ():
        return HookScriptSettlement(
            "error",
            entry_results=(),
            started=False,
            error_category="hook_script_nonempty_entries",
        )
    return HookScriptSettlement(
        "success",
        entry_results=(),
        started=False,
        error_category=None,
    )


def _validate_discovery_plan_input(
    hook_script_configured: object,
    discovery_result: object,
) -> str | None:
    """Reject missing, malformed, or contradictory discovery planning state."""
    if type(hook_script_configured) is not bool:
        return "hook_script_configured must be a boolean"
    if not hook_script_configured:
        if discovery_result is None:
            return None
        return "unconfigured hook_script must not have a discovery result"
    if discovery_result is None:
        return "configured hook_script requires a discovery result"
    if type(discovery_result) is not HookScriptDiscoveryResult:
        return "discovery_result must be a HookScriptDiscoveryResult"
    if type(discovery_result.accepted) is not bool:
        return "discovery_result accepted must be a boolean"
    if type(discovery_result.entries) is tuple and len(discovery_result.entries) > 128:
        return "registration capacity limit exceeded"
    if type(discovery_result.entries) is not tuple or any(
        type(entry) is not HookScriptEntry for entry in discovery_result.entries
    ):
        return "discovery_result entries must contain HookScriptEntry values"
    if type(discovery_result.errors) is not tuple or any(
        type(error) is not str or not error for error in discovery_result.errors
    ):
        return "discovery_result errors must contain non-empty strings"
    if discovery_result.accepted:
        if discovery_result.errors:
            return "accepted discovery result must not contain errors"
        if not _valid_entries(discovery_result.entries):
            return "discovery_result entries must contain valid unique Script metadata"
        return None
    if discovery_result.entries:
        return "rejected discovery result must not contain entries"
    if not discovery_result.errors:
        return "rejected discovery result must contain errors"
    return None


def _validate_plan_inputs(
    hook_point: object,
    module_bindings: object,
    bindings_per_event: object,
    hook_script_configured: object,
) -> tuple[str, ...]:
    """Validate the complete candidate before any binding plan is published."""
    if type(hook_point) is not str or not hook_point:
        return ("hook_point must be a non-empty string",)
    if type(module_bindings) is tuple and len(module_bindings) > 128:
        return ("registration capacity limit exceeded",)
    if type(module_bindings) is not tuple or any(
        type(binding) is not Binding for binding in module_bindings
    ):
        return ("module_bindings must be a tuple of Binding values",)
    if type(bindings_per_event) is not int or bindings_per_event <= 0:
        return ("bindings_per_event must be a positive integer",)
    if type(hook_script_configured) is not bool:
        return ("hook_script_configured must be a boolean",)

    binding_ids = tuple(binding.binding_id for binding in module_bindings)
    if _RESERVED_BINDING_ID in binding_ids:
        return ("hook_script binding is framework-owned",)
    if any(
        _RESERVED_BINDING_ID in binding.after
        or _RESERVED_BINDING_ID in binding.requires_success
        for binding in module_bindings
    ):
        return ("no binding may depend on terminal hook_script",)
    if any(binding.requires_success for binding in module_bindings):
        return ("discovered module requires_success dependencies are not supported",)
    if len(binding_ids) != len(set(binding_ids)):
        return ("module binding identity is duplicated",)
    if any(not binding_id.startswith("module:") for binding_id in binding_ids):
        return ("module binding identity must start with module:",)
    if len(module_bindings) + 1 > bindings_per_event:
        return ("bindings_per_event limit exceeded",)
    if any(
        type(binding.handler_ref) is not str
        or binding.handler_ref.count(":") != 1
        or binding.handler_ref.rsplit(":", 1)[1] != "main"
        or not all(
            component.isidentifier()
            for component in binding.handler_ref.split(":", 1)[0].split(".")
        )
        for binding in module_bindings
    ):
        return ("module handler_ref must use non-empty module:main format",)
    return ()
