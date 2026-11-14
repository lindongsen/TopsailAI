"""Unit tests for database I/O failure recovery at the User2Agent boundary.

A database write failure must never terminate the process. The conversation, the
session metadata and the diagnostic artifacts all survive, so an interactive
turn is abandoned and the loop waits for the next user message. Non-interactive
callers and worker threads cannot wait for a human, so they end with an explicit
failure answer instead of an uncaught traceback.
"""

import sqlite3
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from topsailai.workspace.agent.agent_shell_base import (
    AgentChat,
    _resolve_db_io_failure,
)


def _sqlite_error(code: int, message: str = "synthetic") -> OperationalError:
    """Build an OperationalError carrying a real SQLite primary result code."""
    orig = sqlite3.OperationalError(message)
    orig.sqlite_errorcode = code
    return OperationalError("stmt", {}, orig)


@pytest.fixture
def agent_chat():
    """Build an AgentChat with isolated runtime collaborators."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "db-io-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "db-io-session"
    ctx_runtime_data.session_data = None
    ctx_rt_aiagent.ai_agent = ai_agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    with (
        patch(
            "topsailai.workspace.agent.hooks.base.init.get_hooks",
            return_value=[],
        ),
        patch(
            "topsailai.workspace.agent.agent_chat_base.set_ai_agent",
        ),
    ):
        chat = AgentChat(
            hook_instruction=hook_instruction,
            ctx_rt_aiagent=ctx_rt_aiagent,
            ctx_rt_instruction=ctx_rt_instruction,
        )

    chat._start_control_server = MagicMock()
    chat._stop_control_server = MagicMock()
    chat.call_hooks_pre_run = MagicMock()
    chat.call_hooks_post_fail_run = MagicMock()
    chat.call_hooks_post_succ_run = MagicMock()
    chat.call_hook_for_final_answer = MagicMock()
    chat.hook_for_answer = MagicMock()
    chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
    return chat


def _run_patches(*, runtime_input=None, input_messages=()):
    """Return patches that isolate one AgentChat execution."""
    env_values = {
        "TOPSAILAI_INTERACTIVE_MODE": True,
        "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": False,
        "TOPSAILAI_ENABLE_SESSION_LOCK": False,
        "TOPSAILAI_PRINT_TOOL_STAT": False,
    }
    return (
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.EnvReaderInstance.check_bool",
            side_effect=lambda key, default: env_values.get(key, default),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_debug_mode",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.env_tool.is_need_print",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_runtime_input",
            return_value=runtime_input,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=input_messages,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.task_tool.ctxm_process_task",
            side_effect=lambda _task: nullcontext(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.lock_tool.ctxm_void",
            side_effect=lambda **_: nullcontext({}),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.terminal_title.refresh_terminal_title",
        ),
    )


def _run_with_patches(agent_chat, patches, *, message, times, need_interactive, **kwargs):
    """Execute one AgentChat run with the isolated patch set applied."""
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4] as input_mock, patches[5], patches[6], patches[7],
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
    ):
        result = agent_chat._run(
            message=message,
            times=times,
            need_interactive=need_interactive,
            **kwargs,
        )
    return result, input_mock


# --------------------------------------------------------------------------
# A. Exception-chain resolution
# --------------------------------------------------------------------------

def test_resolve_returns_direct_io_failure():
    exc = _sqlite_error(5)
    assert _resolve_db_io_failure(exc) is exc


def test_resolve_walks_cause_chain():
    io_error = _sqlite_error(13)
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = io_error
    assert _resolve_db_io_failure(wrapper) is io_error


def test_resolve_walks_context_chain():
    io_error = _sqlite_error(5)
    wrapper = RuntimeError("wrapped")
    wrapper.__context__ = io_error
    assert _resolve_db_io_failure(wrapper) is io_error


def test_resolve_returns_none_for_unrelated_error():
    assert _resolve_db_io_failure(ValueError("bad input")) is None


def test_resolve_survives_a_cyclic_chain():
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    assert _resolve_db_io_failure(first) is None


# --------------------------------------------------------------------------
# B. Interactive main thread abandons the turn
# --------------------------------------------------------------------------

def test_interactive_io_failure_abandons_turn_and_waits_for_next_message(agent_chat):
    """An interactive database failure must keep the session alive."""
    io_error = _sqlite_error(13, "database or disk is full")
    agent_chat.ai_agent.run.side_effect = [io_error, "recovered answer"]
    failure_hook = agent_chat.call_hooks_post_fail_run
    success_hook = agent_chat.call_hooks_post_succ_run
    built_turns = []

    def build_message(*, message, curr_count):
        built_turns.append((message, curr_count))
        return message

    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    result, input_mock = _run_with_patches(
        agent_chat,
        patches,
        message="failed request",
        times=1,
        need_interactive=True,
        func_build_message=build_message,
    )

    assert result == "recovered answer"
    assert agent_chat.ai_agent.run.call_count == 2
    assert [item.args[1] for item in agent_chat.ai_agent.run.call_args_list] == [
        "failed request",
        "next request",
    ]
    # The abandoned turn must not consume the finite-turn budget.
    assert built_turns == [("failed request", 1), ("next request", 1)]
    input_mock.assert_called_once_with(hook=agent_chat.hook_instruction)
    failure_hook.assert_called_once_with(io_error)
    success_hook.assert_called_once_with()
    assert agent_chat.interrupted is False
    assert agent_chat.last_message == "recovered answer"


def test_interactive_io_failure_does_not_terminate_the_process(agent_chat):
    """The failure path must never reach a process-terminating call."""
    io_error = _sqlite_error(13, "database or disk is full")
    agent_chat.ai_agent.run.side_effect = io_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=(EOFError(),),
    )
    with (
        patch("os._exit") as exit_mock,
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_yes",
            return_value=False,
        ),
    ):
        result, _ = _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=0,
            need_interactive=True,
        )

    exit_mock.assert_not_called()
    assert result == "failed due to abort by Human"


# --------------------------------------------------------------------------
# C. Non-interactive and worker-thread callers end with a failure answer
# --------------------------------------------------------------------------

def test_non_interactive_io_failure_returns_failure_answer(agent_chat):
    """A non-interactive caller must not receive an uncaught traceback."""
    io_error = _sqlite_error(13, "database or disk is full")
    agent_chat.ai_agent.run.side_effect = io_error
    patches = _run_patches(runtime_input=None, input_messages=())

    result, input_mock = _run_with_patches(
        agent_chat,
        patches,
        message="failed request",
        times=1,
        need_interactive=False,
    )

    assert "Task terminated" in result
    assert "database or disk is full" in result
    assert agent_chat._terminal_failure is True
    assert agent_chat.last_message == result
    input_mock.assert_not_called()
    agent_chat.call_hooks_post_fail_run.assert_called_once_with(io_error)
    agent_chat.call_hooks_post_succ_run.assert_not_called()


def test_worker_thread_io_failure_returns_failure_answer(agent_chat):
    """A worker thread must never read the main conversation's input."""
    io_error = _sqlite_error(5, "database is locked")
    agent_chat.ai_agent.run.side_effect = io_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    with patch(
        "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
        return_value=False,
    ):
        result, input_mock = _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=True,
        )

    assert "Task terminated" in result
    assert agent_chat._terminal_failure is True
    input_mock.assert_not_called()


