"""
Tool approval instance lifecycle.

A ``ToolApprovalInstance`` represents a single tool call that may need human
or policy approval before it can execute.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from topsailai.ai_base.tool_approval.matcher import (
    _ENV_DEFAULT_POLICY,
    _ENV_DEFAULT_TIMEOUT,
    is_tool_approval_enabled,
    match_approval_rule,
)
from topsailai.utils import env_tool

if TYPE_CHECKING:
    from topsailai.ai_base.tool_approval.transport import ApprovalTransport


DEFAULT_APPROVAL_TIMEOUT = 60.0
DEFAULT_APPROVAL_POLICY = "deny"

_default_transport: "ApprovalTransport | None" = None
_default_transport_lock = threading.Lock()


def get_default_approval_transport() -> "ApprovalTransport":
    """Return the default approval transport, creating it if necessary."""
    global _default_transport
    if _default_transport is None:
        with _default_transport_lock:
            if _default_transport is None:
                from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport

                _default_transport = LocalApprovalTransport.get_instance()
    return _default_transport


def set_default_approval_transport(transport: "ApprovalTransport") -> None:
    """Override the default approval transport."""
    global _default_transport
    with _default_transport_lock:
        _default_transport = transport


def get_default_timeout() -> float:
    """Return the default approval timeout in seconds."""
    value = env_tool.EnvReaderInstance.get(_ENV_DEFAULT_TIMEOUT, default="")
    if value:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return DEFAULT_APPROVAL_TIMEOUT


def get_default_policy() -> str:
    """Return the default timeout policy."""
    value = env_tool.EnvReaderInstance.get(_ENV_DEFAULT_POLICY, default="")
    if value and value in ("deny", "allow", "ask_again"):
        return value
    return DEFAULT_APPROVAL_POLICY


class ApprovalDecision:
    """Decision produced by ``ToolApprovalInstance.decide()`` for one call."""

    NO_APPROVAL = "no_approval"
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

    def __init__(
        self,
        action: str,
        rule: Any = None,
        timeout: float | None = None,
        policy: str | None = None,
    ):
        self.action = action
        self.rule = rule
        self.timeout = timeout
        self.policy = policy


class ToolApprovalInstance:
    """
    Represents one tool call awaiting approval.

    The instance starts in ``STATUS_PENDING`` for ``ask`` mode, or directly in
    ``STATUS_APPROVED`` / ``STATUS_DENIED`` / ``STATUS_NO_APPROVAL`` for rules
    that do not require a decision.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"
    STATUS_TIMEOUT = "timeout"
    STATUS_NO_APPROVAL = "no_approval"

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        context: dict[str, Any] | None = None,
        transport: "ApprovalTransport | None" = None,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.context = context or {}
        self.transport = transport
        self.status = self.STATUS_PENDING
        self.decision_by: str | None = None
        self.decision_at: float | None = None
        self.created_at = time.time()
        self.timeout = get_default_timeout()
        self.policy = get_default_policy()

    def decide(self) -> ApprovalDecision:
        """
        Evaluate configured rules against this tool call.

        Returns an ``ApprovalDecision`` describing what the caller should do.
        """
        if not is_tool_approval_enabled():
            return ApprovalDecision(action=ApprovalDecision.NO_APPROVAL)

        rule = match_approval_rule(tool_name=self.tool_name, tool_args=self.tool_args)
        if not rule:
            return ApprovalDecision(action=ApprovalDecision.NO_APPROVAL)

        if rule.mode in ("bypass", "skip"):
            return ApprovalDecision(action=ApprovalDecision.ALLOW, rule=rule)
        if rule.mode == "require":
            self.timeout = rule.timeout if rule.timeout is not None else self.timeout
            self.policy = rule.policy if rule.policy is not None else self.policy
            return ApprovalDecision(
                action=ApprovalDecision.ASK,
                rule=rule,
                timeout=self.timeout,
                policy=self.policy,
            )

        # Unknown modes default to require (safe default) per the feature spec.
        logger = __import__("logging").getLogger(__name__)
        logger.warning("Unknown approval rule mode '%s', defaulting to require", rule.mode)
        return ApprovalDecision(
            action=ApprovalDecision.ASK,
            rule=rule,
            timeout=self.timeout,
            policy=self.policy,
        )

    def approve(self, by: str = "user") -> None:
        """Mark the request as approved."""
        self.status = self.STATUS_APPROVED
        self.decision_by = by
        self.decision_at = time.time()
        if self.transport is not None:
            self.transport.on_resolved(self)

    def deny(self, by: str = "user") -> None:
        """Mark the request as denied."""
        self.status = self.STATUS_DENIED
        self.decision_by = by
        self.decision_at = time.time()
        if self.transport is not None:
            self.transport.on_resolved(self)

    def mark_timeout(self) -> None:
        """Called by transports to record a timeout."""
        self.status = self.STATUS_TIMEOUT
        self.decision_by = "policy"
        self.decision_at = time.time()

    def apply_timeout_policy(self, policy: str) -> str:
        """
        Resolve a timeout according to the given policy.

        Returns the resolved status.
        """
        if policy == "allow":
            self.status = self.STATUS_APPROVED
            self.decision_by = "policy"
            self.decision_at = time.time()
            return self.status
        if policy == "ask_again":
            # Reset state and allow one additional wait cycle.
            self.status = self.STATUS_PENDING
            self.decision_by = None
            self.decision_at = None
            return self.status
        # "deny" and unknown policies default to deny.
        self.status = self.STATUS_DENIED
        self.decision_by = "policy"
        self.decision_at = time.time()
        return self.status

    def wait_for_decision(self, *, timeout: float | None = None, policy: str | None = None) -> str:
        """
        Wait for a human decision, applying timeout policy and ask_again logic.

        Returns the final status. This method encapsulates all approval waiting
        logic so the decorator does not need to know about ask_again cycles.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        effective_policy = policy if policy is not None else self.policy

        if self.transport is None:
            return self.status

        status = self.transport.wait_response(self, timeout=effective_timeout)
        if status != self.STATUS_TIMEOUT:
            return status

        status = self.apply_timeout_policy(effective_policy)
        if status == self.STATUS_PENDING:
            # ask_again: one extra wait cycle, then deny if still no answer.
            status = self.transport.wait_response(self, timeout=effective_timeout)
            if status == self.STATUS_TIMEOUT:
                status = self.apply_timeout_policy("deny")
        return status
