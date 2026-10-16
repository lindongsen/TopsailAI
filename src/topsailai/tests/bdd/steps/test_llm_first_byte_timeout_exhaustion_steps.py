"""BDD steps for real U5 first-byte retry exhaustion scenarios."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario, assert_completed_result

_CONTEXTS = {}


@given("a real U5 headers timeout exhaustion scenario")
def headers_scenario(request):
    """Create a scenario retaining response headers before release."""
    _CONTEXTS[request.node.nodeid] = ExhaustionScenario("headers", request.getfixturevalue("monkeypatch"))
    request.addfinalizer(lambda: _close(request))
    _CONTEXTS[request.node.nodeid].prepare()


@given("a real U5 first_item timeout exhaustion scenario")
def first_item_scenario(request):
    """Create a scenario retaining the first decoded entry before release."""
    _CONTEXTS[request.node.nodeid] = ExhaustionScenario("first_item", request.getfixturevalue("monkeypatch"))
    request.addfinalizer(lambda: _close(request))
    _CONTEXTS[request.node.nodeid].prepare()


@when("the U5 production retry loop is executed")
def execute(request):
    """Execute the unchanged production retry loop."""
    scenario = _CONTEXTS[request.node.nodeid]
    scenario.result = scenario.run()


@then("U5 records exactly 18 attempts and 18 requests")
def exact_counts(request):
    """Assert exact production, adapter, and HTTP request counts."""
    scenario = _CONTEXTS.get(request.node.nodeid)
    assert scenario is not None, "missing U5 context"
    assert_completed_result(scenario)


@then("U5 proves terminal settlement and no nineteenth request")
def terminal_settlement(request):
    """Assert final handle settlement and the bounded negative request check."""
    scenario = _CONTEXTS.get(request.node.nodeid)
    assert scenario is not None, "missing U5 context"
    assert_completed_result(scenario)


def _close(request):
    """Release scenario-owned resources after assertions, including failures."""
    scenario = _CONTEXTS.get(request.node.nodeid)
    if scenario is not None:
        scenario.close()
        if scenario.resources.restoration_complete:
            _CONTEXTS.pop(request.node.nodeid, None)
