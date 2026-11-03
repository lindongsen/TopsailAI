"""Author: DawsonLin. Shared worker identity and stdout path contracts."""

import os

import pytest

from topsailai.workspace.folder_utils import get_session_stdout_path
from topsailai.workspace.session_identity import initialize_session_id


@pytest.mark.parametrize("explicit, primary, legacy, expected", [
    ("explicit", "primary", "legacy", "explicit"),
    (None, "primary", "legacy", "primary"),
    (None, "", "legacy", "legacy"),
    (None, None, None, None),
    ("", "primary", "legacy", ""),
])
def test_initialize_session_id(monkeypatch, explicit, primary, legacy, expected):
    """Keep parameter precedence, empty semantics and environment aliases stable."""
    for key, value in (("TOPSAILAI_SESSION_ID", primary), ("SESSION_ID", legacy)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    assert initialize_session_id(explicit) == expected
    if expected:
        assert os.environ["TOPSAILAI_SESSION_ID"] == expected
        assert os.environ["SESSION_ID"] == expected
    else:
        assert os.getenv("TOPSAILAI_SESSION_ID") == primary
        assert os.getenv("SESSION_ID") == legacy


@pytest.mark.parametrize("session_id, name", [
    ("session-123", "session-123.42.session.stdout"),
    ("", "topsailai.42.session.stdout"),
    (None, "topsailai.42.session.stdout"),
])
def test_session_stdout_path(tmp_path, monkeypatch, session_id, name):
    """Build the exact absolute path without consulting inherited identity."""
    monkeypatch.setenv("TOPSAILAI_SESSION_ID", "unrelated")
    assert get_session_stdout_path(str(tmp_path), session_id, 42) == str(tmp_path / name)
