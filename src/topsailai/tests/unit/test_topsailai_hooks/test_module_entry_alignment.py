"""Real child entry admission agreement. Author: DawsonLin."""

import os
import sys

import pytest

from topsailai.hooks.module_discovery_probe import probe_candidate
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import compile_extension
from topsailai.tests.unit.test_topsailai_hooks.test_module_worker_transport import backend, gone
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


def _service(root, monkeypatch):
    """Give only child processes the plugin search path and record exact launches."""
    service = backend(root)
    environment = service._worker_environment
    def child_environment():
        """Keep plugin imports off the host path."""
        env = environment()
        env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
        return env
    monkeypatch.setattr(service, '_worker_environment', child_environment)
    processes = []
    spawn = service._spawn
    def recorded_spawn(*args):
        """Retain exact Popen objects without minting historical PID authority."""
        result = spawn(*args)
        processes.append(args[-1].process)
        return result
    monkeypatch.setattr(service, '_spawn', recorded_spawn)
    return service, processes


def _agreement(root, name, path, expected, monkeypatch):
    """Probe then invoke in separate children, checking cleanup and host isolation."""
    service, processes = _service(root, monkeypatch)
    entry, probe = probe_candidate(service, root, 'test.point', name, path)
    result = service.execute_module(name + ':main', _context(), 5000)
    assert entry.entry_valid is expected
    assert probe.status == 'success' and probe.cleanup_confirmed
    assert result.status == ('success' if expected else 'error')
    assert result.cleanup_confirmed and not service.cleanup_debts()
    if expected:
        assert result.returned.present and result.returned.representation == 'transported'
    else:
        assert not result.returned.present
    assert len(processes) == 2
    assert all(p is not None and p.pid != os.getpid() and p.poll() is not None
               and gone(p.pid) for p in processes)
    assert name not in sys.modules
    assert not (root / 'observed').exists()
    return result


def test_compiled_entry_discovery_and_execution(tmp_path, monkeypatch):
    """A genuine C function is admitted and completed only in an owned child."""
    name = 'aligned_compiled_plugin'
    path = compile_extension(tmp_path, name)
    result = _agreement(tmp_path, name, path, True, monkeypatch)
    assert result.value is None


@pytest.mark.parametrize('body,expected', [
    ('def main():\n    return False\n', True),
    ('async def main():\n    return {"async": True}\n', True),
    ('VALUE = 1\n', False),
    ('main = 1\n', False),
    ('main = None\n', False),
    ('class Entry:\n    def __call__(self):\n        mark()\nmain = Entry()\n', False),
    ('class Entry:\n    @property\n    def __class__(self):\n        mark()\n        raise RuntimeError()\n    def __call__(self):\n        mark()\nmain = Entry()\n', False),
    ('class Meta(type):\n    def __eq__(self, other):\n        mark()\n        raise RuntimeError()\nclass Entry(metaclass=Meta):\n    def __call__(self):\n        mark()\nmain = Entry()\n', False),
    ('def __getattr__(name):\n    mark()\n    return lambda: None\n', False),
    ('class Entry:\n    @property\n    def main(self):\n        mark()\nmain = Entry.main\n', False),

])
def test_python_entry_agreement(tmp_path, monkeypatch, body, expected):
    """Exact entry types agree without executing hostile classification hooks."""
    name = 'aligned_source_plugin'
    marker = tmp_path / 'import-pids'
    path = tmp_path / (name + '.py')
    path.write_text(
        'import os\nfrom pathlib import Path\n'
        f'with Path({str(marker)!r}).open("a") as stream: stream.write(str(os.getpid()) + "\\n")\n'
        f'def mark():\n    Path({str(tmp_path / "observed")!r}).touch()\n' + body)
    _agreement(tmp_path, name, path, expected, monkeypatch)
    imported = [int(line) for line in marker.read_text().splitlines()]
    assert len(imported) == 2 and all(pid != os.getpid() and gone(pid) for pid in imported)
