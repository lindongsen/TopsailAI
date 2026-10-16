"""Failure-path checks for BDD helper ownership. Author: DawsonLin."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.bdd import hook_point_resource_harness as harness
from tests.bdd.steps.hook_point_resource_steps import finish_resource_case
from tests.bdd.temp_storage import BDDTempStorage


@pytest.fixture
def case(tmp_path):
    """Construct a helper-only case without copying the complete package."""
    root = tmp_path / 'scenario'
    root.mkdir()
    context = object.__new__(harness.ResourceScenario)
    context.root, context.known, context.process = root, [], None
    return context


def record(case, pid, start, descendant=False):
    """Persist identities in the same format as real plugin evidence."""
    data = dict(pid=pid, start_identity=start)
    path = case.root / ('descendant.json' if descendant else 'trace.jsonl')
    path.write_text(json.dumps(data) + '\n')


def test_real_plugins_and_descendant_are_reaped(case):
    """Exercise real leaked children including one recorded only as a descendant."""
    children = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
                for _ in range(3)]
    try:
        for index, child in enumerate(children):
            start = harness.identity(child.pid)[0]
            if index == 0:
                record(case, child.pid, start)
            elif index == 1:
                case.known.append((child.pid, start))
            else:
                record(case, child.pid, start, descendant=True)
        with pytest.raises(ExceptionGroup) as caught:
            case.close()
        assert len(caught.value.exceptions) == 3
        assert all(harness.identity(child.pid) is None for child in children)
        assert (case.root.parent / 'evidence/scenario-descendant.json').exists()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)


def test_failures_do_not_truncate_other_processes(case, monkeypatch):
    """Retain both settlement errors while attempting every owned identity."""
    case.known = [(101, 'a'), (102, 'b'), (103, 'c')]
    calls = []

    def settle(pid, start):
        """Inject independent failures with evidence already safely copied."""
        assert (case.root.parent / 'evidence/scenario-trace.jsonl').exists()
        calls.append(pid)
        if pid != 102:
            raise OSError(str(pid))

    record(case, 101, 'a')
    monkeypatch.setattr(case, '_settle_identity', settle)
    with pytest.raises(ExceptionGroup) as caught:
        case.close()
    assert calls == [101, 102, 103]
    assert len(caught.value.exceptions) == 2
    assert case.root.exists()


def test_host_wait_failure_still_kills_and_cleans_plugins(case, monkeypatch):
    """A host wait timeout must not bypass forced host stop or plugin cleanup."""
    calls = []

    def wait(timeout):
        """Fail the first host wait and confirm the forced-stop wait."""
        calls.append('wait')
        if calls.count('wait') == 1:
            raise subprocess.TimeoutExpired('owned-host', timeout)

    case.process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append('terminate'),
                                   kill=lambda: calls.append('kill'), wait=wait)
    case.known = [(101, 'a')]
    monkeypatch.setattr(case, '_settle_identity', lambda *args: calls.append('plugin'))
    with pytest.raises(ExceptionGroup):
        case.close()
    assert calls == ['terminate', 'wait', 'kill', 'wait', 'plugin']


def test_stale_identity_is_never_signalled(case, monkeypatch):
    """Identifier reuse is absence of authority, not permission to kill the new process."""
    monkeypatch.setattr(harness, 'identity', lambda pid: ('new-start', 'S'))
    monkeypatch.setattr(harness, 'os', SimpleNamespace(kill=lambda *args: pytest.fail('stale signal')))
    case._settle_identity(101, 'old-start')


def test_unconfirmed_exit_is_reported(case, monkeypatch):
    """A still-present identity cannot be reported as settled after a signal."""
    ticks = iter([0, 4])
    signals = []
    monkeypatch.setattr(harness, 'identity', lambda pid: ('start', 'S'))
    monkeypatch.setattr(harness, 'os', SimpleNamespace(
        kill=lambda *args: signals.append(args), waitpid=lambda *args: (0, 0), WNOHANG=1))
    monkeypatch.setattr(harness, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(AssertionError, match='exit unconfirmed'):
        case._settle_identity(101, 'start')
    assert signals == [(101, harness.signal.SIGKILL)]


def test_evidence_failure_does_not_skip_process_cleanup(case, monkeypatch):
    """Copy failure retains resources but does not strand known processes."""
    (case.root.parent / 'evidence').write_text('not a directory')
    calls = []
    case.known = [(101, 'a')]
    monkeypatch.setattr(case, '_settle_identity', lambda *args: calls.append(args))
    with pytest.raises(ExceptionGroup):
        case.close()
    assert calls == [(101, 'a')]
    assert case.root.exists()


def test_malformed_trace_does_not_skip_descendant(case, monkeypatch):
    """Independent descendant evidence survives a partial or invalid trace line."""
    (case.root / 'trace.jsonl').write_text('incomplete json\n')
    record(case, 102, 'b', descendant=True)
    calls = []
    monkeypatch.setattr(case, '_settle_identity', lambda *args: calls.append(args))
    with pytest.raises(ExceptionGroup):
        case.close()
    assert calls == [(102, 'b')]


@pytest.mark.parametrize('fails', [True, False])
def test_fixture_deletes_only_after_success(tmp_path, fails):
    """Verify the actual fixture finalizer retains failed trees and neighbor evidence."""
    storage = BDDTempStorage(tmp_path)
    root = storage.create_directory('owned-')
    neighbor = tmp_path / 'neighbor'
    neighbor.write_text('unrelated sentinel')

    def close():
        """Model an unresolved cleanup obligation without spawning a leaked process."""
        if fails:
            raise ExceptionGroup('unresolved', [OSError('owned process')])

    context = SimpleNamespace(root=root, close=close)
    if fails:
        with pytest.raises(ExceptionGroup):
            finish_resource_case(context, storage, neighbor)
        assert root.exists() and neighbor.read_text() == 'unrelated sentinel'
        storage.cleanup()
        neighbor.unlink()
        print(f'deleted owned sentinel {neighbor}')
    else:
        finish_resource_case(context, storage, neighbor)
        assert not root.exists() and not neighbor.exists()
