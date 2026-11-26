"""BDD steps for surviving a provider bad-request failure. Author: DawsonLin.

Every scenario drives the real ``AgentChat`` turn loop and the real turn-error
policy. Only the collaborators outside the behavior under test are replaced: the
provider call, the runtime input channel, and the session metadata store. The
failure itself is a real ``LLMProviderBadRequestError``, so the policy classifies
it exactly as production does.

The scenarios assert the two outcomes that matter to an operator: a multi-turn
interactive session abandons the turn and keeps running, while every other shape
keeps the failure fatal so a broken request never looks like a handled turn.
"""

from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, then, when
from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_control.exception import (
    LLMProviderBadRequestError,
    LLMProviderPermissionDeniedError,
)
from topsailai.workspace.agent.agent_shell_base import AgentChat

ABANDONED_ANSWER = "failed due to abort by Human"


@pytest.fixture
def bdd_state():
    """Carry one scenario's observable outcome."""
    return {}


@pytest.fixture
def bdd_chat():
    """Build a real AgentChat whose collaborators outside the behavior are isolated."""
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ai_agent = MagicMock()
    ai_agent.agent_type = "react"
    ai_agent.agent_name = "bdd-bad-request-agent"
    ai_agent.hooks_after_init_prompt = []
    ai_agent.hooks_after_new_session = []
    ai_agent.hooks_pre_chat = []
    ai_agent.messages = []
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "bdd-bad-request-session"
    ctx_runtime_data.session_data = None
    ctx_rt_aiagent.ai_agent = ai_agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    with (
        patch("topsailai.workspace.agent.hooks.base.init.get_hooks", return_value=[]),
        patch("topsailai.workspace.agent.agent_chat_base.set_ai_agent"),
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


def _run_patches(*, runtime_input=None, is_main_thread=True):
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
            "topsailai.workspace.agent.agent_shell_base.get_agent_step_call",
            return_value=MagicMock(),
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.update_session_meta_status",
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_yes",
            return_value=False,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.thread_tool.is_main_thread",
            return_value=is_main_thread,
        ),
        patch(
            "topsailai.workspace.agent.agent_shell_base.input_message",
            side_effect=EOFError(),
        ),
    )


def _execute(chat, *, need_interactive, times, runtime_input=None, is_main_thread=True):
    """Run one AgentChat turn with the isolated patch set applied.

    A fatal failure is captured rather than propagated so a scenario can assert
    that the rejection stayed fatal without aborting the test runner.
    """
    patches = _run_patches(runtime_input=runtime_input, is_main_thread=is_main_thread)
    with (
        patches[0], patches[1], patches[2], patches[3],
        patches[4], patches[5] as meta_status, patches[6], patches[7],
        patches[8],
    ):
        try:
            result = chat._run(
                message="request the provider rejects",
                times=times,
                need_interactive=need_interactive,
            )
            raised = None
        except BaseException as error:  # noqa: BLE001 - the outcome is the assertion
            result = None
            raised = error
    return {
        "result": result,
        "raised": raised,
        "meta_status": meta_status,
    }


def _arm(chat, error):
    """Make the provider call raise the given error."""
    chat.ai_agent.run.side_effect = error


@given("an interactive multi-turn agent session whose provider rejects the request")
def multi_turn_rejection(bdd_chat, bdd_state):
    """Arm a bad-request failure on an unlimited-turn interactive session."""
    _arm(bdd_chat, LLMProviderBadRequestError("invalid request payload"))
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()


@given(
    "an interactive multi-turn agent session whose retries are exhausted by a rejection"
)
def multi_turn_exhausted_rejection(bdd_chat, bdd_state):
    """Arm a retry-exhaustion wrapper whose underlying cause is a rejection."""
    _arm(
        bdd_chat,
        LLMRetryExhaustedError(
            attempts=18,
            last_error=LLMProviderBadRequestError("invalid request payload"),
            retry_reason="bad_request",
        ),
    )
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()


@given("a single-turn agent session whose provider rejects the request")
def single_turn_rejection(bdd_chat, bdd_state):
    """Arm a bad-request failure on a single-turn session."""
    _arm(bdd_chat, LLMProviderBadRequestError("invalid request payload"))
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()
    bdd_state["times"] = 1


