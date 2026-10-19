"""Settlement Hook and host lifecycle evidence. Author: DawsonLin."""

import os
import json
import threading
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.exception import HardInterruptError, LLMBackToChatError
from topsailai.ai_base.llm_control.control_runtime import LLMControlledInterruptError
from topsailai.hooks.points.workspace.after_attempt_settle_user2agent import (
    hook__workspace__after__attempt_settle_user2agent,
)
from topsailai.hooks.points.workspace.after_attempt_settle_user2agent.modules import session_stats
from topsailai.utils.thread_local_tool import ctxm_set_agent
from topsailai.workspace.session_stats_projection import capture
from topsailai.workspace.session_stats_service import Binding, StatsService
from tests.unit.test_topsailai_workspace_agent_agent_shell_base_llm_retry import (
    agent_chat, _run_patches,
)
from tests.unit.workspace.test_session_stats_service import agent, wait_for

HOST = "topsailai.workspace.agent.agent_shell_base."


def test_capture_uses_binding_even_with_unrelated_thread_local():
    """A returned Agent run need not leave its thread-local installed."""
    owner, unrelated = agent(), agent()
    binding = Binding(MagicMock(), owner, "example", None, True)
    with ctxm_set_agent(unrelated):
        record = capture(binding, session_id="example", writer_id="a" * 32,
                         agent_id="b" * 32, sequence=1, outcome="success")
    assert record["sources"]["tool_stat"] == owner.runtime.tool_stat._id
    assert record["sources"]["tool_stat"] != unrelated.runtime.tool_stat._id


def test_module_missing_unauthorized_and_failure():
    """Missing bindings, refused ownership and ordinary failures are tolerated."""
    chat = SimpleNamespace(ai_agent=object())
    assert session_stats.main(agent_chat=chat, outcome="success") is False
    attempt = MagicMock()
    attempt.binding.settle_authorized.return_value = False
    assert session_stats.main(agent_chat=chat, outcome="success", attempt=attempt) is False
    attempt.deliver.assert_not_called()
    attempt.binding.settle_authorized.return_value = True
    attempt.deliver.side_effect = RuntimeError("offer unavailable")
    assert session_stats.main(agent_chat=chat, outcome="success", attempt=attempt) is False


def test_real_hook_delivers_once_and_close_preserves_service():
    """Real Module discovery retains payload identity and Attempt one-shot state."""
    owner = agent()
    service = MagicMock()
    service.pid = os.getpid()
    service.writer_id = "a" * 32
    service.offer.return_value = True
    binding = Binding(service, owner, "example", object(), True)
    attempt = binding.begin()
    attempt.determine("failure")
    chat = SimpleNamespace(ai_agent=owner)
    for _ in range(2):
        hook__workspace__after__attempt_settle_user2agent(
            agent_chat=chat, outcome="failure", attempt=attempt,
        )
    service.offer.assert_called_once()
    assert b'"outcome":"failure"' in service.offer.call_args.args[1]
    binding.close()
    service.stop.assert_not_called()
    service.reclaim.assert_called_once()


def signal(kind):
    """Construct the production control signals without contacting a provider."""
    if issubclass(kind, LLMBackToChatError):
        return kind(attempts=1, manual_cycle_count=0,
                    last_error=RuntimeError("busy"), retry_reason="busy")
    return kind("stop")


@pytest.mark.parametrize("kind,outcome", [
    (None, "success"), (RuntimeError, "failure"),
    (LLMBackToChatError, "back"), (LLMControlledInterruptError, "interrupt"),
    (HardInterruptError, "interrupt"), (KeyboardInterrupt, "interrupt"),
    (EOFError, "interrupt"),
])
def test_host_outcome_and_settlement_before_input(agent_chat, kind, outcome):
    """Settle only run and before the outer Back/interrupt interaction."""
    events = []
    binding = MagicMock()
    agent_chat._stats_binding = binding
    attempt = binding.begin.return_value
    attempt.determine.side_effect = lambda value: events.append(value)
    if kind is None:
        agent_chat.ai_agent.run.return_value = "answer"
    else:
        agent_chat.ai_agent.run.side_effect = signal(kind)

    def next_message(*args):
        """Stop Back handling only after observing the settled result."""
        assert events == [outcome]
        raise EOFError()

    agent_chat._read_next_user_message = next_message
    with ExitStack() as stack:
        for item in _run_patches():
            stack.enter_context(item)
        stack.enter_context(patch(HOST + "get_agent_step_call", return_value=MagicMock()))
        hook = stack.enter_context(patch(HOST + "hook__workspace__after__attempt_settle_user2agent"))
        stack.enter_context(patch(HOST + "input_yes", return_value=False))
        if kind is RuntimeError:
            with pytest.raises(RuntimeError, match="stop"):
                agent_chat._run(message="request", times=1, need_confirm_abort=True)
        else:
            agent_chat._run(message="request", times=1, need_confirm_abort=True)
    assert events == [outcome]
    hook.assert_called_once_with(agent_chat=agent_chat, outcome=outcome, attempt=attempt)


