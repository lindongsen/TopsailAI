"""Tests for the non-interactive workspace resume command."""

from unittest.mock import patch

import pytest

from cli_topsailai import process_liveness
from cli_topsailai.process_liveness import ProcessState
from cli_topsailai.workspace_resume_cli import build_parser, run_workspace_resume_cli


def test_parser_requires_exact_session_id():
    """The parser exposes the exact persisted session identity through the required session option."""
    args = build_parser().parse_args(["-s", "session-123", "-m", "raw", "-b"])
    assert args.session_id == "session-123"
    assert args.agent_mode == "raw"
    assert args.background is True


@pytest.mark.parametrize("mechanism", ["raw", "tmux", "dtach"])
def test_background_forwards_each_selected_mechanism(mechanism):
    """Background resume delegates every supported mechanism unchanged."""
    with patch(
        "cli_topsailai.project_scope.resume_session_result", return_value=0,
    ) as resume:
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-m", mechanism, "-b"]) == 0
    resume.assert_called_once_with(
        "session-123", agent_mode=mechanism, background=True,
    )


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


def test_core_resume_rejects_conflicting_drivers_with_global_options():
    """Global options must not bypass conflicting resume-driver validation."""
    import pytest
    from cli_topsailai import core

    with patch.object(core.main, "startup_cwd", None, create=True), patch(
        "cli_topsailai.project_scope.resume_session_result"
    ) as resume:
        with pytest.raises(SystemExit) as error:
            core.main([
                "-n", "20", "workspace", "resume", "-s", "session-123",
                "-d", "topsailai_agent_chats",
                "-d", "topsailai_agent_plan_tasks",
            ])
    assert error.value.code == 2
    resume.assert_not_called()


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
        output.assert_called_once_with(include_completed=False, session_ids=None)
    with patch.object(core, "_print_workspace_table") as output:
        assert core._handle_workspace_subcommand(Namespace()) == 0
        output.assert_called_once_with(include_completed=False, session_ids=None)


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

    for extra in ("--pid", "--yes", "--driver", "--agent-m", "extra"):
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
    with patch.object(
        process_liveness, "pid_state",
        side_effect=lambda pid: ProcessState.ALIVE if pid == 101 else ProcessState.DEAD,
    ):
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
    assert launch.call_args.args == (str(tmp_path), "topsailai_agent_chats", "123")


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
        assert argv == ["topsailai_agent_chats"]
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
    assert options["driver"] == "topsailai_agent_chats"
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


def _writer_command(code):
    """Return a real interpreter argv that runs *code* as the lookup child."""
    import sys

    return [sys.executable, "-c", code]


def _pid_alive(pid):
    """Return True while *pid* still exists."""
    import os

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _read_pid(path):
    """Read a PID recorded by a writer child."""
    import pathlib

    return int(pathlib.Path(path).read_text().strip())


