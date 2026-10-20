"""Report control-channel liveness without accessing agent state.

Author: DawsonLin
"""
import os
import socket

from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import ControlResponse


class HeartbeatHandler(ControlHandler):
    """Answer lightweight liveness requests for the responding process."""

    action = "heartbeat"

    def handle(self, request, context):
        """Return process identity for an empty heartbeat payload."""
        if request.payload:
            return ControlResponse(request.request_id, "error", error="invalid_payload")
        return ControlResponse(
            request.request_id,
            "ok",
            result={
                "alive": True,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "session_id": context.session_id or None,
            },
        )
