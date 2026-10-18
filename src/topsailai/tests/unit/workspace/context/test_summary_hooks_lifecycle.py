"""U5 explicit summary lifecycle checkpoint regressions.

Author: DawsonLin
"""

import asyncio
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from topsailai.ai_base.exception import HardInterruptError, HeavyTaskError, LLMBackToChatError
from topsailai.ai_base.llm_control.exception import (
    LLMProviderError, LLMProviderTimeoutError, LLMProviderConnectionError, LLMProviderReadError,
)
from topsailai.hooks.contracts import DispatchReport
from topsailai.hooks.points.context.summary_adapter import (
    DirectSummaryOperation, _CHECKPOINTS, current_summary_operation, summary_operation,
)
from topsailai.workspace.context import base, ctx_runtime, agent2llm
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData

_DIRECT_ENTRIES = {point.NAME: getattr(point, point.NAME)
                   for points in _CHECKPOINTS.values() for point in points.values()}


class Executor:
    """Observe metadata-only dispatch with optional observer failure injection."""

    def __init__(self, timeline, failure=None):
        """Keep all state local to one summary test."""
        self.timeline = timeline
        self.failure = failure
        self.calls = []

    def dispatch(self, point, *, payload, operation):
        """Record each checkpoint before simulating a report-type failure."""
        self.calls.append((point.name, payload, operation.operation_id))
        self.timeline.append(point.name.split('__')[2])
        if self.failure:
            raise self.failure
        return DispatchReport('event', 0, rejection_reason='observer_rejected')


@pytest.fixture
def setup_runtime(monkeypatch):
    """Build real layer methods with deterministic generation and feasibility seams."""
    timeline = []
    executor = Executor(timeline)
    runtime = ContextRuntimeData()
    for points in _CHECKPOINTS.values():
        for selected in points.values():
            def direct(*, operation_id, _selected=selected, **classification):
                """Observe the actual direct point lookup, retaining real payload checks."""
                payload = _selected.build_payload(operation_id=operation_id, **classification)
                return executor.dispatch(_selected.POINT, payload=payload,
                    operation=SimpleNamespace(operation_id=operation_id))
            monkeypatch.setattr(selected, selected.NAME, direct)
    runtime.messages = [
        {'role': 'user', 'content': 'task'},
        {'role': 'assistant', 'content': 'middle'},
        {'role': 'user', 'content': 'last'},
    ]
    runtime.ai_agent = SimpleNamespace(
        messages=list(runtime.messages),
        get_work_memory_first_position=lambda: 0,
        available_tools={},
        runtime=SimpleNamespace(token_stat=SimpleNamespace(add_msgs=Mock(
            side_effect=lambda *args, **kwargs: timeline.append('tokens')))),
    )
    monkeypatch.setattr(runtime, '_get_summary_head_messages', lambda messages: [])
    monkeypatch.setattr(runtime, '_get_head_offset_to_keep_in_summary', lambda offset: 0)
    monkeypatch.setattr(runtime, '_get_tail_offset_to_keep_in_summary', lambda: 0)
    monkeypatch.setattr(runtime, '_get_current_tokens', lambda *args, **kwargs: 10)
    monkeypatch.setattr(runtime, '_can_summarize_user2agent_messages', lambda *args, **kwargs: (True, 100))
    monkeypatch.setattr(runtime, '_can_summarize_agent2llm_messages', lambda *args, **kwargs: (True, 100))
    monkeypatch.setattr(runtime, '_log_summarize_message_identity_changes', lambda *args: None)
    monkeypatch.setattr(runtime, '_check_summarize_token_reduction', lambda *args: timeline.append('checked'))
    monkeypatch.setattr(runtime, '_get_summary_prompt', lambda **kwargs: 'summary prompt')
    reader = SimpleNamespace(get=lambda name, *args, **kwargs: 'message' if name == 'TOPSAILAI_CONTEXT_SUMMARY_MODE' else None,
                             check_bool=lambda *args, **kwargs: False)
    monkeypatch.setattr(base.env_tool, 'EnvReaderInstance', reader)
    monkeypatch.setattr(base.env_tool, 'is_interactive_mode', lambda: False)
    monkeypatch.setattr(base.env_tool, 'is_use_tool_calls', lambda: False)
    chat = SimpleNamespace(prompt_ctl=SimpleNamespace(messages=[]), llm_model=SimpleNamespace())

    def build_chat(**kwargs):
        """Make chat/model selection observable before the before checkpoint."""
        timeline.append('build')
        return chat

    def generate(*args, **kwargs):
        """Return one summary answer through the real shared generation seam."""
        timeline.append('request')
        chat.prompt_ctl.messages.append({'role': 'assistant', 'content': 'summary'})
        return 'summary'

    monkeypatch.setattr(runtime, '_build_summary_chat', build_chat)
    monkeypatch.setattr(runtime, '_chat_for_summary', generate)
    return runtime, executor, timeline, chat, reader


