"""Unit tests for the non-interactive ``topsailai session`` subcommand.

Every child CLI script is replaced by a spy or by an isolated temporary home,
so no real session record, database, or process is touched.

Author: DawsonLin
"""

from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import pytest

from cli_topsailai import session_cli as cli
from cli_topsailai.process_liveness import ProcessState


def _make_target(tmp_path, session_id="20261107021807", pid=12345):
    """Create one session stdout file inside an isolated task directory."""
    task_dir = tmp_path / "workspace" / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / f"{session_id}.{pid}.session.stdout"
    path.write_text("stale output\n", encoding="utf-8")
    return path


def _delete(tmp_path, session_id="20261107021807", pid=12345, extra=()):
    """Run the delete action against an isolated home with injected probes."""
    return cli.run_session_cli(
        ["delete", session_id, str(pid), "--home", str(tmp_path), *extra]
    )


class TestParser:
    """The parser must expose exactly the documented actions."""

    def test_all_actions_registered(self):
        assert set(cli._HANDLERS) == {
            "info", "list", "status", "history", "search", "add-msg", "delete",
        }

    def test_parser_accepts_every_action(self):
        parser = cli.build_parser()
        for action in cli._HANDLERS:
            assert action in parser.format_help()

    def test_info_accepts_one_or_many_ids(self):
        parser = cli.build_parser()
        assert parser.parse_args(["info", "a"]).session_ids == ["a"]
        assert parser.parse_args(["info", "a", "b"]).session_ids == ["a", "b"]

    def test_delete_parses_pid_as_integer(self):
        args = cli.build_parser().parse_args(["delete", "abc", "12345"])
        assert args.session_id == "abc"
        assert args.pid == 12345

    def test_delete_rejects_non_integer_pid(self):
        with pytest.raises(cli.SessionUsageError):
            cli.build_parser().parse_args(["delete", "abc", "not-a-pid"])

    def test_add_msg_requires_message(self):
        with pytest.raises(cli.SessionUsageError):
            cli.build_parser().parse_args(["add-msg", "abc"])

    def test_duplicate_option_is_rejected(self):
        """A conflicting repeated option is a usage error, not a crash."""
        assert cli.run_session_cli(["list", "--limit", "1", "--limit", "2"]) == 2

    def test_identical_repeated_option_is_accepted(self):
        """Repeating the same value is harmless and must stay accepted."""
        with patch.object(cli, "_run_script", return_value=0) as run:
            assert cli.run_session_cli(["list", "--limit", "1", "--limit", "1"]) == 0
        assert run.call_args.args[1] == ["--limit", "1"]


class TestDispatch:
    """Dispatch must keep the documented exit-code contract."""

    def test_bare_invocation_prints_help_and_succeeds(self, capsys):
        assert cli.run_session_cli([]) == 0
        assert "delete" in capsys.readouterr().out

    def test_help_flag_succeeds(self, capsys):
        assert cli.run_session_cli(["--help"]) == 0
        assert "ACTION" in capsys.readouterr().out

    def test_unknown_action_exits_two(self, capsys):
        assert cli.run_session_cli(["bogus"]) == 2
        assert "usage_error" in capsys.readouterr().err

    def test_missing_pid_exits_two(self, capsys):
        assert cli.run_session_cli(["delete", "abc"]) == 2
        assert "usage_error" in capsys.readouterr().err

    def test_negative_pid_exits_two(self, capsys):
        assert cli.run_session_cli(["delete", "abc", "-5"]) == 2
        assert "usage_error" in capsys.readouterr().err

    def test_zero_pid_exits_two(self, capsys):
        assert cli.run_session_cli(["delete", "abc", "0"]) == 2
        assert "usage_error" in capsys.readouterr().err

    def test_empty_message_exits_two(self, capsys):
        assert cli.run_session_cli(["add-msg", "abc", "-m", "   "]) == 2
        assert "usage_error" in capsys.readouterr().err


