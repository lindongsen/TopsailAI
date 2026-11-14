'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Unit tests for workspace/project_workspace.py, which resolves the
           project workspace from the environment with a persisted-session
           fallback.
'''

import os
from collections import OrderedDict

import pytest

from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.workspace import folder_constants, project_workspace


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    """Point the resolver at a temporary home and clear cached lookups.

    Only the home directory is redirected. The real connection-string helper is
    left in place so the tests exercise the production path, including its
    absolute-path composition.
    """
    monkeypatch.setattr(folder_constants, "TOPSAILAI_HOME", str(tmp_path))
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE", OrderedDict())
    for name in (
        "TOPSAILAI_PROJECT_WORKSPACE",
        "TOPSAILAI_PROJECT_FOLDER",
        "SESSION_ID",
        "TOPSAILAI_SESSION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _persist(tmp_path, session_id, workspace):
    """Persist one session row with the given project workspace."""
    storage = SessionSQLAlchemy(f"sqlite:///{tmp_path / 'memory.db'}")
    storage.create_session(SessionData(
        session_id=session_id, task="task", project_workspace=workspace,
    ))


def test_explicit_argument_wins_over_environment(monkeypatch):
    """An explicit argument is returned unchanged."""
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert project_workspace.resolve_project_workspace("/explicit") == "/explicit"


def test_environment_variable_wins_over_persisted_record(monkeypatch, tmp_path):
    """The environment is preferred, so no lookup is needed."""
    _persist(tmp_path, "s-env", "/persisted/ws")
    monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", "/env/wins")

    assert project_workspace.resolve_project_workspace(session_id="s-env") == "/env/wins"


def test_project_folder_environment_is_the_second_choice(monkeypatch, tmp_path):
    """TOPSAILAI_PROJECT_FOLDER is used when the primary name is absent."""
    _persist(tmp_path, "s-folder", "/persisted/ws")
    monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", "/env/folder")

    assert project_workspace.resolve_project_workspace(session_id="s-folder") == "/env/folder"


def test_persisted_record_is_the_fallback(tmp_path):
    """With no environment value the persisted workspace is returned."""
    _persist(tmp_path, "s-db", "/persisted/ws")

    assert project_workspace.resolve_project_workspace(session_id="s-db") == "/persisted/ws"


def test_unknown_session_yields_none(tmp_path):
    """A session with no persisted row resolves to None."""
    _persist(tmp_path, "s-known", "/persisted/ws")

    assert project_workspace.resolve_project_workspace(session_id="s-unknown") is None


def test_missing_database_yields_none_without_creating_a_file(tmp_path):
    """A missing database must not be created, because that would hide a miss."""
    assert project_workspace.resolve_project_workspace(session_id="s-any") is None
    assert not (tmp_path / "memory.db").exists()


def test_session_identity_comes_from_the_environment(monkeypatch, tmp_path):
    """The runtime session identity is used when no identity is passed."""
    _persist(tmp_path, "s-runtime", "/persisted/ws")
    monkeypatch.setenv("SESSION_ID", "s-runtime")

    assert project_workspace.resolve_project_workspace() == "/persisted/ws"


def test_lookup_failure_degrades_to_none(monkeypatch, tmp_path):
    """A storage failure must degrade instead of failing the caller."""
    _persist(tmp_path, "s-broken", "/persisted/ws")

    def explode(*args, **kwargs):
        """Simulate an unavailable session manager."""
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", explode,
    )

    assert project_workspace.resolve_project_workspace(session_id="s-broken") is None


def test_successful_lookup_is_cached(tmp_path, monkeypatch):
    """A hit is cached, so a repeated resolution does not query the database."""
    _persist(tmp_path, "s-cache", "/persisted/ws")
    queries = []
    original = SessionSQLAlchemy.get_session

    def counting(self, session_id):
        """Count real storage queries while delegating to the implementation."""
        queries.append(session_id)
        return original(self, session_id)

    monkeypatch.setattr(SessionSQLAlchemy, "get_session", counting)

    first = project_workspace.resolve_project_workspace(session_id="s-cache")
    second = project_workspace.resolve_project_workspace(session_id="s-cache")

    assert first == second == "/persisted/ws"
    assert queries == ["s-cache"]


def test_miss_is_not_cached(tmp_path):
    """A miss is not cached, so a row created later is still observable."""
    SessionSQLAlchemy(f"sqlite:///{tmp_path / 'memory.db'}")

    assert project_workspace.resolve_project_workspace(session_id="s-late") is None

    _persist(tmp_path, "s-late", "/persisted/late")

    assert project_workspace.resolve_project_workspace(session_id="s-late") == "/persisted/late"


def test_database_path_is_absolute_and_independent_of_cwd(tmp_path):
    """The connection string must not depend on the process working directory."""
    (tmp_path / "memory.db").write_bytes(b"")

    original_cwd = os.getcwd()
    try:
        os.chdir("/")
        conn = project_workspace._session_database_conn()
    finally:
        os.chdir(original_cwd)

    assert conn == f"sqlite:///{tmp_path / 'memory.db'}"


def test_lookup_cache_is_bounded(tmp_path, monkeypatch):
    """The cache must not grow without limit in a long-lived process."""
    (tmp_path / "memory.db").write_bytes(b"")
    monkeypatch.setattr(project_workspace, "_LOOKUP_CACHE_MAX_ENTRIES", 3)

    for index in range(10):
        _persist(tmp_path, f"s-bounded-{index}", f"/persisted/{index}")
        assert project_workspace.resolve_project_workspace(
            session_id=f"s-bounded-{index}"
        ) == f"/persisted/{index}"

    assert len(project_workspace._LOOKUP_CACHE) <= 3
