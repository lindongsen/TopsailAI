'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Unit tests for workspace/project_workspace.py, which resolves the
           project workspace from the environment with a fallback that reads the
           persisted session record through the shared context manager.
'''

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from topsailai.workspace import project_workspace


@pytest.fixture(autouse=True)
def _isolated_lookup(monkeypatch):
    """Clear cached lookups and every environment name the resolver reads."""
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE", OrderedDict())
    for name in (
        "TOPSAILAI_PROJECT_WORKSPACE",
        "TOPSAILAI_PROJECT_FOLDER",
        "SESSION_ID",
        "TOPSAILAI_SESSION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _fake_session(monkeypatch, workspace, calls=None):
    """Replace the shared context manager with a canned session record.

    The manager is stubbed at the ``ctx_manager`` boundary, which is the single
    supported way for this layer to reach session storage, so the tests never
    open a real database.
    """
    from topsailai.context import ctx_manager

    class FakeManager:
        """Minimal session manager exposing only ``get_session``."""

        def get_session(self, session_id):
            """Record the lookup and return a record carrying the workspace."""
            if calls is not None:
                calls.append(session_id)
            if workspace is None:
                return None
            return SimpleNamespace(project_workspace=workspace)

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: FakeManager())


def _explode_manager(monkeypatch):
    """Fail the test if session storage is reached at all."""
    from topsailai.context import ctx_manager

    def explode():
        """Raise when the fallback is consulted."""
        raise AssertionError("session storage must not be reached")

    monkeypatch.setattr(ctx_manager, "get_session_manager", explode)


def test_explicit_argument_wins_over_environment(monkeypatch):
    """An explicit argument is returned unchanged."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert project_workspace.resolve_project_workspace("/explicit") == "/explicit"


def test_environment_variable_wins_without_reading_storage(monkeypatch):
    """The environment is preferred, so storage is never consulted."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")
    _explode_manager(monkeypatch)

    assert project_workspace.resolve_project_workspace(session_id="s-env") == "/env/wins"


def test_project_folder_environment_is_the_second_choice(monkeypatch):
    """TOPSAILAI_PROJECT_FOLDER is used when the primary name is absent."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", "/env/folder")
    _explode_manager(monkeypatch)

    assert project_workspace.resolve_project_workspace(session_id="s-folder") == "/env/folder"


def test_persisted_record_is_the_fallback(monkeypatch):
    """The persisted record is used when no environment value is present."""
    _fake_session(monkeypatch, "/persisted/ws")

    assert project_workspace.resolve_project_workspace(session_id="s-db") == "/persisted/ws"


def test_lookup_uses_the_shared_context_manager(monkeypatch):
    """The fallback reads storage through ``ctx_manager.get_session_manager``."""
    calls = []
    _fake_session(monkeypatch, "/persisted/ws", calls)

    project_workspace.resolve_project_workspace(session_id="s-manager")

    assert calls == ["s-manager"]


def test_unknown_session_yields_none(monkeypatch):
    """A missing session record degrades to ``None``."""
    _fake_session(monkeypatch, None)

    assert project_workspace.resolve_project_workspace(session_id="s-missing") is None


def test_empty_workspace_yields_none(monkeypatch):
    """A blank persisted workspace is treated as absent."""
    _fake_session(monkeypatch, "")

    assert project_workspace.resolve_project_workspace(session_id="s-empty") is None


def test_whitespace_workspace_yields_none(monkeypatch):
    """A whitespace-only persisted workspace is treated as absent."""
    _fake_session(monkeypatch, "   ")

    assert project_workspace.resolve_project_workspace(session_id="s-blank") is None


def test_non_string_workspace_yields_none(monkeypatch):
    """A non-string persisted workspace is treated as absent."""
    _fake_session(monkeypatch, 12345)

    assert project_workspace.resolve_project_workspace(session_id="s-int") is None


def test_storage_failure_degrades_to_none(monkeypatch):
    """A storage exception degrades to ``None`` instead of propagating."""
    from topsailai.context import ctx_manager

    def explode():
        """Simulate an unavailable database."""
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(ctx_manager, "get_session_manager", explode)

    assert project_workspace.resolve_project_workspace(session_id="s-broken") is None


def test_session_identity_comes_from_the_environment(monkeypatch):
    """The runtime session identity is used when no argument is supplied."""
    calls = []
    _fake_session(monkeypatch, "/persisted/ws", calls)
    monkeypatch.setenv("SESSION_ID", "s-from-env")

    assert project_workspace.resolve_project_workspace() == "/persisted/ws"
    assert calls == ["s-from-env"]


def test_absent_session_identity_skips_storage(monkeypatch):
    """No session identity means no lookup at all."""
    _explode_manager(monkeypatch)

    assert project_workspace.resolve_project_workspace() is None


def test_successful_lookup_is_cached(monkeypatch):
    """A hit is cached, so a second resolution does not read storage again."""
    calls = []
    _fake_session(monkeypatch, "/persisted/ws", calls)

    assert project_workspace.resolve_project_workspace(session_id="s-cache") == "/persisted/ws"
    assert project_workspace.resolve_project_workspace(session_id="s-cache") == "/persisted/ws"
    assert calls == ["s-cache"]


def test_miss_is_not_cached(monkeypatch):
    """A miss is not cached, so a record created later is still observable."""
    from topsailai.context import ctx_manager

    state = {"workspace": None}

    class FakeManager:
        """Session manager whose record appears after the first lookup."""

        def get_session(self, session_id):
            """Return the current record state."""
            return None if state["workspace"] is None else SimpleNamespace(
                project_workspace=state["workspace"]
            )

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: FakeManager())

    assert project_workspace.resolve_project_workspace(session_id="s-late") is None
    state["workspace"] = "/persisted/late"
    assert project_workspace.resolve_project_workspace(session_id="s-late") == "/persisted/late"


def test_lookup_cache_is_bounded(monkeypatch):
    """The cache never grows beyond its configured bound."""
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE_MAX_ENTRIES", 3)
    _fake_session(monkeypatch, "/persisted/ws")

    for index in range(10):
        project_workspace.resolve_project_workspace(session_id=f"s-{index}")

    assert len(project_workspace._LOOKUP_CACHE) <= 3


def test_cache_evicts_the_least_recently_used_entry(monkeypatch):
    """The oldest entry is evicted first when the bound is exceeded."""
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE_MAX_ENTRIES", 2)
    _fake_session(monkeypatch, "/persisted/ws")

    project_workspace.resolve_project_workspace(session_id="s-first")
    project_workspace.resolve_project_workspace(session_id="s-second")
    project_workspace.resolve_project_workspace(session_id="s-third")

    assert "s-first" not in project_workspace._LOOKUP_CACHE
    assert "s-third" in project_workspace._LOOKUP_CACHE


def test_no_subprocess_is_used(monkeypatch):
    """The resolver never spawns a command, which the layering rule forbids."""
    import subprocess

    def explode(*args, **kwargs):
        """Fail the test if any process is spawned."""
        raise AssertionError("no subprocess may be spawned")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)
    _fake_session(monkeypatch, "/persisted/ws")

    assert project_workspace.resolve_project_workspace(session_id="s-noproc") == "/persisted/ws"
