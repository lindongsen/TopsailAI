"""Unit tests for session category storage."""

import itertools
import logging
import re
from datetime import datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text, event

from topsailai.context.session_category import resolve_session_category
from topsailai.context.session_manager.manager import DefaultSessionManager
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


def _seed_exclusion_rows(manager):
    """Create one row per category used by the exclusion tests."""
    for session_id, category in (
        ("driver-1", "agent_driver"),
        ("driver-2", "agent_driver"),
        ("agent-1", "agent"),
        ("chat-1", "chat"),
        ("plain-1", ""),
    ):
        manager.create_session(
            SessionData(session_id=session_id, task="task", category=category)
        )


def test_excluded_categories_remove_only_listed_categories():
    """Exclusion drops the listed categories and keeps every other row."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(excluded_categories={"agent_driver"})
    assert {row.session_id for row in rows} == {"agent-1", "chat-1", "plain-1"}
    assert manager.count_sessions(excluded_categories={"agent_driver"}) == 3


def test_excluded_categories_empty_string_removes_uncategorized_rows():
    """An empty string excludes uncategorized sessions like any other name."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(excluded_categories={""})
    assert {row.session_id for row in rows} == {"driver-1", "driver-2", "agent-1", "chat-1"}
    assert manager.count_sessions(excluded_categories={""}) == 4


def test_excluded_categories_combine_with_inclusion():
    """Inclusion and exclusion compose into one SQL predicate."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(category="agent", excluded_categories={"agent_driver"})
    assert [row.session_id for row in rows] == ["agent-1"]
    assert manager.count_sessions(category="agent", excluded_categories={"agent_driver"}) == 1


def test_excluded_categories_apply_before_pagination():
    """Offset and limit select a full page of surviving rows."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    page = manager.list_sessions(
        excluded_categories={"agent_driver"}, order_by="session_id", offset=1, limit=2
    )
    assert [row.session_id for row in page] == ["chat-1", "plain-1"]
    assert manager.count_sessions(excluded_categories={"agent_driver"}) == 3


@pytest.mark.parametrize("excluded", [None, set()])
def test_omitted_or_empty_exclusion_keeps_every_row(excluded):
    """An omitted or empty exclusion must not change the unfiltered result."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(excluded_categories=excluded)
    assert len(rows) == 5
    assert manager.count_sessions(excluded_categories=excluded) == 5


def test_null_category_is_treated_as_uncategorized(tmp_path):
    """A NULL category counts as uncategorized instead of being dropped.

    The current schema declares category NOT NULL, so this only happens in a
    legacy table whose category column was created nullable. The coalesced
    predicate must still treat such a row as uncategorized rather than letting
    the negated IN silently discard it.
    """
    path = tmp_path / "nullable_category.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE session (session_id TEXT PRIMARY KEY, session_name TEXT, "
            "task TEXT NOT NULL, project_workspace TEXT, pwd TEXT, topsailai_home TEXT, "
            "total_tokens INTEGER DEFAULT 0, total_cached_tokens INTEGER DEFAULT 0, "
            "total_completion_tokens INTEGER DEFAULT 0, summary_count INTEGER DEFAULT 0, "
            "turn_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0, "
            "tool_error_count INTEGER DEFAULT 0, llm_request_count INTEGER DEFAULT 0, "
            "llm_request_failure_count INTEGER DEFAULT 0, tool_duration_ms_sum INTEGER DEFAULT 0, "
            "llm_request_duration_ms_sum INTEGER DEFAULT 0, create_time DATETIME NOT NULL, "
            "update_time DATETIME NOT NULL, category TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO session (session_id, task, create_time, update_time, category) "
            "VALUES ('null-1', 'task', '2020-01-01 00:00:00', '2020-01-01 00:00:00', NULL)"
        ))
        connection.execute(text(
            "INSERT INTO session (session_id, task, create_time, update_time, category) "
            "VALUES ('driver-1', 'task', '2020-01-02 00:00:00', '2020-01-02 00:00:00', 'agent_driver')"
        ))
    engine.dispose()
    manager = SessionSQLAlchemy(f"sqlite:///{path}")
    kept = {row.session_id for row in manager.list_sessions(excluded_categories={"agent_driver"})}
    assert kept == {"null-1"}
    dropped = {row.session_id for row in manager.list_sessions(excluded_categories={""})}
    assert dropped == {"driver-1"}
    manager.engine.dispose()


def test_exclusion_predicate_is_sql_side_and_uses_coalesce():
    """The exclusion reaches SQL as a negated coalesced IN predicate."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(manager.engine, "before_cursor_execute", before_cursor_execute)
    try:
        manager.list_sessions(excluded_categories={"agent_driver"}, offset=0, limit=2)
        manager.count_sessions(excluded_categories={"agent_driver"})
    finally:
        event.remove(manager.engine, "before_cursor_execute", before_cursor_execute)

    select_statements = [item for item in statements if "FROM session" in item[0]]
    assert len(select_statements) == 2
    list_sql, list_parameters = select_statements[0]
    count_sql, count_parameters = select_statements[1]
    for statement, parameters in ((list_sql, list_parameters), (count_sql, count_parameters)):
        lowered = statement.lower()
        assert "coalesce" in lowered
        assert "not in" in lowered
        assert "agent_driver" in parameters
    assert " limit " in f" {list_sql.lower()} "
    assert " limit " not in f" {count_sql.lower()} "


