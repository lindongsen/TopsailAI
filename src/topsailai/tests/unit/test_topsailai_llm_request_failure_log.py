"""Per-request LLM failure log contracts. Author: DawsonLin."""

import importlib
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import topsailai.ai_base.llm_base as llm
import topsailai.ai_base.llm_control.request_failure_log as failure_log
from topsailai.ai_base.exception import HardInterruptError, LLMRetryExhaustedError
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy

MODULE = importlib.import_module(
    "topsailai.hooks.points.aibase.after_llm_request_failures.modules.print_failure_log"
)
PREFIX = "[LLMRequestFailureLog]"


@pytest.fixture
def case(monkeypatch):
    """Drive the real chat retry loop while capturing the failure report."""
    model = object.__new__(llm.LLMModel)
    model.tokenStat = SimpleNamespace(current_tokens=0, current_cached_tokens=0)
    model.model_config = {"api_key": "private"}
    model._get_pending_native_tool_call_responses = lambda: deque()
    model._split_native_tool_call_response = lambda obj, content: (obj, content, 1, 1)
    model._return_chat_response = MagicMock(return_value="parsed")
    model._is_special_response_for_retry = lambda error: False
    model.call_llm_model = MagicMock(return_value=(object(), "ok"))
    model.call_llm_model_by_stream = model.call_llm_model

    events, sleeps, console, logged = [], [], [], []
    monkeypatch.setattr(
        llm, "time",
        SimpleNamespace(monotonic=time.monotonic, sleep=sleeps.append),
    )
    monkeypatch.setattr(llm, "get_agent_object", lambda: None)
    # The report Module is re-executed on every dispatch, so it binds these
    # names at call time and the source module is the correct seam. That seam
    # also carries framework output, so only the failure report is captured.
    monkeypatch.setattr(
        "topsailai.utils.print_tool.print_with_time",
        lambda message, **_kwargs: (
            console.append(message)
            if str(message).startswith(PREFIX) else None
        ),
    )
    monkeypatch.setattr(
        "topsailai.logger.log_chat.logger",
        SimpleNamespace(warning=lambda message, *a: logged.append(message)),
    )
    for phase in ("before", "after", "error"):
        def record(_phase=phase, **metadata):
            """Capture attempt hook metadata in emission order."""
            events.append((_phase, metadata))
        monkeypatch.setattr(llm, f"hook__aibase__{phase}__llm_chat_attempt", record)
    return SimpleNamespace(
        model=model, events=events, sleeps=sleeps, console=console, logged=logged,
    )


def _detail_attempts(summary):
    """Return the rendered per-failure detail lines of one summary."""
    return [
        line for line in summary.splitlines()
        if line.startswith(f"{PREFIX}   attempt=")
    ]


def test_success_without_failures_reports_nothing(case):
    """A request that never failed produces no failure output at all."""
    assert case.model.chat([]) == "parsed"
    assert case.console == []
    assert case.logged == []


def test_consecutive_failures_are_reported_once_on_exit(case):
    """Every failed attempt of one request appears in one summary."""
    case.model.call_llm_model.side_effect = [
        TypeError("first failure"),
        ValueError("second failure"),
        (object(), "ok"),
    ]
    assert case.model.chat([], for_raw=True) == "ok"
    assert len(case.console) == 1
    summary = case.console[0]
    assert summary.startswith(f"{PREFIX} operation_id=")
    assert "outcome=success" in summary
    assert "failed_attempts=2" in summary
    assert "last_failed_attempt=2" in summary
    assert "attempt=1 error=TypeError" in summary
    assert "message=first failure" in summary
    assert "attempt=2 error=ValueError" in summary
    assert "message=second failure" in summary
    assert case.logged == [summary]


def test_summary_reuses_the_attempt_operation_id(case):
    """The report correlates with the attempt hook events of the same request."""
    case.model.call_llm_model.side_effect = [TypeError("boom"), (object(), "ok")]
    case.model.chat([], for_raw=True)
    operation_ids = {payload["operation_id"] for _, payload in case.events}
    assert len(operation_ids) == 1
    assert f"operation_id={operation_ids.pop()}" in case.console[0]


def test_exhaustion_reports_failed_outcome_and_keeps_cause(case):
    """A request that exhausts its budget reports every attempt and stays failed."""
    error = TypeError("always failing")
    case.model.call_llm_model.side_effect = error
    with pytest.raises(LLMRetryExhaustedError) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value.__cause__ is error
    assert len(case.console) == 1
    summary = case.console[0]
    assert "outcome=failed" in summary
    assert "failed_attempts=18" in summary
    assert "last_failed_attempt=18" in summary
    assert len(_detail_attempts(summary)) == 10  # bounded console detail
    assert "failure(s) omitted" in summary


def test_console_detail_is_bounded_while_log_keeps_every_failure(case):
    """Long failure runs stay readable on screen but complete in the log."""
    case.model.call_llm_model.side_effect = error = TypeError("always failing")
    with pytest.raises(LLMRetryExhaustedError):
        case.model.chat([], for_raw=True)
    console, logged = case.console[0], case.logged[0]
    assert "failure(s) omitted" in console
    assert "omitted" not in logged
    assert len(_detail_attempts(logged)) == 18
    assert "message=always failing" in logged
    assert str(error) in logged


