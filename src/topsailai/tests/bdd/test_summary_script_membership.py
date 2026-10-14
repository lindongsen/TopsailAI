"""Real HTTP/SSE mixed summary Script feature. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.summary_script_membership_steps import *  # noqa: F403

scenarios("features/summary_script_membership.feature")