def summarize(runtime, layer, **kwargs):
    """Use the public layer entry rather than bypassing checkpoint plumbing."""
    if layer == 'user2agent':
        return runtime.summarize_messages_for_processed(force=True, **kwargs)
    return runtime.summarize_messages_for_processing(force=True, **kwargs)


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('mode', ['message', 'runtime'])
def test_success_order_routing_and_one_operation(setup_runtime, layer, mode):
    """BG precedes request and AA follows all application accounting in either mode."""
    runtime, executor, timeline, _, reader = setup_runtime
    reader.get = lambda name, *args, **kwargs: mode if name == 'TOPSAILAI_CONTEXT_SUMMARY_MODE' else None
    assert summarize(runtime, layer) == 'summary'
    assert timeline.index('build') < timeline.index('before') < timeline.index('request')
    assert timeline.index('checked') < timeline.index('after')
    assert [call[0] for call in executor.calls] == [
        f'hook__context__before__summary_generate_{layer}',
        f'hook__context__after__summary_apply_{layer}',
    ]
    assert len({call[2] for call in executor.calls}) == 1
    assert all('content' not in call[1] and 'layer' not in call[1] for call in executor.calls)
    if layer == 'agent2llm':
        assert timeline.index('tokens') < timeline.index('after')


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
def test_default_activation_without_executor(setup_runtime, layer):
    """Summary reaches direct entries without an injected owner or executor."""
    runtime, executor, _, _, _ = setup_runtime
    assert not hasattr(runtime, 'summary_hooks_executor')
    assert summarize(runtime, layer) == 'summary'
    assert len(executor.calls) == 2
    assert current_summary_operation() is None


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('kind', ['empty_input', 'feasibility', 'empty_answer'])
def test_skips_never_emit_success_or_error(setup_runtime, monkeypatch, layer, kind):
    """An attempted empty generation has BG only; preflight skips have no events."""
    runtime, executor, _, _, _ = setup_runtime
    if kind == 'empty_input':
        runtime.messages = []
        runtime.ai_agent.messages = []
    elif kind == 'feasibility':
        method = '_can_summarize_user2agent_messages' if layer == 'user2agent' else '_can_summarize_agent2llm_messages'
        monkeypatch.setattr(runtime, method, lambda *args, **kwargs: (False, 100))
    else:
        monkeypatch.setattr(runtime, '_chat_for_summary', lambda *args, **kwargs: '')
    assert summarize(runtime, layer) is None
    assert len(executor.calls) == (1 if kind == 'empty_answer' else 0)
    assert all('__before__' in call[0] for call in executor.calls)