class TestIdentityHelpers:
    """Display and on-disk identities differ for temporary sessions."""

    def test_temp_sentinel_maps_to_file_prefix(self):
        assert cli._on_disk_session_id("(temp)") == "topsailai"

    def test_real_session_id_is_unchanged(self):
        assert cli._on_disk_session_id("20261107021807") == "20261107021807"

    @pytest.mark.parametrize("pid", [1, 2147483647])
    def test_valid_pid_accepts_positive_range(self, pid):
        assert cli._valid_pid(pid) is True

    @pytest.mark.parametrize("pid", [0, -1, 2147483648, True, False, "1", None, 1.0])
    def test_valid_pid_rejects_everything_else(self, pid):
        assert cli._valid_pid(pid) is False


class TestDeleteSafety:
    """A stdout may be deleted only when it is provably invalid."""

    def test_live_owner_is_refused(self, tmp_path, capsys):
        path = _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.ALIVE), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path) == cli._TARGET_INVALID
        assert path.exists()
        assert "still alive" in capsys.readouterr().err

    def test_unknown_owner_fails_closed(self, tmp_path, capsys):
        path = _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.UNKNOWN), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path) == cli._TARGET_INVALID
        assert path.exists()
        assert "Cannot prove" in capsys.readouterr().err

    def test_open_file_is_refused(self, tmp_path, capsys):
        path = _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=True):
            assert _delete(tmp_path) == cli._TARGET_INVALID
        assert path.exists()
        assert "holds the file open" in capsys.readouterr().err

    def test_missing_file_is_refused(self, tmp_path, capsys):
        (tmp_path / "workspace" / "task").mkdir(parents=True)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path) == cli._TARGET_INVALID
        assert "No such session stdout" in capsys.readouterr().err

    def test_other_pid_of_same_session_is_untouched(self, tmp_path):
        """Precision: only the exact session ID and PID pair is a target."""
        keep = _make_target(tmp_path, pid=999)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path, pid=12345) == cli._TARGET_INVALID
        assert keep.exists()

    def test_other_session_of_same_pid_is_untouched(self, tmp_path):
        """Precision: the session ID is part of the identity, not just the PID."""
        keep = _make_target(tmp_path, session_id="20260101000000", pid=12345)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path, session_id="20261107021807") == cli._TARGET_INVALID
        assert keep.exists()


class TestDeleteExecution:
    """A proven-invalid stdout is removed and the removal is logged."""

    def test_dead_owner_is_deleted_and_logged(self, tmp_path, capsys):
        path = _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
             patch("cli_topsailai.session_cleanup.find_related_files",
                   return_value=[]):
            assert _delete(tmp_path) == 0
        assert not path.exists()
        assert "Deleted invalid session stdout" in capsys.readouterr().out

    def test_temp_sentinel_deletes_prefixed_file(self, tmp_path):
        path = _make_target(tmp_path, session_id="topsailai", pid=777)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
             patch("cli_topsailai.session_cleanup.find_related_files",
                   return_value=[]):
            assert _delete(tmp_path, session_id="(temp)", pid=777) == 0
        assert not path.exists()

    def test_remaining_related_files_are_reported_not_deleted(self, tmp_path, capsys):
        _make_target(tmp_path)
        leftover = [str(tmp_path / "workspace" / "task" / "x.session.stderr")]
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
             patch("cli_topsailai.session_cleanup.find_related_files",
                   return_value=leftover):
            assert _delete(tmp_path) == 0
        assert "1 related file(s) remain" in capsys.readouterr().out

    def test_json_success_keeps_stdout_parseable(self, tmp_path, capsys):
        _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
             patch("cli_topsailai.session_cleanup.find_related_files",
                   return_value=[]):
            assert _delete(tmp_path, extra=("--json",)) == 0
        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert document["ok"] is True
        assert document["action"] == "delete"
        assert document["pid"] == 12345
        assert document["error_code"] is None
        assert "Deleted invalid session stdout" in captured.err

    def test_json_refusal_reports_error_code(self, tmp_path, capsys):
        _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.ALIVE), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False):
            assert _delete(tmp_path, extra=("--json",)) == cli._TARGET_INVALID
        document = json.loads(capsys.readouterr().out)
        assert document["ok"] is False
        assert document["error_code"] == "target_alive"
        assert document["exit_code"] == cli._TARGET_INVALID

    def test_removal_failure_exits_four(self, tmp_path, capsys):
        _make_target(tmp_path)
        with patch("cli_topsailai.process_liveness.pid_state",
                   return_value=ProcessState.DEAD), \
             patch("cli_topsailai.log_files.is_file_in_use", return_value=False), \
             patch("cli_topsailai.session_cli.os.remove",
                   side_effect=OSError("permission denied")):
            assert _delete(tmp_path) == cli._DELETE_FAILED
        assert "permission denied" in capsys.readouterr().err


