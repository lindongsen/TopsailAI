"""Focused flag-to-real-Hook control checks. Author: DawsonLin."""
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import topsailai.hooks as hooks
from topsailai.ai_base.exception import HardInterruptError
from topsailai.ai_base.llm_control import control_runtime as control
from topsailai.hooks.control_signal import HookControlSignal
from topsailai.utils import env_tool, thread_local_tool
from topsailai.workspace.control_channel.protocol import ControlRequest
from topsailai.workspace.control_handlers.llm_control import LLMControlHandler


@pytest.fixture
def scope(monkeypatch, tmp_path):
    """Isolate markers and Agent identity while retaining real Module loading."""
    agent = SimpleNamespace(_check_hard_interrupt=Mock())
    monkeypatch.setattr(thread_local_tool, 'get_agent_object', lambda: agent)
    monkeypatch.setattr(env_tool, 'get_session_id', lambda: 'test')
    monkeypatch.setattr(control, '_paths', lambda session, pid: (
        tmp_path / f'{session}.{pid}.waiting', tmp_path / f'{session}.{pid}.retry'))
    monkeypatch.setattr(hooks, '_point_configuration', None)
    context = SimpleNamespace(pid=os.getpid(), session_id='test', agent_chat=object())
    return agent, context


def test_receiver_stages_and_real_hook_executes_once(scope):
    """A receipt does not execute retry; the real bundled Module does."""
    agent, context = scope
    handler = LLMControlHandler()
    request = ControlRequest('one', 'llm_control', {'operation': 'force_retry'})
    assert handler.handle(request, context).error == 'not_waiting'
    with control.first_byte_wait_scope():
        assert handler.handle(request, context).result == {'state': 'flag_written'}
        agent._check_hard_interrupt.assert_not_called()
        with pytest.raises(control.LLMRequestedRetryError):
            hooks.hook__llm__before__first_byte_wait_tick()
        hooks.hook__llm__before__first_byte_wait_tick()
        assert not control.consume_retry('test', os.getpid())
    assert not control.stage_retry('test', os.getpid())


def test_generic_interrupt_identity(scope):
    """The existing hard-interrupt action escapes optional Hook isolation."""
    agent, _ = scope
    error = HardInterruptError('stop')
    agent._check_hard_interrupt.side_effect = error
    with control.first_byte_wait_scope():
        with pytest.raises(HardInterruptError) as caught:
            hooks.hook__llm__before__first_byte_wait_tick()
    assert caught.value is error


def test_stale_retry_removed_and_other_session_preserved(scope):
    """Leaving a ready wait never leaves a retry for the next request."""
    _, context = scope
    _, foreign = control._paths('other', context.pid)
    foreign.touch()
    with control.first_byte_wait_scope():
        assert control.stage_retry('test', context.pid)
    with control.first_byte_wait_scope():
        assert not control.consume_retry('test', context.pid)
    assert foreign.exists()


def test_removed_operation_and_target_rejected(scope):
    """Old command and target protocols are not silently reinterpreted."""
    _, context = scope
    handler = LLMControlHandler()
    for payload, expected in [({'operation': 'hard_interrupt'}, 'invalid_operation'),
                              ({'operation': 'status'}, 'invalid_operation'),
                              ({'operation': 'force_retry', 'target': {}}, 'unsupported_target')]:
        assert handler.handle(ControlRequest('id', 'llm_control', payload), context).error == expected


def test_ordinary_plugin_failure_stays_isolated(scope):
    """An ordinary Module failure is reported rather than raised to wait."""
    agent, _ = scope
    agent._check_hard_interrupt.side_effect = ValueError('ordinary failure')
    result = hooks.hook__llm__before__first_byte_wait_tick()
    assert result.handlers[0].status == 'error'


def test_carrier_rejects_other_exceptions():
    """The explicit propagation carrier admits only known control signals."""
    with pytest.raises(TypeError):
        HookControlSignal(ValueError('not control'))


