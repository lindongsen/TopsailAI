"""Summarize Hooks acceptance bindings. Author: DawsonLin."""

from pytest_bdd import given, parsers, then, when

from tests.bdd.summarize_hooks_harness import SummarizeHooksScenario


@given(parsers.parse('a private {transport} summarize Hooks {layer} application for {case}'),
       target_fixture='summarize_hooks_ctx')
def summary_application(monkeypatch, request, layer, case, transport):
    """Allocate one private provider and typed configured application."""
    return SummarizeHooksScenario(monkeypatch, request, layer, case, transport)


@when('the summarize Hooks acceptance path runs')
def run_summary_acceptance(summarize_hooks_ctx):
    """Exercise production startup, session finalization, or summary application."""
    summarize_hooks_ctx.exercise()


@then('the provider and managed observers prove the approved summary outcome')
def assert_summary_acceptance(summarize_hooks_ctx):
    """Verify wire evidence and lifecycle outcomes rather than internal call counts."""
    summarize_hooks_ctx.assert_outcome()
