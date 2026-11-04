"""Tests for the non-interactive workspace agent command."""

import json
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
        str(folder), mode="raw", background=False, entrypoint_base=str(tmp_path),
        non_interactive=False,
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
        str(folder), mode=mechanism, background=True, entrypoint_base=os.getcwd(),
        non_interactive=False,
    )


def test_json_option_emits_foreground_receipt(tmp_path, capsys):
    folder = tmp_path / "project"
    folder.mkdir()

    def launch(_folder, **kwargs):
        kwargs["receipt"].update(
            session_id="session-1", workspace=str(folder), mode="raw",
            background=False, resumed=False, launcher_pid=321,
            startup_confirmed=False, child_exit_code=0,
            launcher_exit_observed=True,
        )
        print("child output", file=kwargs["child_stdout"])
        return 0

    with patch("cli_topsailai.agent_launch.launch_configured_agent", side_effect=launch):
        assert run_workspace_agent_cli([str(folder), "--json"]) == 0
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["ok"] is True
    assert receipt["action"] == "agent"
    assert receipt["session_id"] == "session-1"
    assert receipt["pid"] == 321
    assert receipt["delivery_state"] == "launcher_exited"
    assert receipt["response"] == {
        "workspace": str(folder), "mode": "raw", "background": False,
        "resumed": False, "launcher_pid": 321, "log_path": None,
        "startup_confirmed": False, "child_exit_code": 0,
    }
    assert captured.err == "child output\n"


def test_json_foreground_pid_without_observed_exit_is_uncertain(tmp_path, capsys):
    """A spawned launcher is not reported exited when wait and cleanup are unresolved."""
    folder = tmp_path / "project"
    folder.mkdir()

    def launch(_folder, **kwargs):
        kwargs["receipt"].update(
            session_id="session-1", workspace=str(folder), mode="raw",
            background=False, launcher_pid=321, spawn_confirmed=True,
            effect_uncertain=True,
        )
        return 6

    with patch("cli_topsailai.agent_launch.launch_configured_agent", side_effect=launch):
        assert run_workspace_agent_cli([str(folder), "--json"]) == 6
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["delivery_state"] == "delivery_unknown"
    assert receipt["delivery_unknown"] is True
    assert "retry blindly" in receipt["message"]


def test_json_background_unconfirmed_effect_is_not_not_delivered(tmp_path, capsys):
    """An unresolved background acknowledgement preserves uncertain side effects."""
    folder = tmp_path / "project"
    folder.mkdir()

    def launch(_folder, **kwargs):
        kwargs["receipt"].update(
            session_id="session-1", workspace=str(folder), mode="raw",
            background=True, submission_attempted=True, effect_uncertain=True,
        )
        return 6

    with patch("cli_topsailai.agent_launch.launch_configured_agent", side_effect=launch):
        assert run_workspace_agent_cli([str(folder), "-b", "--json"]) == 6
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["delivery_state"] == "delivery_unknown"
    assert receipt["delivery_unknown"] is True


