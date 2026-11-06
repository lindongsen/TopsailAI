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

        parsed = json.loads(ssi._format_sessions_json(sessions, str(tmp_path)))

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0] == si._session_to_dict(sessions[0], str(tmp_path))
        assert parsed[1] == si._session_to_dict(sessions[1], str(tmp_path))

    def test_empty_batch_is_empty_array(self, tmp_path: Path):
        assert json.loads(ssi._format_sessions_json([], str(tmp_path))) == []


class TestFormatSessions:
    @patch("shutil.get_terminal_size", return_value=Mock(columns=80))
    def test_cards_match_single_session_cards(self, _mock_size, tmp_path: Path):
        sessions = [
            SessionData(session_id="s1", task="Task one", session_name="First"),
            SessionData(session_id="s2", task="Task two"),
        ]
        for session in sessions:
            session.create_time = datetime(2026, 7, 5, 10, 30, 15)

        output = ssi._format_sessions(sessions, str(tmp_path), False)

        expected = "\n\n".join(
            si._format_session(session, str(tmp_path), False) for session in sessions
        )
        assert output == expected
        assert output.count("Session Information") == 2


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

    def test_invalid_db_conn_reports_error(self, tmp_path: Path, capsys):
        code = ssi.main(["s1", "--db-conn", "invalid://bad", "--home", str(tmp_path)])
        captured = capsys.readouterr()

        assert code == 1
        assert "[ERROR]" in captured.out

    def test_no_color_sets_environment(self, db_conn: str, tmp_path: Path, capsys):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            assert ssi.main(
                ["s1", "--db-conn", db_conn, "--home", str(tmp_path), "--no-color"]
            ) == 0
            assert os.environ.get("NO_COLOR") == "1"
        capsys.readouterr()

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


if __name__ == "__main__":
    pytest.main([__file__, "--color=no"])
