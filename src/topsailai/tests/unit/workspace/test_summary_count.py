"""Summary application accounting and session totals. Author: DawsonLin."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from topsailai.context import ctx_manager
from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.workspace.context.base import ContextRuntimeBase
from topsailai.workspace.agent.agent_shell_base import _get_session_summary_count, _summary_count


def test_storage_summary_count_migration_and_addition(tmp_path):
    """Upgrade an old schema without losing rows and expose additive list/get totals."""
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE session (session_id VARCHAR(32) PRIMARY KEY, session_name TEXT, task TEXT NOT NULL, create_time DATETIME, update_time DATETIME)"))
        connection.execute(text("INSERT INTO session VALUES ('old', 'retained', 'task', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    engine.dispose()
    storage = SessionSQLAlchemy(url)
    try:
        assert storage.get_session('old').summary_count == 0
        assert storage.accumulate_session_metrics('old', summary_count=2)
        assert storage.accumulate_session_metrics('old', summary_count=3)
        assert storage.accumulate_session_metrics('old', summary_count=-10)
        assert storage.get_session('old').summary_count == 5
        assert storage.list_sessions(sessions=['old'])[0].summary_count == 5
        assert storage.get_session('old').session_name == 'retained'
        assert storage.get_session('old').turn_count == 0
        assert storage.create_session(SessionData('new'))
        assert storage.get_session('new').summary_count == 0
        assert not storage.accumulate_session_metrics('missing', summary_count=1)
    finally:
        storage.engine.dispose()


@pytest.mark.parametrize('result', [True, False, RuntimeError('offline')])
def test_local_count_survives_persistence_failure(monkeypatch, result):
    """A best-effort database failure cannot invalidate applied summaries."""
    manager = Mock()
    if isinstance(result, Exception):
        manager.accumulate_session_metrics.side_effect = result
    else:
        manager.accumulate_session_metrics.return_value = result
    monkeypatch.setattr(ctx_manager, 'get_session_manager', lambda: manager)
    runtime = ContextRuntimeBase()
    runtime.session_id = 'exact-session'
    runtime._record_summary_applied()
    runtime._record_summary_applied()
    assert runtime.summary_count == 2
    assert manager.accumulate_session_metrics.call_count == 2
    manager.accumulate_session_metrics.assert_called_with('exact-session', summary_count=1)


def test_without_session_never_writes(monkeypatch):
    """Anonymous summaries remain available locally without a placeholder session."""
    factory = Mock()
    monkeypatch.setattr(ctx_manager, 'get_session_manager', factory)
    runtime = ContextRuntimeBase()
    runtime._record_summary_applied()
    assert runtime.summary_count == 1
    factory.assert_not_called()


def test_display_prefers_persisted_total_and_falls_back(monkeypatch):
    """Session totals include previous workers while fallback stays runtime-local."""
    runtime = SimpleNamespace(summary_count=3)
    manager = Mock()
    manager.get_session.return_value = SimpleNamespace(summary_count=20)
    monkeypatch.setattr(ctx_manager, 'get_session_manager', lambda: manager)
    assert _get_session_summary_count('session', runtime) == 20
    manager.get_session.side_effect = RuntimeError('offline')
    assert _get_session_summary_count('session', runtime) == 3
    assert _get_session_summary_count('', runtime) == 3
    assert _summary_count(object()) == 0
