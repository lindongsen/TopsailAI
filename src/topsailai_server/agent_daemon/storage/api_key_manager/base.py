"""Base classes for API key storage."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from topsailai_server.agent_daemon.storage.api_key_environ_manager.base import ApiKeyEnvironData


@dataclass
class ApiKeyData:
    """Data class representing an API key record."""
    api_key_id: str
    api_key: str
    name: str
    role: str = "user"
    rate_limit: int = 0
    is_active: bool = True
    create_time: datetime = field(default_factory=datetime.now)
    update_time: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "api_key_id": self.api_key_id,
            "api_key": self.api_key,
            "name": self.name,
            "role": self.role,
            "rate_limit": self.rate_limit,
            "is_active": self.is_active,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "update_time": self.update_time.isoformat() if self.update_time else None
        }


@dataclass
class ApiKeySessionData:
    """Data class representing an API key to session binding."""
    api_key_id: str
    session_id: str
    create_time: datetime = field(default_factory=datetime.now)


@dataclass
class RateLimitLogData:
    """Data class representing a rate limit log entry."""
    id: Optional[int] = None
    api_key_id: str = ""
    session_id: str = ""
    action: str = ""
    create_time: datetime = field(default_factory=datetime.now)


class ApiKeyStorageBase(ABC):
    """Abstract base class for API key storage operations."""

    @abstractmethod
    def create_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Create a new API key. Returns True on success, False on duplicate or error."""
        pass

    @abstractmethod
    def get_api_key_by_value(self, api_key: str) -> Optional[ApiKeyData]:
        """Get API key by its value."""
        pass

    @abstractmethod
    def get_api_key_by_id(self, api_key_id: str) -> Optional[ApiKeyData]:
        """Get API key by its ID."""
        pass

    @abstractmethod
    def list_api_keys(self) -> list:
        """List all API keys."""
        pass

    @abstractmethod
    def update_api_key(self, api_key_data: ApiKeyData) -> bool:
        """Update an existing API key. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def list_api_keys_with_sessions(self) -> list:
        """List all API keys with their bound session IDs.

        Returns:
            list: List of dicts, each containing:
                - "api_key": ApiKeyData instance
                - "session_ids": list of bound session ID strings
        """
        pass

    @abstractmethod
    def list_api_keys_with_details(self, offset: int = 0, limit: int = 1000, sort_key: str = "create_time", order_by: str = "desc") -> list:
        """List all API keys with their bound session IDs and environment variables.

        Args:
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            sort_key: Field to sort by, default is create_time.
            order_by: Sort order, 'asc' or 'desc', default is desc.

        Returns:
            list: List of dicts, each containing:
                - "api_key": ApiKeyData instance
                - "session_ids": list of bound session ID strings
                - "environs": list of ApiKeyEnvironData instances
        """
        pass

    @abstractmethod
    def get_api_key_with_details(self, api_key_id: str) -> Optional[dict]:
        """Get a single API key with its bound sessions and environs.

        Returns:
            dict: {
                "api_key": ApiKeyData,
                "session_ids": list[str],
                "environs": list[ApiKeyEnvironData]
            } or None if not found.
        """
        pass

    @abstractmethod
    def list_api_keys_by_session_id(self, session_id: str, offset: int = 0, limit: int = 1000, sort_key: str = "create_time", order_by: str = "desc") -> list:
        """List all API keys bound to a specific session.

        Args:
            session_id: The session ID to filter by.
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            sort_key: Field to sort by, default is create_time.
            order_by: Sort order, 'asc' or 'desc', default is desc.

        Returns:
            list: Same format as list_api_keys_with_details().
        """
        pass
    @abstractmethod
    def delete_api_key(self, api_key_id: str) -> bool:
        """Delete an API key and its related data. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def count_api_keys(self) -> int:
        """Count the total number of API keys."""
        pass

    @abstractmethod
    def count_admin_api_keys(self) -> int:
        """Count the number of admin API keys."""
        pass

    @abstractmethod
    def bind_session(self, binding: ApiKeySessionData) -> None:
        """Bind a session to an API key."""
        pass

    @abstractmethod
    def bind_sessions(self, api_key_id: str, session_ids: list) -> bool:
        """Bind multiple sessions to an API key. Returns True on success."""
        pass

    @abstractmethod
    def unbind_session(self, api_key_id: str, session_id: str) -> None:
        """Unbind a session from an API key."""
        pass

    @abstractmethod
    def unbind_sessions(self, api_key_id: str, session_ids: list) -> bool:
        """Unbind multiple sessions from an API key. Returns True on success."""
        pass

    @abstractmethod
    def is_session_bound(self, api_key_id: str, session_id: str) -> bool:
        """Check if a session is bound to an API key."""
        pass

    @abstractmethod
    def get_bound_sessions(self, api_key_id: str) -> list:
        """Get all sessions bound to an API key."""
        pass

    @abstractmethod
    def log_rate_limit(self, *args) -> bool:
        """Log a rate limit entry. Accepts either (RateLimitLogData) or (api_key_id, session_id, action). Returns True on success."""
        pass

    @abstractmethod
    def count_rate_limit(self, api_key_id: str, action: str, since: datetime) -> int:
        """Count rate limit entries for an API key since a given time."""
        pass

    @abstractmethod
    def clean_rate_limit_logs(self, before: datetime) -> int:
        """Clean rate limit logs older than the given time. Returns number of records deleted."""
        pass

    # API Key Environ methods

    @abstractmethod
    def create_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Create an environment variable for an API key. Returns True on success."""
        pass

    @abstractmethod
    def update_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Update an environment variable for an API key. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def delete_api_key_environ(self, api_key_id: str, key: str) -> bool:
        """Delete an environment variable for an API key. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def get_api_key_environs_by_api_key_id(self, api_key_id: str) -> list:
        """Get all environment variables for an API key."""
        pass

    @abstractmethod
    def get_api_key_environ_by_api_key_id_and_key(self, api_key_id: str, key: str) -> Optional[ApiKeyEnvironData]:
        """Get a specific environment variable for an API key by key name."""
        pass

    @abstractmethod
    def get_api_key_environs_by_session_id(self, session_id: str) -> list:
        """Get all environment variables for a session via its bound API key."""
        pass
