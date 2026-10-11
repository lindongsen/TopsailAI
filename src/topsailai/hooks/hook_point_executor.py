"""Synchronous orchestration of one acquired complete plan. Author: DawsonLin.

The caller retains the reader and execution cleanup custody. Module adapters must
honor the supplied absolute deadline and certify cleanup in their WorkerResult.
This module neither admits scheduler work nor grants Catalog policy authority.
"""
from dataclasses import replace
import time

from topsailai.hooks.hook_point_plan_ownership import HookPointReader
from topsailai.hooks.hook_script import execute_configured_hook_script
from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry
from topsailai.hooks.process_state import WorkerResult
from topsailai.hooks.result_contracts import (
    HandlerResult, HookPointResult, ReturnedValue, ResultCleanup, ResultDiagnostic, ResultTiming,
)


def _stop(cancellation, deadline, clock):
    """Observe cancellation before the same absolute business deadline."""
    if cancellation.is_set():
        return 'cancelled'
    if clock() >= deadline:
        return 'deadline'
    return None


def _not_run(context, plan, version, identity, reason):
    """Represent an unstarted planned handler without inventing return data."""
    return HandlerResult(context.delivery_id, plan.hook_point_name, version,
                         identity, status='not_run', not_run_reason=reason)


def _module_result(context, plan, version, module, worker, elapsed):
    """Map process facts independently of normal return payload or truthiness."""
    status = worker.status if worker.status in ('success', 'timeout', 'cancelled') else 'error'
    diagnostic = ResultDiagnostic(worker.error_category or 'module_error', '') if status == 'error' else None
    cleanup = ResultCleanup('safe' if worker.cleanup_confirmed else 'pending')
    returned = worker.returned if status == 'success' else ReturnedValue()
    return HandlerResult(context.delivery_id, plan.hook_point_name, version,
        module.identity, status=status, returned=returned, error=diagnostic,
        timing=ResultTiming(elapsed_ms=elapsed), cleanup=cleanup)


def _script_result(context, plan, version, runner, deadline, cancellation, clock, capacity, settlement_receiver, script_executor):
    """Run the default Hook once and retain bounded stream and cleanup facts."""
    terminal = plan.default_script_hook
    if not terminal.scripts:
        return HandlerResult(context.delivery_id, plan.hook_point_name, version, terminal.identity)
    entries = tuple(HookScriptEntry(item.captured_path, item.logical_name, item.identity.name)
                    for item in terminal.scripts)
    settlement = script_executor(
        hook_point=plan.hook_point_name, module_bindings=(), bindings_per_event=capacity,
        discovery_result=HookScriptDiscoveryResult(True, entries), context=context,
        options=plan.options, policy=plan.execution_policy, runner=runner,
        dispatch_deadline=deadline, cancellation=cancellation, clock=clock,
    )
    if settlement_receiver is not None:
        settlement_receiver(settlement)
    children = []
    for script, raw in zip(terminal.scripts, settlement.entry_results):
        status = raw.status.value
        reason = raw.error_category or status
        skipped = status.startswith('skipped_') or status == 'rejected_capacity'
        selected = 'not_run' if skipped else status if status in ('success', 'timeout', 'cancelled') else 'error'
        children.append(HandlerResult(context.delivery_id, plan.hook_point_name, version,
            script.identity, status=selected, not_run_reason=reason if skipped else None,
            returned=ReturnedValue(True, 'direct', {
                'exit_code': raw.exit_code, 'stdout': raw.stdout, 'stderr': raw.stderr,
                'stdout_dropped': raw.stdout_dropped, 'stderr_dropped': raw.stderr_dropped,
            }) if selected == 'success' else ReturnedValue(),
            error=ResultDiagnostic(reason, '') if selected == 'error' else None,
            timing=ResultTiming(elapsed_ms=raw.duration_ms),
            cleanup=ResultCleanup('safe' if raw.cleanup_confirmed else 'pending')))
    # All raw entry facts are retained even for failed entries, without claiming a return.
    status = 'success' if settlement.status == 'success' else 'completed_with_errors'
    pending = any(item.cleanup.state != 'safe' for item in children)
    return HandlerResult(context.delivery_id, plan.hook_point_name, version, terminal.identity,
        status=status, children=tuple(children), cleanup=ResultCleanup('pending' if pending else 'safe'),
        returned=ReturnedValue(True, 'direct', settlement.entry_results)
        if status in ('success', 'completed_with_errors') else ReturnedValue())


def execute_hook_point(*, reader, context, module_executor, script_runner, deadline,
                       cancellation, capacity, clock=time.monotonic, settlement_receiver=None,
                       script_executor=execute_configured_hook_script):
    """Execute exactly one acquired snapshot; caller keeps all ownership tokens."""
    if type(reader) is not HookPointReader:
        raise ValueError('exact acquired reader required')
    if type(capacity) is not int or capacity < 1:
        raise ValueError('invalid execution capacity')
    snapshot = reader.snapshot
    plan, version = snapshot.plan, snapshot.active_version
    start = clock()
    reason = 'capacity' if len(plan.handlers) > capacity else _stop(cancellation, deadline, clock)
    handlers = []
    for module in plan.modules:
        reason = reason or _stop(cancellation, deadline, clock)
        if reason is not None:
            handlers.append(_not_run(context, plan, version, module.identity, reason))
            continue
        before = clock()
        child_context = replace(context, binding_id=module.identity.id,
            registry_generation=version, remaining_budget_ms=max(1, int((deadline - before) * 1000)))
        try:
            worker = module_executor(module=module, context=child_context,
                                     deadline=deadline, cancellation=cancellation)
            if type(worker) is not WorkerResult:
                raise ValueError('invalid module adapter result')
        except Exception:
            # An adapter failure is not evidence of process absence.
            worker = WorkerResult('error', error_category='module_adapter_error', cleanup_confirmed=False)
        current = _module_result(context, plan, version, module, worker,
                                 max(0, int((clock() - before) * 1000)))
        handlers.append(current)
        reason = _stop(cancellation, deadline, clock)
        if reason is None and current.cleanup.state != 'safe':
            reason = 'cleanup_pending'
        if reason is None and current.status in ('timeout', 'cancelled'):
            reason = current.status
    reason = reason or _stop(cancellation, deadline, clock)
    if reason is not None:
        terminal = _not_run(context, plan, version, plan.default_script_hook.identity, reason)
    else:
        terminal_context = replace(context, binding_id='hook_script', registry_generation=version,
            remaining_budget_ms=max(1, int((deadline - clock()) * 1000)))
        terminal = _script_result(terminal_context, plan, version, script_runner,
                                  deadline, cancellation, clock, capacity, settlement_receiver, script_executor)
    handlers.append(terminal)
    cleanup = ResultCleanup('pending' if any(h.cleanup.state != 'safe' for h in handlers) else 'safe')
    statuses = {h.status for h in handlers} | {child.status for child in terminal.children}
    if reason == 'cancelled' or 'cancelled' in statuses:
        status = 'cancelled'
    elif reason in ('deadline', 'timeout') or 'timeout' in statuses:
        status = 'timeout'
    elif reason == 'capacity':
        status = 'unavailable'
    else:
        status = 'success' if all(h.status == 'success' for h in handlers) else 'completed_with_errors'
    return HookPointResult(context.delivery_id, plan.hook_point_name, version, status=status,
        handlers=tuple(handlers), cleanup=cleanup,
        timing=ResultTiming(elapsed_ms=max(0, int((clock() - start) * 1000))))
