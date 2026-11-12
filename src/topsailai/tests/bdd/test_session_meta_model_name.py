"""Gherkin bindings for session metadata model-name projection."""

from pytest_bdd import scenarios

from tests.bdd.steps.session_meta_model_name_steps import *  # noqa: F403


scenarios("features/session_meta_model_name.feature")
