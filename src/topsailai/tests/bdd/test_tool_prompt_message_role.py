"""Gherkin bindings for tool prompt message-role behavior."""

from pytest_bdd import scenarios

from tests.bdd.steps.tool_prompt_message_role_steps import *  # noqa: F403


scenarios("features/tool_prompt_message_role.feature")
