"""Behavioral tests for all approved U5 application entry boundaries."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.workspace import agent_shell

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


class RecordingApplication:
    """Record application ownership and expose a unique executor."""

    instances = []
    active = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.executor = object()
        self.events = []
        self.close_count = 0
        type(self).instances.append(self)

    def __enter__(self):
        assert not type(self).active
        type(self).active = True
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, traceback):
        assert type(self).active
        self.close_count += 1
        self.events.append("exit")
        type(self).active = False
        return False


class RecordingChat:
    """Exercise a complete entry-owned run boundary."""

    run_failure = None
    chat_failure = None

    def __init__(self, events):
        self.events = events
        self.first_message = "first"

    def run(self, **kwargs):
        assert RecordingApplication.active
        self.events.extend(("run", "turn-1", "turn-2"))
        if type(self).run_failure is not None:
            raise type(self).run_failure
        return "agent-answer"

    def chat(self, *args, **kwargs):
        assert RecordingApplication.active
        self.events.append("chat")
        if type(self).chat_failure is not None:
            raise type(self).chat_failure
        return "llm-answer"


@pytest.fixture(autouse=True)
def reset_recording_application():
    """Reset shared test instrumentation between entry invocations."""
    RecordingApplication.instances.clear()
    RecordingApplication.active = False
    RecordingChat.run_failure = None
    RecordingChat.chat_failure = None
    yield
    assert not RecordingApplication.active


def _patch_common(module, monkeypatch, events):
    """Replace module-local business boundaries while retaining real main bodies."""
    monkeypatch.setattr(module, "HooksApplication", RecordingApplication)
    if module.__name__ in AGENT_MODULES:
        def get_agent_chat(**kwargs):
            assert RecordingApplication.active
            events.append(("factory", kwargs))
            return RecordingChat(events)

        monkeypatch.setattr(module, "get_agent_chat", get_agent_chat)
    else:
        def get_llm_chat(**kwargs):
            assert RecordingApplication.active
            events.append(("factory", kwargs))
            return RecordingChat(events)

        monkeypatch.setattr(module, "get_llm_chat", get_llm_chat)
        if hasattr(module, "input_message"):
            def input_message():
                assert RecordingApplication.active
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
def test_each_real_cli_main_binds_before_business_and_closes_once(module_name, monkeypatch):
    """Every approved CLI body executes entirely inside its own application."""
    module = importlib.import_module(module_name)
    events = []
    _patch_common(module, monkeypatch, events)
    request, trust, root = object(), object(), "/tmp/u5-entry"

    result = module.main(request=request, trust_policy=trust, temp_root=root)

    app = RecordingApplication.instances[0]
    assert app.kwargs == {"request": request, "trust_policy": trust, "temp_root": root}
    assert app.events == ["enter", "exit"]
    assert app.close_count == 1
    assert events and events[0][0] == "factory"
    assert result == ("agent-answer" if module_name == "topsailai.cli.team_agent" else None)
    if module_name in AGENT_MODULES:
        assert events[0][1]["summary_hooks_executor"] is app.executor
    assert not RecordingApplication.active


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_each_cli_no_argument_call_preserves_disabled_compatibility(module_name, monkeypatch):
    """Existing no-argument CLI calls still construct a disabled application."""
    module = importlib.import_module(module_name)
    events = []
    _patch_common(module, monkeypatch, events)

    module.main()

    assert RecordingApplication.instances[0].kwargs == {
        "request": None, "trust_policy": None, "temp_root": None,
    }


def test_each_application_invocation_has_distinct_ownership(monkeypatch):
    """Repeated entry calls do not reuse a process-global application."""
    module = importlib.import_module("topsailai.cli.llm_chat")
    events = []
    _patch_common(module, monkeypatch, events)

    module.main()
    module.main()

    assert len(RecordingApplication.instances) == 2
    assert RecordingApplication.instances[0] is not RecordingApplication.instances[1]
    assert all(item.close_count == 1 for item in RecordingApplication.instances)


def test_factory_executor_is_forwarded_before_lock_and_input(monkeypatch):
    """The infrastructure executor reaches the internal factory unchanged."""
    executor = object()
    captured = {}
    lock_entered = []

    def implementation(**kwargs):
        captured.update(kwargs)
        return "chat"

    class Lock:
        def __enter__(self):
            lock_entered.append("enter")
            return True

        def __exit__(self, *args):
            lock_entered.append("exit")

    monkeypatch.setattr(agent_shell, "_get_agent_chat_impl", implementation)
    monkeypatch.setattr(agent_shell, "ctxm_project_workspace_lock", lambda: Lock())

    assert agent_shell.get_agent_chat(summary_hooks_executor=executor) == "chat"
    assert captured["summary_hooks_executor"] is executor
    assert lock_entered == ["enter", "exit"]


def test_factory_rejects_executor_with_each_legacy_member_before_lock(monkeypatch):
    """Conflicting infrastructure inputs fail before lock or allocation."""
    executor = object()
    lock = Mock(side_effect=AssertionError("lock must not run"))
    monkeypatch.setattr(agent_shell, "ctxm_project_workspace_lock", lock)
    members = (
        {"summary_preparation_request": object()},
        {"summary_trust_policy": object()},
        {"summary_hooks_temp_root": "/tmp/u5"},
    )
    for member in members:
        with pytest.raises(ValueError):
            agent_shell.get_agent_chat(summary_hooks_executor=executor, **member)
    lock.assert_not_called()


def test_business_exception_identity_and_binding_restoration(monkeypatch):
    """The real context preserves the business exception and prior binding."""
    from topsailai.hooks.application_access import bind_hook_application, get_hook_executor
    from topsailai.workspace import hooks_application as module

    previous = module.HookApplicationAccess(None)
    error = RuntimeError("business")
    app = module.HooksApplication()
    with bind_hook_application(previous):
        with pytest.raises(RuntimeError) as raised:
            with app:
                raise error
        assert get_hook_executor()._binding.application is previous


def test_input_message_signature_is_unchanged():
    """U5 does not change the existing input_message API."""
    from inspect import signature
    from topsailai.workspace.input_tool import input_message

    assert tuple(signature(input_message).parameters) == ("tips", "hook", "hook_executor")


@pytest.mark.parametrize("module_name", (
    "topsailai.cli.agent_chat",
    "topsailai.cli.agent_chats",
    "topsailai.cli.team_agent",
    "topsailai.cli.team_chat",
    "topsailai.cli.llm_chat",
    "topsailai.cli.llm_chats",
))
@pytest.mark.parametrize("failure_type", (RuntimeError, KeyboardInterrupt))
def test_real_cli_failure_preserves_identity_and_closes_after_business(
        module_name, failure_type, monkeypatch):
    """Real CLI bodies keep application binding through run/chat failures."""
    module = importlib.import_module(module_name)
    events = []
    _patch_common(module, monkeypatch, events)
    failure = failure_type(module_name)
    if module_name in AGENT_MODULES:
        RecordingChat.run_failure = failure
    else:
        RecordingChat.chat_failure = failure

    with pytest.raises(failure_type) as raised:
        module.main(request=object(), trust_policy=object(), temp_root="/tmp/u5-entry")

    assert raised.value is failure
    assert RecordingApplication.instances[0].events == ["enter", "exit"]
    assert RecordingApplication.instances[0].close_count == 1
    assert not RecordingApplication.active


def test_real_llm_output_handling_runs_while_bound(monkeypatch):
    """Single-run output handling executes before the application closes."""
    module = importlib.import_module("topsailai.cli.llm_chat")
    events = []
    _patch_common(module, monkeypatch, events)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: (
        printed.append((RecordingApplication.active, args))))
    monkeypatch.setattr(module.env_tool, "is_debug_mode", lambda: False)
    monkeypatch.setattr(module.env_tool.EnvReaderInstance, "check_bool",
                        lambda *args, **kwargs: True)

    module.main()

    assert printed
    assert all(active for active, _ in printed)
    assert RecordingApplication.instances[0].close_count == 1



def test_real_disabled_team_chat_writes_result_file_while_application_is_bound(monkeypatch, tmp_path):
    """The real team-chat owner keeps output writing inside the active application."""
    module = importlib.import_module("topsailai.cli.team_chat")
    output = tmp_path / "team-result.txt"
    active = []

    class Chat:
        def chat(self):
            active.append(module.HooksApplication)
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
    assert active == [module.HooksApplication]


def test_real_disabled_team_agent_preserves_exception_identity_and_traceback(monkeypatch):
    """The real team-agent owner restores its binding after a business exception."""
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


def _real_enabled_cli_inputs(tmp_path):
    """Build the real prepared request and deployment authority for CLI ownership tests."""
    from tests.integration.test_hooks_application_lifecycle import _prepared_inputs

    return _prepared_inputs(tmp_path / "prepared")[:2] + (str(tmp_path / "prepared" / "runtime"),)


def _instrument_real_application_stages(monkeypatch):
    """Record exact resource identities and per-owner shutdown counts."""
    from topsailai.hooks.application_access import HookApplicationAccess
    from topsailai.hooks.configured_registration import ConfiguredHookRegistrar
    from topsailai.hooks.runtime import HookRuntime, HookScope
    from topsailai.workspace.hooks_application import HooksApplication

    owners = []
    resource_owner = {}
    original_enter = HooksApplication.__enter__
    original_access_stop = HookApplicationAccess.stop_admission
    original_registrar_stop = ConfiguredHookRegistrar.stop_admission
    original_scope_close = HookScope.close
    original_runtime_close = HookRuntime.close

    def enter(self):
        result = original_enter(self)
        record = {
            "application": self,
            "resources": {
                "access": self.access,
                "registrar": self.registrar,
                "scope": self.scope,
                "runtime": self.runtime,
            },
            "counts": {name: 0 for name in ("access", "registrar", "scope", "runtime")},
        }
        owners.append(record)
        for resource_name, resource in record["resources"].items():
            resource_owner[id(resource)] = (record, resource_name)
        return result

    def count(resource, resource_name):
        record, expected_name = resource_owner[id(resource)]
        assert expected_name == resource_name
        record["counts"][resource_name] += 1
        return record

    def access_stop(self):
        count(self, "access")
        return original_access_stop(self)

    def registrar_stop(self):
        count(self, "registrar")
        return original_registrar_stop(self)

    def scope_close(self, *args, **kwargs):
        count(self, "scope")
        return original_scope_close(self, *args, **kwargs)

    def runtime_close(self, *args, **kwargs):
        count(self, "runtime")
        return original_runtime_close(self, *args, **kwargs)

    monkeypatch.setattr(HooksApplication, "__enter__", enter)
    monkeypatch.setattr(HookApplicationAccess, "stop_admission", access_stop)
    monkeypatch.setattr(ConfiguredHookRegistrar, "stop_admission", registrar_stop)
    monkeypatch.setattr(HookScope, "close", scope_close)
    monkeypatch.setattr(HookRuntime, "close", runtime_close)
    return owners


def _assert_owner_closed_once(owner):
    """Assert each exact owned resource settled exactly once."""
    assert owner["counts"] == {"access": 1, "registrar": 1, "scope": 1, "runtime": 1}


def _traceback_names(error):
    """Return traceback function names for dependency and CLI assertions."""
    return [frame.name for frame in __import__("traceback").extract_tb(error.__traceback__)]


def test_enabled_real_single_cli_exception_restores_outer_binding_and_closes_once(monkeypatch, tmp_path):
    """A real enabled single-run owner keeps binding through failure and closes once."""
    from topsailai.hooks.application_access import bind_hook_application, get_hook_executor
    from topsailai.hooks.application_access import HookApplicationAccess
    from topsailai.cli import agent_chat

    request, trust, root = _real_enabled_cli_inputs(tmp_path)
    owners = _instrument_real_application_stages(monkeypatch)
    outer = HookApplicationAccess(None)
    failure = RuntimeError("real single failure")
    observed = {}

    class Chat:
        def run(self, **kwargs):
            observed["binding"] = get_hook_executor()._binding.application
            observed["counts"] = owners[0]["counts"].copy()
            raise failure

    monkeypatch.setattr(agent_chat, "get_agent_chat", lambda **kwargs: Chat())
    with bind_hook_application(outer):
        with pytest.raises(RuntimeError) as raised:
            agent_chat.main(request=request, trust_policy=trust, temp_root=root)
        assert raised.value is failure
        assert observed["binding"] is owners[0]["resources"]["access"]
        assert observed["counts"] == {name: 0 for name in ("access", "registrar", "scope", "runtime")}
        assert {"run", "main"}.issubset(_traceback_names(raised.value))
        assert get_hook_executor()._binding.application is outer
    assert owners[0]["resources"]["access"] is not outer
    _assert_owner_closed_once(owners[0])


def test_enabled_real_loop_cli_interrupt_restores_outer_binding_and_closes_once(monkeypatch, tmp_path):
    """A real enabled loop owner preserves interruption identity through cleanup."""
    from topsailai.hooks.application_access import bind_hook_application, get_hook_executor
    from topsailai.hooks.application_access import HookApplicationAccess
    from topsailai.cli import llm_chats

    request, trust, root = _real_enabled_cli_inputs(tmp_path)
    owners = _instrument_real_application_stages(monkeypatch)
    outer = HookApplicationAccess(None)
    interrupt = KeyboardInterrupt()
    observed = {}

    class LoopChat:
        def chat(self, *args):
            return "unused"

    def raise_interrupt():
        observed["binding"] = get_hook_executor()._binding.application
        observed["counts"] = owners[0]["counts"].copy()
        raise interrupt

    monkeypatch.setattr(llm_chats, "get_llm_chat", lambda **kwargs: LoopChat())
    monkeypatch.setattr(llm_chats, "input_message", raise_interrupt)
    with bind_hook_application(outer):
        with pytest.raises(KeyboardInterrupt) as raised:
            llm_chats.main(request=request, trust_policy=trust, temp_root=root)
        assert raised.value is interrupt
        assert observed["binding"] is owners[0]["resources"]["access"]
        assert observed["counts"] == {name: 0 for name in ("access", "registrar", "scope", "runtime")}
        assert {"raise_interrupt", "main"}.issubset(_traceback_names(raised.value))
        assert get_hook_executor()._binding.application is outer
    _assert_owner_closed_once(owners[0])


def test_enabled_real_team_output_boundary_precedes_shutdown_and_restores_outer(monkeypatch, tmp_path):
    """Real team output writes while its exact inner owner remains active."""
    import builtins
    from topsailai.hooks.application_access import bind_hook_application, get_hook_executor
    from topsailai.hooks.application_access import HookApplicationAccess
    from topsailai.cli import team_chat

    request, trust, root = _real_enabled_cli_inputs(tmp_path)
    owners = _instrument_real_application_stages(monkeypatch)
    outer = HookApplicationAccess(None)
    output = tmp_path / "team-result.txt"
    written = {}

    class TeamChat:
        def chat(self):
            return "real team result"

    original_open = builtins.open

    class ObservedFile:
        def __init__(self, file_object):
            self.file_object = file_object

        def __enter__(self):
            self.file_object.__enter__()
            return self

        def __exit__(self, *args):
            return self.file_object.__exit__(*args)

        def write(self, content):
            written["binding"] = get_hook_executor()._binding.application
            written["counts"] = owners[0]["counts"].copy()
            written["path"] = str(output)
            written["content"] = content
            return self.file_object.write(content)

        def __getattr__(self, name):
            return getattr(self.file_object, name)

    def observed_open(file, *args, **kwargs):
        opened = original_open(file, *args, **kwargs)
        if str(file) == str(output):
            return ObservedFile(opened)
        return opened

    monkeypatch.setattr(builtins, "open", observed_open)
    monkeypatch.setattr(team_chat, "get_llm_chat", lambda **kwargs: TeamChat())
    monkeypatch.setattr(team_chat, "get_member_name", lambda: "member")
    monkeypatch.setattr(team_chat, "get_system_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(team_chat, "is_team_prompt_precomposed_launch", lambda: False)
    monkeypatch.setattr(team_chat.env_tool, "is_debug_mode", lambda: False)
    monkeypatch.setattr(team_chat.env_tool.EnvReaderInstance, "check_bool", lambda *args, **kwargs: False)
    monkeypatch.setenv("TOPSAILAI_SAVE_RESULT_TO_FILE", str(output))
    with bind_hook_application(outer):
        team_chat.main(request=request, trust_policy=trust, temp_root=root)
        assert written["binding"] is owners[0]["resources"]["access"]
        assert written["counts"] == {name: 0 for name in ("access", "registrar", "scope", "runtime")}
        assert written["path"] == str(output)
        assert written["content"] == "real team result"
        assert get_hook_executor()._binding.application is outer
    assert output.read_text(encoding="utf-8") == "real team result"
    _assert_owner_closed_once(owners[0])


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_all_cli_main_functions_retain_docstrings(module_name):
    """All six public CLI entry points retain their original docstrings."""
    module = importlib.import_module(module_name)
    assert module.main.__doc__
