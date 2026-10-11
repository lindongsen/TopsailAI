"""Production captured Module prelaunch recovery. Author: DawsonLin."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from topsailai.hooks.module_runner import OwnedHookModuleRunner
from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.tests.unit.test_topsailai_hooks.test_captured_module_worker import captured
from topsailai.tests.unit.test_topsailai_hooks.test_execution_debt_isolation import _Registry
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


class _PausedBackend(IsolatedProcessBackend):
    """Observe production binding and pause only one exact child publication."""
    def __init__(self, **kwargs):
        """Arm independent synchronization before real launch."""
        super().__init__(**kwargs)
        self.ready = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.held = None
        self.runner = None
        self.interrupt = False
        self.hold_cleanup = True
        self.bound_before_launch = False

    def _spawn(self, interpreter, deadline, record):
        """Observe custody without preventing the real child from launching."""
        if self.held is None:
            self.held = record
            self.bound_before_launch = any(item is record for item in self.runner._records)
        return super()._spawn(interpreter, deadline, record)

    def _before_publish_process(self, record):
        """Pause the selected real child without creating caller authority."""
        if record is self.held:
            self.ready.set()
            assert self.release.wait(5)

    def _wait_for_launch(self, record, remaining):
        """Interrupt only after a child exists under launcher ownership."""
        if self.interrupt and record is self.held:
            assert self.ready.wait(5)
            raise KeyboardInterrupt('production launch interruption')
        return super()._wait_for_launch(record, remaining)

    def _terminate_record(self, record, process):
        """Defer only the held execution's late cleanup."""
        if self.hold_cleanup and record is self.held:
            return False
        return super()._terminate_record(record, process)

    def _cleanup_launch_record(self, record, category):
        """Signal the creator's cleanup handoff, not merely publication."""
        try:
            return super()._cleanup_launch_record(record, category)
        finally:
            if record is self.held:
                self.finished.set()


@pytest.mark.parametrize('interrupt', [False, True])
def test_production_runner_prelaunch_custody_two_executions(tmp_path, interrupt):
    """Own launch debt retains capture while a concurrent peer settles safely."""
    backend = _PausedBackend(temp_root=str(tmp_path))
    runners = [OwnedHookModuleRunner(backend), OwnedHookModuleRunner(backend)]
    backend.runner, backend.interrupt = runners[0], interrupt
    module = captured(tmp_path, 'def main():\n    return False\n')
    registry = _Registry()
    tokens = [object(), object()]
    custodies = [ExecutionCleanupCustody(registry, token) for token in tokens]
    for custody, runner in zip(custodies, runners):
        custody.runner = runner
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            own = pool.submit(runners[0].execute, module, _context(), 250)
            assert backend.ready.wait(5)
            peer = pool.submit(runners[1].execute, module, _context(), 2000)
            assert peer.result(5).cleanup_confirmed
            if interrupt:
                with pytest.raises(KeyboardInterrupt, match='production launch interruption'):
                    own.result(5)
            else:
                result = own.result(5)
                assert result.status == 'timeout' and not result.cleanup_confirmed
        for custody in custodies:
            custody.completed = True
        record = backend.held
        assert backend.bound_before_launch
        assert runners[0].cleanup_debts()[0].state == 'launching'
        assert runners[1].cleanup_debts() == ()
        assert not runners[1].retry_cleanup(record.debt_id)
        assert not runners[0].retry_cleanup(record.debt_id)
        assert not runners[0].retry_cleanup('unknown')
        assert not custodies[0].close().accepted
        assert custodies[1].close().accepted
        assert registry.released == [tokens[1]]
        backend.release.set()
        assert backend.finished.wait(5)
        assert runners[0].cleanup_debts()[0].state == 'process'
        backend.hold_cleanup = False
        assert custodies[0].retry_cleanup(record.debt_id)
        assert record.process.poll() is not None
        assert runners[0].cleanup_debts() == ()
        assert custodies[0].close().accepted
        assert registry.released == [tokens[1], tokens[0]]
    finally:
        backend.release.set()
        backend.hold_cleanup = False
        if backend.ready.is_set():
            assert backend.finished.wait(5)
        if backend.held is not None:
            for debt in backend.cleanup_debts_for_record(backend.held):
                assert backend.retry_cleanup(debt.debt_id, record=backend.held)
        for runner in runners:
            for debt in runner.cleanup_debts():
                runner.retry_cleanup(debt.debt_id)
        assert backend.cleanup_debts() == ()


def test_runner_admission_and_safe_completion(tmp_path):
    """Rejected admission binds nothing; safe child completion leaves no debt."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    runner = OwnedHookModuleRunner(backend)
    assert runner.execute(object(), _context(), 1000).status == 'invalid_request'
    assert runner._records == []
    assert not runner.retry_cleanup('unknown')
    module = captured(tmp_path, 'def main():\n    return False\n')
    assert runner.execute(module, _context(), 2000).cleanup_confirmed
    assert len(runner._records) == 1
    assert runner._records[0].process.poll() is not None
    assert runner.cleanup_debts() == ()
    assert backend.cleanup_debts() == ()


@pytest.mark.parametrize('error_type', [RuntimeError, KeyboardInterrupt])
def test_record_receiver_failure_precedes_launch(tmp_path, error_type, monkeypatch):
    """Receiver failure propagates unchanged without a fictitious launch debt."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    module = captured(tmp_path, 'def main():\n    return False\n')
    error = error_type('receiver rejected')
    observed = []

    def receive(record):
        """Record the original identity then reject the handoff before resources."""
        observed.append(record)
        raise error

    def forbidden_spawn(*args):
        """Fail if a rejected receiver nevertheless authorizes resource creation."""
        pytest.fail('spawn after receiver failure')

    monkeypatch.setattr(backend, '_spawn', forbidden_spawn)
    with pytest.raises(error_type) as raised:
        backend.execute_captured_module(module, _context(), 2000,
                                        record_receiver=receive)
    assert raised.value is error
    assert len(observed) == 1
    assert observed[0].process is None
    assert backend.cleanup_debts_for_record(observed[0]) == ()
    assert backend.cleanup_debts() == ()
