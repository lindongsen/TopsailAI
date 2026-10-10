"""Real isolated v2 invocation and cleanup checks. Author: DawsonLin."""
import concurrent.futures
import os
import sys
import time
from pathlib import Path

import pytest
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import WorkerResult
from topsailai.hooks.contracts import ValidationError
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context, HANDLERS

MODULE = 'topsailai.tests.unit.test_topsailai_hooks.module_transport_handlers'
REF = MODULE + ':main'


def backend(tmp_path, **kwargs):
    """Create an explicitly owned process root."""
    assert MODULE not in sys.modules
    service = IsolatedProcessBackend(temp_root=str(tmp_path), **kwargs)
    import coverage
    active = coverage.Coverage.current()
    if active is not None and 'worker_module' not in kwargs:
        data_file = active.config.data_file
        wrapper = tmp_path / 'measured_worker.py'
        wrapper.write_text(
            'import coverage, os\n'
            'cov = coverage.Coverage(data_file=os.environ["MODULE_COVERAGE_FILE"], '
            'branch=True, source=["topsailai.hooks"])\n'
            'cov.start()\n'
            'from topsailai.hooks import worker\n'
            'original = worker.encode_frame\n'
            'def measured(*args, **kwargs):\n'
            '    result = original(*args, **kwargs)\n'
            '    cov.save()\n'
            '    return result\n'
            'worker.encode_frame = measured\n'
            'try: worker.main()\n'
            'finally: cov.stop(); cov.save()\n'
        )
        service._worker_module = 'measured_worker'
        original = service._worker_environment
        def measured_environment():
            """Enable child coverage only through a test-owned bootstrap module."""
            env = original()
            env['PYTHONPATH'] = str(tmp_path) + os.pathsep + env.get('PYTHONPATH', '')
            env['MODULE_COVERAGE_FILE'] = data_file + '.child.' + str(time.time_ns())
            return env
        service._worker_environment = measured_environment
    return service