def test_default_mode_is_forwarded_without_auto(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(["project"], startup_cwd=str(tmp_path)) == 0
    launch.assert_called_once_with(
        str(folder), mode=None, background=False, entrypoint_base=str(tmp_path),
        non_interactive=False,
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


def test_omitted_folder_defaults_to_startup_cwd(tmp_path):
    """An omitted folder launches in the caller's working directory."""
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli([], startup_cwd=str(tmp_path)) == 0
    launch.assert_called_once_with(
        str(tmp_path), mode=None, background=False, entrypoint_base=str(tmp_path),
        non_interactive=False,
    )


def test_omitted_folder_without_startup_cwd_uses_process_cwd(tmp_path, monkeypatch):
    """Without a recorded startup directory the process working directory is used."""
    monkeypatch.chdir(tmp_path)
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli([]) == 0
    launch.assert_called_once_with(
        str(tmp_path), mode=None, background=False, entrypoint_base=str(tmp_path),
        non_interactive=False,
    )


@pytest.mark.parametrize(
    "argv, expected_mode, expected_background",
    [(["-m", "raw"], "raw", False), (["-b"], None, True), (["-b", "-m", "tmux"], "tmux", True)],
)
def test_options_only_invocation_uses_default_folder(
    tmp_path, argv, expected_mode, expected_background
):
    """Options without a folder still launch in the caller's working directory."""
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(argv, startup_cwd=str(tmp_path)) == 0
    launch.assert_called_once_with(
        str(tmp_path), mode=expected_mode, background=expected_background,
        entrypoint_base=str(tmp_path),
        non_interactive=False,
    )


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
        str(target), mode="raw", background=False, entrypoint_base=str(tmp_path),
        non_interactive=False,
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


def test_non_interactive_flag_is_forwarded_to_the_launch(tmp_path):
    """The flag reaches the launch boundary instead of being parsed and dropped."""
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(
            [str(folder), "--non-interactive"], startup_cwd=str(tmp_path)
        ) == 0
    launch.assert_called_once_with(
        str(folder), mode=None, background=False, entrypoint_base=str(tmp_path),
        non_interactive=True,
    )


def test_non_interactive_flag_is_forwarded_in_json_mode(tmp_path):
    """JSON mode forwards the flag through the same boundary."""
    folder = tmp_path / "project"
    folder.mkdir()

    def launch(folder_arg, **kwargs):
        kwargs["receipt"].update(session_id="s", launcher_pid=1, child_exit_code=0)
        return 0

    with patch("cli_topsailai.agent_launch.launch_configured_agent", side_effect=launch) as boundary:
        assert run_workspace_agent_cli(
            [str(folder), "--non-interactive", "--json"], startup_cwd=str(tmp_path)
        ) == 0
    assert boundary.call_args.kwargs["non_interactive"] is True


def test_non_interactive_flag_is_forwarded_in_background_mode(tmp_path):
    """Background submission carries the flag to the detached supervisor."""
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(
            [str(folder), "-b", "--non-interactive"], startup_cwd=str(tmp_path)
        ) == 0
    assert launch.call_args.kwargs["non_interactive"] is True
    assert launch.call_args.kwargs["background"] is True


def test_non_interactive_flag_is_optional_and_defaults_to_off(tmp_path):
    """Omitting the flag keeps the previous launch request unchanged."""
    folder = tmp_path / "project"
    folder.mkdir()
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli([str(folder)], startup_cwd=str(tmp_path)) == 0
    assert launch.call_args.kwargs["non_interactive"] is False


def test_non_interactive_flag_does_not_change_the_agent_interactive_mode(tmp_path):
    """The flag governs the launch only and never touches the agent's own mode.

    The agent's internal interactive mode is an environment concern, so the
    proof is that the launched environment is identical with and without the
    flag rather than that the variable is absent from the ambient environment.
    """
    folder = tmp_path / "project"
    folder.mkdir()

    def launch(non_interactive):
        child = _StatusChild(returncode=0)
        calls = []

        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            return child

        with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
                   side_effect=lambda _: ({}, set())), \
             patch("cli_topsailai.agent_launch._session_id", return_value="fixed"):
            from cli_topsailai.agent_launch import launch_configured_agent
            assert launch_configured_agent(
                str(folder), mode="raw", spawn=spawn,
                non_interactive=non_interactive,
            ) == 0
        return calls[0]

    plain_argv, plain_kwargs = launch(False)
    flagged_argv, flagged_kwargs = launch(True)

    assert flagged_argv == plain_argv + ["--non-interactive"]
    # Only the argv differs; the environment the agent receives is untouched.
    assert flagged_kwargs["env"] == plain_kwargs["env"]


def test_non_interactive_flag_is_absent_from_argv_when_not_requested(tmp_path):
    """A launch without the flag produces the historical argv exactly."""
    folder = tmp_path / "project"
    folder.mkdir()
    child = _StatusChild(returncode=0)
    calls = []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return child

    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               side_effect=lambda _: ({}, set())), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed"):
        from cli_topsailai.agent_launch import launch_configured_agent
        assert launch_configured_agent(str(folder), mode="raw", spawn=spawn) == 0
    assert calls[0][0] == [
        "topsailai_launch_agent", "--subprocess", "--session-id", "fixed",
    ]


