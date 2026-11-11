"""
Unit tests for stale session-flag cleanup in workspace/agent_shell.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-07
Purpose: Verify startup cleanup removes both the hard-interrupt flag and the
         pause marker, and that the pause marker is registered as a session
         owner suffix so session cleanup is never blocked by it
"""

import json
import socket
from unittest.mock import patch

import pytest

from topsailai.context.session_activity import ActivityState, SessionActivityProbe
from topsailai.workspace import agent_shell


def _patch_task_folder(tmp_path):
    """Point the task folder at *tmp_path* for the duration of a test."""
    return patch(
        "topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK",
        str(tmp_path),
    )


def _flag(tmp_path, suffix, session_id="session", pid=123):
    """Create one session-scoped flag file and return its path."""
    path = tmp_path / f"{session_id}.{pid}.session.{suffix}"
    path.write_text("{}", encoding="utf-8")
    return path


def test_cleanup_removes_interrupt_flag_and_pause_marker(tmp_path):
    """Startup must not inherit an interrupted or paused state."""
    interrupt_flag = _flag(tmp_path, "agent2llm_interrupt.flag")
    pause_marker = _flag(tmp_path, "agent2llm_pause.flag")

    with _patch_task_folder(tmp_path):
        agent_shell._cleanup_stale_interrupt_flag("session", 123)

    assert not interrupt_flag.exists()
    assert not pause_marker.exists()


def test_cleanup_keeps_other_session_flags(tmp_path):
    """Cleanup is scoped to the exact session and pid."""
    other_session = _flag(tmp_path, "agent2llm_pause.flag", session_id="other")
    other_pid = _flag(tmp_path, "agent2llm_pause.flag", pid=456)

    with _patch_task_folder(tmp_path):
        agent_shell._cleanup_stale_interrupt_flag("session", 123)

    assert other_session.exists()
    assert other_pid.exists()


def test_cleanup_without_session_identity_touches_nothing(tmp_path):
    """An unknown session identity must not remove another process's marker."""
    pause_marker = _flag(tmp_path, "agent2llm_pause.flag")

    with _patch_task_folder(tmp_path):
        agent_shell._cleanup_stale_interrupt_flag(None, 123)
        agent_shell._cleanup_stale_interrupt_flag("session", None)

    assert pause_marker.exists()


def test_cleanup_tolerates_missing_files(tmp_path):
    """Absent flags are a normal startup condition."""
    with _patch_task_folder(tmp_path):
        agent_shell._cleanup_stale_interrupt_flag("session", 123)


def test_cleanup_logs_removal_failure_without_raising(tmp_path):
    """A removal failure is reported and never blocks startup."""
    pause_marker = _flag(tmp_path, "agent2llm_pause.flag")

    with _patch_task_folder(tmp_path), \
            patch.object(agent_shell.os, "remove", side_effect=OSError("denied")), \
            patch.object(agent_shell.logger, "warning") as warning:
        agent_shell._cleanup_stale_interrupt_flag("session", 123)

    assert pause_marker.exists()
    descriptions = [call.args[1] for call in warning.call_args_list]
    assert "pause marker" in descriptions


def test_pause_marker_is_a_recognized_session_owner(tmp_path):
    """An unconsumed pause marker must not block session cleanup."""
    metadata = {
        "session_id": "session",
        "pid": 123,
        "hostname": socket.gethostname(),
        "status": "completed",
    }
    (tmp_path / "session.123.session.meta").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    _flag(tmp_path, "agent2llm_pause.flag")

    probe = SessionActivityProbe((tmp_path,), lambda pid: ActivityState.STOPPED)

    assert probe.can_clean("session")


def test_unknown_suffix_still_blocks_session_cleanup(tmp_path):
    """The pause registration must not widen the owner whitelist."""
    metadata = {
        "session_id": "session",
        "pid": 123,
        "hostname": socket.gethostname(),
        "status": "completed",
    }
    (tmp_path / "session.123.session.meta").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    _flag(tmp_path, "agent2llm_pause_flag_typo")

    probe = SessionActivityProbe((tmp_path,), lambda pid: ActivityState.STOPPED)

    assert not probe.can_clean("session")


@pytest.mark.parametrize("suffix", ["agent2llm_interrupt.flag", "agent2llm_pause.flag"])
def test_cleanup_handles_each_registered_flag(tmp_path, suffix):
    """Every registered flag suffix is removable through the shared helper."""
    flag_path = _flag(tmp_path, suffix)

    with _patch_task_folder(tmp_path):
        agent_shell._cleanup_stale_session_flag("session", 123, suffix, "test flag")

    assert not flag_path.exists()
