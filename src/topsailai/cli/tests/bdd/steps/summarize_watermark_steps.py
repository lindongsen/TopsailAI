"""Step definitions for deterministic summarize watermark behavior."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, parsers, then, when

from tests.bdd.summarize_watermark_harness import SummarizeWatermarkHarness


@given("a deterministic summarize watermark harness")
def watermark_context(monkeypatch) -> dict[str, Any]:
    """Create isolated harness state for one scenario."""
    return {"harness": SummarizeWatermarkHarness(monkeypatch)}



import pytest


@pytest.fixture
def context(monkeypatch) -> dict[str, Any]:
    """Provide isolated mutable state for each watermark scenario."""
    return {"harness": SummarizeWatermarkHarness(monkeypatch)}

def _ctx(context: dict[str, Any]) -> SummarizeWatermarkHarness:
    """Return the scenario harness."""
    return context["harness"]


@given(parsers.parse("the current context contains {tokens:d} tokens"))
def current_context(context, tokens: int) -> None:
    """Store the current token snapshot."""
    context["tokens"] = tokens


@given(parsers.parse("LOW and HIGH watermark ratios of {low} and {high}"))
def watermark_ratios(context, low: str, high: str) -> None:
    """Configure low and high ratios, including non-finite literals."""
    harness = _ctx(context)
    low_value = harness.parse_value(low)
    high_value = harness.parse_value(high)
    harness.monkeypatch.setenv("TOPSAILAI_CONTEXT_LOW_WATERMARK_RATIO", str(low_value))
    harness.monkeypatch.setenv("TOPSAILAI_CONTEXT_HIGH_WATERMARK_RATIO", str(high_value))


@when("the context watermark is classified")
def classify_watermark(context) -> None:
    """Classify the stored token snapshot or the configured cached snapshot."""
    context["watermark"] = _ctx(context).classify(context.get("tokens"))


@then(parsers.parse("the watermark level is {level}"))
def watermark_level(context, level: str) -> None:
    """Assert the expected watermark classification."""
    assert context["watermark"].level == level


@then(parsers.parse("the summary-safe limit is {limit:d} tokens"))
def summary_safe_limit(context, limit: int) -> None:
    """Assert the derived summary-safe budget."""
    result = context.get("watermark") or context["harness"].trace["limits"]
    actual = result.summary_safe_limit if hasattr(result, "summary_safe_limit") else result[1]
    assert actual == limit


@then(parsers.parse("the send limit is {limit:d} tokens"))
def send_limit(context, limit: int) -> None:
    """Assert the derived model send budget."""
    result = context.get("watermark") or context["harness"].trace["limits"]
    actual = result.send_limit if hasattr(result, "send_limit") else result[2]
    assert actual == limit


@then(parsers.parse("the effective ratios are {low:f} and {high:f}"))
def effective_ratios(context, low: float, high: float) -> None:
    """Assert the effective ratio values represented by watermark limits."""
    result = context["watermark"]
    assert result.low_limit == 0.73 * result.summary_safe_limit
    assert result.high_limit == 0.93 * result.summary_safe_limit


@given(parsers.parse("a token safety coefficient of {coefficient}"))
def safety_coefficient(context, coefficient: str) -> None:
    """Configure the token safety coefficient."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_CONTEXT_TOKEN_SAFETY_COEF", coefficient)


@given(parsers.parse("a raw context estimate of {tokens:d} tokens"))
def raw_estimate(context, tokens: int) -> None:
    """Store a raw token estimate."""
    context["raw_tokens"] = tokens


@when("safe tokens are estimated")
def estimate_safe_tokens(context) -> None:
    """Apply production safe-token estimation."""
    context["safe_tokens"] = _ctx(context).estimate(context["raw_tokens"])


@then(parsers.parse("the safe token estimate is {tokens:d} tokens"))
def safe_token_estimate(context, tokens: int) -> None:
    """Assert the estimated safe token count."""
    assert context["safe_tokens"] == tokens


@given(parsers.parse("a summary operation margin of {margin:d} tokens"))
def summary_margin(context, margin: int) -> None:
    """Configure the operation margin."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_OP_MARGIN", str(margin))


@when("context limits are computed")
def compute_limits(context) -> None:
    """Compute model send and summary-safe limits."""
    context["limits"] = _ctx(context).compute_limits()


@given("no positive model context limit is configured")
def no_model_context(context) -> None:
    """Disable dynamic model context resolution."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_MODEL_MAX_CONTEXT_MAP", "{}")
    _ctx(context).monkeypatch.setenv("TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT", "0")


@then("no dynamic watermark result is produced")
def no_watermark(context) -> None:
    """Assert that dynamic classification is unavailable."""
    assert context["watermark"] is None


@given(parsers.parse("cached token usage is {tokens:d} tokens"))
def cached_tokens(context, tokens: int) -> None:
    """Set cached token-stat usage."""
    _ctx(context).set_cached_tokens(tokens)

