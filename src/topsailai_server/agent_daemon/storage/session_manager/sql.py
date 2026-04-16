'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: SQLAlchemy implementation for Session storage
'''

from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy import Column, String, Text, DateTime, Index, inspect
from sqlalchemy.orm import Session as SQLSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import asc, desc

from .base import SessionStorageBase
from .base import SessionData

Base = declarative_base()


class Session(Base, SessionStorageBase):
    """SQLAlchemy Session model"""
    __tablename__ = SessionStorageBase.tb_session

    session_id = Column(String(32), primary_key=True)
    session_name = Column(String(255), nullable=True)
    task = Column(Text, nullable=True)
    create_time = Column(DateTime, nullable=False, default=datetime.now)
    update_time = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    processed_msg_id = Column(String(32), nullable=True, index=True)

    # Composite index for cleanup queries (get_sessions_older_than)
    __table_args__ = (
        Index('idx_session_update_create_time', 'update_time', 'create_time'),
    )

    def __init__(self, **kwargs):
        # Extract engine if provided (for SQLAlchemy initialization)
        engine = kwargs.pop('engine', None)
        # Call SQLAlchemy's declarative base __init__
        super().__init__(**kwargs)
        if engine:
            self.engine = engine

    def get_engine(self):
        """Get the SQLAlchemy engine"""
        return getattr(self, 'engine', None)


class SessionSQLAlchemy(SessionStorageBase):
    """SQLAlchemy implementation of Session storage"""

    def __init__(self, engine):
        self.engine = engine
        Base.metadata.create_all(engine)

    @staticmethod
    def _to_data(session: Session) -> SessionData:
        """Convert SQLAlchemy model to SessionData"""
        return SessionData(
            session_id=session.session_id,
            session_name=session.session_name,
            task=session.task,
            create_time=session.create_time,
            update_time=session.update_time,
            processed_msg_id=session.processed_msg_id
        )

    def create(self, session_data: SessionData) -> bool:
        """Create a new session"""
        with SQLSession(self.engine) as db:
            session = Session(
                session_id=session_data.session_id,
                session_name=session_data.session_name,
                task=session_data.task,
                create_time=session_data.create_time,
                update_time=session_data.update_time,
                processed_msg_id=session_data.processed_msg_id
            )
            db.add(session)
            db.commit()
        return True

    def update(self, session_data: SessionData) -> bool:
        """Update an existing session"""
        with SQLSession(self.engine) as db:
            session = db.query(Session).filter(
                Session.session_id == session_data.session_id
            ).first()
            if session:
                session.session_name = session_data.session_name
                session.task = session_data.task
                session.update_time = datetime.now()
                session.processed_msg_id = session_data.processed_msg_id
                db.commit()
                return True
            return False

    def delete(self, session_id: str) -> bool:
        """Delete a session"""
        with SQLSession(self.engine) as db:
            session = db.query(Session).filter(
                Session.session_id == session_id
            ).first()
            if session:
                db.delete(session)
                db.commit()
                return True
            return False

    def get(self, session_id: str) -> Optional[SessionData]:
        """Get a session by ID"""
        with SQLSession(self.engine) as db:
            session = db.query(Session).filter(
                Session.session_id == session_id
            ).first()
            if session:
                return self._to_data(session)
            return None

    def get_all(self) -> List[SessionData]:
        """Get all sessions"""
        with SQLSession(self.engine) as db:
            sessions = db.query(Session).all()
            return [self._to_data(s) for s in sessions]

    def get_sessions_before(self, before_time: datetime) -> List[SessionData]:
        """Get sessions updated before the specified time"""
        with SQLSession(self.engine) as db:
            sessions = db.query(Session).filter(
                Session.update_time < before_time
            ).all()
            return [self._to_data(s) for s in sessions]

    def get_sessions_older_than(self, cutoff_date: datetime) -> List[SessionData]:
        """Get sessions with update_time older than the cutoff date"""
        with SQLSession(self.engine) as db:
            sessions = db.query(Session).filter(
                Session.update_time < cutoff_date
            ).all()
            return [self._to_data(s) for s in sessions]

    def update_processed_msg_id(self, session_id: str, processed_msg_id: str) -> bool:
        """Update the processed_msg_id for a session"""
        with SQLSession(self.engine) as db:
            session = db.query(Session).filter(
                Session.session_id == session_id
            ).first()
            if session:
                session.processed_msg_id = processed_msg_id
                session.update_time = datetime.now()
                db.commit()
                return True
            return False

    def get_or_create(self, session_id: str, session_name: str = None, task: str = None) -> SessionData:
        """Get an existing session or create a new one"""
        with SQLSession(self.engine) as db:
            session = db.query(Session).filter(
                Session.session_id == session_id
            ).first()

            if session:
                return self._to_data(session)

            # Create new session
            now = datetime.now()
            new_session = Session(
                session_id=session_id,
                session_name=session_name,
                task=task,
                create_time=now,
                update_time=now,
                processed_msg_id=None
            )
            db.add(new_session)
            db.commit()

            return SessionData(
                session_id=session_id,
                session_name=session_name,
                task=task,
                create_time=now,
                update_time=now,
                processed_msg_id=None
            )

    def get_engine(self):
        """Get the SQLAlchemy engine"""
        return self.engine

    def verify_indexes(self) -> Dict[str, bool]:
        """Verify that all required indexes exist on the session table.

        Returns:
            Dict mapping index names to their existence status.
        """
        inspector = inspect(self.engine)
        indexes = inspector.get_indexes(SessionStorageBase.tb_session)
        index_names = {idx['name'] for idx in indexes}

        required_indexes = {
            'idx_session_update_create_time': 'Composite index for cleanup queries',
            'ix_session_processed_msg_id': 'Index on processed_msg_id column'
        }

        result = {}
        for idx_name, description in required_indexes.items():
            exists = idx_name in index_names
            result[idx_name] = exists

        return result

    def list_sessions(
        self,
        session_ids: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_time",
        order_by: str = "desc"
    ) -> List[SessionData]:
        """
        Get sessions with filtering, sorting, and pagination.

        Args:
            session_ids: Filter sessions by specific session IDs (optional)
            start_time: Filter sessions created after this time
            end_time: Filter sessions created before this time
            offset: Number of records to skip
            limit: Maximum number of records to return
            sort_key: Field to sort by (create_time, update_time, session_id, session_name)
            order_by: Sort order - 'asc' or 'desc'

        Returns:
            List of SessionData objects
        """
        with SQLSession(self.engine) as db:
            query = db.query(Session)

            # Apply session_ids filter
            if session_ids:
                query = query.filter(Session.session_id.in_(session_ids))

            # Apply time filters
            if start_time:
                query = query.filter(Session.create_time >= start_time)
            if end_time:
                query = query.filter(Session.create_time <= end_time)

            # Apply sorting
            sort_column = getattr(Session, sort_key, Session.create_time)
            if order_by == "asc":
                query = query.order_by(asc(sort_column))
            else:
                query = query.order_by(desc(sort_column))

            # Apply pagination
            sessions = query.offset(offset).limit(limit).all()
            return [self._to_data(s) for s in sessions]
