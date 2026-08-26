"""Step definitions for hard interrupts over real HTTP/SSE streaming."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.hard_interrupt_mock_server_harness import (
    HardInterruptMockServerHarness,
)
from topsailai.ai_base.exception import HardInterruptError


@pytest.fixture
def hard_interrupt_mock_server_context(monkeypatch) -> dict[str, Any]:
    """Provide and reliably close one isolated HTTP integration harness."""
    harness = HardInterruptMockServerHarness(monkeypatch)
    try:
        yield {"harness": harness}
    finally:
        harness.close()


@given("a hard-interrupt LLM mock server with SSE streaming")
def sse_mock_server(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Confirm that the scenario owns a real listening HTTP server."""
    assert hard_interrupt_mock_server_context["harness"].server.server_port > 0


@given(parsers.parse("the HTTP retry prompt would be answered {answer}"))
def retry_answer(
    hard_interrupt_mock_server_context: dict[str, Any],
    answer: str,
) -> None:
    """Configure the answer that would be used if prompting were incorrect."""
    hard_interrupt_mock_server_context["harness"].set_retry_answer(answer)


@given("a hard interrupt will surface after an HTTP SSE chunk")
def stream_interrupt(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Arrange interruption at the production stream-check boundary."""
    hard_interrupt_mock_server_context["harness"].arrange_stream_interrupt()


@given("an HTTP streaming request will end with a retryable client failure")
def retryable_failure(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Mark the scenario as requiring one completed HTTP streaming request."""
    hard_interrupt_mock_server_context["retryable_failure"] = True


@given("a hard interrupt will surface at the next HTTP retry-loop check")
def retry_loop_interrupt(
    hard_interrupt_mock_server_context: dict[str, Any],
) -> None:
    """Arrange a client failure followed by a retry-top hard interrupt."""
    assert hard_interrupt_mock_server_context["retryable_failure"] is True
    hard_interrupt_mock_server_context["harness"].arrange_retry_loop_interrupt()


@when("the HTTP streaming chat is executed")
def execute_streaming(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Execute production chat through the official client and mock server."""
    hard_interrupt_mock_server_context["harness"].execute_streaming_chat()


@then("the HTTP hard interrupt propagates immediately")
def interrupt_propagates(
    hard_interrupt_mock_server_context: dict[str, Any],
) -> None:
    """Require the hard control-flow exception to escape chat()."""
    error = hard_interrupt_mock_server_context["harness"].error
    assert isinstance(error, HardInterruptError), repr(error)


@then("no HTTP LLM retry prompt is shown")
def no_retry_prompt(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Require hard interrupts to bypass the interactive retry branch."""
    hard_interrupt_mock_server_context["harness"].retry_prompt.assert_not_called()


@then("the mock server receives exactly one completion request")
def one_request(hard_interrupt_mock_server_context: dict[str, Any]) -> None:
    """Require the server to observe no request after interruption."""
    assert hard_interrupt_mock_server_context["harness"].request_count == 1
