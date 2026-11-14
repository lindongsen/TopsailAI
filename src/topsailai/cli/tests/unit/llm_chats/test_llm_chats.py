"""Unit tests for cli/llm_chats.py closed-input handling.

The multi-turn LLM chat prompts for a message before the first turn and again
after every turn. Once the input channel is closed, neither prompt can ever be
answered, so the entry point must end the conversation instead of letting
``EOFError`` escape as a traceback or reprompting without bound.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load llm_chats as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import llm_chats


def _patch_chat():
    """Patch the chat factory so no model or session is created."""
    return mock.patch.object(llm_chats, "get_llm_chat")


def test_closed_channel_before_first_message_ends_the_chat() -> None:
    """A closed channel at the first prompt returns instead of raising."""
    with _patch_chat() as mock_get_chat:
        mock_get_chat.side_effect = EOFError()
        llm_chats.main()

    mock_get_chat.assert_called_once()


def test_closed_channel_before_first_message_reports_the_condition() -> None:
    """The operator is told why nothing happened."""
    with _patch_chat() as mock_get_chat:
        mock_get_chat.side_effect = EOFError()
        with mock.patch("builtins.print") as mock_print:
            llm_chats.main()

    printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
    assert "Input channel closed" in printed


def test_closed_channel_after_a_turn_ends_the_chat() -> None:
    """A closed channel at the next-turn prompt breaks the loop cleanly."""
    with _patch_chat() as mock_get_chat:
        chat = mock_get_chat.return_value
        with mock.patch.object(llm_chats, "input_message", side_effect=EOFError()):
            llm_chats.main()

    # The first turn ran, then the prompt failed and the loop ended.
    assert chat.chat.call_count == 1


def test_closed_channel_does_not_reprompt() -> None:
    """The prompt is never repeated once the channel is closed."""
    with _patch_chat():
        with mock.patch.object(llm_chats, "input_message", side_effect=EOFError()) as mock_input:
            llm_chats.main()

    assert mock_input.call_count == 1


def test_unrelated_failure_is_not_swallowed() -> None:
    """Only ``EOFError`` is handled; other failures keep their contract."""
    with _patch_chat() as mock_get_chat:
        mock_get_chat.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            llm_chats.main()
