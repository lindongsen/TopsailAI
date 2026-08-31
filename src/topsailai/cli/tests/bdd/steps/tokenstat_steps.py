"""Step definitions for TokenStat observability behavior."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, then, when


TOKENSTAT_FIELDS = {
    "current_tokens",
    "current_prompt_tokens",
    "current_completion_tokens",
    "current_total_tokens",
    "cached_tokens",
    "uncached_prompt_tokens",
    "msg_count",
    "current_text_len",
    "total_cached_tokens",
    "total_text_len",
    "total_tokens",
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_usage_tokens",
    "first_byte_avg_sec",
    "first_byte_max_sec",
    "first_byte_min_sec",
}

TOKENSTAT_INTEGER_FIELDS = {
    "current_tokens",
    "current_prompt_tokens",
    "current_completion_tokens",
    "current_total_tokens",
    "cached_tokens",
    "uncached_prompt_tokens",
    "msg_count",
    "current_text_len",
    "total_cached_tokens",
    "total_text_len",
    "total_tokens",
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_usage_tokens",
}


@given(
    "first-byte latency samples of 100.1234567, 200.9876543, and "
    "50.5555555 milliseconds"
)
def first_byte_samples(cached_tokens_context: dict[str, Any]) -> None:
    """Feed deterministic millisecond samples into the real TokenStat."""
    cached_tokens_context["harness"].feed_first_byte(
        [100.1234567, 200.9876543, 50.5555555]
    )


@given("a shared session for TokenStat accumulation")
def shared_session(cached_tokens_context: dict[str, Any]) -> None:
    """Create a real in-memory session for multiple TokenStat agents."""
    cached_tokens_context["harness"].enable_session("bdd-tokenstat-session")


@given("a TokenStat measurement of 20 tokens with 30 cached tokens")
def cached_tokens_exceed_measurement(cached_tokens_context: dict[str, Any]) -> None:
    """Set a defensive edge case where cache usage exceeds counted tokens."""
    stat = cached_tokens_context["harness"].model.tokenStat
    stat.current_count = 20
    stat.current_cached_tokens = 30


@when("the TokenStat snapshot is emitted")
def emit_snapshot(cached_tokens_context: dict[str, Any]) -> None:
    """Capture the dictionary from the actual TokenStat output path."""
    cached_tokens_context["snapshot"] = cached_tokens_context[
        "harness"
    ].emit_snapshot()


@when("the conversation is sent to the LLM mock server")
def send_conversation(cached_tokens_context: dict[str, Any]) -> None:
    """Send one request and retain the total-token delta for verification."""
    harness = cached_tokens_context["harness"]
    total_before = harness.model.tokenStat.total_count
    harness.request(cached_tokens_context["messages"])
    cached_tokens_context["response_prompt_tokens"] = harness.response_prompt_tokens()
    cached_tokens_context["total_token_delta"] = (
        harness.model.tokenStat.total_count - total_before
    )


@when("one AgentChat turn completes against the LLM mock server")
def run_one_shot_agent_chat(cached_tokens_context: dict[str, Any]) -> None:
    """Run the one-shot AgentChat path with a real mock-server request."""
    cached_tokens_context["harness"].run_one_shot_agent_chat()


@then("the one-shot answer is output once before one final session token summary")
def one_shot_answer_before_final_summary(
    cached_tokens_context: dict[str, Any],
) -> None:
    """Require the terminating turn to emit its summary after its answer."""
    assert cached_tokens_context[
        "harness"
    ].one_shot_answer_precedes_summary_once()


@when("one agent reports 120 tokens with 40 cached tokens")
def first_agent_delta(cached_tokens_context: dict[str, Any]) -> None:
    """Accumulate the first agent's current-request delta."""
    cached_tokens_context["harness"].report_session_delta(120, 40)


@when("another agent reports 80 tokens with 15 cached tokens")
def second_agent_delta(cached_tokens_context: dict[str, Any]) -> None:
    """Accumulate the second agent's current-request delta."""
    cached_tokens_context["harness"].report_session_delta(80, 15)


@then("the snapshot contains every TokenStat observability field")
def complete_snapshot(cached_tokens_context: dict[str, Any]) -> None:
    """Require the emitted snapshot to match the complete public field set."""
    assert set(cached_tokens_context["snapshot"]) == TOKENSTAT_FIELDS


