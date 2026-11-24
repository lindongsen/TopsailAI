"""Bundled before-input Hook scripts Module regressions.

Author: DawsonLin

The Module mirrors ``TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER`` at the
complete-message input checkpoint. These tests prove the operator contract:
an unset variable costs nothing, a configured script really runs as a child
process, and no script outcome can interrupt the human's input.
"""

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

import topsailai.hooks as hooks
from topsailai.hooks.points.workspace.before_input_message import (
    NAME, hook__workspace__before__input_message,
)
from topsailai.utils import hook_tool

MODULE_NAME = "run_hook_scripts.py"
ENV_KEY = "TOPSAILAI_HOOK_SCRIPTS_BEFORE_INPUT_MESSAGE"


@pytest.fixture(autouse=True)
def isolated_points():
    """Restore the process-wide point snapshot around every test."""
    hooks.initialize_hook_points({})
    yield
    hooks.initialize_hook_points({})


def load_module():
    """Import the bundled Module file exactly as the framework does."""
    import importlib.util

    path = (Path(hooks.__file__).parent / "points" / "workspace"
            / "before_input_message" / "modules" / MODULE_NAME)
    spec = importlib.util.spec_from_file_location("probe_before_input_scripts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def script(path, output, text="ran"):
    """Create one real executable Script writing a single marker."""
    path.write_text(f"#!/bin/sh\nprintf '{text}' >> '{output}'\n")
    path.chmod(0o755)
    return path


def test_env_key_matches_documented_name():
    """The Module owns exactly one documented variable name."""
    assert load_module().ENV_KEY == ENV_KEY


def test_unset_variable_runs_no_child(monkeypatch):
    """An unset variable returns immediately without spawning a process."""
    monkeypatch.delenv(ENV_KEY, raising=False)
    launch = Mock()
    monkeypatch.setattr(hook_tool.cmd_tool, "exec_cmd", launch)
    assert load_module().main() == {"scripts": 0}
    launch.assert_not_called()


def test_configured_script_runs_as_child(tmp_path, monkeypatch):
    """A configured script really executes and its marker proves the run."""
    output = tmp_path / "trace"
    monkeypatch.setenv(ENV_KEY, str(script(tmp_path / "notify", output)))
    assert load_module().main() == {"scripts": 1}
    assert output.read_text() == "ran"


def test_script_failure_does_not_raise(tmp_path, monkeypatch):
    """A failing script is reported by count and never interrupts input."""
    failing = tmp_path / "failing"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    monkeypatch.setenv(ENV_KEY, str(failing))
    assert load_module().main() == {"scripts": 1}


def test_hook_tool_failure_is_logged(monkeypatch, caplog):
    """An unexpected dispatch failure is logged and converted to a safe result."""
    monkeypatch.setattr(hook_tool, "call_hook_scripts",
                        Mock(side_effect=RuntimeError("fixture dispatch failure")))
    with caplog.at_level(logging.WARNING):
        assert load_module().main() == {"scripts": 0}
    assert "before_input_message_hook_scripts_failed" in caplog.text


def test_bundled_module_runs_through_real_entry(tmp_path, monkeypatch):
    """The real named entry executes the bundled Module and the operator script."""
    output = tmp_path / "trace"
    monkeypatch.setenv(ENV_KEY, str(script(tmp_path / "notify", output)))
    result = hook__workspace__before__input_message()
    assert result.status == "success"
    bundled = [item for item in result.handlers if item.handler.name == MODULE_NAME]
    assert len(bundled) == 1
    assert bundled[0].status == "success"
    assert bundled[0].returned.value == {"scripts": 1}
    assert output.read_text() == "ran"


def test_bundled_module_is_a_permanent_point_member():
    """The Module is discovered from the bundled folder without configuration."""
    result = hook__workspace__before__input_message()
    assert [item.handler.name for item in result.handlers] == [MODULE_NAME, "hook_script"]


def test_tips_reach_script_environment(tmp_path, monkeypatch):
    """The prompt text reaches a real Script child through its environment."""
    output = tmp_path / "trace"
    path = tmp_path / "capture"
    path.write_text(f"#!/bin/sh\nprintf '%s' \"$TOPSAILAI_INPUT_TIPS\" >> '{output}'\n")
    path.chmod(0o755)
    monkeypatch.setenv(ENV_KEY, str(path))
    assert load_module().main(tips="What would you like to do? ") == {"scripts": 1}
    assert output.read_text() == "What would you like to do? "


def test_missing_tips_reaches_script_as_empty(tmp_path, monkeypatch):
    """An absent payload key still exports the variable, as an empty value."""
    output = tmp_path / "trace"
    path = tmp_path / "capture"
    path.write_text(f"#!/bin/sh\nprintf '[%s]' \"$TOPSAILAI_INPUT_TIPS\" >> '{output}'\n")
    path.chmod(0o755)
    monkeypatch.setenv(ENV_KEY, str(path))
    assert load_module().main() == {"scripts": 1}
    assert output.read_text() == "[]"


def test_tips_env_name_is_documented():
    """The Module owns exactly one documented tips variable name."""
    assert load_module().TIPS_ENV == "TOPSAILAI_INPUT_TIPS"


def test_real_entry_forwards_tips_to_script(tmp_path, monkeypatch):
    """The named entry carries the caller's prompt text down to the child."""
    output = tmp_path / "trace"
    path = tmp_path / "capture"
    path.write_text(f"#!/bin/sh\nprintf '%s' \"$TOPSAILAI_INPUT_TIPS\" >> '{output}'\n")
    path.chmod(0o755)
    monkeypatch.setenv(ENV_KEY, str(path))
    result = hook__workspace__before__input_message(tips="team prompt")
    assert result.status == "success"
    assert output.read_text() == "team prompt"
