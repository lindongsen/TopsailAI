"""Unit tests for the interactive prompt loops in the User2Agent run loop.

A closed input channel (Ctrl+D, /dev/null, a closed stdin) raises ``EOFError``
on every read. Reprompting can therefore never succeed, and an unbounded
reprompt loop prints the prompt forever while the tee log grows without limit.
Each prompt site must end the session instead, and must keep propagating every
unrelated exception unchanged.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from topsailai.workspace.agent.agent_shell_base import AgentChat


@pytest.fixture
def agent_chat():
    """Build an AgentChat with isolated runtime collaborators."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "prompt-loop-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "prompt-loop-session"
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

    chat.interrupted = False
    chat._start_control_server = MagicMock()
    chat._stop_control_server = MagicMock()
    chat.call_hooks_pre_run = MagicMock()
    chat.call_hooks_post_fail_run = MagicMock()
    chat.call_hooks_post_succ_run = MagicMock()
    chat.call_hook_for_final_answer = MagicMock()
    chat.hook_for_answer = MagicMock()
    chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
    return chat


def _run_patches(*, input_side_effect=None, get_message_side_effect=None):
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
            return_value=None,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=input_side_effect,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_message",
            side_effect=get_message_side_effect,
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
        patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
    )


def _run_with_patches(agent_chat, patches, **kwargs):
    """Execute one AgentChat run with the isolated patch set applied."""
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4] as input_mock, patches[5] as get_message_mock,
        patches[6], patches[7], patches[8], patches[9],
    ):
        result = agent_chat._run(**kwargs)
    return result, input_mock, get_message_mock


# --------------------------------------------------------------------------
# A. The first-message prompt ends the session on a closed channel
# --------------------------------------------------------------------------

def test_first_message_eof_returns_empty_without_raising(agent_chat):
    """A closed channel before the first message must end the run cleanly."""
    patches = _run_patches(get_message_side_effect=EOFError())

    result, _, get_message_mock = _run_with_patches(
        agent_chat,
        patches,
        message=None,
        times=0,
        need_interactive=True,
    )

    assert result == ""
    get_message_mock.assert_called_once()
    # No turn ran, so no agent execution and no success hook.
    agent_chat.ai_agent.run.assert_not_called()
    agent_chat.call_hooks_post_succ_run.assert_not_called()


def test_first_message_unrelated_exception_still_propagates(agent_chat):
    """Only a closed input channel is recoverable at the first prompt."""
    patches = _run_patches(get_message_side_effect=ValueError("defect"))

    with pytest.raises(ValueError):
        _run_with_patches(
            agent_chat,
            patches,
            message=None,
            times=0,
            need_interactive=True,
        )


# --------------------------------------------------------------------------
# B. The interrupted-resume prompt ends the session on a closed channel
# --------------------------------------------------------------------------

def test_interrupted_prompt_eof_ends_the_session(agent_chat):
    """A closed channel cannot deliver a resume message, so the run ends."""
    agent_chat.interrupted = True
    agent_chat._clear_interrupt_state = MagicMock()
    patches = _run_patches(input_side_effect=EOFError())

    result, input_mock, _ = _run_with_patches(
        agent_chat,
        patches,
        message="request",
        times=0,
        need_interactive=True,
    )

    assert result == ""
    input_mock.assert_called_once()
    # The interrupt state must be cleared before the loop ends, otherwise a
    # later run would re-enter the same unreachable prompt.
    agent_chat._clear_interrupt_state.assert_called_once()
    agent_chat.ai_agent.run.assert_not_called()


def test_interrupted_prompt_unrelated_exception_still_propagates(agent_chat):
    """An unrelated failure at the resume prompt keeps the raise contract."""
    agent_chat.interrupted = True
    agent_chat._clear_interrupt_state = MagicMock()
    patches = _run_patches(input_side_effect=ValueError("defect"))

    with pytest.raises(ValueError):
        _run_with_patches(
            agent_chat,
            patches,
            message="request",
            times=0,
            need_interactive=True,
        )


# --------------------------------------------------------------------------
# C. The next-turn prompt ends the session on a closed channel
# --------------------------------------------------------------------------

def test_next_turn_prompt_eof_ends_the_session(agent_chat):
    """A completed turn must not reprompt forever on a closed channel."""
    agent_chat.ai_agent.run.return_value = "produced answer"
    patches = _run_patches(input_side_effect=EOFError())

    result, input_mock, _ = _run_with_patches(
        agent_chat,
        patches,
        message="request",
        times=0,
        need_interactive=True,
        only_save_final=True,
    )

    assert result == "produced answer"
    input_mock.assert_called_once()
    # The turn itself succeeded, so its hooks still run exactly once.
    agent_chat.call_hooks_post_succ_run.assert_called_once()
    agent_chat.ai_agent.run.assert_called_once()


def test_next_turn_prompt_unrelated_exception_still_propagates(agent_chat):
    """An unrelated failure at the next-turn prompt keeps the raise contract."""
    agent_chat.ai_agent.run.return_value = "produced answer"
    patches = _run_patches(input_side_effect=ValueError("defect"))

    with pytest.raises(ValueError):
        _run_with_patches(
            agent_chat,
            patches,
            message="request",
            times=0,
            need_interactive=True,
            only_save_final=True,
        )


# --------------------------------------------------------------------------
# D. A bounded run never reaches the next-turn prompt
# --------------------------------------------------------------------------

def test_bounded_run_does_not_prompt_again(agent_chat):
    """A finite run exits on its turn budget instead of prompting."""
    agent_chat.ai_agent.run.return_value = "produced answer"
    patches = _run_patches(input_side_effect=EOFError())

    result, input_mock, _ = _run_with_patches(
        agent_chat,
        patches,
        message="request",
        times=1,
        need_interactive=True,
        only_save_final=True,
    )

    assert result == "produced answer"
    input_mock.assert_not_called()
