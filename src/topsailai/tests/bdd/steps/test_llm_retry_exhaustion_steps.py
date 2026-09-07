"""BDD steps for interactive LLM retry exhaustion over real HTTP/SSE."""

import pytest
from pytest_bdd import given, then, when

from topsailai.ai_base.exception import LLMRetryExhaustedError
from tests.bdd.llm_retry_exhaustion_harness import (
    MAX_ATTEMPTS,
    BDD_MAX_MANUAL_RETRY_CYCLES,
    BDD_MAX_TOTAL_ATTEMPTS,
    SUCCESS_RESPONSE,
    LLMRetryScenario,
)


@pytest.fixture
def llm_retry_ctx(monkeypatch):
    """Yield one isolated real-HTTP retry scenario and stop its exact thread."""
    context = LLMRetryScenario(monkeypatch)
    yield context
    context.close()


@given(
    "an LLM retry scenario whose first request cycle returns busy SSE responses "
    "and then succeeds"
)
def given_retry_cycle_then_success(llm_retry_ctx):
    """Script one exhausted request cycle followed by a successful response."""
    llm_retry_ctx.script_exhaustion_then_success()
    assert llm_retry_ctx.server_owner.thread.is_alive()


@given(
    "an LLM retry scenario whose bounded request cycle returns only busy SSE responses"
)
def given_exhausted_retry_cycle(llm_retry_ctx):
    """Script one complete bounded request cycle with no successful response."""
    llm_retry_ctx.script_exhaustion()
    assert llm_retry_ctx.server_owner.thread.is_alive()


@given(
    "an LLM retry scenario whose configured retry budget returns busy SSE responses"
)
def given_total_retry_budget_exhaustion(llm_retry_ctx):
    """Script busy responses through the injected finite request budget."""
    llm_retry_ctx.script_total_bound_exhaustion()
    assert llm_retry_ctx.server_owner.thread.is_alive()


@when("the user enters an invalid exhaustion choice and then chooses Retry")
def when_invalid_then_retry(llm_retry_ctx):
    """Retry the same request inside the current LLM chat, not the Agent loop."""
    llm_retry_ctx.run_direct(["invalid", "1"])


@when("the user repeatedly chooses Retry through every permitted manual cycle")
def when_retry_reaches_absolute_bound(llm_retry_ctx):
    """Use every injected manual cycle and stop at the request limit."""
    llm_retry_ctx.run_direct(
        ["1"] * BDD_MAX_MANUAL_RETRY_CYCLES,
        max_manual_retry_cycles=BDD_MAX_MANUAL_RETRY_CYCLES,
    )


@when("the continuous chat user enters an invalid choice and then chooses Back")
def when_invalid_then_back(llm_retry_ctx):
    """Abandon the failed Agent turn before obtaining fresh User2Agent input."""
    llm_retry_ctx.run_back_to_fresh_message()


@when("the continuous chat user chooses Exit after exhaustion")
def when_continuous_user_exits(llm_retry_ctx):
    """Exit the three-choice continuous-chat exhaustion menu."""
    llm_retry_ctx.run_direct(["3"], allow_back=True)


@when("the finite execution user chooses Exit after exhaustion")
def when_finite_user_exits(llm_retry_ctx):
    """Exit the finite execution menu, where Back is unavailable."""
    llm_retry_ctx.run_direct(["2"])


@when("the retry exhaustion input reaches EOF")
def when_retry_input_reaches_eof(llm_retry_ctx):
    """Map EOF from the explicit runtime input callback to Exit."""
    llm_retry_ctx.run_direct([EOFError()])


@when("the retry exhaustion input is interrupted by the keyboard")
def when_retry_input_keyboard_interrupt(llm_retry_ctx):
    """Map KeyboardInterrupt from the runtime input callback to Exit."""
    llm_retry_ctx.run_direct([KeyboardInterrupt()])


@when("retry exhaustion has no runtime input capability")
def when_retry_input_is_unavailable(llm_retry_ctx):
    """Exhaust automatically without consulting builtin or runtime input."""
    llm_retry_ctx.run_direct(None, input_available=False)


@then("the retry scenario returns the successful provider response")
def then_retry_succeeds(llm_retry_ctx):
    """Assert the second bounded cycle returned its first successful SSE body."""
    assert llm_retry_ctx.error is None
    assert llm_retry_ctx.result == SUCCESS_RESPONSE


@then("the retry scenario terminates with a bounded exhaustion error")
def then_retry_exhausted(llm_retry_ctx):
    """Assert terminal exit retains the bounded-cycle diagnostic details."""
    assert isinstance(llm_retry_ctx.error, LLMRetryExhaustedError)
    assert llm_retry_ctx.error.attempts == MAX_ATTEMPTS
    assert llm_retry_ctx.result is None


@then("the retry scenario reaches its configured absolute request bound")
def then_retry_reaches_absolute_bound(llm_retry_ctx):
    """Assert the injected finite policy terminates at its exact request bound."""
    assert isinstance(llm_retry_ctx.error, LLMRetryExhaustedError)
    assert llm_retry_ctx.error.attempts == BDD_MAX_TOTAL_ATTEMPTS
    assert llm_retry_ctx.error.manual_cycle_count == BDD_MAX_MANUAL_RETRY_CYCLES
    assert llm_retry_ctx.state()["total_requests"] == BDD_MAX_TOTAL_ATTEMPTS


