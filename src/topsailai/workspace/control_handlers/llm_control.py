"""Control-channel boundary for explicitly bound LLM attempts. Author: DawsonLin."""
from dataclasses import asdict
import os

from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL
from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import ControlResponse


class LLMControlHandler(ControlHandler):
    """Queue first-byte commands without accessing handler-thread Agent context."""

    @property
    def action(self):
        """Expose the additive action without changing legacy interrupts."""
        return "llm_control"

    def handle(self, request, context):
        """Authenticate server-bound ownership before scalar command projection."""
        route = getattr(context.agent_chat, "_llm_control_route", None)
        if (route is None or route.agent is not context.agent_chat.ai_agent
                or route.session_id != context.session_id or route.pid != context.pid
                or context.pid != os.getpid() or route.closed):
            return ControlResponse(request.request_id, "error", error="unavailable")
        payload = request.payload
        operation = payload.get("operation", "status")
        route.reconcile()
        with route.lock:
            if (route.closed or route.agent is not context.agent_chat.ai_agent
                    or route is not context.agent_chat._llm_control_route):
                return ControlResponse(request.request_id, "error", error="unavailable")
            if operation == "status":
                command_id = payload.get("command_id")
                if command_id is None:
                    result = {"state": route.state, "reason": route.reason,
                              "target": asdict(route.target) if route.target else None}
                else:
                    status = REQUEST_CONTROL.status(command_id)
                    if status is None or status.proposal.target.binding_id != route.binding_id:
                        return ControlResponse(request.request_id, "error", error="unknown_command")
                    result = asdict(status)
                return ControlResponse(request.request_id, "ok", result=result)
            if operation not in ("hard_interrupt", "force_retry"):
                return ControlResponse(request.request_id, "error", error="invalid_operation")
            if route.reason == "control_capacity":
                return ControlResponse(request.request_id, "error", error="unavailable/control_capacity")
            try:
                target_data = payload.get("target")
                if type(target_data) is not dict:
                    raise ValueError("exact target required")
                target = AttemptTarget(**target_data)
                if target.binding_id != route.binding_id or target.generation != route.generation:
                    raise ValueError("stale_target")
                command_id = payload.get("command_id", request.request_id)
                status = REQUEST_CONTROL.submit(target, command_id, operation)
            except (ValueError, TypeError) as error:
                return ControlResponse(request.request_id, "error", error=str(error))
            return ControlResponse(request.request_id, "ok", result=asdict(status))
