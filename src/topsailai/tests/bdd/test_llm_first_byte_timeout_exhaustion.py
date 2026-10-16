"""BDD entry point for U5 retry-exhaustion acceptance."""

from pytest_bdd import scenarios

from tests.bdd.steps.test_llm_first_byte_timeout_exhaustion_steps import *  # noqa: F403


scenarios("features/llm_first_byte_timeout_exhaustion.feature")
