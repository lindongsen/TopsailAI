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

from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func as sql_func
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
        create_time (datetime): Timestamp when the session was created.
    """
    __tablename__ = SessionStorageBase.tb_session

    session_id = Column(String(32), primary_key=True)
    session_name = Column(String, nullable=True)
    task = Column(Text, nullable=False)
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
        self.engine = create_engine(conn)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        self.chat_history = ChatHistorySQLAlchemy(conn)

    def create_session(self, session_data:SessionData):
        """
        Create a new session in the storage and keep only the most recent 100 sessions.

        Args:
            session_data (SessionData): The session data to create.
        """
        db_session = self.SessionLocal()
        try:
            new_session = Session(
                session_id=session_data.session_id,
                session_name=session_data.session_name,
                task=session_data.task,
                create_time=session_data.create_time or datetime.now()
            )
            db_session.add(new_session)
            db_session.commit()
            logger.info(f"new session: session_id={session_data.session_id}, task={session_data.task}")

            # Keep only the most recent 100 sessions
            total_count = db_session.query(Session).count()
            if total_count > 100:
                # Delete the oldest sessions to keep only 100
                sessions_to_delete = db_session.query(Session).order_by(Session.create_time.asc()).limit(total_count - 100).all()
                for session in sessions_to_delete:
                    db_session.delete(session)
                    self.chat_history.del_messages(session_id=session.session_id)
                db_session.commit()
                logger.info(f"clear oldest sessions")
        except Exception as e:
            db_session.rollback()
            logger.error(f"create_session failed: {e}")
            raise e
        finally:
            db_session.close()

    def list_sessions(self, offset: int = None, limit: int = None) -> list[SessionData]:
        """
        List sessions from the storage with optional pagination.

        Args:
            offset (int, optional): Number of sessions to skip. Defaults to None.
            limit (int, optional): Maximum number of sessions to return. If None, returns all sessions.

        Returns:
            list[SessionData]: List of session data objects, ordered by creation time (descending).
        """
        db_session = self.SessionLocal()
        try:
            query = db_session.query(Session).order_by(Session.create_time.desc())

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
                    task=session.task
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

    def delete_session(self, session_id: str):
        """
        Delete a session and its associated chat history.

        Args:
            session_id (str): The session id to delete.

        Raises:
            Exception: If the session does not exist or deletion fails.
        """
        db_session = self.SessionLocal()
        try:
            # Check if session exists
            session = db_session.query(Session).filter(Session.session_id == session_id).first()
            if not session:
                raise Exception(f"Session {session_id} does not exist")

            # Delete the session
            db_session.delete(session)

            # Delete associated chat history
            self.chat_history.del_messages(session_id=session_id)

            db_session.commit()
            logger.info(f"Session deleted: session_id={session_id}")

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
