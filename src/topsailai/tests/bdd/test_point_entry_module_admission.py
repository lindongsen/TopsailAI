"""Live point_entry Module admission BDD suite. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.point_entry_module_admission_steps import *  # noqa: F403

scenarios('features/point_entry_module_admission.feature')
