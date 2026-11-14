"""Unit tests for cli/agent_chats.py agent role and session identity.

Verifies that the multi-turn agent chat entry point explicitly creates its
agent with the ``manager`` role, so role-gated behavior does not depend on the
``TOPSAILAI_AGENT_ROLE`` environment variable, and that it always runs with a
session identity by generating one when none is configured.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

# Make the cli directory importable so we can load agent_chats as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import agent_chats

# Documented shape of an automatically generated chat session identity.
GENERATED_SESSION_ID_PATTERN = r"\d{14}"


@pytest.fixture(autouse=True)
def clear_agent_role_env() -> None:
    """Ensure the role env var cannot influence the resolved role."""
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)
    yield
    os.environ.pop("TOPSAILAI_AGENT_ROLE", None)


@pytest.fixture(autouse=True)
def clear_session_id_env() -> None:
    """Start every test with no configured session identity."""
    for key in agent_chats.SESSION_ID_ENV_KEYS:
        os.environ.pop(key, None)
    yield
    for key in agent_chats.SESSION_ID_ENV_KEYS:
        os.environ.pop(key, None)


def _run_main() -> mock.MagicMock:
    """Run main() with the chat factory patched and return the mock."""
    with mock.patch.object(agent_chats, "get_agent_chat") as mock_get_chat:
        agent_chats.main()
    return mock_get_chat


def test_agent_role_is_manager() -> None:
    """get_agent_chat receives agent_role='manager' explicitly."""
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


def test_agent_role_manager_overrides_env_worker() -> None:
    """An explicit worker env value must not downgrade the entry-point role."""
    os.environ["TOPSAILAI_AGENT_ROLE"] = "worker"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["agent_role"] == "manager"


def test_agent_tool_remains_disabled() -> None:
    """The pre-existing agent_tool restriction must be preserved."""
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["disabled_tools"] == ["agent_tool"]


def test_generates_session_id_when_both_variables_are_missing() -> None:
    """An unconfigured chat still runs with a generated session identity."""
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    session_id = kwargs["session_id"]
    assert session_id
    assert re.fullmatch(GENERATED_SESSION_ID_PATTERN, session_id)


def test_generated_session_id_is_published_to_both_aliases() -> None:
    """The generated identity reaches both environment aliases."""
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    session_id = kwargs["session_id"]
    assert os.environ["TOPSAILAI_SESSION_ID"] == session_id
    assert os.environ["SESSION_ID"] == session_id


def test_generated_session_id_is_a_compact_timestamp() -> None:
    """The generated identity is the documented ``YYYYMMDDHHMMSS`` timestamp."""
    session_id = agent_chats._generate_session_id()

    assert re.fullmatch(GENERATED_SESSION_ID_PATTERN, session_id)
    # A dot would corrupt session filename parsing, which splits on ".".
    assert "." not in session_id
    # The value must be a real timestamp, not an arbitrary 14-digit number.
    datetime.strptime(session_id, "%Y%m%d%H%M%S")


def test_preserves_topsailai_session_id() -> None:
    """An explicit TOPSAILAI_SESSION_ID is forwarded verbatim."""
    os.environ["TOPSAILAI_SESSION_ID"] = "existing-topsailai"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == "existing-topsailai"
    assert os.environ["SESSION_ID"] == "existing-topsailai"


def test_preserves_legacy_session_id() -> None:
    """An explicit legacy SESSION_ID is forwarded verbatim."""
    os.environ["SESSION_ID"] = "existing-legacy"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == "existing-legacy"
    assert os.environ["TOPSAILAI_SESSION_ID"] == "existing-legacy"


def test_topsailai_session_id_wins_over_legacy_alias() -> None:
    """TOPSAILAI_SESSION_ID takes precedence when both aliases are set."""
    os.environ["TOPSAILAI_SESSION_ID"] = "preferred"
    os.environ["SESSION_ID"] = "legacy"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == "preferred"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_session_id_means_no_session(blank: str) -> None:
    """A present but blank alias opts out of session persistence."""
    os.environ["TOPSAILAI_SESSION_ID"] = blank
    os.environ["SESSION_ID"] = blank
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == ""


def test_blank_session_id_is_not_generated() -> None:
    """An explicit blank value must never be replaced by a generated identity."""
    os.environ["TOPSAILAI_SESSION_ID"] = ""
    with mock.patch.object(agent_chats, "_generate_session_id") as mock_generate:
        _run_main()

    mock_generate.assert_not_called()


def test_absent_topsailai_session_id_falls_through_to_legacy_alias() -> None:
    """An absent alias must not stop the search for a configured one."""
    os.environ.pop("TOPSAILAI_SESSION_ID", None)
    os.environ["SESSION_ID"] = "legacy-only"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == "legacy-only"


def test_blank_topsailai_session_id_does_not_fall_through_to_legacy_alias() -> None:
    """A present blank alias decides, so the legacy alias is not consulted."""
    os.environ["TOPSAILAI_SESSION_ID"] = ""
    os.environ["SESSION_ID"] = "legacy"
    mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    assert kwargs["session_id"] == ""


def test_no_session_identity_is_published_as_empty() -> None:
    """Opting out publishes an empty identity instead of leaving a stale one."""
    os.environ["TOPSAILAI_SESSION_ID"] = ""
    os.environ["SESSION_ID"] = ""
    _run_main()

    assert os.environ["TOPSAILAI_SESSION_ID"] == ""
    assert os.environ["SESSION_ID"] == ""


def test_generated_session_id_is_announced_when_library_is_silent() -> None:
    """The generated identity is printed once when the library stays silent."""
    with mock.patch.object(agent_chats, "_library_prints_session", return_value=False):
        with mock.patch.object(agent_chats, "print_info") as mock_print:
            mock_get_chat = _run_main()

    _, kwargs = mock_get_chat.call_args
    mock_print.assert_called_once_with(f"session_id: {kwargs['session_id']}")


def test_generated_session_id_is_not_duplicated_when_library_prints() -> None:
    """No extra line is printed when the library prints the session itself."""
    with mock.patch.object(agent_chats, "_library_prints_session", return_value=True):
        with mock.patch.object(agent_chats, "print_info") as mock_print:
            _run_main()

    mock_print.assert_not_called()


def test_configured_session_id_is_never_announced() -> None:
    """A configured identity is not re-announced by this entry point."""
    os.environ["TOPSAILAI_SESSION_ID"] = "configured"
    with mock.patch.object(agent_chats, "_library_prints_session", return_value=False):
        with mock.patch.object(agent_chats, "print_info") as mock_print:
            _run_main()

    mock_print.assert_not_called()
