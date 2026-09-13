"""Core integration tests for the simulated Team plugin prompt contract.

These tests simulate, but do not execute, the external ``/work/ai_team`` plugin.

Author: DawsonLin
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from topsailai.ai_team import manager, member_agent
from topsailai.ai_team.role import get_member_prompt

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import team_agent
import team_chat


AI_TEAM_HEADING = "# AI Team"
RUNTIME_MARKER = f"{AI_TEAM_HEADING}\nRUNTIME_TEAM_MARKER"
TEAM_MARKER = "TEAM_VALUES_MARKER"
MEMBER_MARKER = "MEMBER_PRIVATE_MARKER"
BASE_MARKER = "BASE_SYSTEM_MARKER"


@pytest.fixture
def team_directory(tmp_path: Path) -> Path:
    """Create one isolated team directory for a Member and shared values."""
    team_path = tmp_path / "team"
    team_path.mkdir()
    (team_path / "member-a.member").write_text(
        "Member inventory marker", encoding="utf-8"
    )
    (team_path / "member-a.values").write_text(MEMBER_MARKER, encoding="utf-8")
    (team_path / "team.values").write_text(TEAM_MARKER, encoding="utf-8")
    return team_path


@pytest.fixture(autouse=True)
def isolated_team_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove prompt state so every integration case controls its own sources."""
    for key in (
        "SYSTEM_PROMPT",
        "SYSTEM_PROMPT_EXTRA_FILES",
        "TOPSAILAI_SYSTEM_PROMPT",
        "TOPSAILAI_TEAM_PATH",
        "TOPSAILAI_TEAM_PROMPT",
        "TOPSAILAI_TEAM_PROMPT_CONTENT",
        "TOPSAILAI_SAVE_RESULT_TO_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    manager.g_members.clear()
    yield
    manager.g_members.clear()


def _assert_order(content: str, markers: list[str]) -> None:
    """Assert that each marker occurs once and follows the declared order."""
    positions = []
    for marker in markers:
        assert content.count(marker) == 1
        positions.append(content.index(marker))
    assert positions == sorted(positions)


def test_manager_to_plugin_simulation_matches_direct_member(
    team_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate Manager handoff and prove shared content is not reloaded."""
    monkeypatch.setenv("TOPSAILAI_TEAM_PATH", str(team_directory))
    monkeypatch.setenv("TOPSAILAI_TEAM_PROMPT", RUNTIME_MARKER)
    monkeypatch.setenv("SYSTEM_PROMPT", BASE_MARKER)

    manager_prompt = manager.generate_system_prompt()
    plugin_content = os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"]
    inventory_marker = "Member inventory marker"

    _assert_order(
        manager_prompt,
        [BASE_MARKER, RUNTIME_MARKER, TEAM_MARKER, inventory_marker],
    )
    _assert_order(
        plugin_content,
        [RUNTIME_MARKER, TEAM_MARKER, inventory_marker],
    )

    plugin_prompt_file = team_directory / "plugin-system-prompt.md"
    plugin_prompt_file.write_text(
        plugin_content + "\n" + get_member_prompt("member-a"),
        encoding="utf-8",
    )
    monkeypatch.setenv("SYSTEM_PROMPT", str(plugin_prompt_file))
    monkeypatch.setenv("TOPSAILAI_SYSTEM_PROMPT", str(plugin_prompt_file))
    agent_chat = mock.MagicMock()
    with (
        mock.patch.object(team_agent, "get_member_name", return_value="member-a"),
        mock.patch.object(team_agent, "get_agent_chat", return_value=agent_chat) as get_agent_chat,
        mock.patch.object(
            member_agent.team_prompt,
            "load_team_values",
            side_effect=AssertionError("precomposed Member reloaded team.values"),
        ) as load_team_values,
    ):
        team_agent.main()
    load_team_values.assert_not_called()
    plugin_member_prompt = get_agent_chat.call_args.kwargs["system_prompt"]

    monkeypatch.setenv("SYSTEM_PROMPT", BASE_MARKER)
    direct_member_prompt = member_agent.get_system_prompt("member-a")

    for content in (plugin_member_prompt, direct_member_prompt):
        assert content.count(AI_TEAM_HEADING) == 1
        assert content.count(RUNTIME_MARKER) == 1
        assert content.count(TEAM_MARKER) == 1
        assert content.count(MEMBER_MARKER) == 1
    assert TEAM_MARKER in plugin_member_prompt
    assert TEAM_MARKER in direct_member_prompt


def test_team_agent_and_chat_use_equivalent_member_composition(
    team_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise both CLI entries and compare their canonical Member prompts."""
    monkeypatch.setenv("TOPSAILAI_TEAM_PATH", str(team_directory))
    monkeypatch.setenv("TOPSAILAI_TEAM_PROMPT", RUNTIME_MARKER)
    monkeypatch.setenv("SYSTEM_PROMPT", BASE_MARKER)

    agent_chat = mock.MagicMock()
    agent_chat.run.return_value = "agent answer"
    llm_chat = mock.MagicMock()
    llm_chat.chat.return_value = "chat answer"

    with (
        mock.patch.object(team_agent, "get_member_name", return_value="member-a"),
        mock.patch.object(team_agent, "get_agent_chat", return_value=agent_chat) as get_agent_chat,
        mock.patch.object(team_chat, "get_member_name", return_value="member-a"),
        mock.patch.object(team_chat, "get_llm_chat", return_value=llm_chat) as get_llm_chat,
    ):
        team_agent.main()
        team_chat.main()

    agent_prompt = get_agent_chat.call_args.kwargs["system_prompt"]
    chat_prompt = get_llm_chat.call_args.kwargs["system_prompt"]
    assert agent_prompt == chat_prompt
    _assert_order(
        agent_prompt,
        [BASE_MARKER, RUNTIME_MARKER, TEAM_MARKER, MEMBER_MARKER],
    )
    assert "Output Required" not in chat_prompt
    assert "Output Required" in get_llm_chat.call_args.kwargs["more_prompt"]


@pytest.mark.parametrize("create_empty_file", [False, True])
def test_missing_or_empty_team_values_preserves_member_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_empty_file: bool,
) -> None:
    """Treat a missing or empty shared file as a compatibility no-op."""
    team_path = tmp_path / "team"
    team_path.mkdir()
    (team_path / "member-a.values").write_text(MEMBER_MARKER, encoding="utf-8")
    if create_empty_file:
        (team_path / "team.values").write_text("", encoding="utf-8")

    monkeypatch.setenv("TOPSAILAI_TEAM_PATH", str(team_path))
    monkeypatch.setenv("SYSTEM_PROMPT", BASE_MARKER)

    result = member_agent.get_system_prompt("member-a")

    assert result.count(BASE_MARKER) == 1
    assert result.count(MEMBER_MARKER) == 1
    assert TEAM_MARKER not in result


def test_unreadable_team_values_fails_closed(
    team_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Propagate a read error from an existing shared values file."""
    monkeypatch.setenv("TOPSAILAI_TEAM_PATH", str(team_directory))
    monkeypatch.setenv("SYSTEM_PROMPT", BASE_MARKER)

    with mock.patch(
        "topsailai.ai_team.prompt.open",
        side_effect=PermissionError("team.values denied"),
    ):
        with pytest.raises(PermissionError, match="team.values denied"):
            member_agent.get_system_prompt("member-a")
