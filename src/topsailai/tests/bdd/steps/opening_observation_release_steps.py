"""BDD steps for the opening-observation release over real HTTP and SQLite."""

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.opening_observation_release_harness import (
    LARGE_OBSERVATION_TEXT,
    SMALL_OBSERVATION_TEXT,
    OpeningObservationReleaseScenario,
)


@pytest.fixture
def release_ctx(monkeypatch, tmp_path):
    """Yield one isolated real-HTTP scenario and stop its exact resources."""
    context = OpeningObservationReleaseScenario(monkeypatch, tmp_path)
    try:
        yield context
    finally:
        context.close()


@given(
    parsers.parse(
        "an opening observation release with ratio {ratio:g} "
        "and a token threshold of {threshold:d}"
    ),
    target_fixture="release_case",
)
def given_release(release_ctx, ratio, threshold):
    """Start the provider, the database and the production runtime."""
    release_ctx.start(ratio=str(ratio), token_threshold=str(threshold))
    return release_ctx


@given("a large startup observation")
def given_large_observation(release_case):
    """The default seed already carries a large startup observation."""
    assert LARGE_OBSERVATION_TEXT in release_case.persisted_texts()[0]


@given("a small startup observation")
def given_small_observation(release_case):
    """Replace the seed with a startup observation far below the ratio."""
    release_case.reseed(observation_text=SMALL_OBSERVATION_TEXT)


@given("a later user-role tool observation")
def given_tool_observation(release_case):
    """Append a tool result stored as a user-role observation."""
    release_case.append_tool_observation()


@when("the user-facing summarization completes")
def when_summary_completes(release_case):
    """Run the production summarization path with a real provider request."""
    release_case.run_summary(force=True)


@when("the agent-layer summarization completes")
def when_agent_summary_completes(release_case):
    """Run the agent-layer path, which is a separate release call site."""
    release_case.run_agent_summary(force=True)


@when("the user-facing summarization completes without a session")
def when_summary_completes_without_session(release_case):
    """Run the in-memory branch, the second user-facing release call site."""
    release_case.run_in_memory_summary(force=True)


@when("the user-facing summarization is skipped")
def when_summary_skipped(release_case):
    """Run the production path without force, which the budget check rejects."""
    release_case.run_summary(force=False)


@then("the opening observation is gone from memory")
def then_gone_from_memory(release_case):
    """The in-memory result must no longer start with an observation."""
    assert not release_case.observation_survives_in_memory(), (
        release_case.memory_step_names()
    )


@then("the opening observation is still in memory")
def then_still_in_memory(release_case):
    """A kept observation must remain in the in-memory result."""
    assert release_case.observation_survives_in_memory(), (
        release_case.memory_step_names()
    )


@then("the opening observation is gone from agent memory")
def then_gone_from_agent_memory(release_case):
    """The agent-layer result must no longer start with an observation."""
    assert not release_case.observation_survives_in_agent_memory(), (
        release_case.agent_memory_step_names()
    )


@then("the opening observation is gone from storage")
def then_gone_from_storage(release_case):
    """The persisted rows must be removed, or a reload resurrects them."""
    assert not release_case.observation_survives_in_storage(), (
        release_case.persisted_texts()
    )


@then("the opening observation is still in storage")
def then_still_in_storage(release_case):
    """A kept observation must remain persisted."""
    assert release_case.observation_survives_in_storage(), (
        release_case.persisted_texts()
    )


@then("the startup observation is gone from storage")
def then_startup_gone(release_case):
    """The startup observation specifically must be removed."""
    assert not release_case.startup_observation_survives_in_storage(), (
        release_case.persisted_texts()
    )


@then("the later user-role tool observation is still in storage")
def then_tool_observation_survives(release_case):
    """Regression: the release must not widen to a later observation."""
    assert release_case.tool_observation_survives_in_storage(), (
        release_case.persisted_texts()
    )


@then("the summary request reached the provider exactly once")
def then_provider_count_once(release_case):
    """Prove the summary really ran over the wire, exactly one request."""
    assert release_case.provider_request_count() == 1


@then("no release warning was printed")
def then_no_warning(release_case):
    """A skipped summary must not report a release."""
    assert release_case.release_warnings() == []


@then("no release event was recorded")
def then_no_event(release_case):
    """A skipped summary must not record a release event."""
    assert release_case.release_events() == []


@then("a release warning names the removed count and the decision inputs")
def then_warning_content(release_case):
    """The operator must see what was removed and why.

    Two warnings are expected: one for the in-memory removal and one for the
    persisted removal. They are asserted separately because the persisted one
    carries no decision inputs, so merging them would hide a missing field.
    """
    warnings = release_case.release_warnings()
    in_memory = [text for text in warnings if "from session" not in text]
    persisted = [text for text in warnings if "from session" in text]
    assert len(in_memory) == 1, warnings
    assert len(persisted) == 1, warnings
    text = in_memory[0]
    assert "removed=1" in text
    assert "block_tokens=" in text
    assert "budget=1000" in text
    assert "ratio=0.3" in text
    assert "removed_rows=1" in persisted[0]


@then("a release event records the decision inputs")
def then_event_content(release_case):
    """The removal must be auditable after the fact.

    Two events are expected: the in-memory removal carries the decision inputs,
    and the persisted removal carries the durable half. They are asserted
    separately so a missing decision field cannot be hidden by the other event.
    """
    events = release_case.release_events()
    in_memory = [payload for payload in events if payload["persisted"] is False]
    persisted = [payload for payload in events if payload["persisted"] is True]
    assert len(in_memory) == 1, events
    assert len(persisted) == 1, events
    payload = in_memory[0]
    assert payload["removed_messages"] == 1
    assert payload["budget_tokens"] == 1000
    assert payload["ratio"] == 0.3
    assert payload["session_id"] == "opening-observation"
    assert payload["block_tokens"] > 0
    assert persisted[0]["removed_messages"] == 1
