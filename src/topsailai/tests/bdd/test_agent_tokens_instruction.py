"""Gherkin bindings for the `/agent.tokens` instruction."""

from pytest_bdd import scenarios

from tests.bdd.steps.agent_tokens_instruction_steps import *  # noqa: F403


scenarios("features/agent_tokens_instruction.feature")
