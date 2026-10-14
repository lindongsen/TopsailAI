"""Workspace termination safety and command discovery tests.

Author: DawsonLin
"""
from types import SimpleNamespace
from unittest.mock import Mock
import signal

import pytest
from cli_topsailai import core, state, workspace_kill, completer, help_text


@pytest.fixture
def killer(monkeypatch):
    """Replace only the consumer OS reference to prevent real signals."""
    kill = Mock()
    monkeypatch.setattr(workspace_kill, "os", SimpleNamespace(kill=kill, getpid=lambda: 555))
    return kill


@pytest.mark.parametrize("answer", ["y", "yes", " YES "])
def test_exact_displayed_pid(killer, answer, capsys):
    """Confirmation targets the displayed PID, not filename/parent/driver PID."""
    read = Mock(return_value=answer)
    rows = [{"workspace_pid": 1234, "pid": 9999, "session_pid": 7777, "session_id": "sample"}]
    assert workspace_kill.kill_workspace_row(rows, 0, read_input=read)
    killer.assert_called_once_with(1234, signal.SIGTERM)
    assert "session=sample, PID=1234" in read.call_args.args[0]
    assert "exit is not confirmed" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "no", "sure"])
def test_cancel(killer, answer):
    """Only affirmative confirmation authorizes signaling."""
    assert not workspace_kill.kill_workspace_row([{"workspace_pid": 1234}], 0, read_input=lambda _: answer)
    killer.assert_not_called()


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_interrupt(killer, error):
    """Input interruption cancels rather than killing."""
    assert not workspace_kill.kill_workspace_row([{"workspace_pid": 1234}], 0, read_input=Mock(side_effect=error))
    killer.assert_not_called()


@pytest.mark.parametrize("index", [-1, 1, None, True])
def test_invalid_row(killer, index):
    """Invalid indices cannot authorize termination."""
    read = Mock()
    assert not workspace_kill.kill_workspace_row([{}], index, read_input=read)
    read.assert_not_called()
    killer.assert_not_called()


@pytest.mark.parametrize("pid", [None, 0, -1, "1234", True, 2147483648, 1, 555])
def test_missing_or_unsafe_pid(killer, pid):
    """Reject absent, malformed and protected displayed PIDs without fallback."""
    read = Mock()
    assert not workspace_kill.kill_workspace_row([{"workspace_pid": pid, "pid": 1234}], 0, read_input=read)
    read.assert_not_called()
    killer.assert_not_called()


@pytest.mark.parametrize("error", [ProcessLookupError("exited"), PermissionError("denied"), OSError("unavailable")])
def test_signal_error(killer, error, capsys):
    """Report OS failures with exact target and exception context."""
    killer.side_effect = error
    assert not workspace_kill.kill_workspace_row([{"workspace_pid": 1234}], 0, read_input=lambda _: "y")
    killer.assert_called_once_with(1234, signal.SIGTERM)
    out = capsys.readouterr().out
    assert "PID=1234" in out and type(error).__name__ in out


@pytest.mark.parametrize("scope,managed,command,expected", [
    ("workspace", False, "/kill 1", ("kill", 0)),
    ("workspace", False, "/KILL 1", ("kill", 0)),
    ("workspace", False, "/kill 2", ("quit", None)),
    ("workspace", False, "/kill 0", ("quit", None)),
    ("workspace", False, "/kill", ("quit", None)),
    ("workspace", False, "/kill -1", ("quit", None)),
    ("workspace", False, "/kill 1 extra", ("quit", None)),
    ("workspace", False, "/kill 9999999999", ("quit", None)),
    ("workspace", True, "/kill 1", ("quit", None)),
    ("project", False, "/kill 1", ("quit", None)),
    ("session", False, "/kill 1", ("quit", None)),
    ("runtime", False, "/kill 1", ("quit", None)),
    ("doc", False, "/kill 1", ("leave_scope", None)),
])
def test_prompt(monkeypatch, killer, scope, managed, command, expected):
    """Parsing never signals and restricts destructive commands to workspace."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    monkeypatch.setattr(state, "history_manager", None)
    commands = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(commands))
    assert core.prompt_selection([{}], "/unused") == expected
    killer.assert_not_called()


def test_discovery(monkeypatch, capsys):
    """Workspace completion and help consistently expose the command."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "yaml_commands", [])
    assert "/kill" in completer.get_available_completions()
    help_text.print_help([], "workspace", keyword="kill")
    assert "/kill <number>" in capsys.readouterr().out
    monkeypatch.setattr(state, "workspace_showing_managed_projects", True)
    assert "/kill" not in completer.get_available_completions()


@pytest.fixture
def installed_cli_handlers(monkeypatch):
    """Install real CLI handlers but isolate all child cleanup and restore state."""
    from cli_topsailai import process
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    cleanup = Mock()
    monkeypatch.setattr(process, "cleanup_children", cleanup)
    monkeypatch.setattr(state, "running", True)
    try:
        core.setup_signal_handlers()
        assert signal.getsignal(signal.SIGINT) is process.signal_handler
        yield cleanup, process.signal_handler
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_ctrl_c_bypasses_real_global_cleanup(killer, installed_cli_handlers, capsys):
    """Dispatch a simulated SIGINT through the installed callback, not an OS signal."""
    cleanup, global_handler = installed_cli_handlers

    def interrupted_input(prompt):
        """Invoke the handler Python would dispatch during confirmation."""
        assert signal.getsignal(signal.SIGINT) is not global_handler
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        pytest.fail("SIGINT must interrupt confirmation")

    assert not workspace_kill.kill_workspace_row(
        [{"workspace_pid": 1234}], 0, read_input=interrupted_input
    )
    killer.assert_not_called()
    cleanup.assert_not_called()
    assert state.running is True
    assert signal.getsignal(signal.SIGINT) is global_handler
    assert "Cancelled termination" in capsys.readouterr().out

    # Prove the restored handler still has the actual exit/cleanup semantics.
    with pytest.raises(SystemExit) as exc:
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
    assert exc.value.code == 0
    cleanup.assert_called_once_with()
    assert state.running is False
    killer.assert_not_called()


@pytest.mark.parametrize("outcome", ["yes", "no", EOFError, KeyboardInterrupt, RuntimeError])
def test_confirmation_restores_global_handler(killer, installed_cli_handlers, outcome):
    """Restore global SIGINT on acceptance, cancellation and unexpected errors."""
    cleanup, global_handler = installed_cli_handlers

    def read_input(prompt):
        """Require the local handler while input is being read."""
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        if isinstance(outcome, type):
            raise outcome()
        return outcome

    def terminate(pid, sig):
        """Require restoration before any mocked process signal."""
        assert signal.getsignal(signal.SIGINT) is global_handler

    killer.side_effect = terminate
    if outcome is RuntimeError:
        with pytest.raises(RuntimeError):
            workspace_kill.kill_workspace_row([{"workspace_pid": 1234}], 0, read_input=read_input)
    else:
        assert workspace_kill.kill_workspace_row(
            [{"workspace_pid": 1234}], 0, read_input=read_input
        ) is (outcome == "yes")
    assert signal.getsignal(signal.SIGINT) is global_handler
    assert state.running is True
    cleanup.assert_not_called()
    if outcome == "yes":
        killer.assert_called_once_with(1234, signal.SIGTERM)
    else:
        killer.assert_not_called()
