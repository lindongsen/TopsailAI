"""Gherkin bindings for optional USER.md startup context loading."""

from pytest_bdd import scenarios

from tests.bdd.steps.user_md_loading_steps import *  # noqa: F403


scenarios("features/user_md_loading.feature")