@then("the snapshot token and text fields are integer measurements")
def integer_measurements(cached_tokens_context: dict[str, Any]) -> None:
    """Require token, cache, message, and text measurements to be integers."""
    snapshot = cached_tokens_context["snapshot"]
    for field in TOKENSTAT_INTEGER_FIELDS:
        assert isinstance(snapshot[field], int), field


@then("the empty first-byte fields are reported as unknown")
def empty_first_byte_unknown(cached_tokens_context: dict[str, Any]) -> None:
    """Require absent streaming samples to remain distinguishable from zero."""
    snapshot = cached_tokens_context["snapshot"]
    assert snapshot["first_byte_avg_sec"] is None
    assert snapshot["first_byte_max_sec"] is None
    assert snapshot["first_byte_min_sec"] is None


@then("the mock server receives exactly two non-streaming requests with the scenario message")
def non_streaming_request_body(cached_tokens_context: dict[str, Any]) -> None:
    """Require both real HTTP requests and their non-streaming scenario body."""
    state = cached_tokens_context["harness"].request_state()
    assert state["total_requests"] == 2, state
    assert len(state["request_bodies"]) == 2, state
    for record in state["request_bodies"]:
        body = record["body"]
        assert record["parsed"] is True, record
        assert body["stream"] is False, body
        assert body["messages"] == cached_tokens_context["messages"], body


@then("TokenStat current tokens equal the response prompt tokens")
def response_prompt_tokens_are_current(
    cached_tokens_context: dict[str, Any],
) -> None:
    """Require provider prompt usage to replace the local request estimate."""
    stat = cached_tokens_context["harness"].model.tokenStat
    assert stat.current_tokens == cached_tokens_context["response_prompt_tokens"]
    assert stat.current_count_source == "llm_response"


@then("TokenStat total tokens count the request only once")
def response_prompt_tokens_counted_once(
    cached_tokens_context: dict[str, Any],
) -> None:
    """Require total tokens to contain one authoritative request contribution."""
    assert cached_tokens_context["total_token_delta"] == cached_tokens_context[
        "response_prompt_tokens"
    ]


@then("TokenStat explicit current usage equals the response prompt and completion usage")
def explicit_non_streaming_usage(cached_tokens_context: dict[str, Any]) -> None:
    """Require explicit usage fields while legacy fields remain prompt-only."""
    harness = cached_tokens_context["harness"]
    stat = harness.model.tokenStat
    prompt_tokens = harness.response_prompt_tokens()
    completion_tokens = harness.response_completion_tokens()
    assert stat.current_tokens == prompt_tokens
    assert stat.current_prompt_tokens == prompt_tokens
    assert stat.current_completion_tokens == completion_tokens
    assert stat.current_total_tokens == prompt_tokens + completion_tokens
    assert stat.total_tokens == stat.total_prompt_tokens
    assert stat.total_usage_tokens == stat.total_prompt_tokens + stat.total_completion_tokens


@then("the non-streaming response is output before the token summary")
def non_streaming_response_before_summary(cached_tokens_context: dict[str, Any]) -> None:
    """Require production response dispatch to precede TokenStat display."""
    assert cached_tokens_context["harness"].response_precedes_token_summary()


@then(
    "first-byte latency is reported as 0.117 average, 0.201 maximum, and "
    "0.051 minimum seconds"
)
def rounded_first_byte_metrics(cached_tokens_context: dict[str, Any]) -> None:
    """Require millisecond conversion, aggregation, and three-decimal rounding."""
    snapshot = cached_tokens_context["snapshot"]
    assert snapshot["first_byte_avg_sec"] == 0.117
    assert snapshot["first_byte_max_sec"] == 0.201
    assert snapshot["first_byte_min_sec"] == 0.051
    assert all(
        isinstance(snapshot[field], float)
        for field in (
            "first_byte_avg_sec",
            "first_byte_max_sec",
            "first_byte_min_sec",
        )
    )


@then("the shared session totals are 200 tokens and 55 cached tokens")
def combined_session_totals(cached_tokens_context: dict[str, Any]) -> None:
    """Require shared storage to preserve both agents' accumulated deltas."""
    assert cached_tokens_context["harness"].session_token_totals() == (200, 55)
