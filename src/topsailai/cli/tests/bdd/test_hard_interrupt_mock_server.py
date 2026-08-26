"""Gherkin scenarios for hard interrupts over HTTP/SSE streaming."""

from pytest_bdd import scenarios


scenarios("features/hard_interrupt_mock_server.feature")
