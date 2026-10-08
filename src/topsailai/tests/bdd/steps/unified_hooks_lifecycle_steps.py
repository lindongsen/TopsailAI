"""Unique BDD steps for bounded standalone Unified Hooks lifecycle behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.unified_hooks_lifecycle_harness import UnifiedHooksLifecycleScenario


@pytest.fixture
def unified_hooks_lifecycle_ctx(bdd_tmp_path: Path):
    """Own one lifecycle runtime and close it before B01 removes its directory."""
    context = {"scenario": None, "tmp_path": bdd_tmp_path}
    yield context
    scenario = context["scenario"]
    if scenario is not None:
        scenario.close()


@given(parsers.parse("a standalone Unified Hooks lifecycle runtime for {state}"))
def given_lifecycle_runtime(unified_hooks_lifecycle_ctx, state: str):
    """Create one standalone Runtime through its public construction boundary."""
    scenario = UnifiedHooksLifecycleScenario(unified_hooks_lifecycle_ctx["tmp_path"], state)
    unified_hooks_lifecycle_ctx["scenario"] = scenario
    return scenario


@when("the host dispatches one event to a deterministically stalled worker")
def when_timeout_dispatch_runs(unified_hooks_lifecycle_ctx):
    """Run the real worker until its public deadline settles it."""
    unified_hooks_lifecycle_ctx["scenario"].run_timeout()


@when("the host cancels public asynchronous dispatch after the worker starts")
def when_host_cancels(unified_hooks_lifecycle_ctx):
    """Cancel public adispatch only after FIFO readiness is observed."""
    unified_hooks_lifecycle_ctx["scenario"].run_cancellation()


@when("the lifecycle runtime is closed after settlement")
def when_lifecycle_runtime_closes(unified_hooks_lifecycle_ctx):
    """Close through the public lifecycle after the dispatch has settled."""
    unified_hooks_lifecycle_ctx["scenario"].close_after_settlement()


@when("the host closes the runtime with a finite deadline during real worker execution")
def when_host_closes_during_execution(unified_hooks_lifecycle_ctx):
    """Exercise bounded and repeated public close around owned real work."""
    unified_hooks_lifecycle_ctx["scenario"].run_bounded_close()
    unified_hooks_lifecycle_ctx["scenario"].close_after_settlement()


@then("the timeout report preserves the host main flow")
def then_timeout_report(unified_hooks_lifecycle_ctx):
    """Assert the timeout outcome remains optional to host continuation."""
    unified_hooks_lifecycle_ctx["scenario"].assert_timeout()


@then("only the timed-out worker started")
def then_timeout_only_started(unified_hooks_lifecycle_ctx):
    """Keep the explicit cardinality assertion visible in the scenario."""
    unified_hooks_lifecycle_ctx["scenario"]._assert_one_stalled_call()


@then("host cancellation propagates boundedly before cooperative worker release")
def then_cancellation_propagates(unified_hooks_lifecycle_ctx):
    """Assert bounded propagation is distinct from cooperative settlement."""
    unified_hooks_lifecycle_ctx["scenario"].assert_cancellation()


@then("only the cancelled dispatch worker started")
def then_cancelled_only_started(unified_hooks_lifecycle_ctx):
    """Assert cancellation did not start the successor binding."""
    unified_hooks_lifecycle_ctx["scenario"]._assert_one_stalled_call()


@then("bounded close returns with pending host work diagnostics")
def then_close_is_bounded(unified_hooks_lifecycle_ctx):
    """Assert close reports pending host ownership diagnostically."""
    unified_hooks_lifecycle_ctx["scenario"].assert_bounded_close()


@then("repeated close is idempotent and later dispatch is rejected")
def then_repeated_close(unified_hooks_lifecycle_ctx):
    """Assert public repeated-close and post-close admission contracts."""
    unified_hooks_lifecycle_ctx["scenario"].assert_bounded_close()


@then("the original host flow settles without starting a successor")
def then_original_settles(unified_hooks_lifecycle_ctx):
    """Assert only the already-running delivery existed after close."""
    unified_hooks_lifecycle_ctx["scenario"].assert_original_settled()


@then("the lifecycle public close report and observed worker are settled")
def then_lifecycle_settled(unified_hooks_lifecycle_ctx):
    """Assert public close evidence and exact observed process exits."""
    unified_hooks_lifecycle_ctx["scenario"].assert_closed()
