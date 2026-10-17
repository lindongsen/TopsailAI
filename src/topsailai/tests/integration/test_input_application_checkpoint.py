"""Real direct-input checkpoint regression after owner removal. Author: DawsonLin."""

import json
import os
import sys
from unittest.mock import Mock

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.point_entry import pending_cleanup
from topsailai.workspace import input_tool


@pytest.fixture
def direct_input(tmp_path, monkeypatch):
    """Select real external workers and restore the package configuration exactly."""
    ledger = tmp_path / "input.jsonl"
    module = tmp_path / "worker.py"
    script = tmp_path / "script"
    module.write_text(
        "import json, os\ndef main():\n"
        f"    with open({str(ledger)!r}, 'a') as f:\n"
        "        f.write(json.dumps({'kind': 'module', 'pid': os.getpid()}) + '\\n')\n"
    )
    script.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        "assert sys.stdin.buffer.read() == b''\n"
        f"with open({str(ledger)!r}, 'a') as f:\n"
        "    f.write(json.dumps({'kind': 'script', 'pid': os.getpid()}) + '\\n')\n"
    )
    script.chmod(0o700)
    previous = hooks._point_configuration
    hooks.initialize_hook_points({"hook__workspace__before__input_message": {
        "modules": [str(module)], "scripts": [str(script)]}})
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)

    def rows():
        """Read exact fixture observations from completed real workers."""
        return [json.loads(row) for row in ledger.read_text().splitlines()] if ledger.exists() else []

    yield rows
    monkeypatch.setattr(hooks, "_point_configuration", previous)
    assert not pending_cleanup()
    for row in rows():
        if row["kind"] == "module":
            assert row["pid"] == os.getpid()
            continue
        with pytest.raises(ProcessLookupError):
            os.kill(row["pid"], 0)


def test_input_runs_real_module_then_script_before_read(direct_input, monkeypatch):
    """Both direct workers finish before ordinary input acquisition."""
    def read(*args):
        """Observe completion at the real input boundary."""
        assert [row["kind"] for row in direct_input()] == ["module", "script"]
        return "message"

    monkeypatch.setattr(input_tool, "_input", read)
    assert input_tool.input_message() == "message"


def test_input_retries_without_redispatch_and_next_call_executes(direct_input, monkeypatch):
    """An empty read retries locally; a later acquisition starts fresh workers."""
    values = iter(("", "message", "next"))
    reads = []

    def read(*args):
        """Count real workers at each input attempt, not mocked hook callbacks."""
        reads.append(len(direct_input()))
        return next(values)

    monkeypatch.setattr(input_tool, "_input", read)
    assert input_tool.input_message() == "message"
    assert reads == [2, 2]
    assert input_tool.input_message() == "next"
    assert reads == [2, 2, 4]
    assert [row["kind"] for row in direct_input()] == ["module", "script"] * 2
    module_pids = {row["pid"] for row in direct_input() if row["kind"] == "module"}
    script_pids = {row["pid"] for row in direct_input() if row["kind"] == "script"}
    assert module_pids == {os.getpid()}
    assert len(script_pids) == 2
    assert os.getpid() not in script_pids


def test_input_exception_identity_after_workers_finish(direct_input, monkeypatch):
    """Removing the owner does not wrap an input-hook business exception."""
    failure = RuntimeError("input interception")
    monkeypatch.setattr(input_tool, "_input", lambda *args: "message")

    def intercept(message):
        """Raise the original exception only after input acquisition."""
        raise failure

    interceptor = Mock()
    interceptor.exist_hook.side_effect = intercept
    with pytest.raises(RuntimeError) as raised:
        input_tool.input_message(hook=interceptor)
    assert raised.value is failure
    assert len(direct_input()) == 2
