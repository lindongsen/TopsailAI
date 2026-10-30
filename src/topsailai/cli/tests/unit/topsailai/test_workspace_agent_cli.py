"""Tests for the non-interactive workspace agent command."""

import os
from unittest.mock import patch

import pytest

from cli_topsailai.workspace_agent_cli import run_workspace_agent_cli


def test_relative_folder_uses_startup_cwd(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=7) as launch:
        assert run_workspace_agent_cli(["project", "-m", "raw"], startup_cwd=str(tmp_path)) == 7
    launch.assert_called_once_with(
        str(folder), mode="raw", background=False, entrypoint_base=str(tmp_path)
    )


def test_missing_folder_is_rejected(tmp_path):
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli(["missing"], startup_cwd=str(tmp_path)) == 3
    launch.assert_not_called()


@pytest.mark.parametrize("mechanism", ["raw", "tmux", "dtach"])
def test_background_forwards_each_selected_mechanism(tmp_path, mechanism):
    """Background launch forwards every supported mechanism unchanged."""
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli([str(folder), "-b", "-m", mechanism]) == 0
    launch.assert_called_once_with(
        str(folder), mode=mechanism, background=True, entrypoint_base=os.getcwd()
    )


def test_unknown_json_option_is_usage_error(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli([str(folder), "--json"]) == 2
    launch.assert_not_called()


def test_default_mode_is_forwarded_without_auto(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(["project"], startup_cwd=str(tmp_path)) == 0
    launch.assert_called_once_with(
        str(folder), mode=None, background=False, entrypoint_base=str(tmp_path)
    )


def test_repeated_conflicting_modes_are_usage_errors(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli([str(folder), "-m", "raw", "-m", "tmux"]) == 2
    launch.assert_not_called()


def test_core_main_propagates_startup_cwd_to_workspace_agent(tmp_path, monkeypatch):
    """The real core dispatch forwards the caller startup directory."""
    from cli_topsailai import core
    target = tmp_path / "project"
    target.mkdir()
    seen = {}
    monkeypatch.setattr(core.main, "startup_cwd", str(tmp_path), raising=False)
    with patch("cli_topsailai.workspace_agent_cli.run_workspace_agent_cli", side_effect=lambda argv, startup_cwd: seen.update(argv=argv, startup_cwd=startup_cwd) or 17):
        with pytest.raises(SystemExit) as error:
            core.main(["workspace", "agent", "project", "-m", "raw"])
    assert error.value.code == 17
    assert seen == {"argv": ["project", "-m", "raw"], "startup_cwd": str(tmp_path)}


def test_missing_folder_argument_is_usage_error(capsys):
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli([]) == 2
    assert launch.call_count == 0
    assert "required" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["folder", "extra"], ["folder", "--agent"], ["folder", "--session", "x"], ["folder", "--pid", "1"]])
def test_argument_error_matrix_is_usage_error(argv, capsys):
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli(argv, startup_cwd="/tmp") == 2
    assert launch.call_count == 0
    assert capsys.readouterr().err


def test_dedicated_parser_help_is_offline_and_describes_background_contract(capsys):
    from cli_topsailai.workspace_agent_cli import build_parser
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "Background mode is headless" in normalized
    assert "submission rather than readiness" in normalized


@pytest.mark.parametrize("tool, expected", [("tmux", "tmux"), ("dtach", "dtach"), (None, "raw")])
def test_real_capability_detection_selects_effective_mode(tool, expected, monkeypatch):
    from cli_topsailai import core
    def which(name):
        return "/usr/bin/" + name if name == tool else None
    monkeypatch.setattr(core.shutil, "which", which)
    assert core._detect_agent_mode() == expected


def test_target_path_forms_are_literal(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    spaced = tmp_path / "space folder"
    spaced.mkdir()
    numeric = tmp_path / "123"
    numeric.mkdir()
    dash = tmp_path / "-folder"
    dash.mkdir()
    monkeypatch.setenv("HOME", str(home))
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(["space folder"], startup_cwd=str(tmp_path)) == 0
        assert run_workspace_agent_cli(["123"], startup_cwd=str(tmp_path)) == 0
        assert run_workspace_agent_cli(["--", "-folder"], startup_cwd=str(tmp_path)) == 0
        assert run_workspace_agent_cli(["~"], startup_cwd=str(tmp_path)) == 0
    assert [call.args[0] for call in launch.call_args_list] == [
        str(spaced), str(numeric), str(dash), str(home)
    ]


def test_real_core_parser_resolves_relative_folder_against_startup_cwd(tmp_path, monkeypatch):
    from cli_topsailai import core
    target = tmp_path / "project"
    target.mkdir()
    monkeypatch.setattr(core.main, "startup_cwd", str(tmp_path), raising=False)
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        with pytest.raises(SystemExit) as error:
            core.main(["workspace", "agent", "project", "-m", "raw"])
    assert error.value.code == 0
    launch.assert_called_once_with(
        str(target), mode="raw", background=False, entrypoint_base=str(tmp_path)
    )


class _StatusChild:
    """Finite child double for status and wrapper contract tests."""

    def __init__(self, returncode):
        self.returncode = returncode
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        return self.returncode

    def poll(self):
        self.calls.append(("poll", None))
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", None))

    def kill(self):
        self.calls.append(("kill", None))


def test_status_matrix_and_output_channels(tmp_path, capsys):
    from cli_topsailai.agent_launch import launch_configured_agent
    for code in (0, 1, 2, 42, 127, 255, -2, -15):
        child = _StatusChild(returncode=code)
        with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=lambda _: ({}, set())), \
             patch("cli_topsailai.agent_launch._session_id", return_value="fixed"):
            result = launch_configured_agent(str(tmp_path), mode="raw", spawn=lambda *a, **k: child)
        expected = code if code >= 0 else 128 + -code
        assert result == expected
        captured = capsys.readouterr()
        launch_line = (
            f"[INFO] Launching agent: workspace={tmp_path} mode=raw "
            "background=no session=fixed\n"
        )
        exit_line = (
            f"[INFO] Agent launcher exited: code={code} session=fixed\n"
            if code == 0
            else f"[ERROR] Agent launcher exited: code={code} session=fixed\n"
        )
        assert captured.out == launch_line + (exit_line if code == 0 else "")
        assert captured.err == ("" if code == 0 else exit_line)
        assert child.calls == [("wait", None)]


def test_wrapper_exit_does_not_terminate_server_or_claim_completion(tmp_path, capsys):
    from cli_topsailai.agent_launch import launch_configured_agent
    child = _StatusChild(returncode=0)
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment", side_effect=lambda _: ({}, set())), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed"), \
         patch("cli_topsailai.agent_launch._wrap_command_for_agent_mode", return_value="tmux command") as wrap:
        assert launch_configured_agent(str(tmp_path), mode="tmux", spawn=lambda *a, **k: child) == 0
    assert child.calls == [("wait", None)]
    output = capsys.readouterr()
    assert "completed" not in output.out.lower() + output.err.lower()
    wrap.assert_called_once()