@then("every bounded retry request body is identical")
def then_all_bounded_retry_bodies_are_identical(llm_retry_ctx):
    """Prove every bounded cycle resends the unchanged request body."""
    bodies = llm_retry_ctx.request_bodies()
    assert len(bodies) == BDD_MAX_TOTAL_ATTEMPTS
    assert all(body == bodies[0] for body in bodies[1:])


@then("the retry scenario sent exactly 19 completion requests")
def then_retry_sent_nineteen_requests(llm_retry_ctx):
    """Assert one full cycle plus one request in the manual retry cycle."""
    state = llm_retry_ctx.state()
    assert state["total_requests"] == MAX_ATTEMPTS + 1, state
    assert len(state["request_bodies"]) == MAX_ATTEMPTS + 1, state
    assert all(record["parsed"] for record in state["request_bodies"]), state


@then("the retry scenario sent exactly 18 completion requests")
def then_retry_sent_eighteen_requests(llm_retry_ctx):
    """Assert terminal handling does not add a provider request."""
    state = llm_retry_ctx.state()
    assert state["total_requests"] == MAX_ATTEMPTS, state
    assert len(state["request_bodies"]) == MAX_ATTEMPTS, state
    assert all(record["parsed"] for record in state["request_bodies"]), state


@then("every retry request body is identical")
def then_retry_request_bodies_are_identical(llm_retry_ctx):
    """Prove Retry resends the same messages and request options in one chat."""
    bodies = llm_retry_ctx.request_bodies()
    assert len(bodies) == MAX_ATTEMPTS + 1
    assert all(body == bodies[0] for body in bodies[1:])
    assert bodies[0]["messages"][-1] == {
        "role": "user",
        "content": "original request",
    }


@then("the invalid retry choice issued no provider request")
def then_invalid_retry_choice_did_not_request(llm_retry_ctx):
    """Assert menu re-prompting is local and leaves request cardinality unchanged."""
    assert llm_retry_ctx.input_script is not None
    assert len(llm_retry_ctx.input_script.prompts) == 2
    assert llm_retry_ctx.input_script.prompts[0] == llm_retry_ctx.input_script.prompts[1]
    assert llm_retry_ctx.state()["total_requests"] == MAX_ATTEMPTS + 1


@then("the Back scenario ran the old and fresh Agent turns exactly once each")
def then_back_runs_two_distinct_turns(llm_retry_ctx):
    """Assert Back, unlike Retry, re-enters the Agent only for fresh input."""
    assert llm_retry_ctx.error is None
    assert llm_retry_ctx.result == SUCCESS_RESPONSE
    assert llm_retry_ctx.agent is not None
    assert llm_retry_ctx.agent.run_messages == ["old request", "fresh request"]


@then("the Back scenario ignored blank and formatting-empty fresh input")
def then_back_ignores_empty_fresh_input(llm_retry_ctx):
    """Assert only a non-empty formatted message starts the next Agent turn."""
    assert llm_retry_ctx.back_input_calls == 3
    assert llm_retry_ctx.agent is not None
    assert llm_retry_ctx.agent.run_messages == ["old request", "fresh request"]


@then("the Back scenario sent 18 old requests followed by one fresh request")
def then_back_wire_requests_change_only_after_fresh_input(llm_retry_ctx):
    """Prove Back never resends the old request after its control decision."""
    bodies = llm_retry_ctx.request_bodies()
    assert len(bodies) == MAX_ATTEMPTS + 1
    old_bodies = bodies[:MAX_ATTEMPTS]
    assert all(body == old_bodies[0] for body in old_bodies[1:])
    assert all(body["messages"][-1]["content"] == "old request" for body in old_bodies)
    assert bodies[MAX_ATTEMPTS]["messages"][-1] == {
        "role": "user",
        "content": "fresh request",
    }


@then("the invalid Back choice issued no provider request")
def then_invalid_back_choice_did_not_request(llm_retry_ctx):
    """Assert invalid and Back decisions occur after exactly one provider cycle."""
    assert llm_retry_ctx.input_script is not None
    assert len(llm_retry_ctx.input_script.prompts) == 2
    assert llm_retry_ctx.input_script.prompts[0] == llm_retry_ctx.input_script.prompts[1]
    assert llm_retry_ctx.state()["total_requests"] == MAX_ATTEMPTS + 1


@then("the continuous exhaustion menu includes Back")
def then_continuous_menu_includes_back(llm_retry_ctx):
    """Assert continuous interactive chat exposes Retry, Back, and Exit."""
    assert llm_retry_ctx.input_script is not None
    assert len(llm_retry_ctx.input_script.prompts) == 1
    prompt = llm_retry_ctx.input_script.prompts[0]
    assert "2. Back to chat" in prompt
    assert "3. Exit" in prompt


@then("the finite exhaustion menu omits Back")
def then_finite_menu_omits_back(llm_retry_ctx):
    """Assert finite execution offers only Retry and Exit."""
    assert llm_retry_ctx.input_script is not None
    assert len(llm_retry_ctx.input_script.prompts) == 1
    prompt = llm_retry_ctx.input_script.prompts[0]
    assert "Back to chat" not in prompt
    assert "2. Exit" in prompt


@then("no retry exhaustion prompt was attempted")
def then_no_retry_prompt_was_attempted(llm_retry_ctx):
    """Assert unavailable input fails closed instead of reading another source."""
    assert llm_retry_ctx.input_script is None
