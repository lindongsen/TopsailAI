"""Step definitions for cached-token behavior through the in-process harness."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, then, when

from tests.bdd.cached_tokens_harness import CachedTokensHarness


@pytest.fixture
def cached_tokens_context(monkeypatch) -> dict[str, Any]:
    """Provide one isolated server and driver per BDD scenario."""
    harness = CachedTokensHarness(monkeypatch)
    context = {"harness": harness, "messages": harness.stable_messages()}
    try:
        yield context
    finally:
        harness.close()


@given("a TopsailAI environment connected to the LLM mock server")
def connected_environment(cached_tokens_context: dict[str, Any]) -> None:
    """Confirm that the scenario owns a running mock-backed driver."""
    assert cached_tokens_context["harness"].server_thread.is_alive()


@given("a conversation whose leading messages form a stable prefix")
def stable_prefix(cached_tokens_context: dict[str, Any]) -> None:
    """Prime the mock cache with the scenario's stable conversation."""
    harness = cached_tokens_context["harness"]
    harness.request(cached_tokens_context["messages"])


@given("a conversation with a previously cached leading prefix")
def previously_cached_prefix(cached_tokens_context: dict[str, Any]) -> None:
    """Prime the mock cache before changing the leading message."""
    stable_prefix(cached_tokens_context)


@given("a conversation that has accumulated measurable cached tokens")
def measurable_cached_tokens(cached_tokens_context: dict[str, Any]) -> None:
    """Issue two equal requests so TokenStat contains a measured cache hit."""
    stable_prefix(cached_tokens_context)
    harness = cached_tokens_context["harness"]
    harness.request(cached_tokens_context["messages"])
    assert harness.cached_tokens and harness.cached_tokens > 0


@given("summarization has just marked the cache state as unknown")
def summarized_unknown_state(cached_tokens_context: dict[str, Any]) -> None:
    """Establish a measured hit and run the real context rebuild path."""
    measurable_cached_tokens(cached_tokens_context)
    harness = cached_tokens_context["harness"]
    assert harness.summarize() == "Mock summary"
    assert harness.cached_tokens is None


@when("the same leading prefix is sent again")
def resend_same_prefix(cached_tokens_context: dict[str, Any]) -> None:
    """Send the unchanged conversation through the TopsailAI client."""
    harness = cached_tokens_context["harness"]
    harness.request(cached_tokens_context["messages"])


@when("the leading message differs from the cached prefix")
def change_leading_message(cached_tokens_context: dict[str, Any]) -> None:
    """Send a conversation whose first transmitted message differs."""
    messages = list(cached_tokens_context["messages"])
    messages[0] = {
        "role": "system",
        "content": "different cache behavior system prompt",
    }
    cached_tokens_context["harness"].request(messages)


@when("summarization rebuilds the Agent2LLM messages")
def rebuild_with_summary(cached_tokens_context: dict[str, Any]) -> None:
    """Invoke the real Agent2LLM rebuild with deterministic summary generation."""
    answer = cached_tokens_context["harness"].summarize()
    assert answer == "Mock summary"


@when("a new request completes against the mock server")
def request_after_summary(cached_tokens_context: dict[str, Any]) -> None:
    """Send the rebuilt context so usage is measured again by the mock server."""
    harness = cached_tokens_context["harness"]
    harness.request(harness.messages)


@then("the response reports a non-zero cached token count")
def reports_cache_hit(cached_tokens_context: dict[str, Any]) -> None:
    """Require a server-measured cache hit to reach TokenStat."""
    assert cached_tokens_context["harness"].cached_tokens > 0


@then("the response reports zero cached tokens")
def reports_cache_miss(cached_tokens_context: dict[str, Any]) -> None:
    """Require a genuine server miss to remain distinguishable from unknown."""
    assert cached_tokens_context["harness"].cached_tokens == 0


@then("the cached-token statistic is reported as unknown rather than zero")
def reports_unknown(cached_tokens_context: dict[str, Any]) -> None:
    """Require local context rebuilding to mark cache usage as not measured."""
    assert cached_tokens_context["harness"].cached_tokens is None


@then("the uncached-token statistic is not reported as a negative number")
def uncached_is_safe(cached_tokens_context: dict[str, Any]) -> None:
    """Require unknown or non-negative uncached-token reporting."""
    uncached_tokens = cached_tokens_context["harness"].uncached_tokens
    assert uncached_tokens is None or uncached_tokens >= 0


@then("the measured uncached-token statistic is non-negative")
def measured_uncached_is_safe(cached_tokens_context: dict[str, Any]) -> None:
    """Require a measured uncached-token statistic to be present and non-negative."""
    uncached_tokens = cached_tokens_context["harness"].uncached_tokens
    assert uncached_tokens is not None
    assert uncached_tokens >= 0


