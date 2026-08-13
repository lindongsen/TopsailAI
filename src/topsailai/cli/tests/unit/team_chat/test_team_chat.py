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
def clear_env(tmp_path: Path) -> None:
    """Reset relevant variables and point result saving at a temp file."""
    os.environ.pop("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", None)
    os.environ.pop("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER", None)
    out_file = tmp_path / "out.txt"
    os.environ["TOPSAILAI_SAVE_RESULT_TO_FILE"] = str(out_file)
    yield out_file
    os.environ.pop("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", None)
    os.environ.pop("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER", None)
    os.environ.pop("TOPSAILAI_SAVE_RESULT_TO_FILE", None)


def _patch_deps(name: str, answer: str):
    """Patch team_chat dependencies and return the saved-output reader."""
    chat_instance = mock.MagicMock()
    chat_instance.chat.return_value = answer
    patches = [
        mock.patch.object(team_chat, "get_member_name", return_value=name),
        mock.patch.object(team_chat, "get_member_prompt", return_value="prompt\n"),
        mock.patch.object(team_chat, "get_llm_chat", return_value=chat_instance),
    ]
    for p in patches:
        p.start()
    return patches


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