def test_create_time_index_exists_and_is_idempotent(tmp_path):
    """Initialization adds the listing index once and keeps it on reopen."""
    path = tmp_path / "index.db"
    manager = SessionSQLAlchemy(f"sqlite:///{path}")
    with manager.engine.connect() as connection:
        first = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_session_create_time'"
        )).fetchall()
    assert first == [("idx_session_create_time",)]
    manager.engine.dispose()

    reopened = SessionSQLAlchemy(f"sqlite:///{path}")
    with reopened.engine.connect() as connection:
        second = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_session_create_time'"
        )).fetchall()
        plan = connection.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM session ORDER BY create_time DESC LIMIT 10"
        )).fetchall()
    assert second == [("idx_session_create_time",)]
    assert any("idx_session_create_time" in str(row) for row in plan)
    reopened.engine.dispose()


def test_create_time_index_is_added_to_a_legacy_table(tmp_path):
    """A table created before the index existed gains it on initialization."""
    path = tmp_path / "legacy_index.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE session (session_id TEXT PRIMARY KEY, task TEXT NOT NULL, "
            "create_time DATETIME NOT NULL, update_time DATETIME NOT NULL, "
            "category TEXT NOT NULL DEFAULT '')"
        ))
        connection.execute(text(
            "INSERT INTO session VALUES ('legacy', 'task', '2020-01-01 00:00:00', "
            "'2020-01-01 00:00:00', '')"
        ))
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_session_create_time'"
        )).fetchall() == []
    engine.dispose()

    manager = SessionSQLAlchemy(f"sqlite:///{path}")
    with manager.engine.connect() as connection:
        assert connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_session_create_time'"
        )).fetchall() == [("idx_session_create_time",)]
        assert connection.execute(text("SELECT count(*) FROM session")).scalar_one() == 1
    manager.engine.dispose()


def test_included_categories_keep_only_listed_categories():
    """Inclusion keeps the listed categories and drops every other row."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(included_categories={"agent", "chat"})
    assert {row.session_id for row in rows} == {"agent-1", "chat-1"}
    assert manager.count_sessions(included_categories={"agent", "chat"}) == 2


def test_included_categories_empty_string_keeps_uncategorized_rows():
    """An empty string includes uncategorized sessions like any other name."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(included_categories={""})
    assert {row.session_id for row in rows} == {"plain-1"}
    assert manager.count_sessions(included_categories={""}) == 1


