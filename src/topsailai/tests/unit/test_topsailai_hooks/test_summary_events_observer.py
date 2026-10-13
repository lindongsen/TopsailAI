"""Direct observer safety and failure isolation tests. Author: DawsonLin."""

import inspect
import logging
from types import SimpleNamespace

import pytest

from topsailai.events import collector
from topsailai.hooks.contracts import _thaw_frozen_json
from topsailai.hooks.points.context.summary_contracts import SUMMARY_POINTS
from topsailai.hooks.points.context.summary_payloads import (
    build_summary_hook_context, build_summary_payload,
)
from topsailai.hooks.points.context.summary_events_observer import observer

ACTIVE = tuple(point for point in SUMMARY_POINTS if point.phase_one_eligible)
INACTIVE = tuple(point for point in SUMMARY_POINTS if not point.phase_one_eligible)
FORBIDDEN = ("layer", "path", "messages", "history", "session", "config",
             "environment", "exception", "traceback", "credentials", "secret")


def raw_context(point=ACTIVE[0]):
    """Construct only approved scalar metadata without source or session inputs."""
    extra = {}
    if point.outcome == "error":
        extra = {"error_category": "unknown", "failed_stage": sorted(point.failed_stages)[0]}
    if point.is_apply_error:
        extra["partial_apply_possible"] = True
    return {"event_name": point.name, "event_version": 1, "operation_id": "operation-1",
            "payload": build_summary_payload(point, operation_id="operation-1", **extra)}


def safe_context(point=ACTIVE[0]):
    """Build the actual immutable worker projection for direct observer calls."""
    return build_summary_hook_context(**raw_context(point))


def assert_safe_failure(caplog):
    """Require exactly the constant observer log with no exception or argument data."""
    records = [record for record in caplog.records if record.name == observer.__name__]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "summary_hook_event_record_failed"
    assert not record.args
    assert record.exc_info is None
    assert record.stack_info is None


@pytest.mark.parametrize("point", ACTIVE, ids=lambda point: point.name)
def test_exact_event_for_each_active_point(point, monkeypatch):
    """All eight active points emit one exact detached JSON-safe payload."""
    calls = []
    monkeypatch.setattr(observer, "record_event", lambda **kwargs: calls.append(kwargs))
    context = safe_context(point)
    assert observer.main(hook_context=context) == {"recorded": True}
    expected = raw_context(point)["payload"]
    assert calls == [{"event_type": "summary.hook.observed",
                      "source": "hooks.summary_events_observer", "payload": expected,
                      "flush": True}]
    assert set(calls[0]["payload"]) == point.allowed_fields
    assert not set(FORBIDDEN).intersection(calls[0]["payload"])
    calls[0]["payload"]["operation_id"] = "recorder-mutation"
    assert context["payload"]["operation_id"] == "operation-1"
    with pytest.raises(TypeError):
        context["payload"]["outcome"] = "mutated"


@pytest.mark.parametrize("point", INACTIVE, ids=lambda point: point.name)
def test_phase_two_is_rejected(point, monkeypatch, caplog):
    """An otherwise valid inactive summary payload cannot be observed."""
    calls = []
    monkeypatch.setattr(observer, "record_event", lambda **kwargs: calls.append(kwargs))
    with caplog.at_level(logging.WARNING, logger=observer.__name__):
        assert observer.main(hook_context=raw_context(point)) == {"recorded": False}
    assert calls == []
    assert_safe_failure(caplog)


@pytest.mark.parametrize("case", ["none", "list", "missing", "extra", "generic",
    "version", "bool-version", "operation", "point", "outcome", "schema",
    "payload-list", "oversized", "long-operation", "bad-category", "bad-stage",
    "bad-partial"] + list(FORBIDDEN))
