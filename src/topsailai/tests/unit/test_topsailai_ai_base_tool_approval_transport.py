"""
Unit tests for the tool approval transport layer.
"""

import fcntl
import io
import os
import pty
import sys
import threading
import time
from unittest.mock import patch

import pytest

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

    def test_on_resolved_removes_instance(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        instance.approve()
        transport.on_resolved(instance)
        # The request queue is not cleared on resolve; only the response event is.
        # Drain the queue and verify no further pending instance remains.
        assert transport.get_request(timeout=0.05) == instance
        assert transport.get_request(timeout=0.05) is None

    def test_supports_external_resolution(self):
        transport = LocalApprovalTransport()
        assert transport.supports_external_resolution() is True

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
