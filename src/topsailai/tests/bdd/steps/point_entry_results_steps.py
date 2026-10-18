"""Real named-entry result behavior with private plugin files. Author: DawsonLin."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

import topsailai.hooks as hooks
from topsailai.hooks.points.workspace.before_input_message import (
    NAME, hook__workspace__before__input_message,
)


@pytest.fixture
def result_case(tmp_path, monkeypatch):
    """Restore configuration and fixture imports after each real invocation."""
    monkeypatch.setattr(hooks, "_point_configuration", ())
    shared = ModuleType("_hook_result_bdd_shared")
    shared.value = {"message": "business value", "count": 3}
    shared.error = RuntimeError("original Module error")
    shared.executed = []
    monkeypatch.setitem(sys.modules, shared.__name__, shared)
    return SimpleNamespace(root=tmp_path, shared=shared, result=None, caught=None)


@given(parsers.parse("result Modules configured for {case} execution"))
def configure(result_case, case):
    """Configure actual source files without replacing the executor or importer."""
    shared = result_case.shared
    controls = {"interrupt": KeyboardInterrupt, "exit": SystemExit,
                "cancel": asyncio.CancelledError}
    if case in controls:
        shared.error = controls[case]("host control flow")
    prefix = "import _hook_result_bdd_shared as shared\n"
    if case == "import":
        body = "raise shared.error\n"
    elif case == "normal":
        body = "def main():\n    shared.executed.append('first')\n    return shared.value\n"
    else:
        declaration = "async def" if case == "async" else "def"
        body = f"{declaration} main():\n    raise shared.error\n"
    first = result_case.root / "a_result.py"
    first.write_text(prefix + body)
    second = result_case.root / "z_result.py"
    second.write_text(prefix + "def main():\n    shared.executed.append('later')\n    return shared.value\n")
    hooks.initialize_hook_points({NAME: {"modules": [str(second), str(first)]}})


@when("the caller invokes the named input Hook Point")
def invoke(result_case):
    """Capture only at the business test boundary, never inside the executor."""
    try:
        result_case.result = hook__workspace__before__input_message()
    except BaseException as error:
        result_case.caught = error


@then("the original normal value is accessible in a successful envelope")
def normal(result_case):
    """Normal return presence, identity and order remain independent of errors."""
    assert result_case.caught is None
    result = result_case.result
    assert result.status == "success"
    first, later, terminal = result.handlers
    assert [item.handler.name for item in result.handlers] == ["a_result.py", "z_result.py", "hook_script"]
    for handler in (first, later):
        assert handler.status == "success" and handler.error is None
        assert handler.returned.present
        assert handler.returned.value is result_case.shared.value
    assert terminal.children == () and terminal.status == "success"
    assert result_case.shared.executed == ["first", "later"]


@then("the original exception is accessible and the next Module still succeeds")
def exceptional(result_case):
    """Identity, traceback and continuation prove a live error reached the caller."""
    assert result_case.caught is None
    result = result_case.result
    assert result.status == "completed_with_errors"
    first, later, terminal = result.handlers
    assert first.status == "error" and not first.returned.present
    assert first.not_run_reason is None
    assert first.error.category == "error"
    assert first.error.exception is result_case.shared.error
    assert first.error.exception.__traceback__ is not None
    assert "original Module error" not in first.error.message
    assert later.status == "success" and later.error is None
    assert later.returned.value is result_case.shared.value
    assert result_case.shared.executed == ["later"]
    assert terminal.status == "success" and terminal.children == ()
    assert first.cleanup.state == result.cleanup.state == "safe"
    assert first.decision.action == result.decision.action == "continue"


@then("the exact host interruption propagates instead of an envelope")
def interrupted(result_case):
    """Host interruption identity and noncontinuation are unchanged."""
    assert result_case.caught is result_case.shared.error
    assert result_case.result is None
    assert result_case.shared.executed == []


@then("the failure is logged with its exception and invocation identity")
def failure_logged(result_case, caplog):
    """Prove the real named entry logs the same exception delivered to the caller."""
    result = result_case.result
    records = [record for record in caplog.records if record.msg.startswith("Hook resource failed")]
    record, = records
    assert record.levelname == "ERROR" and record.created > 0
    assert NAME in record.getMessage() and result.execution_id in record.getMessage()
    assert "handler=module:a_result.py" in record.getMessage()
    assert record.exc_info[1] is result_case.shared.error
    assert "RuntimeError: original Module error" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
