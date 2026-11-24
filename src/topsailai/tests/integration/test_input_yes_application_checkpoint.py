"""Real yes/no confirmation checkpoint regression. Author: DawsonLin."""

import json
import os
import sys
from unittest.mock import Mock

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.point_entry import pending_cleanup
from topsailai.workspace import input_tool


@pytest.fixture
def confirmation(tmp_path, monkeypatch):
    """Select real external workers and restore the package configuration exactly."""
    ledger = tmp_path / "confirm.jsonl"
    module = tmp_path / "worker.py"
    script = tmp_path / "script"
    module.write_text(
        "import json, os\ndef main(**kwargs):\n"
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
    hooks.initialize_hook_points({"hook__workspace__before__input_yes": {
        "modules": [str(module)], "scripts": [str(script)]}})

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


def test_confirmation_runs_real_module_then_script_before_read(confirmation, monkeypatch):
    """Both direct workers finish before the confirmation reader runs."""
    def read(*args):
        """Observe completion at the real confirmation boundary."""
        assert [row["kind"] for row in confirmation()] == ["module", "script"]
        return "yes"

    monkeypatch.setattr(input_tool, "input_one_line", read)
    assert input_tool.input_yes("Proceed? ") is True


def test_confirmation_retries_without_redispatch(confirmation, monkeypatch):
    """An invalid answer retries locally; a later confirmation starts fresh workers."""
    values = iter(("maybe", "no", "yes"))
    reads = []

    def read(*args):
        """Count real workers at each confirmation attempt, not mocked callbacks."""
        reads.append(len(confirmation()))
        return next(values)

    monkeypatch.setattr(input_tool, "input_one_line", read)
    assert input_tool.input_yes("Proceed? ") is False
    assert reads == [2, 2]
    assert input_tool.input_yes("Proceed? ") is True
    assert reads == [2, 2, 4]
    assert [row["kind"] for row in confirmation()] == ["module", "script"] * 2
    module_pids = {row["pid"] for row in confirmation() if row["kind"] == "module"}
    script_pids = {row["pid"] for row in confirmation() if row["kind"] == "script"}
    assert module_pids == {os.getpid()}
    assert len(script_pids) == 2
    assert os.getpid() not in script_pids


def test_confirmation_exception_identity_after_workers_finish(confirmation, monkeypatch):
    """A reader failure is not wrapped by the checkpoint."""
    failure = RuntimeError("confirmation reader failure")
    monkeypatch.setattr(input_tool, "input_one_line", Mock(side_effect=failure))
    with pytest.raises(RuntimeError) as raised:
        input_tool.input_yes("Proceed? ")
    assert raised.value is failure
    assert len(confirmation()) == 2
