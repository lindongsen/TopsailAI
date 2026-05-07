'''
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: SQLAlchemy implementation for API key management in agent_daemon.
'''

from datetime import datetime
from typing import Optional, List

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Index
from sqlalchemy.orm import Session as DBSession, declarative_base

from topsailai_server.agent_daemon.storage.api_key_manager.base import (
    ApiKeyData,
    ApiKeySessionData,
    RateLimitLogData,
    ApiKeyStorageBase
)
from topsailai_server.agent_daemon import logger

Base = declarative_base()


class ApiKey(Base):
    """SQLAlchemy model for api_key table."""

    __tablename__ = 'api_key'

    api_key_id = Column(String(32), primary_key=True)
    api_key = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default='user')
    rate_limit = Column(Integer, nullable=False, default=60)
    is_active = Column(Boolean, nullable=False, default=True)
    create_time = Column(DateTime, default=datetime.now)
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('ix_api_key_api_key', 'api_key'),
        Index('ix_api_key_role', 'role'),
    )

    def to_data(self) -> ApiKeyData:
        """Convert SQLAlchemy model to ApiKeyData."""
        return ApiKeyData(
            api_key_id=self.api_key_id,
            api_key=self.api_key,
            name=self.name,
            role=self.role,
            rate_limit=self.rate_limit,
            is_active=self.is_active,
            create_time=self.create_time,
            update_time=self.update_time
        )

    @classmethod
    def from_data(cls, data: ApiKeyData) -> 'ApiKey':
        """Create SQLAlchemy model from ApiKeyData."""
        return cls(
            api_key_id=data.api_key_id,
            api_key=data.api_key,
            name=data.name,
            role=data.role,
            rate_limit=data.rate_limit,
            is_active=data.is_active,
            create_time=data.create_time,
            update_time=data.update_time
        )


class ApiKeySession(Base):
    """SQLAlchemy model for api_key_session table."""

    __tablename__ = 'api_key_session'

    api_key_id = Column(String(32), primary_key=True)
    session_id = Column(String(32), primary_key=True)
    create_time = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('ix_api_key_session_session_id', 'session_id'),
    )

    def to_data(self) -> ApiKeySessionData:
        """Convert SQLAlchemy model to ApiKeySessionData."""
        return ApiKeySessionData(
            api_key_id=self.api_key_id,
            session_id=self.session_id,
            create_time=self.create_time
        )

    @classmethod
    def from_data(cls, data: ApiKeySessionData) -> 'ApiKeySession':
        """Create SQLAlchemy model from ApiKeySessionData."""
        return cls(
            api_key_id=data.api_key_id,
            session_id=data.session_id,
            create_time=data.create_time
        )


class RateLimitLog(Base):
    """SQLAlchemy model for rate_limit_log table."""

    __tablename__ = 'rate_limit_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(String(32), nullable=False)
    session_id = Column(String(32), nullable=False)
    action = Column(String(32), nullable=False)
    create_time = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('ix_rate_limit_log_api_key_id', 'api_key_id'),
        Index('ix_rate_limit_log_create_time', 'create_time'),
    )

    def to_data(self) -> RateLimitLogData:
        """Convert SQLAlchemy model to RateLimitLogData."""
        return RateLimitLogData(
            log_id=self.id,
            api_key_id=self.api_key_id,
            session_id=self.session_id,
            action=self.action,
            create_time=self.create_time
        )

    @classmethod
    def from_data(cls, data: RateLimitLogData) -> 'RateLimitLog':
        """Create SQLAlchemy model from RateLimitLogData."""
        return cls(
            id=data.log_id,
            api_key_id=data.api_key_id,
            session_id=data.session_id,
            action=data.action,
            create_time=data.create_time
        )


