"""
Unit tests for the tool approval instance and transport.
"""

import threading
import time

import pytest

from topsailai.ai_base.tool_approval.instance import (
    ApprovalDecision,
    ToolApprovalInstance,
    get_default_policy,
    get_default_timeout,
)
from topsailai.ai_base.tool_approval.transport import ApprovalTransport


class MockTransport(ApprovalTransport):
    """Transport that records calls and can be resolved manually."""

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
        """Helper to resolve an instance from tests."""
        instance = next((i for i in self.instances if i.id == instance_id), None)
        if instance is None:
            return
        if status == "approve":
            instance.approve()
        elif status == "deny":
            instance.deny()


class TestApprovalDecision:
    """Tests for ApprovalDecision."""

    def test_decision_values(self):
        assert ApprovalDecision.NO_APPROVAL == "no_approval"
        assert ApprovalDecision.ALLOW == "allow"
        assert ApprovalDecision.DENY == "deny"
        assert ApprovalDecision.ASK == "ask"


class TestToolApprovalInstanceDecide:
    """Tests for ToolApprovalInstance.decide()."""

    def test_disabled_returns_no_approval(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {"cmd": "ls"})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.NO_APPROVAL

    def test_no_rule_match_returns_no_approval(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_RULES", "[]")
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {"cmd": "ls"})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.NO_APPROVAL

    def test_bypass_mode_returns_allow(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "file_tool-read_*", "mode": "bypass"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        instance = ToolApprovalInstance("file_tool-read_file", {"path": "/tmp"})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.ALLOW
        assert decision.rule is not None
        assert decision.rule.match == "file_tool-read_*"

    def test_skip_alias_returns_allow(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "file_tool-read_*", "mode": "skip"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        instance = ToolApprovalInstance("file_tool-read_file", {"path": "/tmp"})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.ALLOW

    def test_require_mode_returns_ask(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "cmd_tool-exec_cmd", "mode": "require", "timeout": 120, "policy": "deny"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {"cmd": "ls"})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.ASK
        assert decision.timeout == 120.0
        assert decision.policy == "deny"

    def test_unknown_mode_defaults_to_require(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_ENABLED", "1")
        monkeypatch.setenv(
            "TOPSAILAI_TOOL_APPROVAL_RULES",
            '[{"match": "*", "mode": "unknown"}]',
        )
        from topsailai.ai_base.tool_approval import matcher

        matcher.clear_approval_rules_cache()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        decision = instance.decide()
        assert decision.action == ApprovalDecision.ASK


class TestToolApprovalInstanceState:
    """Tests for state transitions."""

    def test_approve(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        instance.approve()
        assert instance.status == instance.STATUS_APPROVED
        assert instance.decision_by == "user"
        assert instance.decision_at is not None

    def test_deny(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        instance.deny()
        assert instance.status == instance.STATUS_DENIED
        assert instance.decision_by == "user"

    def test_mark_timeout(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        instance.mark_timeout()
        assert instance.status == instance.STATUS_TIMEOUT
        assert instance.decision_by == "policy"

    def test_apply_timeout_policy_deny(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        assert instance.apply_timeout_policy("deny") == instance.STATUS_DENIED

    def test_apply_timeout_policy_allow(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        assert instance.apply_timeout_policy("allow") == instance.STATUS_APPROVED

    def test_apply_timeout_policy_ask_again(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        instance.mark_timeout()
        assert instance.apply_timeout_policy("ask_again") == instance.STATUS_PENDING

    def test_apply_timeout_policy_unknown_defaults_to_deny(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {})
        assert instance.apply_timeout_policy("unknown") == instance.STATUS_DENIED


class TestToolApprovalInstanceWait:
    """Tests for wait_for_decision."""

    def test_wait_approved(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)

        def resolve_later():
            time.sleep(0.05)
            transport.resolve(instance.id, "approve")

        threading.Thread(target=resolve_later).start()
        status = instance.wait_for_decision(timeout=1.0, policy="deny")
        assert status == instance.STATUS_APPROVED

    def test_wait_denied(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)

        def resolve_later():
            time.sleep(0.05)
            transport.resolve(instance.id, "deny")

        threading.Thread(target=resolve_later).start()
        status = instance.wait_for_decision(timeout=1.0, policy="deny")
        assert status == instance.STATUS_DENIED

    def test_wait_timeout_deny(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        status = instance.wait_for_decision(timeout=0.05, policy="deny")
        assert status == instance.STATUS_DENIED

    def test_wait_timeout_allow(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        status = instance.wait_for_decision(timeout=0.05, policy="allow")
        assert status == instance.STATUS_APPROVED

    def test_wait_ask_again_then_deny(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)
        status = instance.wait_for_decision(timeout=0.05, policy="ask_again")
        assert status == instance.STATUS_DENIED

    def test_wait_ask_again_then_approved(self):
        transport = MockTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        transport.send_request(instance)

        def resolve_later():
            time.sleep(0.08)
            transport.resolve(instance.id, "approve")

        threading.Thread(target=resolve_later).start()
        status = instance.wait_for_decision(timeout=0.05, policy="ask_again")
        assert status == instance.STATUS_APPROVED

    def test_wait_no_transport_returns_current_status(self):
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=None)
        status = instance.wait_for_decision(timeout=0.05, policy="deny")
        assert status == instance.STATUS_PENDING


class TestDefaultConfig:
    """Tests for default configuration helpers."""

    def test_default_timeout(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT", "120")
        assert get_default_timeout() == 120.0

    def test_default_timeout_invalid(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT", "abc")
        assert get_default_timeout() == 60.0

    def test_default_policy(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY", "allow")
        assert get_default_policy() == "allow"

    def test_default_policy_unknown(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY", "unknown")
        assert get_default_policy() == "deny"
