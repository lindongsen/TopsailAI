"""Gherkin bindings for the session agent driver behavior suite."""

from pytest_bdd import scenarios

from tests.bdd.steps.session_agent_driver_steps import *  # noqa: F403

scenarios("features/session_agent_driver.feature")
