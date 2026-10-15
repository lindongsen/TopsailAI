"""Approved complete-message before boundary regressions.

Author: DawsonLin
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from topsailai.hooks.configured_executor import ConfiguredHookExecutor
from topsailai.hooks.configured_registration import RegistrationEnsureResult, RegistrationState
from topsailai.hooks.contracts import DispatchReport, HookOutcome, HookStatus, ValidationError
from topsailai.hooks.points.workspace.before_input_message import NAME, POINT
from topsailai.hooks.points.workspace.catalog import INPUT_CATALOG, create_input_catalog
from topsailai.hooks.validation import validate_payload
from topsailai.workspace import input_tool


@pytest.fixture
def prepared(monkeypatch):
    """Keep input history out of the host and resolve mode explicitly."""
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", Mock(return_value=False))
    prepared = Mock(dispatch=Mock(return_value=DispatchReport("input", 1)))
    monkeypatch.setattr(
        "topsailai.hooks.points.workspace.input_adapter.get_hook_executor",
        lambda: prepared,
    )
    return prepared


@pytest.mark.parametrize('multiline', [False, True])
def test_resolved_mode_once_before_reader(prepared, monkeypatch, multiline):
    """Dispatch only once, after mode resolution and before the selected reader."""
    trace = []
    mode = Mock(side_effect=lambda: trace.append('mode') or multiline)
    monkeypatch.setattr(input_tool.env_tool, 'is_chat_multi_line', mode)
    prepared.dispatch.side_effect = lambda *a, **k: trace.append('hook') or DispatchReport('x', 1)
    reader = Mock(side_effect=lambda *a: trace.append('read') or 'original')
    monkeypatch.setattr(input_tool, 'input_multi_line' if multiline else 'input_one_line', reader)
    assert input_tool.input_message('private prompt') == 'original'
    assert trace == ['mode', 'hook', 'read']
    assert prepared.dispatch.call_args.kwargs['payload'] == {'multiline': multiline}
    prepared.dispatch.assert_called_once()
    reader.assert_called_once_with('private prompt', None)


@pytest.mark.parametrize('multiline,lines', [
    (False, ['', '/help', 'message']),
    (True, ['EOF', '/help', 'first', 'second', 'EOF']),
])
def test_retries_help_and_continuations_do_not_redispatch(prepared, monkeypatch, multiline, lines):
    """Real reader loops and multiline recursion retain one outer occurrence."""
    monkeypatch.setattr(input_tool.env_tool, 'is_chat_multi_line', lambda: multiline)
    values = iter(lines)
    def read(*args):
        """Require dispatch before every subsequent read and command interception."""
        assert prepared.dispatch.call_count == 1
        return next(values)
    monkeypatch.setattr(input_tool, '_input', read)
    instruction = Mock()
    instruction.exist_hook.side_effect = lambda message: message.strip() == '/help'
    result = input_tool.input_message(hook=instruction)
    assert result == ('first\nsecond' if multiline else 'message')
    prepared.dispatch.assert_called_once()
    instruction.call_hook.assert_called_once_with('/help')


@pytest.mark.parametrize('command', ['exit', 'quit', '/exit', '/quit'])
def test_exit_after_hook_preserves_system_exit(prepared, monkeypatch, command):
    """Exit interception occurs after dispatch without changing termination."""
    def read(*args):
        """Verify observer precedes acquisition of an exit token."""
        prepared.dispatch.assert_called_once()
        return command
    monkeypatch.setattr(input_tool, '_input', read)
    with pytest.raises(SystemExit):
        input_tool.input_message()


def test_direct_read_and_confirmation_are_excluded(prepared, monkeypatch):
    """Direct and yes/no readers never acquire input-message Hook authority."""
    monkeypatch.setattr(input_tool, '_input', Mock(side_effect=['direct', 'yes']))
    assert input_tool.input_one_line() == 'direct'
    assert input_tool.input_yes() is True
    prepared.dispatch.assert_not_called()


@pytest.mark.parametrize('report', [
    DispatchReport('x', 1, rejection_reason='capacity'),
    DispatchReport('x', 1, deadline_exhausted=True),
    DispatchReport('x', 1, outcomes=(HookOutcome('delivery', 'module', HookStatus.ERROR),)),
    DispatchReport('x', 1, outcomes=(HookOutcome('delivery', 'module', HookStatus.TIMEOUT),)),
    False, None, {'error': 1},
])
def test_failure_report_preserves_input(prepared, monkeypatch, caplog, report):
    """Report rejection, timeout and malformed responses cannot rewrite input."""
    prepared.dispatch.return_value = report
    monkeypatch.setattr(input_tool, '_input', lambda *a: 'original')
    assert input_tool.input_message() == 'original'
    assert 'Input before Hook' in caplog.text


def test_ordinary_dispatch_exception_is_safe(prepared, monkeypatch, caplog):
    """Unexpected ordinary facade failures log only safe context and continue."""
    prepared.dispatch.side_effect = RuntimeError('secret sentinel')
    monkeypatch.setattr(input_tool, '_input', lambda *a: 'original')
    assert input_tool.input_message() == 'original'
    assert 'dispatch failed' in caplog.text
    assert 'secret sentinel' not in caplog.text


@pytest.mark.parametrize('error', [KeyboardInterrupt(), SystemExit(), asyncio.CancelledError()])
def test_host_interrupt_does_not_prompt_quit(prepared, monkeypatch, error):
    """Host interruption retains identity outside the input-only handler."""
    prepared.dispatch.side_effect = error
    confirmation = Mock()
    reader = Mock()
    monkeypatch.setattr(input_tool, 'input_yes', confirmation)
    monkeypatch.setattr(input_tool, 'input_one_line', reader)
    with pytest.raises(type(error)) as caught:
        input_tool.input_message()
    assert caught.value is error
    confirmation.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("answer", [False, True])
def test_read_interrupt_keeps_legacy_confirmation(prepared, monkeypatch, answer):
    """Only an interruption during input uses the existing confirmation."""
    monkeypatch.setattr(input_tool, "input_one_line", Mock(side_effect=KeyboardInterrupt))
    confirmation = Mock(return_value=answer)
    monkeypatch.setattr(input_tool, "input_yes", confirmation)
    if answer:
        with pytest.raises(Exception, match="User Quit"):
            input_tool.input_message()
    else:
        assert input_tool.input_message() == ""
    confirmation.assert_called_once_with("Quit Your Turn? [yes/no] ")
    prepared.dispatch.assert_called_once()


def test_absent_executor_and_noop(prepared, monkeypatch):
    """Default callers remain unchanged, including empty noop results."""
    monkeypatch.setattr(input_tool, "_input", lambda *a: "/noop")
    assert input_tool.input_message() == ""
    assert input_tool.input_message() == ""
    assert prepared.dispatch.call_count == 2


def test_payload_mutation_cannot_change_mode_or_future_calls(prepared, monkeypatch):
    """A detached scalar payload cannot redirect the chosen input reader."""
    operations = []
    def dispatch(point, *, payload, operation):
        """Mutate the worker-bound copy rather than input-layer state."""
        assert payload == {'multiline': False}
        payload['multiline'] = True
        operations.append(operation.operation_id)
        return DispatchReport('x', 1)
    prepared.dispatch.side_effect = dispatch
    monkeypatch.setattr(input_tool, '_input', lambda *a: 'message')
    for _ in range(2):
        assert input_tool.input_message() == 'message'
    assert len(set(operations)) == 2
    prepared.register.assert_not_called()
    prepared.ensure_registered.assert_not_called()


@pytest.mark.parametrize('payload', [{}, {'multiline': None}, {'multiline': 1},
                                     {'multiline': False, 'prompt': 'secret'}])
def test_payload_schema_rejects_extra_or_invalid_fields(payload):
    """The exact metadata-only schema denies input content and lookalike booleans."""
    with pytest.raises(ValidationError):
        validate_payload(POINT.definition, payload)

def test_removed_executor_keyword_is_rejected():
    """The temporary explicit Executor injection seam is removed."""
    with pytest.raises(TypeError, match="hook_executor"):
        input_tool.input_message(hook_executor=Mock())



def test_catalog_and_real_executor(monkeypatch):
    """A real facade accepts the static Catalog without input-side registration."""
    from topsailai.hooks.application_access import HookApplicationAccess, bind_hook_application

    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", Mock(return_value=False))
    assert POINT.name == POINT.definition.name == NAME
    assert (POINT.phase, POINT.mode, POINT.failure_policy) == ("before", "sync", "report")
    assert len(INPUT_CATALOG.declarations) == len(create_input_catalog().declarations) == 1
    runtime = Mock()
    runtime.make_event.return_value = SimpleNamespace(event_id="x")
    runtime.dispatch_configured.return_value = DispatchReport("x", 1)
    registrar = Mock()
    registrar.ensure_registered.return_value = RegistrationEnsureResult(RegistrationState.READY)
    executor = ConfiguredHookExecutor(
        runtime, SimpleNamespace(scope_id="input", closed=False), registrar, INPUT_CATALOG
    )
    monkeypatch.setattr(input_tool, "_input", lambda *a: "message")
    with bind_hook_application(HookApplicationAccess(executor)):
        assert input_tool.input_message() == "message"
    registrar.ensure_registered.assert_called_once_with(NAME)
    runtime.dispatch_configured.assert_called_once_with(NAME, runtime.make_event.return_value)
    assert runtime.make_event.call_args.args[3] == {"multiline": False}
    runtime.register_configured.assert_not_called()
