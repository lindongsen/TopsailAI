"""
Integration tests for the tool approval module.
"""

import threading
import time

import pytest

from topsailai.ai_base.tool_approval import matcher
from topsailai.ai_base.tool_approval.decorator import with_tool_approval
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import (
    ToolApprovalInstance,
    set_default_approval_transport,
)
from topsailai.ai_base.tool_approval.transport import ApprovalTransport


class MockTransport(ApprovalTransport):
    """Transport used for integration tests."""

    def __init__(self):
        self.instances = []
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def send_request(self, instance):
        self.instances.append(instance)
        with self._lock:
            self._events[instance.id] = threading.Event()

    def wait_response(self, instance, timeout=None):
        with self._lock:
            event = self._events.get(instance.id)
        if event is None:
            return instance.status
        effective = timeout if timeout is not None else instance.timeout
        if event.wait(timeout=effective):
            return instance.status
        return instance.STATUS_TIMEOUT

    def on_resolved(self, instance):
        with self._lock:
            event = self._events.pop(instance.id, None)
        if event is not None:
            event.set()

    def supports_external_resolution(self):
        return True

    def resolve(self, instance_id, status):
        instance = next((i for i in self.instances if i.id == instance_id), None)
        if instance is None:
            return
        if status == "approve":
            instance.approve()
        elif status == "deny":
            instance.deny()


@pytest.fixture(autouse=True)
def clear_rules():
    matcher.clear_approval_rules_cache()
    yield
    matcher.clear_approval_rules_cache()


class TestIntegration:
    """End-to-end integration tests."""

    def test_bypass_rule(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "file_tool-read_*", "mode": "bypass"}]',
        )
        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def read_file(path):
            return f"content of {path}"

        result = exec_tool_func(read_file, {"path": "/tmp/test"}, tool_name="file_tool-read_file")
        assert result == "content of /tmp/test"
        assert transport.instances == []

    def test_require_and_approve(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "policy": "deny"}]',
        )
        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def approve_later():
            time.sleep(0.05)
            instance = transport.instances[0]
            transport.resolve(instance.id, "approve")

        threading.Thread(target=approve_later).start()
        result = exec_tool_func(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "ran ls"

    def test_require_and_deny(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "policy": "deny"}]',
        )
        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def deny_later():
            time.sleep(0.05)
            instance = transport.instances[0]
            transport.resolve(instance.id, "deny")

        threading.Thread(target=deny_later).start()
        with pytest.raises(ToolApprovalDeniedError):
            exec_tool_func(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")

    def test_params_logic_or(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "params": [{"param": "cmd", "op": "contains", "value": "safe_cmd_a"}, {"param": "cmd", "op": "contains", "value": "safe_cmd_b"}], "logic": "or", "policy": "deny"}]',
        )
        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            exec_tool_func(run_cmd, {"cmd": "safe_cmd_b arg"}, tool_name="cmd_tool-exec_cmd")

    def test_match_must_always_satisfy(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "params": [{"param": "cmd", "op": "contains", "value": "safe_cmd"}], "logic": "or", "policy": "deny"}]',
        )
        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        # file_tool does not match the rule, so it bypasses approval
        result = exec_tool_func(run_cmd, {"cmd": "safe_cmd status"}, tool_name="file_tool-read_file")
        assert result == "ran safe_cmd status"
