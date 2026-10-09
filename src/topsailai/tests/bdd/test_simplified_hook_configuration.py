"""Gherkin bindings for simplified configured Hook Runtime behavior."""

from pytest_bdd import scenarios

from tests.bdd.steps.simplified_hook_configuration_steps import *  # noqa: F403


scenarios("features/simplified_hook_configuration.feature")
