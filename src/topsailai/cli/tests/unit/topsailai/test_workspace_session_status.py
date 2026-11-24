"""Verify per-row lock state collection for the workspace JSON document.

Author: DawsonLin

``session_status`` answers a different question than the row's ``status`` field:
``status`` reports what the agent process is doing, while ``session_status``
reports whether a task currently holds the session lock. These tests pin the
collector's contract: it reuses the existing ``topsailai_session_status``
command instead of probing the lock itself, it queries each session once however
many rows that session has, and a failure stays inside its own row.
"""

import json
import subprocess
from unittest.mock import Mock

import pytest

from cli_topsailai import core, workspace_session_status as wss


def row(session_id="sample", filename=None):
    """Build a discovered row carrying only the fields the collector reads."""
    return {
        "session_id": session_id,
        "filename": filename or f"{session_id}.1.session.stdout",
    }


def answer(status="idle", error_code=None, message=None):
    """Build the child command's own JSON answer."""
    return json.dumps({
        "session_id": "sample",
        "status": status,
        "error_code": error_code,
        "message": message,
    })


def completed(returncode=0, stdout="", stderr=""):
    """Build the completed-process value the shared runner returns."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestOneQueryPerSession:
    """Several rows of one session share one lock, so they share one query."""

    def test_rows_of_one_session_share_one_query(self):
        """Four rows over two sessions must run the child exactly twice."""
        calls = []

        def query(session_id):
            calls.append(session_id)
            return {"status": "idle", "error_code": None, "message": None}

        rows = [
            row("s1", "s1.1.session.stdout"),
            row("s1", "s1.1.task.stdout"),
            row("s1", "s1.2.session.stdout"),
            row("s2", "s2.3.session.stdout"),
        ]
        collected = wss.collect_workspace_session_status(rows, query=query)

        assert calls == ["s1", "s2"]
        assert sorted(collected) == [
            "s1.1.session.stdout", "s1.1.task.stdout",
            "s1.2.session.stdout", "s2.3.session.stdout",
        ]

    def test_every_row_of_a_session_reports_the_same_answer(self):
        """A shared answer must reach every row, not only the first one."""
        rows = [row("s1", "s1.1.session.stdout"), row("s1", "s1.2.session.stdout")]
        collected = wss.collect_workspace_session_status(
            rows, query=lambda sid: {"status": "processing", "error_code": None,
                                     "message": None},
        )

        assert collected["s1.1.session.stdout"]["status"] == "processing"
        assert collected["s1.2.session.stdout"]["status"] == "processing"

    def test_a_row_answer_is_a_copy(self):
        """Mutating one row's record must not change its sibling's record."""
        rows = [row("s1", "s1.1.session.stdout"), row("s1", "s1.2.session.stdout")]
        collected = wss.collect_workspace_session_status(
            rows, query=lambda sid: {"status": "idle", "error_code": None,
                                     "message": None},
        )
        collected["s1.1.session.stdout"]["status"] = "changed"

        assert collected["s1.2.session.stdout"]["status"] == "idle"


class TestReuseOfTheExistingCommand:
    """The collector must call the existing command, never probe the lock."""

    def test_the_existing_command_is_invoked_with_json(self, monkeypatch):
        """The child is the existing command, asked for its structured answer."""
        seen = []

        def fake_run(cmd):
            seen.append(cmd)
            return completed(stdout=answer("processing"))

        monkeypatch.setattr(
            "cli_topsailai.session_info._run_lookup_command", fake_run,
        )
        collected = wss.collect_workspace_session_status([row("s1")])

        assert seen == [[wss.SESSION_STATUS_COMMAND, "-s", "s1", "--json"]]
        assert collected["s1.1.session.stdout"]["status"] == "processing"

    def test_the_collector_does_not_open_lock_files(self, monkeypatch):
        """No lock helper may be reached: detection belongs to the command."""
        import cli_topsailai.workspace_session_status as module

        assert not hasattr(module, "ctxm_try_session_lock")
        assert not hasattr(module, "fcntl")

    def test_a_missing_command_is_reported_per_row(self, monkeypatch):
        """An uninstalled child must not raise out of the collector."""
        def fake_run(cmd):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(
            "cli_topsailai.session_info._run_lookup_command", fake_run,
        )
        collected = wss.collect_workspace_session_status([row("s1")])

        record = collected["s1.1.session.stdout"]
        assert record["status"] is None
        assert record["error_code"] == "command_missing"

    def test_a_timeout_is_reported_per_row(self, monkeypatch):
        """A timed-out child is one row's failure, not the document's."""
        def fake_run(cmd):
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(
            "cli_topsailai.session_info._run_lookup_command", fake_run,
        )
        collected = wss.collect_workspace_session_status([row("s1")])

        assert collected["s1.1.session.stdout"]["error_code"] == "timeout"

    def test_a_nonzero_exit_keeps_the_child_message(self, monkeypatch):
        """The child's own diagnostic must survive into the row record."""
        monkeypatch.setattr(
            "cli_topsailai.session_info._run_lookup_command",
            lambda cmd: completed(returncode=1, stderr="lock backend failed\n"),
        )
        collected = wss.collect_workspace_session_status([row("s1")])

        record = collected["s1.1.session.stdout"]
        assert record["error_code"] == "status_unavailable"
        assert record["message"] == "lock backend failed"