def gone(pid):
    """Check exact PID absence without signaling a historical identity."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def assert_closed(tmp_path, result):
    """Observe launch and invocation separately and confirm owned worker exit."""
    imported = int((tmp_path / 'import.pid').read_text())
    invoked = int((tmp_path / 'invoke.pid').read_text())
    assert imported == invoked and imported != os.getpid()
    assert gone(imported)
    assert result.cleanup_confirmed
    assert MODULE not in sys.modules


@pytest.mark.parametrize('value', [False, None, 0, [], {}, {'error': 1}, {'a': [1, None, '雪']}])
def test_normal_values(tmp_path, value):
    """No normal return value implies failure or blocking."""
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=('return', value))
    assert result.status == 'success'
    assert result.returned.present and result.returned.representation == 'transported'
    assert result.returned.value == value and result.value == value
    assert result.transport_diagnostic is None
    assert_closed(tmp_path, result)


@pytest.mark.parametrize('mode', ['hostile', 'nested', 'cycle', 'oversize', 'plain_generator', 'shadowed_awaitable'])
def test_unavailable_normal_returns(tmp_path, mode):
    """Unsupported normal objects remain success without observation."""
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=(mode,))
    assert result.status == 'success' and result.returned.present
    assert result.returned.representation == 'unavailable' and result.value is None
    assert result.transport_diagnostic.category == 'return_unavailable'
    assert not (tmp_path / 'observed').exists()
    assert_closed(tmp_path, result)


def test_arguments_and_exception_detachment(tmp_path):
    """Owned args and Unicode kwargs reach only the child without context injection."""
    owned = [1]
    service = backend(tmp_path)
    result = service.execute_module(REF, _context(), 2500, args=('echo', owned), kwargs={'雪': '值'})
    assert result.value['value'] == [1] and result.value['kwargs'] == {'雪': '值'}
    failed = service.execute_module(REF, _context(), 2500, args=('mutate', owned))
    assert owned == [1]
    assert failed.status == 'error' and failed.error_category == 'handler_error'
    assert not failed.returned.present
    assert_closed(tmp_path, failed)


@pytest.mark.parametrize('args,kwargs,ref,context', [
    ((object(),), {}, REF, _context()), ((), {'x': object()}, REF, _context()),
    (object(), {}, REF, _context()), ((), [], REF, _context()),
    ((), {}, 'invalid:other', _context()), ((), {}, REF, object()),
])
def test_admission_before_launch(tmp_path, monkeypatch, args, kwargs, ref, context):
    """Invalid admission cannot spawn or import a plugin."""
    service = backend(tmp_path)
    def forbidden(*args):
        """Prove the launch boundary is unreachable."""
        pytest.fail('spawn reached')
    monkeypatch.setattr(service, '_spawn', forbidden)
    result = service.execute_module(ref, context, 1000, args=args, kwargs=kwargs)
    assert result.status == 'invalid_request' and not result.returned.present
    assert not service.cleanup_debts() and not (tmp_path / 'import.pid').exists()


def test_import_error(tmp_path):
    """Import failure remains an execution error and absent return."""
    result = backend(tmp_path).execute_module('missing.module:main', _context(), 2500)
    assert result.status == 'error' and result.error_category == 'import_error'
    assert not result.returned.present and result.cleanup_confirmed


@pytest.mark.parametrize('mode,status', [('descendant', 'success'), ('sleep', 'timeout')])
def test_descendant_cleanup(tmp_path, mode, status):
    """Both normal completion and timeout reap exact recorded descendants."""
    result = backend(tmp_path).execute_module(REF, _context(),
                                              3000 if status == 'success' else 1500,
                                              args=(mode, 1))
    assert result.status == status
    assert_closed(tmp_path, result)
    assert gone(int((tmp_path / 'descendant.pid').read_text()))
    if status == 'timeout':
        assert not result.returned.present


@pytest.mark.parametrize('mutation', ['version', 'bool_version', 'correlation', 'token', 'delivery', 'extra', 'contradiction'])
def test_malformed_terminal(tmp_path, monkeypatch, mutation):
    """Untrusted child envelopes fail closed before result publication."""
    import topsailai.hooks.process_execution as execution
    original = execution.validate_module_response
    def corrupt(response, **expected):
        """Mutate the decoded wire before its real validator."""
        if mutation in ('version', 'bool_version'):
            response['protocol_version'] = 1 if mutation == 'version' else True
        elif mutation == 'extra':
            response['extra'] = 1
        elif mutation == 'contradiction':
            response['returned']['present'] = False
        else:
            key = {'correlation': 'correlation_id', 'token': 'channel_token', 'delivery': 'delivery_id'}[mutation]
            response[key] = 'wrong'
        return original(response, **expected)
    monkeypatch.setattr(execution, 'validate_module_response', corrupt)
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=('return', None))
    assert result.status == 'invalid_output' and not result.returned.present
    assert_closed(tmp_path, result)


@pytest.mark.parametrize('worker', ['fake_worker_malformed', 'fake_worker_wrong', 'fake_worker_modes'])
def test_fake_v1_response_fails_closed(tmp_path, worker):
    """Malformed or incompatible frames never authorize a v2 normal return."""
    service = backend(tmp_path, worker_module='topsailai.tests.unit.test_topsailai_hooks.' + worker)
    result = service.execute_module(REF, _context(), 1000, args=('return', None))
    assert result.status in ('invalid_output', 'worker_lost', 'timeout')
    assert not result.returned.present and result.cleanup_confirmed


def test_concurrent_protocol_selection(tmp_path):
    """Per-call codecs cannot cross concurrent v1 and v2 executions."""
    service = backend(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        legacy = pool.submit(service.execute, HANDLERS + ':sync_success', _context(), 2500)
        modern = pool.submit(service.execute_module, REF, _context(), 2500, args=('return', False))
        old, new = legacy.result(), modern.result()
    assert old.status == new.status == 'success'
    assert not old.returned.present and new.returned.present and new.value is False


def test_legacy_positional_result():
    """Appending metadata preserves old positional fields and absent presence."""
    result = WorkerResult('success', None, None, b'', b'', 0, 0, True, None)
    assert not result.returned.present and result.transport_diagnostic is None


@pytest.mark.parametrize('frame', [b'\x00\x00\x00\x01{', b'\x00\x01\x00\x01', b'\x00\x00\x00\x08{}', b'\x00\x00\x00\x02{}extra'])
def test_raw_invalid_frames(tmp_path, monkeypatch, frame):
    """Malformed, oversized, truncated and trailing frames fail closed."""
    service = backend(tmp_path)
    def exchange(record, process, fd, request, buffers, dropped, deadline):
        """Supply one controlled corrupt terminal buffer through owned resources."""
        buffers['result'].extend(frame)
        return 'result'
    monkeypatch.setattr(service, '_exchange', exchange)
    result = service.execute_module(REF, _context(), 2500, args=('return', None))
    assert result.status == 'invalid_output' and not result.returned.present
    assert result.cleanup_confirmed


def test_post_validation_deadline(tmp_path, monkeypatch):
    """A late valid response cannot authorize a normal return."""
    service = backend(tmp_path)
    monkeypatch.setattr(service, '_deadline_expired', lambda deadline: True)
    result = service.execute_module(REF, _context(), 2500, args=('return', 1))
    assert result.status == 'timeout' and not result.returned.present
    assert_closed(tmp_path, result)


def test_cleanup_debt_retains_return(tmp_path, monkeypatch):
    """Uncertain termination publishes queryable debt without dropping safe metadata."""
    service = backend(tmp_path)
    original = service._terminate_record
    monkeypatch.setattr(service, '_terminate_record', lambda record, process: False)
    result = service.execute_module(REF, _context(), 2500, args=('hostile',))
    assert result.status == 'success' and result.returned.present
    assert not result.cleanup_confirmed and result.cleanup_debt
    assert service.cleanup_debts()[0].debt_id == result.cleanup_debt
    monkeypatch.setattr(service, '_terminate_record', original)
    assert service.retry_cleanup(result.cleanup_debt)
    assert not service.cleanup_debts()


def test_host_interrupt_cleanup(tmp_path, monkeypatch):
    """Host interrupts preserve identity after settling launched resources."""
    service = backend(tmp_path)
    interrupt = KeyboardInterrupt()
    captured = []
    def interrupted(record, process, fd, request, buffers, dropped, deadline):
        """Interrupt at the established process ownership boundary."""
        captured.append(process)
        raise interrupt
    monkeypatch.setattr(service, '_exchange', interrupted)
    with pytest.raises(KeyboardInterrupt) as raised:
        service.execute_module(REF, _context(), 2500, args=('return', None))
    assert raised.value is interrupt
    assert captured[0].poll() is not None and not service.cleanup_debts()


def test_channel_close_debt_retry(tmp_path, monkeypatch):
    """Channel uncertainty does not bypass the cleanup publication transaction."""
    service = backend(tmp_path)
    original = service._close_record_channels
    monkeypatch.setattr(service, '_close_record_channels', lambda record: None)
    result = service.execute_module(REF, _context(), 2500, args=('return', None))
    assert result.status == 'success' and result.returned.present
    assert not result.cleanup_confirmed and result.cleanup_debt
    monkeypatch.setattr(service, '_close_record_channels', original)
    assert service.retry_cleanup(result.cleanup_debt)


def test_import_deadline(tmp_path, monkeypatch):
    """One absolute deadline includes child import rather than just invocation."""
    root = tmp_path / 'plugins'
    root.mkdir()
    (root / 'slow_module.py').write_text('import time; time.sleep(60)\ndef main(): return 1\n')
    service = backend(tmp_path)
    original = service._worker_environment
    def environment():
        """Inject only the test-owned module search root into the child."""
        result = original()
        result['PYTHONPATH'] = str(root) + os.pathsep + result.get('PYTHONPATH', '')
        return result
    monkeypatch.setattr(service, '_worker_environment', environment)
    started = time.monotonic()
    result = service.execute_module('slow_module:main', _context(), 200)
    assert result.status == 'timeout' and not result.returned.present
    assert result.cleanup_confirmed and time.monotonic() - started < 2
    assert 'slow_module' not in sys.modules


@pytest.mark.parametrize('mode', ['awaitable', 'generator_awaitable', 'custom_awaitable'])
def test_child_awaitable(tmp_path, mode):
    """v2 preserves worker-owned awaitable execution without host scheduling."""
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=(mode,))
    assert result.status == 'success' and result.returned.value == 'awaited'
    assert_closed(tmp_path, result)


def test_invalid_temp_root(tmp_path):
    """Preflight filesystem rejection remains structured before launch."""
    path = tmp_path / 'file'
    path.write_text('not a directory')
    result = IsolatedProcessBackend(temp_root=str(path)).execute_module(REF, _context(), 1000)
    assert result.status == 'unsupported_backend' and not result.returned.present


def test_legacy_build_error_priority(tmp_path):
    """Moving the transaction retains the legacy builder exception boundary."""
    with pytest.raises((ValidationError, AttributeError)):
        backend(tmp_path).execute(REF, object(), 1000)


def test_measured_v1_worker(tmp_path):
    """The same measured child bootstrap retains legacy normal JSON output."""
    result = backend(tmp_path).execute(HANDLERS + ':sync_success', _context(), 2500)
    assert result.status == 'success' and result.value['delivery'] == 'delivery-1'
    assert not result.returned.present and result.cleanup_confirmed


@pytest.mark.parametrize('version', [True, 3, None])
def test_worker_rejects_version_before_import(monkeypatch, version):
    """Reject unvalidated protocol discrimination without resolving a plugin."""
    from topsailai.hooks import worker
    from topsailai.hooks.worker_protocol import encode_frame
    monkeypatch.setattr(worker, '_install_stop_handlers', lambda: None)
    monkeypatch.setattr(worker, '_read_request_frame', lambda limit: encode_frame({'protocol_version': version}, limit))
    def forbidden(ref):
        """Assert no plugin resolution after bad admission."""
        pytest.fail('plugin resolved')
    monkeypatch.setattr(worker, '_resolve_handler', forbidden)
    assert worker.run_worker(-1, 131072, 65536) == 2


def test_measured_v1_unsupported_return(tmp_path):
    """Legacy unsupported returns remain invalid_output rather than v2 unavailable."""
    result = backend(tmp_path).execute(HANDLERS + ':return_invalid_value', _context(), 2500)
    assert result.status == 'invalid_output' and result.error_category == 'protocol_error'
    assert not result.returned.present and result.transport_diagnostic is None
    assert result.cleanup_confirmed



@pytest.mark.parametrize('mode', ['hostile_class', 'hostile_meta'])
def test_opaque_class_not_observed(tmp_path, mode):
    """A hostile class property cannot turn a normal child return into failure."""
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=(mode,))
    assert_closed(tmp_path, result)
    assert result.status == 'success' and result.returned.present
    assert result.returned.representation == 'unavailable' and result.value is None
    assert result.transport_diagnostic.category == 'return_unavailable'
    assert result.transport_diagnostic.message == ''
    assert not (tmp_path / 'observed').exists()



def test_child_await_exception(tmp_path):
    """A failure in actual awaiting remains an execution error with absent return."""
    result = backend(tmp_path).execute_module(REF, _context(), 2500, args=('await_error',))
    assert result.status == 'error' and result.error_category == 'handler_error'
    assert not result.returned.present and result.transport_diagnostic is None
    assert_closed(tmp_path, result)