def test_resume_driver_never_receives_launcher_flags():
    """A resume driver is a different executable, so launcher flags are omitted."""
    from cli_topsailai.agent_launch_command import launcher_command

    assert launcher_command("s", driver="topsailai_agent_chats",
                            non_interactive=True) == ["topsailai_agent_chats"]
    assert launcher_command("s", non_interactive=True) == [
        "topsailai_launch_agent", "--subprocess", "--session-id", "s",
        "--non-interactive",
    ]


# Initial task forwarding: keep the task on the fresh-launch command contract.
def test_task_is_forwarded_without_normalizing_multiline_unicode(tmp_path):
    """The public parser preserves the exact first-task text."""
    folder = tmp_path / "project"
    folder.mkdir()
    task = "检查项目\n修复失败测试 🚀"
    with patch("cli_topsailai.agent_launch.launch_configured_agent", return_value=0) as launch:
        assert run_workspace_agent_cli(
            [str(folder), "--task", task], startup_cwd=str(tmp_path)
        ) == 0
    launch.assert_called_once_with(
        str(folder), mode=None, background=False, entrypoint_base=str(tmp_path),
        non_interactive=False, task=task,
    )


@pytest.mark.parametrize("task", ["", " ", "\n\t"])
def test_blank_task_is_a_usage_error_before_launch(tmp_path, capsys, task):
    """An explicit task must contain at least one non-whitespace character."""
    with patch("cli_topsailai.agent_launch.launch_configured_agent") as launch:
        assert run_workspace_agent_cli(
            [str(tmp_path), "--task", task], startup_cwd=str(tmp_path)
        ) == 2
    launch.assert_not_called()
    assert "--task must contain a non-whitespace message" in capsys.readouterr().err


def test_json_task_is_forwarded_but_never_copied_into_receipt(tmp_path, capsys):
    """Structured launch output does not disclose the first-task text."""
    task = "private task marker 9d6e"

    def launch(_folder, **kwargs):
        assert kwargs["task"] == task
        kwargs["receipt"].update(
            session_id="s", workspace=str(tmp_path), mode="raw",
            background=False, child_exit_code=0, launcher_exit_observed=True,
        )
        return 0

    with patch("cli_topsailai.agent_launch.launch_configured_agent", side_effect=launch):
        assert run_workspace_agent_cli(
            [str(tmp_path), "--task", task, "--json"], startup_cwd=str(tmp_path)
        ) == 0
    captured = capsys.readouterr()
    assert task not in captured.out
    assert task not in captured.err
    assert json.loads(captured.out)["ok"] is True


def test_foreground_launcher_argv_contains_exact_task(tmp_path):
    """The fresh launcher receives the task as one exact argv value."""
    from cli_topsailai.agent_launch import launch_configured_agent

    task = "first line\n第二行"
    child = _StatusChild(returncode=0)
    calls = []
    with patch("cli_topsailai.agent_launch._apply_selected_model_environment",
               side_effect=lambda _: ({}, set())), \
         patch("cli_topsailai.agent_launch._session_id", return_value="fixed"):
        assert launch_configured_agent(
            str(tmp_path), mode="raw", task=task,
            spawn=lambda argv, **kwargs: calls.append((argv, kwargs)) or child,
        ) == 0
    assert calls[0][0] == [
        "topsailai_launch_agent", "--subprocess", "--session-id", "fixed",
        "--task", task,
    ]
    assert task not in calls[0][1]["env"].values()


def test_resume_driver_never_receives_initial_task():
    """A resume executable is not a fresh launcher and receives no task flag."""
    from cli_topsailai.agent_launch_command import launcher_command

    assert launcher_command(
        "s", driver="topsailai_agent_chats", task="new task",
        non_interactive=True,
    ) == ["topsailai_agent_chats"]