def test_human_rejection_generated_is_not_applied(setup_runtime, monkeypatch):
    """Human rejection retains input and notifies neither success nor error."""
    runtime, executor, _, _, _ = setup_runtime
    original = list(runtime.messages)
    monkeypatch.setattr(ctx_runtime, 'input_yes', lambda *args: False)
    assert summarize(runtime, 'user2agent', need_interactive=True) == 'summary'
    assert runtime.messages == original
    assert len(executor.calls) == 1


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('error,category', [
    (RuntimeError('secret'), 'unknown'), (TimeoutError(), 'timeout'),
    (LLMProviderTimeoutError(), 'timeout'), (LLMProviderConnectionError(), 'transport'),
    (ConnectionError(), 'transport'), (LLMProviderReadError(), 'transport'),
    (LLMProviderError(), 'provider'),
])
@pytest.mark.parametrize('mode', ['message', 'runtime'])
def test_generation_primary_exception_preserved(setup_runtime, monkeypatch, layer, error, category, mode):
    """Only request business errors yield EG; exact exception and source frame survive."""
    runtime, executor, _, _, reader = setup_runtime
    reader.get = lambda name, *args, **kwargs: mode if name == 'TOPSAILAI_CONTEXT_SUMMARY_MODE' else None

    def fail(*args, **kwargs):
        """Raise the exact business exception inside the generation request."""
        raise error

    monkeypatch.setattr(runtime, '_chat_for_summary', fail)
    with pytest.raises(type(error)) as caught:
        summarize(runtime, layer)
    assert caught.value is error
    frames = []
    tb = caught.value.__traceback__
    while tb:
        frames.append(tb.tb_frame.f_code.co_name)
        tb = tb.tb_next
    assert 'fail' in frames
    assert executor.calls[-1][0] == f'hook__context__error__summary_generate_{layer}'
    assert executor.calls[-1][1]['error_category'] == category
    assert executor.calls[-1][1]['failed_stage'] == 'generation_request'
    assert len(executor.calls) == 2
    assert 'secret' not in str(executor.calls)


@pytest.mark.parametrize('stage', ['session_write', 'history_delete', 'session_reload', 'memory_update'])
def test_user_application_failures(setup_runtime, monkeypatch, stage):
    """Every mutable User2Agent boundary emits one truthful EA, never AA."""
    runtime, executor, timeline, _, _ = setup_runtime
    error = RuntimeError('business persistence failure')

    def fail(*args, **kwargs):
        """Inject one failure at the selected real application action."""
        raise error

    if stage == 'memory_update':
        monkeypatch.setattr(runtime, 'set_messages', fail)
    else:
        runtime.session_id = 'session'
        records = [SimpleNamespace(message=message, msg_id=str(index)) for index, message in enumerate(runtime.messages)]
        monkeypatch.setattr(ctx_runtime.ctx_manager, 'get_messages_by_session', lambda *args, **kwargs: records)
        monkeypatch.setattr(ctx_runtime.ctx_manager, 'add_session_message', fail if stage == 'session_write' else lambda *args: timeline.append('write'))
        monkeypatch.setattr(ctx_runtime.ctx_manager, 'del_session_messages', fail if stage == 'history_delete' else lambda *args: timeline.append('delete'))
        monkeypatch.setattr(runtime, 'reset_messages', fail if stage == 'session_reload' else lambda: timeline.append('reload'))
    with pytest.raises(RuntimeError) as caught:
        summarize(runtime, 'user2agent', messages=list(runtime.messages))
    assert caught.value is error
    payload = executor.calls[-1][1]
    assert payload['failed_stage'] == stage
    assert payload['partial_apply_possible'] is True
    assert payload['error_category'] == ('state_update' if stage in ('session_reload', 'memory_update') else 'persistence')
    assert len(executor.calls) == 2
    assert '__error__summary_apply_user2agent' in executor.calls[-1][0]


