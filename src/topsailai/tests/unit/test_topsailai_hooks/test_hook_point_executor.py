"""Complete acquired-plan synchronous execution. Author: DawsonLin."""
import threading

from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_publication import empty_candidate
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context
from topsailai.hooks.registry import HookRegistry


def test_empty_terminal_from_exact_reader(tmp_path):
    """An empty acquired plan still reports one successful default Hook."""
    from topsailai.hooks.hook_point_executor import execute_hook_point
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    registry.publish_hook_point('scope', 'point', candidate)
    reader = registry.acquire_hook_point('scope', 'point')
    try:
        result = execute_hook_point(reader=reader, context=_context(),
            module_executor=None, script_runner=None, deadline=10.,
            cancellation=threading.Event(), capacity=1, clock=lambda: 1.)
        assert result.plan_version == reader.snapshot.active_version
        assert result.status == 'success' and len(result.handlers) == 1
        assert result.handlers[0].handler.kind == 'default_script_hook'
        assert result.handlers[0].status == 'success'
    finally:
        registry.release_hook_point(reader)
        registry.remove_hook_point('scope', 'point').retire()

from dataclasses import replace
from pathlib import Path
import asyncio
import time
import pytest

from topsailai.hooks.hook_point_plan_contracts import HookPointPlan, DefaultScriptHook
from topsailai.hooks.hook_point_plan_ownership import HookPointReader, PublishedHookPoint
from topsailai.hooks.hook_point_executor import execute_hook_point
from topsailai.hooks.process_state import WorkerResult
from topsailai.hooks.result_contracts import ReturnedValue
from topsailai.hooks.contracts import HookStatus
from topsailai.hooks.hook_script_contracts import HookScriptEntryResult
from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_contracts import captured


def reader(modules=(), scripts=()):
    """Make a canonical structural publication, without filesystem authority claims."""
    def unique(item):
        """Give each structural entry its own original source address."""
        path = Path('/trusted') / str(item.inventory_index) / 'plugin.py'
        return replace(item, source=replace(item.source, source_path=path)) if item.identity.kind == 'module' else replace(item, source_path=path)
    modules = tuple(unique(item) for item in modules)
    scripts = tuple(unique(item) for item in scripts)
    plan = HookPointPlan('point', modules, DefaultScriptHook(scripts))
    return HookPointReader(PublishedHookPoint(plan, 7), None, None)


def invoke(snapshot, executor=None, runner=None, **changes):
    """Invoke with explicit deterministic clock and owned cancellation signal."""
    values = dict(reader=snapshot, context=_context(), module_executor=executor,
        script_runner=runner, deadline=10., cancellation=threading.Event(),
        capacity=8, clock=lambda: 1.)
    values.update(changes)
    return execute_hook_point(**values)


@pytest.mark.parametrize('value', [None, False, {'error': 1}])
def test_sorted_modules_and_normal_returns(value):
    """Registered Unicode order and return presence never infer failure policy."""
    modules = tuple(captured('module', i, n) for i, n in enumerate(('Z', 'a10', 'a2', '中')))
    seen = []
    def execute(**call):
        """Observe the exact snapshot's addresses, version and shared boundaries."""
        seen.append(call)
        return WorkerResult('success', returned=ReturnedValue(True, 'transported', value))
    result = invoke(reader(modules), execute)
    assert [c['module'].identity.name for c in seen] == ['Z', 'a10', 'a2', '中']
    assert all(c['deadline'] == 10. and c['context'].registry_generation == 7 for c in seen)
    assert len({id(c['cancellation']) for c in seen}) == 1
    assert all(h.returned.present and h.returned.value == value for h in result.handlers[:-1])
    assert result.status == 'success' and result.decision.action == 'continue'


