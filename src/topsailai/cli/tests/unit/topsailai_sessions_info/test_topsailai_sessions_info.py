"""Unit tests for topsailai_sessions_info.py."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

CLI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.abspath(os.path.join(CLI_ROOT, "..", "src"))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, CLI_ROOT)

import topsailai_session_info as si
import topsailai_sessions_info as ssi
from cli_topsailai.process_liveness import ProcessState
from topsailai.context.ctx_manager import get_session_manager
from topsailai.context.session_manager import SessionData


@pytest.fixture
def db_conn(tmp_path: Path) -> str:
    """Provide an isolated session database with two stored sessions."""
    db_path = tmp_path / "sessions.db"
    conn = f"sqlite:///{db_path}"
    manager = get_session_manager(conn)
    manager.create_session(
        SessionData(session_id="s1", task="Task one", session_name="First", category="agent")
    )
    manager.create_session(SessionData(session_id="s2", task="Task two", session_name="Second"))
    return conn


class TestParseArgs:
    def test_multiple_session_ids(self):
        args = ssi._parse_args(["a", "b", "c"])
        assert args.session_ids == ["a", "b", "c"]
        assert args.db_conn is None
        assert args.home is None
        assert args.no_color is False
        assert args.json is False

    def test_session_ids_required(self):
        with pytest.raises(SystemExit) as error:
            ssi._parse_args([])
        assert error.value.code == 2

    def test_shared_options(self):
        args = ssi._parse_args(
            ["a", "b", "--db-conn", "sqlite:///t.db", "--home", "/tmp/h", "--no-color", "--json"]
        )
        assert args.db_conn == "sqlite:///t.db"
        assert args.home == "/tmp/h"
        assert args.no_color is True
        assert args.json is True


class TestUniqueSessionIds:
    def test_preserves_first_occurrence_order(self):
        assert ssi._unique_session_ids(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]

    def test_strips_whitespace_and_drops_empty(self):
        assert ssi._unique_session_ids([" s1 ", "", "   ", "s2"]) == ["s1", "s2"]


class TestOrderFoundSessions:
    def test_requested_order_and_missing(self):
        sessions = [SessionData(session_id="s2"), SessionData(session_id="s1")]
        found, missing = ssi._order_found_sessions(["s1", "gone", "s2"], sessions)
        assert [session.session_id for session in found] == ["s1", "s2"]
        assert missing == ["gone"]

    def test_all_missing(self):
        found, missing = ssi._order_found_sessions(["a", "b"], [])
        assert found == []
        assert missing == ["a", "b"]


class TestFormatSessionsJson:
    def test_records_match_single_session_records(self, tmp_path: Path):
        sessions = [
            SessionData(session_id="s1", task="Task one", session_name="First"),
            SessionData(session_id="s2", task="Task two"),
        ]
        for session in sessions:
            session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        parsed = json.loads(ssi._format_sessions_json(sessions, str(tmp_path), {}))

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0] == si._session_to_dict(sessions[0], str(tmp_path))
        assert parsed[1] == si._session_to_dict(sessions[1], str(tmp_path))

    def test_injected_running_status_matches_reference_resolution(self, tmp_path: Path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "s1.999999999.session.stdout").write_text("x")
        session = SessionData(session_id="s1", task="Task one")

        running_by_id = ssi._running_status_map(str(tmp_path))
        parsed = json.loads(ssi._format_sessions_json([session], str(tmp_path), running_by_id))

        assert parsed[0] == si._session_to_dict(session, str(tmp_path))
        assert parsed[0]["is_running"] is False
        assert parsed[0]["status"] == "Idle"

    def test_empty_batch_is_empty_array(self, tmp_path: Path):
        assert json.loads(ssi._format_sessions_json([], str(tmp_path), {})) == []


class TestFormatSessions:
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_cards_match_single_session_cards(self, _mock_size, tmp_path: Path):
        sessions = [
            SessionData(session_id="s1", task="Task one", session_name="First"),
            SessionData(session_id="s2", task="Task two"),
        ]
        for session in sessions:
            session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = ssi._format_sessions(sessions, str(tmp_path), False, {})

        expected = "\n\n".join(
            si._format_session(session, str(tmp_path), False) for session in sessions
        )
        assert output == expected
        assert output.count("Session Information") == 2


class _CountingOs:
    """Stand-in for the ``os`` module that counts ``listdir`` calls.

    The consumer module imports the real ``os`` singleton, so patching
    ``ssi.os.listdir`` would mutate process-wide state: any unrelated
    ``os.listdir`` call from pytest internals would inflate the count and make
    the assertion flaky.  This proxy is bound only to the consumer module and
    delegates every other attribute to the real module.
    """

    def __init__(self, listdir_impl):
        self._listdir_impl = listdir_impl
        self.listdir_calls = 0

    def listdir(self, path):
        """Count the call, then delegate to the configured implementation."""
        self.listdir_calls += 1
        return self._listdir_impl(path)

    def __getattr__(self, name):
        """Delegate every other attribute to the real ``os`` module."""
        return getattr(os, name)


class TestRunningStatusMap:
    def test_single_scan_for_many_sessions(self, tmp_path: Path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        for index in range(50):
            (task_dir / f"s{index}.999999999.session.stdout").write_text("x")

        counting_os = _CountingOs(os.listdir)
        with patch.object(ssi, "os", counting_os):
            running_by_id = ssi._running_status_map(str(tmp_path))

        assert counting_os.listdir_calls == 1
        assert len(running_by_id) == 50
        assert all(value is False for value in running_by_id.values())

    def test_every_stdout_file_is_probed(self, tmp_path: Path):
        """A dead candidate must not stop the search for a live one."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        old = task_dir / "s1.111111111.session.stdout"
        new = task_dir / "s1.222222222.session.stdout"
        old.write_text("x")
        new.write_text("x")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))

        with patch.object(ssi, "pid_state", return_value=ProcessState.DEAD) as probe:
            running_by_id = ssi._running_status_map(str(tmp_path))

        assert running_by_id == {"s1": False}
        probed = sorted(call.args[0] for call in probe.call_args_list)
        assert probed == [111111111, 222222222]

    def test_newer_dead_file_does_not_hide_older_live_file(self, tmp_path: Path):
        """A live older candidate keeps the session running."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        old = task_dir / "s1.111111111.session.stdout"
        new = task_dir / "s1.222222222.session.stdout"
        old.write_text("x")
        new.write_text("x")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))

        def probe(pid):
            return ProcessState.ALIVE if pid == 111111111 else ProcessState.DEAD

        with patch.object(ssi, "pid_state", side_effect=probe):
            running_by_id = ssi._running_status_map(str(tmp_path))

        assert running_by_id == {"s1": True}

    def test_missing_directory_is_empty_map(self, tmp_path: Path):
        assert ssi._running_status_map(str(tmp_path)) == {}

    def test_unreadable_directory_is_empty_map(self, tmp_path: Path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        def denied(_path):
            raise OSError("denied")

        with patch.object(ssi, "os", _CountingOs(denied)):
            assert ssi._running_status_map(str(tmp_path)) == {}

    def test_ignores_non_stdout_and_unparsable_entries(self, tmp_path: Path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "notes.txt").write_text("x")
        (task_dir / "s1.notapid.session.stdout").write_text("x")
        (task_dir / "s2.333333333.session.stdout").write_text("x")

        with patch.object(ssi, "pid_state", return_value=ProcessState.DEAD):
            running_by_id = ssi._running_status_map(str(tmp_path))

        assert running_by_id == {"s2": False}


class TestMain:
    def test_multiple_sessions_in_requested_order(self, db_conn: str, tmp_path: Path, capsys):
        code = ssi.main(["s2", "s1", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"])
        captured = capsys.readouterr()

        assert code == 0
        assert captured.err == ""
        assert captured.out.index("s2") < captured.out.index("s1")
        assert "First" in captured.out
        assert "Second" in captured.out

    def test_json_output_is_array_of_single_session_records(
        self, db_conn: str, tmp_path: Path, capsys
    ):
        assert ssi.main(["s1", "s2", "--db-conn", db_conn, "--home", str(tmp_path), "--json"]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert [record["session_id"] for record in parsed] == ["s1", "s2"]
        assert parsed[0]["session_name"] == "First"
        assert parsed[0]["category"] == "agent"
        assert parsed[1]["task"] == "Task two"

    def test_duplicate_identifiers_render_once(self, db_conn: str, tmp_path: Path, capsys):
        assert ssi.main(
            ["s1", "s1", "s1", "--db-conn", db_conn, "--home", str(tmp_path), "--json"]
        ) == 0
        parsed = json.loads(capsys.readouterr().out)
        assert len(parsed) == 1

    def test_missing_session_reports_on_stderr_and_keeps_stdout_parseable(
        self, db_conn: str, tmp_path: Path, capsys
    ):
        code = ssi.main(["s1", "gone", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
        captured = capsys.readouterr()

        assert code == 1
        assert "Session not found: gone" in captured.err
        assert [record["session_id"] for record in json.loads(captured.out)] == ["s1"]

    def test_all_sessions_missing_returns_one(self, db_conn: str, tmp_path: Path, capsys):
        code = ssi.main(["gone", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"])
        captured = capsys.readouterr()

        assert code == 1
        assert captured.out == ""
        assert "Session not found: gone" in captured.err

    def test_all_sessions_missing_json_prints_empty_array(
        self, db_conn: str, tmp_path: Path, capsys
    ):
        code = ssi.main(["gone", "--db-conn", db_conn, "--home", str(tmp_path), "--json"])
        captured = capsys.readouterr()

        assert code == 1
        assert json.loads(captured.out) == []
        assert "Session not found: gone" in captured.err

    def test_invalid_db_conn_reports_error_on_stderr(self, tmp_path: Path, capsys):
        code = ssi.main(["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path)])
        captured = capsys.readouterr()

        assert code == 1
        assert "[ERROR]" in captured.err
        assert captured.out == ""

    def test_invalid_db_conn_keeps_json_stdout_parseable(self, tmp_path: Path, capsys):
        code = ssi.main(
            ["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path), "--json"]
        )
        captured = capsys.readouterr()

        assert code == 1
        assert captured.out == ""
        assert "[ERROR]" in captured.err

    def test_batch_scans_task_directory_once(self, db_conn: str, tmp_path: Path, capsys):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        for index in range(20):
            (task_dir / f"s{index}.999999999.session.stdout").write_text("x")

        counting_os = _CountingOs(os.listdir)
        with patch.object(ssi, "os", counting_os):
            code = ssi.main(
                ["s1", "s2", "--db-conn", db_conn, "--home", str(tmp_path), "--json"]
            )

        captured = capsys.readouterr()
        assert code == 0
        assert counting_os.listdir_calls == 1
        assert [record["session_id"] for record in json.loads(captured.out)] == ["s1", "s2"]

    def test_batch_renders_running_status_from_the_single_scan(
        self, db_conn: str, tmp_path: Path, capsys
    ):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "s1.424242.session.stdout").write_text("x")

        with patch.object(ssi, "pid_state", return_value=ProcessState.ALIVE):
            code = ssi.main(
                ["s1", "s2", "--db-conn", db_conn, "--home", str(tmp_path), "--json"]
            )

        captured = capsys.readouterr()
        records = {record["session_id"]: record for record in json.loads(captured.out)}
        assert code == 0
        assert records["s1"]["is_running"] is True
        assert records["s1"]["status"] == "Running"
        assert records["s2"]["is_running"] is False
        assert records["s2"]["status"] == "Idle"

    def test_no_color_sets_environment(self, db_conn: str, tmp_path: Path, capsys):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            assert ssi.main(
                ["s1", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"]
            ) == 0
            assert os.environ.get("NO_COLOR") == "1"
        capsys.readouterr()

    def test_no_color_strips_ansi_from_stderr_diagnostics(
        self, db_conn: str, tmp_path: Path, capsys
    ):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            code = ssi.main(
                ["gone", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"]
            )
        captured = capsys.readouterr()

        assert code == 1
        assert "\x1b[" not in captured.err
        assert captured.err.strip() == "[INFO] Session not found: gone"

    def test_whitespace_only_identifier_is_rejected(self, db_conn: str, capsys):
        code = ssi.main(["   ", "--db-conn", db_conn])
        captured = capsys.readouterr()

        assert code == 2
        assert captured.out == ""
        assert "[ERROR] No session identifier provided" in captured.err

    def test_home_defaults_to_resolved_topsailai_home(self, db_conn: str, capsys):
        with patch.object(ssi, "get_topsailai_home", return_value="/tmp/resolved-home") as home:
            with patch.object(ssi.session_info, "_format_session", return_value="card") as fmt:
                assert ssi.main(["s1", "--db-conn", db_conn, "--no-color"]) == 0
        home.assert_called_once_with()
        assert fmt.call_args.args[1] == "/tmp/resolved-home"
        capsys.readouterr()


class TestIncludeRuntime:
    """Pin the `--include-runtime` contract of the batch command."""

    def test_flag_defaults_to_false(self):
        """Runtime collection is opt-in, so the default must not query anything."""
        assert ssi._parse_args(["s1"]).include_runtime is False
        assert ssi._parse_args(["s1", "--include-runtime"]).include_runtime is True

    def test_records_carry_runtime_null_when_not_requested(self, db_conn: str, capsys):
        """Every record keeps the key so the array shape never changes."""
        assert ssi.main(["s1", "s2", "--db-conn", db_conn, "--json"]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert [item["runtime"] for item in parsed] == [None, None]

    def test_flag_alone_selects_json(self, db_conn: str, capsys):
        """Runtime data has no card representation, so the flag selects JSON."""
        assert ssi.main(["s1", "--db-conn", db_conn, "--include-runtime"]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert parsed[0]["session_id"] == "s1"
        assert parsed[0]["runtime"] is None

    def test_only_live_sessions_are_queried(self, tmp_path: Path, capsys):
        """An idle session has no process, so it must never be contacted."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        manager = get_session_manager(db_conn)
        manager.create_session(SessionData(session_id="live1", task="Task"))
        manager.create_session(SessionData(session_id="idle1", task="Task"))
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"live1.{os.getpid()}.session.stdout").write_text("")
        collected = {"live1": {"state": "ok", "error_code": None,
                               "pid": os.getpid(), "data": {"ok": True}}}

        with patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   return_value=collected) as collect:
            assert ssi.main([
                "live1", "idle1", "--db-conn", db_conn, "--home", str(tmp_path),
                "--include-runtime",
            ]) == 0
        parsed = json.loads(capsys.readouterr().out)

        rows = collect.call_args.args[0]
        assert [row["session_id"] for row in rows] == ["live1"]
        assert rows[0]["pid"] == os.getpid()
        by_id = {item["session_id"]: item for item in parsed}
        assert by_id["live1"]["runtime"] == collected["live1"]
        assert by_id["idle1"]["runtime"] is None

    def test_status_and_pid_come_from_one_scan(self, tmp_path: Path):
        """Asking for runtime data must not double the directory scan."""
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"live1.{os.getpid()}.session.stdout").write_text("")

        with patch.object(ssi.os, "listdir", wraps=os.listdir) as listdir:
            running, live_pid = ssi._status_and_pid_maps(str(tmp_path))

        assert listdir.call_count == 1
        assert running["live1"] is True
        assert live_pid["live1"] == os.getpid()

    def test_collection_failure_leaves_runtime_null(self, tmp_path: Path, capsys):
        """Runtime data is optional enrichment, so a failure must not raise."""
        db_conn = f"sqlite:///{tmp_path / 'sessions.db'}"
        get_session_manager(db_conn).create_session(
            SessionData(session_id="live1", task="Task")
        )
        task_dir = tmp_path / si.TASK_SUBDIR
        task_dir.mkdir(parents=True)
        (task_dir / f"live1.{os.getpid()}.session.stdout").write_text("")

        with patch("cli_topsailai.workspace_runtime.collect_workspace_runtime",
                   side_effect=RuntimeError("boom")):
            assert ssi.main([
                "live1", "--db-conn", db_conn, "--home", str(tmp_path),
                "--include-runtime",
            ]) == 0
        parsed = json.loads(capsys.readouterr().out)

        assert parsed[0]["runtime"] is None

    def test_text_mode_is_unchanged(self, db_conn: str, capsys):
        """Without the flag the table is printed exactly as before."""
        assert ssi.main(["s1", "--db-conn", db_conn, "--no-color"]) == 0
        text = capsys.readouterr().out

        assert "s1" in text
        assert "runtime" not in text



if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