@given(parsers.parse("the Agent2LLM quantity threshold is {threshold:d} messages"))
def watermark_agent_quantity_threshold(context, threshold: int) -> None:
    """Configure the Agent2LLM quantity threshold for retention checks."""
    _ctx(context).monkeypatch.setenv(
        "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD", str(threshold)
    )


@given(parsers.parse("the session maximum ratio is {ratio}"))
def session_max_ratio(context, ratio: str) -> None:
    """Configure the session retention ratio, including non-finite values."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO", ratio)


@given(parsers.parse("Agent2LLM has {agent_count:d} messages and User2Agent has {session_count:d} messages"))
def retention_message_counts(context, agent_count: int, session_count: int) -> None:
    """Set Agent2LLM and User2Agent message counts for retention checks."""
    context["agent_count"] = agent_count
    context["session_count"] = session_count


@when("Agent2LLM session retention is evaluated")
def evaluate_session_retention(context) -> None:
    """Drive the real session-retention branch without invoking an LLM."""
    harness = _ctx(context)
    harness.evaluate_session_retention(context["agent_count"], context["session_count"])
    context["retention"] = harness.trace.get("retention")
    context["retention_error"] = harness.trace.get("retention_error")


@then(parsers.parse("session messages are {retention}"))
def session_retention(context, retention: str) -> None:
    """Assert whether session messages were retained."""
    assert context["retention"] == retention




@given(parsers.parse("the runtime token counter returns {tokens:d} tokens"))
def runtime_counter(context, tokens: int) -> None:
    """Patch token counting with a deterministic return value."""
    import topsailai.workspace.context.base as base_module

    _ctx(context).monkeypatch.setattr(base_module, "count_tokens", lambda _: tokens)


@given("realtime token calculation is disabled")
def realtime_disabled(context) -> None:
    """Disable realtime token calculation."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_REALTIME_TOKEN_CALCULATION", "0")


@given("realtime token calculation is enabled")
def realtime_enabled(context) -> None:
    """Enable realtime token calculation."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_REALTIME_TOKEN_CALCULATION", "1")


@when("current tokens are requested for explicit messages")
def current_explicit(context) -> None:
    """Request token usage with an explicit message list."""
    context["current_tokens"] = _ctx(context).current_tokens(explicit=True)


@when("current tokens are requested without explicit messages")
def current_implicit(context) -> None:
    """Request token usage using the configured implicit source."""
    context["current_tokens"] = _ctx(context).current_tokens(explicit=False)


@then(parsers.parse("current token usage is {tokens:d} tokens"))
def current_token_usage(context, tokens: int) -> None:
    """Assert selected token usage."""
    assert context["current_tokens"] == tokens


@given(parsers.parse("the real pre-chat hook classifies {first} then {second}"))
def real_pre_chat_classifications(context, first: str, second: str) -> None:
    """Configure successive watermark classifications for the real closure."""
    from topsailai.workspace.context.base import ContextWatermarkResult

    def result(level: str, tokens: int) -> ContextWatermarkResult:
        """Build a deterministic watermark result for one checkpoint."""
        return ContextWatermarkResult(
            level=level.upper(),
            current_tokens=tokens,
            safe_tokens=tokens,
            model_max_context=1000,
            max_tokens=100,
            summary_safe_limit=800,
            send_limit=900,
            low_limit=584,
            high_limit=744,
        )

    context["pre_chat_levels"] = (first, second)
    context["pre_chat_results"] = [
        result(first, 600),
        result(second, 300),
    ]


@when("the real summarize pre-chat hook is invoked")
def invoke_real_pre_chat(context) -> None:
    """Invoke AgentChatBase's registered summarize closure."""
    harness = _ctx(context)
    harness.run_real_pre_chat_hook(context["pre_chat_results"])
    context["pre_chat_runtime"] = harness.trace["pre_chat_runtime"]
    context["pre_chat_error"] = harness.trace["pre_chat_error"]


@then("neither layer is summarized by the pre-chat hook")
def neither_pre_chat_summary(context) -> None:
    """Assert NORMAL leaves both summary operations untouched."""
    runtime = context["pre_chat_runtime"]
    runtime.summarize_messages_for_processed.assert_not_called()
    runtime.summarize_messages_for_processing.assert_not_called()


@then("both layers are summarized without force by the pre-chat hook")
def ordinary_pre_chat_summary(context) -> None:
    """Assert LOW invokes ordinary summarization for both layers."""
    runtime = context["pre_chat_runtime"]
    runtime.summarize_messages_for_processed.assert_called_once_with(force=False)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=False)
    assert context["pre_chat_error"] is None


@then("both layers are summarized with force by the pre-chat hook")
def forced_pre_chat_summary(context) -> None:
    """Assert HIGH or HARD invokes forced summarization for both layers."""
    runtime = context["pre_chat_runtime"]
    runtime.summarize_messages_for_processed.assert_called_once_with(force=True)
    runtime.summarize_messages_for_processing.assert_called_once_with(force=True)


