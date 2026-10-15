"""BDD entry point for U4 warning-only continuity scenarios."""

from pytest_bdd import scenarios

from tests.bdd.steps.test_llm_first_byte_timeout_warning_steps import *  # noqa: F403


scenarios("features/llm_first_byte_timeout_warning.feature")