@pytest.mark.parametrize('stage,partial', [('runtime_rebuild', True), ('tool_pairing', False), ('token_stat_update', True)])
def test_agent_application_failures(setup_runtime, monkeypatch, stage, partial):
    """Agent rebuild/pairing/token failures distinguish mutation entry honestly."""
    runtime, executor, _, _, _ = setup_runtime
    error = RuntimeError('business state failure')

    def fail(*args, **kwargs):
        """Inject failure at a selected existing Agent2LLM application seam."""
        raise error

    if stage == 'token_stat_update':
        runtime.ai_agent.runtime.token_stat.add_msgs = fail
    elif stage == 'tool_pairing':
        monkeypatch.setattr(runtime, '_get_tail_offset_to_keep_in_summary', lambda: 1)
        monkeypatch.setattr(agent2llm.message_tool, 'expand_tail_start_for_tool_pairing', fail)
    else:
        class RejectAssignment:
            """Retain agent state but reject the runtime publication assignment."""

            def __init__(self, agent):
                """Copy the fixture without invoking the rejection setter."""
                self.__dict__.update(vars(agent))

            def __setattr__(self, name, value):
                """Reject only mutable runtime-message publication."""
                if name == 'messages':
                    raise error
                object.__setattr__(self, name, value)

        runtime.ai_agent = RejectAssignment(runtime.ai_agent)
    with pytest.raises(RuntimeError) as caught:
        summarize(runtime, 'agent2llm')
    assert caught.value is error
    payload = executor.calls[-1][1]
    assert payload['failed_stage'] == stage
    assert payload['partial_apply_possible'] is partial
    assert '__error__summary_apply_agent2llm' in executor.calls[-1][0]
    assert len(executor.calls) == 2


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('business_failure', [False, True])
def test_observer_failures_never_recurse_or_replace_primary(setup_runtime, monkeypatch, layer, business_failure):
    """Raised observer failures and rejection reports remain observation-only."""
    runtime, executor, _, _, _ = setup_runtime
    executor.failure = RuntimeError('observer secret')
    if business_failure:
        error = ValueError('business error')

        def fail(*args, **kwargs):
            """Retain a primary business error while its error observer also fails."""
            raise error

        monkeypatch.setattr(runtime, '_chat_for_summary', fail)
        with pytest.raises(ValueError) as caught:
            summarize(runtime, layer)
        assert caught.value is error
    else:
        assert summarize(runtime, layer) == 'summary'
    assert len(executor.calls) == 2
    assert ('__error__' in executor.calls[-1][0]) is business_failure


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('error', [KeyboardInterrupt(), SystemExit(), asyncio.CancelledError(),
                                  CancelledError(), HardInterruptError(), HeavyTaskError(),
                                  LLMBackToChatError(attempts=1)])
@pytest.mark.parametrize('boundary', ['generation', 'application', 'observer'])
def test_control_signals_propagate_without_error_points(setup_runtime, monkeypatch, layer, error, boundary):
    """Interrupts and host control decisions retain identity at every boundary."""
    runtime, executor, _, _, _ = setup_runtime

    def fail(*args, **kwargs):
        """Raise the exact host signal rather than a business exception."""
        raise error

    if boundary == 'generation':
        monkeypatch.setattr(runtime, '_chat_for_summary', fail)
    elif boundary == 'observer':
        executor.failure = error
    elif layer == 'user2agent':
        monkeypatch.setattr(runtime, 'set_messages', fail)
    else:
        runtime.ai_agent.runtime.token_stat.add_msgs = fail
    with pytest.raises(type(error)) as caught:
        summarize(runtime, layer)
    assert caught.value is error
    assert len(executor.calls) == 1
    assert '__before__' in executor.calls[0][0]


def test_direct_idempotency_in_same_operation(setup_runtime):
    """At-most-once marking prevents observer re-execution within a summary."""
    _, executor, _, _, _ = setup_runtime
    operation = DirectSummaryOperation('user2agent')
    result = operation.emit('before_summary_generate')
    assert isinstance(result, DispatchReport)
    assert result.rejection_reason == 'observer_rejected'
    assert operation.emit('before_summary_generate').already_handled
    assert len(executor.calls) == 1