@given("a non-interactive multi-turn agent session whose provider rejects the request")
def non_interactive_multi_turn_rejection(bdd_chat, bdd_state):
    """Arm a bad-request failure on a non-interactive multi-turn session."""
    _arm(bdd_chat, LLMProviderBadRequestError("invalid request payload"))
    bdd_state["chat"] = bdd_chat
    bdd_state["non_interactive"] = True


@given(
    "an interactive multi-turn agent session whose provider rejects the request in a worker thread"
)
def worker_thread_rejection(bdd_chat, bdd_state):
    """Arm a bad-request failure observed from a worker thread."""
    _arm(bdd_chat, LLMProviderBadRequestError("invalid request payload"))
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()
    bdd_state["worker_thread"] = True


@given("an interactive multi-turn agent session whose provider denies permission")
def multi_turn_permission_denied(bdd_chat, bdd_state):
    """Arm a permission-denied failure on an unlimited-turn interactive session."""
    _arm(bdd_chat, LLMProviderPermissionDeniedError("credential rejected"))
    bdd_state["chat"] = bdd_chat
    bdd_state["input_mock"] = MagicMock()
    bdd_state["input_mock"].side_effect = EOFError()


@when("the turn is abandoned")
def abandon_one_turn(bdd_state):
    """Execute one turn that the provider rejects."""
    bdd_state["outcome"] = _execute(
        bdd_state["chat"],
        need_interactive=not bdd_state.get("non_interactive", False),
        times=bdd_state.get("times", 0),
        runtime_input=bdd_state.get("input_mock"),
        is_main_thread=not bdd_state.get("worker_thread", False),
    )


@when(parsers.parse("{count:d} consecutive turns are rejected"))
def abandon_consecutive_turns(bdd_state, count):
    """Execute several turns that the provider rejects."""
    chat = bdd_state["chat"]
    outcomes = []
    for _ in range(count):
        _arm(chat, LLMProviderBadRequestError("invalid request payload"))
        outcomes.append(
            _execute(
                chat,
                need_interactive=True,
                times=0,
                runtime_input=bdd_state["input_mock"],
            )
        )
    bdd_state["outcome"] = outcomes[-1]
    bdd_state["outcomes"] = outcomes


@when("the turn is abandoned in a worker thread")
def abandon_turn_in_worker_thread(bdd_state):
    """Execute one turn while the caller is a worker thread."""
    bdd_state["outcome"] = _execute(
        bdd_state["chat"],
        need_interactive=True,
        times=0,
        runtime_input=bdd_state["input_mock"],
        is_main_thread=False,
    )


@then("the session returns to the input prompt")
def session_returns_to_prompt(bdd_state):
    """The abandoned turn must hand control back to the input channel."""
    outcome = bdd_state["outcome"]
    assert outcome["raised"] is None, (
        "a multi-turn interactive session must not propagate the rejection: "
        f"{outcome['raised']!r}"
    )
    assert outcome["result"] == ABANDONED_ANSWER


@then("the process is still alive")
def process_is_alive(bdd_state):
    """No fatal outcome may be observed for a multi-turn interactive session."""
    assert bdd_state["outcome"]["raised"] is None


@then("the session metadata is retained")
def metadata_is_retained(bdd_state):
    """A live session must never be finalized as ``error``."""
    meta_status = bdd_state["outcome"]["meta_status"]
    error_calls = [
        call
        for call in meta_status.call_args_list
        if call.args and call.args[0] == "error"
    ]
    assert error_calls == [], (
        f"a live session must not be finalized as error: {error_calls}"
    )


@then("the session returns to the input prompt after every rejection")
def session_returns_to_prompt_every_time(bdd_state):
    """Every consecutive rejection must hand control back to the input channel."""
    for outcome in bdd_state["outcomes"]:
        assert outcome["raised"] is None
        assert outcome["result"] == ABANDONED_ANSWER


@then("the rejection stays fatal")
def rejection_stays_fatal(bdd_state):
    """Every shape without a live interactive conversation keeps the failure fatal."""
    raised = bdd_state["outcome"]["raised"]
    assert raised is not None, (
        "the rejection must stay fatal, but the turn returned "
        f"{bdd_state['outcome']['result']!r}"
    )
    assert isinstance(
        raised,
        (LLMProviderBadRequestError, LLMProviderPermissionDeniedError, LLMRetryExhaustedError),
    ), f"unexpected fatal error type: {type(raised).__name__}"
