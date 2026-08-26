"""Step definitions for session-context cache lifecycle behavior."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, then, when


@given("a TopsailAI session connected to the LLM mock server")
def connected_session(cached_tokens_context: dict[str, Any]) -> None:
    """Confirm that the shared in-process harness owns a running mock server."""
    assert cached_tokens_context["harness"].server_thread.is_alive()


@given("a session with a fully cached compressible context")
def fully_cached_context(cached_tokens_context: dict[str, Any]) -> None:
    """Prime an identical multi-message context and retain its full cache hit."""
    harness = cached_tokens_context["harness"]
    messages = cached_tokens_context["messages"]
    harness.request(messages)
    harness.request(messages)
    cached_tokens_context["before_cached_tokens"] = harness.cached_tokens
    cached_tokens_context["before_prompt_tokens"] = harness.response_prompt_tokens()
    cached_tokens_context["before_message_count"] = len(messages)
    assert harness.cached_tokens == harness.response_prompt_tokens()


@given("a session with measured cache usage and no compressible messages")
def no_compressible_context(cached_tokens_context: dict[str, Any]) -> None:
    """Prime a context containing only the preserved system and task prefix."""
    harness = cached_tokens_context["harness"]
    messages = harness.stable_messages()[:2]
    cached_tokens_context["messages"] = messages
    harness.request(messages)
    harness.request(messages)
    cached_tokens_context["before_cached_tokens"] = harness.cached_tokens
    cached_tokens_context["before_messages"] = list(harness.messages)
    assert harness.cached_tokens and harness.cached_tokens > 0


@when("the context is summarized and requested again")
def summarize_and_request(cached_tokens_context: dict[str, Any]) -> None:
    """Run the real summarize rebuild and then remeasure through HTTP."""
    harness = cached_tokens_context["harness"]
    assert harness.summarize() == "Mock summary"
    assert harness.cached_tokens is None
    assert harness.last_summary_message_count < cached_tokens_context["before_message_count"]
    harness.request(harness.messages)


@when("summarization is attempted for that session")
def attempt_unavailable_summary(cached_tokens_context: dict[str, Any]) -> None:
    """Attempt the real forced summarize path when every message is preserved."""
    harness = cached_tokens_context["harness"]
    cached_tokens_context["summary_result"] = harness.summarize()


@then("the achievable cached-token hit is lower than before compression")
def lower_cache_hit(cached_tokens_context: dict[str, Any]) -> None:
    """Require summary insertion to reduce the exact reusable message prefix."""
    harness = cached_tokens_context["harness"]
    assert harness.cached_tokens is not None
    assert harness.cached_tokens < cached_tokens_context["before_cached_tokens"]


@then("the post-compression cache usage matches the mock server result")
def matches_mock_result(cached_tokens_context: dict[str, Any]) -> None:
    """Require TokenStat and the mock HTTP response to expose the same usage."""
    harness = cached_tokens_context["harness"]
    cache_result = harness.last_cache_result()
    assert harness.cached_tokens == harness.response_cached_tokens()
    assert harness.cached_tokens == cache_result["cached_tokens"]
    assert 0 < cache_result["cached_messages"] < cache_result["message_count"]


@then("no session summarization occurs")
def no_summary_occurs(cached_tokens_context: dict[str, Any]) -> None:
    """Require the hard no-compressible-message guard to skip rebuilding."""
    harness = cached_tokens_context["harness"]
    assert cached_tokens_context["summary_result"] is None
    assert harness.last_summary_message_count is None
    assert harness.messages == cached_tokens_context["before_messages"]


@then("the cached-token statistic remains in its prior state")
def cache_state_unchanged(cached_tokens_context: dict[str, Any]) -> None:
    """Require a skipped summary to preserve the measured cache statistic."""
    assert (
        cached_tokens_context["harness"].cached_tokens
        == cached_tokens_context["before_cached_tokens"]
    )


@then("the uncached-token statistic remains non-negative")
def uncached_remains_safe(cached_tokens_context: dict[str, Any]) -> None:
    """Require measured lifecycle states never to expose negative uncached usage."""
    uncached_tokens = cached_tokens_context["harness"].uncached_tokens
    assert uncached_tokens is not None
    assert uncached_tokens >= 0