class TestAnswerParsing:
    """The record copies the child's vocabulary instead of inventing one."""

    def test_idle_and_processing_are_the_only_success_values(self):
        """Both documented states parse into a success record."""
        assert wss._parse_status(answer("idle"))["status"] == "idle"
        assert wss._parse_status(answer("processing"))["status"] == "processing"

    def test_a_failure_answer_forwards_the_child_error_code(self):
        """The child's own failure code is preserved, not replaced."""
        record = wss._parse_status(answer(None, "missing_session_id", "no id"))

        assert record["status"] is None
        assert record["error_code"] == "missing_session_id"
        assert record["message"] == "no id"

    def test_an_undecodable_answer_is_invalid_payload(self):
        """A non-JSON answer is classified rather than guessed at."""
        assert wss._parse_status("not json")["error_code"] == "invalid_payload"

    def test_a_non_object_answer_is_invalid_payload(self):
        """A JSON array is not the documented answer shape."""
        assert wss._parse_status("[1, 2]")["error_code"] == "invalid_payload"

    def test_an_unknown_status_is_not_accepted(self):
        """A status outside the vocabulary must not be published as success."""
        record = wss._parse_status(answer("busy"))

        assert record["status"] is None
        assert record["error_code"] == "invalid_payload"


class TestSessionIdentity:
    """A temporary session has no identifier, so its display label is mapped."""

    def test_temporary_spellings_resolve_to_the_reserved_prefix(self):
        """Both the display marker and the on-disk prefix name one session."""
        assert wss._file_session_id("(temp)") == wss.TEMP_SESSION_ID
        assert wss._file_session_id("topsailai") == wss.TEMP_SESSION_ID
        assert wss._file_session_id("") == wss.TEMP_SESSION_ID
        assert wss._file_session_id(None) == wss.TEMP_SESSION_ID

    def test_an_unsafe_identifier_is_unsupported(self):
        """A path-like identity must not be handed to the child command."""
        rows = [row("../etc", "../etc.1.session.stdout")]
        collected = wss.collect_workspace_session_status(
            rows, query=Mock(side_effect=AssertionError("must not be queried")),
        )

        assert collected["../etc.1.session.stdout"]["error_code"] == "unsupported_row"

    def test_a_row_without_a_filename_is_absent(self):
        """A row with no key to report under is skipped, not invented."""
        collected = wss.collect_workspace_session_status(
            [{"session_id": "s1"}], query=lambda sid: {"status": "idle"},
        )

        assert collected == {}


