"""Unique BDD steps for standalone Unified Hooks reload behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, then, when

from tests.bdd.unified_hooks_reload_harness import UnifiedHooksReloadScenario


@pytest.fixture
def unified_hooks_reload_ctx(bdd_tmp_path: Path):
    """Own one reload Runtime and settle it before B01 removes storage."""
    context = {"scenario": None, "tmp_path": bdd_tmp_path}
    yield context
    scenario = context["scenario"]
    if scenario is not None:
        scenario.close()


@given("a standalone Unified Hooks reload runtime with an admitted old plan")
def given_reload_runtime(unified_hooks_reload_ctx):
    """Create the public Runtime and its initial binding generation."""
    scenario = UnifiedHooksReloadScenario(unified_hooks_reload_ctx["tmp_path"])
    unified_hooks_reload_ctx["scenario"] = scenario
    return scenario


@when("the host changes registrations and reloads settings during real worker execution")
def when_reload_during_execution(unified_hooks_reload_ctx):
    """Reload only after a real old-generation worker confirms admission."""
    unified_hooks_reload_ctx["scenario"].run_reload_during_dispatch()


@when("the Unified Hooks reload runtime is closed")
def when_reload_runtime_closes(unified_hooks_reload_ctx):
    """Close through the public Runtime lifecycle."""
    unified_hooks_reload_ctx["scenario"].close()


@then("the admitted report keeps the old generation and binding plan")
def then_old_admission_is_coherent(unified_hooks_reload_ctx):
    """Assert the old report did not mix post-admission registry state."""
    unified_hooks_reload_ctx["scenario"].assert_reload_and_snapshots()


@then("the later report uses the latest generation and binding plan")
def then_later_admission_is_current(unified_hooks_reload_ctx):
    """Assert a later dispatch sees the replacement and reload generation."""
    unified_hooks_reload_ctx["scenario"].assert_reload_and_snapshots()


@then("no-op and rejected reloads do not advance generation")
def then_reload_generation_is_monotonic(unified_hooks_reload_ctx):
    """Assert only accepted changed publications advance generation."""
    unified_hooks_reload_ctx["scenario"].assert_reload_and_snapshots()


@then("reload leaves the host main flow intact")
def then_reload_preserves_host_flow(unified_hooks_reload_ctx):
    """Assert optional reload and hook work did not replace host flow."""
    unified_hooks_reload_ctx["scenario"].assert_host_flow()


@then("the reload runtime and observed workers are settled")
def then_reload_runtime_is_settled(unified_hooks_reload_ctx):
    """Assert public close and exact worker identity settlement."""
    unified_hooks_reload_ctx["scenario"].assert_closed()
