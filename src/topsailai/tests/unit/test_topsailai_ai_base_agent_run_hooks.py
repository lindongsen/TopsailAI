"""Unit tests for Agent2LLM run lifecycle Hook Points. Author: DawsonLin."""

import asyncio
import logging
import shutil
import uuid
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from topsailai.ai_base.agent_base import AgentBase
from topsailai.hooks.points.aibase.after_agent_run.point import (
    NAME as AFTER_NAME,
    POINT as AFTER_POINT,
)
from topsailai.hooks.points.aibase.before_agent_run.point import (
    NAME as BEFORE_NAME,
    POINT as BEFORE_POINT,
)
logger = logging.getLogger(__name__)
_TEST_TMP_ROOT = Path("/TopsailAI/src/topsailai/.tmp")


@pytest.fixture
def hook_tmp_dir():
    """Create and remove one owned temporary Hook-resource directory."""
    path = _TEST_TMP_ROOT / f"agent-run-hook-test-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        if path.exists():
            for child in sorted(path.rglob("*"), reverse=True):
                logger.info("Deleting test-owned temporary path: %s", child)
            logger.info("Deleting test-owned temporary directory: %s", path)
            shutil.rmtree(path)


from topsailai.hooks.points.aibase.error_agent_run.point import (
    NAME as ERROR_NAME,
    POINT as ERROR_POINT,
)


class _StepCall:
    """Minimal step-call stand-in for lifecycle metadata tests."""


def _agent(run):
    """Build an AgentBase instance without initializing external services."""
    agent = AgentBase.__new__(AgentBase)
    agent.agent_name = "test-agent"
    agent.llm_model = type("Model", (), {})()
    agent.llm_model.clear_pending_native_tool_call_responses = lambda: None
    agent._run = run
    agent.flag_dump_messages = False
    return agent


def _contexts():
    """Return inert context-manager patches for the run boundary."""
    return {
        "topsailai.ai_base.agent_base.ctxm_give_agent_name": lambda *args, **kwargs: nullcontext(),
        "topsailai.ai_base.agent_base.ctxm_set_agent": lambda *args, **kwargs: nullcontext(),
    }


def test_run_calls_before_and_after_once_and_preserves_none_result():
    """Normal None completion emits one before and one after point."""
    events = []
    agent = _agent(lambda *_: None)
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run":
            lambda **payload: events.append(("before", payload)),
        "topsailai.ai_base.agent_base.hook__aibase__after__agent_run":
            lambda **payload: events.append(("after", payload)),
        "topsailai.ai_base.agent_base.hook__aibase__error__agent_run":
            lambda **payload: events.append(("error", payload)),
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        assert agent.run(_StepCall(), "input") is None

    assert [event[0] for event in events] == ["before", "after"]
    assert events[0][1]["operation_id"] == events[1][1]["operation_id"]
    assert events[1][1]["result_kind"] == "none"


def test_run_emits_error_once_and_preserves_exception_identity():
    """Ordinary errors reach error once and retain the original exception."""
    error = RuntimeError("business failure")
    observed = []
    agent = _agent(lambda *_: (_ for _ in ()).throw(error))
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run":
            lambda **payload: observed.append(("before", payload)),
        "topsailai.ai_base.agent_base.hook__aibase__after__agent_run":
            lambda **payload: observed.append(("after", payload)),
        "topsailai.ai_base.agent_base.hook__aibase__error__agent_run":
            lambda **payload: observed.append(("error", payload)),
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        with pytest.raises(RuntimeError) as raised:
            agent.run(_StepCall(), "input")

    assert raised.value is error
    assert [event[0] for event in observed] == ["before", "error"]
    assert observed[-1][1]["error_category"] == "RuntimeError"


@pytest.mark.parametrize("control_flow", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_run_does_not_convert_host_control_flow(control_flow):
    """Host control flow propagates without an error Hook."""
    observed = []
    agent = _agent(lambda *_: (_ for _ in ()).throw(control_flow()))
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run":
            lambda **payload: observed.append("before"),
        "topsailai.ai_base.agent_base.hook__aibase__error__agent_run":
            lambda **payload: observed.append("error"),
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        with pytest.raises(control_flow):
            agent.run(_StepCall(), "input")

    assert observed == ["before"]


def test_hook_failure_does_not_change_business_result():
    """A failing observation call does not replace a normal business result."""
    agent = _agent(lambda *_: "business-result")
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run":
            lambda **payload: None,
        "topsailai.ai_base.agent_base.hook__aibase__after__agent_run":
            lambda **payload: {"status": "error"},
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        assert agent.run(_StepCall(), "input") == "business-result"


def test_payloads_are_metadata_only_and_point_names_match_event_names():
    """Payload builders omit business objects and declarations use one name."""
    from topsailai.hooks.points.aibase.after_agent_run.payloads import build_payload as after
    from topsailai.hooks.points.aibase.before_agent_run.payloads import build_payload as before
    from topsailai.hooks.points.aibase.error_agent_run.payloads import build_payload as error

    payloads = [
        before(operation_id="op", agent_name="a", step_call=_StepCall(), user_input="secret"),
        after(operation_id="op", agent_name="a", step_call=_StepCall(), result={"secret": "value"}),
        error(operation_id="op", agent_name="a", step_call=_StepCall(), error=ValueError("secret")),
    ]
    forbidden = {"user_input", "result", "error", "step_call", "messages", "traceback"}
    assert all(forbidden.isdisjoint(payload) for payload in payloads)
    assert BEFORE_NAME == BEFORE_POINT.definition.name
    assert AFTER_NAME == AFTER_POINT.definition.name
    assert ERROR_NAME == ERROR_POINT.definition.name


def test_after_hook_exception_preserves_business_result():
    """An ordinary after-hook failure remains observational."""
    agent = _agent(lambda *_: "business-result")
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run": lambda **payload: None,
        "topsailai.ai_base.agent_base.hook__aibase__after__agent_run":
            lambda **payload: (_ for _ in ()).throw(RuntimeError("hook failure")),
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        assert agent.run(_StepCall(), "input") == "business-result"


def test_error_hook_exception_preserves_original_business_exception():
    """An ordinary error-hook failure cannot replace the business exception."""
    error = RuntimeError("business failure")
    agent = _agent(lambda *_: (_ for _ in ()).throw(error))
    patches = _contexts()
    patches.update({
        "topsailai.ai_base.agent_base.hook__aibase__before__agent_run": lambda **payload: None,
        "topsailai.ai_base.agent_base.hook__aibase__error__agent_run":
            lambda **payload: (_ for _ in ()).throw(ValueError("hook failure")),
    })
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in patches.items()
    }):
        with pytest.raises(RuntimeError) as raised:
            agent.run(_StepCall(), "input")
    assert raised.value is error


