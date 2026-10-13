"""Exercise existing main dispatch under isolated workspace dependencies.

Author: DawsonLin
"""
from unittest.mock import Mock

import pytest
from cli_topsailai import core, state


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Replace external I/O while retaining the real main control flow."""
    from cli_topsailai import (cleaning, completer, doc_scope, formatting, help_text,
                              history, log_files, paths, process, project_scope,
                              retrieve, session_info, streaming, yaml_commands)
    monkeypatch.setattr(state, "running", True)
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "current_session_id", None)
    monkeypatch.setattr(core, "_project_scope_mode", "sessions")
    row = dict(session_id="sample", pid=123, session_pid=123, path="/unused",
               filename="sample.123.session.stdout")
    mocks = {}
    specs = [(core, "setup_signal_handlers", None), (core, "_driver_authority", None),
             (core, "_enrich_driver_rows", None), (core, "_reap_driver_children", None),
             (core, "_handle_driver_action", None), (core, "_resume_from_workspace_log", None),
             (core, "_prompt_project_workspace", str(tmp_path)),
             (core, "_handle_models_action", None), (core, "add_project", True),
             (core, "delete_project_by_index", True),
             (core, "build_doc_list", [dict(rel_path="usage/sample.md")]),
             (core, "print_doc_table", None), (core, "get_docs_dir", str(tmp_path)),
             (core, "resolve_doc", dict(status="ok", rel_path="usage/sample.md", content="body")),
             (history, "HistoryManager", Mock()), (history, "load_readline_history", None),
             (completer, "setup_tab_completion", None),
             (yaml_commands, "load_yaml_commands", []), (paths, "get_topsailai_home", str(tmp_path)),
             (log_files, "discover_log_files", [row]), (formatting, "print_table", None),
             (session_info, "enrich_files_with_session_names", None),
             (session_info, "enrich_running_unnamed_sessions", None),
             (process, "cleanup_children", None), (streaming, "stream_file", None),
             (streaming, "handle_send_command", None), (retrieve, "retrieve_session", None),
             (cleaning, "clean_expired_files", None), (cleaning, "clean_by_numbers", None),
             (project_scope, "build_project_list", [row]),
             (project_scope, "build_managed_project_list", [row]),
             (project_scope, "print_project_table", None),
             (project_scope, "print_managed_project_table", None),
             (project_scope, "resolve_agent_folder", str(tmp_path)),
             (project_scope, "launch_agent_in_folder", None),
             (project_scope, "resume_session", None),
             (help_text, "print_help", None), (help_text, "print_scopes", None),
             (help_text, "print_instruction_help", None)]
    for module, name, value in specs:
        mock = Mock(return_value=value)
        monkeypatch.setattr(module, name, mock)
        mocks[name] = mock

    def run(actions, scope="workspace", managed=False, initial="workspace"):
        """Run bounded actions with explicit scope transitions and final quit."""
        state.current_scope = initial
        iterator = iter(actions + [("quit", None)])
        def prompt(*args):
            """Inject displayed-list actions and scope facts at the boundary."""
            state.current_scope = scope
            state.workspace_showing_managed_projects = managed
            core._project_scope_mode = "managed" if managed else "sessions"
            return next(iterator)
        monkeypatch.setattr(core, "prompt_selection", prompt)
        core.main([])
        mocks["cleanup_children"].assert_called_once()
    return run, mocks, row


@pytest.mark.parametrize("scope", ["workspace", "project", "doc"])
def test_dispatch_actions(harness, scope):
    """Verify action dispatch and scope-sensitive cleanup/send/resume routes."""
    run, mocks, row = harness
    actions = [("refresh", None), ("help", "meta"), ("scopes", None),
               ("help_cmd", {}), ("models", "current"), ("clean", None),
               ("clean_numbers", [0]), ("send", "/send 1 hi"), ("agent", "1"),
               ("agent_managed_project", "1"), ("resume", "1"),
               ("session", 0), ("session_id", "sample"), ("enter_session", "sample"),
               ("enter_doc", None), ("read_doc", 0), ("leave_scope", None),
               ("watch", 0), ("show_managed_projects", None), ("show_recent_projects", None),
               ("add_managed_project", "/folder name"), ("delete_managed_project", "1")]
    run(actions, scope)
    mocks["print_help"].assert_called_once()
    mocks["handle_send_command"].assert_called_once()
    mocks["launch_agent_in_folder"].assert_called()
    mocks["retrieve_session"].assert_any_call("sample", max_chars=1000)
    mocks["add_project"].assert_called_once_with("/folder", name="name")
    mocks["delete_project_by_index"].assert_called_once_with(1)


@pytest.mark.parametrize("status", ["conflict", "missing"])
def test_doc_failure(harness, status):
    """Malformed document resolution stays in the command loop."""
    run, mocks, _ = harness
    mocks["resolve_doc"].return_value = dict(status=status, options=["usage/a.md"])
    run([("enter_doc", None), ("read_doc", 0)], "doc")
    mocks["resolve_doc"].assert_called_once_with("usage/sample.md")


@pytest.mark.parametrize("scope", ["workspace", "project"])
def test_managed_rejection(harness, scope):
    """Managed lists cannot watch logs; project lists cannot retrieve sessions."""
    run, mocks, _ = harness
    run([("show_managed_projects", None), ("watch", 0), ("session", 0),
         ("refresh", None), ("driver_start", 0)], scope, True)
    mocks["stream_file"].assert_not_called()
    mocks["_handle_driver_action"].assert_not_called()


@pytest.mark.parametrize("action", ["agent", "agent_managed_project"])
def test_invalid_agent_folder(harness, action):
    """Unresolvable folders never launch an agent."""
    run, mocks, _ = harness
    mocks["resolve_agent_folder"].return_value = None
    run([(action, "bad")])
    mocks["launch_agent_in_folder"].assert_not_called()


@pytest.mark.parametrize("value", ["", "invalid", "1"])
def test_delete_failures(harness, value):
    """Invalid selection or registry rejection is not reported as deletion."""
    run, mocks, _ = harness
    mocks["delete_project_by_index"].return_value = False
    run([("delete_managed_project", value)])
    assert mocks["delete_project_by_index"].call_count == (1 if value == "1" else 0)


@pytest.mark.parametrize("path,name,accepted", [("", "", False), ("/folder", "", False),
                                               ("/folder", "name", True)])
def test_add_prompt(harness, monkeypatch, path, name, accepted):
    """Interactive registry inputs preserve empty-path and rejection rules."""
    run, mocks, _ = harness
    inputs = iter([path, name])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    mocks["add_project"].return_value = accepted
    run([("add_managed_project", "")])
    assert mocks["add_project"].call_count == bool(path)


def test_models_no_project(harness):
    """No selected workspace prevents project-specific model mutation."""
    run, mocks, _ = harness
    mocks["_prompt_project_workspace"].return_value = None
    run([("models", "clear")], "project")
    mocks["_handle_models_action"].assert_not_called()


def test_missing_session(harness):
    """Incomplete rows cannot retrieve another session's content."""
    run, mocks, row = harness
    row["session_id"] = None
    run([("session", 0)])
    mocks["retrieve_session"].assert_not_called()


