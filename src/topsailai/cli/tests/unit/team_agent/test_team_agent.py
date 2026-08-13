"""Unit tests for cli/team_agent.py symbol-start gating.

Verifies that TOPSAILAI_NEED_SYMBOL_FOR_ANSWER controls whether the agent
chat receives ``need_symbol_for_answer`` as an explicit parameter, resolved
once at the entry boundary (parameter priority over environment variables).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load team_agent as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import team_agent


@pytest.fixture(autouse=True)
def clear_env() -> None:
    """Ensure the gate variable starts unset for every test."""
    os.environ.pop("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", None)
    yield
    os.environ.pop("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", None)


@mock.patch.object(team_agent, "get_member_name", return_value="member-a")
@mock.patch.object(team_agent, "get_system_prompt", return_value="system-prompt")
@mock.patch.object(team_agent, "get_session_head_tail_offset", return_value=7)
def test_gate_disabled_when_unset(mock_offset, mock_prompt, mock_name) -> None:
    """Unset gate resolves to False and is passed explicitly to run()."""
    with mock.patch.object(team_agent, "get_agent_chat") as mock_get_chat:
        chat_instance = mock_get_chat.return_value
        team_agent.main()

    _, kwargs = chat_instance.run.call_args
    assert kwargs["need_symbol_for_answer"] is False


@mock.patch.object(team_agent, "get_member_name", return_value="member-a")
@mock.patch.object(team_agent, "get_system_prompt", return_value="system-prompt")
@mock.patch.object(team_agent, "get_session_head_tail_offset", return_value=7)
def test_gate_enabled_when_set_to_one(mock_offset, mock_prompt, mock_name) -> None:
    """Setting the gate to '1' resolves to True and is passed explicitly."""
    os.environ["TOPSAILAI_NEED_SYMBOL_FOR_ANSWER"] = "1"
    with mock.patch.object(team_agent, "get_agent_chat") as mock_get_chat:
        chat_instance = mock_get_chat.return_value
        team_agent.main()

    _, kwargs = chat_instance.run.call_args
    assert kwargs["need_symbol_for_answer"] is True
