"""Steps for real-HTTP Agent2LLM runtime summary input verification."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, then, when

from tests.bdd.summarize_runtime_messages_harness import (
    SummarizeRuntimeMessagesHarness,
)


@pytest.fixture
def summarize_runtime_messages_context(monkeypatch) -> dict[str, Any]:
    """Provide and precisely close one runtime-summary HTTP harness."""
    harness = SummarizeRuntimeMessagesHarness(monkeypatch)
    try:
        yield {"harness": harness}
    finally:
        harness.close()


@given("a runtime-summary mock server and distinct Agent2LLM and User2Agent messages")
def runtime_summary_environment(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Confirm the server is live and the two context layers differ."""
    harness = summarize_runtime_messages_context["harness"]
    assert harness.server_thread.is_alive()
    assert harness.runtime_messages != harness.session_messages


@when("forced runtime Agent2LLM summarization crosses the real HTTP boundary")
def execute_runtime_summary(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Run forced production summarization through the mock HTTP endpoint."""
    harness = summarize_runtime_messages_context["harness"]
    harness.summarize()
    assert harness.answer == "Mock runtime summary"


@then("the runtime-summary mock server receives exactly one request")
def one_runtime_summary_request(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Require exactly one valid chat-completion request."""
    harness = summarize_runtime_messages_context["harness"]
    assert harness.request_count == 1


@then("the runtime-summary request has one appended instruction message")
def one_appended_summary_instruction(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Require the wire request to contain the captured runtime prefix plus one."""
    harness = summarize_runtime_messages_context["harness"]
    assert len(harness.transmitted_messages) == len(harness.pre_summary_messages) + 1


@then("the runtime-summary request prefix hash equals the pre-summary Agent2LLM hash")
def runtime_prefix_hash_matches(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Require exact canonical equality after excluding only the final message."""
    harness = summarize_runtime_messages_context["harness"]
    assert harness.transmitted_prefix_hash == harness.pre_summary_hash


@then("the runtime-summary request ends with the appended summary instruction")
def appended_summary_instruction_is_last(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Require the positionally excluded item to be the summary instruction."""
    harness = summarize_runtime_messages_context["harness"]
    final_message = harness.transmitted_messages[-1]
    assert final_message["role"] == "user"
    assert "DONOT INVOKE ANY TOOLS" in final_message["content"]
    assert final_message not in harness.pre_summary_messages


@then("runtime-summary source fallback emits no warning")
def no_runtime_source_fallback_warning(
    summarize_runtime_messages_context: dict[str, Any],
) -> None:
    """Require normal runtime selection to avoid either fallback warning."""
    harness = summarize_runtime_messages_context["harness"]
    fallback_warnings = [
        message for message in harness.warning_messages
        if "runtime messages not used" in message
    ]
    assert fallback_warnings == []
