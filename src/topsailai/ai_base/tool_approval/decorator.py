"""
Tool approval decorator.

Wraps the agent's tool execution entry point so that every tool call can be
gated by configurable approval rules.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import (
    ApprovalDecision,
    ToolApprovalInstance,
    get_default_approval_transport,
)
from topsailai.ai_base.tool_approval.matcher import is_tool_approval_enabled
from topsailai.ai_base.tool_approval.registry import (
    register_pending_approval,
    unregister_pending_approval,
)


logger = logging.getLogger(__name__)


def _get_default_transport():
    return get_default_approval_transport()


def _get_rule_name(rule: Any) -> str | None:
    """
    Return the matched rule's name, or ``None`` when it has no usable name.

    Rules normally come from JSON, so a plain ``dict`` must be read as well as
    the ``ApprovalRule`` dataclass. An empty or missing name returns ``None`` so
    callers can omit the reason instead of printing a placeholder.
    """
    if rule is None:
        return None
    if isinstance(rule, dict):
        name = rule.get("name")
    else:
        name = getattr(rule, "name", None)
    if not name:
        return None
    return str(name)


def _build_denial_message(tool_name: str, rule_name: str | None, status: str | None = None) -> str:
    """
    Build the denial message shown to the agent as the tool observation.

    The matched rule name is appended as the reason because the agent only sees
    this text: without it the model cannot tell which policy blocked the call
    and tends to retry the identical request. The reason is omitted when the
    rule has no name so the message stays free of placeholder noise.
    """
    reason = f" (rule: {rule_name})" if rule_name else ""
    if status is None:
        return f"Tool '{tool_name}' was denied by approval policy{reason}."
    status_part = f"status: {status}"
    if rule_name:
        status_part = f"{status_part}, rule: {rule_name}"
    return f"Tool '{tool_name}' was not approved ({status_part})."


def with_tool_approval(exec_tool_func: Callable) -> Callable:
    """
    Decorator that wraps the agent's tool execution entry point.

    The decorated function receives the same signature as ``exec_tool_func``
    plus the original ``tool_func`` as the first positional argument:

        def exec_tool_func(tool_func, args, tool_name=None, **kwargs)

    When approval is disabled, the call is forwarded directly to the original
    ``exec_tool_func``. When enabled, the decorator checks approval rules and
    either runs the tool, raises ``ToolApprovalDeniedError``, or waits for an
    approval decision before running the tool.
    """

    @functools.wraps(exec_tool_func)
    def wrapper(tool_func: Callable, args: dict, tool_name: str | None = None, **kwargs) -> Any:
        effective_tool_name = tool_name or getattr(tool_func, "__name__", "unknown")

        instance = ToolApprovalInstance(
            tool_name=effective_tool_name,
            tool_args=args or {},
            transport=_get_default_transport(),
        )
        decision = instance.decide()

        if decision.action in (ApprovalDecision.NO_APPROVAL, ApprovalDecision.ALLOW):
            return exec_tool_func(tool_func=tool_func, args=args, tool_name=tool_name, **kwargs)

        if decision.action == ApprovalDecision.DENY:
            rule_name = _get_rule_name(decision.rule)
            logger.info(
                "Tool approval matched rule: [%s] for tool [%s] decision=deny",
                rule_name or "<unnamed>",
                effective_tool_name,
            )
            raise ToolApprovalDeniedError(
                _build_denial_message(effective_tool_name, rule_name),
                instance_id=instance.id,
            )

        # decision.action == ApprovalDecision.ASK
        register_pending_approval(instance)
        rule_name = _get_rule_name(decision.rule)
        instance.rule_name = rule_name or "<unnamed>"
        logger.info(
            "Tool approval matched rule: [%s] for tool [%s] instance=%s timeout=%s policy=%s",
            instance.rule_name,
            effective_tool_name,
            instance.id,
            decision.timeout,
            decision.policy,
        )
        try:
            instance.transport.send_request(instance)
            status = instance.wait_for_decision(
                timeout=decision.timeout,
                policy=decision.policy,
            )

            if status in (ToolApprovalInstance.STATUS_DENIED, ToolApprovalInstance.STATUS_TIMEOUT):
                raise ToolApprovalDeniedError(
                    _build_denial_message(effective_tool_name, rule_name, status),
                    instance_id=instance.id,
                )
        finally:
            unregister_pending_approval(instance.id)

        return exec_tool_func(tool_func=tool_func, args=args, tool_name=tool_name, **kwargs)

    return wrapper
