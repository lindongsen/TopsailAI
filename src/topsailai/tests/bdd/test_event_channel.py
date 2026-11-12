"""Real UDS event-channel acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.event_channel_steps import *  # noqa: F403

scenarios("features/event_channel.feature")
