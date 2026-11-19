"""Gherkin bindings for severe-repetition interactive recovery."""

from pytest_bdd import scenarios

from tests.bdd.steps.severe_repetition_interactive_recovery_steps import *  # noqa: F403


scenarios("features/severe_repetition_interactive_recovery.feature")
