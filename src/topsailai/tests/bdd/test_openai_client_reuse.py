"""Gherkin bindings for OpenAI SDK client reuse."""

from pytest_bdd import scenarios

from tests.bdd.steps.openai_client_reuse_steps import *  # noqa: F403


scenarios("features/openai_client_reuse.feature")
