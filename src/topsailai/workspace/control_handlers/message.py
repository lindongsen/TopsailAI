"""
Message-related business control handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Provide control-channel actions for inspecting runtime and session messages
"""

from __future__ import annotations

import dataclasses
from typing import Any

from topsailai.context.ctx_manager import get_session_manager
from topsailai.utils.thread_local_tool import get_agent_object
from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest, ControlResponse

def serialize_message(message: Any) -> Any:
    """Serialize a message value into JSON-compatible primitives."""
    if message is None or isinstance(message, (bool, int, float, str)):
        return message

    if isinstance(message, dict):
        return {str(key): serialize_message(value) for key, value in message.items()}

    if isinstance(message, (list, tuple)):
        return [serialize_message(value) for value in message]

    if hasattr(message, "model_dump") and callable(message.model_dump):
        return serialize_message(message.model_dump(mode="json"))

    if hasattr(message, "to_dict") and callable(message.to_dict):
        return serialize_message(message.to_dict())

    if dataclasses.is_dataclass(message) and not isinstance(message, type):
        return serialize_message(dataclasses.asdict(message))

    try:
        return serialize_message(dict(message))
    except (TypeError, ValueError):
        pass

    obj_dict = getattr(message, "__dict__", None)
    if obj_dict:
        return serialize_message(obj_dict)

    return str(message)

def _get_context_agent(context: ControlContext) -> Any:
    """Return Agent2LLM through the User2Agent reference in the context."""
    agent_chat = getattr(context, "agent_chat", None)
    if agent_chat is not None:
        return getattr(agent_chat, "ai_agent", None)
    return getattr(context, "ai_agent", None)

class GetRuntimeMessagesHandler(ControlHandler):
    """Return current Agent2LLM messages using the server context when available."""

    @property
    def action(self) -> str:
        return "get_runtime_messages"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        agent = _get_context_agent(context) or get_agent_object()
        if agent is None:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="no active agent in control context or current thread",
            )

        if not hasattr(agent, "messages"):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="active agent has no messages attribute",
            )

        messages = [serialize_message(m) for m in agent.messages]
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result={
                "count": len(messages),
                "messages": messages,
            },
        )


class GetSessionMessagesHandler(ControlHandler):
    """Return persisted User2Agent session messages for a given session_id."""

    @property
    def action(self) -> str:
        return "get_session_messages"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        session_id = request.payload.get("session_id")
        if not session_id:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="missing or empty session_id",
            )

        session_mgr = getattr(context, "session_mgr", None)
        if session_mgr is None:
            try:
                session_mgr = get_session_manager()
            except Exception as exc:
                return ControlResponse(
                    request_id=request.request_id,
                    status="error",
                    error=f"failed to initialize session manager: {exc}",
                )

        if session_mgr is None:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="session manager is not available",
            )

        if hasattr(session_mgr, "exists_session") and not session_mgr.exists_session(session_id):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"session not found: {session_id}",
            )

        try:
            messages = session_mgr.retrieve_messages(session_id)
        except Exception as exc:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"failed to retrieve session messages: {exc}",
            )

        serialized = [serialize_message(m) for m in messages]
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result={
                "count": len(serialized),
                "messages": serialized,
            },
        )
