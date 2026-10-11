"""Registrar target reload business steps. Author: DawsonLin."""
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.temp_storage import BDDTempStorage
from tests.bdd.unified_hook_point_reload_harness import RegistrarReloadScenario


@pytest.fixture
def registrar_reload_context():
    """Own the Runtime lifecycle before removing scenario-specific storage."""
    storage = BDDTempStorage(Path(__file__).resolve().parents[3] / ".tmp" / "u11" / "final")
    context = {"path": storage.create_directory("registrar-reload-"), "scenario": None}
    try:
        yield context
    finally:
        try:
            if context["scenario"] is not None:
                context["scenario"].close()
        finally:
            storage.cleanup()


@given(parsers.parse("a real Registrar with {mode} reload sources"))
def registrar_sources(registrar_reload_context, mode):
    """Construct real trusted Scripts and one rejected desired candidate."""
    registrar_reload_context["scenario"] = RegistrarReloadScenario(registrar_reload_context["path"], mode)


@when("the host executes the Registrar reload business flow")
def registrar_flow(registrar_reload_context):
    """Drive real registration, replacement and awaited target Script execution."""
    registrar_reload_context["scenario"].run()


@then("reload workers and captured resources are settled")
def registrar_settled(registrar_reload_context):
    """Assert exact process exits and rejection of unconverged artifact content."""
    registrar_reload_context["scenario"].assert_settled()
