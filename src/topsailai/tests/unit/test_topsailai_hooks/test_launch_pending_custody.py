"""Exact launch-pending custody with real Module children. Author: DawsonLin."""
import threading
import time

import pytest

from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord
from topsailai.tests.unit.test_topsailai_hooks.test_execution_debt_isolation import _Registry
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


class _RecordOwner:
    """Bind an exact record before the backend creates any child resources."""
    def __init__(self, backend):
        """Retain only records admitted by this execution."""
        self.backend = backend
        self.record = None

    def cleanup_debts(self):
        """Use exact identity, never the shared backend inventory."""
        return self.backend.cleanup_debts_for_record(self.record)

    def retry_cleanup(self, debt_id):
        """Reject debts absent from this execution before backend invocation."""
        if not any(debt.debt_id == debt_id for debt in self.cleanup_debts()):
            return False
        return self.backend.retry_cleanup(debt_id, record=self.record)


class _LateModuleBackend(IsolatedProcessBackend):
    """Pause a real child's publication while its caller abandons launch."""
    def __init__(self, **kwargs):
        """Initialize bounded synchronization and independent execution owners."""
        super().__init__(**kwargs)
        self.owners = [_RecordOwner(self), _RecordOwner(self)]
        self.ready = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.interrupt = False
        self.hold_cleanup = False
        self.bound = 0

    def _spawn(self, interpreter, deadline, record):
        """Prebind recovery responsibility before delegating real launch."""
        self.owners[self.bound].record = record
        self.bound += 1
        return super()._spawn(interpreter, deadline, record)

    def _before_publish_process(self, record):
        """Hold only the first execution's real child before publication."""
        if record is self.owners[0].record:
            self.ready.set()
            assert self.release.wait(5)

    def _wait_for_launch(self, record, remaining):
        """Inject host interruption only after the held child exists."""
        if self.interrupt and record is self.owners[0].record:
            assert self.ready.wait(5)
            raise KeyboardInterrupt('controlled launch interruption')
        return super()._wait_for_launch(record, remaining)

    def _terminate_record(self, record, process):
        """Optionally defer late cleanup to prove the retry authority handoff."""
        if self.hold_cleanup and record is self.owners[0].record:
            return False
        return super()._terminate_record(record, process)

    def _cleanup_launch_record(self, record, category):
        """Signal that the creator has finished its cleanup transaction."""
        try:
            return super()._cleanup_launch_record(record, category)
        finally:
            self.finished.set()


@pytest.mark.parametrize('interrupt', [False, True])
@pytest.mark.parametrize('hold_cleanup', [False, True])
def test_two_execution_launch_pending_blocks_only_own_capture_release(
        tmp_path, interrupt, hold_cleanup):
    """Pending launch is visible locally, non-retryable, and capture-protecting."""
    backend = _LateModuleBackend(temp_root=str(tmp_path))
    backend.interrupt, backend.hold_cleanup = interrupt, hold_cleanup
    registry = _Registry()
    tokens = [object(), object()]
    custodies = [ExecutionCleanupCustody(registry, token) for token in tokens]
    try:
        if interrupt:
            with pytest.raises(KeyboardInterrupt, match='controlled launch interruption'):
                backend.execute_module(
                    'topsailai.tests.unit.test_topsailai_hooks.module_transport_handlers:main',
                    _context(), 200, args=('return', None))
        else:
            result = backend.execute_module(
                    'topsailai.tests.unit.test_topsailai_hooks.module_transport_handlers:main',
                    _context(), 200, args=('return', None))
            assert result.status == 'timeout' and not result.cleanup_confirmed
        assert backend.ready.wait(5)
        peer = backend.execute_module(
            'topsailai.tests.unit.test_topsailai_hooks.module_transport_handlers:main',
            _context(), 2000, args=('return', None))
        assert peer.cleanup_confirmed
        for custody, owner in zip(custodies, backend.owners):
            custody.runner, custody.completed = owner, True
        record = backend.owners[0].record
        debts = backend.owners[0].cleanup_debts()
        assert len(debts) == 1 and debts[0].state == 'launching'
        assert backend.cleanup_debts_for_record(LaunchRecord(record.debt_id)) == ()
        assert backend.owners[1].cleanup_debts() == ()
        assert not backend.owners[1].retry_cleanup(record.debt_id)
        assert not backend.retry_cleanup(record.debt_id, record=LaunchRecord(record.debt_id))
        assert not backend.owners[0].retry_cleanup(record.debt_id)
        assert record.process is None
        assert not custodies[0].close().accepted
        assert custodies[1].close().accepted
        assert registry.released == [tokens[1]]
        backend.release.set()
        assert backend.finished.wait(5)
        if hold_cleanup:
            assert backend.owners[0].cleanup_debts()[0].state == 'process'
            backend.hold_cleanup = False
            assert backend.owners[0].retry_cleanup(record.debt_id)
        assert backend.owners[0].cleanup_debts() == ()
        assert record.process.poll() is not None
        assert custodies[0].close().accepted
        assert registry.released == [tokens[1], tokens[0]]
    finally:
        backend.release.set()
        backend.hold_cleanup = False
        if backend.ready.is_set():
            assert backend.finished.wait(5)
        deadline = time.monotonic() + 3
        while backend.cleanup_debts() and time.monotonic() < deadline:
            record = backend.owners[0].record
            backend.retry_cleanup(record.debt_id, record=record)
            time.sleep(.01)
        assert backend.cleanup_debts() == ()


def test_script_launch_timeout_retains_exact_pending_identity(tmp_path):
    """Script abandonment shares identity visibility without early retry authority."""
    backend = _LateModuleBackend(temp_root=str(tmp_path))
    record = LaunchRecord('pending-script')
    backend.owners[0].record = record
    try:
        result = backend.launch_script(
            argv=(backend._resolve_interpreter(), '-c', 'import time; time.sleep(5)'),
            cwd=str(tmp_path), environment=backend._worker_environment(),
            argument_environment_limit_bytes=65536,
            deadline=time.monotonic() + .2, record=record,
        )
        assert result.status == 'timeout' and not result.cleanup_confirmed
        assert backend.ready.wait(5)
        assert backend.cleanup_debts_for_record(record)[0].state == 'launching'
        assert backend.cleanup_debts_for_record(LaunchRecord(record.debt_id)) == ()
        assert not backend.retry_cleanup(record.debt_id, record=record)
        backend.release.set()
        assert backend.finished.wait(5)
        assert backend.cleanup_debts_for_record(record) == ()
        assert record.debt_id not in backend._launch_debt_records
        assert record.process.poll() is not None
    finally:
        backend.release.set()
        if backend.ready.is_set():
            assert backend.finished.wait(5)
        assert backend.cleanup_debts() == ()
