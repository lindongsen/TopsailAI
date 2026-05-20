"""Storage module for agent_daemon.

This module provides the main Storage class that aggregates all storage managers.
"""

from topsailai_server.agent_daemon.storage.api_key_environ_manager import (
    ApiKeyEnvironData,
    ApiKeyEnvironSQLAlchemy,
    ApiKeyEnvironStorageBase,
)
from topsailai_server.agent_daemon.storage.api_key_manager import (
    ApiKeyData,
    ApiKeySQLAlchemy,
    ApiKeySessionData,
    ApiKeyStorageBase,
    RateLimitLogData,
)
from topsailai_server.agent_daemon.storage.message_manager import (
    MessageData,
    MessageSQLAlchemy,
    MessageStorageBase,
)
from topsailai_server.agent_daemon.storage.session_manager import (
    SessionData,
    SessionSQLAlchemy,
    SessionStorageBase,
)


class Storage:
    """Main storage class that aggregates all storage managers.

    This class provides a unified interface to all storage operations
    by composing individual storage managers for sessions, messages,
    API keys, and API key environment variables.

    Example:
        >>> storage = Storage(engine)
        >>> session = storage.session.create_session("test-session")
        >>> api_key = storage.api_key.create_api_key(api_key_data)
        >>> env_vars = storage.api_key_environ.get_by_api_key_id("ak_123")
    """

    def __init__(self, engine):
        """Initialize all storage managers.

        Args:
            engine: SQLAlchemy engine instance.
        """
        self.engine = engine
        self.session = SessionSQLAlchemy(engine)
        self.message = MessageSQLAlchemy(engine)
        self.api_key = ApiKeySQLAlchemy(engine)
        self.api_key_environ = ApiKeyEnvironSQLAlchemy(engine)

    def init_db(self):
        """Initialize all database tables.

        Ensures all tables for session, message, api_key, and related
        models are created. Safe to call multiple times (idempotent).
        """
        from topsailai_server.agent_daemon.storage.session_manager.sql import Base as SessionBase
        from topsailai_server.agent_daemon.storage.message_manager.sql import Base as MessageBase
        from topsailai_server.agent_daemon.storage.api_key_manager.sql import Base as ApiKeyBase
        from topsailai_server.agent_daemon.storage.api_key_environ_manager.sql import Base as ApiKeyEnvironBase

        SessionBase.metadata.create_all(self.engine)
        MessageBase.metadata.create_all(self.engine)
        ApiKeyBase.metadata.create_all(self.engine)
        ApiKeyEnvironBase.metadata.create_all(self.engine)
