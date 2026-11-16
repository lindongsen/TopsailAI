"""BDD steps for the sliding-window summary guard over real HTTP/SSE."""

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.summary_window_guard_harness import (
    ORDINARY_MODE,
    SUMMARY_MODE,
    SummaryWindowGuardScenario,
)


@pytest.fixture
def summary_window_ctx(monkeypatch):
    """Yield one isolated real-HTTP scenario and stop its exact resources."""
    context = SummaryWindowGuardScenario(monkeypatch)
    yield context
    context.close()


@given(
    parsers.parse(
        "a summary window guard with a window of {window_size:d} requests "
        "and a limit of {max_summaries:d}"
    )
)
def given_guard(summary_window_ctx, window_size, max_summaries):
    """Start the loopback provider and build the agent-owned guard."""
    summary_window_ctx.start(
        window_size=window_size, max_summaries=max_summaries
    )


@when("three summary requests are sent through the provider boundary")
def when_three_summaries(summary_window_ctx):
    """Send exactly three summary requests."""
    summary_window_ctx.run_three_summaries()


@when("four summary requests are sent through the provider boundary")
def when_four_summaries(summary_window_ctx):
    """Send four summary requests, where the fourth must terminate."""
    summary_window_ctx.run_four_summaries()


@when("twelve ordinary agent requests are sent through the provider boundary")
def when_ordinary(summary_window_ctx):
    """Send only ordinary agent requests."""
    summary_window_ctx.run_ordinary_only()


@when("summary requests are interleaved with ordinary agent requests")
def when_interleaved(summary_window_ctx):
    """Send summary traffic interleaved with ordinary agent requests."""
    summary_window_ctx.run_interleaved()


@when("six summary requests are sent through the provider boundary")
def when_six_summaries(summary_window_ctx):
    """Send summary traffic with the guard disabled."""
    summary_window_ctx.run_disabled()


@then("the summary window guard terminates the turn")
def then_terminates(summary_window_ctx):
    """Verify the guard raised the control-flow signal."""
    assert summary_window_ctx.error is not None, "the guard did not terminate"


@then("the summary window guard does not terminate the turn")
def then_does_not_terminate(summary_window_ctx):
    """Verify the guard stayed silent."""
    assert summary_window_ctx.error is None, (
        f"the guard terminated unexpectedly: {summary_window_ctx.error}"
    )


@then(
    parsers.parse(
        "the termination names {summary_count:d} summary requests in the last "
        "{window_size:d} LLM requests"
    )
)
def then_message_names_counts(summary_window_ctx, summary_count, window_size):
    """Verify the termination message states the observed counts."""
    message = str(summary_window_ctx.error)
    assert f"{summary_count} summary requests" in message
    assert f"last {window_size} LLM requests" in message


@then(parsers.parse("the provider received exactly {count:d} requests"))
def then_provider_count(summary_window_ctx, count):
    """Verify the guard fired before the offending request reached the provider."""
    assert summary_window_ctx.provider_request_count() == count


@then(parsers.parse("the summary window recorded {count:d} summary requests"))
def then_window_summary_count(summary_window_ctx, count):
    """Verify the window holds the expected number of summary requests."""
    snapshot = summary_window_ctx.window_snapshot()
    assert snapshot.count(SUMMARY_MODE) == count, snapshot


@then("the summary window holds only ordinary agent requests")
def then_window_ordinary_only(summary_window_ctx):
    """Verify ordinary traffic never counts as summary traffic."""
    snapshot = summary_window_ctx.window_snapshot()
    assert snapshot == [ORDINARY_MODE] * 10, snapshot
