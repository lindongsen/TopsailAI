"""Unit tests for session category storage."""

import pytest
from sqlalchemy import create_engine, text

from topsailai.context.session_manager.sql import SessionData, SessionSQLAlchemy


def test_session_category_defaults_to_empty_string():
    """New sessions store an empty category by default."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    manager.create_session(SessionData(session_id="default", task="task"))

    assert manager.get_session("default").category == ""
    assert manager.list_sessions()[0].category == ""


def test_session_category_round_trips_legal_values():
    """Legal lowercase category values round-trip through storage."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    for session_id, category in (("agent", "agent"), ("chat", "chat_2")):
        manager.create_session(
            SessionData(session_id=session_id, task="task", category=category)
        )

    assert manager.get_session("agent").category == "agent"
    listed = {item.session_id: item.category for item in manager.list_sessions()}
    assert listed == {"agent": "agent", "chat": "chat_2"}


def test_invalid_session_category_logs_and_stores_empty(caplog):
    """Invalid category values are rejected without blocking session creation."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    with caplog.at_level("ERROR"):
        manager.create_session(
            SessionData(session_id="invalid", task="task", category="Agent")
        )

    assert manager.get_session("invalid").category == ""
    assert "Agent" in caplog.text


def test_existing_session_schema_gains_empty_category(tmp_path):
    """Existing rows gain the category column without data backfill."""
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT NOT NULL, "
            "session_name TEXT, project_workspace TEXT, pwd TEXT, topsailai_home TEXT, "
            "total_tokens INTEGER DEFAULT 0, total_cached_tokens INTEGER DEFAULT 0, "
            "total_completion_tokens INTEGER DEFAULT 0, create_time DATETIME NOT NULL, "
            "update_time DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO session VALUES "
            "('legacy', 'task', NULL, NULL, NULL, NULL, 0, 0, 0, "
            "'2020-01-01 00:00:00', '2020-01-01 00:00:00')"
        ))
    engine.dispose()

    manager = SessionSQLAlchemy(f"sqlite:///{path}")
    assert manager.get_session("legacy").category == ""
    with manager.engine.connect() as connection:
        column = connection.execute(text(
            "SELECT type, \"notnull\", dflt_value FROM pragma_table_info('session') "
            "WHERE name = 'category'"
        )).one()
        assert column == ("TEXT", 1, "''")
        assert connection.execute(text("SELECT count(*) FROM session")).scalar_one() == 1


@pytest.mark.parametrize("category", ["Agent", "chat x", "chat-x", "聊天", "agent\n"])
def test_invalid_session_categories_store_raw_empty_string(category):
    """Invalid category values are persisted as a real empty string."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    manager.create_session(SessionData(session_id="invalid", task="task", category=category))

    with manager.engine.connect() as connection:
        value = connection.execute(
            text("SELECT category FROM session WHERE session_id = 'invalid'")
        ).scalar_one()
    assert value == ""


def test_default_session_category_is_raw_empty_string():
    """The default category is not NULL in the database."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    manager.create_session(SessionData(session_id="default", task="task"))

    with manager.engine.connect() as connection:
        value = connection.execute(
            text("SELECT category FROM session WHERE session_id = 'default'")
        ).scalar_one()
    assert value == ""
