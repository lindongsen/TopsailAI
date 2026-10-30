"""Gherkin bindings for mixed JSON history at the real provider boundary."""

from pytest_bdd import scenarios

from tests.bdd.steps.mixed_json_history_steps import *  # noqa: F403


scenarios("features/mixed_json_history.feature")
