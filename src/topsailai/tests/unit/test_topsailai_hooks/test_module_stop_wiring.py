"""Explicit Module stop boundaries. Author: DawsonLin."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from topsailai.hooks.module_runner import OwnedHookModuleRunner
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.tests.unit.test_topsailai_hooks.test_captured_module_worker import captured
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


def test_expired_absolute_deadline_before_preparation(tmp_path):
    """An exhausted preparation-inclusive budget creates no launch record."""
    runner = OwnedHookModuleRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    deadline = time.monotonic() - 1
    module = captured(tmp_path, 'def main():\n    return False\n')
    result = runner.execute(module, _context(), 2000, deadline=deadline,
                            cancellation=threading.Event())
    assert result.status == 'timeout' and result.cleanup_confirmed
    assert runner._records == [] and runner.cleanup_debts() == ()


def test_running_cancellation_isolated_from_peer(tmp_path):
    """Cancel one real running child without changing another execution's signal."""
    marker = tmp_path / 'entered'
    module = captured(tmp_path, 'import time\nfrom pathlib import Path\n'
                      f'def main():\n    Path({str(marker)!r}).touch()\n    time.sleep(1)\n')
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    own, peer = OwnedHookModuleRunner(backend), OwnedHookModuleRunner(backend)
    cancellation = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(own.execute, module, _context(), 3000,
                             deadline=time.monotonic() + 3, cancellation=cancellation)
        wait_until = time.monotonic() + 3
        while not marker.exists() and not future.done() and time.monotonic() < wait_until:
            time.sleep(0.01)
        assert marker.exists(), future.exception() if future.done() else 'child never entered'
        other = pool.submit(peer.execute, module, _context(), 3000,
                            deadline=time.monotonic() + 3, cancellation=threading.Event())
        cancellation.set()
        result = future.result(4)
        assert result.status == 'cancelled' and result.cleanup_confirmed
        assert own._records[0].process.poll() is not None
        assert not peer.retry_cleanup(own._records[0].debt_id)
        assert other.result(4).status == 'success'
    assert own.cleanup_debts() == peer.cleanup_debts() == ()

import pytest
from topsailai.hooks.hook_point_plan_publication import ExecutionCleanupCustody
from topsailai.tests.unit.test_topsailai_hooks.test_execution_debt_isolation import _Registry
from topsailai.tests.unit.test_topsailai_hooks.test_module_runner_custody import _PausedBackend


@pytest.mark.parametrize('deadline,cancellation,category', [
    (float('nan'), None, 'invalid_deadline'),
    ('bad', None, 'invalid_deadline'),
    (None, object(), 'invalid_cancellation'),
])
def test_invalid_stop_configuration(tmp_path, deadline, cancellation, category):
    """Reject malformed stop inputs before creating resources."""
    runner = OwnedHookModuleRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    result = runner.execute(captured(tmp_path, 'def main():\n    return None\n'),
                            _context(), 1000, deadline=deadline, cancellation=cancellation)
    assert result.status == 'invalid_request' and result.error_category == category
    assert runner._records == []


@pytest.mark.parametrize('stage', ['before', 'receiver', 'terminal'])
def test_cancellation_at_handoffs(tmp_path, stage):
    """Cancel before creation, before launch or before accepting a complete response."""
    signal = threading.Event()
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    module = captured(tmp_path, 'def main():\n    return None\n')
    def receive(record):
        """Request cancellation without stealing backend recovery authority."""
        signal.set()
    if stage == 'before':
        signal.set()
    if stage == 'terminal':
        import topsailai.hooks.process_execution as delivery
        original = delivery.validate_module_response
        def validate(*args, **kwargs):
            """Cancel after real wire validation and before terminal acceptance."""
            result = original(*args, **kwargs)
            signal.set()
            return result
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(delivery, 'validate_module_response', validate)
            result = backend.execute_captured_module(module, _context(), 2000,
                                                     cancellation=signal)
    else:
        result = backend.execute_captured_module(module, _context(), 2000,
            cancellation=signal, record_receiver=receive if stage == 'receiver' else None)
    assert result.status == 'cancelled' and result.cleanup_confirmed
    assert backend.cleanup_debts() == ()


