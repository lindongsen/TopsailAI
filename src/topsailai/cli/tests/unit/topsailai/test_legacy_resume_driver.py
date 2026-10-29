"""Tests for legacy resume driver parsing and forwarding."""

from __future__ import annotations

from unittest.mock import patch

from cli_topsailai import core
from cli_topsailai.legacy_resume_cli import parse_args


def test_default_and_explicit_driver_parse():
    """The parser leaves default selection to the resume boundary."""
    assert parse_args(["session-1"], target_name="session_id").driver is None
    assert parse_args(
        ["session-1", "--driver", "ai-team-flow-dev"], target_name="session_id"
    ).driver == "ai-team-flow-dev"


def test_identical_repeated_driver_is_accepted():
    """Repeated identical options are harmless."""
    args = parse_args(
        ["session-1", "-d", "topsailai_agent_chats", "--driver", "topsailai_agent_chats"],
        target_name="session_id",
    )
    assert args.driver == "topsailai_agent_chats"


def test_conflicting_driver_is_rejected_before_lookup():
    """Conflicting options fail before project lookup or launch."""
    with patch("cli_topsailai.project_scope.build_project_list") as build:
        result = core._try_handle_project_subcommand(
            [
                "project", "resume", "session-1", "-d",
                "topsailai_agent_chats", "--driver", "ai-team-flow-dev",
            ]
        )
    assert result == 2
    build.assert_not_called()


def test_project_resume_forwards_explicit_driver():
    """The direct project route forwards the selected driver."""
    entries = [{"session_id": "session-1", "status": "Idle", "project_workspace": "/tmp"}]
    with patch("cli_topsailai.project_scope.build_project_list", return_value=entries), patch(
        "cli_topsailai.project_scope.resume_session", return_value=True
    ) as resume:
        result = core._try_handle_project_subcommand(
            ["project", "resume", "session-1", "-d", "topsailai_agent_plan_tasks"]
        )
    assert result == 0
    assert resume.call_args.kwargs["driver"] == "topsailai_agent_plan_tasks"


def test_workspace_log_forwards_explicit_driver():
    """The workspace adapter forwards a parsed driver to the legacy boundary."""
    logs = [{"session_id": "session-1", "status": "Idle", "project_workspace": "/tmp"}]
    with patch("cli_topsailai.project_scope.resume_session") as resume:
        assert core._resume_from_workspace_log(
            "1", logs, agent_mode="raw", driver="ai-team-flow-dev"
        ) is True
    assert resume.call_args.kwargs["driver"] == "ai-team-flow-dev"
