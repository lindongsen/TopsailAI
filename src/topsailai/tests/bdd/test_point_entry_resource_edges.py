"""Live point_entry resource edge BDD suite. Author: DawsonLin."""

from pytest_bdd import scenarios

from tests.bdd.steps.point_entry_resource_edges_steps import *  # noqa: F403

scenarios('features/point_entry_resource_edges.feature')
