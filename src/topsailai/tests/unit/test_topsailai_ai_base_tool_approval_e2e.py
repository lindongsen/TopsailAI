"""
End-to-end tests for the tool approval feature.
"""

import json
import os
import threading
import time

import pytest

from topsailai.ai_base.tool_approval import matcher
from topsailai.ai_base.tool_approval.decorator import with_tool_approval
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import set_default_approval_transport
from topsailai.ai_base.tool_approval.transport import ApprovalTransport


class MockTransport(ApprovalTransport):
    """Transport that simulates an external approval system."""

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


class TestE2E:
    """Full feature tests."""

    def test_json_file_rules(self, monkeypatch, tmp_path):
        rules = [
            {
                "match": "cmd_tool-exec_cmd",
                "mode": "require",
                "timeout": 0.1,
                "policy": "deny",
                "params": [{"param": "cmd", "op": "contains", "value": "dangerous_cmd"}],
            }
        ]
        rules_file = tmp_path / "rules.json"
        rules_file.write_text(json.dumps(rules))

        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_RULES", str(rules_file))

        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            exec_tool_func(run_cmd, {"cmd": "dangerous_cmd /"}, tool_name="cmd_tool-exec_cmd")

    def test_invalid_json_disables_approval(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_RULES", "not valid json")

        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        result = exec_tool_func(run_cmd, {"cmd": "echo hello"}, tool_name="cmd_tool-exec_cmd")
        assert result == "ran echo hello"
        assert transport.instances == []

    def test_missing_rules_file_disables_approval(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_RULES", "/nonexistent/path/rules.json")

        transport = MockTransport()
        set_default_approval_transport(transport)

        @with_tool_approval
        def exec_tool_func(tool_func, args, tool_name=None):
            return tool_func(**args)

        def run_cmd(cmd):
            return f"ran {cmd}"

        result = exec_tool_func(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "ran ls"
        assert transport.instances == []

    def test_external_callback_resolution(self, monkeypatch):
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

        def external_callback():
            time.sleep(0.05)
            instance = transport.instances[0]
            # Simulate external REST/WebSocket callback calling approve
            instance.approve()

        threading.Thread(target=external_callback).start()
        result = exec_tool_func(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "ran ls"
