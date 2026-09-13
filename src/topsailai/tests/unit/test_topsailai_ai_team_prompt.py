"""Unit tests for the canonical AI team prompt composer.

Author: DawsonLin
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from topsailai.ai_team.prompt import (
    TeamPromptSegments,
    compose_team_prompt,
    load_team_values,
    resolve_runtime_team_prompt,
)


def test_compose_team_prompt_uses_canonical_order() -> None:
    """All prompt layers are composed in the accepted canonical order."""
    segments = TeamPromptSegments(
        base_system_prompt="BASE",
        runtime_team_prompt="RUNTIME",
        team_values="TEAM_VALUES",
        team_inventory="INVENTORY",
        role_prompt="ROLE",
        member_values="MEMBER_VALUES",
        extra_prompts="EXTRA",
    )

    assert compose_team_prompt(segments) == (
        "BASE\nRUNTIME\nTEAM_VALUES\nINVENTORY\nROLE\nMEMBER_VALUES\nEXTRA"
    )


def test_load_team_values_returns_empty_when_file_is_missing(tmp_path: Path) -> None:
    """A missing optional team values file preserves legacy behavior."""
    assert load_team_values(str(tmp_path)) == ""
    assert load_team_values(None) == ""


def test_load_team_values_returns_empty_for_empty_file(tmp_path: Path) -> None:
    """An empty team values file contributes no prompt segment."""
    (tmp_path / "team.values").write_text(" \n", encoding="utf-8")

    assert load_team_values(str(tmp_path)) == ""


def test_load_team_values_propagates_read_failure(tmp_path: Path) -> None:
    """An existing but unreadable values file fails closed."""
    values_path = tmp_path / "team.values"
    values_path.write_text("TEAM_VALUES", encoding="utf-8")

    with patch("builtins.open", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError, match="denied"):
            load_team_values(str(tmp_path))


def test_precomposed_provenance_skips_team_wide_segments() -> None:
    """Explicit precomposed provenance prevents team-wide reinjection."""
    segments = TeamPromptSegments(
        base_system_prompt="BASE_WITH_RUNTIME_AND_TEAM_VALUES",
        runtime_team_prompt="RUNTIME",
        team_values="TEAM_VALUES",
        role_prompt="ROLE",
        member_values="MEMBER_VALUES",
    )

    result = compose_team_prompt(segments, team_prompt_precomposed=True)

    assert result == "BASE_WITH_RUNTIME_AND_TEAM_VALUES\nROLE\nMEMBER_VALUES"
    assert "\nRUNTIME\n" not in result


def test_team_values_are_opaque_and_member_files_are_not_loaded(tmp_path: Path) -> None:
    """The team loader preserves key-like text and ignores member values files."""
    team_content = "priority=shared\nmode: collaborative"
    (tmp_path / "team.values").write_text(team_content, encoding="utf-8")
    (tmp_path / "member-a.values").write_text("PRIVATE_A", encoding="utf-8")
    (tmp_path / "member-b.values").write_text("PRIVATE_B", encoding="utf-8")

    result = load_team_values(str(tmp_path))

    assert result == team_content
    assert "PRIVATE_A" not in result
    assert "PRIVATE_B" not in result


def test_runtime_prompt_and_team_values_are_cumulative(tmp_path: Path) -> None:
    """Runtime team prompt and persistent team values accumulate without override."""
    (tmp_path / "team.values").write_text("TEAM_VALUES", encoding="utf-8")
    runtime_prompt = resolve_runtime_team_prompt("RUNTIME_TEAM_PROMPT")
    segments = TeamPromptSegments(
        runtime_team_prompt=runtime_prompt,
        team_values=load_team_values(str(tmp_path)),
    )

    result = compose_team_prompt(segments)

    assert result == "RUNTIME_TEAM_PROMPT\nTEAM_VALUES"


def test_empty_optional_segments_preserve_base_prompt_exactly() -> None:
    """Missing optional layers do not alter an existing base prompt."""
    assert compose_team_prompt(TeamPromptSegments(base_system_prompt="BASE\n")) == "BASE\n"
