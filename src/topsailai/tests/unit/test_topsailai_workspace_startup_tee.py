"""Author: DawsonLin. Verify staged initialization and run stdout capture."""

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.workspace import agent_shell, print_tool
from topsailai.utils.env_tool import resolve_python_interpreter


@pytest.fixture
def capture_folder(monkeypatch, tmp_path):
    """Keep real Tee files and configuration isolated from runtime sessions."""
    monkeypatch.setenv("TOPSAILAI_ENABLE_SESSION_TEE_OUT", "1")
    monkeypatch.delenv("SESSION_ID", raising=False)
    monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
    monkeypatch.setattr(agent_shell, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setattr(print_tool, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setattr(print_tool, "register_cleanup_func", Mock())
    return tmp_path


def test_initialization_then_run_append_once(monkeypatch, capture_folder):
    """Observe flushed initialization output before return and append run once."""
    path = capture_folder / f"explicit.{os.getpid()}.session.stdout"
    path.write_text("earlier\n", encoding="utf-8")
    monkeypatch.setenv("TOPSAILAI_SESSION_ID", "inherited")
    terminal = sys.stdout
    owners = []

    @print_tool.decorator_tee_output_by_session()
    def run():
        """Exercise the same decorator used by AgentChat.run."""
        owners.append(sys.stdout)
        assert owners[0].log_file.closed
        print("running")

    def initialize(**kwargs):
        """Stand in for initialization while observing its active writer."""
        assert kwargs["session_id"] == "explicit"
        owners.append(sys.stdout)
        print("waiting for input")
        assert path.read_text(encoding="utf-8") == "earlier\nwaiting for input\n"
        return run

    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", initialize)
    chat_run = agent_shell.get_agent_chat(session_id="explicit", need_project_workspace_lock=False)
    assert sys.stdout is terminal
    assert owners[0].log_file.closed
    chat_run()
    assert sys.stdout is terminal
    assert owners[1].log_file.closed
    assert path.read_text(encoding="utf-8") == "earlier\nwaiting for input\nrunning\n"
    assert not (capture_folder / f"inherited.{os.getpid()}.session.stdout").exists()


@pytest.mark.parametrize("session_id, inherited, expected", [
    (None, "from-env", "from-env"),
    (None, "", "topsailai"),
    ("", "", "topsailai"),
])
def test_session_identity(monkeypatch, capture_folder, session_id, inherited, expected):
    """Resolve environment fallback and preserve explicit empty identities."""
    monkeypatch.setenv("SESSION_ID", inherited)
    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", lambda **kwargs: print("startup"))
    agent_shell.get_agent_chat(session_id=session_id, need_project_workspace_lock=False)
    path = capture_folder / f"{expected}.{os.getpid()}.session.stdout"
    assert path.read_text(encoding="utf-8") == "startup\n"


@pytest.mark.parametrize("enabled", ["0", ""])
def test_disabled_creates_no_file(monkeypatch, capture_folder, enabled):
    """Respect the existing Tee opt-out without opening a startup file."""
    monkeypatch.setenv("TOPSAILAI_ENABLE_SESSION_TEE_OUT", enabled)
    terminal = sys.stdout

    def initialize(**kwargs):
        """Check that disabled capture leaves the caller's stdout untouched."""
        assert sys.stdout is terminal
        return "chat"

    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", initialize)
    assert agent_shell.get_agent_chat(session_id="off", need_project_workspace_lock=False) == "chat"
    assert list(capture_folder.iterdir()) == []


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_failed_startup_restores_and_retains(monkeypatch, capture_folder, error_type):
    """Close on ordinary failure or interruption without deleting diagnostics."""
    state = Mock()
    monkeypatch.setattr(agent_shell, "AgentStartupState", lambda: state)
    cleanup = Mock()
    monkeypatch.setattr(print_tool, "register_cleanup_func", cleanup)
    terminal = sys.stdout
    owners = []
    error = error_type("startup interrupted")

    def initialize(**kwargs):
        """Emit a diagnostic before the simulated startup failure."""
        owners.append(sys.stdout)
        print("startup diagnostic")
        raise error

    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", initialize)
    with pytest.raises(error_type) as caught:
        agent_shell.get_agent_chat(session_id="failed", need_project_workspace_lock=False)
    assert caught.value is error
    assert sys.stdout is terminal
    assert owners[0].log_file.closed
    state.cancel.assert_called_once_with()
    cleanup.assert_called_once_with(owners[0].delete_log_files)
    path = capture_folder / f"failed.{os.getpid()}.session.stdout"
    assert path.read_text(encoding="utf-8") == "startup diagnostic\n"


def test_nested_initialization_reuses_outer_capture(monkeypatch, capture_folder):
    """Do not introduce duplicate writes while a parent Tee owns stdout."""
    path = capture_folder / "outer.stdout"
    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", lambda **kwargs: print("nested"))
    with print_tool.TeeOutput(str(path)) as outer:
        agent_shell.get_agent_chat(session_id="child", need_project_workspace_lock=False)
        assert sys.stdout is outer
        assert not outer.log_file.closed
    assert path.read_text(encoding="utf-8") == "nested\n"
    assert len(list(capture_folder.iterdir())) == 1


def test_new_session_input_is_captured_before_agent_creation(monkeypatch, capture_folder):
    """Drive the real factory and input prompt without constructing an LLM."""
    from topsailai.workspace import input_tool

    monkeypatch.setenv("TOPSAILAI_INTERACTIVE_MODE", "1")
    monkeypatch.setattr(sys, "argv", ["agent"])
    context = Mock(messages=[])
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", lambda: context)
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", Mock())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", Mock())
    monkeypatch.setattr(agent_shell, "HookInstruction", Mock())
    monkeypatch.setattr(agent_shell.ctx_manager, "exists_session", lambda sid: False)
    create_session = Mock()
    monkeypatch.setattr(agent_shell.ctx_manager, "create_session", create_session)
    agent = Mock()
    agent.runtime.llm_model.max_tokens = 4000
    agent.runtime.llm_model.temperature = 0.3
    create_agent = Mock(return_value=agent)
    monkeypatch.setattr(agent_shell, "get_ai_agent", create_agent)
    monkeypatch.setattr(agent_shell, "record_project_history", Mock())
    monkeypatch.setattr(agent_shell, "create_session_meta", Mock())
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", Mock())
    monkeypatch.setattr(agent_shell, "AgentChat", Mock())
    path = capture_folder / f"new-session.{os.getpid()}.session.stdout"

    def receive_input(tips):
        """Inspect the file at the exact point production would wait for input."""
        create_agent.assert_not_called()
        create_session.assert_not_called()
        assert input_tool.SPLIT_LINE in path.read_text(encoding="utf-8")
        return "first task"

    monkeypatch.setattr(input_tool, "_input", receive_input)
    monkeypatch.setattr(input_tool, "hook_message", lambda *args: False)
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    from topsailai.hooks.points.workspace import before_input_message
    monkeypatch.setattr(before_input_message, "hook__workspace__before__input_message", Mock())
    chat = agent_shell.get_agent_chat(
        session_id="new-session", need_project_workspace_lock=False, need_print_session=False,
    )
    assert chat.first_message == "first task"
    create_agent.assert_called_once()
    assert create_session.call_args.kwargs["task"] == "first task"


@pytest.mark.parametrize("outcome", ["normal", "failure", "interrupt", "run"])
def test_startup_files_removed_on_process_exit(tmp_path, outcome):
    """Run real exit callbacks without requiring AgentChat.run to be reached."""
    script = r"""
import os
import sys
from pathlib import Path
from topsailai.workspace import agent_shell, print_tool
from topsailai.workspace.folder_utils import get_session_stdout_path

folder = Path(sys.argv[1])
outcome = sys.argv[2]
agent_shell.FOLDER_WORKSPACE_TASK = str(folder)
print_tool.FOLDER_WORKSPACE_TASK = str(folder)
path = Path(get_session_stdout_path(str(folder), "owned", os.getpid()))
rotation = Path(str(path) + ".1")
unrelated = folder / "unrelated.session.stdout"
unrelated.write_text("keep", encoding="utf-8")

@print_tool.decorator_tee_output_by_session(need_delete_log_files=True)
def run():
    # Retain the existing runtime owner and verify sequential append.
    print("running")

def initialize(**kwargs):
    # Verify startup output is flushed before initialization completes.
    print("startup diagnostic")
    assert path.read_text(encoding="utf-8") == "startup diagnostic\n"
    rotation.write_text("rotation", encoding="utf-8")
    if outcome == "failure":
        raise RuntimeError("startup failed")
    if outcome == "interrupt":
        raise KeyboardInterrupt("startup interrupted")
    return run

agent_shell._get_agent_chat_impl = initialize
terminal = sys.stdout
try:
    chat_run = agent_shell.get_agent_chat(session_id="owned", need_project_workspace_lock=False)
except (RuntimeError, KeyboardInterrupt):
    if outcome not in ("failure", "interrupt"):
        raise
else:
    if outcome == "run":
        chat_run()
assert sys.stdout is terminal
assert path.exists() and rotation.exists()
if outcome == "run":
    assert path.read_text(encoding="utf-8") == "startup diagnostic\nrunning\n"
print("exit cleanup armed")
"""
    env = dict(os.environ)
    env.update({
        "TOPSAILAI_HOME": str(tmp_path / "home"),
        "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "1",
        "TOPSAILAI_INTERACTIVE_MODE": "0",
        "TOPSAILAI_EVENTS_ENABLED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([
            str(Path(agent_shell.__file__).resolve().parents[2]),
            str(Path(agent_shell.__file__).resolve().parents[1]),
        ]),
    })
    result = subprocess.run(
        [resolve_python_interpreter(), "-c", script, str(tmp_path), outcome],
        env=env, cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "exit cleanup armed" in result.stdout
    assert not list(tmp_path.glob("owned.*.session.stdout*"))
    assert (tmp_path / "unrelated.session.stdout").read_text(encoding="utf-8") == "keep"