def test_included_categories_combine_with_exclusion():
    """Inclusion and exclusion compose into one SQL predicate."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(
        included_categories={"agent", "agent_driver"}, excluded_categories={"agent_driver"}
    )
    assert [row.session_id for row in rows] == ["agent-1"]
    assert manager.count_sessions(
        included_categories={"agent", "agent_driver"}, excluded_categories={"agent_driver"}
    ) == 1


def test_included_categories_intersect_with_exact_category():
    """An exact category and an inclusion set intersect instead of overriding."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(category="agent", included_categories={"agent", "chat"})
    assert [row.session_id for row in rows] == ["agent-1"]
    assert manager.count_sessions(
        category="agent", included_categories={"agent", "chat"}
    ) == 1

    disjoint = manager.list_sessions(category="chat", included_categories={"agent"})
    assert disjoint == []
    assert manager.count_sessions(category="chat", included_categories={"agent"}) == 0


def test_included_categories_apply_before_pagination():
    """Offset and limit select a full page of surviving rows."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    page = manager.list_sessions(
        included_categories={"agent", "chat", ""}, order_by="session_id", offset=1, limit=2
    )
    assert [row.session_id for row in page] == ["chat-1", "plain-1"]
    assert manager.count_sessions(included_categories={"agent", "chat", ""}) == 3


@pytest.mark.parametrize("included", [None, set()])
def test_omitted_or_empty_inclusion_keeps_every_row(included):
    """An omitted or empty inclusion must not change the unfiltered result."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    rows = manager.list_sessions(included_categories=included)
    assert len(rows) == 5
    assert manager.count_sessions(included_categories=included) == 5


def test_null_category_is_included_as_uncategorized(tmp_path):
    """A NULL category counts as uncategorized for the inclusion predicate.

    The current schema declares category NOT NULL, so this only happens in a
    legacy table whose category column was created nullable. The coalesced
    predicate must still treat such a row as uncategorized instead of letting
    the positive IN silently discard it.
    """
    path = tmp_path / "nullable_category_inclusion.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE session (session_id TEXT PRIMARY KEY, session_name TEXT, "
            "task TEXT NOT NULL, project_workspace TEXT, pwd TEXT, topsailai_home TEXT, "
            "total_tokens INTEGER DEFAULT 0, total_cached_tokens INTEGER DEFAULT 0, "
            "total_completion_tokens INTEGER DEFAULT 0, summary_count INTEGER DEFAULT 0, "
            "turn_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0, "
            "tool_error_count INTEGER DEFAULT 0, llm_request_count INTEGER DEFAULT 0, "
            "llm_request_failure_count INTEGER DEFAULT 0, tool_duration_ms_sum INTEGER DEFAULT 0, "
            "llm_request_duration_ms_sum INTEGER DEFAULT 0, create_time DATETIME NOT NULL, "
            "update_time DATETIME NOT NULL, category TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO session (session_id, task, create_time, update_time, category) "
            "VALUES ('null-1', 'task', '2020-01-01 00:00:00', '2020-01-01 00:00:00', NULL)"
        ))
        connection.execute(text(
            "INSERT INTO session (session_id, task, create_time, update_time, category) "
            "VALUES ('driver-1', 'task', '2020-01-02 00:00:00', '2020-01-02 00:00:00', 'agent_driver')"
        ))
    engine.dispose()
    manager = SessionSQLAlchemy(f"sqlite:///{path}")
    kept = {row.session_id for row in manager.list_sessions(included_categories={""})}
    assert kept == {"null-1"}
    dropped = {row.session_id for row in manager.list_sessions(included_categories={"agent_driver"})}
    assert dropped == {"driver-1"}
    manager.engine.dispose()