@pytest.mark.parametrize('signal', ['retry', 'interrupt'])
def test_create_wait_control_closes_late_response_once(scope, signal):
    """Blocked SDK work is abandoned, not killed, and its late value closes."""
    import threading
    from tests.unit.test_topsailai_ai_base_llm_control_first_byte_timeout import _FirstByteHost
    from topsailai.ai_base.llm_control.response_ownership import response_ownership_scope

    agent, _ = scope
    entered, release = threading.Event(), threading.Event()
    response = Mock()
    host = _FirstByteHost()

    def provider(params):
        """Hold the provider until the wait has propagated its control signal."""
        entered.set()
        assert release.wait(5)
        return response

    def check():
        """Stage a command only after genuine provider admission."""
        assert entered.wait(3)
        if signal == 'interrupt':
            raise HardInterruptError('generic interrupt')
        control.stage_retry('test', os.getpid())

    host._create_first_byte_response = provider
    agent._check_hard_interrupt.side_effect = check
    expected = HardInterruptError if signal == 'interrupt' else control.LLMRequestedRetryError
    with response_ownership_scope() as owner:
        try:
            with pytest.raises(expected):
                host._create_with_first_byte_timeout([], first_byte_timeout=1)
        finally:
            release.set()
            owner.create_thread.join(3)
    assert not owner.create_thread.is_alive()
    assert host.events.count(('finish', 'ticket')) == 1
    response.close.assert_called_once()


@pytest.mark.parametrize("ready", [False, True])
def test_ready_and_deadline_do_not_execute_pending_control(scope, ready):
    """Terminal readiness wins; otherwise expired budgets win before a tick."""
    import threading
    from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget
    from topsailai.ai_base.llm_control.first_byte_timeout import _wait_for_events
    agent, _ = scope
    event = threading.Event()
    if ready:
        event.set()
    budget = FirstByteBudget(0, 1, clock=lambda: 1)
    assert _wait_for_events((event,), budget) is ready
    agent._check_hard_interrupt.assert_not_called()
    assert not control.stage_retry("test", os.getpid())


def test_marker_cleanup_preserves_primary_and_attempts_both(scope, monkeypatch):
    """A failed deletion cannot replace control flow or skip other markers."""
    original = control._remove
    paths = []
    error = HardInterruptError("primary")

    def remove(path):
        """Fail teardown only, after the wait marker was created."""
        if path.suffix == ".waiting":
            paths.append(path)
            raise PermissionError("blocked cleanup")
        paths.append(path)
        original(path)

    with pytest.raises(HardInterruptError) as caught:
        with control.first_byte_wait_scope():
            control.stage_retry("test", os.getpid())
            monkeypatch.setattr(control, "_remove", remove)
            raise error
    assert caught.value is error
    assert [path.suffix for path in paths] == [".waiting", ".retry"]
    assert not control.consume_retry("test", os.getpid())


def test_requested_retry_preserves_original_eighteen_attempt_budget(monkeypatch):
    """Repeated explicit retry exhausts one chat without replaying Agent work."""
    from unittest.mock import MagicMock
    from topsailai.ai_base.llm_base import LLMModel
    from topsailai.ai_base import llm_base
    from topsailai.ai_base.exception import LLMRetryExhaustedError
    from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
    monkeypatch.setattr(llm_base.LLMModelBase, "__init__", lambda self: None)
    monkeypatch.setattr(llm_base, "time", SimpleNamespace(
        sleep=lambda seconds: None, monotonic=time.monotonic))
    model = LLMModel()
    model.tokenStat = MagicMock()
    model._get_pending_native_tool_call_responses = lambda: []
    error = control.LLMRequestedRetryError("retry")
    model.call_llm_model = Mock(side_effect=error)
    messages = [{"role": "user", "content": "same request"}]
    with pytest.raises(LLMRetryExhaustedError) as caught:
        model.chat(messages, retry_interaction_policy=LLMRetryInteractionPolicy())
    assert caught.value.attempts == 18
    assert caught.value.last_error is error
    assert caught.value.retry_reason == "requested_retry"
    assert model.call_llm_model.call_count == 18
    assert all(item.args[0] is messages for item in model.call_llm_model.call_args_list)


