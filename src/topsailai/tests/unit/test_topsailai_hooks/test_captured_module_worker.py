"""Captured Module child execution regressions. Author: DawsonLin."""
import hashlib
import os
import sys
from dataclasses import replace

import pytest

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.hook_point_plan_contracts import CapturedModule, ModuleSource
from topsailai.hooks.module_invocation_protocol import ModuleInvocation
from topsailai.hooks.result_contracts import HandlerIdentity
from topsailai.tests.unit.test_topsailai_hooks.test_module_worker_transport import backend, gone
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


def captured(tmp_path, code, *, args=(), kwargs=None):
    """Construct a detached indexed locator with a distinct registered alias."""
    source = tmp_path / 'original' / 'sealed_plugin.py'
    source.parent.mkdir(exist_ok=True)
    source.write_text(code)
    target = tmp_path / 'sealed' / 'entry-000000' / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    source.write_text('raise AssertionError("live source executed")\n')
    return CapturedModule(
        HandlerIdentity('module-id', 'registered_alias', 'module'),
        ModuleSource('registered_alias', source, 'sealed_plugin', 'python_source',
                     'sealed_plugin:main', ModuleInvocation(args, kwargs or {})),
        'a' * 64, 0, 'entry-000000/sealed_plugin.py', target,
        hashlib.sha256(target.read_bytes()).hexdigest(), 'b' * 64,
    )


def test_real_captured_source_not_original(tmp_path):
    """Only the child imports captured bytes; exact worker identity exits."""
    marker = tmp_path / 'child.pid'
    code = ('import os\nfrom pathlib import Path\n'
            f'Path({str(marker)!r}).write_text(str(os.getpid()))\n'
            'def main(value):\n    return [value, __name__, __file__]\n')
    module = captured(tmp_path, code, args=(False,))
    result = backend(tmp_path).execute_captured_module(module, _context(), 2500)
    assert result.status == 'success'
    assert result.returned.present
    assert result.value == [False, 'sealed_plugin', str(module.captured_path)]
    pid = int(marker.read_text())
    assert pid != os.getpid() and gone(pid) and result.cleanup_confirmed
    assert 'sealed_plugin' not in sys.modules


from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import compile_extension


@pytest.mark.parametrize('body,value,representation', [
    ('def main():\n    return None\n', None, 'transported'),
    ('async def main():\n    return {"error": 1}\n', {'error': 1}, 'transported'),
    ('def main():\n    return object()\n', None, 'unavailable'),
])
def test_captured_normal_returns(tmp_path, body, value, representation):
    """Async and opaque normal results use existing presence envelopes."""
    result = backend(tmp_path).execute_captured_module(captured(tmp_path, body), _context(), 2500)
    assert result.status == 'success' and result.returned.present
    assert result.value == value and result.returned.representation == representation
    assert result.cleanup_confirmed


@pytest.mark.parametrize('body,category', [
    ('main = 1\n', 'protocol_error'),
    ('def __getattr__(name):\n    raise AssertionError()\n', 'protocol_error'),
    ('raise ImportError()\n', 'import_error'),
    ('def main():\n    raise RuntimeError()\n', 'handler_error'),
])
def test_captured_errors(tmp_path, body, category):
    """Invalid entries never run callable lookalikes or module attribute hooks."""
    result = backend(tmp_path).execute_captured_module(captured(tmp_path, body), _context(), 2500)
    assert result.status == 'error' and result.error_category == category
    assert not result.returned.present and result.cleanup_confirmed


def test_digest_rejects_before_plugin_execution(tmp_path):
    """Changed captured bytes cannot invoke or import the replacement."""
    module = captured(tmp_path, 'def main():\n    return 1\n')
    marker = tmp_path / 'tampered'
    module.captured_path.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    result = backend(tmp_path).execute_captured_module(module, _context(), 2500)
    assert result.status == 'error' and result.error_category == 'protocol_error'
    assert result.cleanup_confirmed and not marker.exists()


def test_compiled_captured_entry(tmp_path):
    """A genuine extension loads by its logical identity from the indexed copy."""
    original = compile_extension(tmp_path, 'sealed_plugin')
    target = tmp_path / 'sealed' / 'entry-000000' / original.name
    target.parent.mkdir(parents=True)
    target.write_bytes(original.read_bytes())
    module = CapturedModule(
        HandlerIdentity('id', 'alias', 'module'),
        ModuleSource('alias', original, 'sealed_plugin', 'python_extension', 'sealed_plugin:main'),
        'a' * 64, 0, 'entry-000000/' + original.name, target,
        hashlib.sha256(target.read_bytes()).hexdigest(), 'b' * 64,
    )
    original.write_bytes(b'not an extension')
    service = backend(tmp_path)
    processes = []
    spawn = service._spawn
    def recorded(*args):
        """Capture exact launched process identity."""
        lease = spawn(*args)
        processes.append(args[-1].process)
        return lease
    service._spawn = recorded
    result = service.execute_captured_module(module, _context(), 5000)
    assert result.status == 'success' and result.returned.present and result.value is None
    assert result.cleanup_confirmed and len(processes) == 1
    assert processes[0].poll() is not None and gone(processes[0].pid)
    assert 'sealed_plugin' not in sys.modules


