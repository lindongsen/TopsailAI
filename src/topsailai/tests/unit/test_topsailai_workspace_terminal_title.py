"""
Unit tests for workspace/terminal_title module.

Test coverage:
- get_host_name: short hostname resolution
- build_title: format string expansion and fallback behavior
- set_terminal_title: TTY detection, caching, disable switch, POSIX output
- refresh_terminal_title: session name resolution and failure isolation
"""

import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from topsailai.workspace import terminal_title


class TTYStringIO(io.StringIO):
    """StringIO subclass that claims to be a TTY."""

    def isatty(self):
        return True


class NonTTYStringIO(io.StringIO):
    """StringIO subclass that claims not to be a TTY."""

    def isatty(self):
        return False


class TestGetHostName(unittest.TestCase):
    """Tests for get_host_name."""

    def test_returns_short_hostname(self):
        """Should return the hostname without domain suffix."""
        with patch("socket.gethostname", return_value="myhost.example.com"):
            result = terminal_title.get_host_name()
        self.assertEqual(result, "myhost")

    def test_returns_unknown_on_failure(self):
        """Should return 'unknown' when socket.gethostname fails."""
        with patch("socket.gethostname", side_effect=OSError("fail")):
            result = terminal_title.get_host_name()
        self.assertEqual(result, "unknown")


class TestBuildTitle(unittest.TestCase):
    """Tests for build_title."""

    def test_default_format(self):
        """Default format should produce host_name:session_name."""
        with patch.object(terminal_title, "get_host_name", return_value="myhost"):
            result = terminal_title.build_title(session_name="my-session")
        self.assertEqual(result, "myhost:my-session")

    def test_session_name_falls_back_to_session_id(self):
        """Empty session_name should fall back to session_id."""
        with patch.object(terminal_title, "get_host_name", return_value="myhost"):
            result = terminal_title.build_title(session_name="", session_id="sid-123")
        self.assertEqual(result, "myhost:sid-123")

    def test_session_name_and_id_fallback_to_empty(self):
        """Empty session_name and session_id should produce host_name:."""
        with patch.object(terminal_title, "get_host_name", return_value="myhost"):
            result = terminal_title.build_title(session_name="", session_id="")
        self.assertEqual(result, "myhost:")

    def test_custom_format(self):
        """Custom format should expand all placeholders."""
        os.environ["TOPSAILAI_TERMINAL_TITLE_FORMAT"] = "[{session_id}] {host_name}"
        try:
            with patch.object(terminal_title, "get_host_name", return_value="myhost"):
                result = terminal_title.build_title(
                    session_name="my-session", session_id="sid-123"
                )
            self.assertEqual(result, "[sid-123] myhost")
        finally:
            del os.environ["TOPSAILAI_TERMINAL_TITLE_FORMAT"]


