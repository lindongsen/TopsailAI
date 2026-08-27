"""Step definitions for llm_mock_server streaming over real HTTP/SSE."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

import openai

from tests.bdd.streaming_mock_server_harness import StreamingMockServerHarness


@pytest.fixture
def streaming_mock_server_context(monkeypatch) -> dict[str, Any]:
    """Provide and reliably close one isolated HTTP integration harness."""
    context: dict[str, Any] = {"harness": None, "monkeypatch": monkeypatch}
    try:
        yield context
    finally:
        harness = context["harness"]
        if harness is not None:
            harness.close()


@given("a streaming LLM mock server with SSE chunks")
def streaming_server_ready(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Lazily create the harness so each scenario picks its own chunks."""
    if streaming_mock_server_context["harness"] is None:
        streaming_mock_server_context["harness"] = StreamingMockServerHarness(
            streaming_mock_server_context["monkeypatch"],
        )
    assert streaming_mock_server_context["harness"].server.server_port > 0


@given(parsers.parse("the SSE chunks are {chunks}"))
def configure_sse_chunks(
    streaming_mock_server_context: dict[str, Any],
    chunks: str,
) -> None:
    """Create the harness with the scenario-specific chunk list."""
    chunk_list = [part.strip().strip('"') for part in chunks.split(",")]
    existing = streaming_mock_server_context["harness"]
    if existing is not None:
        existing.close()
    streaming_mock_server_context["harness"] = StreamingMockServerHarness(
        streaming_mock_server_context["monkeypatch"],
        stream_chunks=tuple(chunk_list),
    )


@given("a streaming LLM mock server with streaming disabled")
def streaming_disabled_server(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Create the harness with streaming disabled (stream_chunks=None)."""
    existing = streaming_mock_server_context["harness"]
    if existing is not None:
        existing.close()
    streaming_mock_server_context["harness"] = StreamingMockServerHarness(
        streaming_mock_server_context["monkeypatch"],
        stream_chunks=None,
    )


@when("the streaming mock chat is executed")
def execute_streaming_chat(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Execute production chat through the official client and mock server."""
    streaming_mock_server_context["content"] = (
        streaming_mock_server_context["harness"].execute_streaming_chat()
    )


@when("the streaming mock chat is executed twice with the same prompt")
def execute_streaming_chat_twice_same_prompt(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Execute two identical streaming chats for prompt-cache reuse."""
    harness = streaming_mock_server_context["harness"]
    streaming_mock_server_context["first_content"] = harness.execute_streaming_chat()
    streaming_mock_server_context["content"] = harness.execute_streaming_chat()


@when("the streaming mock chat is executed directly without the retry loop")
def execute_streaming_chat_direct(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Call call_llm_model_by_stream directly to avoid chat() retry sleeps."""
    streaming_mock_server_context["harness"].execute_streaming_chat_direct()


@when("the streaming mock chat is executed twice with different prompts")
def execute_streaming_chat_twice_different_prompts(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Execute two streaming chats with distinct user prompts."""
    harness = streaming_mock_server_context["harness"]
    streaming_mock_server_context["content"] = harness.execute_streaming_chat()
    harness.messages = [{"role": "user", "content": "BDD streaming second prompt"}]
    harness.execute_streaming_chat()


@then(parsers.parse('the streamed content equals "{expected}"'))
def streamed_content_equals(
    streaming_mock_server_context: dict[str, Any],
    expected: str,
) -> None:
    """Require the production chain to return the exact concatenation."""
    assert streaming_mock_server_context["content"] == expected, (
        streaming_mock_server_context["content"]
    )


@then('the streamed content equals "done check" on the first call')
def streamed_first_call_content(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require the first call of scenario 4 to return the full content."""
    assert streaming_mock_server_context["content"] == "done check", (
        streaming_mock_server_context["content"]
    )


@then("the stream produced first-byte timing on the token stat")
def first_byte_timing_recorded(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require first-byte timing to be recorded synchronously."""
    token_stat = streaming_mock_server_context["harness"].model.tokenStat
    assert token_stat.first_byte_count >= 1, token_stat.first_byte_count


@then("the second server-side request reports cached tokens greater than zero")
def second_request_cached_tokens(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require the server-side prompt cache to report reuse on request two."""
    state = streaming_mock_server_context["harness"].get_state()
    requests = state["requests"]
    assert len(requests) == 2, requests
    assert requests[1]["cached_tokens"] > 0, requests[1]
    streaming_mock_server_context["server_cached_tokens"] = (
        requests[1]["cached_tokens"]
    )


@then("the token stat current cached tokens equal the server-reported value")
def token_stat_current_cached_tokens(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require TokenStat to mirror the server-reported cached tokens."""
    token_stat = streaming_mock_server_context["harness"].model.tokenStat
    assert token_stat.current_cached_tokens == (
        streaming_mock_server_context["server_cached_tokens"]
    ), token_stat.current_cached_tokens


@then("the token stat total cached tokens accumulate both requests")
def token_stat_total_cached_tokens(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require TokenStat to accumulate cached tokens across both calls."""
    token_stat = streaming_mock_server_context["harness"].model.tokenStat
    assert token_stat.total_cached_tokens >= (
        token_stat.current_cached_tokens
    ), token_stat.total_cached_tokens
    assert token_stat.total_cached_tokens > 0, token_stat.total_cached_tokens


@then(parsers.parse('a bad request error surfaces with "{message_part}"'))
def bad_request_error_surfaces(
    streaming_mock_server_context: dict[str, Any],
    message_part: str,
) -> None:
    """Require the 400 response to surface as openai.BadRequestError."""
    error = streaming_mock_server_context["harness"].error
    assert isinstance(error, openai.BadRequestError), repr(error)
    assert message_part in str(error), str(error)


@then("the mock server receives exactly one streaming-disabled request")
def exactly_one_streaming_disabled_request(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require the HTTP layer to observe exactly one POST request."""
    assert streaming_mock_server_context["harness"].request_count == 1, (
        streaming_mock_server_context["harness"].request_count
    )


@then("the mock server state reports exactly two total requests")
def exactly_two_total_requests(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require /debug/state to report exactly two recorded requests."""
    state = streaming_mock_server_context["harness"].get_state()
    assert state["total_requests"] == 2, state


@then("each recorded request has a positive prompt token count")
def each_request_positive_prompt_tokens(
    streaming_mock_server_context: dict[str, Any],
) -> None:
    """Require every recorded request to carry positive prompt tokens."""
    state = streaming_mock_server_context["harness"].get_state()
    for request in state["requests"]:
        assert request["prompt_tokens"] > 0, request
