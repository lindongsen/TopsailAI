"""Unique BDD steps for the standalone Unified Hooks runtime boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.unified_hooks_harness import UnifiedHooksScenario


@pytest.fixture
def unified_hooks_ctx(bdd_tmp_path: Path):
    """Own one runtime and close it before B01 removes its directory."""
    context = {"scenario": None, "tmp_path": bdd_tmp_path}
    yield context
    scenario = context["scenario"]
    if scenario is not None:
        scenario.close()


@given(parsers.parse("a standalone Unified Hooks runtime with {binding_state} bindings"))
def given_standalone_runtime(unified_hooks_ctx, binding_state: str):
    """Create an enabled runtime using only its public lifecycle facade."""
    scenario = UnifiedHooksScenario(unified_hooks_ctx["tmp_path"], binding_state)
    unified_hooks_ctx["scenario"] = scenario
    return scenario


@when("the host marks its main flow around one public runtime dispatch")
def when_host_dispatches(unified_hooks_ctx):
    """Drive dispatch through the public runtime boundary."""
    unified_hooks_ctx["scenario"].run_host_flow()


@when("the standalone Unified Hooks runtime is closed")
def when_runtime_is_closed(unified_hooks_ctx):
    """Close all runtime-owned resources through the public lifecycle API."""
    unified_hooks_ctx["scenario"].close()


@then("the host main-flow markers remain intact")
def then_host_markers_remain(unified_hooks_ctx):
    """Confirm optional hook work did not replace host flow continuation."""
    assert unified_hooks_ctx["scenario"].host_markers == ["host-before", "host-after"]


@then(parsers.parse("the {binding_state} Unified Hooks report is observable"))
def then_report_is_observable(unified_hooks_ctx, binding_state: str):
    """Assert the immutable public dispatch report for this skeleton case."""
    scenario = unified_hooks_ctx["scenario"]
    assert scenario.binding_state == binding_state
    scenario.assert_report()


@then("worker launch and handler call counts match the public plan")
def then_worker_and_handler_counts_match(unified_hooks_ctx):
    """Verify separate worker-start and handler-invocation cardinalities."""
    unified_hooks_ctx["scenario"].assert_execution_counts()


@then("the Unified Hooks public lifecycle and observed workers are settled")
def then_observed_workers_are_settled(unified_hooks_ctx):
    """Verify public close reports and exact observed worker process exits."""
    unified_hooks_ctx["scenario"].assert_closed()