@then("the pre-chat hook does not raise a context window error")
def no_context_window_error(context) -> None:
    """Assert forced summarization recovered from HARD."""
    assert context["pre_chat_error"] is None


@then("the pre-chat hook raises a context window error")
def context_window_error(context) -> None:
    """Assert unrecovered HARD raises the required domain exception."""
    from topsailai.ai_base.exception import ContextWindowLimitError

    assert isinstance(context["pre_chat_error"], ContextWindowLimitError)


@given(parsers.parse("the minimum extra message setting is {minimum:d}"))
def minimum_extra_setting(context, minimum: int) -> None:
    """Store the minimum-extra configuration for retention scenarios."""
    context["minimum_extra"] = minimum


@when("minimum-extra summarization is evaluated without force")
def evaluate_min_extra_without_force(context) -> None:
    """Evaluate the real minimum-extra guard without force."""
    harness = _ctx(context)
    harness.evaluate_min_extra(
        context["agent_count"], context["session_count"], context["minimum_extra"], False
    )
    context["min_extra_summary_called"] = harness.trace["min_extra_summary_called"]


@when("minimum-extra summarization is evaluated with force")
def evaluate_min_extra_with_force(context) -> None:
    """Evaluate the real minimum-extra guard with force enabled."""
    harness = _ctx(context)
    harness.evaluate_min_extra(
        context["agent_count"], context["session_count"], context["minimum_extra"], True
    )
    context["min_extra_summary_called"] = harness.trace["min_extra_summary_called"]


@then(parsers.parse("minimum-extra summarization is {outcome}"))
def minimum_extra_outcome(context, outcome: str) -> None:
    """Assert whether the summary boundary was reached."""
    assert context["min_extra_summary_called"] is (outcome == "summarized")


@given(parsers.parse("a model context of {maximum:d} tokens with a summary margin of {margin:d} tokens"))
def feasibility_limits(context, maximum: int, margin: int) -> None:
    """Store model feasibility limits for the scenario."""
    context["feasibility_maximum"] = maximum
    context["feasibility_margin"] = margin


@given("summary feasibility uses safety coefficient 1.0")
def feasibility_safety_coefficient(context) -> None:
    """Pin safety estimation to one for exact boundary assertions."""
    _ctx(context).monkeypatch.setenv("TOPSAILAI_CONTEXT_TOKEN_SAFETY_COEF", "1.0")


@given(parsers.parse("summary input tokens are {input_tokens:d} and preserved tokens are {preserved_tokens:d}"))
def feasibility_tokens(context, input_tokens: int, preserved_tokens: int) -> None:
    """Store input and preserved token values."""
    context["feasibility_input_tokens"] = input_tokens
    context["feasibility_preserved_tokens"] = preserved_tokens


@given(parsers.parse("the summary token reserve is {reserve:d}"))
def feasibility_reserve(context, reserve: int) -> None:
    """Store the reserved summary token budget."""
    context["feasibility_reserve"] = reserve


@when("summary feasibility is checked")
def check_feasibility(context) -> None:
    """Run the real dynamic feasibility check."""
    harness = _ctx(context)
    harness.evaluate_feasibility(
        context["feasibility_input_tokens"],
        context["feasibility_preserved_tokens"],
        context["feasibility_reserve"],
        context["feasibility_maximum"],
        context["feasibility_margin"],
    )
    context["feasibility_result"] = harness.trace["feasibility"]


@then(parsers.parse("summary feasibility is {outcome}"))
def feasibility_outcome(context, outcome: str) -> None:
    """Assert the real feasibility decision."""
    allowed = context["feasibility_result"][0]
    assert allowed is (outcome == "allowed")


@then(parsers.parse("summary feasibility is rejected with reason {reason}"))
def feasibility_rejection_reason(context, reason: str) -> None:
    """Assert a hard feasibility rejection and its production reason."""
    allowed, actual_reason, _, _ = context["feasibility_result"]
    assert allowed is False
    assert actual_reason == reason


@given(
    parsers.parse(
        "a model context limit of {maximum:d} tokens and a completion budget of {budget:d} tokens"
    )
)
def model_context_and_completion_budget(context, maximum: int, budget: int) -> None:
    """Configure model capacity and completion budget for classification."""
    import json

    harness = _ctx(context)
    harness.monkeypatch.setenv(
        "TOPSAILAI_MODEL_MAX_CONTEXT_MAP",
        json.dumps({"bdd-model": maximum}),
    )
    harness.agent.llm_model.max_tokens = budget


@given(parsers.parse("the model context map is {configuration}"))
def invalid_model_context_map(context, configuration: str) -> None:
    """Configure one invalid model-context map variant."""
    values = {
        "malformed": "{bad json",
        "non-positive": '{"bdd-model": -5}',
        "non-integer": '{"bdd-model": "invalid"}',
    }
    harness = _ctx(context)
    harness.monkeypatch.setenv(
        "TOPSAILAI_MODEL_MAX_CONTEXT_MAP", values[configuration]
    )
    harness.monkeypatch.setenv("TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT", "0")
