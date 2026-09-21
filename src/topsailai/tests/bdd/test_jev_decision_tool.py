"""Gherkin bindings for JEV decision-tool behavior."""

from pytest_bdd import scenarios

from tests.bdd.steps.jev_decision_tool_steps import *  # noqa: F403


scenarios("features/jev_decision_tool.feature")
