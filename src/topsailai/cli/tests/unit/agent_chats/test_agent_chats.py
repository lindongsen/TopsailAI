"""Unit tests for cli/agent_chats.py agent role.

Verifies that the multi-turn agent chat entry point explicitly creates its
agent with the ``manager`` role, so role-gated behavior does not depend on the
``TOPSAILAI_AGENT_ROLE`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load agent_chats as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import agent_chats


@pytest.fixture(autouse=True)
def clear_agent_role_env() -> None:
    """Ensure the role env var cannot influence the resolved role."""
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)
    yield
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)


def test_agent_role_is_manager() -> None:
    """get_agent_chat receives agent_role='manager' explicitly."""
    with mock.patch.object(agent_chats, "get_agent_chat") as mock_get_chat:
        agent_chats.main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


def test_agent_role_manager_overrides_env_worker() -> None:
    """An explicit worker env value must not downgrade the entry-point role."""
    os.environ["TOPSAILAI_AGENT_ROLE"] = "worker"
    with mock.patch.object(agent_chats, "get_agent_chat") as mock_get_chat:
        agent_chats.main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


def test_agent_tool_remains_disabled() -> None:
    """The pre-existing agent_tool restriction must be preserved."""
    with mock.patch.object(agent_chats, "get_agent_chat") as mock_get_chat:
        agent_chats.main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["disabled_tools"] == ["agent_tool"]