def test_payloads_have_exact_point_specific_fields_and_safe_fallbacks():
    """Payloads expose only the approved metadata fields and bounded tokens."""
    from topsailai.hooks.points.aibase.after_agent_run.payloads import build_payload as after
    from topsailai.hooks.points.aibase.before_agent_run.payloads import build_payload as before
    from topsailai.hooks.points.aibase.error_agent_run.payloads import build_payload as error

    assert set(before(operation_id="op", agent_name="a", step_call=_StepCall(), user_input=None)) == {
        "schema_version", "operation_id", "point_name", "outcome", "agent_layer",
        "agent_name_present", "step_call_type", "user_input_present",
    }
    assert set(after(operation_id="op", agent_name="a", step_call=_StepCall(), result=None)) == {
        "schema_version", "operation_id", "point_name", "outcome", "agent_layer",
        "agent_name_present", "step_call_type", "result_kind", "result_present",
        "pending_native_tool_responses_cleared",
    }
    assert set(error(operation_id="op", agent_name="a", step_call=_StepCall(), error=ValueError())) == {
        "schema_version", "operation_id", "point_name", "outcome", "agent_layer",
        "agent_name_present", "step_call_type", "error_category", "failed_stage",
        "partial_run_possible",
    }
    assert before(operation_id="op", agent_name="a", step_call=type("Bad\nName", (), {})(), user_input="x")["step_call_type"] == "unknown"
    with pytest.raises(ValueError):
        before(operation_id="bad id", agent_name="a", step_call=_StepCall(), user_input=None)


@pytest.mark.parametrize(
    "point_name, resource_kind",
    [
        (BEFORE_NAME, "missing_module"),
        (BEFORE_NAME, "import_failure"),
        (AFTER_NAME, "nonzero_script"),
        (ERROR_NAME, "raising_module"),
    ],
)
def test_real_configured_hook_failure_preserves_agent_run_boundary(
        monkeypatch, hook_tmp_dir, point_name, resource_kind):
    """Configured resource failures do not alter AgentBase results or cleanup."""
    import topsailai.hooks as hooks
    from unittest.mock import Mock

    resource = hook_tmp_dir / resource_kind
    if resource_kind == "missing_module":
        resource = hook_tmp_dir / "does-not-exist.py"
        config = {point_name: {"modules": [str(resource)]}}
        expected_result = "business-result"
        agent = _agent(lambda *_: expected_result)
    elif resource_kind == "import_failure":
        resource.write_text("raise RuntimeError(\'import failure\')\n")
        config = {point_name: {"modules": [str(resource)]}}
        expected_result = "business-result"
        agent = _agent(lambda *_: expected_result)
    elif resource_kind == "nonzero_script":
        resource.write_text("#!/bin/sh\nexit 7\n")
        resource.chmod(resource.stat().st_mode | 0o111)
        config = {point_name: {"scripts": [str(resource)]}}
        expected_result = "business-result"
        agent = _agent(lambda *_: expected_result)
    else:
        resource.write_text("def main(**kwargs):\n    raise RuntimeError('hook failure')\n")
        config = {point_name: {"modules": [str(resource)]}}
        business_error = RuntimeError("business failure")
        agent = _agent(lambda *_: (_ for _ in ()).throw(business_error))

    cleanup = Mock()
    agent.llm_model.clear_pending_native_tool_call_responses = cleanup
    contexts = _contexts()
    with patch.multiple("topsailai.ai_base.agent_base", **{
        name.rsplit(".", 1)[1]: value for name, value in contexts.items()
    }):
        hooks.initialize_hook_points(config)
        try:
            if resource_kind == "raising_module":
                with pytest.raises(RuntimeError) as raised:
                    agent.run(_StepCall(), "input")
                assert raised.value is business_error
                assert raised.traceback is not None
            else:
                assert agent.run(_StepCall(), "input") == expected_result
        finally:
            hooks.initialize_hook_points({})

    assert cleanup.call_count == 2


def test_after_hook_is_structurally_outside_react_loop():
    """The after call is not nested in AgentRun's ReAct loop body."""
    import ast
    import inspect
    import textwrap
    from topsailai.ai_base.agent_base import AgentRun

    tree = ast.parse(textwrap.dedent(inspect.getsource(AgentBase.run)))
    after_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "hook__aibase__after__agent_run"
    ]
    assert len(after_calls) == 1
    loops = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
    assert all(
        not any(child is call for child in ast.walk(loop))
        for call in after_calls for loop in loops
    )
    assert "while True" in inspect.getsource(AgentRun._run)
