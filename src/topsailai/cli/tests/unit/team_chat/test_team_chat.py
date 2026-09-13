"""Unit tests for cli/team_chat.py symbol-start gating.

Verifies that TOPSAILAI_NEED_SYMBOL_FOR_ANSWER controls whether the answer
prefix is applied, resolved once at the entry boundary. Content precedence:
explicit TOPSAILAI_SYMBOL_STARTSWITH_ANSWER > member-name fallback > none.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import team_chat


@pytest.fixture(autouse=True)
def clear_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Reset prompt state and point result saving at a temporary file."""
    for key in (
        "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER",
        "TOPSAILAI_SYMBOL_STARTSWITH_ANSWER",
        "TOPSAILAI_SYSTEM_PROMPT",
        "TOPSAILAI_TEAM_PROMPT_CONTENT",
    ):
        monkeypatch.delenv(key, raising=False)
    out_file = tmp_path / "out.txt"
    monkeypatch.setenv("TOPSAILAI_SAVE_RESULT_TO_FILE", str(out_file))
    return out_file


def _patch_deps(name: str, answer: str):
    """Patch team_chat dependencies and return the active patches."""
    chat_instance = mock.MagicMock()
    chat_instance.chat.return_value = answer
    patches = [
        mock.patch.object(team_chat, "get_member_name", return_value=name),
        mock.patch.object(
            team_chat,
            "get_system_prompt",
            return_value="canonical-member-prompt",
        ),
        mock.patch.object(team_chat, "get_llm_chat", return_value=chat_instance),
    ]
    for patcher in patches:
        patcher.start()
    return patches


def test_main_uses_canonical_member_prompt_with_chat_output_requirement(
    clear_env: Path,
) -> None:
    """Pass canonical Member content as the base and chat output text last."""
    patches = _patch_deps("member-a", "answer")
    try:
        team_chat.main()
        team_chat.get_system_prompt.assert_called_once_with(
            "member-a", team_prompt_precomposed=False
        )
        _, kwargs = team_chat.get_llm_chat.call_args
    finally:
        for patcher in patches:
            patcher.stop()

    assert kwargs["system_prompt"] == "canonical-member-prompt"
    assert kwargs["more_prompt"] == (
        "\n# Output Required\n"
        "Directly output the content without any formatting.\n"
    )


def test_flag_off_no_prefix_even_with_explicit_symbol(clear_env: Path) -> None:
    """Gate unset => no prefix regardless of SYMBOL_STARTSWITH_ANSWER."""
    os.environ["TOPSAILAI_SYMBOL_STARTSWITH_ANSWER"] = ">> "
    patches = _patch_deps("member-a", "hello world")
    try:
        team_chat.main()
    finally:
        for p in patches:
            p.stop()
    assert clear_env.read_text() == "hello world"


def test_flag_on_uses_explicit_symbol(clear_env: Path) -> None:
    """Flag on + explicit symbol => exact prefix used."""
    os.environ["TOPSAILAI_NEED_SYMBOL_FOR_ANSWER"] = "1"
    os.environ["TOPSAILAI_SYMBOL_STARTSWITH_ANSWER"] = ">> "
    patches = _patch_deps("member-a", "hello world")
    try:
        team_chat.main()
    finally:
        for p in patches:
            p.stop()
    assert clear_env.read_text() == ">> hello world"


def test_flag_on_falls_back_to_member_name(clear_env: Path) -> None:
    """Flag on without explicit symbol => uses From '<name>':\n prefix."""
    os.environ["TOPSAILAI_NEED_SYMBOL_FOR_ANSWER"] = "1"
    patches = _patch_deps("member-b", "hi there")
    try:
        team_chat.main()
    finally:
        for p in patches:
            p.stop()
    assert clear_env.read_text() == "From 'member-b':\nhi there"


def test_flag_on_empty_name_and_no_symbol_adds_nothing(clear_env: Path) -> None:
    """Flag on but no name and no explicit symbol => unchanged answer."""
    os.environ["TOPSAILAI_NEED_SYMBOL_FOR_ANSWER"] = "true"
    patches = _patch_deps("", "plain answer")
    try:
        team_chat.main()
    finally:
        for p in patches:
            p.stop()
    assert clear_env.read_text() == "plain answer"