@pytest.mark.parametrize('worker,expected,launches', [
    (WorkerResult('error', error_category='handler_error'), 'completed_with_errors', 2),
    (WorkerResult('invalid_output'), 'completed_with_errors', 2),
    (WorkerResult('success', cleanup_confirmed=False), 'completed_with_errors', 1),
    (WorkerResult('timeout'), 'timeout', 1),
    (WorkerResult('cancelled'), 'cancelled', 1),
])
def test_module_barrier(worker, expected, launches):
    """Only cleanup-safe ordinary failures allow successors to launch."""
    calls = []
    def execute(**call):
        """Return independent process and cleanup facts."""
        calls.append(call)
        return worker
    result = invoke(reader((captured('module', 0, 'A'), captured('module', 1, 'B'))), execute)
    assert len(calls) == launches and result.status == expected
    assert result.handlers[-1].status == ('success' if launches == 2 else 'not_run')
    assert result.cleanup.state == ('pending' if not worker.cleanup_confirmed else 'safe')


@pytest.mark.parametrize('mode', ['deadline', 'cancelled', 'capacity'])
def test_no_launch_preflight(mode):
    """Stop before any plugin call but include the terminal shape."""
    cancel = threading.Event()
    if mode == 'cancelled':
        cancel.set()
    result = invoke(reader((captured('module'),)),
        deadline=0. if mode == 'deadline' else 10., cancellation=cancel,
        capacity=1 if mode == 'capacity' else 8)
    assert all(h.status == 'not_run' for h in result.handlers)
    assert result.status == {'deadline':'timeout', 'cancelled':'cancelled', 'capacity':'unavailable'}[mode]


@pytest.mark.parametrize('mode', ['deadline', 'cancelled'])
def test_stop_between_handlers(mode):
    """Late observations cannot authorize a second launch or an empty terminal."""
    now = [1.]
    cancel = threading.Event()
    def execute(**call):
        """Simulate a concurrent stop while the first worker finishes safely."""
        if mode == 'deadline':
            now[0] = 10.
        else:
            cancel.set()
        return WorkerResult('success')
    result = invoke(reader((captured('module', 0, 'A'), captured('module', 1, 'B'))),
        execute, cancellation=cancel, clock=lambda: now[0])
    assert result.handlers[0].status == 'success'
    assert all(h.status == 'not_run' for h in result.handlers[1:])


@pytest.mark.parametrize('failure', [RuntimeError(), KeyboardInterrupt(), SystemExit(), asyncio.CancelledError()])
def test_adapter_failure_identity(failure):
    """Ordinary failures fail closed; host interrupts retain original identity."""
    def execute(**call):
        """Raise the exact supplied failure."""
        raise failure
    if isinstance(failure, Exception):
        result = invoke(reader((captured('module'),)), execute)
        assert result.cleanup.state == 'pending' and result.handlers[-1].status == 'not_run'
    else:
        with pytest.raises(type(failure)) as caught:
            invoke(reader((captured('module'),)), execute)
        assert caught.value is failure


def test_invalid_adapter_result():
    """A lookalike cannot claim cleanup safety."""
    result = invoke(reader((captured('module'),)), lambda **call: None)
    assert result.cleanup.state == 'pending'


class Runner:
    """Trusted deterministic Script boundary with authoritative current results."""
    def __init__(self, statuses):
        """Retain bounded planned facts and observed calls."""
        self.statuses, self.calls, self.results = statuses, [], {}

    def execute_entry(self, **call):
        """Return one correlated result at the real script executor seam."""
        self.calls.append(call)
        index = call['entry_index']
        status, safe = self.statuses[index]
        result = HookScriptEntryResult(index, call['entry'].basename, status, True,
            exit_code=0 if status is HookStatus.SUCCESS else 1, stdout=b'out', stderr=b'err',
            cleanup_confirmed=safe, error_category=None if status is HookStatus.SUCCESS else 'script_error')
        self.results[index] = result
        return result

    def current_result(self, index):
        """Expose only the exact prior authoritative observation."""
        return self.results[index]


@pytest.mark.parametrize('status,safe', [(HookStatus.SUCCESS, True), (HookStatus.ERROR, True),
                                        (HookStatus.TIMEOUT, True), (HookStatus.ERROR, False)])
