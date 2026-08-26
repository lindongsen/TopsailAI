"""Step definitions for summarize head and reconstruction retention."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.summarize_watermark_harness import SummarizeWatermarkHarness


@pytest.fixture
def structure_context(monkeypatch) -> dict[str, Any]:
    """Provide isolated message-structure state for one scenario."""
    return {"harness": SummarizeWatermarkHarness(monkeypatch)}


def _harness(context: dict[str, Any]) -> SummarizeWatermarkHarness:
    """Return the summarize structure harness."""
    return context["harness"]


@given("a deterministic summarize structure harness")
def structure_harness(structure_context) -> None:
    """Initialize deterministic structure state."""
    return None


@given(parsers.parse("first-task retention is {switch}"))
def first_task_retention(structure_context, switch: str) -> None:
    """Configure whether the first task belongs to the intrinsic head."""
    structure_context["keep_first_task"] = switch == "on"


@when("the intrinsic summary head is resolved")
def resolve_intrinsic_head(structure_context) -> None:
    """Resolve the intrinsic head through production logic."""
    _harness(structure_context).resolve_summary_head(
        structure_context["keep_first_task"]
    )


@then(parsers.parse("the intrinsic head contains {count:d} messages"))
def intrinsic_head_count(structure_context, count: int) -> None:
    """Assert the number of retained intrinsic-head messages."""
    assert len(_harness(structure_context).trace["summary_head"]) == count


@then(parsers.parse("the intrinsic head task is {retention}"))
def intrinsic_task_retention(structure_context, retention: str) -> None:
    """Assert whether a task message appears in the intrinsic head."""
    harness = _harness(structure_context)
    has_task = any(
        harness.base._is_task_message(message)
        for message in harness.trace["summary_head"]
    )
    assert has_task is (retention == "retained")


@when("Agent2LLM profitability is evaluated with and without force")
def evaluate_profitability_force(structure_context) -> None:
    """Evaluate ordinary, forced, and hard Agent2LLM guards."""
    _harness(structure_context).evaluate_agent_profitability_force()


@then("ordinary summarization is rejected as not smaller")
def ordinary_profitability_rejected(structure_context) -> None:
    """Assert the ordinary profitability guard rejects equal token usage."""
    assert _harness(structure_context).trace["ordinary_profitability"] is False


@then("forced summarization bypasses the profitability guard")
def forced_profitability_allowed(structure_context) -> None:
    """Assert force bypasses only the ordinary value guard."""
    assert _harness(structure_context).trace["forced_profitability"] is True


@then("forced summarization still honors hard feasibility")
def forced_hard_feasibility_rejected(structure_context) -> None:
    """Assert force cannot bypass model-capacity feasibility."""
    assert _harness(structure_context).trace["forced_hard_feasibility"] is False


@given(parsers.parse("session-message retention is {switch}"))
def session_message_retention(structure_context, switch: str) -> None:
    """Configure session-message retention during reconstruction."""
    structure_context["keep_session"] = switch == "on"


@given(parsers.re(r"the summary head offset is (?P<count>\d+) messages?"))
def summary_head_offset(structure_context, count: str) -> None:
    """Configure the Agent2LLM head offset."""
    structure_context["head_offset"] = int(count)


@given(parsers.re(r"the summary tail offset is (?P<count>\d+) messages?"))
def summary_tail_offset(structure_context, count: str) -> None:
    """Configure the Agent2LLM tail offset."""
    structure_context["tail_offset"] = int(count)


@when("Agent2LLM messages are reconstructed")
def reconstruct_agent_messages(structure_context) -> None:
    """Run production Agent2LLM reconstruction with a stubbed LLM boundary."""
    _harness(structure_context).rebuild_agent_messages(
        structure_context["keep_session"],
        structure_context["head_offset"],
        structure_context["tail_offset"],
    )


@then("the configured head messages are retained")
def configured_head_retained(structure_context) -> None:
    """Assert every configured head message survives reconstruction."""
    harness = _harness(structure_context)
    rebuilt = harness.trace["rebuilt_messages"]
    expected = harness.trace["rebuild_objects"]["head"]
    assert all(harness.base._message_in_list(message, rebuilt) for message in expected)


@then("the configured tail messages are retained")
def configured_tail_retained(structure_context) -> None:
    """Assert every configured tail message survives reconstruction."""
    harness = _harness(structure_context)
    rebuilt = harness.trace["rebuilt_messages"]
    expected = harness.trace["rebuild_objects"]["tail"]
    assert all(harness.base._message_in_list(message, rebuilt) for message in expected)


@then("the rebuilt context ends with the last User2Agent user message")
def rebuilt_ends_with_session_user(structure_context) -> None:
    """Assert the final prompt comes from User2Agent rather than Agent2LLM."""
    harness = _harness(structure_context)
    rebuilt = harness.trace["rebuilt_messages"]
    objects = harness.trace["rebuild_objects"]
    assert harness.base._message_equal(rebuilt[-1], objects["session_user"])
    assert not harness.base._message_equal(rebuilt[-1], objects["internal_user"])


@then(parsers.parse("session messages are {retention} in the rebuilt context"))
def rebuilt_session_retention(structure_context, retention: str) -> None:
    """Assert the session retention switch controls session marker inclusion."""
    harness = _harness(structure_context)
    rebuilt = harness.trace["rebuilt_messages"]
    marker = harness.trace["rebuild_objects"]["session_marker"]
    is_present = harness.base._message_in_list(marker, rebuilt)
    assert is_present is (retention == "present")
