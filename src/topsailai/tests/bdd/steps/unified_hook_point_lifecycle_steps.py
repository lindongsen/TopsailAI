"""Real target lifecycle business steps. Author: DawsonLin."""
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.temp_storage import BDDTempStorage
from tests.bdd.unified_hook_point_lifecycle_harness import TargetLifecycleScenario


@pytest.fixture
def target_lifecycle_context():
    """Close scenario owners before deleting only their private temporary storage."""
    storage = BDDTempStorage(Path(__file__).resolve().parents[3] / ".tmp" / "u11" / "final")
    context = {"path": storage.create_directory("target-lifecycle-"), "scenario": None}
    try:
        yield context
    finally:
        try:
            if context["scenario"] is not None:
                context["scenario"].close()
        finally:
            storage.cleanup()


@given(parsers.parse("real target lifecycle scripts for {mode}"))
def lifecycle_sources(target_lifecycle_context, mode):
    """Create real executable sources and deployment trust for the scenario."""
    target_lifecycle_context["scenario"] = TargetLifecycleScenario(target_lifecycle_context["path"], mode)


@when("the host awaits the target lifecycle stop boundary")
def lifecycle_stop(target_lifecycle_context):
    """Await the public async execution and its genuine cancellation or deadline."""
    target_lifecycle_context["scenario"].run()


@then("target lifecycle children and custody are settled without successors")
def lifecycle_settled(target_lifecycle_context):
    """Reject live children, later starts, retained debt and captured contents."""
    target_lifecycle_context["scenario"].assert_settled()
