"""
Unit tests for the tool approval transport layer.
"""

import errno
import fcntl
import io
import os
import pty
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from topsailai.workspace.input_tool import input_from_pipe_session
from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance
from topsailai.ai_base.tool_approval.transport import (
    ApprovalTransport,
    LocalApprovalTransport,
)


class TestLocalApprovalTransport:
    """Tests for the default local transport."""

    def test_send_request_stores_instance(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        assert transport.get_request(timeout=0.1) is instance

    def test_wait_response_returns_approved(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)

        def resolve_later():
            time.sleep(0.05)
            instance.approve()

        threading.Thread(target=resolve_later).start()
        status = transport.wait_response(instance, timeout=1.0)
        assert status == instance.STATUS_APPROVED

    def test_wait_response_times_out(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=0.05)
        assert status == instance.STATUS_TIMEOUT

    def test_wait_response_indefinite(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)

        def resolve_later():
            time.sleep(0.05)
            instance.approve()

        threading.Thread(target=resolve_later).start()
        status = transport.wait_response(instance, timeout=None)
        assert status == instance.STATUS_APPROVED

    def test_wait_response_zero_timeout(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=0)
        assert status == instance.STATUS_TIMEOUT

    def test_get_request_with_timeout(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        retrieved = transport.get_request(timeout=0.5)
        assert retrieved is instance

    def test_get_request_timeout_returns_none(self):
        transport = LocalApprovalTransport()
        retrieved = transport.get_request(timeout=0.05)
        assert retrieved is None

    def test_resolve_approve(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        from topsailai.ai_base.tool_approval import registry

        registry.register_pending_approval(instance)
        try:
            result = transport.resolve(instance.id, True)
            assert result is True
            assert instance.status == instance.STATUS_APPROVED
        finally:
            registry.unregister_pending_approval(instance.id)

    def test_resolve_deny(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        from topsailai.ai_base.tool_approval import registry

        registry.register_pending_approval(instance)
        try:
            result = transport.resolve(instance.id, False)
            assert result is True
            assert instance.status == instance.STATUS_DENIED
        finally:
            registry.unregister_pending_approval(instance.id)

    def test_resolve_missing_instance(self):
        transport = LocalApprovalTransport()
        result = transport.resolve("missing", True)
        assert result is False

    def test_reset_instance(self):
        first = LocalApprovalTransport.get_instance()
        LocalApprovalTransport.reset_instance()
        second = LocalApprovalTransport.get_instance()
        assert first is not second

    def _run_stdin_thread_with_pty(self, input_text: str, timeout: float = 1.0):
        """
        Create a real PTY, feed *input_text* to it, and run the local transport
        stdin reader against the PTY's slave side.

        Returns the resolved status of the instance and any bytes echoed back to
        the PTY master (used to verify terminal echo is enabled).
        """
        master_fd, slave_fd = pty.openpty()
        try:
            # Make the master non-blocking so we can drain it later.
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            slave_in = os.fdopen(slave_fd, "r")
            stdout_capture = io.StringIO()

            transport = LocalApprovalTransport()
            instance = ToolApprovalInstance(
                "cmd_tool-exec_cmd", {}, transport=transport
            )
            instance.timeout = timeout

            with patch.object(sys, "stdin", slave_in), patch.object(
                sys, "stdout", stdout_capture
            ):
                transport.send_request(instance)
                # Give the stdin reader thread a moment to start and configure
                # the terminal before we feed input.
                time.sleep(0.05)
                if input_text:
                    os.write(master_fd, input_text.encode())
                status = transport.wait_response(instance, timeout=timeout + 0.5)

            # Drain any bytes echoed by the terminal (the input itself).
            echoed = b""
            deadline = time.monotonic() + 0.2
            while time.monotonic() < deadline:
                try:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        echoed += chunk
                    else:
                        break
                except BlockingIOError:
                    time.sleep(0.01)

            return status, echoed
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                slave_in.close()
            except OSError:
                pass

    def test_stdin_thread_approve(self):
        status, echoed = self._run_stdin_thread_with_pty("approve\n")
        assert status == ToolApprovalInstance.STATUS_APPROVED
        assert b"approve" in echoed

    def test_stdin_thread_deny(self):
        status, echoed = self._run_stdin_thread_with_pty("deny\n")
        assert status == ToolApprovalInstance.STATUS_DENIED
        assert b"deny" in echoed

    def test_stdin_thread_unrecognized_defaults_to_deny(self):
        status, echoed = self._run_stdin_thread_with_pty("maybe\n")
        assert status == ToolApprovalInstance.STATUS_DENIED
        assert b"maybe" in echoed

    def test_stdin_thread_timeout(self):
        status, echoed = self._run_stdin_thread_with_pty("", timeout=0.2)
        assert status == ToolApprovalInstance.STATUS_TIMEOUT

    def test_stdin_thread_not_started_when_non_interactive(self, monkeypatch):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=0.05)
        assert status == instance.STATUS_TIMEOUT


class TestApprovalTransportInterface:
    """Tests for the abstract transport interface."""

    def test_subclass_must_implement(self):
        class BrokenTransport(ApprovalTransport):
            pass

        with pytest.raises(TypeError):
            BrokenTransport()

    def test_minimal_subclass(self):
        class MinimalTransport(ApprovalTransport):
            def send_request(self, instance):
                pass

            def wait_response(self, instance, timeout=None):
                return instance.status

            def on_resolved(self, instance):
                pass

            def supports_external_resolution(self):
                return False

        transport = MinimalTransport()
        assert transport.supports_external_resolution() is False


class TestLocalApprovalTransportTimeoutWrapper:
    """Tests verifying the timeout-aware agent-runtime input wrapper is used."""

    @pytest.fixture(autouse=True)
    def _clear_thread_local(self):
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()
        yield
        rid_all_thread_vars()

    def _write_to_pipe(self, pipe_path, payload, delay=0.02):
        """Start a daemon thread that writes payload to a FIFO after delay."""

        def writer():
            time.sleep(delay)
            fd = None
            for _ in range(200):
                try:
                    fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                    break
                except FileNotFoundError:
                    time.sleep(0.01)
                except OSError as exc:
                    if exc.errno == errno.ENXIO:
                        time.sleep(0.01)
                    else:
                        raise
            if fd is None:
                return
            try:
                os.write(fd, payload.encode())
            finally:
                os.close(fd)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        return thread

    def test_read_stdin_input_uses_timeout_wrapper(self, monkeypatch):
        """_read_stdin_input applies the registered timeout wrapper."""
        from topsailai.utils import env_tool
        from topsailai.utils.thread_local_tool import (
            set_agent_runtime_input_with_timeout,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK", tmpdir
            )

            session_id = env_tool.get_session_id() or "topsailai"
            pipe_path = os.path.join(
                tmpdir, f"{session_id}.{os.getpid()}.session.pipe"
            )

            writer_thread = self._write_to_pipe(
                pipe_path, "approve\nEOF\n", delay=0.02
            )

            def input_func(prompt, timeout):
                return input_from_pipe_session(
                    session_id=env_tool.get_session_id(),
                    single_line=True,
                    timeout=timeout,
                    prompt=prompt,
                )

            set_agent_runtime_input_with_timeout(input_func)

            transport = LocalApprovalTransport()
            instance = ToolApprovalInstance(
                "cmd_tool-exec_cmd", {}, transport=transport
            )
            instance.timeout = 1.0

            start = time.monotonic()
            transport._read_stdin_input(instance, input_func=input_func)
            elapsed = time.monotonic() - start

            assert instance.status == instance.STATUS_APPROVED
            assert elapsed < 0.5
            writer_thread.join(timeout=0.5)

    def test_read_stdin_input_timeout_wrapper_times_out(self, monkeypatch):
        """_read_stdin_input raises TimeoutError when no data arrives."""
        from topsailai.utils import env_tool
        from topsailai.utils.thread_local_tool import (
            set_agent_runtime_input_with_timeout,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(
                "topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK", tmpdir
            )

            def input_func(prompt, timeout):
                return input_from_pipe_session(
                    session_id=env_tool.get_session_id(),
                    single_line=True,
                    timeout=timeout,
                    prompt=prompt,
                )

            set_agent_runtime_input_with_timeout(input_func)

            transport = LocalApprovalTransport()
            instance = ToolApprovalInstance(
                "cmd_tool-exec_cmd", {}, transport=transport
            )
            instance.timeout = 0.1

            start = time.monotonic()
            with pytest.raises(TimeoutError):
                transport._read_stdin_input(instance, input_func=input_func)
            elapsed = time.monotonic() - start

            assert instance.status == instance.STATUS_PENDING
            assert 0.08 <= elapsed <= 0.3

    def test_send_request_non_tty_uses_timeout_wrapper(self, monkeypatch):
        """When a runtime input function is registered, send_request uses it even without a TTY."""
        from topsailai.utils.thread_local_tool import (
            set_agent_runtime_input_with_timeout,
        )

        mock_wrapper = MagicMock(return_value="approve")
        set_agent_runtime_input_with_timeout(mock_wrapper)

        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance(
            "cmd_tool-exec_cmd", {}, transport=transport
        )
        instance.timeout = 0.5

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=1.0)

        assert status == instance.STATUS_APPROVED
        mock_wrapper.assert_called_once()
        call_args = mock_wrapper.call_args
        assert "APPROVAL REQUEST" in call_args.args[0]
        assert call_args.args[1] == 0.5

    def test_send_request_non_tty_without_wrapper_falls_back_to_timeout(
        self, monkeypatch
    ):
        """Without a registered wrapper and no TTY, send_request does not start a stdin thread."""
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance(
            "cmd_tool-exec_cmd", {}, transport=transport
        )
        instance.timeout = 0.05

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=0.1)

        assert status == instance.STATUS_TIMEOUT
