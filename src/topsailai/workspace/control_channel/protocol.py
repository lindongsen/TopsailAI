"""
Protocol layer for the control channel module.

Defines the request/response data models and JSONL encoding/decoding logic.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Control channel message protocol
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from topsailai.workspace.control_channel.exceptions import ControlProtocolError


@dataclass
class ControlRequest:
    """Incoming control request message.

    Attributes:
        request_id: Unique identifier for request-response correlation.
        action: The command/action to be executed.
        payload: Optional parameters for the action.
    """

    request_id: str
    action: str
    payload: dict = field(default_factory=dict)


@dataclass
class ControlResponse:
    """Outgoing control response message.

    Attributes:
        request_id: Unique identifier matching the request.
        status: Either "ok" or "error".
        result: Optional business result when status is "ok".
        error: Optional error description when status is "error".
    """

    request_id: str
    status: str
    result: Any = None
    error: Optional[str] = None


@dataclass
class ControlContext:
    """Runtime context exposed to business handlers.

    This context provides read-only or controlled access to runtime objects.
    Business handlers should not depend on the entire AgentChat instance.

    Attributes:
        session_id: Current session identifier, if any.
        pid: Current process identifier, if any.
        task_folder: Resolved workspace task folder used for session-scoped files.
        ai_agent: Optional reference to the active AgentBase instance.
        ctx_runtime_data: Optional reference to User2Agent context manager.
        agent_chat: Optional reference to the AgentChat instance.
        control_event: Optional threading.Event for interrupt/pause/resume signals.
    """

    session_id: Optional[str] = None
    pid: Optional[int] = None
    task_folder: Optional[str] = None
    ai_agent: Optional[Any] = None
    ctx_runtime_data: Optional[Any] = None
    agent_chat: Optional[Any] = None
    control_event: Optional[Any] = None


def encode_response(response: ControlResponse) -> bytes:
    """Encode a ControlResponse into a JSONL line.

    Args:
        response: The response object to encode.

    Returns:
        UTF-8 encoded JSONL bytes terminated with a newline.
    """
    payload = {
        "request_id": response.request_id,
        "status": response.status,
    }
    if response.result is not None:
        payload["result"] = response.result
    if response.error is not None:
        payload["error"] = response.error
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def decode_request(raw: str) -> ControlRequest:
    """Decode a raw JSONL line into a ControlRequest.

    Args:
        raw: A single JSONL line string.

    Returns:
        A validated ControlRequest instance.

    Raises:
        ControlProtocolError: When the line is not valid JSON, not an object,
            or missing required fields.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ControlProtocolError(f"invalid json: {e}", request_id="") from e

    if not isinstance(data, dict):
        raise ControlProtocolError("message must be a JSON object", request_id="")

    request_id = data.get("request_id", "")
    action = data.get("action", "")
    payload = data.get("payload") or {}

    if not request_id:
        raise ControlProtocolError("missing request_id", request_id="")
    if not action:
        raise ControlProtocolError("missing action", request_id=request_id)
    if not isinstance(payload, dict):
        raise ControlProtocolError("payload must be a JSON object", request_id=request_id)

    return ControlRequest(
        request_id=request_id,
        action=action,
        payload=payload,
    )
