"""
Control Channel Module

This module provides an independent runtime control channel for TopsailAI.
It focuses solely on message sending, receiving, consuming, and returning.
Business logic is decoupled through a handler registry pattern.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Runtime control channel for agent processes
"""

from topsailai.workspace.control_channel.exceptions import (
    ControlChannelError,
    ControlProtocolError,
    ControlHandlerError,
)
from topsailai.workspace.control_channel.protocol import (
    ControlRequest,
    ControlResponse,
    ControlContext,
    encode_response,
    decode_request,
)
from topsailai.workspace.control_channel.handler import (
    ControlHandler,
    ControlHandlerRegistry,
)
from topsailai.workspace.control_channel.server import ControlServer

__all__ = [
    "ControlChannelError",
    "ControlProtocolError",
    "ControlHandlerError",
    "ControlRequest",
    "ControlResponse",
    "ControlContext",
    "encode_response",
    "decode_request",
    "ControlHandler",
    "ControlHandlerRegistry",
    "ControlServer",
]
