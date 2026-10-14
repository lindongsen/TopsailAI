"""Mixed summary Script scenario bindings. Author: DawsonLin."""

from pytest_bdd import given, parsers, then, when

from tests.bdd.summary_script_membership_harness import SummaryScriptScenario


@given(parsers.parse("a private {transport} mixed summary {layer} application using {mode} for {case}"),
       target_fixture="mixed_summary")
def mixed_application(monkeypatch, request, tmp_path, layer, case, transport, mode):
    """Own a task-local deployment and real loopback provider before business entry."""
    return SummaryScriptScenario(monkeypatch, request, layer, case, transport, tmp_path, mode)


@when("the mixed summary acceptance path runs")
def run_mixed_summary(mixed_summary):
    """Execute real application summary and checkpoint paths."""
    mixed_summary.exercise()


@then("mixed observers and the real provider prove the unchanged business outcome")
def assert_mixed_summary(mixed_summary):
    """Assert provider records, history, exceptions, reports and process observations."""
    mixed_summary.assert_outcome()
