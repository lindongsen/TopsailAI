"""Gherkin bindings for LLM request statistics."""

from pytest_bdd import scenarios

from tests.bdd.steps.llm_request_stat_steps import *  # noqa: F403


scenarios("features/llm_request_stat.feature")
