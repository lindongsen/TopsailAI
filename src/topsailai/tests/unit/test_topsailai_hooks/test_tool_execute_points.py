"""Tool execution observation contract tests. Author: DawsonLin."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import topsailai.hooks as hooks
from topsailai.ai_base.agent_types import tool
from topsailai.ai_base.agent_types.exception import AgentToolCallException
from topsailai.ai_base.tool_approval import decorator as approval
from topsailai.hooks.points.aibase.tool_execute_payloads import build_tool_execute_payload

PHASES = ('before', 'after', 'error')
COMMON = {'tool_name', 'argument_count', 'argument_keys'}


@pytest.fixture(autouse=True)
def isolated_points(monkeypatch):
    """Restore point configuration and suppress unrelated statistics output."""
    hooks.initialize_hook_points({})
    monkeypatch.setattr(tool.tool_stat, 'record_tool_call', lambda **kwargs: None)
    monkeypatch.setattr(tool.print_tool, 'print_error', lambda *args, **kwargs: None)
    yield
    hooks.initialize_hook_points({})


def execute(function, args=None):
    """Exercise the exact body without duplicate-cache and approval wrappers."""
    return inspect.unwrap(tool.exec_tool_func)(function, args or {}, 'fixture_tool')


def record_points(monkeypatch):
    """Record each business-boundary invocation without interpreting returns."""
    records = []
    for phase in PHASES:
        def capture(_phase=phase, **payload):
            """Detach the received metadata and return an ignored proposal."""
            records.append((_phase, payload))
            return {'veto': True}
        monkeypatch.setattr(tool, f'hook__aibase__{phase}__tool_execute', capture)
    return records


@pytest.mark.parametrize('failed', [False, True])
def test_phase_counts_and_exact_metadata(monkeypatch, failed):
    """Only the actual outcome emits a terminal point; values never escape."""
    records = record_points(monkeypatch)
    value = object()
    args = {'token': 'SECRET-ARG', 'alpha': [value]}

    def target(**kwargs):
        """Assert original argument identities and optionally fail."""
        assert kwargs['alpha'] is args['alpha']
        if failed:
            raise ValueError('SECRET-ERROR')
        return value

    result = execute(target, args)
    assert result == 'SECRET-ERROR' if failed else result is value
    assert [phase for phase, _ in records] == ['before', 'error' if failed else 'after']
    for phase, payload in records:
        extra = {'error_category'} if phase == 'error' else {'duration_sec'} if phase == 'after' else set()
        assert set(payload) == COMMON | extra
        assert payload['tool_name'] == 'fixture_tool'
        assert payload['argument_count'] == 2
        assert payload['argument_keys'] == ('alpha', 'token')
        assert 'SECRET' not in str(payload)
    if failed:
        assert records[-1][1]['error_category'] == 'ValueError'
    else:
        assert records[-1][1]['duration_sec'] >= 0


@pytest.mark.parametrize('failed', [False, True])
def test_empty_configuration_is_noop(failed):
    """Absent bundled resources preserves returns and existing error conversion."""
    result = {'original': True}

    def target():
        """Return the original object or raise an ordinary error."""
        if failed:
            raise RuntimeError('expected text')
        return result

    actual = execute(target)
    assert actual == 'expected text' if failed else actual is result


@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('body', ['return False', 'return None', "return {'replace': 1}", "raise RuntimeError('plugin failed')"])
def test_real_module_returns_and_failures_are_isolated(tmp_path, phase, body):
    """Real import and invocation cannot replace a tool outcome."""
    marker = tmp_path / 'ran'
    module = tmp_path / 'plugin.py'
    module.write_text(f"def main(**kwargs):\n    open({str(marker)!r}, 'w').write('yes')\n    {body}\n")
    hooks.initialize_hook_points({f'hook__aibase__{phase}__tool_execute': {'modules': str(module)}})

    def target():
        """Select the ordinary error path only for the error Hook Point."""
        if phase == 'error':
            raise ValueError('tool error')
        return 'original'

    assert execute(target) == ('tool error' if phase == 'error' else 'original')
    assert marker.read_text() == 'yes'


@pytest.mark.parametrize('exception_type', [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
@pytest.mark.parametrize('phase', PHASES)
def test_real_module_host_controls_propagate(tmp_path, exception_type, phase):
    """Host controls from real Modules are never converted into tool errors."""
    expression = 'asyncio.CancelledError' if exception_type is asyncio.CancelledError else exception_type.__name__
    module = tmp_path / 'interrupt.py'
    module.write_text(f"import asyncio\ndef main(**kwargs):\n    raise {expression}('stop')\n")
    hooks.initialize_hook_points({f'hook__aibase__{phase}__tool_execute': {'modules': str(module)}})

    def target():
        """Reach the error Hook Point when requested."""
        if phase == 'error':
            raise ValueError('tool failure')
        return 'original'

    with pytest.raises(exception_type, match='stop'):
        execute(target)


@pytest.mark.parametrize('exception_type', [KeyboardInterrupt, SystemExit, asyncio.CancelledError, AgentToolCallException])
def test_tool_control_identity_and_no_terminal_hook(monkeypatch, exception_type):
    """Tool and host control flow retains identity and emits no error point."""
    records = record_points(monkeypatch)
    error = exception_type('stop')

    def target():
        """Raise the exact control instance."""
        raise error

    with pytest.raises(exception_type) as caught:
        execute(target)
    assert caught.value is error
    assert [phase for phase, _ in records] == ['before']


@pytest.mark.parametrize('allowed', [False, True])
def test_approval_precedes_body_hooks(monkeypatch, allowed):
    """The real approval wrapper denies before Hook Points or forwards in order."""
    records = record_points(monkeypatch)
    action = approval.ApprovalDecision.ALLOW if allowed else approval.ApprovalDecision.DENY

    def decide(self):
        """Observe entry into the actual approval decision seam."""
        assert records == []
        return SimpleNamespace(action=action, rule=None)

    monkeypatch.setattr(approval.ToolApprovalInstance, 'decide', decide)

    def target():
        """Ensure approval has already forwarded to before observation."""
        assert [phase for phase, _ in records] == ['before']
        return 'approved'

    if allowed:
        assert tool.exec_tool_func(target, {}, tool_name='approval_fixture_unique') == 'approved'
        assert [phase for phase, _ in records] == ['before', 'after']
    else:
        with pytest.raises(tool.ToolApprovalDeniedError):
            tool.exec_tool_func(target, {}, tool_name='denial_fixture_unique')
        assert records == []


def test_metadata_fallback_and_non_string_keys():
    """Metadata never stringifies arbitrary objects or exposes value references."""
    records = [build_tool_execute_payload(len, {'z': object(), 2: object()}, None)]
    assert records == [{'tool_name': 'len', 'argument_count': 2, 'argument_keys': ('z',)}]
    records.append(build_tool_execute_payload(object(), None, None))
    assert records[-1] == {'tool_name': None, 'argument_count': None, 'argument_keys': ()}


def test_observation_preparation_failure_is_isolated(caplog):
    """An exotic callable name lookup cannot prevent tool execution."""
    class Callable:
        """Provide a failing metadata accessor."""
        @property
        def __name__(self):
            """Reject introspection without formatting the callable."""
            raise ValueError('name unavailable')
    assert build_tool_execute_payload(Callable(), {}, None) == {
        'tool_name': None, 'argument_count': None, 'argument_keys': (),
    }
    assert 'Tool execution metadata preparation failed' in caplog.text


def test_script_receives_no_payload(tmp_path):
    """A configured Script receives neither argv nor stdin metadata."""
    marker = tmp_path / 'input'
    script = tmp_path / 'plugin.sh'
    script.write_text(f'#!/bin/sh\nprintf "%s:" "$#" > "{marker}"\ncat >> "{marker}"\n')
    script.chmod(0o700)
    hooks.initialize_hook_points({'hook__aibase__before__tool_execute': {'scripts': str(script)}})
    assert execute(lambda: 'original') == 'original'
    assert marker.read_text() == '0:'
