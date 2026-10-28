"""Tests for the non-interactive workspace resume command."""

from unittest.mock import patch

from cli_topsailai.workspace_resume_cli import build_parser, run_workspace_resume_cli


def test_parser_requires_exact_session_id():
    """The parser exposes the exact persisted session identity through the required session option."""
    args = build_parser().parse_args(["-s", "session-123", "-m", "raw", "-b"])
    assert args.session_id == "session-123"
    assert args.agent_mode == "raw"
    assert args.background is True


def test_background_rejects_non_raw_mode(capsys):
    """Background resume refuses terminal-attached modes before lookup."""
    assert run_workspace_resume_cli(["-s", "session-123", "-m", "dtach", "-b"]) == 2
    assert "raw mode only" in capsys.readouterr().err


def test_resume_delegates_exact_identity_and_background_options():
    """The CLI delegates the exact session and selected launch options."""
    with patch(
        "cli_topsailai.project_scope.resume_session_result",
        return_value=0,
    ) as resume:
        assert run_workspace_resume_cli(["-s", "session-123", "-m", "raw", "-b"]) == 0
    resume.assert_called_once_with(
        "session-123", agent_mode="raw", background=True,
    )


def test_resume_propagates_boundary_status():
    """Resume returns the shared boundary status unchanged."""
    with patch(
        "cli_topsailai.project_scope.resume_session_result",
        return_value=6,
    ):
        assert run_workspace_resume_cli(["-s", "session-123", "-m", "raw"]) == 6


def test_core_resume_help_exits_without_lookup(capsys):
    """Resume help reaches argparse without entering the watcher or lookup."""
    import pytest
    from cli_topsailai import core

    with patch("cli_topsailai.project_scope.resume_session_result") as resume:
        with pytest.raises(SystemExit) as error:
            core.main(["workspace", "resume", "--help"])
    assert error.value.code == 0
    assert "--session" in capsys.readouterr().out
    resume.assert_not_called()


def test_core_resume_forwards_exact_background_request():
    """The actual core parser forwards the session and propagates exit status."""
    import pytest
    from cli_topsailai import core

    # The shim records the caller startup directory on ``core.main``; pin it so
    # this assertion does not depend on which test ran first.
    with patch.object(core.main, "startup_cwd", None, create=True), patch(
        "cli_topsailai.project_scope.resume_session_result", return_value=6
    ) as resume:
        with pytest.raises(SystemExit) as error:
            core.main(["workspace", "resume", "-s", "session-123", "-m", "raw", "-b"])
    assert error.value.code == 6
    resume.assert_called_once_with("session-123", agent_mode="raw", background=True)


def test_core_resume_rejects_missing_session_and_invalid_mode():
    """Malformed resume requests exit before touching session state."""
    import pytest
    from cli_topsailai import core

    for argv in (["workspace", "resume"],
                 ["workspace", "resume", "-s", "s", "-m", "invalid"]):
        with patch("cli_topsailai.project_scope.resume_session_result") as resume:
            with pytest.raises(SystemExit) as error:
                core.main(argv)
        assert error.value.code == 2
        resume.assert_not_called()


def test_workspace_handler_preserves_agent_and_list_routes():
    """The repaired handler retains agent dispatch and both list output modes."""
    from argparse import Namespace
    from cli_topsailai import core

    args = Namespace(workspace_command="agent", agent_args=["folder"], startup_cwd="/startup")
    with patch("cli_topsailai.workspace_agent_cli.run_workspace_agent_cli", return_value=17) as agent:
        assert core._handle_workspace_subcommand(args) == 17
    agent.assert_called_once_with(["folder"], startup_cwd="/startup")
    with patch.object(core, "_print_workspace_json") as output:
        assert core._handle_workspace_subcommand(Namespace(format="json")) == 0
        output.assert_called_once_with()
    with patch.object(core, "_print_workspace_table") as output:
        assert core._handle_workspace_subcommand(Namespace()) == 0
        output.assert_called_once_with()


