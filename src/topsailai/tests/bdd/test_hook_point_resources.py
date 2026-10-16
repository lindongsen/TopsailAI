"""Public generic-entry resource BDD suite. Author: DawsonLin."""

from pytest_bdd import scenarios
from tests.bdd.steps.hook_point_resource_steps import *  # noqa: F403

scenarios('features/hook_point_resource_matrix.feature')
scenarios('features/hook_point_resource_edges.feature')