def test_record_is_cleared_when_the_request_finishes(case):
    """A later request starts from an empty record instead of accumulating."""
    case.model.call_llm_model.side_effect = [TypeError("first request"), (object(), "ok")]
    case.model.chat([], for_raw=True)
    case.model.call_llm_model.side_effect = [(object(), "ok")]
    case.model.chat([], for_raw=True)
    assert len(case.console) == 1
    assert "failed_attempts=1" in case.console[0]
    assert failure_log.current_llm_request_failure_log() is None


def test_no_active_record_outside_a_request(case):
    """Recording outside a request is a no-op instead of an error."""
    failure_log.record_llm_request_failure(1, TypeError("orphan"))
    failure_log.bind_llm_request_operation("orphan")
    assert failure_log.current_llm_request_failure_log() is None


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_host_interrupt_reports_aborted_outcome(case, error):
    """A host interruption still reports the failures it already collected."""
    case.model.call_llm_model.side_effect = [TypeError("before interrupt"), error]
    with pytest.raises(type(error)) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value is error
    assert len(case.console) == 1
    assert "outcome=aborted" in case.console[0]
    assert "failed_attempts=1" in case.console[0]


def test_business_control_error_reports_failed_outcome(case):
    """A domain control error is a failed request, not a host interruption."""
    case.model.call_llm_model.side_effect = [TypeError("boom"), HardInterruptError("stop")]
    with pytest.raises(HardInterruptError):
        case.model.chat([], for_raw=True)
    assert "outcome=failed" in case.console[0]


def test_broken_report_module_never_masks_the_request_error(case, monkeypatch):
    """A failing report Module is isolated by the Hook Point, not propagated."""
    def explode(message, **_kwargs):
        """Fail only while reporting, leaving framework output intact."""
        if str(message).startswith(PREFIX):
            raise RuntimeError("reporter broken")

    monkeypatch.setattr("topsailai.utils.print_tool.print_with_time", explode)
    error = TypeError("request failure")
    case.model.call_llm_model.side_effect = error
    with pytest.raises(LLMRetryExhaustedError) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value.__cause__ is error
    assert case.console == []


def test_broken_dispatch_never_masks_the_request_error(case, monkeypatch):
    """A dispatch failure is swallowed so the request result stays authoritative."""
    def explode(**_payload):
        """Fail while dispatching the report."""
        raise RuntimeError("dispatch broken")

    monkeypatch.setattr(
        failure_log, "hook__aibase__after__llm_request_failures", explode
    )
    # The module bound its logger at import time, so patch that exact binding.
    monkeypatch.setattr(
        failure_log, "logger",
        SimpleNamespace(warning=lambda message, *a: case.logged.append(message)),
    )
    error = TypeError("request failure")
    case.model.call_llm_model.side_effect = error
    with pytest.raises(LLMRetryExhaustedError) as caught:
        case.model.chat([], for_raw=True)
    assert caught.value.__cause__ is error
    assert any("failed to report LLM request failures" in message
               for message in case.logged)


def test_manual_retry_cycle_stays_one_request(case, monkeypatch):
    """A manual retry cycle continues the same record instead of starting a new one."""
    case.model.call_llm_model.side_effect = [TypeError("cycle one")] * 18 + [(object(), "ok")]
    monkeypatch.setattr(llm, "_read_retry_exhaustion_action", lambda *a, **k: "retry")
    policy = LLMRetryInteractionPolicy(
        interactive_enabled=True, input_func=lambda _: "yes", max_manual_retry_cycles=1,
    )
    assert case.model.chat([], for_raw=True, retry_interaction_policy=policy) == "ok"
    assert len(case.console) == 1
    assert "failed_attempts=18" in case.console[0]
    assert "last_failed_attempt=18" in case.console[0]


def test_failure_message_is_collapsed_and_bounded(case):
    """A multi-line provider error becomes one bounded line."""
    message = "line one\nline two\n" + "x" * 500
    case.model.call_llm_model.side_effect = [TypeError(message), (object(), "ok")]
    case.model.chat([], for_raw=True)
    detail = _detail_attempts(case.console[0])
    assert len(detail) == 1
    assert "message=line one line two" in detail[0]
    assert "x" * 500 not in detail[0]
    assert detail[0].endswith("...")


def test_record_cap_marks_unrecorded_failures():
    """The safety cap reports how many failures were not recorded."""
    record = failure_log.LLMRequestFailureLog()
    for attempt in range(failure_log.MAX_RECORDED_FAILURES + 3):
        record.record_failure(attempt + 1, TypeError("many"))
    assert len(record.failures) == failure_log.MAX_RECORDED_FAILURES
    assert record.dropped_failures == 3
    report = record.build_report()
    assert "3 failure(s) not recorded" in MODULE._format(MODULE._header(report), report)


def test_empty_record_emits_nothing():
    """An empty record never prints a summary."""
    record = failure_log.LLMRequestFailureLog()
    record.mark_outcome("success")
    assert record.has_failures() is False
    assert MODULE._header(record.build_report()).startswith(
        f"{PREFIX} operation_id=null"
    )