def test_script_children_preserve_facts(status, safe):
    """Terminal Scripts retain name order, streams and independent cleanup facts."""
    scripts = (captured('script', 0, 'A'), captured('script', 1, 'B'))
    runner = Runner([(status, safe), (HookStatus.SUCCESS, True)])
    result = invoke(reader(scripts=scripts), runner=runner)
    terminal = result.handlers[0]
    assert [h.handler.name for h in terminal.children] == ['A', 'B']
    assert runner.calls[0]['execution_deadline'] <= 10.
    if terminal.returned.present:
        assert terminal.returned.value[0].stdout == b'out'
        assert terminal.returned.value[0].stderr == b'err'
    if status is HookStatus.SUCCESS:
        assert terminal.children[0].returned.value['stdout'] == b'out'
        assert result.status == 'success'
    if not safe:
        assert len(runner.calls) == 1 and terminal.children[1].status == 'not_run'
        assert result.cleanup.state == 'pending'


@pytest.mark.parametrize('capacity', [0, True, '8'])
def test_invalid_capacity(capacity):
    """Reject invalid budgets before observing snapshot-dependent execution."""
    with pytest.raises(ValueError):
        invoke(reader(), capacity=capacity)


def test_exact_reader_required():
    """Do not accept duck-typed release authority."""
    with pytest.raises(ValueError):
        invoke(object())


def test_real_captured_worker(tmp_path):
    """The executor invokes sealed bytes in a real child through the explicit adapter."""
    from topsailai.tests.unit.test_topsailai_hooks.test_captured_module_worker import captured as real_captured
    from topsailai.tests.unit.test_topsailai_hooks.test_module_worker_transport import backend
    module = real_captured(tmp_path, 'def main():\n    return False\n')
    service = backend(tmp_path)
    def execute(**call):
        """Adapt the current backend without claiming U06C absolute-deadline integration."""
        remaining = max(1, int((call['deadline'] - time.monotonic()) * 1000))
        return service.execute_captured_module(call['module'], call['context'], remaining)
    snapshot = HookPointReader(PublishedHookPoint(HookPointPlan('point', (module,), DefaultScriptHook(())), 7), None, None)
    result = invoke(snapshot, execute, deadline=time.monotonic() + 3., clock=time.monotonic)
    assert result.handlers[0].returned.value is False and result.handlers[0].returned.present
    assert result.status == 'success' and result.cleanup.state == 'safe'
    assert not service.cleanup_debts()


def test_mixed_plan_module_before_script():
    """One snapshot controls both kinds; the Script cannot precede Module cleanup."""
    seen = []
    runner = Runner([(HookStatus.SUCCESS, True)])
    original = runner.execute_entry
    def script(**call):
        """Observe terminal launch only after the Module adapter returned safe."""
        seen.append('script')
        return original(**call)
    runner.execute_entry = script
    def module(**call):
        """Preserve the Module's registered alias and certify completed cleanup."""
        seen.append('module')
        return WorkerResult('success')
    snapshot = reader((captured('module', 0, 'same'),), (captured('script', 1, 'same'),))
    result = invoke(snapshot, module, runner)
    assert seen == ['module', 'script'] and result.status == 'success'
    assert all(h.plan_version == 7 for h in result.handlers)
    assert result.handlers[-1].children[0].plan_version == 7
    assert result.handlers[0].handler.name == result.handlers[-1].children[0].handler.name


def test_reader_version_survives_replacement(tmp_path):
    """Execution reads the admitted version, not a newly published active point."""
    registry = HookRegistry()
    first = empty_candidate(tmp_path)
    registry.publish_hook_point('scope', 'point', first)
    admitted = registry.acquire_hook_point('scope', 'point')
    old_version = admitted.snapshot.active_version
    replacement = empty_candidate(tmp_path)
    owner = registry.remove_hook_point('scope', 'point')
    registry.publish_hook_point('scope', 'point', replacement)
    try:
        result = invoke(admitted)
        assert result.plan_version == old_version
        assert result.status == 'success'
    finally:
        registry.release_hook_point(admitted)
        owner.retire()
        registry.remove_hook_point('scope', 'point').retire()
