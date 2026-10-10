"""BDD entry point for Hook framework readiness wrappers."""

from pytest_bdd import scenarios

from tests.bdd.steps.hook_framework_readiness_steps import *  # noqa: F403

scenarios("features/hook_framework_readiness.feature")