@then("the cached-token statistic reflects the new request's real hit or miss")
def reflects_new_usage(cached_tokens_context: dict[str, Any]) -> None:
    """Require TokenStat to equal the mock's usage value after remeasurement."""
    harness = cached_tokens_context["harness"]
    assert harness.cached_tokens is not None
    assert harness.cached_tokens == harness.response_cached_tokens()


@given("a shared session whose Provider omits cache usage details")
def session_without_cache_details(cached_tokens_context: dict[str, Any]) -> None:
    """Create a real session and configure the mock to omit cache details."""
    harness = cached_tokens_context["harness"]
    harness.enable_session("bdd-cache-unknown-session")
    harness.set_cache_usage_reporting(False)


@given("a shared session whose Provider reports cache usage details")
def session_with_cache_details(cached_tokens_context: dict[str, Any]) -> None:
    """Create a real session using the mock Provider's default cache reporting."""
    cached_tokens_context["harness"].enable_session("bdd-cache-measured-session")


@when("a request is persisted from the LLM mock server")
def persist_unknown_cache_request(cached_tokens_context: dict[str, Any]) -> None:
    """Persist one request whose Provider cache usage is unknown."""
    harness = cached_tokens_context["harness"]
    harness.request_with_session(cached_tokens_context["messages"])


@when("a first request is persisted from the LLM mock server")
def persist_explicit_zero_request(cached_tokens_context: dict[str, Any]) -> None:
    """Persist a first request whose reported cache usage is explicitly zero."""
    harness = cached_tokens_context["harness"]
    harness.request_with_session(cached_tokens_context["messages"])


@when("the same request is persisted twice from the LLM mock server")
def persist_positive_cache_request(cached_tokens_context: dict[str, Any]) -> None:
    """Persist one cache miss followed by a deterministic full-prefix hit."""
    harness = cached_tokens_context["harness"]
    messages = cached_tokens_context["messages"]
    harness.request_with_session(messages)
    harness.request_with_session(messages)


def _assert_known_usage_matches_responses(context: dict[str, Any]) -> None:
    """Require persisted known usage to equal all completed Provider responses."""
    harness = context["harness"]
    usage = harness.session_token_usage()
    assert usage is not None
    state = harness.request_state()
    request_count = state["total_requests"]
    expected_prompt_tokens = sum(
        request["prompt_tokens"] for request in state["requests"]
    )
    expected_completion_tokens = request_count * harness.response_completion_tokens()
    assert usage["prompt_tokens"] == expected_prompt_tokens
    assert usage["completion_tokens"] == expected_completion_tokens
    assert usage["total_tokens"] == expected_prompt_tokens + expected_completion_tokens


@then("request cache usage is unknown while known session usage is accumulated")
def unknown_request_persists_known_usage(cached_tokens_context: dict[str, Any]) -> None:
    """Keep request cache unknown while persisting prompt and completion usage."""
    harness = cached_tokens_context["harness"]
    assert harness.cached_tokens is None
    usage = harness.session_token_usage()
    assert usage is not None
    assert usage["cached_prompt_tokens"] == 0
    _assert_known_usage_matches_responses(cached_tokens_context)


@then("request cache usage is explicitly zero while known session usage is accumulated")
def zero_request_persists_known_usage(cached_tokens_context: dict[str, Any]) -> None:
    """Keep an explicit Provider cache miss distinct from unknown."""
    harness = cached_tokens_context["harness"]
    assert harness.cached_tokens == 0
    usage = harness.session_token_usage()
    assert usage is not None
    assert usage["cached_prompt_tokens"] == 0
    _assert_known_usage_matches_responses(cached_tokens_context)


@then("positive request cache usage is added to the session cache total")
def positive_request_increments_cache_total(cached_tokens_context: dict[str, Any]) -> None:
    """Persist the positive cache hit reported for the repeated request."""
    harness = cached_tokens_context["harness"]
    assert harness.cached_tokens is not None
    assert harness.cached_tokens > 0
    usage = harness.session_token_usage()
    assert usage is not None
    assert usage["cached_prompt_tokens"] == harness.cached_tokens
    _assert_known_usage_matches_responses(cached_tokens_context)


@then("the cache persistence request crossed the real HTTP boundary")
def one_persistence_http_request(cached_tokens_context: dict[str, Any]) -> None:
    """Verify one captured HTTP request and its transmitted messages."""
    harness = cached_tokens_context["harness"]
    state = harness.request_state()
    assert state["total_requests"] == 1
    assert len(state["request_bodies"]) == 1
    assert state["request_bodies"][0]["body"]["messages"] == cached_tokens_context["messages"]


@then("both cache persistence requests crossed the real HTTP boundary")
def two_persistence_http_requests(cached_tokens_context: dict[str, Any]) -> None:
    """Verify both repeated requests crossed HTTP with unchanged messages."""
    harness = cached_tokens_context["harness"]
    state = harness.request_state()
    assert state["total_requests"] == 2
    assert len(state["request_bodies"]) == 2
    assert all(
        record["body"]["messages"] == cached_tokens_context["messages"]
        for record in state["request_bodies"]
    )
