"""On-disk events file acceptance scenarios. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.event_source_file_steps import *  # noqa: F403

scenarios("features/event_source_file.feature")
