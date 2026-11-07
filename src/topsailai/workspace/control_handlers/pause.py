"""
Pause control handlers for the Agent2LLM runtime.

The control plane only delivers intent. A pause request is accepted by writing
a session-scoped JSON marker and returning immediately; the agent main thread
consumes the marker at a safe point and blocks on the runtime input channel.
A blocking handler is impossible here because the control transport requires a
correlated response frame within a short budget and has no channel to return the
human's answer.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-07
Purpose: Provide control-channel actions for pausing the Agent2LLM loop
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import (
    ControlContext,
    ControlRequest,
    ControlResponse,
)
from topsailai.workspace.control_handlers.interrupt import _validate_target
from topsailai.workspace.folder_utils import get_pause_flag_path

logger = logging.getLogger(__name__)

DEFAULT_PAUSE_PROMPT = "Agent paused by control request. Continue? [yes/no] "
DEFAULT_PAUSE_ANSWER = "continue"


def _normalize_default(value) -> str:
    """Return a supported timeout default, falling back to continue."""
    if isinstance(value, str) and value.strip().lower() in ("continue", "interrupt"):
        return value.strip().lower()
    return DEFAULT_PAUSE_ANSWER


def _normalize_timeout(value) -> float:
    """Return a non-negative finite timeout; invalid values mean wait forever."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0
    return float(value) if value > 0 else 0.0


def build_pause_payload(request: ControlRequest) -> dict:
    """Build the marker payload from the request without trusting its shape."""
    payload = request.payload if isinstance(request.payload, dict) else {}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        prompt = DEFAULT_PAUSE_PROMPT
    reason = payload.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return {
        "reason": reason,
        "prompt": prompt,
        "timeout_seconds": _normalize_timeout(payload.get("timeout_seconds")),
        "default": _normalize_default(payload.get("default")),
    }


def _atomic_write_marker(marker_path: str, payload: dict) -> bool:
    """Atomically publish the pause marker so the agent never reads a partial file."""
    parent_dir = os.path.dirname(marker_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as error:
            logger.exception(
                "failed to create pause marker directory [%s]: %s", parent_dir, error
            )
            return False

    fd, tmp_path = tempfile.mkstemp(dir=parent_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp_path, marker_path)
        return True
    except OSError as error:
        logger.exception("failed to write pause marker [%s]: %s", marker_path, error)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


class PauseHandler(ControlHandler):
    """Write a pause-request marker for the target session process.

    Payload fields:
        reason (str, optional): Free-form text recorded in the marker.
        prompt (str, optional): Prompt shown when the agent blocks.
        timeout_seconds (number, optional): Positive wait budget; 0 waits forever.
        default (str, optional): ``continue`` or ``interrupt`` applied on timeout.
    """

    @property
    def action(self) -> str:
        return "pause"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        validated = _validate_target(context)
        if isinstance(validated, ControlResponse):
            return ControlResponse(
                request_id=request.request_id,
                status=validated.status,
                result=validated.result,
                error=validated.error,
            )

        session_id, pid, task_folder = validated
        marker_path = get_pause_flag_path(task_folder, session_id, pid)
        payload = build_pause_payload(request)

        if not _atomic_write_marker(marker_path, payload):
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"failed to write pause marker: {marker_path}",
            )

        logger.warning(
            "pause marker written for session=%s pid=%s: %s",
            session_id,
            pid,
            marker_path,
        )
        return ControlResponse(
            request_id=request.request_id,
            status="ok",
            result={
                "action": self.action,
                "session_id": session_id,
                "pid": pid,
                "flag_path": marker_path,
                "state": "pause_requested",
                "message": "pause requested; the agent blocks at its next safe point",
            },
        )


class ClearPauseHandler(ControlHandler):
    """Remove an unconsumed pause marker if it exists."""

    @property
    def action(self) -> str:
        return "clear_pause"

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        validated = _validate_target(context)
        if isinstance(validated, ControlResponse):
            return ControlResponse(
                request_id=request.request_id,
                status=validated.status,
                result=validated.result,
                error=validated.error,
            )

        session_id, pid, task_folder = validated
        marker_path = get_pause_flag_path(task_folder, session_id, pid)

        if not os.path.exists(marker_path):
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "flag_path": marker_path,
                    "removed": False,
                    "message": "no pause marker to clear",
                },
            )

        try:
            os.remove(marker_path)
            logger.warning(
                "pause marker cleared for session=%s pid=%s: %s",
                session_id,
                pid,
                marker_path,
            )
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "flag_path": marker_path,
                    "removed": True,
                    "message": "pause marker cleared",
                },
            )
        except OSError as error:
            logger.exception("failed to clear pause marker [%s]: %s", marker_path, error)
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"failed to clear pause marker: {error}",
            )
