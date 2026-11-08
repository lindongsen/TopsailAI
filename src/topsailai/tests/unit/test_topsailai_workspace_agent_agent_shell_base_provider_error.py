"""Unit tests for recoverable LLM provider failures at the User2Agent boundary.

A provider-side failure (stream error frame, connection drop, timeout, protocol
read failure) leaves the session, the messages and the user's intent intact. In
interactive mode the turn must be abandoned and the process must wait for the
next user message instead of terminating. Non-interactive callers keep the
original fail-fast contract.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, call, patch

import pytest

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_control.exception import (
    LLMProviderBadRequestError,
    LLMProviderConnectionError,
    LLMProviderInternalServerError,
    LLMProviderPermissionDeniedError,
    LLMProviderReadError,
    LLMProviderTimeoutError,
)
from topsailai.workspace.agent.agent_shell_base import (
    AgentChat,
    _resolve_recoverable_provider_error,
)


@pytest.fixture
def agent_chat():
    """Build an AgentChat with isolated runtime collaborators."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "provider-error-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "provider-error-session"
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


@pytest.mark.parametrize(
    "provider_error",
    [
        LLMProviderInternalServerError(
            "litellm.InternalServerError: The model is repeating the same chunk =   |  |  |."
        ),
        LLMProviderConnectionError("connection reset by peer"),
        LLMProviderTimeoutError("first byte timeout"),
        LLMProviderReadError("stream read failed"),
    ],
)
def test_interactive_provider_failure_abandons_turn_and_waits_for_next_message(
    agent_chat, provider_error
):
    """An interactive provider failure must keep the session alive."""
    agent_chat.ai_agent.run.side_effect = [provider_error, "recovered answer"]
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
    failure_hook.assert_called_once_with(provider_error)
    success_hook.assert_called_once_with()
    assert agent_chat.interrupted is False
    assert agent_chat.last_message == "recovered answer"


def test_interactive_exhausted_provider_failure_abandons_turn(agent_chat):
    """A provider failure consumed by the retry loop must also be recoverable."""
    provider_error = LLMProviderInternalServerError(
        "litellm.InternalServerError: The model is repeating the same chunk =   |  |  |."
    )
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=provider_error,
        retry_reason="internal_server",
    )
    agent_chat.ai_agent.run.side_effect = [exhausted, "recovered answer"]
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
    )

    assert result == "recovered answer"
    assert agent_chat.ai_agent.run.call_count == 2
    input_mock.assert_called_once_with(hook=agent_chat.hook_instruction)
    agent_chat.call_hooks_post_fail_run.assert_called_once_with(exhausted)


@pytest.mark.parametrize(
    "provider_error",
    [
        LLMProviderInternalServerError("internal server error"),
        LLMProviderConnectionError("connection reset by peer"),
    ],
)
def test_non_interactive_provider_failure_still_raises(agent_chat, provider_error):
    """Non-interactive callers must keep the original fail-fast contract."""
    agent_chat.ai_agent.run.side_effect = provider_error
    patches = _run_patches(runtime_input=None, input_messages=())
    with pytest.raises(type(provider_error)):
        _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=False,
        )

    agent_chat.ai_agent.run.assert_called_once()
    agent_chat.call_hooks_post_fail_run.assert_not_called()


def test_worker_thread_provider_failure_still_raises(agent_chat):
    """A worker thread (e.g. a subagent) must never read the main input.

    Subagents run on a worker thread where the retry loop cannot prompt, so a
    provider failure arrives as automatic exhaustion. Abandoning the turn there
    would block the subagent on the main conversation's input, so it stays fatal.
    """
    provider_error = LLMProviderInternalServerError(
        "litellm.InternalServerError: The model is repeating the same chunk =   |  |  |."
    )
    agent_chat.ai_agent.run.side_effect = provider_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    with patch(
        "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
        return_value=False,
    ):
        with pytest.raises(LLMProviderInternalServerError):
            _run_with_patches(
                agent_chat,
                patches,
                message="failed request",
                times=1,
                need_interactive=True,
            )

    agent_chat.ai_agent.run.assert_called_once()
    agent_chat.call_hooks_post_fail_run.assert_not_called()


