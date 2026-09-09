"""Gherkin bindings for provider-neutral LLM base import."""

from pytest_bdd import scenarios

from tests.bdd.steps.llm_base_provider_neutral_steps import *  # noqa: F403


scenarios("features/llm_base_provider_neutral.feature")
