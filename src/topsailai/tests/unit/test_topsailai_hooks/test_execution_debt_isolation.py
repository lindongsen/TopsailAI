"""Execution-local cleanup regression with real concurrent children.

Author: DawsonLin.
"""
from concurrent.futures import ThreadPoolExecutor
import threading

from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.script_runner import OwnedHookScriptRunner
from topsailai.tests.unit.test_topsailai_hooks.test_script_runner_process import _child, _execute


class _Registry:
    """Observe exact capture token release without granting cleanup authority."""
    def __init__(self):
        """Collect released token identities."""
        self.released = []

    def release_hook_point_cleanup(self, token):
        """Record only the requested token."""
        self.released.append(token)


class _HeldCleanupBackend(IsolatedProcessBackend):
    """Hold one admitted record's cleanup while another child finishes."""
    def __init__(self, **kwargs):
        """Create a deterministic launch rendezvous."""
        super().__init__(**kwargs)
        self.barrier = threading.Barrier(2)
        self.held = None
        self.hold = True
        self.retries = []

    def launch_script(self, **kwargs):
        """Bind selected exact record before either launch crosses the barrier."""
        if threading.current_thread().name.endswith('_0'):
            self.held = kwargs['record']
        self.barrier.wait(5)
        return super().launch_script(**kwargs)

    def _terminate_record(self, record, process):
        """Retain debt for only the selected record."""
        if self.hold and record is self.held:
            return False
        return super()._terminate_record(record, process)

    def retry_cleanup(self, debt_id, *, record=None):
        """Record whether a foreign retry reached backend authority."""
        self.retries.append(debt_id)
        return super().retry_cleanup(debt_id, record=record)


def _run_pair(tmp_path):
    """Finish two real children and retain one exact pending cleanup owner."""
    root = tmp_path / 'backend'
    root.mkdir()
    backend = _HeldCleanupBackend(temp_root=str(root))
    runners = (OwnedHookScriptRunner(backend), OwnedHookScriptRunner(backend))
    entry = _child(tmp_path)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='custody') as pool:
        futures = [pool.submit(_execute, runner, entry, 'inspect') for runner in runners]
        results = [future.result(10) for future in futures]
    assert not results[0].cleanup_confirmed
    assert results[1].cleanup_confirmed
    assert backend.held is not None
    return backend, runners


def test_concurrent_safe_capture_release_ignores_other_execution_debt(tmp_path):
    """A cleanup-safe execution releases its token despite its peer's debt."""
    backend, runners = _run_pair(tmp_path)
    registry = _Registry()
    token = object()
    custody = ExecutionCleanupCustody(registry, token)
    custody.runner, custody.completed = runners[1], True
    try:
        assert runners[0].cleanup_debts()
        assert custody.cleanup_debts() == ()
        assert custody.close().accepted
        assert registry.released == [token]
    finally:
        backend.hold = False
        assert runners[0].retry_cleanup(backend.held.debt_id)


def test_concurrent_runner_cannot_retry_foreign_process_debt(tmp_path):
    """A foreign exact debt never reaches shared backend retry authority."""
    backend, runners = _run_pair(tmp_path)
    debt_id = backend.held.debt_id
    try:
        assert runners[1].retry_cleanup(debt_id) is False
        assert backend.retries == []
    finally:
        backend.hold = False
        assert runners[0].retry_cleanup(debt_id)
    assert runners[0].cleanup_debts() == ()

    retries = list(backend.retries)
    assert runners[0].retry_cleanup(debt_id) is True
    assert runners[0].retry_cleanup(debt_id) is True
    assert runners[1].retry_cleanup(debt_id) is False
    assert runners[0].retry_cleanup("unknown-debt") is False
    assert backend.retries == retries


def test_backend_rejects_mismatched_exact_record(tmp_path):
    """Reject both a wrong identifier and a same-ID foreign record without cleanup."""
    from topsailai.hooks.process_state import LaunchRecord

    backend, runners = _run_pair(tmp_path)
    record = backend.held
    try:
        foreign = LaunchRecord(record.debt_id)
        assert backend.cleanup_debts_for_record(foreign) == ()
        assert not backend.retry_cleanup(record.debt_id, record=foreign)
        assert not backend.retry_cleanup("unknown-debt", record=record)
        assert backend.cleanup_debts_for_record(record)
        assert not runners[1].cleanup_debts()
    finally:
        backend.hold = False
        assert runners[0].retry_cleanup(record.debt_id)


def test_unbound_storage_mapping_does_not_mint_process_authority(tmp_path):
    """Retaining storage without a launch record cannot authorize process retry."""
    from topsailai.hooks.temporary_storage import TemporaryStorageOwner

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    try:
        runner._remember_process_storage("unbound-process", owner)
        assert runner._process_storage["unbound-process"] is owner
        assert runner.retry_cleanup("unbound-process") is False
        assert owner.path.exists()
    finally:
        assert owner.cleanup()


def test_completion_publication_failure_retains_exact_custody(tmp_path, monkeypatch):
    """A refused completion transition preserves custody until canonical retry."""
    import pytest
    import topsailai.hooks.script_runner as module
    from topsailai.hooks.temporary_storage import TemporaryStorageOwner

    runner = OwnedHookScriptRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    owner = TemporaryStorageOwner(tmp_path)
    assert owner.allocate()
    owner.retain_cleanup_debt()
    custody = module._StorageCustody(owner)
    custody._write_state(pending=True, storage_alias=owner.cleanup_debts()[0])
    runner._write_prelaunch_storage(((id(owner), custody),))
    debt = custody.storage_alias
    assert owner.cleanup()
    custody._write_state(storage_settled=True)
    native = module._access_runner_authority

    def refuse_completion(value, authority):
        """Refuse only the completed-evidence publication, leaving registry intact."""
        observe, transition = native(value, authority)
        if authority == 2:
            return observe, lambda *args: False
        return observe, transition

    with monkeypatch.context() as patch:
        patch.setattr(module, "_access_runner_authority", refuse_completion)
        with pytest.raises(RuntimeError, match="settled completion publication"):
            runner._write_prelaunch_storage(retire=(id(owner),))
        assert runner._prelaunch_storage[id(owner)] is custody
        assert debt.debt_id not in native(runner, 2)[0]()
    runner._write_prelaunch_storage(retire=(id(owner),))
    assert id(owner) not in runner._prelaunch_storage
    assert runner.retry_cleanup(debt.debt_id)
