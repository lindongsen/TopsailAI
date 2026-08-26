"""Step definitions for TokenStat observability behavior."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, then, when


TOKENSTAT_FIELDS = {
    "current_tokens",
    "cached_tokens",
    "msg_count",
    "current_text_len",
    "total_cached_tokens",
    "total_text_len",
    "total_tokens",
    "first_byte_avg_sec",
    "first_byte_max_sec",
    "first_byte_min_sec",
}

TOKENSTAT_INTEGER_FIELDS = {
    "current_tokens",
    "cached_tokens",
    "msg_count",
    "current_text_len",
    "total_cached_tokens",
    "total_text_len",
    "total_tokens",
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
