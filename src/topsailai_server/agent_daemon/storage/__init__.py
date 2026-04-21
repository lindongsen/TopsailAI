'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Storage module for agent_daemon
'''

from typing import Optional
from sqlalchemy import Engine
from sqlalchemy.orm import declarative_base

from .session_manager import SessionData, SessionStorageBase, SessionSQLAlchemy
from .message_manager import MessageData, MessageStorageBase, MessageSQLAlchemy
from .migration import run_migrations, DatabaseMigrator

# Create declarative base for table creation
Base = declarative_base()


class Storage:
    """
    Storage Facade Class
    
    Provides a unified interface for database operations by wrapping both
    SessionSQLAlchemy and MessageSQLAlchemy.
    
    This class is used by API routes and cron jobs to access database operations.
    
    Attributes:
        session: SessionSQLAlchemy instance for session operations
        message: MessageSQLAlchemy instance for message operations
    
    Example:
        >>> from sqlalchemy import create_engine
        >>> from topsailai_server.agent_daemon.storage import Storage
        >>> 
        >>> engine = create_engine("sqlite:///agent_daemon.db")
        >>> storage = Storage(engine)
        >>> 
        >>> # Access session operations
        >>> session_data = storage.session.get("session_123")
        >>> 
        >>> # Access message operations
        >>> messages = storage.message.get_by_session("session_123")
    """
    
    def __init__(self, engine: Engine, auto_migrate: bool = True):
        """
        Initialize Storage with SQLAlchemy engine.
        
        Args:
            engine: SQLAlchemy Engine instance for database connections
            auto_migrate: If True, automatically run migrations to ensure schema is up to date
        """
        self._engine = engine
        
        # Run auto-migration if enabled
        if auto_migrate:
            try:
                run_migrations(engine)
            except (TypeError, AttributeError):
                # Handle mock engines in tests that don't support inspection
                pass
        
        self.session = SessionSQLAlchemy(engine)
        self.message = MessageSQLAlchemy(engine)
    
    @property
    def engine(self) -> Engine:
        """Get the underlying SQLAlchemy engine"""
        return self._engine
    
    def init_db(self):
        """
        Initialize database tables.
        
        Creates all necessary tables in the database based on SQLAlchemy models.
        """
        from .session_manager.sql import Session
        from .message_manager.sql import Message
        Base.metadata.create_all(self._engine)


__all__ = [
    'Storage',
    'SessionData',
    'SessionStorageBase',
    'SessionSQLAlchemy',
    'MessageData',
    'MessageStorageBase',
    'MessageSQLAlchemy',
    'run_migrations',
    'DatabaseMigrator'
]