class TestSetTerminalTitle(unittest.TestCase):
    """Tests for set_terminal_title."""

    def tearDown(self):
        """Reset cached title and environment after each test."""
        terminal_title._last_title = None
        for key in ["TOPSAILAI_TERMINAL_TITLE_ENABLED", "TOPSAILAI_INTERACTIVE_MODE"]:
            if key in os.environ:
                del os.environ[key]

    def test_disabled_returns_false(self):
        """When disabled, set_terminal_title should return False."""
        os.environ["TOPSAILAI_TERMINAL_TITLE_ENABLED"] = "0"
        result = terminal_title.set_terminal_title("title")
        self.assertFalse(result)

    def test_empty_title_returns_false(self):
        """Empty title should return False."""
        result = terminal_title.set_terminal_title("")
        self.assertFalse(result)

    def test_non_tty_returns_false(self):
        """Non-TTY stdout should skip the update."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = NonTTYStringIO()
        with patch.object(sys, "stdout", fake_stdout):
            result = terminal_title.set_terminal_title("title")
        self.assertFalse(result)

    def test_non_interactive_returns_false(self):
        """Non-interactive mode should skip the update."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "0"
        fake_stdout = TTYStringIO()
        with patch.object(sys, "stdout", fake_stdout):
            result = terminal_title.set_terminal_title("title")
        self.assertFalse(result)

    @patch("sys.platform", "linux")
    def test_posix_tty_writes_osc_sequence(self):
        """POSIX TTY should write the OSC escape sequence."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        with patch.object(sys, "stdout", fake_stdout):
            result = terminal_title.set_terminal_title("myhost:my-session")
        self.assertTrue(result)
        self.assertEqual(fake_stdout.getvalue(), "\033]0;myhost:my-session\007")

    @patch("sys.platform", "linux")
    def test_same_title_is_cached(self):
        """Setting the same title twice should skip the second write."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        with patch.object(sys, "stdout", fake_stdout):
            terminal_title.set_terminal_title("myhost:my-session")
            result = terminal_title.set_terminal_title("myhost:my-session")
        self.assertTrue(result)
        self.assertEqual(fake_stdout.getvalue().count("\033]0;"), 1)

    @patch("sys.platform", "win32")
    def test_windows_uses_set_console_title(self):
        """Windows should call SetConsoleTitleW."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        mock_kernel32 = MagicMock()
        mock_kernel32.SetConsoleTitleW.return_value = 1

        def fake_set_title_windows(title: str) -> bool:
            mock_kernel32.SetConsoleTitleW(title)
            return True

        with patch.object(sys, "stdout", fake_stdout):
            with patch.object(
                terminal_title, "_set_title_windows", fake_set_title_windows
            ):
                result = terminal_title.set_terminal_title("myhost:my-session")
        self.assertTrue(result)
        mock_kernel32.SetConsoleTitleW.assert_called_once_with("myhost:my-session")

    def test_write_failure_is_swallowed(self):
        """A write failure must not propagate; it returns False."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        fake_stdout.flush = MagicMock(side_effect=OSError("flush failed"))
        with patch.object(sys, "stdout", fake_stdout):
            result = terminal_title.set_terminal_title("myhost:my-session")
        self.assertFalse(result)


class TestRefreshTerminalTitle(unittest.TestCase):
    """Tests for refresh_terminal_title."""

    def tearDown(self):
        """Reset cached title and environment after each test."""
        terminal_title._last_title = None
        for key in ["TOPSAILAI_TERMINAL_TITLE_ENABLED", "TOPSAILAI_INTERACTIVE_MODE"]:
            if key in os.environ:
                del os.environ[key]

    @patch("sys.platform", "linux")
    def test_uses_provided_session_name(self):
        """When session_name is provided, it should be used directly."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        with patch.object(sys, "stdout", fake_stdout):
            with patch.object(terminal_title, "get_host_name", return_value="myhost"):
                result = terminal_title.refresh_terminal_title(
                    session_id="sid-123", session_name="my-session"
                )
        self.assertTrue(result)
        self.assertEqual(fake_stdout.getvalue(), "\033]0;myhost:my-session\007")

    @patch("sys.platform", "linux")
    def test_reads_session_name_from_manager(self):
        """When session_name is empty, read it from the session manager."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        fake_session = MagicMock()
        fake_session.session_name = "managed-session"
        fake_mgr = MagicMock()
        fake_mgr.get_session.return_value = fake_session

        with patch.object(sys, "stdout", fake_stdout):
            with patch.object(terminal_title, "get_host_name", return_value="myhost"):
                with patch(
                    "topsailai.context.ctx_manager.get_session_manager",
                    return_value=fake_mgr,
                ):
                    result = terminal_title.refresh_terminal_title(session_id="sid-123")
        self.assertTrue(result)
        self.assertEqual(fake_stdout.getvalue(), "\033]0;myhost:managed-session\007")

    @patch("sys.platform", "linux")
    def test_session_manager_failure_is_swallowed(self):
        """Session manager failures must not interrupt the caller."""
        os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "1"
        fake_stdout = TTYStringIO()
        fake_mgr = MagicMock()
        fake_mgr.get_session.side_effect = RuntimeError("db locked")

        with patch.object(sys, "stdout", fake_stdout):
            with patch.object(terminal_title, "get_host_name", return_value="myhost"):
                with patch(
                    "topsailai.context.ctx_manager.get_session_manager",
                    return_value=fake_mgr,
                ):
                    result = terminal_title.refresh_terminal_title(session_id="sid-123")
        self.assertTrue(result)
        self.assertEqual(fake_stdout.getvalue(), "\033]0;myhost:sid-123\007")

    def test_disabled_returns_false(self):
        """When disabled, refresh should return False without writing."""
        os.environ["TOPSAILAI_TERMINAL_TITLE_ENABLED"] = "0"
        result = terminal_title.refresh_terminal_title(session_id="sid-123")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
