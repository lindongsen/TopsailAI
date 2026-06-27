"""
Unit tests for the tool approval decorator.
"""

import threading
import time

import pytest

from topsailai.ai_base.tool_approval.decorator import with_tool_approval, is_tool_approval_enabled
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import set_default_approval_transport
from topsailai.ai_base.tool_approval.transport import ApprovalTransport


class MockTransport(ApprovalTransport):
    """Transport that records requests and can be resolved manually."""

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


def make_wrapped(transport):
    """Create a decorated dummy function with a mock transport."""
    calls = []

    def exec_tool_func(tool_func, args, tool_name=None):
        """Mock matching the real exec_tool_func(tool_func, args, tool_name=None) signature."""
        calls.append((tool_func, args, tool_name))
        return "executed"

    set_default_approval_transport(transport)
    wrapped = with_tool_approval(exec_tool_func)
    return wrapped, calls


class TestIsToolApprovalEnabled:
    """Tests for the standalone enablement helper."""

    def test_enabled_values(self, monkeypatch):
        for value in ("1", "true", "True", "TRUE", "yes", "Yes", "YES"):
            monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", value)
            assert is_tool_approval_enabled() is True

    def test_disabled_values(self, monkeypatch):
        for value in ("0", "false", "False", "FALSE", "no", "No", "NO", ""):
            monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", value)
            assert is_tool_approval_enabled() is False


class TestDecoratorNoApproval:
    """Tests when approval is disabled or not required."""

    def test_disabled_executes_directly(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "0")
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def dummy_tool():
            return "ok"

        result = wrapped(dummy_tool, {}, tool_name="cmd_tool-exec_cmd")
        assert result == "executed"
        assert len(calls) == 1
        assert transport.instances == []

    def test_bypass_executes_directly(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "file_tool-read_*", "mode": "bypass"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def read_file(path):
            return f"content of {path}"

        result = wrapped(read_file, {"path": "/tmp"}, tool_name="file_tool-read_file")
        assert result == "executed"
        assert len(calls) == 1
        assert transport.instances == []


class TestDecoratorDeny:
    """Tests when the rule denies approval."""

    def test_deny_raises_tool_approval_denied_error(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")

        assert len(calls) == 0

    def test_deny_is_not_agent_tool_call_exception(self):
        from topsailai.ai_base.agent_types.exception import AgentToolCallException
        assert not issubclass(ToolApprovalDeniedError, AgentToolCallException)

    def test_unknown_mode_defaults_to_require(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "unknown", "timeout": 0.05, "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert len(calls) == 0


class TestDecoratorAsk:
    """Tests when approval is required."""

    def test_ask_approved_executes(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def resolve_later():
            time.sleep(0.05)
            instance = transport.instances[0]
            transport.resolve(instance.id, "approve")

        threading.Thread(target=resolve_later).start()
        result = wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "executed"
        assert len(calls) == 1

    def test_ask_denied_raises(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def resolve_later():
            time.sleep(0.05)
            instance = transport.instances[0]
            transport.resolve(instance.id, "deny")

        threading.Thread(target=resolve_later).start()
        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert len(calls) == 0

    def test_ask_timeout_deny_raises(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 0.05, "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert len(calls) == 0

    def test_ask_timeout_allow_executes(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 0.05, "policy": "allow"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        result = wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "executed"
        assert len(calls) == 1

    def test_ask_again_then_deny(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 0.05, "policy": "ask_again"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert len(calls) == 0

    def test_ask_again_then_approved(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 0.05, "policy": "ask_again"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, calls = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def resolve_later():
            time.sleep(0.08)
            instance = transport.instances[0]
            transport.resolve(instance.id, "approve")

        threading.Thread(target=resolve_later).start()
        result = wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert result == "executed"
        assert len(calls) == 1


class TestDecoratorRegistry:
    """Tests for pending instance registry interaction."""

    def test_instance_registered_while_pending(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 0.2, "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher, registry

        matcher.clear_approval_rules_cache()
        transport = MockTransport()
        wrapped, _ = make_wrapped(transport)

        def run_cmd(cmd):
            return f"ran {cmd}"

        def check_registry():
            time.sleep(0.02)
            assert len(registry.list_pending_approvals()) >= 1

        threading.Thread(target=check_registry).start()
        with pytest.raises(ToolApprovalDeniedError):
            wrapped(run_cmd, {"cmd": "ls"}, tool_name="cmd_tool-exec_cmd")
        assert registry.get_pending_approval(transport.instances[0].id) is None