def test_launch_cancellation_retains_capture_until_exact_cleanup(tmp_path):
    """A cancelled pending launch cannot release capture or transfer creator authority."""
    backend = _PausedBackend(temp_root=str(tmp_path))
    own, peer = OwnedHookModuleRunner(backend), OwnedHookModuleRunner(backend)
    backend.runner = own
    signal = threading.Event()
    registry, token = _Registry(), object()
    custody = ExecutionCleanupCustody(registry, token)
    custody.runner = own
    module = captured(tmp_path, 'def main():\n    return False\n')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(own.execute, module, _context(), 2000,
                                 deadline=time.monotonic() + 2, cancellation=signal)
            assert backend.ready.wait(3)
            signal.set()
            result = future.result(3)
        custody.completed = True
        assert result.status == 'cancelled' and not result.cleanup_confirmed
        record = backend.held
        assert own.cleanup_debts()[0].state == 'launching'
        assert not own.retry_cleanup(record.debt_id)
        assert peer.cleanup_debts() == () and not peer.retry_cleanup(record.debt_id)
        assert not custody.close().accepted and registry.released == []
        backend.release.set()
        assert backend.finished.wait(3)
        backend.hold_cleanup = False
        assert custody.retry_cleanup(record.debt_id)
        assert record.process.poll() is not None
        assert custody.close().accepted and registry.released == [token]
    finally:
        backend.release.set()
        backend.hold_cleanup = False
        if backend.held is not None:
            backend.finished.wait(3)
            backend.retry_cleanup(backend.held.debt_id, record=backend.held)


def test_cancellation_after_admission_before_record(tmp_path, monkeypatch):
    """A stop during request encoding prevents record and resource creation."""
    import topsailai.hooks.process_execution as delivery
    signal = threading.Event()
    original = delivery.encode_frame
    def encode(*args, **kwargs):
        """Preserve real encoding and then observe a concurrent cancellation."""
        frame = original(*args, **kwargs)
        signal.set()
        return frame
    monkeypatch.setattr(delivery, 'encode_frame', encode)
    runner = OwnedHookModuleRunner(IsolatedProcessBackend(temp_root=str(tmp_path)))
    result = runner.execute(captured(tmp_path, 'def main():\n    return None\n'),
                            _context(), 2000, cancellation=signal)
    assert result.status == 'cancelled' and result.cleanup_confirmed
    assert runner._records == [] and runner.cleanup_debts() == ()


@pytest.mark.parametrize('boundary', ['before_poll', 'select_error', 'select_return'])
def test_transport_stop_boundaries_preserve_cleanup(tmp_path, monkeypatch, boundary):
    """Stop facts across selector boundaries terminate only the exact real child."""
    import topsailai.hooks.process_backend as transport
    signal = threading.Event()
    original_selector = transport.selectors.DefaultSelector
    class StopSelector(original_selector):
        """Inject cancellation at an actual selector boundary without changing ownership."""
        def select(self, timeout=None):
            """Report cancellation before an error or an empty readiness batch."""
            signal.set()
            if boundary == 'select_error':
                raise OSError('controlled select failure')
            return []
    class Backend(IsolatedProcessBackend):
        """Observe the transport boundary after real launch and lease handoff."""
        def _exchange(self, *args, **kwargs):
            """Arm a stop before polling or inside the selector observation."""
            if boundary == 'before_poll':
                signal.set()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(transport.selectors, 'DefaultSelector', StopSelector)
                return super()._exchange(*args, **kwargs)
    runner = OwnedHookModuleRunner(Backend(temp_root=str(tmp_path)))
    result = runner.execute(captured(tmp_path, 'def main():\n    return None\n'),
                            _context(), 2000, cancellation=signal)
    assert result.status == 'cancelled' and result.cleanup_confirmed
    assert runner._records[0].process.poll() is not None
    assert runner.cleanup_debts() == ()
