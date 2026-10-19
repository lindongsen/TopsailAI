"""Stage a force-retry flag; execution belongs to the wait Hook Module."""
import os

from topsailai.ai_base.llm_control.control_runtime import stage_retry
from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import ControlResponse


class LLMControlHandler(ControlHandler):
    """Accept the retained force_retry operation without target/proposal routing."""

    @property
    def action(self):
        """Expose the existing CLI wire action."""
        return "llm_control"

    def handle(self, request, context):
        """Only stage a flag for this live process's current wait."""
        if context.pid != os.getpid() or context.agent_chat is None:
            return ControlResponse(request.request_id, "error", error="unavailable")
        if request.payload.get("operation") != "force_retry":
            return ControlResponse(request.request_id, "error", error="invalid_operation")
        if "target" in request.payload:
            return ControlResponse(request.request_id, "error", error="unsupported_target")
        try:
            staged = stage_retry(context.session_id or "topsailai", context.pid)
        except OSError:
            from topsailai.logger.log_chat import logger
            logger.exception("Failed to stage first-byte retry session=%s pid=%s",
                             context.session_id, context.pid)
            return ControlResponse(request.request_id, "error", error="flag_write_failed")
        if not staged:
            return ControlResponse(request.request_id, "error", error="not_waiting")
        return ControlResponse(request.request_id, "ok", result={"state": "flag_written"})
