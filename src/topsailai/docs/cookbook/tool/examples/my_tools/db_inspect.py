"""Read-only SQLite inspection exposed as db_inspect-query and db_inspect-tables tools."""

# Dict form: the key is the action name, so this module registers
# db_inspect-query and db_inspect-tables.
#
# Scenario: an operator points the agent at a local SQLite file and asks what is
# inside it. The connection is opened read-only, so a generated INSERT/UPDATE
# cannot damage the database.

import sqlite3
from pathlib import Path

MAX_ROWS = 200


def _connect(db: str) -> sqlite3.Connection:
    """Open one SQLite file read-only.

    Args:
        db: Absolute path of the SQLite file.

    Returns:
        A read-only connection.
    """
    path = Path(db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"no such database: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def query(db: str = "", sql: str = "", limit: str = "50") -> str:
    """Run one read-only SELECT and return the rows as text.

    Args:
        db: Absolute path of the SQLite file.
        sql: A single SELECT statement. Other statements are rejected.
        limit: Maximum rows to return, as a decimal string. Capped at 200.

    Returns:
        A header line, then one pipe-separated line per row, or an error message.
    """
    if not db or not sql:
        return "error: db and sql are required"
    if not sql.lstrip().lower().startswith(("select", "with", "pragma")):
        return "error: only SELECT, WITH and PRAGMA statements are allowed"

    try:
        max_rows = int(limit)
    except (TypeError, ValueError):
        return "error: limit must be an integer"
    if max_rows <= 0:
        return "error: limit must be positive"
    max_rows = min(max_rows, MAX_ROWS)

    try:
        with _connect(db) as conn:
            cursor = conn.execute(sql)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(max_rows)
    except (sqlite3.Error, OSError) as exc:
        return f"error: {exc}"

    if not columns:
        return "error: statement returned no columns"
    lines = ["|".join(columns)]
    lines.extend("|".join("" if v is None else str(v) for v in row) for row in rows)
    lines.append(f"rows: {len(rows)} (limit={max_rows})")
    return "\n".join(lines)


def tables(db: str = "") -> str:
    """List the tables and views of one SQLite file with their row counts.

    Args:
        db: Absolute path of the SQLite file.

    Returns:
        One line per table as name|type|rows, or an error message.
    """
    if not db:
        return "error: db is required"

    try:
        with _connect(db) as conn:
            names = conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
            lines = []
            for name, kind in names:
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                lines.append(f"{name}|{kind}|{count}")
    except (sqlite3.Error, OSError) as exc:
        return f"error: {exc}"

    if not lines:
        return "no table found"
    return "\n".join(lines)


TOOLS = {
    "query": query,
    "tables": tables,
}
