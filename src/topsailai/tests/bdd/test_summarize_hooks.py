"""Real HTTP/SSE summarize Hooks feature entry. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.summarize_hooks_steps import *  # noqa: F403


scenarios('features/summarize_hooks.feature')
