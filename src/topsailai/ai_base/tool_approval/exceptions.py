"""
Exceptions raised by the tool approval mechanism.
"""

from __future__ import annotations

class ToolApprovalException(Exception):
    """ Base Exception """
    pass

class ToolApprovalDeniedError(ToolApprovalException):
    """
    Raised when a tool call is denied by the approval policy.
    """

    def __init__(self, message: str, instance_id: str | None = None):
        super().__init__(message)
        self.instance_id = instance_id
