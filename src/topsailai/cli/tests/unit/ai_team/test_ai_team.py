"""Unit tests for cli/ai_team.py agent role.

Verifies that the team manager entry point explicitly creates its agent with
the ``manager`` role, so role-gated behavior does not depend on the
``TOPSAILAI_AGENT_ROLE`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load ai_team as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ai_team mutates TOPSAILAI_ENABLED_TOOLS at import time; keep it out of the
# ambient process environment for the rest of the suite.
_saved_enabled_tools = os.environ.get("TOPSAILAI_ENABLED_TOOLS")

import ai_team

if _saved_enabled_tools is None:
    os.environ.pop("TOPSAILAI_ENABLED_TOOLS", None)
else:
    os.environ["TOPSAILAI_ENABLED_TOOLS"] = _saved_enabled_tools


@pytest.fixture(autouse=True)
def clear_agent_role_env() -> None:
    """Ensure the role env var cannot influence the resolved role."""
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)
    yield
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)


@mock.patch.object(ai_team, "get_session_head_tail_offset", return_value=7)
@mock.patch.object(ai_team, "get_session_id", return_value="session-test")
@mock.patch.object(ai_team, "get_members_cache", return_value=[])
@mock.patch.object(ai_team, "generate_system_prompt", return_value="system-prompt")
@mock.patch.object(ai_team, "get_manager_name", return_value="AIManager.Manager")
def test_agent_role_is_manager(mock_name, mock_prompt, mock_members, mock_session, mock_offset) -> None:
    """get_agent_chat receives agent_role='manager' explicitly."""
    with mock.patch.object(ai_team, "get_agent_chat") as mock_get_chat:
        ai_team.main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


@mock.patch.object(ai_team, "get_session_head_tail_offset", return_value=7)
@mock.patch.object(ai_team, "get_session_id", return_value="session-test")
@mock.patch.object(ai_team, "get_members_cache", return_value=[])
@mock.patch.object(ai_team, "generate_system_prompt", return_value="system-prompt")
@mock.patch.object(ai_team, "get_manager_name", return_value="AIManager.Manager")
def test_agent_role_manager_overrides_env_worker(mock_name, mock_prompt, mock_members, mock_session, mock_offset) -> None:
    """An explicit worker env value must not downgrade the manager role."""
    os.environ["TOPSAILAI_AGENT_ROLE"] = "worker"
    with mock.patch.object(ai_team, "get_agent_chat") as mock_get_chat:
        ai_team.main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


@mock.patch.object(ai_team, "get_session_head_tail_offset", return_value=7)
@mock.patch.object(ai_team, "get_session_id", return_value="session-test")
@mock.patch.object(ai_team, "get_members_cache", return_value=[])
@mock.patch.object(ai_team, "generate_system_prompt", return_value="system-prompt")
@mock.patch.object(ai_team, "get_manager_name", return_value="AIManager.Manager")
def test_agent_tool_remains_disabled(mock_name, mock_prompt, mock_members, mock_session, mock_offset) -> None:
    """The pre-existing agent_tool restriction must be preserved."""
    with mock.patch.object(ai_team, "get_agent_chat") as mock_get_chat:
        ai_team.main()

    _, kwargs = mock_get_chat.call_args
    assert "agent_tool" in kwargs["disabled_tools"]
