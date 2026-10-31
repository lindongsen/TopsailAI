"""Unit tests for session category storage."""

import pytest
import logging
import re
from sqlalchemy import create_engine, text, event

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


def test_category_filter_is_sql_side_and_count_ignores_pagination():
    """Category selection is exact and count is computed before pagination."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    for session_id, category in (("a", "agent"), ("b", "chat"), ("c", "agent")):
        manager.create_session(SessionData(session_id=session_id, task="task", category=category))

    page = manager.list_sessions(category="agent", order_by="session_id", offset=1, limit=1)
    assert [item.session_id for item in page] == ["c"]
    assert manager.count_sessions(category="agent") == 2
    assert [item.session_id for item in manager.list_sessions(category="")] == []


def test_category_filter_intersects_session_ids():
    """ID and category filters are applied together."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
    manager.create_session(SessionData(session_id="chat", task="task", category="chat"))

    assert [item.session_id for item in manager.list_sessions(
        sessions=["agent", "chat"], category="agent"
    )] == ["agent"]
    assert manager.count_sessions(sessions=["agent", "chat"], category="agent") == 1

@pytest.mark.parametrize(
    "category, is_valid",
    [
        ("Agent", False),
        ("agent chat", False),
        ("agent-chat", False),
        ("agent\n", False),
        ("agent@", False),
        ("", True),
        ("agent", True),
    ],
)
def test_query_category_boundary_logs_exact_error_and_never_broadens(
    category, is_valid, caplog
):
    """Query normalization logs invalid values and never removes their filter."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    manager.create_session(SessionData(session_id="empty", task="task", category=""))
    manager.create_session(SessionData(session_id="agent", task="task", category="agent"))
    manager.create_session(SessionData(session_id="chat", task="task", category="chat"))

    caplog.clear()
    with caplog.at_level(logging.ERROR):
        rows = manager.list_sessions(category=category)
        count = manager.count_sessions(category=category)

    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    if is_valid:
        assert errors == []
        expected = category
    else:
        assert errors
        assert any(repr(category) in record.getMessage() for record in errors)
        expected = ""
    assert {row.category for row in rows} == {expected} if rows else expected == ""
    assert count == len(rows)
    if not is_valid:
        assert {row.session_id for row in rows} == {"empty"}


def test_query_sql_capture_places_category_before_pagination_and_count_has_no_pagination():
    """Captured SQL filters category before paging and count has no paging clauses."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    for session_id, category in (("agent-1", "agent"), ("agent-2", "agent"), ("chat", "chat")):
        manager.create_session(SessionData(session_id=session_id, task="task", category=category))

    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(manager.engine, "before_cursor_execute", before_cursor_execute)
    try:
        manager.list_sessions(category="agent", offset=0, limit=20)
        manager.count_sessions(category="agent")
    finally:
        event.remove(manager.engine, "before_cursor_execute", before_cursor_execute)

    select_statements = [
        item for item in statements if "FROM session" in item[0]
    ]
    assert len(select_statements) == 2
    list_sql, list_parameters = select_statements[0]
    count_sql, count_parameters = select_statements[1]

    def where_clause(statement):
        lower = statement.lower()
        where_match = re.search(r"\bwhere\b", lower)
        assert where_match is not None
        start = where_match.end()
        end = len(statement)
        for marker in (r"\border by\b", r"\bgroup by\b", r"\blimit\b", r"\boffset\b"):
            match = re.search(marker, lower[start:])
            if match:
                end = min(end, start + match.start())
        return statement[start:end].lower()

    list_where = where_clause(list_sql)
    count_where = where_clause(count_sql)
    category_predicate = r"(?:session\.)?category\s*=\s*\?"
    assert re.search(category_predicate, list_where)
    assert re.search(category_predicate, count_where)
    assert "agent" in list_parameters
    assert "agent" in count_parameters
    assert re.search(r"\bwhere\b", list_sql.lower()).start() < re.search(r"\blimit\b", list_sql.lower()).start()
    assert " limit " not in f" {count_sql.lower()} "
    assert " offset " not in f" {count_sql.lower()} "


def test_count_sessions_ignores_zero_limit_and_out_of_range_offset():
    """Pagination does not change the total matching category count."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    for session_id in ("agent-1", "agent-2"):
        manager.create_session(SessionData(session_id=session_id, task="task", category="agent"))

    assert manager.list_sessions(category="agent", offset=99, limit=20) == []
    assert manager.list_sessions(category="agent", offset=0, limit=0) == []
    assert manager.count_sessions(category="agent") == 2


def test_category_queries_do_not_change_rows_schema_or_metadata():
    """Category reads leave all database rows and schema metadata unchanged."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    for session_id, category in (("agent", "agent"), ("empty", ""), ("chat", "chat")):
        manager.create_session(SessionData(session_id=session_id, task="task", category=category))

    def snapshot():
        with manager.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM session ORDER BY session_id")
            ).fetchall()
            columns = tuple(
                (column[1], column[2], column[3], column[4])
                for column in connection.execute(text("PRAGMA table_info(session)"))
            )
        return rows, columns

    before = snapshot()
    manager.list_sessions(category="agent")
    manager.count_sessions(category="agent")
    manager.list_sessions(category=None)
    after = snapshot()
    assert after == before
