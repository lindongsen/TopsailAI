"""Gherkin bindings for the opening-observation release."""

from pytest_bdd import scenarios

from tests.bdd.steps.opening_observation_release_steps import *  # noqa: F403


scenarios("features/opening_observation_release.feature")
