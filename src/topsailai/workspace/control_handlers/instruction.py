"""
Instruction-related business control handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-06
Purpose: Provide a control-channel action that reuses the registered
`/` instruction system through HookInstruction.call_instruction.
"""

from __future__ import annotations

from typing import Any

from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest, ControlResponse


def _get_hook_instruction(context: ControlContext) -> Any:
    """Return the HookInstruction instance from the agent chat context."""
    agent_chat = getattr(context, "agent_chat", None)
    if agent_chat is None:
        return None
    return getattr(agent_chat, "hook_instruction", None)


class CallInstructionHandler(ControlHandler):
    """Invoke a registered `/` instruction and return its result.

    Payload fields:
        instruction (str): The instruction name, with or without the leading
            trigger character (e.g. "/ctx.history" or "ctx.history").
        args (list, optional): Positional arguments passed to the instruction.
        kwargs (dict, optional): Keyword arguments passed to the instruction.
    """

    @property
    def action(self) -> str:
        return "call_instruction"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        instruction = request.payload.get("instruction")
        if not instruction or not isinstance(instruction, str):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="missing or invalid instruction",
            )

        hook_instruction = _get_hook_instruction(context)
        if hook_instruction is None:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="hook instruction is not available in control context",
            )

        args = request.payload.get("args") or []
        kwargs = request.payload.get("kwargs") or {}
        if not isinstance(args, list):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="args must be a list",
            )
        if not isinstance(kwargs, dict):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="kwargs must be an object",
            )

        if not hasattr(hook_instruction, "call_instruction"):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error="hook instruction does not support call_instruction",
            )

        try:
            result = hook_instruction.call_instruction(instruction, *args, **kwargs)
        except Exception as exc:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"instruction failed: {exc}",
            )

        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result=result,
        )
