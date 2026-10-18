"""Business-facing Hook Point result acceptance. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.point_entry_results_steps import *  # noqa: F403

scenarios("features/point_entry_results.feature")
