"""U11C target awaited lifecycle acceptance. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.unified_hook_point_lifecycle_steps import *  # noqa: F403

scenarios("features/unified_hook_point_lifecycle.feature")