def test_inclusion_predicate_is_sql_side_and_uses_coalesce():
    """The inclusion reaches SQL as a coalesced IN predicate."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_exclusion_rows(manager)

    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(manager.engine, "before_cursor_execute", before_cursor_execute)
    try:
        manager.list_sessions(included_categories={"agent"}, offset=0, limit=2)
        manager.count_sessions(included_categories={"agent"})
    finally:
        event.remove(manager.engine, "before_cursor_execute", before_cursor_execute)

    select_statements = [item for item in statements if "FROM session" in item[0]]
    assert len(select_statements) == 2
    list_sql, list_parameters = select_statements[0]
    count_sql, count_parameters = select_statements[1]
    for statement, parameters in ((list_sql, list_parameters), (count_sql, count_parameters)):
        lowered = statement.lower()
        assert "coalesce" in lowered
        assert " in " in lowered
        assert "not in" not in lowered
        assert "agent" in parameters
    assert " limit " in f" {list_sql.lower()} "
    assert " limit " not in f" {count_sql.lower()} "


def _seed_project_and_time_rows(manager):
    """Create rows covering project-workspace shapes and creation times."""
    rows = (
        ("proj-early", "/work/a", datetime(2026, 1, 1, 0, 0, 0)),
        ("proj-mid", "/work/b", datetime(2026, 1, 2, 0, 0, 0)),
        ("proj-late", "/work/c", datetime(2026, 1, 3, 0, 0, 0)),
        ("empty-ws", "", datetime(2026, 1, 4, 0, 0, 0)),
        ("blank-ws", "   ", datetime(2026, 1, 5, 0, 0, 0)),
        ("null-ws", None, datetime(2026, 1, 6, 0, 0, 0)),
    )
    for session_id, workspace, created in rows:
        data = SessionData(session_id=session_id, task="task", project_workspace=workspace)
        data.create_time = created
        manager.create_session(data)


def test_has_project_keeps_only_truthy_workspaces():
    """has_project drops NULL and empty workspaces but keeps whitespace-only ones."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    rows = manager.list_sessions(has_project=True, order_by="session_id")
    assert {row.session_id for row in rows} == {"proj-early", "proj-mid", "proj-late", "blank-ws"}
    assert manager.count_sessions(has_project=True) == 4


def test_has_project_applies_before_pagination():
    """A limit selects a full page of rows that have a project workspace."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    page = manager.list_sessions(has_project=True, order_by="session_id", offset=0, limit=2)
    assert [row.session_id for row in page] == ["blank-ws", "proj-early"]
    assert manager.count_sessions(has_project=True) == 4


def test_has_project_false_keeps_every_row():
    """An omitted or false has_project must not change the unfiltered result."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    assert len(manager.list_sessions()) == 6
    assert len(manager.list_sessions(has_project=False)) == 6
    assert manager.count_sessions() == 6
    assert manager.count_sessions(has_project=False) == 6


def test_since_keeps_rows_created_at_or_after_the_bound():
    """since is an inclusive lower bound on create_time."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    rows = manager.list_sessions(since=datetime(2026, 1, 3, 0, 0, 0), order_by="session_id")
    assert {row.session_id for row in rows} == {"proj-late", "empty-ws", "blank-ws", "null-ws"}
    assert manager.count_sessions(since=datetime(2026, 1, 3, 0, 0, 0)) == 4


def test_until_keeps_rows_created_at_or_before_the_bound():
    """until is an inclusive upper bound on create_time."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    rows = manager.list_sessions(until=datetime(2026, 1, 2, 0, 0, 0), order_by="session_id")
    assert {row.session_id for row in rows} == {"proj-early", "proj-mid"}
    assert manager.count_sessions(until=datetime(2026, 1, 2, 0, 0, 0)) == 2


def test_time_range_keeps_only_rows_inside_the_window():
    """Both bounds compose into one inclusive window."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    rows = manager.list_sessions(
        since=datetime(2026, 1, 2, 0, 0, 0),
        until=datetime(2026, 1, 4, 0, 0, 0),
        order_by="session_id",
    )
    assert {row.session_id for row in rows} == {"proj-mid", "proj-late", "empty-ws"}
    assert manager.count_sessions(
        since=datetime(2026, 1, 2, 0, 0, 0), until=datetime(2026, 1, 4, 0, 0, 0)
    ) == 3


def test_time_range_boundary_is_inclusive_on_both_ends():
    """An exact single-instant window selects exactly the row at that instant."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    instant = datetime(2026, 1, 3, 0, 0, 0)
    rows = manager.list_sessions(since=instant, until=instant)
    assert [row.session_id for row in rows] == ["proj-late"]
    assert manager.count_sessions(since=instant, until=instant) == 1


