"""U11B real Registrar target reload acceptance. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.unified_hook_point_reload_steps import *  # noqa: F403

scenarios("features/unified_hook_point_reload.feature")
