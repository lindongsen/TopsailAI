"""
Unit tests for the tool approval transport layer.
"""

import io
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

    def test_stdin_thread_approve(self, monkeypatch):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        input_stream = io.StringIO("approve\n")
        monkeypatch.setattr(sys.stdin, "readline", input_stream.readline)

        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=1.0)
        assert status == instance.STATUS_APPROVED

    def test_stdin_thread_deny(self, monkeypatch):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        input_stream = io.StringIO("deny\n")
        monkeypatch.setattr(sys.stdin, "readline", input_stream.readline)

        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=1.0)
        assert status == instance.STATUS_DENIED

    def test_stdin_thread_unrecognized_defaults_to_deny(self, monkeypatch):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        input_stream = io.StringIO("maybe\n")
        monkeypatch.setattr(sys.stdin, "readline", input_stream.readline)

        transport.send_request(instance)
        status = transport.wait_response(instance, timeout=1.0)
        assert status == instance.STATUS_DENIED

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
