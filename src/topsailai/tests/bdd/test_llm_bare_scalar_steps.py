"""Gherkin bindings for bare-scalar step arrays at the real provider boundary."""

from pytest_bdd import scenarios

from tests.bdd.steps.llm_bare_scalar_steps_steps import *  # noqa: F403


scenarios("features/llm_bare_scalar_steps.feature")