@pytest.mark.parametrize(
    "fatal_error",
    [
        LLMProviderBadRequestError("malformed request payload"),
        LLMProviderPermissionDeniedError("invalid api key"),
    ],
)
def test_interactive_fatal_provider_failure_still_raises(agent_chat, fatal_error):
    """Bad-request and permission-denied failures cannot be fixed by continuing."""
    agent_chat.ai_agent.run.side_effect = fatal_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    with pytest.raises(type(fatal_error)):
        _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=True,
        )

    agent_chat.ai_agent.run.assert_called_once()
    agent_chat.call_hooks_post_fail_run.assert_not_called()


def test_interactive_unrelated_exhaustion_stays_fatal(agent_chat):
    """Exhaustion caused by a non-provider error must not be swallowed."""
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=ValueError("unrelated local defect"),
        retry_reason="unknown",
    )
    agent_chat.ai_agent.run.side_effect = exhausted
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    with pytest.raises(LLMRetryExhaustedError):
        _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=True,
        )

    agent_chat.ai_agent.run.assert_called_once()
    agent_chat.call_hooks_post_fail_run.assert_not_called()


def test_interactive_provider_failure_next_input_interruption_terminates(agent_chat):
    """Interrupting the next-message read must terminate without success effects."""
    provider_error = LLMProviderInternalServerError("internal server error")
    agent_chat.ai_agent.run.side_effect = provider_error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=(EOFError(),),
    )
    with patch(
        "topsailai.workspace.agent.agent_shell_base.input_yes",
        return_value=False,
    ) as confirm_abort:
        result, _ = _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=0,
            need_interactive=True,
        )

    assert result == "failed due to abort by Human"
    agent_chat.ai_agent.run.assert_called_once()
    confirm_abort.assert_called_once_with("Agent Session Continue [yes/no] ")
    assert agent_chat.call_hooks_post_fail_run.call_count == 2
    assert agent_chat.call_hooks_post_fail_run.call_args_list[0] == call(provider_error)
    assert isinstance(
        agent_chat.call_hooks_post_fail_run.call_args_list[1].args[0],
        KeyboardInterrupt,
    )
    agent_chat.call_hooks_post_succ_run.assert_not_called()


def test_resolve_recoverable_provider_error_returns_direct_provider_error():
    """A directly raised provider error resolves to itself."""
    provider_error = LLMProviderInternalServerError("internal server error")
    assert _resolve_recoverable_provider_error(provider_error) is provider_error


def test_resolve_recoverable_provider_error_unwraps_exhaustion_last_error():
    """Exhaustion resolves to the provider error retained in ``last_error``."""
    provider_error = LLMProviderTimeoutError("first byte timeout")
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=provider_error,
        retry_reason="timeout",
    )
    assert _resolve_recoverable_provider_error(exhausted) is provider_error


def test_resolve_recoverable_provider_error_unwraps_exhaustion_cause():
    """Exhaustion resolves to the provider error chained as ``__cause__``."""
    provider_error = LLMProviderReadError("stream read failed")
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=None,
        retry_reason="read_error",
    )
    exhausted.__cause__ = provider_error
    assert _resolve_recoverable_provider_error(exhausted) is provider_error


@pytest.mark.parametrize(
    "error",
    [
        ValueError("unrelated"),
        LLMProviderBadRequestError("malformed request payload"),
        LLMProviderPermissionDeniedError("invalid api key"),
        LLMRetryExhaustedError(
            attempts=18,
            manual_cycle_count=0,
            last_error=ValueError("unrelated"),
            retry_reason="unknown",
        ),
    ],
)
def test_resolve_recoverable_provider_error_rejects_non_recoverable(error):
    """Non-recoverable failures must resolve to ``None``."""
    assert _resolve_recoverable_provider_error(error) is None


def test_resolve_recoverable_provider_error_rejects_explicit_exit():
    """An explicit Exit choice must stay fatal even with a provider cause."""
    provider_error = LLMProviderInternalServerError("internal server error")
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=provider_error,
        retry_reason="internal_server_error",
        explicit_exit=True,
    )
    assert _resolve_recoverable_provider_error(exhausted) is None


def test_explicit_exit_defaults_to_false():
    """Automatic exhaustion must not be mistaken for a human Exit choice."""
    exhausted = LLMRetryExhaustedError(
        attempts=18,
        manual_cycle_count=0,
        last_error=None,
        retry_reason="unknown",
    )
    assert exhausted.explicit_exit is False
