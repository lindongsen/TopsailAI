"""
Exception definitions for the control channel module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Define control channel specific exceptions
"""


class ControlChannelError(Exception):
    """Base exception for control channel errors."""

    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.message = message
        self.request_id = request_id


class ControlProtocolError(ControlChannelError):
    """Raised when a control message violates the protocol."""

    pass


class ControlHandlerError(ControlChannelError):
    """Raised when a handler fails to process a request."""

    pass
