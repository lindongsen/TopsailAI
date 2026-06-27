"""
Tool approval package.
"""

from topsailai.ai_base.tool_approval.decorator import with_tool_approval
from topsailai.ai_base.tool_approval.exceptions import ToolApprovalDeniedError
from topsailai.ai_base.tool_approval.instance import (
    ApprovalDecision,
    ToolApprovalInstance,
    get_default_approval_transport,
    get_default_policy,
    get_default_timeout,
    set_default_approval_transport,
)
from topsailai.ai_base.tool_approval.matcher import (
    ApprovalRule,
    clear_approval_rules_cache,
    get_approval_rules,
    is_tool_approval_enabled,
    load_approval_rules,
    match_approval_rule,
)
from topsailai.ai_base.tool_approval.registry import (
    clear,
    clear_approval_registry,
    clear_pending_approvals,
    get_pending_approval,
    list_pending_approvals,
    register_pending_approval,
    resolve_approval,
    unregister_pending_approval,
)
from topsailai.ai_base.tool_approval.transport import (
    ApprovalTransport,
    LocalApprovalTransport,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalRule",
    "ApprovalTransport",
    "LocalApprovalTransport",
    "ToolApprovalDeniedError",
    "ToolApprovalInstance",
    "clear",
    "clear_approval_registry",
    "clear_approval_rules_cache",
    "clear_pending_approvals",
    "get_approval_rules",
    "get_default_approval_transport",
    "get_default_policy",
    "get_default_timeout",
    "get_pending_approval",
    "is_tool_approval_enabled",
    "list_pending_approvals",
    "load_approval_rules",
    "match_approval_rule",
    "register_pending_approval",
    "resolve_approval",
    "set_default_approval_transport",
    "unregister_pending_approval",
    "with_tool_approval",
]
