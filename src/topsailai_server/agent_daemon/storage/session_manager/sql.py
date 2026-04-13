'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: SQLAlchemy implementation for Session storage
'''

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, Text, DateTime, Index
from sqlalchemy.orm import Session as SQLSession
from sqlalchemy.orm import declarative_base

from .__base import SessionStorageBase
from .__base import SessionData

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
