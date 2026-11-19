"""Pin the ``topsailai runtime info`` contract.

Author: DawsonLin

The command must publish exactly the document that
``topsailai session info --include-runtime --json`` publishes, with one
addition: the answering process can be selected by PID. These tests therefore
assert parity against the reference command instead of a frozen copy of its
fields, and they assert the PID ownership rules that make the addition safe.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

import topsailai_session_info as session_info
from cli_topsailai import runtime_cli as cli
from cli_topsailai import runtime_info as ri
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData

#: A PID that no process owns, used to prove an explicit PID is queried even
#: when the session itself looks idle.
DEAD_PID = 999999


def make_home(tmp_path: Path) -> str:
    """Create an isolated home with the task directory the command scans."""
    (tmp_path / ri.TASK_SUBDIR).mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def write_stdout(home: str, session_id: str, pid: int) -> Path:
    """Create the session stdout file that records a PID's ownership."""
    path = Path(home) / ri.TASK_SUBDIR / f"{session_id}.{pid}.session.stdout"
    path.write_text("", encoding="utf-8")
    return path


def write_task_stdout(home: str, session_id: str, pid: int,
                      task_id: str = "topsailai.1795078235.630223") -> Path:
    """Create the task log a child agent writes instead of a session log."""
    path = (Path(home) / ri.TASK_SUBDIR
            / f"{session_id}.{pid}.{task_id}.task.stdout")
    path.write_text("", encoding="utf-8")
    return path


def manager_for(tmp_path: Path):
    """Return a session manager backed by an isolated SQLite file."""
    return get_session_manager(f"sqlite:///{tmp_path / 'sessions.db'}")


def collected_record(pid: int) -> dict:
    """Return one runtime record shaped like the collector's real output."""
    return {
        "state": "ok",
        "error_code": None,
        "pid": pid,
        "data": {"ok": True, "model": {"name": "example-model"}},
    }


