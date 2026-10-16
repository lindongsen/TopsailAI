"""Behavioral tests for all approved U5 application entry boundaries."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest


CLI_ROOT = str(Path(__file__).parents[3] / "cli")
if CLI_ROOT not in sys.path:
    sys.path.insert(0, CLI_ROOT)

CLI_MODULES = (
    "topsailai.cli.agent_chat",
    "topsailai.cli.agent_chats",
    "topsailai.cli.team_agent",
    "topsailai.cli.team_chat",
    "topsailai.cli.llm_chat",
    "topsailai.cli.llm_chats",
)
AGENT_MODULES = {"topsailai.cli.agent_chat", "topsailai.cli.agent_chats", "topsailai.cli.team_agent"}


class RecordingChat:
    """Exercise a complete entry-owned run boundary."""

    run_failure = None
    chat_failure = None

    def __init__(self, events):
        self.events = events
        self.first_message = "first"

    def run(self, **kwargs):
        self.events.extend(("run", ("run_kwargs", kwargs), "turn-1", "turn-2"))
        if type(self).run_failure is not None:
            raise type(self).run_failure
        return "agent-answer"

    def chat(self, *args, **kwargs):
        self.events.append("chat")
        if type(self).chat_failure is not None:
            raise type(self).chat_failure
        return "llm-answer"


@pytest.fixture(autouse=True)
def reset_recording_chat():
    """Reset business failure instrumentation for each entry invocation."""
    RecordingChat.run_failure = None
    RecordingChat.chat_failure = None


def _patch_common(module, monkeypatch, events):
    """Replace module-local business boundaries while retaining real main bodies."""
    if module.__name__ in AGENT_MODULES:
        def get_agent_chat(**kwargs):
            events.append(("factory", kwargs))
            return RecordingChat(events)

        monkeypatch.setattr(module, "get_agent_chat", get_agent_chat)
    else:
        def get_llm_chat(**kwargs):
            events.append(("factory", kwargs))
            return RecordingChat(events)

        monkeypatch.setattr(module, "get_llm_chat", get_llm_chat)
        if hasattr(module, "input_message"):
            def input_message():
                events.append("input")
                return "next"

            monkeypatch.setattr(module, "input_message", input_message)
    if module.__name__ in {"topsailai.cli.team_agent", "topsailai.cli.team_chat"}:
        monkeypatch.setattr(module, "get_member_name", lambda: "member")
        monkeypatch.setattr(module, "get_system_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(module, "is_team_prompt_precomposed_launch", lambda: False)
        monkeypatch.setattr(module.env_tool, "is_debug_mode", lambda: True)
        monkeypatch.setattr(module.env_tool.EnvReaderInstance, "check_bool", lambda *args, **kwargs: False)


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_each_cli_calls_business_without_hook_parameters(module_name, monkeypatch):
    """Real no-argument main retains its return and business factory contract."""
    module = importlib.import_module(module_name)
    events = []
    _patch_common(module, monkeypatch, events)
    result = module.main()
    assert events[0][0] == "factory"
    assert not any("hook" in key for key in events[0][1])
    assert result == ("agent-answer" if module_name.endswith("team_agent") else None)
    if module_name.endswith("agent_chats"):
        assert events[0][1]["agent_role"] == "manager"
    assert "run" in events if module_name in AGENT_MODULES else "chat" in events
    if module_name in AGENT_MODULES:
        kwargs = next(item[1] for item in events if isinstance(item, tuple) and item[0] == "run_kwargs")
        if module_name.endswith("agent_chats"):
            assert kwargs == {}
        elif module_name.endswith("team_agent"):
            assert kwargs["times"] == 1
            assert kwargs["only_save_final"] is True
            assert kwargs["need_confirm_abort"] is False
            assert kwargs["func_build_message"] is module.hook_build_message
        else:
            assert kwargs == {"times": 1}


def test_input_message_signature_is_unchanged():
    """U5 does not change the existing input_message API."""
    from inspect import signature
    from topsailai.workspace.input_tool import input_message

    assert tuple(signature(input_message).parameters) == ("tips", "hook")


@pytest.mark.parametrize("module_name", (
    "topsailai.cli.agent_chat",
    "topsailai.cli.agent_chats",
    "topsailai.cli.team_agent",
    "topsailai.cli.team_chat",
    "topsailai.cli.llm_chat",
    "topsailai.cli.llm_chats",
))
@pytest.mark.parametrize("failure_type", (RuntimeError, KeyboardInterrupt))
def test_real_cli_failure_preserves_identity(
        module_name, failure_type, monkeypatch):
    """Real CLI bodies preserve failures from run/chat without an owner wrapper."""
    module = importlib.import_module(module_name)
    events = []
    _patch_common(module, monkeypatch, events)
    failure = failure_type(module_name)
    if module_name in AGENT_MODULES:
        RecordingChat.run_failure = failure
    else:
        RecordingChat.chat_failure = failure

    with pytest.raises(failure_type) as raised:
        module.main()

    assert raised.value is failure
    names = [frame.name for frame in __import__("traceback").extract_tb(raised.value.__traceback__)]
    assert "main" in names


def test_real_llm_output_handling(monkeypatch):
    """Single-run output handling preserves the returned business text."""
    module = importlib.import_module("topsailai.cli.llm_chat")
    events = []
    _patch_common(module, monkeypatch, events)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: (
        printed.append(args)))
    monkeypatch.setattr(module.env_tool, "is_debug_mode", lambda: False)
    monkeypatch.setattr(module.env_tool.EnvReaderInstance, "check_bool",
                        lambda *args, **kwargs: True)

    module.main()

    assert printed
    assert any("first" in str(args) for args in printed)
    assert any(">>> answer:" in args for args in printed)



def test_real_team_chat_writes_result_file(monkeypatch, tmp_path):
    """The real team-chat entry still writes its business result."""
    module = importlib.import_module("topsailai.cli.team_chat")
    output = tmp_path / "team-result.txt"
    active = []

    class Chat:
        def chat(self):
            active.append("chat")
            return "team result"

    monkeypatch.setattr(module, "get_llm_chat", lambda **kwargs: Chat())
    monkeypatch.setattr(module, "get_member_name", lambda: "member")
    monkeypatch.setattr(module, "get_system_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(module, "is_team_prompt_precomposed_launch", lambda: False)
    monkeypatch.setattr(module.env_tool, "is_debug_mode", lambda: False)
    monkeypatch.setattr(module.env_tool.EnvReaderInstance, "check_bool", lambda *args, **kwargs: False)
    monkeypatch.setenv("TOPSAILAI_SAVE_RESULT_TO_FILE", str(output))

    module.main()

    assert output.read_text(encoding="utf-8") == "team result"
    assert active == ["chat"]


def test_real_team_agent_preserves_exception_identity_and_traceback(monkeypatch):
    """The real team-agent entry preserves the original business failure."""
    module = importlib.import_module("topsailai.cli.team_agent")
    failure = RuntimeError("team failure")

    class Chat:
        def run(self, **kwargs):
            raise failure

    monkeypatch.setattr(module, "get_member_name", lambda: "member")
    monkeypatch.setattr(module, "get_system_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(module, "is_team_prompt_precomposed_launch", lambda: False)
    monkeypatch.setattr(module, "get_session_head_tail_offset", lambda: 0)
    monkeypatch.setattr(module.env_tool.EnvReaderInstance, "check_bool", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "get_agent_chat", lambda **kwargs: Chat())

    with pytest.raises(RuntimeError) as raised:
        module.main()

    assert raised.value is failure
    names = [frame.name for frame in __import__("traceback").extract_tb(raised.value.__traceback__)]
    assert "main" in names and "run" in names


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_all_cli_main_functions_retain_docstrings(module_name):
    """All six public CLI entry points retain their original docstrings."""
    module = importlib.import_module(module_name)
    assert module.main.__doc__


@pytest.mark.parametrize("failed", (False, True))
def test_session_finalizer_closes_agent_without_hook_owner(monkeypatch, failed):
    """Retain real session cleanup and exception identity after owner retirement."""
    from topsailai.workspace.agent import agent_shell_base

    run = agent_shell_base.AgentChat.run
    body = next(cell.cell_contents for cell in run.__closure__ if callable(cell.cell_contents))
    failure = RuntimeError("session failure")
    session = SimpleNamespace(
        _run=Mock(side_effect=failure) if failed else Mock(return_value="done"),
        ctx_runtime_data=SimpleNamespace(session_id=""),
        _stop_control_server=Mock(), ai_agent=SimpleNamespace(close=Mock()),
    )
    status = Mock()
    monkeypatch.setattr(agent_shell_base, "update_session_meta_status", status)
    if failed:
        with pytest.raises(RuntimeError) as raised:
            body(session)
        assert raised.value is failure
    else:
        assert body(session) == "done"
    status.assert_called_once_with("error" if failed else "completed", "")
    session._stop_control_server.assert_called_once()
    session.ai_agent.close.assert_called_once()
