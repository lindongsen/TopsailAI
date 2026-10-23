"""Standalone contracts only; HTTP/SSE core lifecycle awaits Unit 2. Author: DawsonLin."""

from importlib import import_module
from types import SimpleNamespace

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

import topsailai.hooks as hooks

scenarios("features/llm_chat_attempt_points.feature")


@pytest.fixture
def attempt_case(tmp_path, monkeypatch):
    """Isolate real fixture Modules and restore cached Hook configuration."""
    monkeypatch.setattr(hooks, "_point_configuration", ())
    return SimpleNamespace(root=tmp_path, result=None)


@given(parsers.parse("a standalone {phase} attempt point with a {behavior} Module"))
def configure_attempt(attempt_case, phase, behavior):
    """Configure real on-disk plugin code without stubbing the Hook executor."""
    case = attempt_case
    case.module = import_module(f"topsailai.hooks.points.aibase.{phase}_llm_chat_attempt")
    case.payload = dict(schema_version=1, operation_id="a" * 32, attempt_number=1,
                        point_name=case.module.NAME, outcome=case.module.POINT.phase,
                        stream=True, return_mode="parsed")
    if phase != "before":
        case.payload["duration_sec"] = 0.5
    if phase == "error":
        case.payload["error_category"] = "RuntimeError"
    marker = case.root / "invoked"
    case.marker = marker
    body = (f"from pathlib import Path\ndef main(**payload):\n"
            f"    Path({str(marker)!r}).write_text('called')\n")
    body += "    raise RuntimeError('observer failed')\n" if behavior == "failing" else "    return payload\n"
    plugin = case.root / "observer.py"
    plugin.write_text(body)
    hooks.initialize_hook_points({case.module.NAME: {"modules": str(plugin)}})


@when("the named attempt point receives valid metadata")
def invoke_attempt(attempt_case):
    """Invoke the actual public named entry, not a synthetic business lifecycle."""
    case = attempt_case
    case.result = getattr(case.module, case.module.NAME)(loop_attempts=18, **case.payload)


@then(parsers.parse("the standalone observation has {status} status and exact metadata"))
def check_attempt(attempt_case, status):
    """Results remain observations; only approved scalar kwargs reach Modules."""
    case = attempt_case
    assert case.marker.read_text() == "called"
    assert case.result.status == status
    handler = case.result.handlers[0]
    if status == "success":
        assert handler.returned.value == case.payload
        assert "loop_attempts" not in handler.returned.value
    else:
        assert handler.error.category == "error"
        assert type(handler.error.exception) is RuntimeError
    assert case.result.decision.action == "continue"


@when("the named attempt point receives message content")
def invalid_attempt(attempt_case):
    """Reject unknown content fields before discovery or execution."""
    case = attempt_case
    case.result = getattr(case.module, case.module.NAME)(
        loop_attempts=18, **dict(case.payload, messages="PRIVATE_SENTINEL"))


@then("no standalone Module is invoked")
def no_attempt(attempt_case):
    """Malformed metadata cannot leak to an observer."""
    assert attempt_case.result is None
    assert not attempt_case.marker.exists()