def test_empty_lookup_stdout_is_a_lookup_failure(tmp_path, capsys):
    """Empty stdout cannot be read as an empty (idle) result."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    with patch.object(scope, "_lookup_command", return_value=_writer_command("pass")):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "no JSON payload" in capsys.readouterr().out


def test_oversized_lookup_output_is_a_lookup_failure(tmp_path, capsys):
    """A writer far beyond the limit is stopped while it is still writing."""
    import pytest
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    pidfile = tmp_path / "writer.pid"
    progress = tmp_path / "writer.progress"
    target = 8 * 1024 * 1024
    code = (
        "import os, sys\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "written = 0\n"
        "chunk = ' ' * 65536\n"
        "sys.stdout.write('[')\n"
        "sys.stdout.flush()\n"
        "written = 1\n"
        "while written < %d:\n"
        "    sys.stdout.write(chunk)\n"
        "    sys.stdout.flush()\n"
        "    written += len(chunk)\n"
        f"    tmp = {str(progress)!r} + '.tmp'\n"
        "    open(tmp, 'w').write(str(written))\n"
        f"    os.replace(tmp, {str(progress)!r})\n"
        "sys.stdout.write(']')\n" % target
    )
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        with pytest.raises(scope.ResumeLookupError) as error:
            scope._query_session_records("session-123")
    message = str(error.value)
    assert "exceeded" in message
    # The retained capture must stay inside the declared budget.
    assert "captured " in message, message
    captured = int(message.split("captured ")[1].split(" bytes")[0])
    assert captured <= scope._LOOKUP_MAX_BYTES
    # The writer must have been stopped in flight, not after finishing. The
    # progress record is replaced atomically, so a missing record means the
    # writer was stopped before it completed even one chunk.
    written = int(progress.read_text()) if progress.exists() else 0
    assert written < target, f"writer completed {written} bytes before being stopped"
    assert written <= scope._LOOKUP_MAX_BYTES + scope._LOOKUP_CAPTURE_MARGIN
    writer_pid = _read_pid(pidfile)
    assert not _pid_alive(writer_pid), f"writer {writer_pid} survived overflow"
    # The public boundary reports the same failure as a lookup error.
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "exceeded" in capsys.readouterr().out


def test_lookup_output_exactly_at_limit_is_accepted(tmp_path):
    """A payload of exactly the limit is a boundary, not an off-by-one reject."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    limit = scope._LOOKUP_MAX_BYTES
    code = f"import sys\nsys.stdout.write('[' + ' ' * {limit - 2} + ']')\n"
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        assert scope._query_session_records("session-123") == []


def test_lookup_output_one_byte_over_limit_is_rejected(tmp_path):
    """One byte beyond the limit is an overflow, not a silent truncation."""
    import pytest
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    limit = scope._LOOKUP_MAX_BYTES
    code = f"import sys\nsys.stdout.write('[' + ' ' * {limit - 1} + ']')\n"
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        with pytest.raises(scope.ResumeLookupError, match="exceeded"):
            scope._query_session_records("session-123")


def test_lookup_timeout_is_a_lookup_failure(tmp_path, capsys):
    """A hung authoritative query fails closed and its process is reaped."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    pidfile = tmp_path / "hung.pid"
    code = (
        "import os, sys, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        with patch.object(scope, "_LOOKUP_TIMEOUT_SECONDS", 0.5):
            assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "timed out" in capsys.readouterr().out
    hung_pid = _read_pid(pidfile)
    assert not _pid_alive(hung_pid), f"hung query {hung_pid} survived timeout"


def test_lookup_failure_diagnostic_reads_both_channels(tmp_path, capsys):
    """The real cause printed on stdout must not be lost."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    code = (
        "import sys\n"
        "sys.stdout.write('Error: database is locked\\n')\n"
        "sys.exit(1)\n"
    )
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 4
    assert "database is locked" in capsys.readouterr().out


def test_empty_lookup_list_is_not_found(tmp_path, capsys):
    """A genuine empty list is a not-found result, not a lookup failure."""
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    code = "import sys\nsys.stdout.write('[]')\n"
    with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
        assert scope.resume_session_result("session-123", home=str(tmp_path)) == 3
    assert "no persisted session matches" in capsys.readouterr().out


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
        return ProcessState.DEAD

    with patch.object(process_liveness, "pid_state", side_effect=_pid_state):
        with patch.object(scope, "launch_agent_driver", return_value=0):
            assert scope.resume_session_result(
                "session-123", query=query, agent_mode="raw", home=str(tmp_path),
            ) == 0
    query.assert_called_once_with("session-123")
    assert len(probes) == 5


