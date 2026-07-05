#!/usr/bin/env python3
"""Unit tests for cli_topsailai.session_info."""

import os
import sys
import subprocess
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai import session_info


class TestGetSessionName(unittest.TestCase):
    """Tests for _get_session_name."""

    def test_temp_session_returns_success_with_none(self):
        """Temporary session ID returns a successful None immediately."""
        result = session_info._get_session_name("(temp)")
        self.assertTrue(result.success)
        self.assertIsNone(result.name)

    def test_empty_session_id_returns_success_with_none(self):
        """Empty session ID returns a successful None immediately."""
        result = session_info._get_session_name("")
        self.assertTrue(result.success)
        self.assertIsNone(result.name)

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_valid_session_returns_name(self, mock_run):
        """Valid JSON response returns session_name."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "Auto Summary"}',
            stderr="",
        )
        result = session_info._get_session_name("s1")
        self.assertTrue(result.success)
        self.assertEqual(result.name, "Auto Summary")
        mock_run.assert_called_once()

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_whitespace_name_normalized(self, mock_run):
        """Whitespace-only name is normalized to a successful None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "   "}',
            stderr="",
        )
        result = session_info._get_session_name("s1")
        self.assertTrue(result.success)
        self.assertIsNone(result.name)

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_non_zero_exit_returns_failure(self, mock_run):
        """Non-zero exit code is treated as a transient failure."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error",
        )
        result = session_info._get_session_name("s1")
        self.assertFalse(result.success)
        self.assertIsNone(result.name)

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_invalid_json_returns_failure(self, mock_run):
        """Invalid JSON response is treated as a transient failure."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json",
            stderr="",
        )
        result = session_info._get_session_name("s1")
        self.assertFalse(result.success)
        self.assertIsNone(result.name)

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_non_dict_payload_returns_failure(self, mock_run):
        """Non-dict JSON payload is treated as a transient failure."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='["session_name"]',
            stderr="",
        )
        result = session_info._get_session_name("s1")
        self.assertFalse(result.success)
        self.assertIsNone(result.name)

    @patch(
        "cli_topsailai.session_info.subprocess.run",
        side_effect=FileNotFoundError("not found"),
    )
    def test_missing_command_returns_failure(self, mock_run):
        """Missing external command is treated as a transient failure."""
        result = session_info._get_session_name("s1")
        self.assertFalse(result.success)
        self.assertIsNone(result.name)

    @patch(
        "cli_topsailai.session_info.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=5),
    )
    def test_timeout_returns_failure(self, mock_run):
        """Timeout is treated as a transient failure."""
        result = session_info._get_session_name("s1")
        self.assertFalse(result.success)
        self.assertIsNone(result.name)


class TestEnrichFilesWithSessionNames(unittest.TestCase):
    """Tests for enrich_files_with_session_names."""

    def tearDown(self):
        """Clear module-level cache after each test."""
        session_info._SESSION_NAME_CACHE._data.clear()

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_adds_session_name_to_files(self, mock_run):
        """Session names are added to file dicts."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "Auto Summary"}',
            stderr="",
        )
        files = [
            {"session_id": "s1"},
            {"session_id": "s2"},
        ]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(files[0]["session_name"], "Auto Summary")
        self.assertEqual(files[1]["session_name"], "Auto Summary")

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_deduplicates_session_ids(self, mock_run):
        """Same session ID is only queried once."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "Auto Summary"}',
            stderr="",
        )
        files = [
            {"session_id": "s1"},
            {"session_id": "s1"},
            {"session_id": "s1"},
        ]
        session_info.enrich_files_with_session_names(files)
        self.assertEqual(mock_run.call_count, 1)
        for f in files:
            self.assertEqual(f["session_name"], "Auto Summary")

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_temp_session_skipped(self, mock_run):
        """Temporary sessions are skipped and stored as None."""
        files = [{"session_id": "(temp)"}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertIsNone(files[0]["session_name"])

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_transient_failure_not_cached(self, mock_run):
        """Transient failures are not cached; retries are allowed."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error",
        )
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["session_name"])
        self.assertEqual(mock_run.call_count, 1)

        # Second refresh should invoke subprocess again because failure was not cached.
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "Recovered Name"}',
            stderr="",
        )
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(files2[0]["session_name"], "Recovered Name")

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_successful_result_cached(self, mock_run):
        """Successful lookups are cached and not re-fetched."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": "Cached Name"}',
            stderr="",
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

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_empty_name_in_valid_json_cached_as_none(self, mock_run):
        """A valid JSON response with missing/empty name is cached as None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"session_name": ""}',
            stderr="",
        )
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        self.assertIsNone(files[0]["session_name"])
        self.assertEqual(mock_run.call_count, 1)

        mock_run.reset_mock()
        files2 = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files2)
        mock_run.assert_not_called()
        self.assertIsNone(files2[0]["session_name"])

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_cache_hit_returns_cached_name(self, mock_run):
        """Cached session name is returned without subprocess call."""
        session_info._SESSION_NAME_CACHE.set("s1", "Cached Name")
        files = [{"session_id": "s1"}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertEqual(files[0]["session_name"], "Cached Name")

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_concurrent_lookup_for_multiple_ids(self, mock_run):
        """Multiple distinct IDs are fetched concurrently."""
        def side_effect(cmd, **kwargs):
            session_id = cmd[-1]
            return MagicMock(
                returncode=0,
                stdout=f'{{"session_name": "Name {session_id}"}}',
                stderr="",
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
        self.assertEqual(mock_run.call_count, 3)

    @patch("cli_topsailai.session_info.subprocess.run")
    def test_missing_session_id_handled(self, mock_run):
        """Files without session_id get None."""
        files = [{}]
        session_info.enrich_files_with_session_names(files)
        mock_run.assert_not_called()
        self.assertIsNone(files[0]["session_name"])


if __name__ == "__main__":
    unittest.main()