class TestInfoDispatch:
    """One identifier uses the single-session script; many use the batch one."""

    def test_single_id_uses_session_info(self):
        with patch("topsailai_session_info.main", return_value=0) as single, \
             patch("topsailai_sessions_info.main", return_value=0) as batch:
            assert cli.run_session_cli(["info", "abc"]) == 0
        single.assert_called_once_with(["abc"])
        batch.assert_not_called()

    def test_many_ids_use_sessions_info(self):
        with patch("topsailai_session_info.main", return_value=0) as single, \
             patch("topsailai_sessions_info.main", return_value=0) as batch:
            assert cli.run_session_cli(["info", "abc", "def"]) == 0
        batch.assert_called_once_with(["abc", "def"])
        single.assert_not_called()

    def test_shared_options_are_forwarded(self):
        with patch("topsailai_session_info.main", return_value=0) as single:
            cli.run_session_cli(
                ["info", "abc", "--json", "--no-color", "--db-conn", "sqlite:///x"]
            )
        single.assert_called_once_with(
            ["abc", "--json", "--no-color", "--db-conn", "sqlite:///x"]
        )


class TestChildCommandForwarding:
    """Each action must forward exactly the flags its child script accepts."""

    def test_list_forwards_filters(self):
        with patch.object(cli, "_run_script", return_value=0) as run:
            assert cli.run_session_cli(
                ["list", "--json", "--limit", "5", "--offset", "2", "--sort", "desc"]
            ) == 0
        command, argv = run.call_args.args
        assert command == cli._SESSION_LIST
        assert argv == ["--json", "--limit", "5", "--offset", "2", "--sort", "desc"]

    def test_status_reports_state(self, capsys):
        with patch.object(cli, "_capture_script", return_value=(0, "idle\n", "")):
            assert cli.run_session_cli(["status", "abc"]) == 0
        assert capsys.readouterr().out.strip() == "idle"

    def test_status_json_contract(self, capsys):
        with patch.object(cli, "_capture_script", return_value=(0, "processing\n", "")):
            assert cli.run_session_cli(["status", "abc", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["state"] == "processing"
        assert document["ok"] is True

    def test_history_forwards_session_and_limit(self):
        with patch.object(cli, "_run_script", return_value=0) as run:
            assert cli.run_session_cli(["history", "abc", "--max-chars", "200"]) == 0
        command, argv = run.call_args.args
        assert command == cli._RETRIEVE_MESSAGES
        assert argv == ["abc", "--max-chars", "200"]

    def test_history_json_forwards_json_flag(self):
        """--json is forwarded to the backing retrieval script."""
        with patch.object(cli, "_capture_script", return_value=(0, "[]", "")) as cap:
            assert cli.run_session_cli(["history", "abc", "--json"]) == 0
        command, argv = cap.call_args.args
        assert command == cli._RETRIEVE_MESSAGES
        assert argv == ["abc", "--json"]

    def test_history_json_forwards_db_conn_and_limit(self):
        """The JSON path keeps the same options as the human-readable path."""
        with patch.object(cli, "_capture_script", return_value=(0, "[]", "")) as cap:
            assert cli.run_session_cli(
                ["history", "abc", "--db-conn", "sqlite:///custom.db",
                 "--max-chars", "200", "--json"]
            ) == 0
        command, argv = cap.call_args.args
        assert command == cli._RETRIEVE_MESSAGES
        assert argv == ["abc", "sqlite:///custom.db", "--max-chars", "200", "--json"]

    def test_history_json_success_document(self, capsys):
        """A successful read emits one structured document with the messages."""
        payload = json.dumps([{"role": "user", "content": "hello"}])
        with patch.object(cli, "_capture_script", return_value=(0, payload, "")):
            assert cli.run_session_cli(["history", "abc", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["ok"] is True
        assert document["exit_code"] == 0
        assert document["action"] == "history"
        assert document["session_id"] == "abc"
        assert document["message_count"] == 1
        assert document["messages"] == [{"role": "user", "content": "hello"}]
        assert document["error_code"] is None
        assert document["message"] is None

    def test_history_json_empty_history_is_zero_count(self, capsys):
        """An empty history is an empty array with a zero count."""
        with patch.object(cli, "_capture_script", return_value=(0, "[]", "")):
            assert cli.run_session_cli(["history", "abc", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["ok"] is True
        assert document["messages"] == []
        assert document["message_count"] == 0

    def test_history_json_retrieval_failure_is_classified(self, capsys):
        """A child failure is reported as a classified result, not a document."""
        with patch.object(cli, "_capture_script",
                          return_value=(1, "", "Error: database error")):
            assert cli.run_session_cli(["history", "abc", "--json"]) == 1
        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert document["ok"] is False
        assert document["exit_code"] == 1
        assert document["error_code"] == "history_unavailable"
        assert document["messages"] is None
        assert document["message_count"] is None
        assert "database error" in document["message"]

    def test_history_json_unusable_document_is_rejected(self, capsys):
        """A non-array document is rejected instead of being passed through."""
        with patch.object(cli, "_capture_script",
                          return_value=(0, "Messages:\n----\n", "")):
            assert cli.run_session_cli(["history", "abc", "--json"]) == 1
        document = json.loads(capsys.readouterr().out)
        assert document["ok"] is False
        assert document["error_code"] == "history_unavailable"
        assert document["messages"] is None

    def test_history_json_missing_command_reports_127(self, capsys):
        """A missing child command is reported as command_missing."""
        with patch.object(cli, "_capture_script",
                          return_value=(cli._COMMAND_MISSING, "", "Command not found")):
            assert cli.run_session_cli(["history", "abc", "--json"]) == cli._COMMAND_MISSING
        document = json.loads(capsys.readouterr().out)
        assert document["ok"] is False
        assert document["error_code"] == "command_missing"

    def test_search_uses_registered_instruction(self):
        with patch.object(cli, "_run_script", return_value=0) as run:
            assert cli.run_session_cli(["search", "abc", "timeout"]) == 0
        command, argv = run.call_args.args
        assert command == cli._AGENT_CALL_INSTRUCTION
        assert argv == ["-s", "abc", "-i", "/ctx.search", "-p", "timeout"]

    def test_add_msg_forwards_message(self):
        with patch.object(cli, "_run_script", return_value=0) as run:
            assert cli.run_session_cli(["add-msg", "abc", "-m", "please retry"]) == 0
        command, argv = run.call_args.args
        assert command == cli._SESSION_ADD_MESSAGE
        assert argv == ["-s", "abc", "-m", "please retry"]

    def test_missing_child_command_reports_127(self, capsys):
        with patch.object(cli.subprocess, "run", side_effect=FileNotFoundError):
            assert cli.run_session_cli(["list"]) == cli._COMMAND_MISSING
        assert "Command not found" in capsys.readouterr().err


class TestCoreRegistration:
    """The subcommand must be reachable from the top-level entry point."""

    def test_session_is_not_reported_as_invalid_subcommand(self, capsys):
        """The top-level parser must accept ``session`` as a known subcommand."""
        from cli_topsailai import core

        with patch("cli_topsailai.session_cli.run_session_cli", return_value=0):
            with pytest.raises(SystemExit) as exit_info:
                core.main(["session", "--help"])
        assert exit_info.value.code == 0
        assert "invalid subcommand" not in capsys.readouterr().err

    def test_agent_mode_does_not_swallow_session(self):
        from cli_topsailai import core

        assert core._preprocess_agent_mode(["-m", "session", "list"]) == [
            "--agent-mode=auto", "session", "list",
        ]

    def test_main_dispatches_session(self):
        from cli_topsailai import core

        with patch("cli_topsailai.session_cli.run_session_cli", return_value=0) as run:
            with pytest.raises(SystemExit) as exit_info:
                core.main(["session", "list"])
        assert exit_info.value.code == 0
        run.assert_called_once_with(["list"])
