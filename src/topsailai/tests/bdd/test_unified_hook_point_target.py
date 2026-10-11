"""U11A target-runtime Gherkin acceptance. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.unified_hook_point_target_steps import *  # noqa: F403

scenarios("features/unified_hook_point_target.feature")
