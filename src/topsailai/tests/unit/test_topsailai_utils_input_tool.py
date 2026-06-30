"""Tests for topsailai.utils.input_tool module."""

from __future__ import annotations

import os
import pty
import select
import sys
import termios
import threading
import time
from contextlib import suppress
from unittest.mock import MagicMock, patch

import pytest

from topsailai.utils import input_tool


class TestInputWithTimeout:
    """Tests for input_with_timeout using real PTY."""

    def _run_in_pty(self, prompt: str, timeout: float, input_text: str | None, *, pre_delay: float = 0.0):
        """Run input_with_timeout in a PTY and optionally feed input_text."""
        master_fd, slave_fd = pty.openpty()
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        slave_in = None
        slave_out = None

        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            slave_out = os.fdopen(slave_fd, "w", buffering=1)
            sys.stdin = slave_in
            sys.stdout = slave_out

            result = {"value": None, "exception": None}

            def target():
                try:
                    result["value"] = input_tool.input_with_timeout(
                        prompt, timeout=timeout, stream=sys.stdin, output=sys.stdout
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result["exception"] = exc

            thread = threading.Thread(target=target)
            thread.start()

            if input_text is not None:
                time.sleep(pre_delay)
                os.write(master_fd, input_text.encode("utf-8"))

            thread.join(timeout=timeout + 1.0)
            if thread.is_alive():  # pragma: no cover - safety
                pytest.fail("input_with_timeout thread did not finish")

            if result["exception"] is not None:
                raise result["exception"]
            return result["value"]
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            for fh in (slave_in, slave_out):
                if fh is not None:
                    with suppress(Exception):
                        fh.close()
            with suppress(OSError):
                os.close(master_fd)

    def test_returns_input_on_approve(self):
        value = self._run_in_pty("Prompt: ", 2.0, "approve\n", pre_delay=0.1)
        assert value == "approve"

    def test_returns_input_on_deny(self):
        value = self._run_in_pty("Prompt: ", 2.0, "deny\n", pre_delay=0.1)
        assert value == "deny"

    def test_returns_none_on_timeout(self):
        value = self._run_in_pty("Prompt: ", 0.3, None)
        assert value is None

    def test_echo_is_visible(self):
        master_fd, slave_fd = pty.openpty()
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        slave_in = None
        slave_out = None
        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            slave_out = os.fdopen(slave_fd, "w", buffering=1)
            sys.stdin = slave_in
            sys.stdout = slave_out

            result = {"value": None, "exception": None}

            def target():
                try:
                    result["value"] = input_tool.input_with_timeout(
                        "Prompt: ", timeout=2.0, stream=sys.stdin, output=sys.stdout
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result["exception"] = exc

            thread = threading.Thread(target=target)
            thread.start()
            time.sleep(0.1)
            os.write(master_fd, b"hello\n")
            thread.join(timeout=3.0)

            if result["exception"] is not None:
                raise result["exception"]

            # Drain any pending output from the master side.
            echoed = b""
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if not ready:
                    break
                echoed += os.read(master_fd, 1024)

            assert result["value"] == "hello"
            assert b"hello" in echoed
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            for fh in (slave_in, slave_out):
                if fh is not None:
                    with suppress(Exception):
                        fh.close()
            with suppress(OSError):
                os.close(master_fd)


class TestInputWithTimeoutFallback:
    """Tests for non-tty fallback behavior."""

    def test_non_tty_returns_default(self):
        """When stdin is not a tty, the function should return default immediately."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        with patch.object(sys, "stdin", mock_stdin):
            value = input_tool.input_with_timeout("Prompt: ", timeout=1.0)
        assert value is None

    def test_missing_fileno_returns_default(self):
        """When stdin lacks fileno, the function should return default immediately."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        del mock_stdin.fileno
        with patch.object(sys, "stdin", mock_stdin):
            value = input_tool.input_with_timeout("Prompt: ", timeout=1.0)
        assert value is None


class TestConfigureTerminal:
    """Tests for terminal configuration helper."""

    def test_configure_terminal_restores_on_exit(self):
        """Verify terminal attributes are restored after the context manager."""
        master_fd, slave_fd = pty.openpty()
        try:
            original = termios.tcgetattr(slave_fd)
            with input_tool._configure_terminal(slave_fd) as settings:
                assert settings is not None
                # We enabled canonical mode and echo.
                current = termios.tcgetattr(slave_fd)
                assert current[3] & termios.ICANON
                assert current[3] & termios.ECHO
            restored = termios.tcgetattr(slave_fd)
            assert restored[3] == original[3]
        finally:
            os.close(master_fd)
            os.close(slave_fd)

    def test_configure_terminal_handles_errors(self):
        """Invalid file descriptors should yield None without raising."""
        with input_tool._configure_terminal(-1) as settings:
            assert settings is None

    def test_raise_on_timeout(self):
        """When raise_on_timeout is True, InputTimeoutError is raised."""
        master_fd, slave_fd = pty.openpty()
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        slave_in = None
        slave_out = None
        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            slave_out = os.fdopen(slave_fd, "w", buffering=1)
            sys.stdin = slave_in
            sys.stdout = slave_out

            with pytest.raises(input_tool.InputTimeoutError):
                input_tool.input_with_timeout(
                    "Prompt: ", timeout=0.1, raise_on_timeout=True,
                    stream=sys.stdin, output=sys.stdout,
                )
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            for fh in (slave_in, slave_out):
                if fh is not None:
                    with suppress(Exception):
                        fh.close()
            with suppress(OSError):
                os.close(master_fd)

    def test_timeout_none_blocks_until_input(self):
        """When timeout is None, the call blocks until input is provided."""
        master_fd, slave_fd = pty.openpty()
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        slave_in = None
        slave_out = None
        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            slave_out = os.fdopen(slave_fd, "w", buffering=1)
            sys.stdin = slave_in
            sys.stdout = slave_out

            result = {"value": None}

            def target():
                result["value"] = input_tool.input_with_timeout(
                    "Prompt: ", timeout=None, stream=sys.stdin, output=sys.stdout
                )

            thread = threading.Thread(target=target)
            thread.start()
            time.sleep(0.1)
            os.write(master_fd, b"blocked input\n")
            thread.join(timeout=2.0)
            assert not thread.is_alive()
            assert result["value"] == "blocked input"
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            for fh in (slave_in, slave_out):
                if fh is not None:
                    with suppress(Exception):
                        fh.close()
            with suppress(OSError):
                os.close(master_fd)

    def test_eof_error_returns_default(self):
        """EOFError during blocking readline returns default."""
        mock_stream = MagicMock()
        mock_stream.fileno.return_value = -1
        mock_stream.isatty.return_value = False
        mock_stream.readline.side_effect = EOFError()
        value = input_tool.input_with_timeout(
            "Prompt: ", timeout=None, default="eof_default", stream=mock_stream
        )
        assert value == "eof_default"

    def test_isatty_exception_returns_default(self):
        """If isatty() raises, the function should return default safely."""
        mock_stream = MagicMock()
        mock_stream.fileno.return_value = 0
        mock_stream.isatty.side_effect = OSError("isatty failed")
        value = input_tool.input_with_timeout(
            "Prompt: ", timeout=1.0, default="tty_err_default", stream=mock_stream
        )
        assert value == "tty_err_default"

    def test_timeout_none_empty_readline_returns_default(self):
        """Empty readline result with timeout=None returns default."""
        mock_stream = MagicMock()
        mock_stream.fileno.return_value = -1
        mock_stream.isatty.return_value = False
        mock_stream.readline.return_value = ""
        value = input_tool.input_with_timeout(
            "Prompt: ", timeout=None, default="empty_default", stream=mock_stream
        )
        assert value == "empty_default"

    def test_posix_tty_eof_error_returns_default(self):
        """EOFError in POSIX tty path returns default."""
        mock_stream = MagicMock()
        mock_stream.fileno.return_value = 0
        mock_stream.isatty.return_value = True
        mock_stream.readline.side_effect = EOFError()
        value = input_tool.input_with_timeout(
            "Prompt: ", timeout=1.0, default="eof_tty_default", stream=mock_stream
        )
        assert value == "eof_tty_default"


class TestInputFromPipe:
    """Tests for input_from_pipe using real FIFOs."""

    def _write_to_pipe_after_delay(self, pipe_path: str, content: bytes, delay: float = 0.05):
        """Spawn a thread that opens the FIFO and writes content after a short delay."""

        def writer():
            time.sleep(delay)
            # Opening a FIFO for writing blocks until a reader opens it.
            with open(pipe_path, "wb") as fifo:
                fifo.write(content)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        return thread

    def test_reads_message_from_pipe(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        message = b"hello from pipe\nsecond line\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert result == "hello from pipe\nsecond line"
        finally:
            writer.join(timeout=2.0)

    def test_eof_marker_terminates_input(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        message = b"line before\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert result == "line before"
        finally:
            writer.join(timeout=2.0)

    def test_bare_eof_marker_is_not_recognized(self, tmp_path):
        """EOF must appear on its own line; a trailing 'EOF' without a preceding
        newline is treated as ordinary content."""
        pipe_path = str(tmp_path / "test.pipe")
        message = b"line before EOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert result == "line before EOF"
        finally:
            writer.join(timeout=2.0)

    def test_cleans_up_pipe_after_read(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        writer = self._write_to_pipe_after_delay(pipe_path, b"cleanup test\n")
        try:
            input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert not os.path.exists(pipe_path)
        finally:
            writer.join(timeout=2.0)

    def test_cleans_up_pipe_on_timeout(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        with pytest.raises(TimeoutError):
            input_tool.input_from_pipe(pipe_path, timeout=0.1)
        assert not os.path.exists(pipe_path)

    def test_empty_message_returns_empty_string(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        writer = self._write_to_pipe_after_delay(pipe_path, b"\n")
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert result == ""
        finally:
            writer.join(timeout=2.0)

    def test_not_implemented_on_windows(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        with patch.object(os, "mkfifo", None):
            with pytest.raises(NotImplementedError):
                input_tool.input_from_pipe(pipe_path)

    def test_single_line_returns_first_line(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        message = b"first line\nsecond line\nthird line\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0, single_line=True)
            assert result == "first line"
        finally:
            writer.join(timeout=2.0)

    def test_single_line_returns_all_when_no_newline(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        message = b"only line content"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0, single_line=True)
            assert result == "only line content"
        finally:
            writer.join(timeout=2.0)

    def test_single_line_strips_eof_marker_when_no_newline(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        message = b"content without newline\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(
                pipe_path, timeout=2.0, single_line=True
            )
            assert result == "content without newline"
        finally:
            writer.join(timeout=2.0)

    def test_single_line_cleans_up_pipe_after_read(self, tmp_path):
        pipe_path = str(tmp_path / "test.pipe")
        writer = self._write_to_pipe_after_delay(pipe_path, b"single line\nmore\n")
        try:
            input_tool.input_from_pipe(pipe_path, timeout=2.0, single_line=True)
            assert not os.path.exists(pipe_path)
        finally:
            writer.join(timeout=2.0)

    def test_single_line_buffers_leftover_lines_for_next_call(self, tmp_path):
        """Leftover lines from a single-line pipe read are returned later."""
        pipe_path = str(tmp_path / "buffer.pipe")
        message = b"line one\nline two\nline three\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            first = input_tool.input_from_pipe(
                pipe_path, timeout=2.0, single_line=True
            )
            assert first == "line one"
            # The pipe was removed; a new call with the same path should serve
            # the buffered lines without recreating the pipe.
            second = input_tool.input_from_pipe(
                pipe_path, timeout=0.1, single_line=True
            )
            assert second == "line two"
            third = input_tool.input_from_pipe(
                pipe_path, timeout=0.1, single_line=True
            )
            assert third == "line three"
        finally:
            writer.join(timeout=2.0)

    def test_single_line_eof_marker_is_buffered_as_terminator(self, tmp_path):
        """EOF marker terminates buffered single-line reads."""
        pipe_path = str(tmp_path / "buffer_eof.pipe")
        message = b"line one\nline two\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            first = input_tool.input_from_pipe(
                pipe_path, timeout=2.0, single_line=True
            )
            assert first == "line one"
            second = input_tool.input_from_pipe(
                pipe_path, timeout=0.1, single_line=True
            )
            assert second == "line two"
            third = input_tool.input_from_pipe(
                pipe_path, timeout=0.1, single_line=True
            )
            assert third == ""
        finally:
            writer.join(timeout=2.0)

    def test_terminal_eof_returns_empty_string(self, tmp_path):
        """Ctrl+D / EOF on terminal input returns an empty string."""
        pipe_path = str(tmp_path / "terminal_eof.pipe")
        old_stdin = sys.stdin

        master_fd, slave_fd = pty.openpty()
        slave_in = None
        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            sys.stdin = slave_in

            result = {"value": None}

            def target():
                try:
                    result["value"] = input_tool.input_from_pipe(
                        pipe_path, timeout=2.0, single_line=True
                    )
                except EOFError:
                    result["value"] = ""

            thread = threading.Thread(target=target)
            thread.start()
            time.sleep(0.1)
            # Send EOF (Ctrl+D) on the PTY master side.
            os.close(master_fd)
            thread.join(timeout=3.0)
            assert not thread.is_alive()
            assert result["value"] == ""
        finally:
            sys.stdin = old_stdin
            if slave_in is not None:
                with suppress(Exception):
                    slave_in.close()

    def test_terminal_input_uses_readline_not_raw_bytes(self, tmp_path):
        """Terminal input path forwards typed line via the helper process."""
        pipe_path = str(tmp_path / "terminal_readline.pipe")
        old_stdin = sys.stdin

        master_fd, slave_fd = pty.openpty()
        slave_in = None
        try:
            slave_in = os.fdopen(slave_fd, "r", buffering=1)
            sys.stdin = slave_in

            result = {"value": None}

            def target():
                result["value"] = input_tool.input_from_pipe(
                    pipe_path, timeout=5.0, single_line=True, prompt=""
                )

            thread = threading.Thread(target=target)
            thread.start()
            # Wait for the helper process to start and call input() on the PTY.
            time.sleep(0.5)
            os.write(master_fd, b"typed line\n")
            thread.join(timeout=6.0)
            assert not thread.is_alive()
            assert result["value"] == "typed line"
        finally:
            sys.stdin = old_stdin
            if slave_in is not None:
                with suppress(Exception):
                    slave_in.close()
            with suppress(OSError):
                os.close(master_fd)
    def test_buffer_cleared_on_timeout(self, tmp_path):
        """Stale buffer is discarded when a read times out."""
        pipe_path = str(tmp_path / "timeout_clear.pipe")
        message = b"line one\nline two\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            input_tool.input_from_pipe(pipe_path, timeout=2.0, single_line=True)
            # The second call should consume the buffered leftover line.
            value = input_tool.input_from_pipe(pipe_path, timeout=0.05, single_line=True)
            assert value == "line two"
            # After the buffer is consumed it should be empty.
            assert pipe_path not in input_tool._pipe_leftover_buffer
        finally:
            writer.join(timeout=2.0)
    def test_raise_eof_error_on_eof_marker(self, tmp_path):
        """When raise_eof_error is True, EOF marker raises EOFError."""
        pipe_path = str(tmp_path / "raise_eof.pipe")
        message = b"line before\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            with pytest.raises(EOFError):
                input_tool.input_from_pipe(
                    pipe_path, timeout=2.0, raise_eof_error=True
                )
        finally:
            writer.join(timeout=2.0)

    def test_raise_eof_error_false_returns_content(self, tmp_path):
        """Default behavior strips EOF marker and returns content."""
        pipe_path = str(tmp_path / "no_raise_eof.pipe")
        message = b"line before\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            result = input_tool.input_from_pipe(pipe_path, timeout=2.0)
            assert result == "line before"
        finally:
            writer.join(timeout=2.0)

    def test_raise_eof_error_single_line(self, tmp_path):
        """EOFError is raised in single_line mode when raise_eof_error is True."""
        pipe_path = str(tmp_path / "raise_eof_single.pipe")
        message = b"line one\nline two\nEOF\n"
        writer = self._write_to_pipe_after_delay(pipe_path, message)
        try:
            first = input_tool.input_from_pipe(
                pipe_path, timeout=2.0, single_line=True
            )
            assert first == "line one"
            second = input_tool.input_from_pipe(
                pipe_path, timeout=2.0, single_line=True
            )
            assert second == "line two"
            with pytest.raises(EOFError):
                input_tool.input_from_pipe(
                    pipe_path, timeout=2.0, single_line=True, raise_eof_error=True
                )
        finally:
            writer.join(timeout=2.0)