def test_time_range_after_every_row_returns_nothing():
    """A window later than every row selects no row instead of a short page."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    rows = manager.list_sessions(since=datetime(2030, 1, 1, 0, 0, 0), offset=0, limit=2)
    assert rows == []
    assert manager.count_sessions(since=datetime(2030, 1, 1, 0, 0, 0)) == 0


def test_time_range_applies_before_pagination():
    """Offset and limit select a full page of rows inside the window."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    page = manager.list_sessions(
        since=datetime(2026, 1, 2, 0, 0, 0),
        order_by="session_id",
        offset=1,
        limit=2,
    )
    assert [row.session_id for row in page] == ["empty-ws", "null-ws"]
    assert manager.count_sessions(since=datetime(2026, 1, 2, 0, 0, 0)) == 5


def test_project_and_time_filters_combine_with_categories():
    """Every selection predicate composes into one query."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    rows = (
        ("driver-1", "agent_driver", "/work/a", datetime(2026, 1, 1, 0, 0, 0)),
        ("driver-2", "agent_driver", "/work/b", datetime(2026, 1, 2, 0, 0, 0)),
        ("agent-1", "agent", "/work/c", datetime(2026, 1, 3, 0, 0, 0)),
        ("chat-1", "chat", "", datetime(2026, 1, 4, 0, 0, 0)),
        ("plain-1", "", "/work/d", datetime(2026, 1, 5, 0, 0, 0)),
    )
    for session_id, category, workspace, created in rows:
        data = SessionData(
            session_id=session_id, task="task", category=category, project_workspace=workspace
        )
        data.create_time = created
        manager.create_session(data)

    combined = manager.list_sessions(
        excluded_categories={"agent_driver"},
        has_project=True,
        since=datetime(2026, 1, 3, 0, 0, 0),
        order_by="session_id",
    )
    assert [row.session_id for row in combined] == ["agent-1", "plain-1"]
    assert manager.count_sessions(
        excluded_categories={"agent_driver"},
        has_project=True,
        since=datetime(2026, 1, 3, 0, 0, 0),
    ) == 2

    narrowed = manager.list_sessions(
        included_categories={"agent", "chat"},
        has_project=True,
        until=datetime(2026, 1, 3, 0, 0, 0),
    )
    assert [row.session_id for row in narrowed] == ["agent-1"]
    assert manager.count_sessions(
        included_categories={"agent", "chat"},
        has_project=True,
        until=datetime(2026, 1, 3, 0, 0, 0),
    ) == 1


def test_project_and_time_predicates_reach_the_sql_statement():
    """has_project and the time bounds are SQL predicates, not Python filters."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_project_and_time_rows(manager)

    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(manager.engine, "before_cursor_execute", before_cursor_execute)
    try:
        manager.list_sessions(
            has_project=True,
            since=datetime(2026, 1, 2, 0, 0, 0),
            until=datetime(2026, 1, 4, 0, 0, 0),
            offset=0,
            limit=2,
        )
        manager.count_sessions(
            has_project=True,
            since=datetime(2026, 1, 2, 0, 0, 0),
            until=datetime(2026, 1, 4, 0, 0, 0),
        )
    finally:
        event.remove(manager.engine, "before_cursor_execute", before_cursor_execute)

    select_statements = [item for item in statements if "FROM session" in item[0]]
    assert len(select_statements) == 2
    list_sql, list_parameters = select_statements[0]
    count_sql, count_parameters = select_statements[1]
    for statement, parameters in ((list_sql, list_parameters), (count_sql, count_parameters)):
        lowered = statement.lower()
        assert "project_workspace !=" in lowered
        assert "create_time >=" in lowered
        assert "create_time <=" in lowered
        assert "2026-01-02" in str(parameters)
        assert "2026-01-04" in str(parameters)
    assert " limit " in f" {list_sql.lower()} "
    assert " limit " not in f" {count_sql.lower()} "


# ---------------------------------------------------------------------------
# Filter matrix: every selection filter, passed and omitted, in every
# combination. The reference implementation below encodes the documented
# semantics independently of SQLAlchemy, so a combination that silently drops
# or silently adds a predicate fails here instead of only in the CLI.
# ---------------------------------------------------------------------------