def test_background_defaults_to_raw():
    """A background request needs no redundant explicit raw flag."""
    with patch("cli_topsailai.project_scope.resume_session_result", return_value=0) as resume:
        assert run_workspace_resume_cli(["-s", "session-123", "-b"], startup_cwd="/startup") == 0
    resume.assert_called_once_with(
        "session-123", agent_mode="raw", background=True, entrypoint_base="/startup",
    )


def test_core_resume_rejects_unknown_flags_before_lookup():
    """Strict early dispatch must not discard unrecognized arguments."""
    import pytest
    from cli_topsailai import core

    for extra in ("--json", "--pid", "--yes", "--driver", "--agent-m", "extra"):
        with patch("cli_topsailai.project_scope.resume_session_result") as resume:
            with pytest.raises(SystemExit) as error:
                core.main(["workspace", "resume", "-s", "session-123", extra])
        assert error.value.code == 2
        resume.assert_not_called()


def test_directory_inspection_failure_is_unknown():
    """Permission errors cannot authorize a resume as idle."""
    from cli_topsailai import project_scope as scope

    with patch.object(scope.os, "listdir", side_effect=PermissionError("denied")):
        assert scope.session_liveness("session-123", home="/test-home") == "unknown"


def test_older_live_candidate_is_not_hidden(tmp_path):
    """A dead newer PID cannot hide any other live session PID."""
    from cli_topsailai import project_scope as scope

    task = tmp_path / "workspace" / "task"
    task.mkdir(parents=True)
    (task / "session-123.101.session.stdout").touch()
    (task / "session-123.102.session.stdout").touch()
    with patch.object(scope, "_pid_state", side_effect=lambda pid: "alive" if pid == 101 else "dead"):
        assert scope.session_liveness("session-123", home=str(tmp_path)) == "live"


def test_idle_to_live_race_prevents_launch(tmp_path):
    """A liveness flip during preparation is refused at the launch boundary."""
    from cli_topsailai import project_scope as scope

    record = {"session_id": "session-123", "project_workspace": str(tmp_path)}
    observed = {}

    def _launch(*args, **kwargs):
        """Stand in for the launch boundary and honour its late check."""
        check = kwargs.get("prelaunch_check")
        observed["check"] = check
        refusal = check() if check is not None else None
        return refusal if refusal is not None else 0

    with patch.object(scope, "session_liveness", side_effect=["idle", "live"]) as live:
        with patch.object(scope, "launch_agent_driver", side_effect=_launch) as launch:
            assert scope.resume_session_result(
                "session-123", query=lambda sid: [record], agent_mode="raw",
            ) == 4
    assert live.call_count == 2
    launch.assert_called_once()
    assert observed["check"] is not None


def test_exact_lookup_once_and_foreground_status(tmp_path):
    """Resolve the literal identity once and preserve the actual launch result."""
    from unittest.mock import Mock
    from cli_topsailai import project_scope as scope

    record = {"session_id": "123", "project_workspace": str(tmp_path)}
    query = Mock(return_value=[{"session_id": "123-prefix"}, record])
    with patch.object(scope, "session_liveness", return_value="idle"):
        with patch.object(scope, "launch_agent_driver", return_value=17) as launch:
            assert scope.resume_session_result("123", query=query, agent_mode="raw") == 17
    query.assert_called_once_with("123")
    assert launch.call_args.args == (str(tmp_path), "topsailai_agent_plan_tasks", "123")


def test_real_foreground_resume_child_identity_and_status(tmp_path):
    """A real owned child receives both identities and returns its actual status."""
    import json
    import os
    import subprocess
    import sys
    from cli_topsailai import project_scope as scope

    output = tmp_path / "child.json"
    before = os.environ.copy()
    cwd = os.getcwd()
    record = {"session_id": "persisted-real", "project_workspace": str(tmp_path)}

    def spawn(argv, **kwargs):
        """Replace only the external agent executable with a harmless probe."""
        assert argv == ["topsailai_agent_plan_tasks"]
        code = (
            "import os,json,pathlib; "
            f"pathlib.Path({str(output)!r}).write_text(json.dumps("
            "[os.environ['TOPSAILAI_SESSION_ID'],os.environ['SESSION_ID'],os.getcwd()])); "
            "raise SystemExit(17)"
        )
        return subprocess.Popen([sys.executable, "-c", code], **kwargs)

    with patch.object(scope, "_apply_selected_model_environment", return_value=({}, set())):
        assert scope.resume_session_result(
            "persisted-real", agent_mode="raw", spawn=spawn,
            query=lambda sid: [record], home=str(tmp_path),
        ) == 17
    assert json.loads(output.read_text()) == ["persisted-real", "persisted-real", str(tmp_path)]
    assert os.environ == before
    assert os.getcwd() == cwd


