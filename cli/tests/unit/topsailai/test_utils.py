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
    def test_from_env_var(self):
        """Resolve from TOPSAILAI_HOME environment variable."""
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/custom/path")

    @patch.dict(os.environ, {"TOPSAILAI_HOME": "~/relative/path", "HOME": "/home/user"})
    def test_from_env_var_with_tilde(self):
        """Expand ~ in TOPSAILAI_HOME environment variable."""
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/home/user/relative/path")

    @patch.dict(os.environ, {"TOPSAILAI_HOME": "relative/path"}, clear=True)
    def test_from_env_var_relative(self):
        """Convert relative TOPSAILAI_HOME to absolute path."""
        result = cli.get_topsailai_home()
        self.assertTrue(os.path.isabs(result))
        self.assertTrue(result.endswith("relative/path"))

    @patch.dict(os.environ, {}, clear=True)
    def test_default_path(self):
        """Fall back to default ~/.topsailai when HOME is set."""
        with patch.dict(os.environ, {"HOME": "/home/user"}):
            result = cli.get_topsailai_home()
            self.assertEqual(result, "/home/user/.topsailai")

    @patch.dict(os.environ, {}, clear=True)
    def test_fallback_no_home(self):
        """Fall back to /topsailai when neither TOPSAILAI_HOME nor HOME is set."""
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/topsailai")

    @patch.dict(os.environ, {"TOPSAILAI_HOME": "/invalid/path"})
    def test_env_var_invalid_not_fallback(self):
        """Use env var value even if the directory does not exist."""
        result = cli.get_topsailai_home()
        self.assertEqual(result, "/invalid/path")

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
