"""Unit tests for recoverable LLM content verdicts at the User2Agent boundary.

A severe-repetition verdict is computed from the response content. The response
is unusable, but the session, the messages and the user's intent are all still
valid, so an interactive turn must be abandoned and the process must wait for
the next user message instead of terminating. Non-interactive callers and
worker threads keep the original fail-fast contract.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_control.exception import (
    LLMProviderBadRequestError,
    LLMProviderPermissionDeniedError,
    LLMRequestTimeoutError,
    LLMSevereRepetitionError,
)
from topsailai.workspace.agent.agent_shell_base import (
    RECOVERABLE_CONTENT_ERRORS,
    _resolve_recoverable_turn_error,
)
from tests.unit.test_topsailai_workspace_agent_agent_shell_base_provider_error import (
    _run_patches,
    _run_with_patches,
    agent_chat,
)

REPETITION_MESSAGE = (
    "LLM Mistake: Severe repetition detected 2 consecutive times; "
    "retrying cannot change the verdict"
)


def _repetition_error():
    """Build the verdict raised by the repetition detector."""
    return LLMSevereRepetitionError(REPETITION_MESSAGE)


def test_content_error_set_contains_only_the_repetition_verdict():
    """The content set must stay an explicit allowlist, not a broad family."""
    assert RECOVERABLE_CONTENT_ERRORS == (LLMSevereRepetitionError,)


def test_resolve_recoverable_turn_error_returns_direct_repetition_error():
    """A directly raised verdict resolves to itself."""
    error = _repetition_error()
    assert _resolve_recoverable_turn_error(error) is error


def test_resolve_recoverable_turn_error_unwraps_exhaustion_last_error():
    """Exhaustion resolves to the verdict retained in ``last_error``."""
    error = _repetition_error()
    exhausted = LLMRetryExhaustedError(
        attempts=2,
        manual_cycle_count=0,
        last_error=error,
        retry_reason="severe_repetition",
    )
    assert _resolve_recoverable_turn_error(exhausted) is error


def test_resolve_recoverable_turn_error_unwraps_exhaustion_cause():
    """Exhaustion resolves to the verdict chained as ``__cause__``."""
    error = _repetition_error()
    exhausted = LLMRetryExhaustedError(
        attempts=2,
        manual_cycle_count=0,
        last_error=None,
        retry_reason="severe_repetition",
    )
    exhausted.__cause__ = error
    assert _resolve_recoverable_turn_error(exhausted) is error


def test_resolve_recoverable_turn_error_rejects_explicit_exit():
    """An explicit Exit choice must stay fatal even with a verdict cause."""
    exhausted = LLMRetryExhaustedError(
        attempts=2,
        manual_cycle_count=0,
        last_error=_repetition_error(),
        retry_reason="severe_repetition",
        explicit_exit=True,
    )
    assert _resolve_recoverable_turn_error(exhausted) is None


def test_resolve_recoverable_turn_error_does_not_unwrap_request_timeout():
    """A wrapped request-budget failure keeps its original fatal outcome.

    Widening the unwrap loop is a separate decision from adding the content
    verdict, so this test pins the narrower behaviour.
    """
    request_error = LLMRequestTimeoutError("request exceeded its wall-clock budget")
    exhausted = LLMRetryExhaustedError(
        attempts=19,
        manual_cycle_count=0,
        last_error=request_error,
        retry_reason="request_timeout",
    )
    assert _resolve_recoverable_turn_error(exhausted) is None


def test_interactive_repetition_abandons_turn_and_waits_for_next_message(agent_chat):
    """An interactive repetition verdict must keep the session alive."""
    error = _repetition_error()
    agent_chat.ai_agent.run.side_effect = [error, "recovered answer"]
    failure_hook = agent_chat.call_hooks_post_fail_run
    success_hook = agent_chat.call_hooks_post_succ_run
    built_turns = []

    def build_message(*, message, curr_count):
        """Record the turn accounting of every built message."""
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
    failure_hook.assert_called_once_with(error)
    success_hook.assert_called_once_with()
    assert agent_chat.interrupted is False
    assert agent_chat.last_message == "recovered answer"


def test_interactive_exhausted_repetition_abandons_turn(agent_chat):
    """A verdict consumed by the retry loop must also be recoverable."""
    error = _repetition_error()
    exhausted = LLMRetryExhaustedError(
        attempts=2,
        manual_cycle_count=0,
        last_error=error,
        retry_reason="severe_repetition",
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


def test_non_interactive_repetition_still_raises(agent_chat):
    """Non-interactive callers must keep the original fail-fast contract."""
    error = _repetition_error()
    agent_chat.ai_agent.run.side_effect = error
    patches = _run_patches(runtime_input=None, input_messages=())
    with pytest.raises(LLMSevereRepetitionError):
        _run_with_patches(
            agent_chat,
            patches,
            message="failed request",
            times=1,
            need_interactive=False,
        )

    agent_chat.ai_agent.run.assert_called_once()
    agent_chat.call_hooks_post_fail_run.assert_not_called()


def test_worker_thread_repetition_still_raises(agent_chat):
    """A worker thread must never read the main conversation's input."""
    error = _repetition_error()
    agent_chat.ai_agent.run.side_effect = error
    patches = _run_patches(
        runtime_input=MagicMock(),
        input_messages=("next request",),
    )
    with patch(
        "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
        return_value=False,
    ):
        with pytest.raises(LLMSevereRepetitionError):
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
    """Adding the content verdict must not widen the provider allowlist."""
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


def test_interactive_repetition_next_input_interruption_terminates(agent_chat):
    """Interrupting the next-message read must terminate without success effects."""
    error = _repetition_error()
    agent_chat.ai_agent.run.side_effect = error
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
    assert agent_chat.call_hooks_post_fail_run.call_args_list[0] == call(error)
    assert isinstance(
        agent_chat.call_hooks_post_fail_run.call_args_list[1].args[0],
        KeyboardInterrupt,
    )
    agent_chat.call_hooks_post_succ_run.assert_not_called()
