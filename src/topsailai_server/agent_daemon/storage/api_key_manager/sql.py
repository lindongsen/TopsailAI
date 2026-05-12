"""SQLAlchemy implementation of API key storage."""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, create_engine, Index
from sqlalchemy.orm import sessionmaker, declarative_base, Session as SQLAlchemySession
from sqlalchemy.exc import IntegrityError
from topsailai_server.agent_daemon.storage.api_key_manager.base import (
    ApiKeyData,
    ApiKeySessionData,
    RateLimitLogData,
    ApiKeyStorageBase,
    ApiKeyEnvironData
)
Base = declarative_base()


class ApiKeyModel(Base):
    """SQLAlchemy model for api_key table."""
    __tablename__ = "api_key"

    api_key_id = Column(String(32), primary_key=True)
    api_key = Column(String(64), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(16), default="user", nullable=False)
    rate_limit = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    create_time = Column(DateTime, default=datetime.now)
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_api_key_api_key", "api_key"),
        Index("ix_api_key_role", "role"),
    )


class ApiKeySessionModel(Base):
    """SQLAlchemy model for api_key_session table."""
    __tablename__ = "api_key_session"

    api_key_id = Column(String(32), ForeignKey("api_key.api_key_id"), primary_key=True)
    session_id = Column(String(32), primary_key=True)
    create_time = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_api_key_session_session_id", "session_id"),
    )


class RateLimitLogModel(Base):
    """SQLAlchemy model for rate_limit_log table."""
    __tablename__ = "rate_limit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(String(32), ForeignKey("api_key.api_key_id"), nullable=False)
    session_id = Column(String(32), nullable=False)
    action = Column(String(32), nullable=False)
    create_time = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_rate_limit_log_api_key_id", "api_key_id"),
        Index("ix_rate_limit_log_create_time", "create_time"),
    )


