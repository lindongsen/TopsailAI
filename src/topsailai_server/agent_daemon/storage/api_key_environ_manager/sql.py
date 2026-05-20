"""SQLAlchemy implementation for API key environment variable storage."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base

from topsailai_server.agent_daemon.storage.api_key_environ_manager.base import (
    ApiKeyEnvironData, ApiKeyEnvironStorageBase
)

Base = declarative_base()


class ApiKeyEnvironModel(Base):
    """SQLAlchemy model for api_key_environ table."""
    __tablename__ = "api_key_environ"

    api_key_id = Column(String(32), primary_key=True)
    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)
    create_time = Column(DateTime, default=datetime.now)
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ApiKeyEnvironSQLAlchemy(ApiKeyEnvironStorageBase):
    """SQLAlchemy implementation of API key environment variable storage."""

    def __init__(self, engine):
        """Initialize with a SQLAlchemy engine or database URL.

        Args:
            engine: SQLAlchemy Engine instance, or a database connection URL string.
        """
        if isinstance(engine, Engine):
            self.engine = engine
        else:
            self.engine = create_engine(engine)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def get_engine(self):
        """Return the SQLAlchemy engine instance."""
        return self.engine

    def create_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Create an environment variable for an API key. Returns True on success."""
        with self.Session() as session:
            existing = session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id, key=key
            ).first()
            if existing:
                existing.value = value
                existing.update_time = datetime.now()
            else:
                new_environ = ApiKeyEnvironModel(
                    api_key_id=api_key_id,
                    key=key,
                    value=value
                )
                session.add(new_environ)
            session.commit()
            return True

    def get_api_key_environs_by_api_key_id(self, api_key_id: str) -> List[ApiKeyEnvironData]:
        """Get all environment variables for an API key."""
        with self.Session() as session:
            records = session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id
            ).all()
            return [
                ApiKeyEnvironData(
                    api_key_id=r.api_key_id,
                    key=r.key,
                    value=r.value,
                    create_time=r.create_time,
                    update_time=r.update_time
                )
                for r in records
            ]

    def get_api_key_environ_by_api_key_id_and_key(self, api_key_id: str, key: str) -> Optional[ApiKeyEnvironData]:
        """Get a specific environment variable for an API key by key name."""
        with self.Session() as session:
            record = session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id, key=key
            ).first()
            if not record:
                return None
            return ApiKeyEnvironData(
                api_key_id=record.api_key_id,
                key=record.key,
                value=record.value,
                create_time=record.create_time,
                update_time=record.update_time
            )

    def get_api_key_environs_by_session_id(self, session_id: str) -> List[ApiKeyEnvironData]:
        """Get all environment variables for a session via its bound API key.

        Joins api_key_session with api_key_environ to find all environment
        variables associated with the API keys bound to the given session.
        """
        from topsailai_server.agent_daemon.storage.api_key_manager.sql import ApiKeySessionModel
        with self.Session() as session:
            records = session.query(ApiKeyEnvironModel).join(
                ApiKeySessionModel,
                ApiKeyEnvironModel.api_key_id == ApiKeySessionModel.api_key_id
            ).filter(ApiKeySessionModel.session_id == session_id).all()
            return [
                ApiKeyEnvironData(
                    api_key_id=r.api_key_id,
                    key=r.key,
                    value=r.value,
                    create_time=r.create_time,
                    update_time=r.update_time
                )
                for r in records
            ]

    def update_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Update an environment variable for an API key. Returns True on success, False if not found."""
        with self.Session() as session:
            record = session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id, key=key
            ).first()
            if not record:
                return False
            record.value = value
            record.update_time = datetime.now()
            session.commit()
            return True

    def delete_api_key_environ(self, api_key_id: str, key: str) -> bool:
        """Delete a single environment variable for an API key. Returns True on success, False if not found."""
        with self.Session() as session:
            record = session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id, key=key
            ).first()
            if not record:
                return False
            session.delete(record)
            session.commit()
            return True

    def delete_api_key_environs_by_api_key_id(self, api_key_id: str) -> bool:
        """Delete all environment variables for an API key. Returns True on success."""
        with self.Session() as session:
            session.query(ApiKeyEnvironModel).filter_by(
                api_key_id=api_key_id
            ).delete(synchronize_session=False)
            session.commit()
            return True