def test_background_resume_preserves_identity_and_attempt_log(tmp_path, capsys):
    """The real resume preparation delegates once to the shared background primitive."""
    from cli_topsailai import agent_launch, agent_launch_background as bg
    from cli_topsailai import project_scope as scope

    record = {"session_id": "persisted", "project_workspace": str(tmp_path)}
    with patch.object(agent_launch, "_session_id", side_effect=AssertionError("fresh identity")):
        with patch.object(agent_launch, "_apply_selected_model_environment", return_value=({}, set())):
            with patch.object(bg, "launch_background", return_value={
                "launcher_pid": 12345, "log_path": "attempt.agent-launch.log",
            }) as launch:
                assert scope.resume_session_result(
                    "persisted", background=True, query=lambda sid: [record],
                    home=str(tmp_path), entrypoint_base="/startup",
                ) == 0
    assert launch.call_count == 1
    assert launch.call_args.args == (str(tmp_path), "persisted")
    options = launch.call_args.kwargs
    assert options["driver"] == "topsailai_agent_plan_tasks"
    assert options["entrypoint_base"] == "/startup"
    assert options["log_identity"].startswith("persisted.")
    assert options["environment"]["SESSION_ID"] == "persisted"
    assert options["environment"]["TOPSAILAI_SESSION_ID"] == "persisted"
    assert "launcher_pid=12345" in capsys.readouterr().out


def test_conflicting_values_and_positionals_are_rejected():
    """Session and mode conflicts fail before any authoritative query."""
    for argv in (["positional"], ["-s", "a", "-s", "b"],
                 ["-s", "a", "-m", "raw", "-m", "tmux"]):
        with patch("cli_topsailai.project_scope.resume_session_result") as resume:
            assert run_workspace_resume_cli(argv) == 2
        resume.assert_not_called()


def test_invalid_session_tokens_fail_before_lookup():
    """Identifiers cannot escape task storage through log filename construction."""
    for token in ("", ".", "..", "../outside", "a/b", "a\\b", "nul\0id"):
        with patch("cli_topsailai.project_scope.resume_session_result") as resume:
            assert run_workspace_resume_cli(["-s", token]) == 2
        resume.assert_not_called()


def test_background_driver_is_bounded_before_side_effects():
    """Only built-in executable argv may cross the supervisor request boundary."""
    import pytest
    from cli_topsailai import agent_launch_background as bg

    for driver in ("agent --unsafe", ["agent"], "x" * 10000):
        with patch.object(bg, "get_topsailai_home", side_effect=AssertionError("side effect")):
            with pytest.raises(ValueError, match="invalid background resume driver"):
                bg.launch_background("/not-used", "session", driver=driver)


def test_malformed_lookup_payload_is_a_lookup_failure(tmp_path, capsys):
    """A null entry is untrustworthy, never a silent not-found."""
    import pytest
    from cli_topsailai import project_scope as scope

    with pytest.raises(scope.ResumeLookupError):
        scope.lookup_persisted_session("session-123", query=lambda sid: [None])
    assert scope.resume_session_result(
        "session-123", query=lambda sid: [None], home=str(tmp_path),
    ) == 4
    assert "malformed record" in capsys.readouterr().out


