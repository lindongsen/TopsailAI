"""BDD entry point for separate U3 HTTP/SSE acceptance scenarios."""

from pytest_bdd import scenarios

from tests.bdd.steps.test_llm_first_byte_timeout_retry_steps import *  # noqa: F403


scenarios("features/llm_first_byte_timeout_retry.feature")
