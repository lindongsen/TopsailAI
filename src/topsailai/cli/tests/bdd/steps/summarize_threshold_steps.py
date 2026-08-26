"""Step definitions for fixed summarize threshold behavior."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.summarize_watermark_harness import SummarizeWatermarkHarness


@pytest.fixture
def threshold_context(monkeypatch) -> dict[str, Any]:
    """Provide isolated threshold state for one scenario."""
    return {"harness": SummarizeWatermarkHarness(monkeypatch)}


def _harness(context: dict[str, Any]) -> SummarizeWatermarkHarness:
    """Return the threshold harness from scenario state."""
    return context["harness"]


@given("a deterministic summarize threshold harness")
def threshold_harness(threshold_context: dict[str, Any]) -> None:
    """Initialize the threshold harness."""
    return None


@given(parsers.parse("the User2Agent quantity threshold is {threshold:d} messages"))
def user_quantity_threshold(threshold_context, threshold: int) -> None:
    """Configure the User2Agent quantity threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD", str(threshold)
    )


@given(parsers.parse("the Agent2LLM quantity threshold is {threshold:d} messages"))
def agent_quantity_threshold(threshold_context, threshold: int) -> None:
    """Configure the Agent2LLM quantity threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", str(threshold)
    )


@given("the Agent2LLM quantity threshold is unset")
def unset_agent_quantity_threshold(threshold_context) -> None:
    """Remove the Agent2LLM-specific quantity threshold."""
    _harness(threshold_context).monkeypatch.delenv(
        "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", raising=False
    )


@given(parsers.parse("the shared quantity threshold is {threshold:d} messages"))
def shared_quantity_threshold(threshold_context, threshold: int) -> None:
    """Configure the shared quantity threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD", str(threshold)
    )


@given(parsers.parse("both layer and shared quantity thresholds are {threshold}"))
def both_quantity_thresholds(threshold_context, threshold: str) -> None:
    """Configure both quantity thresholds, including null."""
    value = "" if threshold == "null" else threshold
    harness = _harness(threshold_context)
    for key in (
        "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD",
        "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD",
        "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
    ):
        harness.monkeypatch.setenv(key, value)


@given(parsers.parse("User2Agent contains {count:d} messages"))
def user_messages(threshold_context, count: int) -> None:
    """Set User2Agent message count."""
    _harness(threshold_context).set_user_messages(count)


@given(parsers.parse("Agent2LLM contains {count:d} messages"))
def agent_messages(threshold_context, count: int) -> None:
    """Set Agent2LLM message count."""
    _harness(threshold_context).set_agent_messages(count)


@given(parsers.parse("the User2Agent token threshold is {threshold:d} tokens"))
def user_token_threshold(threshold_context, threshold: int) -> None:
    """Configure the User2Agent token threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD", str(threshold)
    )


@given(parsers.parse("the Agent2LLM token threshold is {threshold:d} tokens"))
def agent_token_threshold(threshold_context, threshold: int) -> None:
    """Configure the Agent2LLM token threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD", str(threshold)
    )


@given(parsers.parse("User2Agent token usage is {tokens:d} tokens"))
def user_token_usage(threshold_context, tokens: int) -> None:
    """Set cached User2Agent token usage."""
    harness = _harness(threshold_context)
    harness.set_cached_tokens(tokens)
    harness.runtime.llm_model = harness.agent.llm_model


@given(parsers.parse("Agent2LLM token usage is {tokens:d} tokens"))
def agent_token_usage(threshold_context, tokens: int) -> None:
    """Set cached Agent2LLM token usage."""
    _harness(threshold_context).set_cached_tokens(tokens)


@given(parsers.parse("both layer and shared quantity thresholds are {threshold:d}"))
def both_numeric_quantity_thresholds(threshold_context, threshold: int) -> None:
    """Configure numeric quantity thresholds."""
    both_quantity_thresholds(threshold_context, str(threshold))


@given("both layer token thresholds are 0")
def disabled_token_thresholds(threshold_context) -> None:
    """Disable token-based triggers for both layers."""
    harness = _harness(threshold_context)
    for key in (
        "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD",
        "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD",
    ):
        harness.monkeypatch.setenv(key, "0")


@given(parsers.parse("both layers contain {count:d} messages"))
def both_layer_messages(threshold_context, count: int) -> None:
    """Set both layer message stores."""
    harness = _harness(threshold_context)
    harness.set_user_messages(count)
    harness.set_agent_messages(count)


@given(parsers.parse("both layers use {tokens:d} tokens"))
def both_layer_tokens(threshold_context, tokens: int) -> None:
    """Set cached token usage for both layers."""
    _harness(threshold_context).set_cached_tokens(tokens)


@when("User2Agent summary need is evaluated")
def evaluate_user_need(threshold_context) -> None:
    """Evaluate the real User2Agent threshold method."""
    threshold_context["needed"] = _harness(threshold_context).runtime.is_need_summarize_for_processed()


@when("Agent2LLM summary need is evaluated")
def evaluate_agent_need(threshold_context) -> None:
    """Evaluate the real Agent2LLM threshold method."""
    threshold_context["needed"] = _harness(threshold_context).runtime.is_need_summarize_for_processing()


@when("quantity summary need is evaluated")
def evaluate_quantity_need(threshold_context) -> None:
    """Evaluate both quantity triggers."""
    harness = _harness(threshold_context)
    threshold_context["user_needed"] = harness.runtime.is_need_summarize_for_processed()
    threshold_context["agent_needed"] = harness.runtime.is_need_summarize_for_processing()


@when("each layer summary need is evaluated")
def evaluate_each_need(threshold_context) -> None:
    """Evaluate both layer triggers."""
    evaluate_quantity_need(threshold_context)
    threshold_context["user_token_needed"] = threshold_context["user_needed"]
    threshold_context["agent_token_needed"] = threshold_context["agent_needed"]


@then(parsers.parse("User2Agent summarization is {expected}"))
def user_need(threshold_context, expected: str) -> None:
    """Assert User2Agent need result."""
    assert threshold_context["needed"] == (expected == "needed")


@then(parsers.parse("Agent2LLM summarization is {expected}"))
def agent_need(threshold_context, expected: str) -> None:
    """Assert Agent2LLM need result."""
    assert threshold_context["needed"] == (expected == "needed")

@then("quantity-based summarization is disabled")
def quantity_disabled(threshold_context) -> None:
    """Assert neither layer is quantity-triggered."""
    assert threshold_context["user_needed"] is False
    assert threshold_context["agent_needed"] is False


@then("neither layer is triggered by token usage")
def tokens_disabled(threshold_context) -> None:
    """Assert disabled token thresholds do not trigger either layer."""
    assert threshold_context["user_needed"] is False
    assert threshold_context["agent_needed"] is False


@given(parsers.parse("the Agent2LLM duplicate-tool-call threshold is {threshold:d}"))
def duplicate_tool_threshold(threshold_context, threshold: int) -> None:
    """Configure the Agent2LLM duplicate-tool-call threshold."""
    _harness(threshold_context).monkeypatch.setenv(
        "TOPSAILAI_AGENT2LLM_DUP_TOOL_CALL_SUMMARIZE_THRESHOLD",
        str(threshold),
    )


@given(parsers.parse("the consecutive duplicate tool call count is {count:d}"))
def consecutive_duplicate_count(threshold_context, count: int) -> None:
    """Attach deterministic duplicate-call statistics to the agent model."""
    tool_stat = type(
        "ToolStatStub",
        (),
        {"get_consecutive_duplicate_count": lambda self: count},
    )()
    _harness(threshold_context).agent.llm_model.tool_stat = tool_stat
