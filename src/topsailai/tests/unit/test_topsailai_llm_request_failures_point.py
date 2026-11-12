"""LLM request failure report Hook contracts. Author: DawsonLin."""

import importlib
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.points.aibase.after_llm_request_failures import (
    hook__aibase__after__llm_request_failures,
)
from topsailai.hooks.points.aibase.after_llm_request_failures.point import (
    FAILURE_MESSAGE_MAX_CHARS,
    MAX_FAILURES,
    MESSAGE_MAX_CHARS,
    NAME,
    POINT,
)
from topsailai.hooks.points.aibase.after_llm_request_failures.payloads import (
    build_payload,
)

MODULE = importlib.import_module(
    "topsailai.hooks.points.aibase.after_llm_request_failures.modules.print_failure_log"
)
PREFIX = "[LLMRequestFailureLog]"


def payload(**overrides):
    """Create the exact approved field set of one failure report."""
    value = {
        "schema_version": 1,
        "operation_id": "a" * 32,
        "outcome": "success",
        "failed_attempts": 1,
        "last_failed_attempt": 1,
        "elapsed_sec": 1.5,
        "dropped_failures": 0,
        "failures": [
            {"attempt": 1, "error": "TypeError", "duration_sec": 0.5, "message": "boom"},
        ],
    }
    value.update(overrides)
    return value


def test_declaration():
    """The point name, phase mapping and budget import and validate cleanly."""
    assert re.fullmatch(r"hook__aibase__after__llm_request_failures", NAME)
    assert NAME == POINT.definition.name == POINT.name
    assert POINT.phase == "success"
    assert POINT.failure_policy == "report"
    assert POINT.definition.major_version == 1
    assert POINT.definition.payload_limit_bytes == 65_536
    assert POINT.latency_budget_ms == 1_000
    with pytest.raises(ValueError):
        replace(POINT, phase="error")
    with pytest.raises(ValueError):
        replace(POINT, definition=replace(POINT.definition, name="other"))


def test_valid_payload_is_detached():
    """A valid report is accepted and returned detached from caller state."""
    value = payload()
    detached = build_payload(value)
    assert detached == value
    assert detached is not value
    assert detached["failures"] is not value["failures"]
    assert detached["failures"][0] is not value["failures"][0]


def test_unbound_operation_id_is_accepted():
    """A request that never bound an operation id still reports."""
    assert build_payload(payload(operation_id=""))["operation_id"] == ""


@pytest.mark.parametrize("outcome", ["success", "failed", "aborted"])
def test_every_outcome_is_accepted(outcome):
    """All three request outcomes are valid report values."""
    assert build_payload(payload(outcome=outcome))["outcome"] == outcome


def test_empty_failure_list_is_accepted():
    """A report with no failures is structurally valid but renders nothing."""
    value = payload(failed_attempts=0, last_failed_attempt=0, failures=[])
    assert build_payload(value)["failures"] == []


@pytest.mark.parametrize("mutation, token", [
    (lambda v: v.pop("outcome"), "invalid_failure_report_fields"),
    (lambda v: v.update(extra=1), "invalid_failure_report_fields"),
    (lambda v: v.update(schema_version=2), "invalid_schema_version"),
    (lambda v: v.update(schema_version=True), "invalid_schema_version"),
    (lambda v: v.update(operation_id="A" * 32), "invalid_operation_id"),
    (lambda v: v.update(operation_id="a" * 31), "invalid_operation_id"),
    (lambda v: v.update(operation_id=None), "invalid_operation_id"),
    (lambda v: v.update(outcome="unknown"), "invalid_outcome"),
    (lambda v: v.update(outcome=None), "invalid_outcome"),
    (lambda v: v.update(failed_attempts=2), "invalid_failed_attempts"),
    (lambda v: v.update(failed_attempts=True), "invalid_failed_attempts"),
    (lambda v: v.update(last_failed_attempt=7), "invalid_last_failed_attempt"),
    (lambda v: v.update(dropped_failures=-1), "invalid_dropped_failures"),
    (lambda v: v.update(elapsed_sec=-1), "invalid_elapsed"),
    (lambda v: v.update(elapsed_sec=float("nan")), "invalid_elapsed"),
    (lambda v: v.update(elapsed_sec=float("inf")), "invalid_elapsed"),
    (lambda v: v.update(elapsed_sec="1.5"), "invalid_elapsed"),
    (lambda v: v.update(failures="none"), "invalid_failures"),
])
def test_invalid_report_is_rejected(mutation, token):
    """Each malformed report field fails with its stable rejection token."""
    value = payload()
    mutation(value)
    with pytest.raises(ValueError) as caught:
        build_payload(value)
    assert token in str(caught.value)