class ApiKeySQLAlchemy(ApiKeyStorageBase):
    """
    SQLAlchemy implementation of API key storage.

    This class provides concrete implementations for all API key storage
    operations using SQLAlchemy ORM.
    """

    def __init__(self, engine):
        """
        Initialize the SQLAlchemy storage backend.

        Args:
            engine: SQLAlchemy engine instance.
        """
        super().__init__()
        self.engine = engine
        Base.metadata.create_all(engine)

    def create_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Create a new API key."""
        try:
            with DBSession(self.engine) as session:
                model = ApiKey.from_data(api_key_data)
                session.add(model)
                session.commit()
                logger.info("Created API key: %s", api_key_data.api_key_id)
                return True
        except Exception as e:
            logger.exception("Failed to create API key: %s", e)
            return False

    def get_api_key_by_value(self, api_key: str) -> Optional[ApiKeyData]:
        """Get an API key by its key value."""
        try:
            with DBSession(self.engine) as session:
                model = session.query(ApiKey).filter(
                    ApiKey.api_key == api_key,
                    ApiKey.is_active == True
                ).first()
                if model:
                    return model.to_data()
                return None
        except Exception as e:
            logger.exception("Failed to get API key by value: %s", e)
            return None

    def get_api_key_by_id(self, api_key_id: str) -> Optional[ApiKeyData]:
        """Get an API key by its ID."""
        try:
            with DBSession(self.engine) as session:
                model = session.query(ApiKey).filter(
                    ApiKey.api_key_id == api_key_id
                ).first()
                if model:
                    return model.to_data()
                return None
        except Exception as e:
            logger.exception("Failed to get API key by id: %s", e)
            return None

    def list_api_keys(self) -> List[ApiKeyData]:
        """List all API keys."""
        try:
            with DBSession(self.engine) as session:
                models = session.query(ApiKey).order_by(ApiKey.create_time.desc()).all()
                return [m.to_data() for m in models]
        except Exception as e:
            logger.exception("Failed to list API keys: %s", e)
            return []

    def delete_api_key(self, api_key_id: str) -> bool:
        """Delete an API key and its session bindings."""
        try:
            with DBSession(self.engine) as session:
                # Delete session bindings first
                session.query(ApiKeySession).filter(
                    ApiKeySession.api_key_id == api_key_id
                ).delete()
                # Delete rate limit logs
                session.query(RateLimitLog).filter(
                    RateLimitLog.api_key_id == api_key_id
                ).delete()
                # Delete the API key
                result = session.query(ApiKey).filter(
                    ApiKey.api_key_id == api_key_id
                ).delete()
                session.commit()
                logger.info("Deleted API key: %s, rows: %d", api_key_id, result)
                return result > 0
        except Exception as e:
            logger.exception("Failed to delete API key: %s", e)
            return False

    def update_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Update an existing API key."""
        try:
            with DBSession(self.engine) as session:
                model = session.query(ApiKey).filter(
                    ApiKey.api_key_id == api_key_data.api_key_id
                ).first()
                if not model:
                    return False
                model.name = api_key_data.name
                model.role = api_key_data.role
                model.rate_limit = api_key_data.rate_limit
                model.is_active = api_key_data.is_active
                model.update_time = datetime.now()
                session.commit()
                logger.info("Updated API key: %s", api_key_data.api_key_id)
                return True
        except Exception as e:
            logger.exception("Failed to update API key: %s", e)
            return False

    def count_api_keys(self) -> int:
        """Count the total number of API keys."""
        try:
            with DBSession(self.engine) as session:
                return session.query(ApiKey).count()
        except Exception as e:
            logger.exception("Failed to count API keys: %s", e)
            return 0

    def bind_sessions(self, api_key_id: str, session_ids: List[str]) -> bool:
        """Bind sessions to an API key."""
        try:
            with DBSession(self.engine) as session:
                for sid in session_ids:
                    existing = session.query(ApiKeySession).filter(
                        ApiKeySession.api_key_id == api_key_id,
                        ApiKeySession.session_id == sid
                    ).first()
                    if not existing:
                        binding = ApiKeySession(
                            api_key_id=api_key_id,
                            session_id=sid,
                            create_time=datetime.now()
                        )
                        session.add(binding)
                session.commit()
                logger.info("Bound %d sessions to API key: %s", len(session_ids), api_key_id)
                return True
        except Exception as e:
            logger.exception("Failed to bind sessions: %s", e)
            return False

    def unbind_sessions(self, api_key_id: str, session_ids: List[str]) -> bool:
        """Unbind sessions from an API key."""
        try:
            with DBSession(self.engine) as session:
                result = session.query(ApiKeySession).filter(
                    ApiKeySession.api_key_id == api_key_id,
                    ApiKeySession.session_id.in_(session_ids)
                ).delete(synchronize_session=False)
                session.commit()
                logger.info("Unbound %d sessions from API key: %s", result, api_key_id)
                return True
        except Exception as e:
            logger.exception("Failed to unbind sessions: %s", e)
            return False

    def get_bound_sessions(self, api_key_id: str) -> List[str]:
        """Get all session IDs bound to an API key."""
        try:
            with DBSession(self.engine) as session:
                results = session.query(ApiKeySession.session_id).filter(
                    ApiKeySession.api_key_id == api_key_id
                ).all()
                return [r[0] for r in results]
        except Exception as e:
            logger.exception("Failed to get bound sessions: %s", e)
            return []

    def is_session_bound(self, api_key_id: str, session_id: str) -> bool:
        """Check if a session is bound to an API key."""
        try:
            with DBSession(self.engine) as session:
                count = session.query(ApiKeySession).filter(
                    ApiKeySession.api_key_id == api_key_id,
                    ApiKeySession.session_id == session_id
                ).count()
                return count > 0
        except Exception as e:
            logger.exception("Failed to check session binding: %s", e)
            return False

    def log_rate_limit(self, api_key_id: str, session_id: str, action: str) -> bool:
        """Log a rate limit entry."""
        try:
            with DBSession(self.engine) as session:
                log_entry = RateLimitLog(
                    api_key_id=api_key_id,
                    session_id=session_id,
                    action=action,
                    create_time=datetime.now()
                )
                session.add(log_entry)
                session.commit()
                return True
        except Exception as e:
            logger.exception("Failed to log rate limit: %s", e)
            return False

    def count_rate_limit(self, api_key_id: str, action: str, since: datetime) -> int:
        """Count rate limit entries for an API key since a given time."""
        try:
            with DBSession(self.engine) as session:
                return session.query(RateLimitLog).filter(
                    RateLimitLog.api_key_id == api_key_id,
                    RateLimitLog.action == action,
                    RateLimitLog.create_time >= since
                ).count()
        except Exception as e:
            logger.exception("Failed to count rate limit: %s", e)
            return 0

    def clean_rate_limit_logs(self, before: datetime) -> int:
        """Delete rate limit logs older than the specified time."""
        try:
            with DBSession(self.engine) as session:
                result = session.query(RateLimitLog).filter(
                    RateLimitLog.create_time < before
                ).delete(synchronize_session=False)
                session.commit()
                logger.info("Cleaned %d rate limit logs", result)
                return result
        except Exception as e:
            logger.exception("Failed to clean rate limit logs: %s", e)
            return 0
