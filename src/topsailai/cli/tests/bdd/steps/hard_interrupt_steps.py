"""Step definitions for hard-interrupt behavior in LLM retry handling."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.hard_interrupt_harness import HardInterruptHarness
from topsailai.ai_base.exception import HardInterruptError


@pytest.fixture
def hard_interrupt_context(monkeypatch) -> dict[str, Any]:
    """Provide isolated hard-interrupt state for each BDD scenario."""
    return {"harness": HardInterruptHarness(monkeypatch)}


@given("a deterministic hard-interrupt LLM harness")
def deterministic_harness(hard_interrupt_context: dict[str, Any]) -> None:
    """Confirm that the scenario owns a configured real chat harness."""
    assert hard_interrupt_context["harness"].model is not None


@given(parsers.parse("the retry prompt would be answered {answer}"))
def retry_answer(hard_interrupt_context: dict[str, Any], answer: str) -> None:
    """Configure the answer that would be used if retry were incorrectly prompted."""
    hard_interrupt_context["harness"].set_retry_answer(answer)


@given("a hard interrupt will surface during LLM streaming")
def stream_interrupt(hard_interrupt_context: dict[str, Any]) -> None:
    """Arrange the Control-Channel exception at the streaming check boundary."""
    hard_interrupt_context["harness"].arrange_stream_interrupt()


@given("a retryable LLM failure has occurred")
def retryable_failure(hard_interrupt_context: dict[str, Any]) -> None:
    """Mark the scenario as requiring a failed first provider request."""
    hard_interrupt_context["retryable_failure"] = True


@given("a hard interrupt will surface at the next retry-loop check")
def retry_loop_interrupt(hard_interrupt_context: dict[str, Any]) -> None:
    """Arrange one retryable failure followed by the retry-top interrupt."""
    assert hard_interrupt_context["retryable_failure"] is True
    hard_interrupt_context["harness"].arrange_retry_loop_interrupt()


@when("the streaming chat is executed")
def execute_streaming(hard_interrupt_context: dict[str, Any]) -> None:
    """Run the production streaming chat path."""
    hard_interrupt_context["harness"].execute_streaming_chat()


@when("the non-streaming chat is executed")
def execute_non_streaming(hard_interrupt_context: dict[str, Any]) -> None:
    """Run the production non-streaming retry path."""
    hard_interrupt_context["harness"].execute_non_streaming_chat()


@then("the hard interrupt propagates immediately")
def interrupt_propagates(hard_interrupt_context: dict[str, Any]) -> None:
    """Require the chat call to expose the hard control-flow exception."""
    assert isinstance(hard_interrupt_context["harness"].error, HardInterruptError)


@then("no LLM retry prompt is shown")
def no_retry_prompt(hard_interrupt_context: dict[str, Any]) -> None:
    """Require hard interrupts to bypass interactive retry handling."""
    hard_interrupt_context["harness"].retry_prompt.assert_not_called()


@then("exactly one LLM request is issued")
def one_request(hard_interrupt_context: dict[str, Any]) -> None:
    """Require no provider request after the hard interrupt is observed."""
    assert hard_interrupt_context["harness"].request_count == 1
