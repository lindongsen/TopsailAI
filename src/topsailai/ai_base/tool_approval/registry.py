"""
Tool approval pending-request registry.

Keeps track of in-flight approval requests so that external decision makers
can resolve them by ID.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance


_registry: dict[str, "ToolApprovalInstance"] = {}
_registry_lock = threading.Lock()


def register_pending_approval(instance: "ToolApprovalInstance") -> None:
    """Register an instance as pending approval."""
    with _registry_lock:
        _registry[instance.id] = instance


def unregister_pending_approval(instance_or_id: "ToolApprovalInstance | str") -> None:
    """Remove an instance from the pending registry."""
    instance_id = instance_or_id if isinstance(instance_or_id, str) else instance_or_id.id
    with _registry_lock:
        _registry.pop(instance_id, None)


def get_pending_approval(instance_id: str) -> "ToolApprovalInstance | None":
    """Return a pending instance by ID, or None if not found."""
    with _registry_lock:
        return _registry.get(instance_id)


# Alias used by tests and external callers.
get_pending_instance = get_pending_approval


def list_pending_approvals() -> list["ToolApprovalInstance"]:
    """Return a snapshot of all pending approval instances."""
    with _registry_lock:
        return list(_registry.values())


# Alias used by tests and external callers.
list_pending_instances = list_pending_approvals


def clear_pending_approvals() -> None:
    """Clear all pending approvals. Useful for tests."""
    with _registry_lock:
        _registry.clear()


# Aliases used by tests and external callers.
clear = clear_pending_approvals
clear_approval_registry = clear_pending_approvals


def resolve_approval(instance_id: str, approved: bool | str) -> bool:
    """
    Resolve a pending approval by instance ID.

    ``approved`` may be a boolean or one of the strings ``"approve"`` or
    ``"deny"``. Any other string leaves the instance unchanged and returns
    False.
    """
    with _registry_lock:
        instance = _registry.get(instance_id)
    if instance is None:
        return False

    if isinstance(approved, bool):
        if approved:
            instance.approve()
        else:
            instance.deny()
        return True

    if approved == "approve":
        instance.approve()
        return True
    if approved == "deny":
        instance.deny()
        return True

    return False
