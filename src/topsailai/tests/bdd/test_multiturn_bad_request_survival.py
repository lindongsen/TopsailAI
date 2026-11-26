"""Multi-turn bad-request survival acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.multiturn_bad_request_survival_steps import *  # noqa: F403

scenarios("features/multiturn_bad_request_survival.feature")