def test_malformed_or_mutated_context_is_isolated(case, monkeypatch, caplog):
    """Reject unsafe mutations before the recorder and avoid logging their contents."""
    context = _thaw_frozen_json(safe_context(ACTIVE[-1]))
    if case == "none":
        context = None
    elif case == "list":
        context = []
    elif case == "missing":
        del context["payload"]
    elif case == "extra":
        context["path"] = "/private/sensitive"
    elif case == "generic":
        context["event_name"] = "generic.event"
    elif case in {"version", "bool-version"}:
        context["event_version"] = True if case == "bool-version" else 2
    elif case == "operation":
        context["operation_id"] = "mismatch"
    elif case == "point":
        context["payload"]["point_name"] = ACTIVE[0].name
    elif case == "outcome":
        context["payload"]["outcome"] = "success"
    elif case == "schema":
        context["payload"]["schema_version"] = 2
    elif case == "payload-list":
        context["payload"] = []
    elif case == "oversized":
        context["payload"]["outcome"] = "敏" * 8192
    elif case == "long-operation":
        context["operation_id"] = context["payload"]["operation_id"] = "x" * 129
    elif case == "bad-category":
        context["payload"]["error_category"] = "sensitive error detail"
    elif case == "bad-stage":
        context["payload"]["failed_stage"] = "sensitive stack detail"
    elif case == "bad-partial":
        context["payload"]["partial_apply_possible"] = "true"
    else:
        context["payload"][case] = "sensitive-value"
    calls = []
    monkeypatch.setattr(observer, "record_event", lambda **kwargs: calls.append(kwargs))
    with caplog.at_level(logging.WARNING, logger=observer.__name__):
        assert observer.main(hook_context=context) == {"recorded": False}
    assert calls == []
    assert_safe_failure(caplog)


@pytest.mark.parametrize("boundary", ["validation", "recorder"])
def test_ordinary_exception_is_safe(boundary, monkeypatch, caplog):
    """Both ordinary failure boundaries acknowledge false without diagnostic leaks."""
    context = safe_context()
    calls = []

    def fail(**kwargs):
        """Raise a sensitive error whose message must not reach observer logging."""
        calls.append(kwargs)
        raise RuntimeError("/private/path password=sensitive traceback secret")

    target = "build_summary_hook_context" if boundary == "validation" else "record_event"
    monkeypatch.setattr(observer, target, fail)
    with caplog.at_level(logging.WARNING, logger=observer.__name__):
        assert observer.main(hook_context=context) == {"recorded": False}
    assert len(calls) == 1
    assert_safe_failure(caplog)


@pytest.mark.parametrize("boundary", ["validation", "recorder"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_interrupt_identity_is_preserved(boundary, error_type, monkeypatch, caplog):
    """Observer never turns process interrupts into ordinary acknowledgements."""
    context = safe_context()
    error = error_type("interrupt")

    def interrupt(**kwargs):
        """Inject the exact interrupt at the selected observer boundary."""
        raise error

    target = "build_summary_hook_context" if boundary == "validation" else "record_event"
    monkeypatch.setattr(observer, target, interrupt)
    with pytest.raises(error_type) as caught:
        observer.main(hook_context=context)
    assert caught.value is error
    assert not [record for record in caplog.records if record.name == observer.__name__]


@pytest.mark.parametrize("result", [None, False])
def test_normal_return_is_not_persistence_acknowledgement(result, monkeypatch):
    """Recorder return value cannot become a durable persistence claim."""
    monkeypatch.setattr(observer, "record_event", lambda **kwargs: result)
    assert observer.main(hook_context=safe_context()) == {"recorded": True}


def test_disabled_real_recorder_acknowledges_without_recording(monkeypatch):
    """The real recorder's disabled branch needs no environment mutation or backend."""
    calls = []
    disabled = SimpleNamespace(enabled=False, record=lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(collector, "get_event_collector", lambda: disabled)
    assert observer.main(hook_context=safe_context()) == {"recorded": True}
    assert calls == []


def test_keyword_only_interface():
    """No raw arguments, configuration, or extra metadata enter the observer API."""
    parameters = inspect.signature(observer.main).parameters
    assert list(parameters) == ["hook_context"]
    assert parameters["hook_context"].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        observer.main(safe_context())
