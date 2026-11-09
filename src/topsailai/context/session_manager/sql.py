'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose: using sqlalchemy to manage session.
  Schema:
    - table_name: session
    - columns:
      - session_id, text, the session id;
      - session_name, text;
      - task, text, the task info;
      - create_time, creation time of this record; default is local time;
'''

import re
import threading

from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func as sql_func, text
from datetime import datetime, timedelta

from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy
from topsailai.context.session_category import resolve_session_category
from topsailai.logger.log_chat import logger
from topsailai.utils import db_io_tool

from .__base import SessionStorageBase, SessionData

DEFAULT_CONN = "sqlite:///memory.db"

Base = declarative_base()

class Session(Base):
    """
    Represents a session in the database.

    Attributes:
        session_id (str): Unique identifier for the session (primary key).
        session_name (str): Name of the session.
        task (str): Task information for the session.
        project_workspace (str): Project workspace path at session creation.
        pwd (str): Working directory at session creation.
        topsailai_home (str): TopsailAI home directory at session creation.
        total_tokens (int): Accumulated prompt tokens (legacy prompt-only column).
        total_cached_tokens (int): Accumulated cached prompt tokens.
        total_completion_tokens (int): Accumulated completion tokens.
        summary_count (int): Successfully applied summaries.
        turn_count (int): Settled User2Agent turns.
        tool_call_count (int): Measured tool calls.
        tool_error_count (int): Tool calls that reported an error.
        llm_request_count (int): LLM requests attempted.
        llm_request_failure_count (int): Failed LLM requests.
        tool_duration_ms_sum (int): Total tool duration in milliseconds.
        llm_request_duration_ms_sum (int): Total LLM request duration in milliseconds.
        create_time (datetime): Timestamp when the session was created.
    """
    __tablename__ = SessionStorageBase.tb_session

    session_id = Column(String(32), primary_key=True)
    session_name = Column(String, nullable=True)
    task = Column(Text, nullable=False)
    project_workspace = Column(Text, nullable=True)
    pwd = Column(Text, nullable=True)
    topsailai_home = Column(Text, nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cached_tokens = Column(Integer, default=0)
    total_completion_tokens = Column(Integer, default=0)
    summary_count = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)
    tool_call_count = Column(Integer, default=0)
    tool_error_count = Column(Integer, default=0)
    llm_request_count = Column(Integer, default=0)
    llm_request_failure_count = Column(Integer, default=0)
    tool_duration_ms_sum = Column(Integer, default=0)
    llm_request_duration_ms_sum = Column(Integer, default=0)
    create_time = Column(DateTime, nullable=False, server_default=sql_func.current_timestamp())
    update_time = Column(DateTime, nullable=False, server_default=sql_func.current_timestamp())
    category = Column(Text, nullable=False, default="", server_default="")

class SessionSQLAlchemy(SessionStorageBase):
    """
    A SQLAlchemy-based implementation of SessionStorageBase for managing sessions.

    This class provides methods to create and manage sessions.

    Attributes:
        engine: SQLAlchemy engine instance.
        SessionLocal: Session factory for database operations.
    """
    def __init__(self, conn:str):
        """
        Initialize the SessionSQLAlchemy instance with the given database connection string.

        Args:
            conn (str): Database connection string.
        """
        super(SessionSQLAlchemy, self).__init__()
        # SQLite in-memory databases are created per connection by default.
        # Use a static pool and disable same-thread checks so the same engine
        # can be shared across threads.
        connect_args = {}
        pool_kwargs = {}
        if conn.startswith("sqlite://"):
            connect_args["check_same_thread"] = False
            if ":memory:" in conn:
                pool_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(conn, connect_args=connect_args, **pool_kwargs)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        self._ensure_columns()

        self.chat_history = ChatHistorySQLAlchemy(conn)
        self.conn = conn
        self._lock = threading.Lock()

    def _ensure_columns(self):
        """Add columns introduced after the initial schema release."""
        with self.engine.connect() as conn:
            if conn.dialect.name != "sqlite":
                return
            update_time = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'session'"
            )).scalar_one_or_none()
            if update_time and (
                    "WITHOUT ROWID" in update_time.upper()
                    or re.search(r"\bSTRICT\b", update_time, re.IGNORECASE)
                    or re.search(r"\bGENERATED\b|\bAS\s*\(", update_time, re.IGNORECASE)):
                if "GENERATED" in update_time.upper() or re.search(
                        r"\bAS\s*\(", update_time, re.IGNORECASE):
                    raise RuntimeError("Unsupported generated column in SQLite session table DDL")
                raise RuntimeError("Unsupported SQLite session table DDL options")
            columns = (
                "project_workspace", "pwd", "topsailai_home", "total_tokens",
                "total_cached_tokens", "total_completion_tokens", "category",
                "summary_count", "turn_count", "tool_call_count", "tool_error_count",
                "llm_request_count", "llm_request_failure_count",
                "tool_duration_ms_sum", "llm_request_duration_ms_sum",
            )
            numeric_columns = {
                "total_tokens", "total_cached_tokens", "total_completion_tokens",
                "summary_count", "turn_count", "tool_call_count", "tool_error_count",
                "llm_request_count", "llm_request_failure_count",
                "tool_duration_ms_sum", "llm_request_duration_ms_sum",
            }
            for column_name in columns:
                result = conn.execute(
                    text("SELECT 1 FROM pragma_table_info('session') WHERE name = :col"),
                    {"col": column_name},
                )
                if not result.fetchone():
                    if column_name in numeric_columns:
                        conn.execute(text(
                            f"ALTER TABLE session ADD COLUMN {column_name} INTEGER DEFAULT 0"
                        ))
                    elif column_name == "category":
                        conn.execute(text(
                            "ALTER TABLE session ADD COLUMN category TEXT NOT NULL DEFAULT ''"
                        ))
                    else:
                        conn.execute(text(f"ALTER TABLE session ADD COLUMN {column_name} TEXT"))
            conn.commit()
            result = conn.execute(
                text("SELECT 1 FROM pragma_table_info('session') WHERE name = 'update_time'")
            )
            if result.fetchone():
                return
            self._rebuild_sqlite_session_table(conn)

    def _rebuild_sqlite_session_table(self, conn):
        """Add update_time while preserving the existing SQLite session schema."""
        table_name = SessionStorageBase.tb_session
        temporary_name = f"{table_name}__update_time_new"
        quote_identifier = lambda value: '"' + value.replace('"', '""') + '"'
        table_identifier = quote_identifier(table_name)
        temporary_identifier = quote_identifier(temporary_name)

        def split_table_items(body):
            """Split table definitions at commas outside quotes and parentheses."""
            items = []
            start = 0
            depth = 0
            quote = None
            index = 0
            while index < len(body):
                char = body[index]
                if quote:
                    if char == quote:
                        if index + 1 < len(body) and body[index + 1] == quote:
                            index += 1
                        else:
                            quote = None
                elif char in "'\"`":
                    quote = char
                elif char == '[':
                    quote = ']'
                elif char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                    if depth < 0:
                        raise RuntimeError("Unsupported SQLite session table DDL")
                elif char == ',' and depth == 0:
                    items.append(body[start:index].strip())
                    start = index + 1
                index += 1
            if quote or depth:
                raise RuntimeError("Unsupported SQLite session table DDL")
            items.append(body[start:].strip())
            if any(not item for item in items):
                raise RuntimeError("Unsupported SQLite session table DDL")
            return items

        def table_body(ddl):
            """Return the table body and trailing options after its outer parentheses."""
            opening = ddl.find('(', ddl.lower().find('session'))
            if opening < 0:
                raise RuntimeError("Unsupported SQLite session table DDL")
            depth = 0
            quote = None
            closing = None
            for index in range(opening, len(ddl)):
                char = ddl[index]
                if quote:
                    if char == quote:
                        quote = None
                elif char in "'\"`":
                    quote = char
                elif char == '[':
                    quote = ']'
                elif char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                    if depth == 0:
                        closing = index
                        break
                    if depth < 0:
                        break
            if closing is None or ddl[closing + 1:].strip():
                raise RuntimeError("Unsupported SQLite session table DDL options")
            return ddl[opening + 1:closing]

        def index_inventory(connection, name):
            """Return index semantics, including indexes created by constraints."""
            result = []
            for row in connection.execute(text(
                f"PRAGMA index_list({quote_identifier(name)})"
            )).fetchall():
                index_name, unique, origin, partial = row[1], row[2], row[3], row[4]
                columns = tuple(item[2] for item in connection.execute(text(
                    f"PRAGMA index_info({quote_identifier(index_name)})"
                )).fetchall())
                sql = connection.execute(text(
                    "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
                ), {"name": index_name}).scalar_one_or_none()
                result.append((index_name, sql, unique, origin, partial, columns))
            return tuple(sorted(result))

        def inventory(connection, name, data_columns=None):
            """Return the SQLite schema and data inventory for a table."""
            columns = connection.execute(text(f"PRAGMA table_info({quote_identifier(name)})")).fetchall()
            foreign_keys = connection.execute(text(
                f"PRAGMA foreign_key_list({quote_identifier(name)})"
            )).fetchall()
            indexes = index_inventory(connection, name)
            triggers = tuple(connection.execute(text(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = :name ORDER BY name"
            ), {"name": name}).fetchall())
            names = data_columns or [row[1] for row in columns]
            projection = ", ".join(quote_identifier(column) for column in names)
            rows = tuple(connection.execute(text(
                f"SELECT {projection} FROM {quote_identifier(name)} ORDER BY rowid"
            )).fetchall())
            return columns, foreign_keys, indexes, triggers, rows

        original_ddl = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"
        ), {"name": table_name}).scalar_one_or_none()
        if not original_ddl:
            raise RuntimeError("SQLite session migration cannot find the session table DDL")
        create_pattern = re.compile(
            r'^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)("session"|`session`|\[session\]|session)(\s*\()',
            re.IGNORECASE | re.DOTALL,
        )
        match = create_pattern.match(original_ddl)
        if not match:
            raise RuntimeError("Unsupported SQLite session table DDL")
        body = table_body(original_ddl)
        items = split_table_items(body)
        upper_ddl = original_ddl.upper()
        if "WITHOUT ROWID" in upper_ddl or " STRICT" in upper_ddl:
            raise RuntimeError("Unsupported SQLite session table DDL options")
        if any(re.search(r"\bGENERATED\b|\bAS\s*\(", item, re.IGNORECASE) for item in items):
            raise RuntimeError("Unsupported generated column in SQLite session table DDL")

        before = inventory(conn, table_name)
        if any(row[1] == "update_time" for row in before[0]):
            return
        temporary_exists = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE name = :name"
        ), {"name": temporary_name}).scalar_one_or_none()
        if temporary_exists:
            raise RuntimeError("SQLite session migration found a stale replacement table")

        constraint_pattern = re.compile(
            r"^(PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|CONSTRAINT)\b",
            re.IGNORECASE,
        )
        insert_at = next((index for index, item in enumerate(items)
                          if constraint_pattern.match(item)), len(items))
        items.insert(insert_at, "update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")
        create_ddl = (
            match.group(1) + temporary_identifier + match.group(3)
            + ", ".join(items) + ")"
        )
        original_columns = [row[1] for row in before[0]]
        quoted_columns = ", ".join(quote_identifier(column) for column in original_columns)
        old_rows = before[4]
        original_foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()
        conn.commit()
        migration_error = None
        try:
            conn.execute(text("PRAGMA foreign_keys = 0"))
            conn.commit()
            conn.exec_driver_sql("BEGIN")
            conn.execute(text(create_ddl))
            conn.execute(text(
                f"INSERT INTO {temporary_identifier} ({quoted_columns}, update_time) "
                f"SELECT {quoted_columns}, create_time FROM {table_identifier}"
            ))
            conn.execute(text(f"DROP TABLE {table_identifier}"))
            conn.execute(text(f"ALTER TABLE {temporary_identifier} RENAME TO {table_identifier}"))
            for index_name, index_sql, *_ in before[2]:
                if index_sql:
                    conn.execute(text(index_sql))
            for _, trigger_sql in before[3]:
                conn.execute(text(trigger_sql))
            after = inventory(conn, table_name, original_columns)
            if after[0][:-1] != before[0] or after[1] != before[1]:
                raise RuntimeError("SQLite session migration changed table constraints")
            if after[2] != before[2]:
                raise RuntimeError("SQLite session migration changed the index inventory")
            if after[3] != before[3] or after[4] != old_rows:
                raise RuntimeError("SQLite session migration changed schema or row data")
            update_rows = conn.execute(text(
                f"SELECT update_time, create_time FROM {table_identifier} ORDER BY rowid"
            )).fetchall()
            if any(update_time != create_time for update_time, create_time in update_rows):
                raise RuntimeError("SQLite session migration did not backfill update_time")
            update_column = next(row for row in after[0] if row[1] == "update_time")
            if update_column[2].upper() != "DATETIME" or update_column[3] != 1 \
                    or "CURRENT_TIMESTAMP" not in update_column[4].upper() \
                    or update_column[5] != 0:
                raise RuntimeError("SQLite session migration changed update_time definition")
            conn.commit()
        except BaseException as error:
            migration_error = error
            try:
                conn.rollback()
            except BaseException:
                logger.exception("SQLite session migration rollback failed")
            raise
        finally:
            try:
                if conn.in_transaction():
                    conn.rollback()
                conn.execute(text(f"PRAGMA foreign_keys = {int(bool(original_foreign_keys))}"))
                conn.commit()
            except BaseException:
                if migration_error is None:
                    raise
                logger.exception("SQLite session migration foreign-key restoration failed")

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Return a valid category or an empty string and log invalid input."""
        if category == "":
            return ""
        if isinstance(category, str) and re.fullmatch(r"[a-z0-9_]+", category):
            return category
        logger.error("Invalid session category %r; storing an empty string", category)
        return ""

    def create_session(self, session_data:SessionData) -> bool:
        """
        Create a new session in the storage.

        Args:
            session_data (SessionData): The session data to create.

        Returns:
            bool: True if the session was created.

        Raises:
            ValueError: If a session with the same session_id already exists.
        """
        with self._lock:
            db_session = self.SessionLocal()
            original_busy_timeout = db_io_tool.apply_write_block(db_session)
            try:
                # Avoid duplicate session_id
                if db_session.query(Session).filter(Session.session_id == session_data.session_id).first():
                    raise ValueError(f"Session {session_data.session_id} already exists")

                session_time = session_data.create_time or datetime.now()
                new_session = Session(
                    session_id=session_data.session_id,
                    session_name=session_data.session_name,
                    task=session_data.task,
                    project_workspace=session_data.project_workspace,
                    pwd=session_data.pwd,
                    topsailai_home=session_data.topsailai_home,
                    category=self._normalize_category(session_data.category),
                    create_time=session_time,
                    update_time=session_time
                )
                db_session.add(new_session)
                db_session.commit()
                logger.info(f"new session: session_id={session_data.session_id}, task={session_data.task}")

                return True
            except Exception as e:
                db_session.rollback()
                logger.error(f"create_session failed: {e}")
                raise db_io_tool.handle_write_failure(
                    e, "create_session", session_id=session_data.session_id,
                )
            finally:
                db_io_tool.restore_write_block(db_session, original_busy_timeout)
                db_session.close()

    def _apply_session_filters(self, query, sessions=None, category=None):
        """Apply ID and optional exact category predicates before pagination."""
        if sessions:
            query = query.filter(Session.session_id.in_(sessions))
        if category is not None:
            query = query.filter(Session.category == resolve_session_category(category))
        return query

    def list_sessions(
        self,
        sessions: list[str] = None,
        order_by: str = None,
        offset: int = 0,
        limit: int = None,
        category: str = None,
    ) -> list[SessionData]:
        """List sessions with SQL-side ID/category filtering and pagination."""
        db_session = self.SessionLocal()
        try:
            query = self._apply_session_filters(
                db_session.query(Session), sessions=sessions, category=category
            )
            query = self._apply_order_by(query, order_by)
            if offset is not None:
                query = query.offset(offset)
            rows = query.limit(limit).all() if limit is not None else query.all()
            result = []
            for session in rows:
                session_data = SessionData(
                    session_id=session.session_id,
                    task=session.task,
                    project_workspace=session.project_workspace,
                    pwd=session.pwd,
                    topsailai_home=session.topsailai_home,
                    total_tokens=session.total_tokens or 0,
                    total_cached_tokens=session.total_cached_tokens or 0,
                    total_completion_tokens=session.total_completion_tokens or 0,
                    category=session.category or "",
                    summary_count=session.summary_count or 0,
                    turn_count=session.turn_count or 0,
                    tool_call_count=session.tool_call_count or 0,
                    tool_error_count=session.tool_error_count or 0,
                    llm_request_count=session.llm_request_count or 0,
                    llm_request_failure_count=session.llm_request_failure_count or 0,
                    tool_duration_ms_sum=session.tool_duration_ms_sum or 0,
                    llm_request_duration_ms_sum=session.llm_request_duration_ms_sum or 0,
                )
                session_data.session_name = session.session_name
                session_data.create_time = session.create_time
                session_data.update_time = session.update_time
                result.append(session_data)
            return result
        except Exception as e:
            db_session.rollback()
            logger.error(f"list_sessions failed: {e}")
            raise e
        finally:
            db_session.close()

    def count_sessions(self, sessions: list[str] = None, category: str = None) -> int:
        """Count sessions matching ID/category filters without pagination."""
        db_session = self.SessionLocal()
        try:
            query = self._apply_session_filters(
                db_session.query(Session), sessions=sessions, category=category
            )
            return query.count()
        except Exception as e:
            db_session.rollback()
            logger.error(f"count_sessions failed: {e}")
            raise e
        finally:
            db_session.close()

    def _apply_order_by(self, query, order_by: str):
        """
        Apply SQLAlchemy ordering based on the order_by string.

        Args:
            query: SQLAlchemy query object.
            order_by (str): Field name to sort by. Prefix with ``-`` for descending.

        Returns:
            Query with ordering applied.

        Raises:
            ValueError: If the field name is not supported.
        """
        allowed_fields = {
            "session_id": Session.session_id,
            "session_name": Session.session_name,
            "task": Session.task,
            "create_time": Session.create_time,
        }

        if order_by is None:
            return query.order_by(Session.create_time.desc())

        direction = "asc"
        field_name = order_by
        if field_name.startswith("-"):
            direction = "desc"
            field_name = field_name[1:]

        if field_name not in allowed_fields:
            raise ValueError(f"Unsupported order_by field: {order_by}")

        column = allowed_fields[field_name]
        if direction == "desc":
            return query.order_by(column.desc())
        return query.order_by(column.asc())

    def get_session(self, session_id: str) -> SessionData | None:
        """
        Retrieve a single session by its ID.

        Args:
            session_id (str): The session id to retrieve.

        Returns:
            SessionData | None: The session data if found, None otherwise.
        """
        db_session = self.SessionLocal()
        try:
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            if not session:
                return None

            session_data = SessionData(
                session_id=session.session_id,
                task=session.task,
                project_workspace=session.project_workspace,
                pwd=session.pwd,
                topsailai_home=session.topsailai_home,
                total_tokens=session.total_tokens or 0,
                total_cached_tokens=session.total_cached_tokens or 0,
                total_completion_tokens=session.total_completion_tokens or 0,
                category=session.category or "",
                summary_count=session.summary_count or 0,
                turn_count=session.turn_count or 0,
                tool_call_count=session.tool_call_count or 0,
                tool_error_count=session.tool_error_count or 0,
                llm_request_count=session.llm_request_count or 0,
                llm_request_failure_count=session.llm_request_failure_count or 0,
                tool_duration_ms_sum=session.tool_duration_ms_sum or 0,
                llm_request_duration_ms_sum=session.llm_request_duration_ms_sum or 0,
            )
            session_data.session_name = session.session_name
            session_data.create_time = session.create_time
            session_data.update_time = session.update_time
            return session_data
        except Exception as e:
            db_session.rollback()
            logger.error(f"get_session failed: session_id={session_id}, {e}")
            raise e
        finally:
            db_session.close()


    def exists_session(self, session_id) -> bool:
        """
        Check if a session with the given session_id exists.

        Args:
            session_id (str): The session id to check.

        Returns:
            bool: True if the session exists, False otherwise.
        """
        db_session = self.SessionLocal()
        try:
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            return session is not None
        except Exception as e:
            db_session.rollback()
            logger.error(f"exists_session failed: {e}")
            raise e
        finally:
            db_session.close()

    def retrieve_messages(self, session_id:str) -> list[dict]:
        """ retrieve messages for session """
        return self.chat_history.retrieve_messages(session_id)

    def get_messages_by_session(self, session_id:str):
        """ get messages by chat_history_manager """
        return self.chat_history.get_messages_by_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its associated chat history.

        Args:
            session_id (str): The session id to delete.

        Returns:
            bool: True if the session was deleted, False if it did not exist.
                A database I/O failure never returns; it blocks or exits the process.
        """
        db_session = self.SessionLocal()
        original_busy_timeout = db_io_tool.apply_write_block(db_session)
        try:
            # Check if session exists
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            if not session:
                logger.warning(f"delete_session: session not found: session_id={session_id}")
                return False

            # Delete the session
            db_session.delete(session)

            # Delete associated chat history
            self.chat_history.del_messages(session_id=session_id)

            db_session.commit()
            logger.info(f"Session deleted: session_id={session_id}")
            return True

        except Exception as e:
            db_session.rollback()
            logger.error(f"delete_session failed: session_id={session_id}, {e}")
            raise db_io_tool.handle_write_failure(
                e, "delete_session", session_id=session_id,
            )
        finally:
            db_io_tool.restore_write_block(db_session, original_busy_timeout)
            db_session.close()

    def clean_sessions(self, before_seconds: int):
        """
        Delete sessions that were created before the specified number of seconds ago.

        Args:
            before_seconds (int): Delete sessions older than this many seconds from current time.

        Returns:
            int: Number of sessions deleted.
                A database I/O failure never returns; it blocks or exits the process.
        """
        db_session = self.SessionLocal()
        original_busy_timeout = db_io_tool.apply_write_block(db_session)
        try:
            # Calculate the cutoff time
            cutoff_time = datetime.now() - timedelta(seconds=before_seconds)

            # Find sessions to delete
            # Use <= for before_seconds=0 edge case to avoid deleting sessions created at exactly the current time
            if before_seconds == 0:
                # When before_seconds=0, we should delete nothing since create_time >= now
                sessions_to_delete = []
            else:
                sessions_to_delete = db_session.query(Session).filter(
                    Session.create_time < cutoff_time
                ).all()

            deleted_count = 0
            for session in sessions_to_delete:
                # Delete associated chat history first
                self.chat_history.del_messages(session_id=session.session_id)
                # Delete the session
                db_session.delete(session)
                deleted_count += 1
                logger.info(f"Cleaned old session: session_id={session.session_id}, created={session.create_time}")

            if deleted_count > 0:
                db_session.commit()
                logger.info(f"Cleaned {deleted_count} sessions older than {before_seconds} seconds")

            return deleted_count

        except Exception as e:
            db_session.rollback()
            logger.error(f"clean_sessions failed: {e}")
            raise db_io_tool.handle_write_failure(e, "clean_sessions")
        finally:
            db_io_tool.restore_write_block(db_session, original_busy_timeout)
            db_session.close()

    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """
        Update the name of an existing session.

        The session row's ``update_time`` is refreshed in the same transaction
        whenever the stored name actually changes, so the "updated at" column
        always reflects the moment of the rename.

        Args:
            session_id (str): The session id to update.
            session_name (str): The new session name.

        Returns:
            bool: True if the session name was updated successfully (or already
                  equalled the requested name), False if the session does not
                  exist. A database I/O failure never returns: it blocks, then
                  exits the process, so a lost write cannot look like success.
        """
        db_session = self.SessionLocal()
        original_busy_timeout = db_io_tool.apply_write_block(db_session)
        try:
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            if not session:
                logger.warning(f"update_session_name: session not found: session_id={session_id}")
                return False

            if session.session_name == session_name:
                return True
            session.session_name = session_name
            session.update_time = datetime.now()
            db_session.commit()
            logger.info(f"update_session_name: session_id={session_id}, session_name={session_name}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"update_session_name failed: session_id={session_id}, {e}")
            if db_io_tool.is_db_io_failure(e):
                raise db_io_tool.handle_write_failure(
                    e, "update_session_name", session_id=session_id,
                )
            return False
        finally:
            db_io_tool.restore_write_block(db_session, original_busy_timeout)
            db_session.close()

    def accumulate_session_tokens(
        self,
        session_id: str,
        current_tokens: int,
        current_cached_tokens: int,
        current_completion_tokens: int = 0,
    ) -> bool:
        """Atomically add one request's prompt, completion, and cache deltas."""
        if not session_id:
            return False

        # Normalize negative deltas to zero so misreported values cannot subtract
        # from the session totals.
        delta_tokens = max(0, int(current_tokens))
        delta_cached = max(0, int(current_cached_tokens))
        delta_completion = max(0, int(current_completion_tokens))

        db_session = self.SessionLocal()
        original_busy_timeout = db_io_tool.apply_write_block(db_session)
        try:
            result = db_session.execute(
                text(
                    "UPDATE session SET "
                    "total_tokens = total_tokens + :tokens, "
                    "total_cached_tokens = total_cached_tokens + :cached, "
                    "total_completion_tokens = total_completion_tokens + :completion, "
                    "update_time = CASE WHEN :has_delta = 1 THEN :update_time ELSE update_time END "
                    "WHERE session_id = :session_id"
                ),
                {
                    "tokens": delta_tokens,
                    "cached": delta_cached,
                    "completion": delta_completion,
                    "has_delta": int(bool(delta_tokens or delta_cached or delta_completion)),
                    "update_time": datetime.now(),
                    "session_id": session_id,
                },
            )
            db_session.commit()
            if result.rowcount == 1:
                logger.info(
                    f"accumulate_session_tokens: session_id={session_id}, "
                    f"+tokens={delta_tokens}, +cached={delta_cached}, "
                    f"+completion={delta_completion}"
                )
                return True
            logger.warning(
                f"accumulate_session_tokens: session not found: session_id={session_id}"
            )
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(
                f"accumulate_session_tokens failed: session_id={session_id}, "
                f"tokens={delta_tokens}, cached={delta_cached}, "
                f"completion={delta_completion}, {e}"
            )
            if db_io_tool.is_db_io_failure(e):
                raise db_io_tool.handle_write_failure(
                    e, "accumulate_session_tokens", session_id=session_id,
                )
            return False
        finally:
            db_io_tool.restore_write_block(db_session, original_busy_timeout)
            db_session.close()

    def accumulate_session_metrics(
        self,
        session_id: str,
        turn_count: int = 0,
        tool_call_count: int = 0,
        tool_error_count: int = 0,
        llm_request_count: int = 0,
        llm_request_failure_count: int = 0,
        tool_duration_ms_sum: int = 0,
        llm_request_duration_ms_sum: int = 0,
        summary_count: int = 0,
    ) -> bool:
        """Atomically add one settled attempt's execution metric deltas."""
        if not session_id:
            return False

        # Normalize negative deltas to zero so misreported values cannot subtract
        # from the session totals.
        deltas = {
            "summary_count": max(0, int(summary_count)),
            "turn_count": max(0, int(turn_count)),
            "tool_call_count": max(0, int(tool_call_count)),
            "tool_error_count": max(0, int(tool_error_count)),
            "llm_request_count": max(0, int(llm_request_count)),
            "llm_request_failure_count": max(0, int(llm_request_failure_count)),
            "tool_duration_ms_sum": max(0, int(tool_duration_ms_sum)),
            "llm_request_duration_ms_sum": max(0, int(llm_request_duration_ms_sum)),
        }
        has_delta = int(any(deltas.values()))

        db_session = self.SessionLocal()
        original_busy_timeout = db_io_tool.apply_write_block(db_session)
        try:
            result = db_session.execute(
                text(
                    "UPDATE session SET "
                    "summary_count = COALESCE(summary_count, 0) + :summary_count, "
                    "turn_count = turn_count + :turn_count, "
                    "tool_call_count = tool_call_count + :tool_call_count, "
                    "tool_error_count = tool_error_count + :tool_error_count, "
                    "llm_request_count = llm_request_count + :llm_request_count, "
                    "llm_request_failure_count = llm_request_failure_count + :llm_request_failure_count, "
                    "tool_duration_ms_sum = tool_duration_ms_sum + :tool_duration_ms_sum, "
                    "llm_request_duration_ms_sum = llm_request_duration_ms_sum + :llm_request_duration_ms_sum, "
                    "update_time = CASE WHEN :has_delta = 1 THEN :update_time ELSE update_time END "
                    "WHERE session_id = :session_id"
                ),
                {
                    **deltas,
                    "has_delta": has_delta,
                    "update_time": datetime.now(),
                    "session_id": session_id,
                },
            )
            db_session.commit()
            if result.rowcount == 1:
                logger.info(
                    f"accumulate_session_metrics: session_id={session_id}, "
                    f"+summaries={deltas['summary_count']}, "
                    f"+turns={deltas['turn_count']}, "
                    f"+tool_calls={deltas['tool_call_count']}, "
                    f"+tool_errors={deltas['tool_error_count']}, "
                    f"+llm_requests={deltas['llm_request_count']}, "
                    f"+llm_failures={deltas['llm_request_failure_count']}"
                )
                return True
            logger.warning(
                f"accumulate_session_metrics: session not found: session_id={session_id}"
            )
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(
                f"accumulate_session_metrics failed: session_id={session_id}, "
                f"deltas={deltas}, {e}"
            )
            if db_io_tool.is_db_io_failure(e):
                raise db_io_tool.handle_write_failure(
                    e, "accumulate_session_metrics", session_id=session_id,
                )
            return False
        finally:
            db_io_tool.restore_write_block(db_session, original_busy_timeout)
            db_session.close()

    def get_session_token_totals(self, session_id: str) -> tuple[int, int] | None:
        """Return legacy prompt and cached-prompt totals for a session."""
        usage = self.get_session_token_usage(session_id)
        if usage is None:
            return None
        return usage["total_prompt_tokens"], usage["total_cached_tokens"]

    def get_session_token_usage(self, session_id: str) -> dict[str, int] | None:
        """Return explicit prompt, completion, combined, and cache totals."""
        if not session_id:
            return None

        db_session = self.SessionLocal()
        try:
            session = db_session.query(Session).filter(
                Session.session_id == session_id
            ).first()
            if not session:
                logger.warning(
                    f"get_session_token_usage: session not found: session_id={session_id}"
                )
                return None

            prompt_tokens = session.total_tokens or 0
            completion_tokens = session.total_completion_tokens or 0
            return {
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "total_usage_tokens": prompt_tokens + completion_tokens,
                "total_cached_tokens": session.total_cached_tokens or 0,
            }
        except Exception as e:
            db_session.rollback()
            logger.error(f"get_session_token_usage failed: session_id={session_id}, {e}")
            return None
        finally:
            db_session.close()
