"""Real UDS heartbeat acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.heartbeat_control_steps import *  # noqa: F403

scenarios("features/heartbeat_control.feature")