_MATRIX_ROWS = (
    {"session_id": "s-agent-a", "category": "agent", "project_workspace": "/work/a",
     "create_time": datetime(2026, 1, 1, 0, 0, 0)},
    {"session_id": "s-agent-b", "category": "agent", "project_workspace": "",
     "create_time": datetime(2026, 1, 2, 0, 0, 0)},
    {"session_id": "s-driver-a", "category": "agent_driver", "project_workspace": "/work/b",
     "create_time": datetime(2026, 1, 3, 0, 0, 0)},
    {"session_id": "s-driver-b", "category": "agent_driver", "project_workspace": None,
     "create_time": datetime(2026, 1, 4, 0, 0, 0)},
    {"session_id": "s-chat-a", "category": "chat", "project_workspace": "   ",
     "create_time": datetime(2026, 1, 5, 0, 0, 0)},
    {"session_id": "s-chat-b", "category": "chat", "project_workspace": "/work/c",
     "create_time": datetime(2026, 1, 6, 0, 0, 0)},
    {"session_id": "s-plain-a", "category": "", "project_workspace": "/work/d",
     "create_time": datetime(2026, 1, 7, 0, 0, 0)},
    {"session_id": "s-plain-b", "category": "", "project_workspace": "",
     "create_time": datetime(2026, 1, 8, 0, 0, 0)},
)

# Each dimension carries the value used when it is "passed". Every value is
# chosen so that passing it alone narrows the result, which keeps the matrix
# from passing vacuously.
_FILTER_DIMENSIONS = (
    ("sessions", ["s-agent-a", "s-driver-a", "s-chat-a", "s-plain-a"]),
    ("category", "agent"),
    ("included_categories", {"agent", "chat"}),
    ("excluded_categories", {"agent_driver"}),
    ("has_project", True),
    ("since", datetime(2026, 1, 3, 0, 0, 0)),
    ("until", datetime(2026, 1, 6, 0, 0, 0)),
)


def _seed_matrix_rows(manager):
    """Create the matrix dataset through the storage layer."""
    for row in _MATRIX_ROWS:
        data = SessionData(
            session_id=row["session_id"],
            task="task",
            category=row["category"],
            project_workspace=row["project_workspace"],
        )
        data.create_time = row["create_time"]
        manager.create_session(data)


def _reference_filter(sessions=None, category=None, included_categories=None,
                      excluded_categories=None, has_project=False, since=None,
                      until=None):
    """Return the rows the documented filter semantics must select.

    This mirrors the contract in words rather than in SQL: an empty or omitted
    collection is a no-op, ``category`` is resolved to a legal name, a NULL or
    empty workspace is dropped by ``has_project`` while a whitespace-only one is
    kept, and the time bounds are inclusive.
    """
    selected = []
    for row in _MATRIX_ROWS:
        if sessions and row["session_id"] not in sessions:
            continue
        if category is not None and row["category"] != resolve_session_category(category):
            continue
        if included_categories and row["category"] not in included_categories:
            continue
        if excluded_categories and row["category"] in excluded_categories:
            continue
        if has_project and not row["project_workspace"]:
            continue
        if since is not None and row["create_time"] < since:
            continue
        if until is not None and row["create_time"] > until:
            continue
        selected.append(row)
    return selected


def _filter_combinations():
    """Yield one kwargs dict per passed/omitted combination of every filter."""
    for flags in itertools.product((False, True), repeat=len(_FILTER_DIMENSIONS)):
        kwargs = {}
        for passed, (name, value) in zip(flags, _FILTER_DIMENSIONS):
            if passed:
                kwargs[name] = value
        yield flags, kwargs


def _describe(flags):
    """Render a combination as a readable pytest id."""
    passed = [name for passed, (name, _) in zip(flags, _FILTER_DIMENSIONS) if passed]
    return "+".join(passed) if passed else "none"


