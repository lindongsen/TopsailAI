"""Business steps for isolated target Hook Points. Author: DawsonLin."""
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.temp_storage import BDDTempStorage
from tests.bdd.unified_hook_point_harness import TargetHookPointScenario


@pytest.fixture
def target_point_context():
    """Own scenario storage and close the runtime before directory deletion."""
    root = Path(__file__).resolve().parents[3] / ".tmp" / "u11" / "final"
    storage = BDDTempStorage(root)
    context = {"path": storage.create_directory("target-point-"), "scenario": None}
    try:
        yield context
    finally:
        try:
            if context["scenario"] is not None:
                context["scenario"].close()
        finally:
            storage.cleanup()


@given(parsers.parse("a real target Hook Point with {mode} sources"))
def target_sources(target_point_context, mode):
    """Create actual trusted Module and Script sources without execution doubles."""
    target_point_context["scenario"] = TargetHookPointScenario(target_point_context["path"], mode)


@when("the host waits for the target Hook Point execution")
def target_execute(target_point_context):
    """Wait through the target public API rather than legacy Binding dispatch."""
    target_point_context["scenario"].run()


@then(parsers.parse("the target business result matches the {mode} acceptance contract"))
def target_result(target_point_context, mode):
    """Validate the exact normal-result partition and business execution order."""
    scenario = target_point_context["scenario"]
    assert scenario.mode == mode
    scenario.assert_business_result()


@then("target process evidence and owned resources are settled")
def target_settled(target_point_context):
    """Check observed probe/handler cardinality, worker exit and resource cleanup."""
    target_point_context["scenario"].assert_settled()
