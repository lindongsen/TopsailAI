"""Real Catalog wrapper steps. Author: DawsonLin."""
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.configured_hook_readiness_harness import CatalogWrapperScenario
from tests.bdd.temp_storage import BDDTempStorage


@pytest.fixture
def catalog_wrapper_context():
    """Close scenario resources before removing only owned storage."""
    storage = BDDTempStorage(Path(__file__).resolve().parents[3] / ".tmp" / "u11" / "final")
    context = {"path": storage.create_directory("catalog-wrapper-"), "scenario": None}
    try:
        yield context
    finally:
        try:
            if context["scenario"] is not None:
                context["scenario"].close()
        finally:
            storage.cleanup()


@given(parsers.parse("a real {mode} Catalog wrapper for {case}"))
def catalog_wrapper(catalog_wrapper_context, mode, case):
    """Build real declarations and trusted process sources."""
    catalog_wrapper_context["scenario"] = CatalogWrapperScenario(catalog_wrapper_context["path"], mode, case)


@when("the host executes the decorated business operation")
def catalog_business(catalog_wrapper_context):
    """Assert business policy through actual configured execution."""
    catalog_wrapper_context["scenario"].run()


@then("wrapper workers and captures converge without changing business facts")
def catalog_settled(catalog_wrapper_context):
    """Assert exact process exits and custody convergence."""
    catalog_wrapper_context["scenario"].assert_settled()
