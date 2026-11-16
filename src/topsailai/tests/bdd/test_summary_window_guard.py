"""Gherkin bindings for the sliding-window summary guard."""

from pytest_bdd import scenarios

from tests.bdd.steps.summary_window_guard_steps import *  # noqa: F403


scenarios("features/summary_window_guard.feature")