def test_receiver_unavailable_and_write_failure(scope, monkeypatch):
    """Reject foreign ownership and report a failed write without execution."""
    import topsailai.workspace.control_handlers.llm_control as receiver
    _, context = scope
    handler = LLMControlHandler()
    assert handler.action == "llm_control"
    request = ControlRequest("id", "llm_control", {"operation": "force_retry"})
    context.pid = -1
    assert handler.handle(request, context).error == "unavailable"
    context.pid = os.getpid()
    monkeypatch.setattr(receiver, "stage_retry", Mock(side_effect=OSError("write failed")))
    assert handler.handle(request, context).error == "flag_write_failed"


def test_absent_agent(scope, monkeypatch):
    """No-Agent waits neither create markers nor execute control actions."""
    monkeypatch.setattr(thread_local_tool, "get_agent_object", lambda: None)
    with control.first_byte_wait_scope():
        pass
    hooks.hook__llm__before__first_byte_wait_tick()


def test_default_marker_paths(monkeypatch, tmp_path):
    """Production marker paths share the folder but isolate session and PID."""
    from topsailai.workspace import folder_constants
    monkeypatch.setattr(folder_constants, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    waiting, retry = control._paths("session-one", 123)
    assert waiting.parent == retry.parent == tmp_path
    assert waiting.suffix == ".fbt_waiting"
    assert retry.suffix == ".fbt_retry"
    assert control._paths("session-two", 123) != (waiting, retry)
    assert control._paths("session-one", 124) != (waiting, retry)


@pytest.mark.parametrize("both", [False, True])
def test_normal_exit_reports_marker_cleanup_failure(scope, monkeypatch, both):
    """Cleanup attempts both markers and raises the first error on normal exit."""
    original = control._remove
    calls = []
    error = PermissionError("cleanup denied")

    def remove(path):
        """Inject failure only after scope entry has completed."""
        calls.append(path)
        if both or path.suffix == ".waiting":
            raise error
        original(path)

    with pytest.raises(PermissionError) as caught:
        with control.first_byte_wait_scope():
            monkeypatch.setattr(control, "_remove", remove)
    assert caught.value is error
    assert len(calls) == 2


@pytest.mark.parametrize("signal_type", [HardInterruptError, control.LLMRequestedRetryError])
def test_control_signal_after_ticket_admission_publishes_and_finishes_once(scope, monkeypatch, signal_type):
    """A Hook interruption after ticket creation preserves its exact custody."""
    import threading
    from topsailai.ai_base.llm_control import first_byte_timeout as timeout_module
    from tests.unit.test_topsailai_ai_base_llm_control_first_byte_timeout import _FirstByteHost
    from topsailai.ai_base.llm_control.response_ownership import response_ownership_scope

    entered, release = threading.Event(), threading.Event()
    response = Mock()
    host = _FirstByteHost()
    error = signal_type("wait interrupted")

    def provider(params):
        """Keep the response worker alive until coordinator cleanup is asserted."""
        entered.set()
        assert release.wait(5)
        return response

    def hook_tick():
        """Interrupt only after the worker has allocated its timing ticket."""
        assert entered.wait(3)
        raise error

    monkeypatch.setattr(timeout_module, "hook__llm__before__first_byte_wait_tick", hook_tick)
    host._create_first_byte_response = provider
    with response_ownership_scope() as owner:
        try:
            with pytest.raises(signal_type) as caught:
                host._create_with_first_byte_timeout([], first_byte_timeout=1)
            assert caught.value is error
            assert owner.primary_error is error
            assert owner.take_outcome().kind == "ABANDONED"
            publications = [event for event in host.events if event[0] == "publish"]
            assert publications
            assert all(event == ("publish", "ticket", threading.get_ident())
                       for event in publications)
            assert host.events.count(("finish", "ticket")) == 1
            assert not any(event[0] == "complete" for event in host.events)
            response.close.assert_not_called()
        finally:
            release.set()
            owner.create_thread.join(3)
    assert not owner.create_thread.is_alive()
    assert owner.create_finished_event.is_set()
    assert owner.take_outcome().kind == "ABANDONED"
    assert host.events.count(("finish", "ticket")) == 1
    response.close.assert_called_once()
