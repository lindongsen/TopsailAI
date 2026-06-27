"""
Unit tests for the tool approval registry.
"""

import threading
import time

import pytest

from topsailai.ai_base.tool_approval import registry
from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance
from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before each test."""
    registry.clear_pending_approvals()
    yield
    registry.clear_pending_approvals()


class TestRegistryBasic:
    """Tests for basic registry operations."""

    def test_register_and_get(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        assert registry.get_pending_approval(instance.id) is instance
        assert registry.get_pending_instance(instance.id) is instance

    def test_unregister(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.unregister_pending_approval(instance.id)
        assert registry.get_pending_approval(instance.id) is None

    def test_list_empty(self):
        assert registry.list_pending_approvals() == []
        assert registry.list_pending_instances() == []

    def test_list_multiple(self):
        transport = LocalApprovalTransport()
        instance1 = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        instance2 = ToolApprovalInstance("file_tool-read_file", {}, transport=transport)
        registry.register_pending_approval(instance1)
        registry.register_pending_approval(instance2)
        assert len(registry.list_pending_approvals()) == 2


class TestResolveApproval:
    """Tests for resolving approvals through the registry."""

    def test_resolve_approve(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.resolve_approval(instance.id, "approve")
        assert instance.status == instance.STATUS_APPROVED

    def test_resolve_deny(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.resolve_approval(instance.id, "deny")
        assert instance.status == instance.STATUS_DENIED

    def test_resolve_unknown_status(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.resolve_approval(instance.id, "unknown")
        assert instance.status == instance.STATUS_PENDING

    def test_resolve_missing_instance(self):
        registry.resolve_approval("missing", "approve")

    def test_resolve_approve_boolean_true(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.resolve_approval(instance.id, True)
        assert instance.status == instance.STATUS_APPROVED

    def test_resolve_deny_boolean_false(self):
        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance("cmd_tool-exec_cmd", {}, transport=transport)
        registry.register_pending_approval(instance)
        registry.resolve_approval(instance.id, False)
        assert instance.status == instance.STATUS_DENIED


class TestRegistryConcurrency:
    """Tests for thread safety of the registry."""

    def test_concurrent_register_unregister(self):
        transport = LocalApprovalTransport()
        instances = [
            ToolApprovalInstance(f"tool_{i}", {}, transport=transport) for i in range(100)
        ]
        errors = []

        def worker(start):
            try:
                for i in range(start, start + 50):
                    registry.register_pending_approval(instances[i])
                    time.sleep(0.001)
                    registry.unregister_pending_approval(instances[i].id)
            except Exception as exc:  # pragma: no cover - safety net
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert registry.list_pending_approvals() == []
