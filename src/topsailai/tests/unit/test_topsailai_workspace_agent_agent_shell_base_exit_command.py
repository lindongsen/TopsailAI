"""
Regression tests for the exit-command session outcome.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify a deliberate exit command records `completed`, not `interrupted`
"""

import inspect
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pytest

from topsailai.workspace.agent.agent_shell_base import AgentChat
from tests.unit.test_topsailai_workspace_agent_agent_shell_base_llm_retry import (
    agent_chat,
    _run_patches,
)


@pytest.fixture
def exit_runtime(agent_chat):
    """Isolate process services and the metadata writer for outcome checks."""
    with ExitStack() as stack:
        for item in _run_patches():
            stack.enter_context(item)
        stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ))
        service = stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.process_service",
        ))
        meta = stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ))
        yield agent_chat, meta, service


def run_chat(chat, **kwargs):
    """Execute the production run boundary without its unrelated stdout tee."""
    return inspect.unwrap(AgentChat.run)(chat, message="task", times=1, **kwargs)


@pytest.mark.parametrize("exit_code", [0, 3])
def test_exit_command_records_completed_and_propagates_code(exit_runtime, exit_code):
    """A deliberate exit marks the session complete and keeps its exit code."""
    chat, meta, _ = exit_runtime
    chat._run = MagicMock(side_effect=SystemExit(exit_code))

    with pytest.raises(SystemExit) as raised:
        run_chat(chat)

    assert raised.value.code == exit_code
    assert meta.call_args_list == [call("completed", "retry-session")]


def test_exit_command_does_not_report_error(exit_runtime):
    """A deliberate exit must never be recorded as a failure."""
    chat, meta, _ = exit_runtime
    chat._run = MagicMock(side_effect=SystemExit(0))

    with pytest.raises(SystemExit):
        run_chat(chat)

    statuses = [args[0] for args, _ in meta.call_args_list]
    assert "error" not in statuses
    assert "interrupted" not in statuses


def test_keyboard_interrupt_still_skips_the_completion_write(exit_runtime):
    """Ctrl+C keeps reporting `interrupted`, so no completion write happens."""
    chat, meta, _ = exit_runtime
    chat._run = MagicMock(side_effect=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        run_chat(chat)

    assert meta.call_args_list == []


def test_ordinary_failure_still_records_error(exit_runtime):
    """A genuine exception keeps its original error outcome."""
    chat, meta, _ = exit_runtime
    chat._run = MagicMock(side_effect=ValueError("bad input"))

    with pytest.raises(ValueError):
        run_chat(chat)

    assert meta.call_args_list == [call("error", "retry-session")]


def test_exit_command_still_closes_runtime_resources(exit_runtime):
    """The exit path must not skip control-server and agent teardown."""
    chat, _, _ = exit_runtime
    chat._run = MagicMock(side_effect=SystemExit(0))

    with pytest.raises(SystemExit):
        run_chat(chat)

    chat._stop_control_server.assert_called_once_with()
    chat.ai_agent.close.assert_called_once_with()
