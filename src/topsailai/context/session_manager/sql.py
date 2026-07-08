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

import threading

from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func as sql_func, text
from datetime import datetime, timedelta

from topsailai.context.chat_history_manager.sql import ChatHistorySQLAlchemy
from topsailai.logger.log_chat import logger

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
        create_time (datetime): Timestamp when the session was created.
    """
    __tablename__ = SessionStorageBase.tb_session

    session_id = Column(String(32), primary_key=True)
    session_name = Column(String, nullable=True)
    task = Column(Text, nullable=False)
    project_workspace = Column(Text, nullable=True)
    pwd = Column(Text, nullable=True)
    topsailai_home = Column(Text, nullable=True)
    create_time = Column(DateTime, nullable=False, server_default=sql_func.current_timestamp())

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
            for column_name in ("project_workspace", "pwd", "topsailai_home"):
                result = conn.execute(
                    text("SELECT 1 FROM pragma_table_info('session') WHERE name = :col"),
                    {"col": column_name},
                )
                if not result.fetchone():
                    conn.execute(text(f"ALTER TABLE session ADD COLUMN {column_name} TEXT"))
            conn.commit()

    def create_session(self, session_data:SessionData) -> bool:
        """
        Create a new session in the storage and keep only the most recent 100 sessions.

        Args:
            session_data (SessionData): The session data to create.

        Returns:
            bool: True if the session was created.

        Raises:
            ValueError: If a session with the same session_id already exists.
        """
        with self._lock:
            db_session = self.SessionLocal()
            try:
                # Avoid duplicate session_id
                if db_session.query(Session).filter(Session.session_id == session_data.session_id).first():
                    raise ValueError(f"Session {session_data.session_id} already exists")

                new_session = Session(
                    session_id=session_data.session_id,
                    session_name=session_data.session_name,
                    task=session_data.task,
                    project_workspace=session_data.project_workspace,
                    pwd=session_data.pwd,
                    topsailai_home=session_data.topsailai_home,
                    create_time=session_data.create_time or datetime.now()
                )
                db_session.add(new_session)
                db_session.commit()
                logger.info(f"new session: session_id={session_data.session_id}, task={session_data.task}")

                # Keep only the most recent 100 sessions
                total_count = db_session.query(Session).count()
                if total_count and total_count > 100:
                    # Delete the oldest sessions to keep only 100
                    sessions_to_delete = db_session.query(Session).order_by(Session.create_time.asc()).limit(total_count - 100).all()
                    for session in sessions_to_delete:
                        db_session.delete(session)
                        self.chat_history.del_messages(session_id=session.session_id)
                    db_session.commit()
                    logger.info(f"clear oldest sessions")
                return True
            except Exception as e:
                db_session.rollback()
                logger.error(f"create_session failed: {e}")
                raise e
            finally:
                db_session.close()

    def list_sessions(
        self,
        sessions: list[str] = None,
        order_by: str = None,
        offset: int = 0,
        limit: int = None,
    ) -> list[SessionData]:
        """
        List sessions from the storage with optional filtering, sorting, and pagination.

        Args:
            sessions (list[str], optional): A list of session IDs to include.
                When provided, only sessions whose ID is in this list are returned.
                When empty or None, all sessions are returned.
            order_by (str, optional): Field name to sort by. Supported fields are
                ``session_id``, ``session_name``, ``task``, and ``create_time``.
                Prefix the field name with ``-`` for descending order
                (e.g., ``-create_time``). When not provided, sessions are ordered
                by ``create_time`` descending.
            offset (int, optional): Number of sessions to skip. Defaults to ``0``.
            limit (int, optional): Maximum number of sessions to return.
                If ``None``, all matching sessions are returned.

        Returns:
            list[SessionData]: List of session data objects matching the query.
        """
        db_session = self.SessionLocal()
        try:
            query = db_session.query(Session)

            # Apply session ID filter if provided
            if sessions:
                query = query.filter(Session.session_id.in_(sessions))

            # Apply ordering
            query = self._apply_order_by(query, order_by)

            # Apply offset if provided
            if offset is not None:
                query = query.offset(offset)

            # Apply limit if provided, otherwise get all
            if limit is not None:
                sessions = query.limit(limit).all()
            else:
                sessions = query.all()

            result = []
            for session in sessions:
                session_data = SessionData(
                    session_id=session.session_id,
                    task=session.task,
                    project_workspace=session.project_workspace,
                    pwd=session.pwd,
                    topsailai_home=session.topsailai_home,
                )
                session_data.session_name = session.session_name
                session_data.create_time = session.create_time
                result.append(session_data)
            return result
        except Exception as e:
            db_session.rollback()
            logger.error(f"list_sessions failed: {e}")
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
            )
            session_data.session_name = session.session_name
            session_data.create_time = session.create_time
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
        """
        db_session = self.SessionLocal()
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
            raise e
        finally:
            db_session.close()

    def clean_sessions(self, before_seconds: int):
        """
        Delete sessions that were created before the specified number of seconds ago.

        Args:
            before_seconds (int): Delete sessions older than this many seconds from current time.

        Returns:
            int: Number of sessions deleted.
        """
        db_session = self.SessionLocal()
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
            raise e
        finally:
            db_session.close()

    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """
        Update the name of an existing session.

        Args:
            session_id (str): The session id to update.
            session_name (str): The new session name.

        Returns:
            bool: True if the session name was updated successfully,
                  False if the session does not exist or the update failed.
        """
        db_session = self.SessionLocal()
        try:
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            if not session:
                logger.warning(f"update_session_name: session not found: session_id={session_id}")
                return False

            session.session_name = session_name
            db_session.commit()
            logger.info(f"update_session_name: session_id={session_id}, session_name={session_name}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"update_session_name failed: session_id={session_id}, {e}")
            return False
        finally:
            db_session.close()
