'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Unit tests proving the two project-workspace consumers use the
           shared resolver, so a resumed session keeps its persisted workspace
           even when the environment variable was not exported.
'''

import json
import os
import subprocess
from collections import OrderedDict

import pytest

from topsailai.workspace import folder_constants, lock_tool, session_meta


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    """Redirect the home directory, metadata folder and lookup cache."""
    monkeypatch.setattr(folder_constants, "TOPSAILAI_HOME", str(tmp_path))
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setattr(
        "topsailai.workspace.project_workspace._LOOKUP_CACHE", OrderedDict(),
    )
    for name in (
        "TOPSAILAI_PROJECT_WORKSPACE",
        "TOPSAILAI_PROJECT_FOLDER",
        "SESSION_ID",
        "TOPSAILAI_SESSION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _persist(monkeypatch, workspace):
    """Make the session-info command report *workspace* for any session.

    The consumers are tested through the same command boundary the resolver
    uses, so no test opens the session database.
    """
    monkeypatch.setattr(
        "topsailai.workspace.project_workspace._resolve_lookup_command",
        lambda: "/fake/session_info",
    )

    def fake_run(cmd):
        """Return a canned session-info document."""
        payload = {"session_id": cmd[-1], "project_workspace": workspace}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(
        "topsailai.workspace.project_workspace._run_lookup_command", fake_run,
    )


def _read_meta(path):
    """Read one session metadata file."""
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def test_session_meta_uses_persisted_workspace_when_environment_is_absent(monkeypatch):
    """A resumed session records the persisted workspace, not an empty string."""
    _persist(monkeypatch, "/persisted/ws")

    path = session_meta.create_session_meta("s-meta-db")

    assert _read_meta(path)["project_workspace"] == "/persisted/ws"


def test_session_meta_prefers_environment_over_persisted_workspace(monkeypatch):
    """An exported environment value still wins over the persisted record."""
    _persist(monkeypatch, "/persisted/ws")
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    path = session_meta.create_session_meta("s-meta-env")

    assert _read_meta(path)["project_workspace"] == "/env/wins"


def test_session_meta_records_empty_when_nothing_is_available(monkeypatch):
    """With no environment and no persisted row the field stays empty."""
    monkeypatch.setattr(
        "topsailai.workspace.project_workspace._resolve_lookup_command",
        lambda: None,
    )

    path = session_meta.create_session_meta("s-meta-none")

    assert _read_meta(path)["project_workspace"] == ""


def test_lock_tool_uses_persisted_workspace_when_environment_is_absent(monkeypatch):
    """The project lock resolves the persisted workspace for a resumed session."""
    _persist(monkeypatch, "/persisted/ws")
    monkeypatch.setenv("SESSION_ID", "s-lock-db")

    assert lock_tool._resolve_project_workspace() == "/persisted/ws"


def test_lock_tool_prefers_environment_over_persisted_workspace(monkeypatch):
    """An exported environment value still wins for the lock target."""
    _persist(monkeypatch, "/persisted/ws")
    monkeypatch.setenv("SESSION_ID", "s-lock-env")
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert lock_tool._resolve_project_workspace() == "/env/wins"


def test_lock_tool_explicit_argument_wins(monkeypatch):
    """An explicit argument is returned unchanged."""
    _persist(monkeypatch, "/persisted/ws")
    monkeypatch.setenv("SESSION_ID", "s-lock-explicit")
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert lock_tool._resolve_project_workspace("/explicit") == "/explicit"


def test_lock_tool_returns_none_when_nothing_is_available(monkeypatch):
    """With no environment and no persisted row the lock target is None."""
    monkeypatch.setattr(
        "topsailai.workspace.project_workspace._resolve_lookup_command",
        lambda: None,
    )

    assert lock_tool._resolve_project_workspace() is None


def test_lock_tool_acquires_the_persisted_workspace_lock(monkeypatch, tmp_path):
    """The lock is actually taken on the persisted workspace directory."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    _persist(monkeypatch, str(workspace))
    monkeypatch.setenv("SESSION_ID", "s-lock-real")

    with lock_tool.ctxm_project_workspace_lock() as has_lock:
        assert has_lock is True
        assert os.path.exists(workspace / ".topsailai" / "project_workspace.lock")

    assert not os.path.exists(workspace / ".topsailai" / "project_workspace.lock")
