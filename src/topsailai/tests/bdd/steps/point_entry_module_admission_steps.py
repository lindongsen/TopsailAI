"""Gherkin bindings for live point_entry Module admission. Author: DawsonLin."""

import logging

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.point_entry_module_admission_harness import AdmissionScenario, WORKSPACE
from tests.bdd.temp_storage import BDDTempStorage


@pytest.fixture
def admission_case():
    """Always settle the owned child and remove only the owned private tree."""
    storage = BDDTempStorage(WORKSPACE / '.tmp/point-entry-admission-bdd')
    root = storage.create_directory('scenario-')
    context = AdmissionScenario(root)
    try:
        yield context
    finally:
        context.close()
        storage.cleanup()
        assert not context.root.exists()


@given(parsers.parse('a live point entry fixture {case}'))
def fixture(admission_case, case):
    """Build one named admission boundary in the private live point tree."""
    admission_case.prepare(case)


@when('the business invokes the public named Hook Point')
def invoke(admission_case):
    """Run the real decode_points/execute_point path in a fresh child process."""
    admission_case.execute()


@then('exact module admission evidence matches the declaration')
def verify(admission_case):
    """Check live-tree origin, admission results and settled process ownership."""
    admission_case.verify()
    logging.getLogger(__name__).info('verified admission case %s', admission_case.case)