@pytest.mark.parametrize("flags,kwargs", list(_filter_combinations()), ids=_describe)
def test_every_filter_combination_matches_the_documented_semantics(flags, kwargs):
    """All 128 passed/omitted combinations select exactly the reference rows."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    expected = sorted(row["session_id"] for row in _reference_filter(**kwargs))
    listed = manager.list_sessions(order_by="session_id", **kwargs)
    assert [row.session_id for row in listed] == expected
    assert manager.count_sessions(**kwargs) == len(expected)


@pytest.mark.parametrize("flags,kwargs", list(_filter_combinations()), ids=_describe)
def test_every_filter_combination_paginates_the_filtered_set(flags, kwargs):
    """Offset and limit slice the filtered set, never the unfiltered table."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    expected = sorted(row["session_id"] for row in _reference_filter(**kwargs))
    page = manager.list_sessions(order_by="session_id", offset=1, limit=2, **kwargs)
    assert [row.session_id for row in page] == expected[1:3]
    assert manager.count_sessions(**kwargs) == len(expected)


@pytest.mark.parametrize("flags,kwargs", list(_filter_combinations()), ids=_describe)
def test_every_filter_combination_survives_manager_forwarding(flags, kwargs):
    """The production manager forwards every combination without changing it."""
    storage = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(storage)
    manager = DefaultSessionManager(storage, Mock())

    expected = sorted(row["session_id"] for row in _reference_filter(**kwargs))
    listed = manager.list_sessions(order_by="session_id", **kwargs)
    assert [row.session_id for row in listed] == expected
    assert manager.count_sessions(**kwargs) == len(expected)


@pytest.mark.parametrize(
    "name,value", _FILTER_DIMENSIONS, ids=[name for name, _ in _FILTER_DIMENSIONS]
)
def test_each_filter_alone_narrows_the_result(name, value):
    """Every dimension is meaningful, so the matrix cannot pass vacuously."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    selected = manager.list_sessions(order_by="session_id", **{name: value})
    assert 0 < len(selected) < len(_MATRIX_ROWS)
    assert manager.count_sessions(**{name: value}) == len(selected)


@pytest.mark.parametrize("kwargs", [
    {},
    {"sessions": []},
    {"category": None},
    {"included_categories": set()},
    {"excluded_categories": set()},
    {"has_project": False},
    {"since": None},
    {"until": None},
    {"sessions": [], "category": None, "included_categories": set(),
     "excluded_categories": set(), "has_project": False, "since": None, "until": None},
])
def test_omitted_and_no_op_values_select_every_row(kwargs):
    """An omitted filter and its no-op value must both leave the result intact."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    listed = manager.list_sessions(order_by="session_id", **kwargs)
    assert len(listed) == len(_MATRIX_ROWS)
    assert manager.count_sessions(**kwargs) == len(_MATRIX_ROWS)


def test_empty_category_string_is_not_the_same_as_omitting_it():
    """category="" selects uncategorized rows while category=None selects all."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    uncategorized = manager.list_sessions(category="", order_by="session_id")
    assert [row.session_id for row in uncategorized] == ["s-plain-a", "s-plain-b"]
    assert manager.count_sessions(category="") == 2
    assert manager.count_sessions(category=None) == len(_MATRIX_ROWS)


def test_inclusion_and_exclusion_of_the_same_category_select_nothing():
    """Inclusion is applied before exclusion, so the two cancel out."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    rows = manager.list_sessions(
        included_categories={"agent"}, excluded_categories={"agent"}, order_by="session_id"
    )
    assert rows == []
    assert manager.count_sessions(
        included_categories={"agent"}, excluded_categories={"agent"}
    ) == 0


def test_contradictory_time_window_selects_nothing():
    """A since later than until is an empty window, not a widened one."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    rows = manager.list_sessions(
        since=datetime(2026, 1, 6, 0, 0, 0), until=datetime(2026, 1, 3, 0, 0, 0)
    )
    assert rows == []
    assert manager.count_sessions(
        since=datetime(2026, 1, 6, 0, 0, 0), until=datetime(2026, 1, 3, 0, 0, 0)
    ) == 0


def test_has_project_combined_with_an_empty_workspace_category():
    """has_project and the uncategorized filter compose without widening."""
    manager = SessionSQLAlchemy("sqlite:///:memory:")
    _seed_matrix_rows(manager)

    rows = manager.list_sessions(has_project=True, category="", order_by="session_id")
    assert [row.session_id for row in rows] == ["s-plain-a"]
    assert manager.count_sessions(has_project=True, category="") == 1
