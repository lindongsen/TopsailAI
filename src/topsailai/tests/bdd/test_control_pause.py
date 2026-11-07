"""Real control-channel pause acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.control_pause_steps import *  # noqa: F403

scenarios("features/control_pause.feature")
