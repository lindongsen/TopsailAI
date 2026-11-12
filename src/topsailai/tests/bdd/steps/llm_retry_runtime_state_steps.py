"""BDD steps for LLM retry Runtime Data over real HTTP/SSE."""

import pytest
from pytest_bdd import given, parsers, then, when

from topsailai.ai_base.exception import LLMRetryExhaustedError
from tests.bdd.llm_retry_runtime_state_harness import (
    MAX_ATTEMPTS,
    SUCCESS_RESPONSE,
    RetryRuntimeStateScenario,
)


@pytest.fixture
def retry_runtime_ctx(monkeypatch):
    """Yield one isolated scenario and close its exact resources."""
    context = RetryRuntimeStateScenario(monkeypatch)
    yield context
    context.close()


@given("an Agent-owned request with three SSE failures before a held success")
def given_three_failures(retry_runtime_ctx):
    """Script activation at the approved threshold and hold attempt four."""
    retry_runtime_ctx.start(3, hold_success=True)
    retry_runtime_ctx.run_async(4)


@given("an Agent-owned request with five SSE failures before a held success")
def given_five_failures(retry_runtime_ctx):
    """Script activation plus two updates and hold attempt six."""
    retry_runtime_ctx.start(5, hold_success=True)
    retry_runtime_ctx.run_async(6)


@given("an Agent-owned request with two SSE failures before success")
def given_two_failures(retry_runtime_ctx):
    """Script success before the Runtime Data threshold is reached."""
    retry_runtime_ctx.start(2)


@given("an Agent-owned request that exhausts all automatic SSE retries")
def given_exhaustion(retry_runtime_ctx):
    """Script provider errors for the complete automatic retry bound."""
    retry_runtime_ctx.start(MAX_ATTEMPTS)


@given("a direct request with three SSE failures before success")
def given_direct_request(retry_runtime_ctx):
    """Script retries without exposing any current Agent Runtime."""
    retry_runtime_ctx.use_agent = False
    retry_runtime_ctx.start(3)


@when("the request reaches the held successful attempt")
def when_request_held(retry_runtime_ctx):
    """The Given synchronization already holds the exact provider attempt."""
    assert retry_runtime_ctx.request_thread is not None
    assert retry_runtime_ctx.request_thread.is_alive()


@when("the held successful attempt is released")
def when_release_success(retry_runtime_ctx):
    """Allow the provider to respond and wait for request settlement."""
    retry_runtime_ctx.release_and_join()


@when("the retry runtime request completes")
def when_request_completes(retry_runtime_ctx):
    """Run the production request synchronously through the real provider."""
    retry_runtime_ctx.run()


@then(parsers.parse("one retry runtime state is active with failed count {count:d}"))
def then_active_count(retry_runtime_ctx, count):
    """Verify one active state contains the current cumulative failure count."""
    states = retry_runtime_ctx.store.snapshot()
    assert len(states) == 1
    state = states[0]
    assert state.value["failed_attempts"] == count
    assert state.value["next_retry_number"] == count + 1
    assert state.value["threshold"] == 3
    retry_runtime_ctx.assert_no_sensitive_runtime_content()


@then("its revision is greater than one")
def then_revision_updated(retry_runtime_ctx):
    """Verify later failures updated rather than duplicated the state."""
    state = retry_runtime_ctx.active_retry_state()
    assert state is not None
    assert state.revision > 1


@then("provider messages contain no runtime state data")
def then_messages_unchanged(retry_runtime_ctx):
    """Verify observability remains outside the provider message payload."""
    retry_runtime_ctx.assert_provider_messages_unchanged()


@then("the request succeeds with no active retry state")
def then_success_settled(retry_runtime_ctx):
    """Verify request success and immediate active-state removal."""
    assert retry_runtime_ctx.error is None
    assert retry_runtime_ctx.result == SUCCESS_RESPONSE
    assert retry_runtime_ctx.store.snapshot() == ()


@then("runtime history records one recovered retry state")
def then_recovered_history(retry_runtime_ctx):
    """Verify one bounded recovered record retains only safe metadata."""
    history = retry_runtime_ctx.retry_history()
    assert len(history) == 1
    assert history[0].outcome == "recovered"
    assert history[0].value["failed_attempts"] == 3
    retry_runtime_ctx.assert_no_sensitive_runtime_content()


@then("no retry runtime state or history exists")
def then_below_threshold_empty(retry_runtime_ctx):
    """Verify below-threshold retries produce neither active nor settled data."""
    assert retry_runtime_ctx.error is None
    assert retry_runtime_ctx.result == SUCCESS_RESPONSE
    assert retry_runtime_ctx.store.snapshot() == ()
    assert retry_runtime_ctx.retry_history() == ()
    retry_runtime_ctx.assert_provider_messages_unchanged()


@then("retry exhaustion leaves no active state")
def then_exhausted_settled(retry_runtime_ctx):
    """Verify existing bounded exhaustion behavior and state removal."""
    assert isinstance(retry_runtime_ctx.error, LLMRetryExhaustedError)
    assert retry_runtime_ctx.error.attempts == MAX_ATTEMPTS
    assert retry_runtime_ctx.result is None
    assert retry_runtime_ctx.store.snapshot() == ()


@then("runtime history records one failed retry state")
def then_failed_history(retry_runtime_ctx):
    """Verify exhaustion settles one failed record at the final count."""
    history = retry_runtime_ctx.retry_history()
    assert len(history) == 1
    assert history[0].outcome == "failed"
    assert history[0].value["failed_attempts"] == MAX_ATTEMPTS
    retry_runtime_ctx.assert_no_sensitive_runtime_content()
    retry_runtime_ctx.assert_provider_messages_unchanged()


@then("the direct request succeeds without Runtime Data publication")
def then_direct_success(retry_runtime_ctx):
    """Verify the no-Agent path preserves request result and has no Store data."""
    assert retry_runtime_ctx.error is None
    assert retry_runtime_ctx.result == SUCCESS_RESPONSE
    assert retry_runtime_ctx.store.snapshot() == ()
    assert retry_runtime_ctx.retry_history() == ()
    assert retry_runtime_ctx.provider_state()["total_requests"] == 4