def test_temp_watch(harness):
    """Temporary labels normalize only at the existing watcher boundary."""
    run, mocks, row = harness
    row["session_id"] = "(temp)"
    run([("watch", 0)])
    assert mocks["stream_file"].call_args.kwargs["default_session_id"] == "topsailai"


@pytest.mark.parametrize("initial", ["project", "doc"])
def test_initial_scope(harness, initial):
    """Initial nonworkspace scope is refreshed before selection."""
    run, mocks, _ = harness
    run([], initial=initial)
    mocks["cleanup_children"].assert_called_once()


@pytest.mark.parametrize("scope", ["project", "doc", "workspace", "session"])
def test_yaml_scope_transition(harness, monkeypatch, scope):
    """YAML actions refresh only recognized changed scopes."""
    run, mocks, _ = harness
    count = 0
    def prompt(*args):
        """Publish a scope transition once, then exit normally."""
        nonlocal count
        count += 1
        if count == 1:
            state.current_scope = scope
            return "yaml_handled", None
        if count == 2:
            state.current_scope = "workspace"
            return "yaml_handled", None
        return "quit", None
    monkeypatch.setattr(core, "prompt_selection", prompt)
    core.main([])
    assert count == 3
    mocks["cleanup_children"].assert_called_once()


@pytest.mark.parametrize("argv,code", [
    (["unknown"], 1), (["-n", "10", "unknown"], 1),
    (["--help"], 0), (["--version"], 0),
    (["-w"], 0), (["--list-docs"], 0), (["--read-doc", "sample"], 0),
    (["workspace"], 0), (["docs"], 1), (["project"], 1),
    (["docs", "list"], 0), (["models"], 0),
])
def test_main_argument_routes(monkeypatch, capsys, argv, code):
    """Argument routing exits before interactive or external operations."""
    for name in ("_handle_workspace_subcommand", "_handle_docs_list_subcommand",
                 "_handle_docs_read_subcommand", "_handle_models_subcommand"):
        monkeypatch.setattr(core, name, Mock(return_value=0))
    with pytest.raises(SystemExit) as exc:
        core.main(argv)
    assert exc.value.code == code
    if "unknown" in argv:
        assert "invalid subcommand" in capsys.readouterr().err
