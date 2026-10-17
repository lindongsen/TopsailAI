"""Gherkin bindings for live point_entry resource edges. Author: DawsonLin."""

import logging

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.point_entry_resource_edges_harness import ResourceEdgeScenario, WORKSPACE
from tests.bdd.temp_storage import BDDTempStorage


@pytest.fixture
def resource_edge_case():
    """Always settle the owned child and remove only the owned private tree."""
    storage = BDDTempStorage(WORKSPACE / '.tmp/point-entry-resource-edges-bdd')
    root = storage.create_directory('scenario-')
    context = ResourceEdgeScenario(root)
    try:
        yield context
    finally:
        context.close()
        storage.cleanup()
        assert not context.root.exists()


@given(parsers.parse('a live point entry resource fixture {case}'))
def fixture(resource_edge_case, case):
    """Build one named resource edge in the private live point tree."""
    resource_edge_case.prepare(case)


@when('the business invokes the public named Hook Point')
def invoke(resource_edge_case):
    """Run the real decode_points/execute_point path in a fresh child process."""
    resource_edge_case.execute()


@then('exact resource edge evidence matches the declaration')
def verify(resource_edge_case):
    """Check live-tree origin, edge results and settled process ownership."""
    resource_edge_case.verify()
    logging.getLogger(__name__).info('verified resource edge case %s', resource_edge_case.case)
