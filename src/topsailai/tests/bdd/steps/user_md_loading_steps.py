"""Gherkin steps for optional USER.md startup context loading."""

from pathlib import Path

import pytest
from pytest_bdd import given, then, when

from tests.bdd.user_md_loading_harness import EXPLICIT_MARKER, USER_MARKER, UserMdLoadingScenario


@pytest.fixture
def user_md_loading_ctx(bdd_tmp_path: Path):
    """Hold one scenario-owned real HTTP harness."""
    context = {"scenario": None}
    yield context
    if context["scenario"] is not None:
        context["scenario"].close()


@given("a USER.md startup context scenario with loading enabled")
def given_loading_enabled(user_md_loading_ctx, monkeypatch, bdd_tmp_path):
    """Configure default-equivalent enabled USER.md loading."""
    user_md_loading_ctx["scenario"] = UserMdLoadingScenario(monkeypatch, bdd_tmp_path, True)


@given("a USER.md startup context scenario with loading disabled")
def given_loading_disabled(user_md_loading_ctx, monkeypatch, bdd_tmp_path):
    """Configure disabled automatic USER.md loading."""
    user_md_loading_ctx["scenario"] = UserMdLoadingScenario(monkeypatch, bdd_tmp_path, False)


@when("the agent sends one real LLM request")
def when_agent_sends_request(user_md_loading_ctx):
    """Drive the production direct-chat request path."""
    user_md_loading_ctx["scenario"].send()


@then("the USER.md mock server received exactly 1 completion request")
def then_one_request(user_md_loading_ctx):
    """Assert one captured provider request."""
    state = user_md_loading_ctx["scenario"].state()
    assert state["total_requests"] == 1
    assert len(state["request_bodies"]) == 1
    assert state["request_bodies"][0]["parsed"] is True


@then("the USER.md mock server received exactly 2 completion requests")
def then_two_requests(user_md_loading_ctx):
    """Assert both real provider requests completed successfully."""
    state = user_md_loading_ctx["scenario"].state()
    assert state["total_requests"] == 2
    assert len(state["request_bodies"]) == 2
    assert all(item["parsed"] is True for item in state["request_bodies"])


@when("the agent sends a second real LLM request")
def when_agent_sends_second_request(user_md_loading_ctx):
    """Drive a second real request in the same process."""
    user_md_loading_ctx["scenario"].send_second()


@then("the USER.md load switch is latched to 0")
def then_switch_is_latched(user_md_loading_ctx):
    """Assert the first startup-context attempt latched the process switch."""
    assert __import__("os").environ.get("TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED") == "0"


def _request_text(user_md_loading_ctx) -> str:
    """Return serialized captured request data for marker assertions."""
    state = user_md_loading_ctx["scenario"].state()
    return str(state["request_bodies"][0]["body"])


@then("the captured request contains the USER.md marker")
def then_contains_user_marker(user_md_loading_ctx):
    """Assert human factual context crossed the provider boundary."""
    assert USER_MARKER in _request_text(user_md_loading_ctx)


@then("the captured request omits the USER.md marker")
def then_omits_user_marker(user_md_loading_ctx):
    """Assert disabled loading omits the automatic source."""
    assert USER_MARKER not in _request_text(user_md_loading_ctx)


@then("the captured request contains the explicit context marker")
def then_contains_explicit_marker(user_md_loading_ctx):
    """Assert the independent explicit context source remains active."""
    assert EXPLICIT_MARKER in _request_text(user_md_loading_ctx)


@then("the second captured request omits the USER.md marker")
def then_second_omits_user_marker(user_md_loading_ctx):
    """Assert the process latch blocks USER.md on the second request."""
    state = user_md_loading_ctx["scenario"].state()
    assert USER_MARKER not in str(state["request_bodies"][1]["body"])


@then("the second captured request contains the explicit context marker")
def then_second_contains_explicit_marker(user_md_loading_ctx):
    """Assert refreshed explicit context remains available to a new instance."""
    state = user_md_loading_ctx["scenario"].state()
    assert EXPLICIT_MARKER + "_SECOND" in str(state["request_bodies"][1]["body"])