def test_unrelated_exception_still_propagates(agent_chat):
    """A programming defect must keep its original contract."""
    agent_chat.ai_agent.run.side_effect = ValueError("unrelated local defect")
    patches = _run_patches(runtime_input=None, input_messages=())

    with pytest.raises(ValueError):
        _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=False,
        )

    agent_chat.call_hooks_post_fail_run.assert_not_called()


# --------------------------------------------------------------------------
# D. A failure after the answer exists must not discard it
# --------------------------------------------------------------------------

def test_persistence_failure_keeps_the_answer_and_continues(agent_chat):
    """A lost write must not lose the result or end the process."""
    io_error = _sqlite_error(13, "database or disk is full")
    agent_chat.ai_agent.run.return_value = "produced answer"
    agent_chat.ctx_runtime_data.add_session_message.side_effect = io_error
    patches = _run_patches(runtime_input=None, input_messages=())

    result, _ = _run_with_patches(
        agent_chat,
        patches,
        message="request",
        times=1,
        need_interactive=False,
        only_save_final=True,
    )
    assert result == "produced answer"
    assert agent_chat.last_message == "produced answer"
    agent_chat.ctx_runtime_data.add_session_message.assert_called_once()
    # The session reload would fail the same way, so it must be skipped.
    agent_chat.ctx_runtime_data.reset_messages.assert_not_called()
    # The turn did not fully succeed, so the success hook must not run.
    agent_chat.call_hooks_post_succ_run.assert_not_called()


def test_persistence_failure_does_not_raise(agent_chat):
    """The persistence guard must swallow only the database I/O failure."""
    io_error = _sqlite_error(5, "database is locked")
    agent_chat.ai_agent.run.return_value = "produced answer"
    agent_chat.ctx_runtime_data.add_session_message.side_effect = io_error
    patches = _run_patches(runtime_input=None, input_messages=())

    result, _ = _run_with_patches(
        agent_chat,
        patches,
        message="request",
        times=1,
        need_interactive=False,
        only_save_final=True,
    )

    assert result == "produced answer"


def test_persistence_unrelated_exception_still_propagates(agent_chat):
    """Only a database I/O failure is recoverable at the persistence boundary."""
    agent_chat.ai_agent.run.return_value = "produced answer"
    agent_chat.ctx_runtime_data.add_session_message.side_effect = ValueError("defect")
    patches = _run_patches(runtime_input=None, input_messages=())

    with pytest.raises(ValueError):
        _run_with_patches(
            agent_chat,
            patches,
            message="request",
            times=1,
            need_interactive=False,
            only_save_final=True,
        )


# --------------------------------------------------------------------------
# E. Last-resort net in run()
# --------------------------------------------------------------------------

def test_run_returns_failure_answer_for_escaping_io_failure(agent_chat):
    """A database failure escaping _run must not become an uncaught traceback."""
    io_error = _sqlite_error(13, "database or disk is full")
    agent_chat._run = MagicMock(side_effect=io_error)

    with (
        patch(
            "topsailai.workspace.agent.agent_shell_base.process_service",
            side_effect=RuntimeError("statistics unavailable"),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ) as meta_status,
    ):
        result = agent_chat.run(message="request", times=1)

    assert "Task terminated" in result
    assert "database or disk is full" in result
    assert agent_chat._terminal_failure is True
    assert agent_chat.last_message == result
    meta_status.assert_called_once_with("error", "db-io-session")


def test_run_still_raises_for_unrelated_escaping_exception(agent_chat):
    """An unrelated failure keeps the original raise contract."""
    agent_chat._run = MagicMock(side_effect=ValueError("defect"))

    with (
        patch(
            "topsailai.workspace.agent.agent_shell_base.process_service",
            side_effect=RuntimeError("statistics unavailable"),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ),
    ):
        with pytest.raises(ValueError):
            agent_chat.run(message="request", times=1)
