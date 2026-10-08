"""Gherkin bindings for the standalone Unified Hooks runtime boundary."""

from pytest_bdd import scenarios

from tests.bdd.steps.unified_hooks_runtime_steps import *  # noqa: F403


scenarios("features/unified_hooks_runtime.feature")
