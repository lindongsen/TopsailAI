"""Stage-2 Hook-only verification for Agent2LLM run points. Author: DawsonLin."""

import logging
import shutil
import uuid
from pathlib import Path

import pytest

from topsailai.hooks.control_signal import HookControlSignal
from topsailai.ai_base.exception import HardInterruptError
from topsailai.hooks.points.aibase.after_agent_run import (
    NAME as AFTER_NAME, POINT as AFTER_POINT,
    hook__aibase__after__agent_run,
)
from topsailai.hooks.points.aibase.before_agent_run import (
    NAME as BEFORE_NAME, POINT as BEFORE_POINT,
    hook__aibase__before__agent_run,
)
from topsailai.hooks.points.aibase.error_agent_run import (
    NAME as ERROR_NAME, POINT as ERROR_POINT,
    hook__aibase__error__agent_run,
)
from topsailai.hooks.points.aibase.after_agent_run.payloads import build_payload as after
from topsailai.hooks.points.aibase.before_agent_run.payloads import build_payload as before
from topsailai.hooks.points.aibase.error_agent_run.payloads import build_payload as error
import topsailai.hooks as hooks


logger = logging.getLogger(__name__)
_TEST_TMP_ROOT = Path("/TopsailAI/src/topsailai/.tmp")


@pytest.fixture
def hook_tmp_dir():
    """Create and remove one owned temporary Hook-resource directory."""
    path = _TEST_TMP_ROOT / f"agent-run-point-test-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        if path.exists():
            for child in sorted(path.rglob("*"), reverse=True):
                logger.info("Deleting test-owned temporary path: %s", child)
            logger.info("Deleting test-owned temporary directory: %s", path)
            shutil.rmtree(path)


POINTS = (
    (BEFORE_NAME, BEFORE_POINT, before),
    (AFTER_NAME, AFTER_POINT, after),
    (ERROR_NAME, ERROR_POINT, error),
)


def _payload(builder, name):
    kwargs = {"operation_id": "op", "agent_name": "agent", "step_call": object()}
    if name == BEFORE_NAME:
        kwargs["user_input"] = "secret"
    elif name == AFTER_NAME:
        kwargs["result"] = {"secret": "value"}
    else:
        kwargs["error"] = ValueError("secret")
    return builder(**kwargs)


def test_declarations_import_validate_and_match_names():
    """All declarations are independently valid and use the shared point name."""
    for name, point, builder in POINTS:
        assert point.name == name == point.definition.name
        assert name.startswith("hook__aibase__")
        assert name.count("__") == 3
        payload = _payload(builder, name)
        assert point.definition.payload_limit_bytes == 8192
        assert point.definition.payload_schema["required"]
        assert set(payload).issubset(point.definition.payload_schema["properties"])


def test_payload_contract_is_exact_and_metadata_only():
    """Builders exclude content, exceptions, objects and tracebacks."""
    expected = {
        BEFORE_NAME: {"schema_version", "operation_id", "point_name", "outcome", "agent_layer", "agent_name_present", "step_call_type", "user_input_present"},
        AFTER_NAME: {"schema_version", "operation_id", "point_name", "outcome", "agent_layer", "agent_name_present", "step_call_type", "result_kind", "result_present", "pending_native_tool_responses_cleared"},
        ERROR_NAME: {"schema_version", "operation_id", "point_name", "outcome", "agent_layer", "agent_name_present", "step_call_type", "error_category", "failed_stage", "partial_run_possible"},
    }
    for name, point, builder in POINTS:
        payload = _payload(builder, name)
        assert set(payload) == expected[name]
        assert not {"user_input", "result", "error", "step_call", "messages", "traceback"} & set(payload)
        assert payload["operation_id"] == "op"
    with pytest.raises(ValueError):
        before(operation_id="bad id", agent_name="a", step_call=object(), user_input=None)


def _write_module(hook_tmp_dir, text):
    path = hook_tmp_dir / "plugin.py"
    path.write_text(text)
    return str(path)


def _configure(monkeypatch, name, module=None, script=None):
    config = {name: {}}
    if module:
        config[name]["modules"] = [str(module)]
    if script:
        config[name]["scripts"] = [str(script)]
    hooks.initialize_hook_points(config)
    monkeypatch.setattr(hooks, "_point_configuration", hooks._point_configuration)


def _invoke_entry(monkeypatch, name, entry, hook_tmp_dir, *, module_text=None, script=None):
    module = _write_module(hook_tmp_dir, module_text) if module_text is not None else None
    _configure(monkeypatch, name, module=module, script=script)
    return entry(**_payload({BEFORE_NAME: before, AFTER_NAME: after, ERROR_NAME: error}[name], name))


def test_real_module_import_execution_and_discovery_failures_are_structured(monkeypatch, hook_tmp_dir):
    """Real direct-entry execution reports ordinary module failures without raising."""
    result = _invoke_entry(monkeypatch, BEFORE_NAME, hook__aibase__before__agent_run, hook_tmp_dir, module_text="raise RuntimeError('import failure')")
    assert result.handlers[0].status == "error"
    result = _invoke_entry(monkeypatch, BEFORE_NAME, hook__aibase__before__agent_run, hook_tmp_dir, module_text="def main(**payload): raise RuntimeError('run failure')")
    assert result.handlers[0].status == "error"
    hooks.initialize_hook_points({BEFORE_NAME: {"modules": [str(hook_tmp_dir / "missing.py")]}})
    result = hook__aibase__before__agent_run(**_payload(before, BEFORE_NAME))
    assert result.status == "unavailable"


def test_real_script_nonzero_is_structured(monkeypatch, hook_tmp_dir):
    """A real executable script failure remains a Hook result."""
    script = hook_tmp_dir / "fail.sh"
    script.write_text("#!/bin/sh\nexit 7\n")
    script.chmod(script.stat().st_mode | 0o111)
    result = _invoke_entry(monkeypatch, BEFORE_NAME, hook__aibase__before__agent_run, hook_tmp_dir, script=script)
    assert result.status == "completed_with_errors"
    assert any(handler.status == "error" for handler in result.handlers[-1].children)


def test_hook_control_signal_propagates(monkeypatch, hook_tmp_dir):
    """Control signals are not swallowed by ordinary failure isolation."""
    text = ("from topsailai.hooks.control_signal import HookControlSignal\n"
            "from topsailai.ai_base.exception import HardInterruptError\n"
            "def main(**payload): raise HookControlSignal(HardInterruptError())\n")
    module = _write_module(hook_tmp_dir, text)
    _configure(monkeypatch, BEFORE_NAME, module=module)
    with pytest.raises(HardInterruptError):
        hook__aibase__before__agent_run(**_payload(before, BEFORE_NAME))
