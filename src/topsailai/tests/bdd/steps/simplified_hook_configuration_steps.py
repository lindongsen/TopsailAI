"""BDD steps for simplified configured Hook registration and execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, then, when

from tests.bdd.simplified_hook_configuration_harness import SimplifiedHookScenario


@pytest.fixture
def simplified_hook_ctx(bdd_tmp_path: Path):
    """Own and close one simplified configured Hook scenario."""
    context = {"scenario": None, "mode": None}
    yield context
    if context["scenario"] is not None:
        context["scenario"].close()


def _given(simplified_hook_ctx, bdd_tmp_path: Path, mode: str):
    """Create one scenario in the requested public registration mode."""
    scenario = SimplifiedHookScenario(bdd_tmp_path, mode)
    simplified_hook_ctx.update(scenario=scenario, mode=mode)
    return scenario


@given("a simplified Hook runtime configured with ordered scripts")
def given_scripts(simplified_hook_ctx, bdd_tmp_path):
    """Register an explicit ordered script list."""
    return _given(simplified_hook_ctx, bdd_tmp_path, "scripts")


@given("a simplified Hook runtime configured from a recursive folder")
def given_folder(simplified_hook_ctx, bdd_tmp_path):
    """Register scripts discovered from nested folders."""
    return _given(simplified_hook_ctx, bdd_tmp_path, "folder")


@given("a simplified Hook runtime configured for exact-name selection")
def given_exact(simplified_hook_ctx, bdd_tmp_path):
    """Register a plan used to prove exact name matching."""
    return _given(simplified_hook_ctx, bdd_tmp_path, "exact")


@given("a simplified Hook runtime with an atomically replaced plan")
def given_replacement(simplified_hook_ctx, bdd_tmp_path):
    """Replace an initial plan with a valid new plan."""
    return _given(simplified_hook_ctx, bdd_tmp_path, "replacement")


@when("the configured Hook is executed through its exact public name")
def when_execute_exact(simplified_hook_ctx):
    """Execute the selected plan through the public API."""
    simplified_hook_ctx["scenario"].execute()


@when("the configured Hook is executed through a different valid name")
def when_execute_different(simplified_hook_ctx):
    """Execute with a valid but unregistered exact name."""
    simplified_hook_ctx["scenario"].execute("hook_bdd_other")


@when("a later invalid replacement is rejected")
def when_replacement_rejected(simplified_hook_ctx):
    """Attempt and observe one failed all-or-nothing replacement."""
    simplified_hook_ctx["scenario"].reject_invalid_replacement()


@then("the configured Hook execution succeeds in name order")
def then_explicit_order(simplified_hook_ctx):
    """Observe target name ordering from real processes despite reversed input."""
    simplified_hook_ctx["scenario"].assert_success(["a", "z"])


@then("the configured Hook execution succeeds in folder order")
def then_folder_order(simplified_hook_ctx):
    """Observe normalized relative-path folder ordering."""
    simplified_hook_ctx["scenario"].assert_success(["a", "new", "z"])


@then("the configured Hook execution is rejected as unknown")
def then_unknown(simplified_hook_ctx):
    """Observe exact-name rejection without executing any script."""
    scenario = simplified_hook_ctx["scenario"]
    assert scenario.report.rejection_reason == "unknown_configured_hook"
    assert scenario.lines() == []


@then("the replacement plan remains active")
def then_replacement_active(simplified_hook_ctx):
    """Observe the last successfully published plan after replacement failure."""
    simplified_hook_ctx["scenario"].assert_success(["new"])


@then("closing the simplified Hook runtime removes its captured artifacts")
def then_cleanup(simplified_hook_ctx):
    """Close Runtime ownership and prove captured resources are gone."""
    scenario = simplified_hook_ctx["scenario"]
    scenario.close()
    scenario.assert_cleanup()
