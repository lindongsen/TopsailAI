"""
Interrupt control handlers for the Agent2LLM runtime.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Provide control-channel actions for hard and soft interrupts
"""

from __future__ import annotations

import logging
import os
import tempfile

from topsailai.ai_base.constants import ROLE_USER, STEP_NAME_OBSERVATION
from topsailai.utils import env_tool
from topsailai.workspace.control_channel.handler import ControlHandler
from topsailai.workspace.control_channel.protocol import (
    ControlContext,
    ControlRequest,
    ControlResponse,
)
from topsailai.workspace.folder_constants import (
    FOLDER_WORKSPACE_TASK,
    get_interrupt_flag_path,
)

logger = logging.getLogger(__name__)

INTERRUPT_FLAG_SUFFIX = ".session.agent2llm_interrupt.flag"
INTERRUPT_INJECT_SUFFIX = ".session.agent2llm_inject_messages.jsonl"
DEFAULT_SOFT_INTERRUPT_MESSAGE = (
    "Stop now. No more tool calls. Summarize completed progress, state the final conclusion, and end the task."
)


def _resolve_session_id(context: ControlContext) -> str | None:
    """Return session_id from context or environment."""
    if context.session_id:
        return context.session_id
    return env_tool.get_session_id()


def _resolve_pid(context: ControlContext) -> int | None:
    """Return pid from context or current process."""
    if context.pid is not None:
        return context.pid
    return os.getpid()


def _resolve_task_folder(context: ControlContext) -> str:
    """Return task_folder from context or default."""
    if context.task_folder:
        return context.task_folder
    return FOLDER_WORKSPACE_TASK


def _build_interrupt_flag_path(session_id: str, pid: int, task_folder: str) -> str:
    """Return the hard-interrupt flag file path."""
    return get_interrupt_flag_path(task_folder, session_id, pid)


def _build_inject_message_path(session_id: str, pid: int, task_folder: str) -> str:
    """Return the soft-interrupt JSONL inject file path."""
    return os.path.join(
        task_folder,
        f"{session_id}.{pid}{INTERRUPT_INJECT_SUFFIX}",
    )


def _validate_target(context: ControlContext) -> tuple[str, int, str] | ControlResponse:
    """Resolve session_id, pid, and task_folder; return error response on failure."""
    session_id = _resolve_session_id(context)
    pid = _resolve_pid(context)
    task_folder = _resolve_task_folder(context)

    if not session_id:
        return ControlResponse(
            request_id="",
            status="error",
            error="missing session_id",
        )
    if pid is None:
        return ControlResponse(
            request_id="",
            status="error",
            error="missing pid",
        )
    if not task_folder:
        return ControlResponse(
            request_id="",
            status="error",
            error="missing task_folder",
        )

    return session_id, pid, task_folder


def _atomic_write_flag(flag_path: str) -> bool:
    """Atomically write a hard-interrupt flag file.

    Uses a temporary file in the same directory followed by os.replace() so
    the agent never sees a partially written marker.
    """
    parent_dir = os.path.dirname(flag_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as e:
            logger.exception(
                "failed to create interrupt flag directory [%s]: %s", parent_dir, e
            )
            return False

    fd, tmp_path = tempfile.mkstemp(dir=parent_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("1")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, flag_path)
        return True
    except OSError as e:
        logger.exception("failed to write interrupt flag [%s]: %s", flag_path, e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def _append_jsonl_message(file_path: str, content: str) -> bool:
    """Append a user message to the JSONL inject file.

    Reuses the same payload shape as the existing file-based Agent2LLM message
    source so the consumer can parse it without any special handling.
    """
    from datetime import datetime, timezone

    parent_dir = os.path.dirname(file_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as e:
            logger.exception(
                "failed to create inject message directory [%s]: %s", parent_dir, e
            )
            return False

    msg = {
        "role": ROLE_USER,
        "content": content,
        "step_name": STEP_NAME_OBSERVATION,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(file_path, "a", encoding="utf-8") as f:
            import json

            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except OSError as e:
        logger.exception("failed to append inject message [%s]: %s", file_path, e)
        return False


class HardInterruptHandler(ControlHandler):
    """Write a hard-interrupt marker file for the target session."""

    @property
    def action(self) -> str:
        return "hard_interrupt"

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
        flag_path = _build_interrupt_flag_path(session_id, pid, task_folder)

        if _atomic_write_flag(flag_path):
            logger.warning(
                "hard interrupt flag written for session=%s pid=%s: %s",
                session_id,
                pid,
                flag_path,
            )
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "flag_path": flag_path,
                    "message": "hard interrupt requested",
                },
            )

        return ControlResponse(
            request_id=request.request_id,
            status="error",
            error=f"failed to write interrupt flag: {flag_path}",
        )


class SoftInterruptHandler(ControlHandler):
    """Append a terminate-and-summarize user message to the inject JSONL file."""

    @property
    def action(self) -> str:
        return "soft_interrupt"

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
        file_path = _build_inject_message_path(session_id, pid, task_folder)
        content = request.payload.get("message") or DEFAULT_SOFT_INTERRUPT_MESSAGE

        if _append_jsonl_message(file_path, content):
            logger.warning(
                "soft interrupt message appended for session=%s pid=%s: %s",
                session_id,
                pid,
                file_path,
            )
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "file_path": file_path,
                    "message": "soft interrupt message appended",
                },
            )

        return ControlResponse(
            request_id=request.request_id,
            status="error",
            error=f"failed to append inject message: {file_path}",
        )


class ClearInterruptHandler(ControlHandler):
    """Remove the hard-interrupt flag file if it exists."""

    @property
    def action(self) -> str:
        return "clear_interrupt"

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
        flag_path = _build_interrupt_flag_path(session_id, pid, task_folder)

        if not os.path.exists(flag_path):
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "flag_path": flag_path,
                    "removed": False,
                    "message": "no interrupt flag to clear",
                },
            )

        try:
            os.remove(flag_path)
            logger.warning(
                "hard interrupt flag cleared for session=%s pid=%s: %s",
                session_id,
                pid,
                flag_path,
            )
            return ControlResponse(
                request_id=request.request_id,
                status="ok",
                result={
                    "action": self.action,
                    "session_id": session_id,
                    "pid": pid,
                    "flag_path": flag_path,
                    "removed": True,
                    "message": "interrupt flag cleared",
                },
            )
        except OSError as e:
            logger.exception("failed to clear interrupt flag [%s]: %s", flag_path, e)
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"failed to clear interrupt flag: {e}",
            )
