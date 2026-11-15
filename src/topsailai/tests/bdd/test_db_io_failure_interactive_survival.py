"""Database write-failure survival acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.db_io_failure_interactive_survival_steps import *  # noqa: F403

scenarios("features/db_io_failure_interactive_survival.feature")