def test_session_success_waits_for_reload_and_accounting(setup_runtime, monkeypatch):
    """Persistent acceptance is reported only after write/delete/reload/check."""
    runtime, executor, timeline, _, _ = setup_runtime
    runtime.session_id = 'session'
    records = [SimpleNamespace(message=message, msg_id=str(index)) for index, message in enumerate(runtime.messages)]
    monkeypatch.setattr(ctx_runtime.ctx_manager, 'get_messages_by_session', lambda *args, **kwargs: records)
    monkeypatch.setattr(ctx_runtime.ctx_manager, 'add_session_message', lambda *args: timeline.append('write'))
    monkeypatch.setattr(ctx_runtime.ctx_manager, 'del_session_messages', lambda *args: timeline.append('delete'))
    monkeypatch.setattr(runtime, 'reset_messages', lambda: timeline.append('reload'))
    assert summarize(runtime, 'user2agent', messages=list(runtime.messages)) == 'summary'
    assert timeline.index('write') < timeline.index('delete') < timeline.index('reload') < timeline.index('checked') < timeline.index('after')
    assert len(executor.calls) == 2


def test_agent_too_short_and_missing_work_memory_are_skips(setup_runtime):
    """Automatic too-short and absent-work-memory guards construct no operation."""
    runtime, executor, _, _, _ = setup_runtime
    runtime.ai_agent.messages = runtime.ai_agent.messages[:1]
    assert runtime.summarize_messages_for_processing() is None
    runtime.ai_agent.get_work_memory_first_position = lambda: None
    assert runtime.summarize_messages_for_processing(force=True) is None
    assert executor.calls == []


@pytest.mark.parametrize('error', [HardInterruptError(), CancelledError(), HeavyTaskError(),
                                  LLMBackToChatError(attempts=1), KeyboardInterrupt(), SystemExit()])
def test_human_confirmation_control_signal_is_not_rejection(setup_runtime, monkeypatch, error):
    """A host interruption during human confirmation must not become a skip return."""
    runtime, executor, _, _, _ = setup_runtime

    def interrupt(*args):
        """Interrupt confirmation before any application can begin."""
        raise error

    monkeypatch.setattr(ctx_runtime, 'input_yes', interrupt)
    with pytest.raises(type(error)) as caught:
        summarize(runtime, 'user2agent', need_interactive=True)
    assert caught.value is error
    assert len(executor.calls) == 1


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
def test_post_application_check_failure_is_not_success(setup_runtime, monkeypatch, layer):
    """A failure after mutation remains partial application rather than fake AA."""
    runtime, executor, _, _, _ = setup_runtime
    error = RuntimeError('accounting failed')

    def fail(*args):
        """Fail the original final accounting/check boundary."""
        raise error

    monkeypatch.setattr(runtime, '_check_summarize_token_reduction', fail)
    with pytest.raises(RuntimeError) as caught:
        summarize(runtime, layer)
    assert caught.value is error
    assert executor.calls[-1][1]['partial_apply_possible'] is True
    assert '__error__summary_apply_' in executor.calls[-1][0]


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
def test_injected_summary_preserves_atomic_tool_tail(setup_runtime, monkeypatch, layer):
    """Injected execution leaves existing assistant/tool tail reconstruction intact."""
    runtime, executor, _, _, _ = setup_runtime
    assistant = {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'call-1', 'type': 'function', 'function': {'name': 'tool', 'arguments': '{}'}}]}
    tool = {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'result'}
    messages = [{'role': 'user', 'content': 'task'}, assistant, tool]
    runtime.messages = list(messages)
    runtime.ai_agent.messages = list(messages)
    monkeypatch.setattr(runtime, '_get_tail_offset_to_keep_in_summary', lambda: 1)
    assert summarize(runtime, layer) == 'summary'
    applied = runtime.messages if layer == 'user2agent' else runtime.ai_agent.messages
    assert assistant in applied and tool in applied
    assert applied.index(assistant) < applied.index(tool)
    assert len(executor.calls) == 2


def test_pre_mutation_failure_is_explicitly_nonpartial(setup_runtime, monkeypatch):
    """A failed read before persistent mutation must not fabricate partial effects."""
    runtime, executor, _, _, _ = setup_runtime
    runtime.session_id = 'session'
    error = OSError('read failed')

    def fail(*args, **kwargs):
        """Fail the read used to construct persistent application bookkeeping."""
        raise error

    monkeypatch.setattr(ctx_runtime.ctx_manager, 'get_messages_by_session', fail)
    with pytest.raises(OSError) as caught:
        summarize(runtime, 'user2agent', messages=list(runtime.messages))
    assert caught.value is error
    assert executor.calls[-1][1]['partial_apply_possible'] is False


