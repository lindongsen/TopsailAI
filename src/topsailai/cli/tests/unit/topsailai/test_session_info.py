#!/usr/bin/env python3
"""Unit tests for cli_topsailai.session_info."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai import session_info


def _batch_payload(*records):
    """Build the JSON array printed by ``topsailai_sessions_info --json``."""
    return json.dumps(
        [
            {
                "session_id": session_id,
                "session_name": name,
                "project_workspace": workspace,
            }
            for session_id, name, workspace in records
        ]
    )


def _lookup_result(stdout, returncode=0, stderr=""):
    """Build a completed-process stand-in for the batch lookup command."""
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _batch_lookup(*records):
    """Build the mapping returned by ``_get_sessions_info`` for *records*."""
    return {
        session_id: session_info._LookupResult(name, workspace, True)
        for session_id, name, workspace in records
    }


class TestGetSessionsInfo(unittest.TestCase):
    """Tests for _get_sessions_info."""

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_valid_records_return_name_and_workspace(self, mock_run):
        """A JSON array of records is mapped by session_id."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "session_id": "s1",
                    "session_name": "Auto Summary",
                    "project_workspace": "/work/project-a",
                },
                {
                    "session_id": "s2",
                    "session_name": "Second",
                    "project_workspace": "/work/project-b",
                },
            ]),
            stderr="",
        )
        result = session_info._get_sessions_info(["s1", "s2"])
        self.assertEqual(set(result), {"s1", "s2"})
        self.assertTrue(result["s1"].success)
        self.assertEqual(result["s1"].name, "Auto Summary")
        self.assertEqual(result["s1"].project_workspace, "/work/project-a")
        self.assertEqual(result["s2"].name, "Second")
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1", "s2"]
        )

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_whitespace_name_normalized(self, mock_run):
        """Whitespace-only name is normalized to None; workspace is preserved."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "session_id": "s1",
                    "session_name": "   ",
                    "project_workspace": "/work/project-a",
                }
            ]),
            stderr="",
        )
        result = session_info._get_sessions_info(["s1"])
        self.assertTrue(result["s1"].success)
        self.assertIsNone(result["s1"].name)
        self.assertEqual(result["s1"].project_workspace, "/work/project-a")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_whitespace_workspace_normalized(self, mock_run):
        """Whitespace-only workspace is normalized to None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "session_id": "s1",
                    "session_name": "Auto Summary",
                    "project_workspace": "   ",
                }
            ]),
            stderr="",
        )
        result = session_info._get_sessions_info(["s1"])
        self.assertTrue(result["s1"].success)
        self.assertEqual(result["s1"].name, "Auto Summary")
        self.assertIsNone(result["s1"].project_workspace)

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_non_zero_exit_with_records_is_partial_success(self, mock_run):
        """Exit code 1 for unknown identifiers still yields the found records."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps([
                {"session_id": "s1", "session_name": "Found",
                 "project_workspace": "/work/a"}
            ]),
            stderr="[INFO] Session not found: s2",
        )
        result = session_info._get_sessions_info(["s1", "s2"])
        self.assertEqual(set(result), {"s1"})
        self.assertEqual(result["s1"].name, "Found")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_non_zero_exit_without_stdout_returns_empty(self, mock_run):
        """A storage error with no payload is a transient failure."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error",
        )
        self.assertEqual(session_info._get_sessions_info(["s1"]), {})

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_invalid_json_returns_empty(self, mock_run):
        """Invalid JSON response is treated as a transient failure."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json",
            stderr="",
        )
        self.assertEqual(session_info._get_sessions_info(["s1"]), {})

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_non_list_payload_returns_empty(self, mock_run):
        """A single-object payload is rejected because the batch shape is an array."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_id": "s1", "session_name": "Name"}',
            stderr="",
        )
        self.assertEqual(session_info._get_sessions_info(["s1"]), {})

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_unrequested_and_malformed_records_ignored(self, mock_run):
        """Records for other identifiers or non-objects never enter the result."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                "not-a-record",
                {"session_id": "other", "session_name": "Other"},
                {"session_name": "No Id"},
                {"session_id": "s1", "session_name": "Wanted"},
            ]),
            stderr="",
        )
        result = session_info._get_sessions_info(["s1"])
        self.assertEqual(set(result), {"s1"})
        self.assertEqual(result["s1"].name, "Wanted")

    @patch(
        "cli_topsailai.session_info._run_lookup_command",
        side_effect=FileNotFoundError("not found"),
    )
    def test_missing_command_returns_empty(self, mock_run):
        """Missing external command is treated as a transient failure."""
        self.assertEqual(session_info._get_sessions_info(["s1"]), {})

    @patch(
        "cli_topsailai.session_info._run_lookup_command",
        side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=5),
    )
    def test_timeout_returns_empty(self, mock_run):
        """Timeout is treated as a transient failure."""
        self.assertEqual(session_info._get_sessions_info(["s1"]), {})

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_empty_request_skips_subprocess(self, mock_run):
        """No identifiers means no subprocess at all."""
        self.assertEqual(session_info._get_sessions_info([]), {})
        mock_run.assert_not_called()

class TestEnrichFilesWithSessionNames(unittest.TestCase):
    """Tests for enrich_files_with_session_names."""

    def tearDown(self):
        """Clear module-level cache after each test."""
        session_info._SESSION_INFO_CACHE._data.clear()

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_adds_session_name_to_files(self, mock_run):
        """Session names are added to file dicts from one batch response."""
        mock_run.return_value = _lookup_result(
            _batch_payload(
                ("s1", "Auto Summary", "/work/project-a"),
                ("s2", "Auto Summary", "/work/project-a"),
            )
        )
        files = [
            {"session_id": "s1"},
            {"session_id": "s2"},
        ]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Auto Summary")
        self.assertEqual(files[1]["session_name"], "Auto Summary")
        self.assertEqual(mock_run.call_count, 1)

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_deduplicates_session_ids(self, mock_run):
        """Same session ID is only requested once in the batch command."""
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Auto Summary", "/work/project-a"))
        )
        files = [
            {"session_id": "s1"},
            {"session_id": "s1"},
            {"session_id": "s1"},
        ]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(mock_run.call_count, 1)
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1"]
        )
        for f in files:
            self.assertEqual(f["session_name"], "Auto Summary")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_temp_session_skipped(self, mock_run):
        """Temporary sessions are skipped and stored as None."""
        files = [{"session_id": "(temp)"}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertIsNone(files[0]["session_name"])
        self.assertIsNone(files[0]["project_workspace"])

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_empty_session_id_skipped(self, mock_run):
        """Empty session IDs are skipped and stored as None."""
        files = [{"session_id": ""}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertIsNone(files[0]["session_name"])
        self.assertIsNone(files[0]["project_workspace"])

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_transient_failure_not_cached(self, mock_run):
        """Transient failures are not cached; retries are allowed."""
        mock_run.return_value = _lookup_result("", returncode=1, stderr="error")
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["session_name"])
        self.assertEqual(mock_run.call_count, 1)

        # Second refresh should invoke subprocess again because failure was not cached.
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Recovered Name", "/work/project-a"))
        )
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(files2[0]["session_name"], "Recovered Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_unknown_identifier_is_not_cached_as_failure(self, mock_run):
        """A missing identifier in a partial batch is retried on the next refresh."""
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Found", "/work/a")),
            returncode=1,
            stderr="[INFO] Session not found: s2",
        )
        files = [{"session_id": "s1"}, {"session_id": "s2"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Found")
        self.assertIsNone(files[1]["session_name"])
        self.assertIs(session_info._SESSION_INFO_CACHE.get("s2"), session_info._MISSING)

        mock_run.return_value = _lookup_result(
            _batch_payload(("s2", "Late Name", "/work/b"))
        )
        files2 = [{"session_id": "s2"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(files2[0]["session_name"], "Late Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_successful_result_cached(self, mock_run):
        """Successful lookups are cached and not re-fetched."""
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Cached Name", "/work/project-a"))
        )
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Cached Name")
        self.assertEqual(mock_run.call_count, 1)

        mock_run.reset_mock()
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        mock_run.assert_not_called()
        self.assertEqual(files2[0]["session_name"], "Cached Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_empty_name_in_valid_json_not_cached(self, mock_run):
        """A valid JSON response with missing/empty name is not cached."""
        mock_run.return_value = _lookup_result(_batch_payload(("s1", "", "")))
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["session_name"])
        self.assertEqual(mock_run.call_count, 1)

        # Second refresh should invoke subprocess again because empty name was not cached.
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Updated Name", "/work/project-a"))
        )
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(files2[0]["session_name"], "Updated Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_whitespace_name_not_cached(self, mock_run):
        """A whitespace-only name is not cached."""
        mock_run.return_value = _lookup_result(_batch_payload(("s1", "   ", "")))
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["session_name"])
        self.assertEqual(mock_run.call_count, 1)

        # Second refresh should invoke subprocess again.
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Real Name", "/work/project-a"))
        )
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(files2[0]["session_name"], "Real Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_cache_hit_returns_cached_name(self, mock_run):
        """Cached session name is returned without subprocess call."""
        session_info._SESSION_INFO_CACHE.set("s1", ("Cached Name", "/work/cached"))
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertEqual(files[0]["session_name"], "Cached Name")

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_single_batch_call_for_multiple_ids(self, mock_run):
        """Every distinct ID is resolved by exactly one subprocess call."""

        def side_effect(cmd, **kwargs):
            session_ids = cmd[2:]
            return _lookup_result(
                _batch_payload(
                    *[
                        (sid, f"Name {sid}", f"/work/{sid}")
                        for sid in session_ids
                    ]
                )
            )

        mock_run.side_effect = side_effect
        files = [
            {"session_id": "s1"},
            {"session_id": "s2"},
            {"session_id": "s3"},
        ]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Name s1")
        self.assertEqual(files[1]["session_name"], "Name s2")
        self.assertEqual(files[2]["session_name"], "Name s3")
        self.assertEqual(mock_run.call_count, 1)
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1", "s2", "s3"]
        )

    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_missing_session_id_handled(self, mock_run):
        """Files without session_id get None."""
        files = [{}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertIsNone(files[0]["session_name"])


class TestEnrichFilesWithProjectWorkspace(unittest.TestCase):
    """Tests for project_workspace enrichment in enrich_files_with_session_names."""

    def tearDown(self):
        """Clear module-level cache after each test."""
        session_info._SESSION_INFO_CACHE._data.clear()

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_prefers_session_info_workspace_over_lookup(self, mock_run, mock_lookup):
        """Authoritative session record wins over project_history lookup."""
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Auto Summary", "/work/from-session"))
        )
        mock_lookup.return_value = {"s1": "/work/from-history"}
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["project_workspace"], "/work/from-session")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_falls_back_to_lookup_when_session_info_has_no_workspace(
        self, mock_run, mock_lookup
    ):
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Auto Summary", ""))
        )
        mock_lookup.return_value = {"s1": "/work/from-history"}
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["project_workspace"], "/work/from-history")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_falls_back_to_lookup_on_session_info_failure(
        self, mock_run, mock_lookup
    ):
        mock_run.return_value = _lookup_result("", returncode=1, stderr="error")
        mock_lookup.return_value = {"s1": "/work/from-history"}
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["project_workspace"], "/work/from-history")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_missing_workspace_shows_none(self, mock_run, mock_lookup):
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Auto Summary", ""))
        )
        mock_lookup.return_value = {}
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["project_workspace"])

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    def test_temp_session_workspace_is_none(self, mock_lookup):
        mock_lookup.return_value = {"topsailai": "/work/temp"}
        files = [{"session_id": "(temp)"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["project_workspace"])
        mock_lookup.assert_not_called()

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    def test_empty_session_id_workspace_is_none(self, mock_lookup):
        mock_lookup.return_value = {"": "/work/empty"}
        files = [{"session_id": ""}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["project_workspace"])

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    def test_missing_session_id_workspace_is_none(self, mock_lookup):
        mock_lookup.return_value = {}
        files = [{}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["project_workspace"])

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_workspace_lookup_refreshed_each_call(self, mock_run, mock_lookup):
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Auto Summary", "/work/first"))
        )
        mock_lookup.return_value = {}
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["project_workspace"], "/work/first")

        # Cache hit on second call; lookup is still loaded as fallback.
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(files2[0]["project_workspace"], "/work/first")
        self.assertEqual(mock_lookup.call_count, 2)




class TestIsPidAlive(unittest.TestCase):
    """Tests for _is_pid_alive.

    These assert behaviour, not mechanism: the probe must agree with the
    shared liveness primitive on live, absent, zombie and non-positive PIDs.
    """

    def test_current_process_is_alive(self):
        """The running test process must be reported alive."""
        self.assertTrue(session_info._is_pid_alive(os.getpid()))

    def test_absent_process_is_dead(self):
        """A reaped PID must be reported as not alive."""
        self.assertFalse(session_info._is_pid_alive(_absent_pid()))

    def test_zombie_is_dead(self):
        """A zombie has terminated and must not be reported alive."""
        pid = _spawn_zombie()
        try:
            self.assertFalse(session_info._is_pid_alive(pid))
        finally:
            _reap(pid)

    def test_none_pid_is_dead(self):
        """None PID is treated as not alive."""
        self.assertFalse(session_info._is_pid_alive(None))

    def test_invalid_pid_is_dead(self):
        """Non-integer or non-positive PID values are treated as not alive."""
        self.assertFalse(session_info._is_pid_alive("abc"))
        self.assertFalse(session_info._is_pid_alive(-1))
        self.assertFalse(session_info._is_pid_alive(0))


class TestHasRealSessionId(unittest.TestCase):
    """Tests for _has_real_session_id."""

    def test_real_session_id(self):
        self.assertTrue(session_info._has_real_session_id({"session_id": "s1"}))

    def test_temp_session_id(self):
        self.assertFalse(
            session_info._has_real_session_id({"session_id": "(temp)"})
        )

    def test_empty_session_id(self):
        self.assertFalse(session_info._has_real_session_id({"session_id": ""}))
        self.assertFalse(
            session_info._has_real_session_id({"session_id": "   "})
        )

    def test_missing_session_id(self):
        self.assertFalse(session_info._has_real_session_id({}))
        self.assertFalse(
            session_info._has_real_session_id({"session_id": None})
        )


class TestIsUnnamedRunningSession(unittest.TestCase):
    """Tests for _is_unnamed_running_session."""

    @patch("cli_topsailai.session_info._is_pid_alive")
    def test_running_unnamed_session_matches(self, mock_alive):
        mock_alive.return_value = True
        self.assertTrue(
            session_info._is_unnamed_running_session(
                {"session_id": "s1", "session_name": None, "pid": 1234}
            )
        )

    @patch("cli_topsailai.session_info._is_pid_alive")
    def test_named_session_is_excluded(self, mock_alive):
        mock_alive.return_value = True
        self.assertFalse(
            session_info._is_unnamed_running_session(
                {"session_id": "s1", "session_name": "Named", "pid": 1234}
            )
        )

    @patch("cli_topsailai.session_info._is_pid_alive")
    def test_dead_session_is_excluded(self, mock_alive):
        mock_alive.return_value = False
        self.assertFalse(
            session_info._is_unnamed_running_session(
                {"session_id": "s1", "session_name": None, "pid": 1234}
            )
        )

    def test_temp_session_is_excluded(self):
        self.assertFalse(
            session_info._is_unnamed_running_session(
                {"session_id": "(temp)", "session_name": None, "pid": 1234}
            )
        )


class TestEnrichRunningUnnamedSessions(unittest.TestCase):
    """Tests for enrich_running_unnamed_sessions."""

    def tearDown(self):
        """Clear module-level cache after each test."""
        session_info._SESSION_INFO_CACHE._data.clear()

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_backfills_running_unnamed_session(self, mock_run, mock_alive):
        """A running unnamed session gets its name from session info."""
        mock_alive.return_value = True
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Fresh Name", "/work/a"))
        )
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertEqual(files[0]["session_name"], "Fresh Name")
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1"]
        )

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_named_sessions_are_unchanged(self, mock_run, mock_alive):
        """Sessions that already have a name are not queried."""
        mock_alive.return_value = True
        files = [
            {"session_id": "s1", "session_name": "Existing", "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertEqual(files[0]["session_name"], "Existing")
        mock_run.assert_not_called()

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_dead_sessions_are_unchanged(self, mock_run, mock_alive):
        """Dead sessions are not queried even if unnamed."""
        mock_alive.return_value = False
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertIsNone(files[0]["session_name"])
        mock_run.assert_not_called()

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_failure_is_silent(self, mock_run, mock_alive):
        """A failed lookup leaves the file unchanged."""
        mock_alive.return_value = True
        mock_run.return_value = _lookup_result("", returncode=1, stderr="error")
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertIsNone(files[0]["session_name"])

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_deduplicates_session_ids(self, mock_run, mock_alive):
        """The same session ID is requested only once."""
        mock_alive.return_value = True
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "Shared Name", ""))
        )
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
            {"session_id": "s1", "session_name": None, "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertEqual(mock_run.call_count, 1)
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1"]
        )
        self.assertEqual(files[0]["session_name"], "Shared Name")
        self.assertEqual(files[1]["session_name"], "Shared Name")

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_multiple_unnamed_sessions_use_one_batch_call(self, mock_run, mock_alive):
        """Several unnamed running sessions are resolved by one subprocess."""
        mock_alive.return_value = True
        mock_run.return_value = _lookup_result(
            _batch_payload(("s1", "First", ""), ("s2", "Second", ""))
        )
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
            {"session_id": "s2", "session_name": None, "pid": 5678},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertEqual(mock_run.call_count, 1)
        mock_run.assert_called_once_with(
            ["topsailai_sessions_info", "--json", "s1", "s2"]
        )
        self.assertEqual(files[0]["session_name"], "First")
        self.assertEqual(files[1]["session_name"], "Second")

    @patch("cli_topsailai.session_info._is_pid_alive")
    @patch("cli_topsailai.session_info._run_lookup_command")
    def test_empty_name_result_is_ignored(self, mock_run, mock_alive):
        """An empty name from session info does not overwrite the field."""
        mock_alive.return_value = True
        mock_run.return_value = _lookup_result(_batch_payload(("s1", "", "")))
        files = [
            {"session_id": "s1", "session_name": None, "pid": 1234},
        ]
        session_info.enrich_running_unnamed_sessions(files)
        self.assertIsNone(files[0]["session_name"])


class TestCompletedMetadataSnapshot(unittest.TestCase):
    """Tests for scan-local completed metadata snapshots."""

    def tearDown(self):
        """Clear module-level cache after each test."""
        session_info._SESSION_INFO_CACHE._data.clear()

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_snapshot_name_and_path_avoid_query(self, mock_query, mock_lookup):
        """A complete snapshot supplies both fields without a subprocess lookup."""
        mock_lookup.return_value = {"s1": "/history"}
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "  Completed Name  ", "/meta"),
        }]
        session_info.enrich_files_with_session_names(files)
        mock_query.assert_not_called()
        self.assertEqual(files[0]["session_name"], "Completed Name")
        self.assertEqual(files[0]["project_workspace"], "/meta")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_missing_snapshot_path_queries_and_preserves_name(self, mock_query, mock_lookup):
        """A cold snapshot path lookup updates cache and avoids a retry."""
        mock_query.return_value = _batch_lookup(("s1", "Queried", "/queried"))
        mock_lookup.return_value = {"s1": "/history"}
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "Completed", None),
        }]
        session_info.enrich_files_with_session_names(files)
        mock_query.assert_called_once_with(["s1"])
        self.assertEqual(session_info._SESSION_INFO_CACHE.get("s1"),
                         ("Queried", "/queried"))
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/queried")

        session_info.enrich_files_with_session_names(files)
        self.assertEqual(mock_query.call_count, 1)
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/queried")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_mixed_instances_reuse_meta_cache_without_query(self, mock_query, mock_lookup):
        """An ordinary row reuses a completed snapshot cached for the same ID."""
        mock_lookup.return_value = {}
        files = [
            {"session_id": "s1", "pid": 123, "is_task": False,
             "_completed_session_meta": ("s1", 123, "First", "/first")},
            {"session_id": "s1", "pid": 456, "is_task": False},
        ]
        session_info.enrich_files_with_session_names(files)
        mock_query.assert_not_called()
        self.assertEqual(files[0]["session_name"], "First")
        self.assertEqual(files[1]["session_name"], "First")
        self.assertEqual(files[1]["project_workspace"], "/first")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_query_failure_keeps_snapshot_and_retries(self, mock_query, mock_lookup):
        """A failed path lookup does not poison retries or erase the name."""
        mock_query.return_value = {}
        mock_lookup.return_value = {"s1": "/history"}
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "Completed", None),
        }]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/history")
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(mock_query.call_count, 2)

    def test_mismatched_snapshot_falls_back_to_query(self):
        """A snapshot for another PID is rejected rather than reused."""
        with patch("cli_topsailai.session_info._get_sessions_info") as mock_query, \
                patch("cli_topsailai.session_info.load_project_workspace_lookup") as mock_lookup:
            mock_query.return_value = _batch_lookup(("s1", "Queried", "/queried"))
            mock_lookup.return_value = {}
            files = [{
                "session_id": "s1", "pid": 456, "is_task": False,
                "_completed_session_meta": ("s1", 123, "Wrong", "/wrong"),
            }]
            session_info.enrich_files_with_session_names(files)
            mock_query.assert_called_once_with(["s1"])
            self.assertEqual(files[0]["session_name"], "Queried")


    def test_snapshot_session_id_mismatch_falls_back_to_query(self):
        """A snapshot for another session ID is rejected even with the same PID."""
        with patch("cli_topsailai.session_info._get_sessions_info") as mock_query, \
                patch("cli_topsailai.session_info.load_project_workspace_lookup") as mock_lookup:
            mock_query.return_value = _batch_lookup(
                ("row-session", "Queried", "/queried")
            )
            mock_lookup.return_value = {}
            files = [{
                "session_id": "row-session", "pid": 123, "is_task": False,
                "_completed_session_meta": ("wrong-session", 123, "Wrong", "/wrong"),
            }]
            session_info.enrich_files_with_session_names(files)
            mock_query.assert_called_once_with(["row-session"])
            self.assertEqual(files[0]["session_name"], "Queried")
            self.assertEqual(files[0]["project_workspace"], "/queried")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_snapshot_name_wins_but_cached_path_is_preserved(self, mock_query, mock_lookup):
        """A cached path wins while the completed snapshot name wins over its name."""
        mock_lookup.return_value = {"s1": "/history"}
        session_info._SESSION_INFO_CACHE.set("s1", ("Cached Name", "/cached"))
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "Completed", "/meta"),
        }]
        session_info.enrich_files_with_session_names(files)
        mock_query.assert_not_called()
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/cached")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_name_only_cache_still_queries_for_missing_snapshot_path(self, mock_query, mock_lookup):
        """A name-only cache is completed by a successful workspace lookup."""
        mock_lookup.return_value = {"s1": "/history"}
        session_info._SESSION_INFO_CACHE.set("s1", ("Cached Name", None))
        mock_query.return_value = _batch_lookup(("s1", "Queried Name", "/queried"))
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "Completed", None),
        }]
        session_info.enrich_files_with_session_names(files)
        mock_query.assert_called_once_with(["s1"])
        self.assertEqual(session_info._SESSION_INFO_CACHE.get("s1"),
                         ("Queried Name", "/queried"))
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/queried")

        session_info.enrich_files_with_session_names(files)
        self.assertEqual(mock_query.call_count, 1)
        self.assertEqual(files[0]["session_name"], "Completed")
        self.assertEqual(files[0]["project_workspace"], "/queried")

    @patch("cli_topsailai.session_info._is_pid_alive", return_value=True)
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_repeated_and_running_enrichment_do_not_query_snapshot(self, mock_query, mock_alive):
        """A complete snapshot remains named through repeated enrichment passes."""
        files = [{
            "session_id": "s1", "pid": 123, "is_task": False,
            "_completed_session_meta": ("s1", 123, "Completed", "/meta"),
        }]
        session_info.enrich_files_with_session_names(files)
        session_info.enrich_files_with_session_names(files)
        session_info.enrich_running_unnamed_sessions(files)
        mock_query.assert_not_called()
        self.assertEqual(files[0]["session_name"], "Completed")

    @patch("cli_topsailai.session_info.load_project_workspace_lookup")
    @patch("cli_topsailai.session_info._get_sessions_info")
    def test_same_session_id_different_snapshot_pids_share_first_cache_value(
        self, mock_query, mock_lookup
    ):
        """Separate completed snapshots retain names but share the first cache value."""
        mock_lookup.return_value = {}
        candidates = [
            {
                "session_id": "shared",
                "pid": 101,
                "is_task": False,
                "_completed_session_meta": ("shared", 101, "First", "/first"),
            },
            {
                "session_id": "shared",
                "pid": 202,
                "is_task": False,
                "_completed_session_meta": ("shared", 202, "Second", "/second"),
            },
        ]
        for ordered in (candidates, list(reversed(candidates))):
            session_info._SESSION_INFO_CACHE = session_info._SessionInfoCache()
            files = [dict(item) for item in ordered]
            session_info.enrich_files_with_session_names(files)
            mock_query.assert_not_called()
            winner = ordered[0]["_completed_session_meta"]
            self.assertEqual(
                [(item["session_name"], item["project_workspace"]) for item in files],
                [(item["_completed_session_meta"][2], winner[3]) for item in ordered],
            )
            self.assertEqual(session_info._SESSION_INFO_CACHE.get("shared"),
                             (winner[2], winner[3]))

            ordinary = [{"session_id": "shared", "pid": 303, "is_task": False}]
            session_info.enrich_files_with_session_names(ordinary)
            mock_query.assert_not_called()
            self.assertEqual(ordinary[0]["session_name"], winner[2])
            self.assertEqual(ordinary[0]["project_workspace"], winner[3])


class TestKillProcessGroup(unittest.TestCase):
    """Tests for _kill_process_group and _run_lookup_command."""

    def _spawn_group_with_grandchild(self):
        """Start a process group whose grandchild outlives its direct parent.

        The CLI dispatcher runs the script through ``uv run``, so the process
        that burns CPU is a grandchild.  This fixture reproduces that shape:
        a shell leader that starts a long-lived grandchild and then exits, so
        only a process-group kill can reach the survivor.
        """
        process = subprocess.Popen(
            ["/bin/sh", "-c", "sleep 120 >/dev/null 2>&1 & echo $!; exit 0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, _stderr = process.communicate(timeout=10)
        grandchild_pid = int(stdout.strip())
        self.addCleanup(self._reap, grandchild_pid)
        return process, grandchild_pid

    @staticmethod
    def _reap(pid):
        """Best-effort cleanup so a failed assertion cannot leak a process."""
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    @staticmethod
    def _is_alive(pid):
        """Return True while *pid* still exists."""
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def test_kill_process_group_reaches_grandchild(self):
        """A grandchild survives a direct-child kill but not a group kill."""
        process, grandchild_pid = self._spawn_group_with_grandchild()
        self.assertTrue(self._is_alive(grandchild_pid))

        session_info._kill_process_group(process)

        deadline = time.time() + 5
        while time.time() < deadline and self._is_alive(grandchild_pid):
            time.sleep(0.05)
        self.assertFalse(
            self._is_alive(grandchild_pid),
            "grandchild survived the process-group kill",
        )

    def test_kill_process_group_tolerates_dead_group(self):
        """Killing an already-terminated group is not an error."""
        process = subprocess.Popen(
            ["/bin/sh", "-c", "exit 0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        process.communicate(timeout=10)
        session_info._kill_process_group(process)

    def test_run_lookup_command_returns_completed_process(self):
        """A successful command returns its exit code and stdout."""
        result = session_info._run_lookup_command(
            ["/bin/sh", "-c", "printf 'payload'"]
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "payload")

    def test_run_lookup_command_kills_group_on_timeout(self):
        """A timeout kills the whole group and still raises TimeoutExpired."""
        original_timeout = session_info._SESSION_INFO_TIMEOUT
        session_info._SESSION_INFO_TIMEOUT = 1
        self.addCleanup(
            setattr, session_info, "_SESSION_INFO_TIMEOUT", original_timeout
        )

        pid_dir = tempfile.mkdtemp(prefix="topsailai-session-info-")
        self.addCleanup(shutil.rmtree, pid_dir, True)
        pid_file = os.path.join(pid_dir, "pid")

        with self.assertRaises(subprocess.TimeoutExpired):
            session_info._run_lookup_command(
                ["/bin/sh", "-c", f"sleep 120 & echo $! > {pid_file}; wait"]
            )

        with open(pid_file, "r", encoding="utf-8") as handle:
            grandchild_pid = int(handle.read().strip())
        self.addCleanup(self._reap, grandchild_pid)

        deadline = time.time() + 5
        while time.time() < deadline and self._is_alive(grandchild_pid):
            time.sleep(0.05)
        self.assertFalse(
            self._is_alive(grandchild_pid),
            "grandchild survived the timeout kill",
        )


def _spawn_zombie():
    """Fork a child that exits immediately without being reaped.

    Returns the child PID, which the caller must reap. The helper waits until
    the OS actually reports state ``Z``, because a freshly forked child is
    still running for a few milliseconds and probing it early would test the
    race instead of the zombie contract.
    """
    from cli_topsailai.agent_launch_process import _process_state

    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os._exit(0)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _process_state(pid) == "Z":
            return pid
        time.sleep(0.01)
    raise AssertionError(f"child {pid} never reached zombie state")


def _reap(pid):
    """Reap a child PID, ignoring an already-reaped or non-child PID."""
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


class TestSessionInfoLiveness(unittest.TestCase):
    """Pin the liveness contract of the session-info status path.

    ``session_info`` previously probed ``/proc/{pid}`` existence, which reports
    a zombie as alive. These tests assert the behaviour every status path must
    share so one command cannot call a session Running while another calls it
    Idle.
    """

    def test_zombie_pid_is_not_alive(self):
        """A zombie must not be reported as a live session process."""
        pid = _spawn_zombie()
        try:
            self.assertFalse(session_info._is_pid_alive(pid))
        finally:
            _reap(pid)

    def test_current_process_is_alive(self):
        """The running test process must be reported alive."""
        self.assertTrue(session_info._is_pid_alive(os.getpid()))

    def test_non_positive_pid_is_not_alive(self):
        """Non-positive PIDs must never be probed as one process."""
        self.assertFalse(session_info._is_pid_alive(-1))
        self.assertFalse(session_info._is_pid_alive(0))


def _absent_pid():
    """Return a PID that the OS authoritatively reports as absent."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os._exit(0)
    _reap(pid)
    return pid


if __name__ == "__main__":
    unittest.main()
