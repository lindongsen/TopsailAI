"""Unit tests for the LLM chat print-enabled default.

``llm_chat`` and ``llm_chats`` must treat an absent ``TOPSAILAI_PRINT_ENABLED``
as ``0``, so framework display output stays off unless the caller asks for it.
An explicitly configured value, including an empty one, must be preserved
because the core reader treats a present value as configured.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load the entry points as modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import llm_chat
import llm_chats
from cli_topsailai.chat_env import (
    PRINT_ENABLED_DEFAULT,
    PRINT_ENABLED_ENV_KEY,
    apply_chat_env_defaults,
    read_print_enabled,
)


def test_default_value_is_zero() -> None:
    """The documented default keeps display output off."""
    assert PRINT_ENABLED_DEFAULT == "0"
    assert PRINT_ENABLED_ENV_KEY == "TOPSAILAI_PRINT_ENABLED"


def test_absent_variable_is_filled_with_zero() -> None:
    """An absent variable is the case the default exists for."""
    environ: dict[str, str] = {}

    apply_chat_env_defaults(environ)

    assert environ[PRINT_ENABLED_ENV_KEY] == "0"


def test_configured_value_is_preserved() -> None:
    """A caller that asked for output keeps its value."""
    environ = {PRINT_ENABLED_ENV_KEY: "1"}

    apply_chat_env_defaults(environ)

    assert environ[PRINT_ENABLED_ENV_KEY] == "1"


def test_empty_value_counts_as_configured() -> None:
    """An empty value is present, so it is not replaced by the default."""
    environ = {PRINT_ENABLED_ENV_KEY: ""}

    apply_chat_env_defaults(environ)

    assert environ[PRINT_ENABLED_ENV_KEY] == ""


def test_read_reports_the_default_when_absent() -> None:
    """Reading an absent variable reports the same value the default writes."""
    assert read_print_enabled({}) == PRINT_ENABLED_DEFAULT


def test_read_reports_the_configured_value() -> None:
    """Reading a configured variable reports it verbatim."""
    assert read_print_enabled({PRINT_ENABLED_ENV_KEY: "1"}) == "1"


def test_llm_chat_defaults_the_variable_when_absent(monkeypatch) -> None:
    """The single-turn entry point pins the default before creating a chat."""
    monkeypatch.delenv(PRINT_ENABLED_ENV_KEY, raising=False)

    with mock.patch.object(llm_chat, "get_llm_chat"):
        llm_chat.main()

    assert os.environ[PRINT_ENABLED_ENV_KEY] == "0"


def test_llm_chat_preserves_a_configured_value(monkeypatch) -> None:
    """The single-turn entry point never overwrites a caller's value."""
    monkeypatch.setenv(PRINT_ENABLED_ENV_KEY, "1")

    with mock.patch.object(llm_chat, "get_llm_chat"):
        llm_chat.main()

    assert os.environ[PRINT_ENABLED_ENV_KEY] == "1"


def test_llm_chats_defaults_the_variable_when_absent(monkeypatch) -> None:
    """The multi-turn entry point pins the default before creating a chat."""
    monkeypatch.delenv(PRINT_ENABLED_ENV_KEY, raising=False)

    with mock.patch.object(llm_chats, "get_llm_chat"):
        with mock.patch.object(llm_chats, "input_message", side_effect=EOFError()):
            llm_chats.main()

    assert os.environ[PRINT_ENABLED_ENV_KEY] == "0"


def test_llm_chats_preserves_a_configured_value(monkeypatch) -> None:
    """The multi-turn entry point never overwrites a caller's value."""
    monkeypatch.setenv(PRINT_ENABLED_ENV_KEY, "1")

    with mock.patch.object(llm_chats, "get_llm_chat"):
        with mock.patch.object(llm_chats, "input_message", side_effect=EOFError()):
            llm_chats.main()

    assert os.environ[PRINT_ENABLED_ENV_KEY] == "1"


def test_llm_chats_preserves_an_empty_value(monkeypatch) -> None:
    """An explicitly empty value survives the multi-turn entry point."""
    monkeypatch.setenv(PRINT_ENABLED_ENV_KEY, "")

    with mock.patch.object(llm_chats, "get_llm_chat"):
        with mock.patch.object(llm_chats, "input_message", side_effect=EOFError()):
            llm_chats.main()

    assert os.environ[PRINT_ENABLED_ENV_KEY] == ""


@pytest.mark.parametrize("entry_point", [llm_chat, llm_chats])
def test_entry_point_applies_the_default_before_the_chat_factory(
    entry_point, monkeypatch
) -> None:
    """The default is in place before the chat object is created.

    The chat factory is the first thing that can print, so the value must
    already be set when it is called.
    """
    monkeypatch.delenv(PRINT_ENABLED_ENV_KEY, raising=False)
    observed: list[str] = []

    def _record_env(*args, **kwargs):
        observed.append(os.environ.get(PRINT_ENABLED_ENV_KEY, "<absent>"))
        return mock.MagicMock()

    with mock.patch.object(entry_point, "get_llm_chat", side_effect=_record_env):
        # Only the multi-turn entry point prompts for a next message; the
        # single-turn one returns after its first answer.
        if hasattr(entry_point, "input_message"):
            with mock.patch.object(entry_point, "input_message", side_effect=EOFError()):
                entry_point.main()
        else:
            entry_point.main()

    assert observed == ["0"]
