"""
Exceptions raised by the tool approval mechanism.
"""

from __future__ import annotations

from topsailai.ai_base.agent_types.exception import AgentToolCallException


class ToolApprovalDeniedError(AgentToolCallException):
    """
    Raised when a tool call is denied by the approval policy.

    Inherits from ``AgentToolCallException`` so the ReAct step loop can
    distinguish approval denials from generic execution failures.
    """

    def __init__(self, message: str, instance_id: str | None = None):
        super().__init__(message)
        self.instance_id = instance_id