class TestItemContract:
    """The field is always present and never overwrites the process status."""

    def test_the_key_is_present_and_null_when_not_requested(self):
        """A consumer can tell "not requested" from "requested but unavailable"."""
        item = core._workspace_json_item({"session_id": "s", "filename": "f"}, 1)

        assert "session_status" in item
        assert item["session_status"] is None

    def test_the_collected_record_is_published(self):
        """A collected record reaches the item unchanged."""
        record = {"status": "processing", "error_code": None, "message": None}
        item = core._workspace_json_item(
            {"session_id": "s", "filename": "f"}, 1, None, record,
        )

        assert item["session_status"] == record

    def test_the_process_status_is_not_overwritten(self):
        """The two fields describe different things and must both survive."""
        item = core._workspace_json_item(
            {"session_id": "s", "filename": "f", "workspace_status": "input"},
            1, None, {"status": "idle", "error_code": None, "message": None},
        )

        assert item["status"] == "input"
        assert item["session_status"]["status"] == "idle"

    def test_the_task_and_session_rows_share_one_schema(self):
        """A task row must not gain or lose the key."""
        session_item = core._workspace_json_item(
            {"session_id": "s", "filename": "f"}, 1,
        )
        task_item = core._workspace_json_item(
            {"session_id": "s", "filename": "f", "is_task": True}, 1,
        )

        assert set(task_item) == set(session_item)


class TestFlagWiring:
    """The flag requests data that only the JSON document can carry."""

    def test_the_flag_alone_selects_json(self, monkeypatch):
        """Lock state has no table column, so the table must never be printed."""
        printed = []

        def fake_json(**kwargs):
            printed.append(kwargs)

        monkeypatch.setattr(core, "_print_workspace_json", fake_json)
        monkeypatch.setattr(
            core, "_print_workspace_table",
            Mock(side_effect=AssertionError("table must not be printed")),
        )

        with pytest.raises(SystemExit) as raised:
            core.main(["workspace", "list", "--include-session-status"])

        assert raised.value.code == 0
        assert len(printed) == 1
        assert printed[0]["include_session_status"] is True

    def test_the_flag_defaults_to_false(self, monkeypatch):
        """The flag must be opt-in, so an unrequested run never collects."""
        printed = []
        monkeypatch.setattr(
            core, "_print_workspace_json",
            lambda **kwargs: printed.append(kwargs),
        )

        with pytest.raises(SystemExit) as raised:
            core.main(["workspace", "list", "--json"])

        assert raised.value.code == 0
        assert printed[0]["include_session_status"] is False

    def test_the_collector_runs_only_when_requested(self, monkeypatch):
        """An unrequested collector must never be imported or called."""
        called = []
        monkeypatch.setattr(
            "cli_topsailai.workspace_session_status.collect_workspace_session_status",
            lambda rows: called.append(rows) or {},
        )
        monkeypatch.setattr(
            "cli_topsailai.log_files.discover_workspace_log_files",
            lambda *a, **k: [row("s1")],
        )
        monkeypatch.setattr(
            "cli_topsailai.session_info.enrich_files_with_session_names",
            lambda files: None,
        )
        monkeypatch.setattr(core, "_enrich_driver_rows", lambda *a, **k: None)
        monkeypatch.setattr(
            "cli_topsailai.paths.get_topsailai_home", lambda: "/tmp/home",
        )

        core._print_workspace_json()
        assert called == []

        core._print_workspace_json(include_session_status=True)
        assert len(called) == 1
        assert [r["filename"] for r in called[0]] == ["s1.1.session.stdout"]

    def test_a_collector_failure_keeps_the_document(self, monkeypatch, capsys):
        """A broken collector must leave the field null, not break the output."""
        monkeypatch.setattr(
            "cli_topsailai.workspace_session_status.collect_workspace_session_status",
            Mock(side_effect=RuntimeError("collector exploded")),
        )
        monkeypatch.setattr(
            "cli_topsailai.log_files.discover_workspace_log_files",
            lambda *a, **k: [row("s1")],
        )
        monkeypatch.setattr(
            "cli_topsailai.session_info.enrich_files_with_session_names",
            lambda files: None,
        )
        monkeypatch.setattr(core, "_enrich_driver_rows", lambda *a, **k: None)
        monkeypatch.setattr(
            "cli_topsailai.paths.get_topsailai_home", lambda: "/tmp/home",
        )

        core._print_workspace_json(include_session_status=True)

        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == 1
        assert payload["items"][0]["session_status"] is None