def test_empty_lookup_stdout_is_a_lookup_failure(tmp_path, capsys):
    """Empty stdout cannot be read as an empty (idle) result."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    def _run(cmd, stdout=None, stderr=None, timeout=None, check=False):
        """Simulate a command that exits cleanly but prints nothing."""
        class _Result:
            returncode = 0
        return _Result()

    with patch.object(scope.subprocess, "run", side_effect=_run):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "no JSON payload" in capsys.readouterr().out


def test_oversized_lookup_output_is_a_lookup_failure(tmp_path, capsys):
    """An unbounded payload is rejected instead of silently truncated."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    def _run(cmd, stdout=None, stderr=None, timeout=None, check=False):
        """Write more bytes than the configured capture limit."""
        stdout.write(b"[" + b" " * (scope._LOOKUP_MAX_BYTES + 16) + b"]")

        class _Result:
            returncode = 0
        return _Result()

    with patch.object(scope.subprocess, "run", side_effect=_run):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "exceeded" in capsys.readouterr().out


def test_lookup_timeout_is_a_lookup_failure(tmp_path, capsys):
    """A hung authoritative query fails closed within a bounded duration."""
    import subprocess as sp
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    def _run(cmd, stdout=None, stderr=None, timeout=None, check=False):
        """Simulate the bounded capture expiring."""
        raise sp.TimeoutExpired(cmd, timeout)

    with patch.object(scope.subprocess, "run", side_effect=_run):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "timed out" in capsys.readouterr().out


def test_lookup_failure_diagnostic_reads_both_channels(tmp_path, capsys):
    """The real cause printed on stdout must not be lost."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    def _run(cmd, stdout=None, stderr=None, timeout=None, check=False):
        """Fail with the reason on stdout, as the real query command does."""
        stdout.write(b"Error: database is locked\n")

        class _Result:
            returncode = 1
        return _Result()

    with patch.object(scope.subprocess, "run", side_effect=_run):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "database is locked" in capsys.readouterr().out


def test_workspace_permission_denied_is_rejected(tmp_path, capsys):
    """An unreadable persisted workspace cannot authorize a resume."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    record = {"session_id": "session-123", "project_workspace": str(tmp_path)}
    with patch.object(scope.os, "access", return_value=False):
        assert scope.resume_session_result(
            "session-123", query=lambda sid: [record], home=str(tmp_path),
        ) == 4
    assert "not accessible" in capsys.readouterr().out


def test_workspace_disappearing_before_launch_is_refused(tmp_path, capsys):
    """A workspace that vanishes during preparation fails closed at launch."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    record = {"session_id": "session-123", "project_workspace": str(tmp_path)}
    seen = {"count": 0}

    def _isdir(path):
        """Report the directory present on the first check, absent later."""
        seen["count"] += 1
        return seen["count"] == 1

    def _launch(*args, **kwargs):
        """Honour the late check exactly as the real boundary does."""
        check = kwargs.get("prelaunch_check")
        refusal = check() if check is not None else None
        return refusal if refusal is not None else 0

    with patch.object(scope.os.path, "isdir", side_effect=_isdir):
        with patch.object(scope, "session_liveness", return_value="idle"):
            with patch.object(scope, "launch_agent_driver", side_effect=_launch):
                assert scope.resume_session_result(
                    "session-123", query=lambda sid: [record],
                    agent_mode="raw", home=str(tmp_path),
                ) == 4
    assert "not a directory" in capsys.readouterr().out


def test_lookup_issues_exactly_one_query_and_bounded_candidates(tmp_path):
    """One authoritative query and O(K) candidate inspection, no N+1 scans."""
    from unittest.mock import Mock
    from cli_topsailai import project_scope as scope

    record = {"session_id": "session-123", "project_workspace": str(tmp_path)}
    query = Mock(return_value=[record])
    task = tmp_path / "workspace" / "task"
    task.mkdir(parents=True)
    for pid in range(200, 205):
        (task / f"session-123.{pid}.session.stdout").touch()
    probes = []

    def _pid_state(pid):
        """Record each liveness probe so the inspection count is observable."""
        probes.append(pid)
        return "dead"

    with patch.object(scope, "_pid_state", side_effect=_pid_state):
        with patch.object(scope, "launch_agent_driver", return_value=0):
            assert scope.resume_session_result(
                "session-123", query=query, agent_mode="raw", home=str(tmp_path),
            ) == 0
    query.assert_called_once_with("session-123")
    assert len(probes) == 5
