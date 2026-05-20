"""
SQLAlchemy-based implementation of session management in AI engineering User Session.

This module provides a concrete implementation of the SessionStorageBase
using SQLAlchemy ORM for database operations. It handles CRUD operations
for session data with proper transaction management.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from sqlalchemy import create_engine, Column, String, Text, DateTime, Index, desc, asc
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from topsailai_server.agent_daemon.storage.session_manager.base import SessionData, SessionStorageBase

Base = declarative_base()


class SessionModel(Base):
    """
    SQLAlchemy model for the session table.

    This model maps the session data structure to database columns
    with appropriate indexing for efficient querying.
    """
    __tablename__ = SessionStorageBase.tb_session

    session_id = Column(String(32), primary_key=True)
    session_name = Column(String(255), default=None)
    task = Column(Text, default=None)
    create_time = Column(DateTime, default=datetime.now)
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    processed_msg_id = Column(String(32), default=None)

    # Create index on processed_msg_id for efficient querying
    ix_session_processed_msg_id = Index('ix_session_processed_msg_id', processed_msg_id)


class SessionSQLAlchemy(SessionStorageBase):
    """
    SQLAlchemy-based session storage implementation.

    This class provides concrete database operations for session management
    using SQLAlchemy ORM. It supports SQLite and other SQLAlchemy-compatible
    databases with automatic table creation and transaction management.

    Attributes:
        engine: SQLAlchemy engine instance
        Session: SQLAlchemy session factory
    """
    def __init__(self, db_url):
        """
        Initialize the SQLAlchemy session storage.

        Args:
            db_url (str or Engine): Database connection URL for SQLAlchemy,
                                    or an existing SQLAlchemy Engine instance.
        """
        super().__init__()
        if isinstance(db_url, Engine):
            self.engine = db_url
        else:
            self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def get_engine(self):
        """Return the SQLAlchemy engine instance."""
        return self.engine

    def exists_session(self, session_id) -> bool:
        """
        Check if a session exists in the database.

        Args:
            session_id (str): The session ID to check

        Returns:
            bool: True if the session exists, False otherwise
        """
        session = self.Session()
        try:
            return session.query(SessionModel).filter_by(session_id=session_id).first() is not None
        finally:
            session.close()

    def create(self, session_data: SessionData) -> bool:
        """
        Create a new session in the database.

        Args:
            session_data (SessionData): The session data to create

        Returns:
            bool: True if successful
        """
        session = self.Session()
        try:
            model = SessionModel(
                session_id=session_data.session_id,
                session_name=session_data.session_name,
                task=session_data.task,
                create_time=session_data.create_time or datetime.now(),
                update_time=session_data.update_time or datetime.now(),
                processed_msg_id=session_data.processed_msg_id
            )
            session.add(model)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update(self, session_data: SessionData) -> bool:
        """
        Update an existing session in the database.

        Args:
            session_data (SessionData): The session data to update

        Returns:
            bool: True if successful
        """
        session = self.Session()
        try:
            model = session.query(SessionModel).filter_by(session_id=session_data.session_id).first()
            if model:
                model.session_name = session_data.session_name
                model.task = session_data.task
                model.update_time = datetime.now()
                model.processed_msg_id = session_data.processed_msg_id
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete(self, session_id: str) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id (str): The session ID to delete

        Returns:
            bool: True if successful
        """
        session = self.Session()
        try:
            model = session.query(SessionModel).filter_by(session_id=session_id).first()
            if model:
                session.delete(model)
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, session_id: str) -> SessionData:
        """
        Get a session by ID from the database.

        Args:
            session_id (str): The session ID to retrieve

        Returns:
            SessionData: The session data, or None if not found
        """
        session = self.Session()
        try:
            model = session.query(SessionModel).filter_by(session_id=session_id).first()
            if model:
                return SessionData(
                    session_id=model.session_id,
                    session_name=model.session_name,
                    task=model.task,
                    create_time=model.create_time,
                    update_time=model.update_time,
                    processed_msg_id=model.processed_msg_id
                )
            return None
        finally:
            session.close()

    def get_all(self) -> List[SessionData]:
        """
        Retrieve all sessions from the database.

        Returns:
            List[SessionData]: List of all session data objects
        """
        session = self.Session()
        try:
            models = session.query(SessionModel).all()
            return [
                SessionData(
                    session_id=m.session_id,
                    session_name=m.session_name,
                    task=m.task,
                    create_time=m.create_time,
                    update_time=m.update_time,
                    processed_msg_id=m.processed_msg_id
                )
                for m in models
            ]
        finally:
            session.close()

    def get_sessions_before(self, before_time) -> List[SessionData]:
        """
        Get sessions updated before the specified time.

        Args:
            before_time: The cutoff datetime

        Returns:
            List[SessionData]: List of sessions
        """
        session = self.Session()
        try:
            models = session.query(SessionModel).filter(SessionModel.update_time < before_time).all()
            return [
                SessionData(
                    session_id=m.session_id,
                    session_name=m.session_name,
                    task=m.task,
                    create_time=m.create_time,
                    update_time=m.update_time,
                    processed_msg_id=m.processed_msg_id
                )
                for m in models
            ]
        finally:
            session.close()

    def get_sessions_older_than(self, cutoff_date) -> List[SessionData]:
        """
        Get sessions with update_time older than the cutoff date.

        Args:
            cutoff_date: The cutoff datetime

        Returns:
            List[SessionData]: List of old sessions
        """
        session = self.Session()
        try:
            models = session.query(SessionModel).filter(SessionModel.update_time < cutoff_date).all()
            return [
                SessionData(
                    session_id=m.session_id,
                    session_name=m.session_name,
                    task=m.task,
                    create_time=m.create_time,
                    update_time=m.update_time,
                    processed_msg_id=m.processed_msg_id
                )
                for m in models
            ]
        finally:
            session.close()

    def update_processed_msg_id(self, session_id: str, processed_msg_id: str) -> bool:
        """
        Update the processed_msg_id for a session.

        Args:
            session_id (str): The session ID
            processed_msg_id (str): The processed message ID

        Returns:
            bool: True if successful
        """
        session = self.Session()
        try:
            model = session.query(SessionModel).filter_by(session_id=session_id).first()
            if model:
                model.processed_msg_id = processed_msg_id
                model.update_time = datetime.now()
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_or_create(self, session_id: str, session_name: str = None, task: str = None) -> SessionData:
        """
        Get an existing session or create a new one.

        Args:
            session_id (str): The session ID
            session_name (str): Optional session name
            task (str): Optional task

        Returns:
            SessionData: The session data
        """
        existing = self.get(session_id)
        if existing:
            return existing

        session_data = SessionData(
            session_id=session_id,
            session_name=session_name,
            task=task,
            create_time=datetime.now(),
            update_time=datetime.now()
        )
        self.create(session_data)
        return session_data

    def list_sessions(
        self,
        session_ids: Optional[list[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sort_key: str = "create_time",
        order_by: str = "desc",
        offset: int = 0,
        limit: int = 1000
    ) -> list[SessionData]:
        """
        Retrieve sessions with optional filtering, sorting, and pagination.

        This method supports querying sessions by a list of session IDs,
        filtering by creation time range, and pagination. It is used by
        cron jobs such as session_cleaner and by API endpoints.

        Args:
            session_ids (list[str], optional): Filter by specific session IDs.
                                               If None, queries all sessions.
            start_time (datetime, optional): Filter sessions created after this time.
            end_time (datetime, optional): Filter sessions created before this time.
            sort_key (str): Field to sort by, default is create_time.
            order_by (str): Sort order, 'asc' or 'desc', default is desc.
            offset (int): Number of records to skip.
            limit (int): Maximum number of records to return.

        Returns:
            list[SessionData]: List of session data objects matching the criteria.
        """
        session = self.Session()
        try:
            query = session.query(SessionModel)

            if session_ids is not None:
                query = query.filter(SessionModel.session_id.in_(session_ids))

            if start_time is not None:
                query = query.filter(SessionModel.create_time >= start_time)

            if end_time is not None:
                query = query.filter(SessionModel.create_time <= end_time)

            sort_column = getattr(SessionModel, sort_key, SessionModel.create_time)
            if order_by == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

            query = query.offset(offset).limit(limit)
            models = query.all()

            return [
                SessionData(
                    session_id=m.session_id,
                    session_name=m.session_name,
                    task=m.task,
                    create_time=m.create_time,
                    update_time=m.update_time,
                    processed_msg_id=m.processed_msg_id
                )
                for m in models
            ]
        finally:
            session.close()