def test_each_new_summary_owns_a_new_operation(setup_runtime):
    """Operation custody stays call-local rather than leaking into session state."""
    runtime, executor, _, _, _ = setup_runtime
    assert summarize(runtime, 'user2agent') == 'summary'
    assert summarize(runtime, 'user2agent') == 'summary'
    assert executor.calls[0][2] != executor.calls[2][2]


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
def test_same_operation_checkpoint_retry_is_not_redispatched(setup_runtime, monkeypatch, layer):
    """A duplicate generation checkpoint in one operation dispatches only once."""
    runtime, executor, _, _, _ = setup_runtime
    original = runtime._chat_for_summary

    def generate(*args, **kwargs):
        """Revisit an already consumed checkpoint during the real generation call."""
        assert current_summary_operation().emit('before_summary_generate').already_handled
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, '_chat_for_summary', generate)
    assert summarize(runtime, layer) == 'summary'
    assert len(executor.calls) == 2


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('mode', ['message', 'runtime'])
@pytest.mark.parametrize('outcome', ['success', 'generation_error', 'application_error'])
def test_business_wiring_reaches_real_workers(setup_runtime, monkeypatch, layer, mode, outcome):
    """Run actual bundled observer children from real business checkpoints."""
    import os
    import topsailai.hooks as hooks
    from topsailai.hooks.point_entry import pending_cleanup

    if os.name != 'posix':
        pytest.skip('Generic direct entry requires POSIX process containment')
    runtime, executor, _, _, reader = setup_runtime
    reader.get = lambda name, *args, **kwargs: mode if name == 'TOPSAILAI_CONTEXT_SUMMARY_MODE' else None
    for points in _CHECKPOINTS.values():
        for point in points.values():
            monkeypatch.setattr(point, point.NAME, _DIRECT_ENTRIES[point.NAME])
    monkeypatch.setattr(hooks, '_point_configuration', ())
    invoke = hooks.invoke_hook_point
    reports = []

    def record(name, **payload):
        """Observe real worker outcomes without replacing subprocess execution."""
        result = invoke(name, **payload)
        reports.append((name, payload, result))
        return result

    def fail(*args, **kwargs):
        """Raise an exact business exception at the requested stage."""
        raise primary

    primary = ValueError('business failure')
    monkeypatch.setattr(hooks, 'invoke_hook_point', record)
    if outcome == 'generation_error':
        monkeypatch.setattr(runtime, '_chat_for_summary', fail)
    elif outcome == 'application_error':
        if layer == 'user2agent':
            monkeypatch.setattr(runtime, 'set_messages', fail)
        else:
            runtime.ai_agent.runtime.token_stat.add_msgs = fail
    if outcome == 'success':
        assert summarize(runtime, layer) == 'summary'
    else:
        with pytest.raises(ValueError) as caught:
            summarize(runtime, layer)
        assert caught.value is primary
    terminal = {'success': 'after__summary_apply', 'generation_error': 'error__summary_generate',
                'application_error': 'error__summary_apply'}[outcome]
    assert [item[0] for item in reports] == [
        f'hook__context__before__summary_generate_{layer}', f'hook__context__{terminal}_{layer}']
    assert len({item[1]['hook_context']['operation_id'] for item in reports}) == 1
    assert all([(result.handler.kind, result.handler.name, result.status)
                for result in item[2].handlers[:-1]] ==
               [('module', 'observer.py', 'success')] for item in reports)
    assert all(item[2].status == 'success' and
               item[2].handlers[-1].handler.name == 'hook_script' and
               item[2].handlers[-1].children == () for item in reports)
    assert executor.calls == []
    assert current_summary_operation() is None
    assert pending_cleanup() == ()