def test_captured_timeout(tmp_path):
    """Timed-out captured code cannot leak its owned worker."""
    marker = tmp_path / 'timeout.pid'
    module = captured(tmp_path, 'import os,time\nfrom pathlib import Path\n'
                      f'Path({str(marker)!r}).write_text(str(os.getpid()))\n'
                      'def main():\n    time.sleep(10)\n')
    result = backend(tmp_path).execute_captured_module(module, _context(), 1500)
    assert result.status == 'timeout' and not result.returned.present
    assert result.cleanup_confirmed and gone(int(marker.read_text()))


def test_captured_cleanup_debt(tmp_path, monkeypatch):
    """Captured dispatch retains normal output while uncertain cleanup is retryable."""
    service = backend(tmp_path)
    original = service._terminate_record
    monkeypatch.setattr(service, '_terminate_record', lambda record, process: False)
    result = service.execute_captured_module(captured(tmp_path, 'def main():\n    return False\n'), _context(), 2500)
    assert result.status == 'success' and result.returned.present and result.value is False
    assert not result.cleanup_confirmed and result.cleanup_debt
    monkeypatch.setattr(service, '_terminate_record', original)
    assert service.retry_cleanup(result.cleanup_debt) and not service.cleanup_debts()


def test_captured_host_interrupt(tmp_path, monkeypatch):
    """Existing cleanup lease preserves interruption identity and exact child exit."""
    service = backend(tmp_path)
    processes = []
    interrupt = KeyboardInterrupt()
    def interrupted(record, process, *args):
        """Interrupt after launch ownership is established."""
        processes.append(process)
        raise interrupt
    monkeypatch.setattr(service, '_exchange', interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        service.execute_captured_module(captured(tmp_path, 'def main():\n    return 1\n'), _context(), 2500)
    assert caught.value is interrupt
    assert len(processes) == 1 and gone(processes[0].pid) and not service.cleanup_debts()


def test_invalid_record_before_launch(tmp_path, monkeypatch):
    """Only an exact immutable captured record can select this entry point."""
    service = backend(tmp_path)
    def forbidden(*args):
        """Reject unexpected spawn."""
        pytest.fail('spawn reached')
    monkeypatch.setattr(service, '_spawn', forbidden)
    assert service.execute_captured_module(object(), _context(), 1000).status == 'invalid_request'


@pytest.mark.parametrize('mutation', ['missing', 'oversize', 'wrong_kind', 'bad_suffix'])
def test_captured_loading_boundaries(tmp_path, mutation):
    """Bounded reads and kind-specific loaders cannot execute mismatched files."""
    module = captured(tmp_path, 'def main():\n    return 1\n')
    if mutation == 'missing':
        module = replace(module, captured_path=tmp_path / 'missing' / module.relative_path)
    elif mutation == 'oversize':
        module.captured_path.write_bytes(b'x' * (16 * 1024 * 1024 + 1))
    elif mutation == 'wrong_kind':
        module = replace(module, source=replace(module.source, kind='python_extension'))
    else:
        target = module.captured_path.with_suffix('.unknown')
        target.write_bytes(module.captured_path.read_bytes())
        module = replace(module, source=replace(module.source, source_path=module.source_path.with_suffix('.unknown'),
                                               kind='python_extension'),
                         relative_path='entry-000000/' + target.name, captured_path=target)
    result = backend(tmp_path).execute_captured_module(module, _context(), 2500)
    assert result.status == 'error' and not result.returned.present and result.cleanup_confirmed


def test_captured_invalid_context_before_spawn(tmp_path, monkeypatch):
    """Protocol admission rejects invalid context without starting a child."""
    service = backend(tmp_path)
    def forbidden(*args):
        """Fail at any unexpected process creation."""
        pytest.fail('spawn reached')
    monkeypatch.setattr(service, '_spawn', forbidden)
    result = service.execute_captured_module(captured(tmp_path, 'def main():\n    return 1\n'), object(), 1000)
    assert result.status == 'invalid_request' and not service.cleanup_debts()
    with pytest.raises(ValidationError):
        captured(tmp_path, 'def main():\n    return 1\n', args=(object(),))
