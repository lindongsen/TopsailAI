"""BDD steps for bounded null-response recovery over real HTTP/SSE."""

import pytest
from pytest_bdd import given, parsers, then, when

from topsailai.ai_base.exception import LLMRetryExhaustedError
from tests.bdd.null_response_recovery_harness import (
    DEFAULT_RECOVERY_MESSAGE,
    MAX_ATTEMPTS,
    SUCCESS_RESPONSE,
    NullResponseRecoveryScenario,
)


@pytest.fixture
def null_recovery_ctx(monkeypatch):
    """Yield one isolated real-HTTP scenario and stop its exact resources."""
    context = NullResponseRecoveryScenario(monkeypatch)
    yield context
    context.close()


@given("a null-response recovery request with repeated blank SSE responses before success")
def given_continuous_streak(null_recovery_ctx):
    """Script one long continuous blank-response streak followed by success."""
    null_recovery_ctx.script_continuous_streak()


@given(
    "a null-response recovery request with two blank streaks separated by "
    "another provider error"
)
def given_separate_streaks(null_recovery_ctx):
    """Script two qualifying streaks inside one production chat request."""
    null_recovery_ctx.script_separate_streaks()


@given("a null-response recovery request with recovery disabled")
def given_disabled(null_recovery_ctx):
    """Disable only recovery injection while retaining the retry path."""
    null_recovery_ctx.script_disabled()


@given(parsers.parse('a null-response recovery request configured with "{configured}"'))
def given_configured_message(null_recovery_ctx, configured):
    """Configure custom or blank recovery content for this request."""
    configured_values = {"<empty>": "", "<whitespace>": "   "}
    value = configured_values.get(configured, configured)
    null_recovery_ctx.script_configured(value)


@given("a null-response recovery request whose blank SSE responses exhaust retries")
def given_exhaustion(null_recovery_ctx):
    """Script blank responses through the complete automatic retry bound."""
    null_recovery_ctx.script_exhaustion()


@when("the null-response recovery request is sent")
def when_request_sent(null_recovery_ctx):
    """Send the caller-owned conversation through the real provider boundary."""
    null_recovery_ctx.run()


@then("requests before the threshold contain no temporary recovery message")
def then_pre_threshold_unchanged(null_recovery_ctx):
    """Verify the first three provider requests contain only caller content."""
    requests = null_recovery_ctx.request_messages()
    assert len(requests) == 6
    assert all(request == null_recovery_ctx.initial_messages for request in requests[:3])


@then("every later retry contains exactly one temporary recovery message")
def then_later_retries_bounded(null_recovery_ctx):
    """Verify one long streak never appends a second temporary message."""
    requests = null_recovery_ctx.request_messages()
    assert all(
        len(request) == len(null_recovery_ctx.initial_messages) + 1
        and null_recovery_ctx.temporary_message_count(request) == 1
        for request in requests[3:]
    )


@then("the second blank streak does not append another recovery message")
def then_second_streak_bounded(null_recovery_ctx):
    """Verify a non-null error cannot re-arm duplicate injection."""
    requests = null_recovery_ctx.request_messages()
    assert len(requests) == 8
    assert all(
        len(request) == len(null_recovery_ctx.initial_messages) + 1
        and null_recovery_ctx.temporary_message_count(request) == 1
        for request in requests[3:]
    )


@then("no retry contains a temporary recovery message")
def then_disabled_unchanged(null_recovery_ctx):
    """Verify disabling recovery preserves every provider request body."""
    requests = null_recovery_ctx.request_messages()
    assert len(requests) == 5
    assert all(request == null_recovery_ctx.initial_messages for request in requests)


@then(parsers.parse('every recovered retry contains exactly one "{expected}" message'))
def then_configured_message_bounded(null_recovery_ctx, expected):
    """Verify custom and fallback content appear exactly once after threshold."""
    requests = null_recovery_ctx.request_messages()
    assert len(requests) == 5
    assert all(request == null_recovery_ctx.initial_messages for request in requests[:3])
    assert all(
        len(request) == len(null_recovery_ctx.initial_messages) + 1
        and null_recovery_ctx.temporary_message_count(request, expected) == 1
        for request in requests[3:]
    )


@then("the request ends with bounded retry exhaustion")
def then_exhausted(null_recovery_ctx):
    """Verify blank responses retain the existing bounded failure contract."""
    assert isinstance(null_recovery_ctx.error, LLMRetryExhaustedError)
    assert null_recovery_ctx.error.attempts == MAX_ATTEMPTS
    assert null_recovery_ctx.result is None


@then("every post-threshold exhausted retry contains exactly one temporary recovery message")
def then_exhausted_retries_bounded(null_recovery_ctx):
    """Verify all 15 later requests retain one stable temporary suffix."""
    requests = null_recovery_ctx.request_messages()
    assert len(requests) == MAX_ATTEMPTS
    assert all(request == null_recovery_ctx.initial_messages for request in requests[:3])
    assert all(
        len(request) == len(null_recovery_ctx.initial_messages) + 1
        and null_recovery_ctx.temporary_message_count(request) == 1
        for request in requests[3:]
    )


@then("the successful request restores the caller-owned conversation")
def then_success_cleanup(null_recovery_ctx):
    """Verify success removes only the mechanism-owned temporary object."""
    assert null_recovery_ctx.error is None
    assert null_recovery_ctx.result == SUCCESS_RESPONSE
    assert null_recovery_ctx.messages == null_recovery_ctx.initial_messages


@then("the exhausted request restores the caller-owned conversation")
def then_exhaustion_cleanup(null_recovery_ctx):
    """Verify exceptional exit also restores the exact caller content."""
    assert null_recovery_ctx.messages == null_recovery_ctx.initial_messages
    assert sum(
        message == {"role": "user", "content": DEFAULT_RECOVERY_MESSAGE}
        for message in null_recovery_ctx.messages
    ) == 1
