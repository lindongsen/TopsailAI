#!/usr/bin/env python3
"""
Unit tests for utility functions in topsailai.py.

Covers:
- get_topsailai_home()
- format_size()
- format_timestamp()
- format_timestamp_full()
- get_prompt()
- Colors class
"""

import sys
import os
import unittest
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestGetTopsailaiHome(unittest.TestCase):
    """Tests for get_topsailai_home."""

    @patch.dict(os.environ, {"TOPSAILAI_HOME": "/custom/path"})
    @patch("os.path.isdir")
    def test_from_env_var(self, mock_isdir):
        """Resolve from TOPSAILAI_HOME environment variable."""
        mock_isdir.return_value = True
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/custom/path")

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="TOPSAILAI_HOME=/env/file/path\n")
    def test_from_env_file(self, mock_file, mock_isfile, mock_isdir):
        """Resolve from .topsailai/.env file."""
        def isdir_side_effect(path):
            return path == "/env/file/path"
        def isfile_side_effect(path):
            return ".topsailai/.env" in path
        mock_isdir.side_effect = isdir_side_effect
        mock_isfile.side_effect = isfile_side_effect
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/env/file/path")

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    def test_default_path(self, mock_isfile, mock_isdir):
        """Fall back to default 'os.path.join(os.environ["HOME"], ".topsailai")'"""
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        result = cli.get_topsailai_home()
        self.assertEqual(result, os.path.join(os.environ["HOME"], ".topsailai"))

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    def test_default_not_exist(self, mock_isfile, mock_isdir):
        """Return default even if it does not exist."""
        mock_isfile.return_value = False
        mock_isdir.return_value = False
        result = cli.get_topsailai_home()
        self.assertEqual(result, os.path.join(os.environ["HOME"], ".topsailai"))

    @patch.dict(os.environ, {"TOPSAILAI_HOME": "/invalid/path"})
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_env_var_invalid_fallback(self, mock_file, mock_isfile, mock_isdir):
        """Fallback when env var points to invalid directory."""
        mock_isdir.return_value = False
        mock_isfile.return_value = False
        result = cli.get_topsailai_home()
        self.assertEqual(result, os.path.join(os.environ["HOME"], ".topsailai"))

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open, read_data="OTHER_VAR=value\n")
    def test_env_file_no_home_var(self, mock_file, mock_isfile, mock_isdir):
        """Fallback when .env file has no TOPSAILAI_HOME."""
        mock_isfile.return_value = True
        mock_isdir.return_value = True
        result = cli.get_topsailai_home()
        self.assertEqual(result, os.path.join(os.environ["HOME"], ".topsailai"))


class TestFormatSize(unittest.TestCase):
    """Tests for format_size."""

    def test_bytes(self):
        """Format size in bytes."""
        self.assertEqual(cli.format_size(0), "0B")
        self.assertEqual(cli.format_size(512), "512B")

    def test_kilobytes(self):
        """Format size in kilobytes."""
        self.assertEqual(cli.format_size(1024), "1.0K")
        self.assertEqual(cli.format_size(1536), "1.5K")

    def test_megabytes(self):
        """Format size in megabytes."""
        self.assertEqual(cli.format_size(1024 * 1024), "1.0M")
        self.assertEqual(cli.format_size(2.5 * 1024 * 1024), "2.5M")

    def test_gigabytes(self):
        """Format size in gigabytes."""
        self.assertEqual(cli.format_size(1024 * 1024 * 1024), "1.0G")
        self.assertEqual(cli.format_size(3.5 * 1024 * 1024 * 1024), "3.5G")


class TestFormatTimestamp(unittest.TestCase):
    """Tests for format_timestamp and format_timestamp_full."""

    def test_format_timestamp(self):
        """Format timestamp to short form."""
        import time
        ts = time.mktime((2026, 5, 19, 14, 30, 0, 0, 0, 0))
        result = cli.format_timestamp(ts)
        self.assertEqual(result, "05-19 14:30")

    def test_format_timestamp_full(self):
        """Format timestamp to full form."""
        import time
        ts = time.mktime((2026, 5, 19, 14, 30, 0, 0, 0, 0))
        result = cli.format_timestamp_full(ts)
        self.assertEqual(result, "2026-05-19 14:30:00")


class TestGetPrompt(unittest.TestCase):
    """Tests for get_prompt."""

    def test_workspace_prompt(self):
        """Prompt in workspace scope."""
        cli.current_scope = "workspace"
        cli.current_session_id = None
        result = cli.get_prompt()
        self.assertIn("[workspace]", result)
        self.assertIn(">", result)

    def test_session_prompt(self):
        """Prompt in session scope."""
        cli.current_scope = "session"
        cli.current_session_id = "my-session"
        result = cli.get_prompt()
        self.assertIn("[session:my-session]", result)
        self.assertIn(">", result)


class TestColors(unittest.TestCase):
    """Tests for Colors class constants."""

    def test_color_constants(self):
        """All color constants are non-empty strings."""
        self.assertTrue(hasattr(cli.Colors, "RESET"))
        self.assertTrue(hasattr(cli.Colors, "BOLD"))
        self.assertTrue(hasattr(cli.Colors, "RED"))
        self.assertTrue(hasattr(cli.Colors, "GREEN"))
        self.assertTrue(hasattr(cli.Colors, "YELLOW"))
        self.assertTrue(hasattr(cli.Colors, "BLUE"))
        self.assertTrue(hasattr(cli.Colors, "CYAN"))
        self.assertTrue(hasattr(cli.Colors, "GRAY"))
        self.assertTrue(cli.Colors.RESET.startswith("\033["))


if __name__ == "__main__":
    unittest.main()