def _wait_for_file(path, timeout=10.0):
    """Wait until *path* exists and is non-empty, returning its text."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = path.read_text().strip()
        except OSError:
            text = ""
        if text:
            return text
        time.sleep(0.01)
    raise AssertionError(f"{path} was not written within {timeout}s")


def _kill_exact(pid):
    """Kill one exact PID and log the action; never signal by name."""
    import os
    import signal

    try:
        os.kill(pid, signal.SIGKILL)
        print(f"[KILLED] exact pid {pid}")
    except ProcessLookupError:
        pass


def test_lookup_interrupt_terminates_and_reaps_the_query(tmp_path):
    """An interrupted lookup must not hang and must not leave the query alive.

    The lookup runs in a child process so SIGINT is delivered to that child
    only, never to the test runner. The interruption must propagate out of the
    lookup and the owned query must be terminated and reaped.
    """
    import os
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    pidfile = tmp_path / "interrupt.pid"
    query_code = (
        "import os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    wrapper = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from unittest.mock import patch\n"
        "from cli_topsailai import project_scope as scope\n"
        f"with patch.object(scope, '_lookup_command', return_value={[sys.executable, '-c', query_code]!r}):\n"
        "    scope._query_session_records('session-123')\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", wrapper],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    query_pid = None
    query_alive_after = None
    started = time.monotonic()
    try:
        query_pid = int(_wait_for_file(pidfile))
        os.kill(process.pid, signal.SIGINT)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError("the interrupted lookup did not return within 10s")
        elapsed = time.monotonic() - started
        # Observe the query state BEFORE any fallback cleanup, so the death
        # assertion below cannot be satisfied by the test's own kill.
        query_alive_after = _pid_alive(query_pid)
    finally:
        if query_pid is not None and _pid_alive(query_pid):
            _kill_exact(query_pid)
        if process.poll() is None:
            _kill_exact(process.pid)
            process.communicate()
    # The interruption must propagate: the caller dies from SIGINT.
    assert process.returncode == -signal.SIGINT, (
        f"interrupt status was {process.returncode}"
    )
    assert elapsed < 10, f"interrupted lookup took {elapsed:.2f}s"
    assert query_alive_after is False, (
        f"query {query_pid} survived the interruption"
    )


def test_lookup_interrupt_returns_130_through_the_public_boundary(tmp_path):
    """A real CLI process interrupted mid-lookup exits 130 and reaps the query.

    SIGINT is delivered to the CLI process only, which is the production
    interruption path: the owned query must be terminated and reaped, and the
    documented interrupt status must still be produced by the caller. A shell
    reports a SIGINT-terminated process as status 130, so both the signal death
    and an explicit 130 exit are accepted.
    """
    import os
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pidfile = tmp_path / "boundary.pid"
    stub = bin_dir / "topsailai_list_sessions"
    stub.write_text(
        "#!" + sys.executable + "\n"
        "import os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    stub.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["TOPSAILAI_HOME"] = str(tmp_path / "home")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        [
            sys.executable, str(root / "topsailai_cli.py"), "workspace", "resume",
            "-s", "session-123", "-m", "raw",
        ],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    query_pid = None
    query_alive_after = None
    started = time.monotonic()
    try:
        query_pid = int(_wait_for_file(pidfile))
        os.kill(process.pid, signal.SIGINT)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError("the interrupted CLI did not return within 10s")
        elapsed = time.monotonic() - started
        # Observe the query state BEFORE any fallback cleanup, so the death
        # assertion below cannot be satisfied by the test's own kill.
        query_alive_after = _pid_alive(query_pid)
    finally:
        if query_pid is not None and _pid_alive(query_pid):
            _kill_exact(query_pid)
        if process.poll() is None:
            _kill_exact(process.pid)
            process.communicate()
    # A shell reports SIGINT death as 130; an explicit 130 exit is equivalent.
    assert process.returncode in (-signal.SIGINT, 130), (
        f"interrupt status was {process.returncode}"
    )
    assert elapsed < 10, f"interrupted resume took {elapsed:.2f}s"
    assert query_alive_after is False, (
        f"query {query_pid} survived the interruption"
    )


def test_lookup_drain_is_bounded_when_a_descendant_holds_the_pipe(tmp_path, capsys):
    """A descendant inheriting the pipe must not block cleanup.

    The query exits after spawning a child that keeps the write end open, so
    EOF never arrives. Cleanup must still return within the bounded drain
    window, report a lookup failure, and reap the owned query.
    """
    import json
    import time
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    record = tmp_path / "inherited.json"
    code = (
        "import json, os, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'])\n"
        f"open({str(record)!r}, 'w').write(json.dumps("
        "{'query': os.getpid(), 'desc': child.pid}))\n"
        "sys.stdout.write('[]')\n"
        "sys.stdout.flush()\n"
    )
    started = time.monotonic()
    try:
        with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
            with patch.object(scope, "_LOOKUP_DRAIN_SECONDS", 0.2):
                with patch.object(scope, "_LOOKUP_TIMEOUT_SECONDS", 5.0):
                    status = scope.resume_session_result(
                        "session-123", home=str(tmp_path),
                    )
        elapsed = time.monotonic() - started
        data = json.loads(record.read_text())
    finally:
        if record.exists():
            data = json.loads(record.read_text())
            if _pid_alive(data["desc"]):
                _kill_exact(data["desc"])
    assert status == 4, f"drain failure status was {status}"
    assert elapsed < 5, f"bounded drain took {elapsed:.2f}s"
    assert "could not be drained" in capsys.readouterr().out
    assert not _pid_alive(data["query"]), (
        f"query {data['query']} was not reaped"
    )


def test_lookup_pipe_setup_failure_still_reaps_the_query(tmp_path):
    """A failure after spawn must still terminate and reap the owned query."""
    import os
    import time
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    pidfile = tmp_path / "setup.pid"
    code = (
        "import os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    query_pid = {"pid": None}
    query_alive_after = {"alive": None}

    def _fail_after_spawn(channels, timeout):
        """Fail once the child is running, after the spawn has succeeded."""
        query_pid["pid"] = int(_wait_for_file(pidfile))
        raise RuntimeError("simulated post-spawn failure")

    try:
        with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
            with patch.object(scope, "_pump_channels", side_effect=_fail_after_spawn):
                try:
                    scope._query_session_records("session-123")
                except RuntimeError:
                    failed = True
                else:
                    failed = False
        # Observe the query state BEFORE any fallback cleanup, so the death
        # assertion below cannot be satisfied by the test's own kill.
        query_alive_after["alive"] = _pid_alive(query_pid["pid"])
    finally:
        if query_pid["pid"] is not None and _pid_alive(query_pid["pid"]):
            _kill_exact(query_pid["pid"])
    assert failed, "the post-spawn failure must propagate"
    assert query_pid["pid"] is not None
    assert query_alive_after["alive"] is False, (
        f"query {query_pid['pid']} survived a post-spawn failure"
    )


def test_lookup_interrupt_after_spawn_still_reaps_the_query(tmp_path):
    """A KeyboardInterrupt after the spawn must still reap the owned query.

    Cleanup responsibility is established before the spawn, so an interruption
    raised by the first fallible step after the child exists must terminate and
    reap that child and still propagate to the caller. The interruption is
    injected through the module's clock, which is the first statement the
    implementation runs after the spawn returns.
    """
    import time
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    pidfile = tmp_path / "spawn-interrupt.pid"
    code = (
        "import os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    query_pid = {"pid": None}
    query_alive_after = {"alive": None}
    real_monotonic = time.monotonic

    class _InterruptingClock:
        """Interrupt once the spawned child is observable."""

        def monotonic(self):
            """Wait for the child, then raise KeyboardInterrupt."""
            if query_pid["pid"] is None:
                query_pid["pid"] = int(_wait_for_file(pidfile))
                raise KeyboardInterrupt
            return real_monotonic()

    try:
        with patch.object(scope, "_lookup_command", return_value=_writer_command(code)):
            with patch.object(scope, "time", _InterruptingClock()):
                try:
                    scope._query_session_records("session-123")
                except KeyboardInterrupt:
                    interrupted = True
                else:
                    interrupted = False
        # Observe the query state BEFORE any fallback cleanup, so the death
        # assertion below cannot be satisfied by the test's own kill.
        query_alive_after["alive"] = _pid_alive(query_pid["pid"])
    finally:
        if query_pid["pid"] is not None and _pid_alive(query_pid["pid"]):
            _kill_exact(query_pid["pid"])
    assert interrupted, "the interruption must propagate"
    assert query_pid["pid"] is not None
    assert query_alive_after["alive"] is False, (
        f"query {query_pid['pid']} survived an interruption after spawn"
    )


def test_lookup_pipe_setup_failure_closes_every_created_descriptor(tmp_path):
    """A non-blocking setup failure must not leak the pipe descriptors.

    ``os.set_blocking`` runs after the descriptors exist, so a failure there
    (or an interruption during setup) must still close every descriptor that
    was created. The descriptors are tracked and probed with ``os.fstat`` so a
    closed descriptor cannot be mistaken for a live one.
    """
    import os
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    class _OsShim:
        """Delegate to the real os module, overriding pipe setup only."""

        def __init__(self, fail_on_call, interrupt):
            self.created = []
            self.calls = 0
            self._fail_on_call = fail_on_call
            self._interrupt = interrupt

        def pipe(self):
            """Create a real pipe and record both descriptors."""
            pair = os.pipe()
            self.created.extend(pair)
            return pair

        def set_blocking(self, fd, blocking):
            """Fail or interrupt on the configured setup call."""
            self.calls += 1
            if self._interrupt and self.calls == 1:
                raise KeyboardInterrupt
            if self.calls == self._fail_on_call:
                raise OSError(9, "simulated set_blocking failure")
            return os.set_blocking(fd, blocking)

        def __getattr__(self, name):
            """Delegate every other attribute to the real os module."""
            return getattr(os, name)

    def _is_open(fd):
        """Return True while *fd* still refers to an open descriptor."""
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    cases = (
        ("first read end", 1, False),
        ("second read end", 2, False),
        ("interruption during setup", 0, True),
    )
    for label, fail_on_call, interrupt in cases:
        shim = _OsShim(fail_on_call, interrupt)
        with patch.object(scope, "os", shim):
            try:
                scope._query_session_records("session-123")
            except (OSError, KeyboardInterrupt, scope.ResumeLookupError):
                pass
            else:
                raise AssertionError(f"{label}: the setup failure did not propagate")
        assert shim.created, f"{label}: no descriptors were created"
        leaked = [fd for fd in shim.created if _is_open(fd)]
        for fd in leaked:
            os.close(fd)
        assert not leaked, f"{label}: leaked descriptors {leaked}"

def test_lookup_channel_construction_failure_closes_every_descriptor():
    """Channel construction failures must close all four owned descriptors."""
    import os
    from unittest.mock import patch
    from cli_topsailai import project_scope as scope

    real_open = scope._open_lookup_pipes
    real_channel = scope._LookupChannel

    def _is_open(fd):
        """Return True while *fd* still refers to an open descriptor."""
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    cases = (
        ("first channel interruption", 1, KeyboardInterrupt),
        ("second channel interruption", 2, KeyboardInterrupt),
        ("first channel exception", 1, RuntimeError),
        ("second channel exception", 2, MemoryError),
    )
    for label, fail_on_call, exception_type in cases:
        created = []
        calls = {"count": 0}

        def _tracking_open():
            """Create real pipes and retain their descriptor identities."""
            descriptors = real_open()
            created.extend(descriptors)
            return descriptors

        def _failing_channel(fd, limit):
            """Fail on the selected channel-construction call."""
            calls["count"] += 1
            if calls["count"] == fail_on_call:
                raise exception_type(f"simulated {label}")
            return real_channel(fd, limit)

        try:
            with patch.object(scope, "_open_lookup_pipes", _tracking_open):
                with patch.object(scope, "_LookupChannel", _failing_channel):
                    try:
                        scope._query_session_records("session-123")
                    except exception_type:
                        failed = True
                    else:
                        failed = False
            leaked = [fd for fd in created if _is_open(fd)]
        finally:
            for fd in created:
                if _is_open(fd):
                    os.close(fd)
        assert failed, f"{label}: construction failure did not propagate"
        assert created, f"{label}: no descriptors were created"
        assert not leaked, f"{label}: leaked descriptors {leaked}"


def test_json_resume_foreground_receipt_uses_stdout_only_for_json(capsys):
    """Foreground JSON mode reports established launcher facts in one document."""
    import json

    def resume(session_id, **kwargs):
        kwargs["receipt"].update(
            session_id=session_id, workspace="/work/project", mode="raw",
            background=False, resumed=True, launcher_pid=4321,
            startup_confirmed=False, child_exit_code=0,
            launcher_exit_observed=True,
        )
        print("resume output", file=kwargs["child_stdout"])
        return 0

    with patch("cli_topsailai.project_scope.resume_session_result", side_effect=resume):
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-m", "raw", "--json"]
        ) == 0
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["action"] == "resume"
    assert payload["session_id"] == "session-123"
    assert payload["pid"] == 4321
    assert payload["delivery_state"] == "launcher_exited"
    assert payload["response"] == {
        "workspace": "/work/project", "mode": "raw", "driver": None,
        "background": False, "resumed": True, "launcher_pid": 4321,
        "log_path": None, "startup_confirmed": False,
        "child_exit_code": 0,
    }
    assert captured.err == "resume output\n"


def test_json_resume_background_receipt_does_not_claim_readiness(capsys):
    """Background success means submission and explicitly not readiness."""
    import json

    def resume(session_id, **kwargs):
        kwargs["receipt"].update(
            session_id=session_id, workspace="/work/project", mode="raw",
            background=True, resumed=True, launcher_pid=5432,
            log_path="/home/task/attempt.agent-launch.log",
            startup_confirmed=False, submission_confirmed=True,
        )
        return 0

    with patch("cli_topsailai.project_scope.resume_session_result", side_effect=resume):
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-b", "--json"]
        ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_state"] == "submitted"
    assert "driver" in payload["response"]
    assert payload["response"]["startup_confirmed"] is False
    assert "not confirmed" in payload["message"]


@pytest.mark.parametrize("code, error_code", [
    (3, "session_not_found"),
    (4, "resume_refused"),
    (5, "spawn_failed"),
    (6, "custody_unresolved"),
    (130, "cancelled"),
    (17, "child_exit_status"),
])
def test_json_resume_failure_receipt_preserves_status(code, error_code, capsys):
    """Resume failures retain their public status and uncertainty semantics."""
    import json

    def resume(session_id, **kwargs):
        kwargs["receipt"].update(
            session_id=session_id, workspace="/work/project", mode="raw",
            background=False, resumed=True,
        )
        return code

    with patch("cli_topsailai.project_scope.resume_session_result", side_effect=resume):
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-m", "raw", "--json"]
        ) == code
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["exit_code"] == code
    assert payload["error_code"] == error_code
    expected_state = "delivery_unknown" if code == 6 else "not_delivered"
    assert payload["delivery_state"] == expected_state
    assert payload["delivery_unknown"] is (code == 6)


def test_json_resume_pid_without_observed_exit_is_uncertain(capsys):
    """Resume does not infer launcher exit from a recorded PID alone."""
    import json

    def resume(session_id, **kwargs):
        kwargs["receipt"].update(
            session_id=session_id, workspace="/work/project", mode="raw",
            background=False, launcher_pid=4321, spawn_confirmed=True,
            effect_uncertain=True,
        )
        return 6

    with patch("cli_topsailai.project_scope.resume_session_result", side_effect=resume):
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-m", "raw", "--json"]
        ) == 6
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_state"] == "delivery_unknown"
    assert payload["delivery_unknown"] is True
    assert "retry blindly" in payload["message"]


def test_json_resume_usage_failure_is_one_receipt(capsys):
    """A malformed JSON request fails before lookup and remains parseable."""
    import json

    with patch("cli_topsailai.project_scope.resume_session_result") as resume:
        assert run_workspace_resume_cli(["--json"]) == 2
    resume.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "resume"
    assert payload["error_code"] == "usage_error"
    assert payload["delivery_state"] == "not_delivered"


def test_plain_resume_delegation_remains_unchanged():
    """Omitting --json preserves the historical call boundary."""
    with patch(
        "cli_topsailai.project_scope.resume_session_result", return_value=17,
    ) as resume:
        assert run_workspace_resume_cli(
            ["-s", "session-123", "-m", "raw"]
        ) == 17
    resume.assert_called_once_with(
        "session-123", agent_mode="raw", background=False,
    )