@pytest.mark.parametrize("failure", ["bootstrap", "bind", "prepare", "close", None])
def test_host_binding_lifecycle_is_best_effort(agent_chat, failure):
    """Statistics failure never blocks Agent execution or stops the shared service."""
    service = MagicMock()
    binding = service.bind.return_value
    agent_chat.ai_agent.run.return_value = "answer"
    if failure in ("bind", "prepare", "close"):
        getattr(service if failure == "bind" else binding, failure).side_effect = RuntimeError(failure)
    with ExitStack() as stack:
        for item in _run_patches():
            stack.enter_context(item)
        stack.enter_context(patch(HOST + "get_agent_step_call", return_value=MagicMock()))
        stack.enter_context(patch(HOST + "update_session_meta_status"))
        stack.enter_context(patch(HOST + "hook__workspace__after__attempt_settle_user2agent"))
        bootstrap = stack.enter_context(patch(HOST + "process_service", return_value=service))
        if failure == "bootstrap":
            bootstrap.side_effect = RuntimeError("bootstrap")
        result = agent_chat.run(message="request", times=1, need_confirm_abort=False)
    assert result == "answer"
    agent_chat.ai_agent.close.assert_called_once_with()
    service.stop.assert_not_called()
    if failure not in ("bootstrap", "bind"):
        binding.close.assert_called_once_with()
        service.bind.assert_called_once_with(agent_chat.ai_agent, "retry-session")


def test_settle_ownership_is_not_model_exclusivity():
    """Default settlement rejects foreign owners/threads and preserves strict capture."""
    owner, foreign = agent(), agent()
    service = MagicMock(pid=os.getpid(), writer_id="a" * 32)
    service.offer.return_value = True
    binding = Binding(service, owner, "example", object())
    assert not binding.authorized(owner)
    assert binding.settle_authorized(owner)
    assert not binding.settle_authorized(foreign)
    kwargs = dict(session_id="example", writer_id="a" * 32,
                  agent_id="b" * 32, sequence=1, outcome="success")
    assert capture(binding, **kwargs) is None
    attempt = binding.begin()
    assert not session_stats.main(agent_chat=SimpleNamespace(ai_agent=foreign),
                                  outcome="success", attempt=attempt)
    assert not attempt.observed
    results = []

    def foreign_thread():
        """A different thread must not borrow the execution-thread binding."""
        results.append(binding.prepare())
        results.append(session_stats.main(agent_chat=SimpleNamespace(ai_agent=owner),
                                          outcome="success", attempt=attempt))
        results.append(capture(binding, settle=True, **kwargs))

    thread = threading.Thread(target=foreign_thread)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert results == [False, False, None]
    assert not attempt.observed
    assert session_stats.main(agent_chat=SimpleNamespace(ai_agent=owner),
                              outcome="success", attempt=attempt)
    assert not attempt.deliver()
    binding.close()
    assert not binding.settle_authorized(owner)
    assert capture(binding, settle=True, **kwargs) is None
    service.offer.assert_called_once()


def test_default_binding_pins_replaced_model():
    """Prepare registers current object identity without relying on its mutable name."""
    owner = agent()
    service = MagicMock(pid=os.getpid(), writer_id="a" * 32)
    service.offer.return_value = True
    binding = Binding(service, owner, "example", object())
    old_model = owner.llm_model
    replacement = agent().llm_model
    owner.llm_model = replacement
    assert binding.prepare()
    replacement.model_name = "renamed"
    assert binding.begin().deliver()
    record = json.loads(service.offer.call_args.args[1])
    assert record["model_name"] == "renamed"
    assert record["sources"]["model_instance_id"] == binding.model_id(replacement)
    assert record["sources"]["model_instance_id"] != binding.model_id(old_model)
    assert record["sources"]["token_stat"] == replacement.tokenStat._id
    assert not binding.authorized(owner)


def test_production_default_bind_persists(agent_chat, tmp_path):
    """Real host run, Hook, queue and writer persist without an exclusivity claim."""
    owner = agent()
    owner.run = MagicMock(return_value="answer")
    owner.close = MagicMock()
    owner.messages = []
    agent_chat.ai_agent = owner
    service = StatsService(diagnostic=lambda *args: True, directory=tmp_path)
    try:
        with ExitStack() as stack:
            for item in _run_patches():
                stack.enter_context(item)
            stack.enter_context(patch(HOST + "get_agent_step_call", return_value=MagicMock()))
            stack.enter_context(patch(HOST + "update_session_meta_status"))
            stack.enter_context(patch(HOST + "process_service", return_value=service))
            bind = stack.enter_context(patch.object(service, "bind", wraps=service.bind))
            assert agent_chat.run(message="request", times=1,
                                  need_confirm_abort=False) == "answer"
        bind.assert_called_once_with(owner, "retry-session")
        binding = agent_chat._stats_binding
        assert binding.closed and not binding.exclusive
        assert not service.stopping
        path = binding.writer.path
        wait_for(lambda: path.exists() and len(path.read_bytes().splitlines()) == 1)
        record = json.loads(path.read_bytes())
        assert record["outcome"] == "success"
        assert record["attempt_seq"] == 1
        assert record["sources"]["tool_stat"] == owner.runtime.tool_stat._id
        assert record["sources"]["token_stat"] == owner.llm_model.tokenStat._id
        assert record["sources"]["llm_request_stat"] == owner.llm_request_stat._id
        owner.close.assert_called_once_with()
    finally:
        service.stop()
        service.worker.join(2)
        assert not service.worker.is_alive()
