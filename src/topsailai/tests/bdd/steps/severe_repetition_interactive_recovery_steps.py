"""Steps for severe-repetition interactive recovery behavior."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.severe_repetition_interactive_recovery_harness import (
    SevereRepetitionScenario,
)


@pytest.fixture
def severe_repetition_ctx(monkeypatch):
    """Provide one isolated real-transport scenario and close its resources."""
    scenario = SevereRepetitionScenario(monkeypatch)
    yield scenario
    scenario.close()


@given(
    "an LLM server returns two severely repetitive responses and then a fresh response"
)
def given_repetition_then_fresh(severe_repetition_ctx):
    """Script two severe responses and one usable completion."""
    severe_repetition_ctx.script_interactive_recovery()


@given("an LLM server returns two severely repetitive responses")
def given_repetition_only(severe_repetition_ctx):
    """Script the minimum responses required for the specialized verdict."""
    severe_repetition_ctx.script_non_interactive_failure()


@when("the interactive session receives a fresh message after the repetition verdict")
def when_interactive_session_recovers(severe_repetition_ctx):
    """Drive the interactive User2Agent loop through the failed and fresh turns."""
    severe_repetition_ctx.run_interactive_recovery()


@when("severe repetition occurs without an interactive user")
def when_non_interactive_session_fails(severe_repetition_ctx):
    """Drive the same verdict through the non-interactive boundary."""
    severe_repetition_ctx.run_non_interactive_failure()


@then("the severe repetition session remains alive for the fresh turn")
def then_interactive_session_remains_alive(severe_repetition_ctx):
    """The fresh turn must complete through the same AgentChat loop."""
    assert severe_repetition_ctx.error is None
    assert severe_repetition_ctx.result == "fresh provider response"
    assert severe_repetition_ctx.agent.run_messages == [
        "old request",
        "fresh request",
    ]
    assert severe_repetition_ctx.fresh_input_calls == 1


@then(
    "the severe repetition scenario sends two old requests followed by one fresh request"
)
def then_request_bodies_change_after_recovery(severe_repetition_ctx):
    """Provider evidence must show a new user message only on the fresh turn."""
    bodies = severe_repetition_ctx.request_bodies()
    assert len(bodies) == 3
    assert bodies[0] == bodies[1]
    assert bodies[0]["messages"][-1]["content"] == "old request"
    assert bodies[2]["messages"][-1]["content"] == "fresh request"


@then("the severe repetition verdict does not open the retry menu")
def then_no_retry_menu_is_opened(severe_repetition_ctx):
    """The specialized verdict must bypass the request retry menu."""
    assert severe_repetition_ctx.input_script.prompts == []


@then("the severe repetition failure hook runs exactly once")
def then_failure_hook_runs_once(severe_repetition_ctx):
    """The abandoned turn must be reported once before recovery."""
    assert severe_repetition_ctx.failure_hook_calls == 1


@then("the non-interactive severe repetition error escapes the turn loop")
def then_non_interactive_error_escapes(severe_repetition_ctx):
    """The non-interactive fail-fast contract must remain unchanged."""
    severe_repetition_ctx.assert_specialized_error()
    assert severe_repetition_ctx.result is None
    assert severe_repetition_ctx.agent.run_messages == ["old request"]


@then("the non-interactive severe repetition scenario sends exactly two requests")
def then_non_interactive_sends_two_requests(severe_repetition_ctx):
    """The specialized error must stop retries at its configured limit."""
    bodies = severe_repetition_ctx.request_bodies()
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