class TestResolveTarget:
    """The PID that answers must be the PID the caller asked about."""

    def test_default_uses_the_proving_pid(self, tmp_path: Path):
        """Without ``-p`` the answer is the PID that proved the session live."""
        home = make_home(tmp_path)

        with patch("cli_topsailai.process_liveness.live_session_pid",
                   return_value=4242) as probe:
            assert ri.resolve_target("s", None, home) == ("s", 4242, False)

        probe.assert_called_once_with("s", home=home)

    def test_idle_session_yields_no_pid(self, tmp_path: Path):
        """An idle session names no process, so nothing may be queried."""
        home = make_home(tmp_path)

        with patch("cli_topsailai.process_liveness.live_session_pid",
                   return_value=None):
            assert ri.resolve_target("s", None, home) == ("s", None, False)

    def test_explicit_pid_for_the_same_session(self, tmp_path: Path):
        """A PID recorded for the requested session is accepted unchanged."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242, False)

    def test_task_agent_pid_is_accepted_and_flagged(self, tmp_path: Path):
        """A child agent writes only a task log, so that file must prove it."""
        home = make_home(tmp_path)
        write_task_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242, True)

    def test_task_agent_pid_is_reachable_without_a_session_id(self, tmp_path: Path):
        """A worker PID alone must derive its session and its kind."""
        home = make_home(tmp_path)
        write_task_stdout(home, "s", 4242)

        assert ri.resolve_target(None, 4242, home) == ("s", 4242, True)

    def test_session_log_wins_when_a_pid_left_both_kinds(self, tmp_path: Path):
        """The session process owns the session log, so it is not a task agent."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)
        write_task_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242, False)

    def test_explicit_pid_without_a_record_is_target_not_found(self, tmp_path: Path):
        """A PID with no stdout record cannot be attributed to any session."""
        home = make_home(tmp_path)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("s", 4242, home)

        assert caught.value.error_code == "target_not_found"
        assert caught.value.exit_code == 3

    def test_explicit_pid_for_another_session_is_target_mismatch(self, tmp_path: Path):
        """Reporting another session's runtime data would be worse than failing."""
        home = make_home(tmp_path)
        write_stdout(home, "other", 4242)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("s", 4242, home)

        assert caught.value.error_code == "target_mismatch"
        assert caught.value.exit_code == 3

    def test_pid_only_derives_the_session_identity(self, tmp_path: Path):
        """A caller who knows only the PID must not have to look the session up."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        assert ri.resolve_target(None, 4242, home) == ("s", 4242, False)

    def test_pid_only_maps_the_temp_prefix_to_the_display_sentinel(self, tmp_path: Path):
        """The storage prefix must never be published as a session identity."""
        home = make_home(tmp_path)
        write_stdout(home, "topsailai", 4242)

        assert ri.resolve_target(None, 4242, home) == ("(temp)", 4242, False)

    def test_unusable_identifier_is_target_mismatch(self, tmp_path: Path):
        """An identifier that cannot name a file must fail instead of matching."""
        home = make_home(tmp_path)
        write_stdout(home, "s", 4242)

        with pytest.raises(ri.RuntimeInfoError) as caught:
            ri.resolve_target("../s", 4242, home)

        assert caught.value.error_code == "target_mismatch"

    def test_unparseable_stdout_files_are_skipped(self, tmp_path: Path):
        """One unusable leftover must not hide the record that does match."""
        home = make_home(tmp_path)
        task_dir = Path(home) / ri.TASK_SUBDIR
        (task_dir / "broken.notapid.session.stdout").write_text("", encoding="utf-8")
        (task_dir / "zero.0.session.stdout").write_text("", encoding="utf-8")
        write_stdout(home, "s", 4242)

        assert ri.resolve_target("s", 4242, home) == ("s", 4242, False)


class TestBuildDocument:
    """The document must be the reference command's document, not a copy."""

    def test_document_matches_session_info_include_runtime(self, tmp_path: Path,
                                                           capsys):
        """Both commands must publish byte-identical documents for one session."""
        home = make_home(tmp_path)
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        manager = get_session_manager(db_conn)
        manager.create_session(SessionData(session_id="parity", task="Task"))
        write_stdout(home, "parity", os.getpid())
        record = collected_record(os.getpid())

        with patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=record):
            assert session_info.main([
                "parity", "--db-conn", db_conn, "--home", home,
                "--include-runtime",
            ]) == 0
            reference = capsys.readouterr().out

            with patch("topsailai.context.ctx_manager.get_session_manager",
                       return_value=manager):
                assert ri.run_info(ri.RuntimeInfoRequest(session_id="parity"),
                                   home=home) == 0
            produced = capsys.readouterr().out

        assert produced == reference
        document = json.loads(produced)
        assert document["runtime"] == record
        assert document["is_running"] is True

    def test_runtime_is_null_without_a_pid(self, tmp_path: Path):
        """An idle session keeps ``runtime: null`` instead of a failure record."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="idle", task="Task"))

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime") as collect:
            document = json.loads(ri.build_document("idle", None, home))

        collect.assert_not_called()
        assert document["runtime"] is None
        assert document["is_running"] is False

    def test_explicit_pid_is_queried_even_when_idle(self, tmp_path: Path):
        """The caller asserted a process, so it is queried despite idle status."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="idle", task="Task"))
        write_stdout(home, "idle", DEAD_PID)
        record = collected_record(DEAD_PID)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=record) as collect:
            document = json.loads(ri.build_document("idle", DEAD_PID, home))

        assert collect.call_args.args == (
            "idle", DEAD_PID, os.path.join(home, ri.TASK_SUBDIR),
        )
        assert document["runtime"] == record
        assert document["is_running"] is False

    def test_default_timeout_is_the_collector_default(self, tmp_path: Path):
        """An omitted ``--timeout`` must not override the collector's budget."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=collected_record(4242)) as collect:
            ri.build_document("s", 4242, home)

        assert "timeout" not in collect.call_args.kwargs

    def test_explicit_timeout_is_forwarded(self, tmp_path: Path):
        """An explicit budget must reach the transport unchanged."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=collected_record(4242)) as collect:
            ri.build_document("s", 4242, home, 0.25)

        assert collect.call_args.kwargs["timeout"] == 0.25

    def test_task_agent_flag_is_forwarded_to_the_collector(self, tmp_path: Path):
        """The runtime record must state which kind of process answered."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager), \
             patch("cli_topsailai.workspace_runtime.collect_session_runtime",
                   return_value=collected_record(4242)) as collect:
            ri.build_document("s", 4242, home, is_task=True)

        assert collect.call_args.kwargs == {"is_task": True}

    def test_missing_session_is_session_not_found(self, tmp_path: Path):
        """A record cannot be produced without a stored session."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            with pytest.raises(ri.RuntimeInfoError) as caught:
                ri.build_document("missing", None, home)

        assert caught.value.error_code == "session_not_found"
        assert caught.value.exit_code == 1


