"""Verify env.set results and control dispatch. Author: DawsonLin."""

import json
import os
from types import SimpleNamespace

import pytest

from topsailai.utils.instruction_tool import HookInstruction
from topsailai.workspace.control_channel.protocol import (
    ControlContext, ControlRequest, encode_response,
)
from topsailai.workspace.control_handlers.instruction import CallInstructionHandler
from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS, set_env


def test_set_returns_confirmation(capsys, monkeypatch):
    """Preserve mutation and stdout while returning the confirmation."""
    monkeypatch.setenv("TOPSAILAI_ENV_TEST", "before")
    result = set_env("TOPSAILAI_ENV_TEST", "after")
    assert result == "set environment ok: TOPSAILAI_ENV_TEST old=before new=after"
    assert os.environ["TOPSAILAI_ENV_TEST"] == "after"
    assert capsys.readouterr().out == result + "\n"


@pytest.mark.parametrize("value", ["", 123, False])
def test_set_coerces_value(value):
    """Allow empty values and preserve existing string conversion."""
    result = set_env("TOPSAILAI_ENV_TEST", value)
    assert result == f"set environment ok: TOPSAILAI_ENV_TEST old=None new={value}"
    assert os.environ["TOPSAILAI_ENV_TEST"] == str(value)


@pytest.mark.parametrize("args, expected", [
    ((), "Usage: /env.set <name> <value>"),
    (("TOPSAILAI_ENV_TEST",), "Usage: /env.set <name> <value>"),
    (("", "value"), "Invalid environment variable name"),
    (("A=B", "value"), "Invalid environment variable name"),
    (("A\0B", "value"), "Invalid environment variable name"),
    (("TOPSAILAI_ENV_TEST", "a\0b"), "Invalid environment variable value"),
])
def test_set_invalid_arguments(args, expected):
    """Invalid inputs report the problem without environment mutation."""
    before = dict(os.environ)
    assert set_env(*args) == expected
    assert dict(os.environ) == before


@pytest.mark.parametrize("suffix", ["KEY", "TOKEN", "SECRET", "PASSWORD", "credential", "passwd"])
def test_set_masks_secrets(suffix, capsys, monkeypatch):
    """Neither previous nor new credentials appear in console or result."""
    name = f"TOPSAILAI_TEST_{suffix}"
    monkeypatch.setenv(name, "previous-sensitive-value")
    result = set_env(name, "replacement-sensitive-value")
    assert result == f"set environment ok: {name} old=*** new=***"
    assert capsys.readouterr().out == result + "\n"
    assert os.environ[name] == "replacement-sensitive-value"


@pytest.mark.parametrize("name", ["TOPSAILAI_ENV_TEST", "TOPSAILAI_TEST_API_KEY"])
def test_set_control_response(name, tmp_path, monkeypatch):
    """Real dispatch preserves the result in the JSONL response envelope."""
    from topsailai.workspace.plugin_instruction.base.init import INSTRUCTIONS as registry

    assert registry["env.set"] is INSTRUCTIONS["set"] is set_env
    monkeypatch.setattr(HookInstruction, "setup_readline_completion", lambda self: None)
    hooks = HookInstruction(str(tmp_path / "completions.json"), {"env.set": registry["env.set"]})
    request = ControlRequest("env-test", "call_instruction", {
        "instruction": "env.set", "args": [name, "test-value"],
    })
    context = ControlContext(agent_chat=SimpleNamespace(hook_instruction=hooks))
    response = CallInstructionHandler().handle(request, context)
    displayed = "***" if "KEY" in name else "test-value"
    old = "***" if "KEY" in name else "None"
    assert response.status == "ok"
    assert response.result == f"set environment ok: {name} old={old} new={displayed}"
    assert json.loads(encode_response(response))["result"] == response.result
    assert os.environ[name] == "test-value"