class ApiKeySQLAlchemy(ApiKeyStorageBase):
    """SQLAlchemy implementation of API key storage."""

    def __init__(self, engine):
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        # Ensure all tables for this module are created
        Base.metadata.create_all(engine)

    def _to_data(self, model: ApiKeyModel) -> ApiKeyData:
        """Convert SQLAlchemy model to data class."""
        return ApiKeyData(
            api_key_id=model.api_key_id,
            api_key=model.api_key,
            name=model.name,
            role=model.role,
            rate_limit=model.rate_limit,
            is_active=model.is_active,
            create_time=model.create_time,
            update_time=model.update_time
        )

    def create_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Create a new API key. Returns True on success, False on duplicate or error."""
        with self.Session() as session:
            model = ApiKeyModel(
                api_key_id=api_key_data.api_key_id,
                api_key=api_key_data.api_key,
                name=api_key_data.name,
                role=api_key_data.role,
                rate_limit=api_key_data.rate_limit,
                is_active=api_key_data.is_active,
                create_time=api_key_data.create_time,
                update_time=api_key_data.update_time
            )
            session.add(model)
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def get_api_key_by_value(self, api_key: str) -> ApiKeyData:
        """Get API key by its value."""
        with self.Session() as session:
            model = session.query(ApiKeyModel).filter(
                ApiKeyModel.api_key == api_key,
                ApiKeyModel.is_active == True
            ).first()
            return self._to_data(model) if model else None

    def get_api_key_by_id(self, api_key_id: str) -> ApiKeyData:
        """Get API key by its ID."""
        with self.Session() as session:
            model = session.query(ApiKeyModel).filter(
                ApiKeyModel.api_key_id == api_key_id
            ).first()
            return self._to_data(model) if model else None

    def list_api_keys(self) -> list:
        """List all API keys."""
        with self.Session() as session:
            models = session.query(ApiKeyModel).order_by(ApiKeyModel.create_time.desc()).all()
            return [self._to_data(m) for m in models]

    def update_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Update an existing API key. Returns True on success, False if not found."""
        with self.Session() as session:
            model = session.query(ApiKeyModel).filter(
                ApiKeyModel.api_key_id == api_key_data.api_key_id
            ).first()
            if not model:
                return False
            model.name = api_key_data.name
            model.role = api_key_data.role
            model.rate_limit = api_key_data.rate_limit
            model.is_active = api_key_data.is_active
            model.update_time = api_key_data.update_time
            session.commit()
            return True


    def list_api_keys_with_sessions(self) -> list:
        """List all API keys with their bound session IDs.

        Returns:
            list: List of dicts, each containing:
                - "api_key": ApiKeyData instance
                - "session_ids": list of bound session ID strings
        """
        with self.Session() as session:
            api_keys = session.query(ApiKeyModel).order_by(
                ApiKeyModel.create_time.desc()
            ).all()
            result = []
            for key_model in api_keys:
                # Get bound sessions for this API key
                session_models = session.query(ApiKeySessionModel).filter(
                    ApiKeySessionModel.api_key_id == key_model.api_key_id
                ).all()
                session_ids = [m.session_id for m in session_models]
                result.append({
                    "api_key": self._to_data(key_model),
                    "session_ids": session_ids
                })
            return result

    def list_api_keys_with_details(self) -> list:
        """List all API keys with their bound session IDs and environment variables.

        Returns:
            list: List of dicts, each containing:
                - "api_key": ApiKeyData instance
                - "session_ids": list of bound session ID strings
                - "environs": list of ApiKeyEnvironData instances
        """
        with self.Session() as session:
            api_keys = session.query(ApiKeyModel).order_by(
                ApiKeyModel.create_time.desc()
            ).all()
            result = []
            for key_model in api_keys:
                # Get bound sessions for this API key
                session_models = session.query(ApiKeySessionModel).filter(
                    ApiKeySessionModel.api_key_id == key_model.api_key_id
                ).all()
                session_ids = [m.session_id for m in session_models]
                # Get environment variables for this API key
                environs = self.get_api_key_environs_by_api_key_id(key_model.api_key_id)
                result.append({
                    "api_key": self._to_data(key_model),
                    "session_ids": session_ids,
                    "environs": environs
                })
            return result

    def delete_api_key(self, api_key_id: str) -> bool:
        """Delete an API key and its related data. Returns True on success, False if not found."""
        with self.Session() as session:
            # Check if the key exists
            model = session.query(ApiKeyModel).filter(
                ApiKeyModel.api_key_id == api_key_id
            ).first()
            if not model:
                return False
            # Delete related rate limit logs
            session.query(RateLimitLogModel).filter(
                RateLimitLogModel.api_key_id == api_key_id
            ).delete(synchronize_session=False)
            # Delete related session bindings
            session.query(ApiKeySessionModel).filter(
                ApiKeySessionModel.api_key_id == api_key_id
            ).delete(synchronize_session=False)
            # Delete the API key
            session.query(ApiKeyModel).filter(
                ApiKeyModel.api_key_id == api_key_id
            ).delete(synchronize_session=False)
            session.commit()
            return True

    def count_api_keys(self) -> int:
        """Count the total number of API keys."""
        with self.Session() as session:
            return session.query(ApiKeyModel).count()

    def count_admin_api_keys(self) -> int:
        """Count the number of admin API keys."""
        with self.Session() as session:
            return session.query(ApiKeyModel).filter(
                ApiKeyModel.role == "admin",
                ApiKeyModel.is_active == True
            ).count()

    def bind_session(self, binding: ApiKeySessionData) -> None:
        """Bind a session to an API key."""
        with self.Session() as session:
            model = ApiKeySessionModel(
                api_key_id=binding.api_key_id,
                session_id=binding.session_id,
                create_time=binding.create_time
            )
            session.add(model)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()

    def bind_sessions(self, api_key_id: str, session_ids: list) -> bool:
        """Bind multiple sessions to an API key. Returns True on success."""
        with self.Session() as session:
            for session_id in session_ids:
                model = ApiKeySessionModel(
                    api_key_id=api_key_id,
                    session_id=session_id,
                    create_time=datetime.now()
                )
                session.add(model)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
            return True

    def unbind_session(self, api_key_id: str, session_id: str) -> None:
        """Unbind a session from an API key."""
        with self.Session() as session:
            session.query(ApiKeySessionModel).filter(
                ApiKeySessionModel.api_key_id == api_key_id,
                ApiKeySessionModel.session_id == session_id
            ).delete(synchronize_session=False)
            session.commit()

    def unbind_sessions(self, api_key_id: str, session_ids: list) -> bool:
        """Unbind multiple sessions from an API key. Returns True on success."""
        with self.Session() as session:
            session.query(ApiKeySessionModel).filter(
                ApiKeySessionModel.api_key_id == api_key_id,
                ApiKeySessionModel.session_id.in_(session_ids)
            ).delete(synchronize_session=False)
            session.commit()
            return True

    def is_session_bound(self, api_key_id: str, session_id: str) -> bool:
        """Check if a session is bound to an API key."""
        with self.Session() as session:
            return session.query(ApiKeySessionModel).filter(
                ApiKeySessionModel.api_key_id == api_key_id,
                ApiKeySessionModel.session_id == session_id
            ).first() is not None

    def get_bound_sessions(self, api_key_id: str) -> list:
        """Get all sessions bound to an API key."""
        with self.Session() as session:
            models = session.query(ApiKeySessionModel).filter(
                ApiKeySessionModel.api_key_id == api_key_id
            ).all()
            return [m.session_id for m in models]

    def log_rate_limit(self, *args) -> bool:
        """Log a rate limit entry.

        Accepts either (RateLimitLogData) or (api_key_id, session_id, action).
        Returns True on success.
        """
        if len(args) == 1 and isinstance(args[0], RateLimitLogData):
            log = args[0]
        elif len(args) == 3:
            log = RateLimitLogData(
                api_key_id=args[0],
                session_id=args[1],
                action=args[2],
                create_time=datetime.now()
            )
        else:
            raise TypeError(
                "log_rate_limit() accepts either (RateLimitLogData) or (api_key_id, session_id, action)"
            )
        with self.Session() as session:
            model = RateLimitLogModel(
                api_key_id=log.api_key_id,
                session_id=log.session_id,
                action=log.action,
                create_time=log.create_time
            )
            session.add(model)
            session.commit()
            return True

    def count_rate_limit(self, api_key_id: str, action: str, since: datetime) -> int:
        """Count rate limit entries for an API key since a given time."""
        with self.Session() as session:
            return session.query(RateLimitLogModel).filter(
                RateLimitLogModel.api_key_id == api_key_id,
                RateLimitLogModel.action == action,
                RateLimitLogModel.create_time >= since
            ).count()

    def clean_rate_limit_logs(self, before: datetime) -> int:
        """Clean rate limit logs older than the given time.

        Returns:
            int: Number of records deleted.
        """
        with self.Session() as session:
            deleted = session.query(RateLimitLogModel).filter(
                RateLimitLogModel.create_time < before
            ).delete(synchronize_session=False)
            session.commit()
            return deleted

    # API Key Environ methods - delegated to ApiKeyEnvironSQLAlchemy

    def create_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Create an environment variable for an API key. Returns True on success."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).create_api_key_environ(api_key_id, key, value)

    def update_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Update an environment variable for an API key. Returns True on success, False if not found."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).update_api_key_environ(api_key_id, key, value)

    def delete_api_key_environ(self, api_key_id: str, key: str) -> bool:
        """Delete an environment variable for an API key. Returns True on success, False if not found."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).delete_api_key_environ(api_key_id, key)

    def get_api_key_environs_by_api_key_id(self, api_key_id: str) -> list:
        """Get all environment variables for an API key."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).get_api_key_environs_by_api_key_id(api_key_id)

    def get_api_key_environs_by_session_id(self, session_id: str) -> list:
        """Get all environment variables for a session via its bound API key."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).get_api_key_environs_by_session_id(session_id)

    def get_api_key_environ_by_api_key_id_and_key(self, api_key_id: str, key: str) -> Optional[ApiKeyEnvironData]:
        """Get a specific environment variable for an API key by key name."""
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import ApiKeyEnvironSQLAlchemy
        return ApiKeyEnvironSQLAlchemy(self.engine).get_api_key_environ_by_api_key_id_and_key(api_key_id, key)