class TestRunInfo:
    """Every path must print one parseable document and no text line."""

    def test_success_prints_one_document(self, tmp_path: Path, capsys):
        """A successful lookup prints the record and exits zero."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)
        manager.create_session(SessionData(session_id="s", task="Task"))

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            assert ri.run_info(ri.RuntimeInfoRequest(session_id="s"), home=home) == 0

        captured = capsys.readouterr()
        assert json.loads(captured.out)["session_id"] == "s"
        assert captured.err == ""

    def test_missing_session_prints_a_parseable_document(self, tmp_path: Path,
                                                         capsys):
        """A machine consumer must receive JSON even when the session is absent."""
        home = make_home(tmp_path)
        manager = manager_for(tmp_path)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   return_value=manager):
            assert ri.run_info(ri.RuntimeInfoRequest(session_id="missing"),
                               home=home) == 1

        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert document["error_code"] == "session_not_found"
        assert document["session_id"] == "missing"
        assert captured.err == ""

    def test_target_failure_uses_its_own_exit_code(self, tmp_path: Path, capsys):
        """A rejected PID exits 3 and names the reason."""
        home = make_home(tmp_path)

        assert ri.run_info(ri.RuntimeInfoRequest(session_id="s", pid=4242),
                           home=home) == 3

        document = json.loads(capsys.readouterr().out)
        assert document["error_code"] == "target_not_found"

    def test_unexpected_error_is_lookup_failed(self, tmp_path: Path, capsys):
        """A storage failure is classified instead of escaping as a traceback."""
        home = make_home(tmp_path)

        with patch("topsailai.context.ctx_manager.get_session_manager",
                   side_effect=RuntimeError("storage unavailable")):
            assert ri.run_info(ri.RuntimeInfoRequest(session_id="s"), home=home) == 1

        document = json.loads(capsys.readouterr().out)
        assert document["error_code"] == "lookup_failed"
        assert "storage unavailable" in document["message"]


class TestCliWiring:
    """The action must be reachable, documented and free of delivery options."""

    def test_info_is_dispatched_before_the_envelope(self):
        """``info`` prints its own document, so it returns before the envelope."""
        executor = Mock(side_effect=AssertionError("no delivery"))
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            code = cli.run_runtime_cli(
                ["info", "-s", "s", "-p", "123", "--timeout", "3"],
                executor=executor, home_resolver=lambda: "/isolated/home",
            )

        assert code == 0
        executor.assert_not_called()
        info.assert_called_once_with(
            ri.RuntimeInfoRequest(session_id="s", pid=123, timeout=3.0),
            home="/isolated/home",
        )

    def test_json_is_a_noop(self):
        """The document is always JSON, so ``--json`` must not change anything."""
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            assert cli.run_runtime_cli(["info", "-s", "s", "--json"],
                                       home_resolver=lambda: "/h") == 0

        assert info.call_args.args[0] == ri.RuntimeInfoRequest(session_id="s")

    @pytest.mark.parametrize("extra", [
        ["-m", "x"], ["-a", "{}"], ["-i", "/send x"], ["--stdin"],
        ["-n", "2"], ["-f"], ["--is-task"], ["extra"],
    ])
    def test_delivery_and_log_options_are_rejected(self, extra, capsys):
        """``info`` accepts only selectors and the transport budget."""
        home, executor, info = Mock(), Mock(), Mock()

        with patch.object(cli, "run_info", info):
            code = cli.run_runtime_cli(["info", "-s", "s", *extra, "--json"],
                                       home_resolver=home, executor=executor)

        assert code == 2
        info.assert_not_called()
        executor.assert_not_called()
        home.assert_not_called()
        assert json.loads(capsys.readouterr().out)["error_code"] == "usage_error"

    def test_pid_only_is_accepted(self):
        """A PID alone is a complete selector for this action."""
        info = Mock(return_value=0)

        with patch.object(cli, "run_info", info):
            assert cli.run_runtime_cli(["info", "-p", "123"],
                                       home_resolver=lambda: "/h") == 0

        assert info.call_args.args[0] == ri.RuntimeInfoRequest(pid=123)

    def test_help_documents_the_action(self, capsys):
        """Help must advertise the action and one example of it."""
        with pytest.raises(SystemExit) as caught:
            cli.run_runtime_cli(["info", "--help"])

        assert caught.value.code == 0
        output = capsys.readouterr().out
        assert "logs, or info" in output
        assert "topsailai runtime info -s SESSION -p PID" in output

    def test_real_entry_point_reports_session_not_found(self, tmp_path: Path):
        """The shipped command emits one JSON document without a real session."""
        root = Path(__file__).resolve().parents[3]
        env = dict(os.environ, TOPSAILAI_HOME=str(tmp_path), HOME=str(tmp_path))
        completed = subprocess.run(
            [sys.executable, str(root / "topsailai_cli.py"), "runtime", "info",
             "-s", "nonexistent-fixture"],
            env=env, capture_output=True, text=True, check=False, timeout=120,
        )

        assert completed.returncode == 1
        assert json.loads(completed.stdout)["error_code"] == "session_not_found"
        assert completed.stderr == ""


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