@pytest.mark.parametrize("mutation, token", [
    (lambda f: f.pop("message"), "invalid_failure_fields"),
    (lambda f: f.update(extra=1), "invalid_failure_fields"),
    (lambda f: f.update(attempt=0), "invalid_failure_attempt"),
    (lambda f: f.update(attempt="1"), "invalid_failure_attempt"),
    (lambda f: f.update(error=""), "invalid_failure_error"),
    (lambda f: f.update(error="x" * 129), "invalid_failure_error"),
    (lambda f: f.update(message="x" * (MESSAGE_MAX_CHARS + 1)), "invalid_failure_message"),
    (lambda f: f.update(message="line one\nline two"), "invalid_failure_message"),
    (lambda f: f.update(duration_sec=-0.5), "invalid_elapsed"),
])
def test_invalid_failure_entry_is_rejected(mutation, token):
    """Each malformed failure entry fails with its stable rejection token."""
    value = payload()
    mutation(value["failures"][0])
    with pytest.raises(ValueError) as caught:
        build_payload(value)
    assert token in str(caught.value)


def test_failure_count_cap_is_enforced():
    """A report cannot exceed the declared failure cap."""
    value = payload(
        failed_attempts=MAX_FAILURES + 1,
        last_failed_attempt=MAX_FAILURES + 1,
        failures=[
            {"attempt": index + 1, "error": "TypeError",
             "duration_sec": 0.0, "message": "boom"}
            for index in range(MAX_FAILURES + 1)
        ],
    )
    with pytest.raises(ValueError) as caught:
        build_payload(value)
    assert "invalid_failures" in str(caught.value)


def test_message_limit_matches_the_declared_truncation():
    """The accepted message length equals the truncation limit plus its suffix."""
    assert MESSAGE_MAX_CHARS == FAILURE_MESSAGE_MAX_CHARS + 3
    value = payload()
    value["failures"][0]["message"] = "x" * MESSAGE_MAX_CHARS
    assert build_payload(value)["failures"][0]["message"] == "x" * MESSAGE_MAX_CHARS


def _capture(monkeypatch):
    """Patch the already-imported Module bindings and return both sinks."""
    console, logged = [], []
    monkeypatch.setattr(
        MODULE, "print_with_time",
        lambda message, **_kwargs: console.append(message),
    )
    monkeypatch.setattr(
        MODULE, "logger",
        SimpleNamespace(warning=lambda message, *a: logged.append(message)),
    )
    return console, logged


def test_module_prints_bounded_console_and_complete_log(monkeypatch):
    """The console keeps the first and last failures while the log keeps all."""
    console, logged = _capture(monkeypatch)
    failures = [
        {"attempt": index + 1, "error": "TypeError",
         "duration_sec": 0.0, "message": f"failure {index + 1}"}
        for index in range(18)
    ]
    MODULE.main(**payload(
        outcome="failed", failed_attempts=18, last_failed_attempt=18, failures=failures,
    ))
    assert len(console) == 1 and len(logged) == 1
    assert "failure(s) omitted" in console[0]
    assert "omitted" not in logged[0]
    assert console[0].splitlines()[0] == logged[0].splitlines()[0]
    assert len(_attempts(logged[0])) == 18
    assert _attempts(console[0]) == [1, 2, 3, 4, 5, 14, 15, 16, 17, 18]


def _attempts(summary):
    """Return the rendered attempt numbers of one summary."""
    return [
        int(line.split("attempt=")[1].split()[0])
        for line in summary.splitlines()
        if line.startswith(f"{PREFIX}   attempt=")
    ]


def test_module_prints_nothing_without_failures(monkeypatch):
    """A clean request produces no console output and no log entry."""
    console, logged = _capture(monkeypatch)
    MODULE.main(**payload(failed_attempts=0, last_failed_attempt=0, failures=[]))
    assert console == [] and logged == []


def test_module_reports_unrecorded_failures(monkeypatch):
    """A capped record states how many failures were not recorded."""
    console, _ = _capture(monkeypatch)
    MODULE.main(**payload(dropped_failures=3))
    assert "3 failure(s) not recorded" in console[0]


def test_module_isolates_its_own_failure(monkeypatch):
    """A broken renderer is isolated by the point and never propagates."""
    def explode(*_args, **_kwargs):
        """Fail while rendering."""
        raise RuntimeError("renderer broken")

    monkeypatch.setattr("topsailai.utils.print_tool.print_with_time", explode)
    result = hook__aibase__after__llm_request_failures(**payload())
    # The Module failure is contained in the result instead of being raised.
    assert result.status == "completed_with_errors"
    failed = [handler for handler in result.handlers if handler.status == "error"]
    assert [handler.handler.name for handler in failed] == ["print_failure_log.py"]


def test_point_dispatches_the_module(monkeypatch):
    """The named entry validates and dispatches the bundled Module."""
    console = []
    monkeypatch.setattr(
        "topsailai.utils.print_tool.print_with_time",
        lambda message, **_kwargs: console.append(message),
    )
    monkeypatch.setattr(
        "topsailai.logger.log_chat.logger", SimpleNamespace(warning=lambda *a: None),
    )
    result = hook__aibase__after__llm_request_failures(**payload())
    assert result.status == "success"
    assert len(console) == 1
    assert console[0].startswith(f"{PREFIX} operation_id={'a' * 32}")


def test_point_rejects_invalid_metadata_without_dispatch(monkeypatch):
    """Invalid metadata is rejected before any Module runs."""
    calls = []
    monkeypatch.setattr(hooks, "invoke_hook_point", lambda *a, **k: calls.append(a))
    assert hook__aibase__after__llm_request_failures(**payload(outcome="unknown")) is None
    assert calls == []
