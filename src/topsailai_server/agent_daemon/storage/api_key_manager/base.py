'''
  Author: km2
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Base module for API key management in agent_daemon.
'''

from datetime import datetime
from typing import Optional, List


class ApiKeyData(object):
    """
    Data container for a single API key.

    This class holds the essential information about an API key,
    including its unique identifier, key value, role, and rate limit.
    """

    def __init__(
        self,
        api_key_id: str,
        api_key: str,
        name: str,
        role: str = "user",
        rate_limit: int = 60,
        is_active: bool = True,
        create_time: Optional[datetime] = None,
        update_time: Optional[datetime] = None
    ):
        """
        Initialize an ApiKeyData instance.

        Args:
            api_key_id (str): Unique identifier for the API key.
            api_key (str): The actual key value.
            name (str): Human-readable name for the key.
            role (str): Role of the key ('admin' or 'user'), default is 'user'.
            rate_limit (int): Max messages per minute, 0 means unlimited, default is 60.
            is_active (bool): Whether the key is active, default is True.
            create_time (datetime): Creation timestamp.
            update_time (datetime): Last update timestamp.
        """
        self.api_key_id = api_key_id
        self.api_key = api_key
        self.name = name
        self.role = role
        self.rate_limit = rate_limit
        self.is_active = is_active
        self.create_time = create_time
        self.update_time = update_time


class ApiKeySessionData(object):
    """
    Data container for API key to session binding.

    This class represents a many-to-many relationship between
    API keys and sessions.
    """

    def __init__(
        self,
        api_key_id: str,
        session_id: str,
        create_time: Optional[datetime] = None
    ):
        """
        Initialize an ApiKeySessionData instance.

        Args:
            api_key_id (str): The API key identifier.
            session_id (str): The session identifier.
            create_time (datetime): Creation timestamp.
        """
        self.api_key_id = api_key_id
        self.session_id = session_id
        self.create_time = create_time


class RateLimitLogData(object):
    """
    Data container for rate limit log entry.

    This class tracks API key usage for QoS enforcement.
    """

    def __init__(
        self,
        api_key_id: str,
        session_id: str,
        action: str,
        create_time: Optional[datetime] = None,
        log_id: Optional[int] = None
    ):
        """
        Initialize a RateLimitLogData instance.

        Args:
            api_key_id (str): The API key identifier.
            session_id (str): The session being accessed.
            action (str): The action performed, e.g., 'receive_message'.
            create_time (datetime): Creation timestamp.
            log_id (int): Auto-increment log ID.
        """
        self.log_id = log_id
        self.api_key_id = api_key_id
        self.session_id = session_id
        self.action = action
        self.create_time = create_time


class ApiKeyStorageBase(object):
    """
    Abstract base class for API key storage implementations.

    This class defines the interface that all API key storage backends
    must implement. It provides methods for managing API keys,
    session bindings, and rate limit logs.
    """

    tb_api_key = "api_key"
    tb_api_key_session = "api_key_session"
    tb_rate_limit_log = "rate_limit_log"

    def __init__(self):
        pass

    def create_api_key(self, api_key_data: ApiKeyData) -> bool:
        """
        Create a new API key.

        Args:
            api_key_data (ApiKeyData): The API key data to create.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def get_api_key_by_value(self, api_key: str) -> Optional[ApiKeyData]:
        """
        Get an API key by its key value.

        Args:
            api_key (str): The API key value.

        Returns:
            ApiKeyData: The API key data, or None if not found.
        """
        raise NotImplementedError

    def get_api_key_by_id(self, api_key_id: str) -> Optional[ApiKeyData]:
        """
        Get an API key by its ID.

        Args:
            api_key_id (str): The API key ID.

        Returns:
            ApiKeyData: The API key data, or None if not found.
        """
        raise NotImplementedError

    def list_api_keys(self) -> List[ApiKeyData]:
        """
        List all API keys.

        Returns:
            List[ApiKeyData]: List of all API keys.
        """
        raise NotImplementedError

    def delete_api_key(self, api_key_id: str) -> bool:
        """
        Delete an API key and its session bindings.

        Args:
            api_key_id (str): The API key ID to delete.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def update_api_key(self, api_key_data: ApiKeyData) -> bool:
        """
        Update an existing API key.

        Args:
            api_key_data (ApiKeyData): The API key data to update.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def count_api_keys(self) -> int:
        """
        Count the total number of API keys.

        Returns:
            int: Total count of API keys.
        """
        raise NotImplementedError

    def bind_sessions(self, api_key_id: str, session_ids: List[str]) -> bool:
        """
        Bind sessions to an API key.

        Args:
            api_key_id (str): The API key ID.
            session_ids (List[str]): List of session IDs to bind.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def unbind_sessions(self, api_key_id: str, session_ids: List[str]) -> bool:
        """
        Unbind sessions from an API key.

        Args:
            api_key_id (str): The API key ID.
            session_ids (List[str]): List of session IDs to unbind.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def get_bound_sessions(self, api_key_id: str) -> List[str]:
        """
        Get all session IDs bound to an API key.

        Args:
            api_key_id (str): The API key ID.

        Returns:
            List[str]: List of bound session IDs.
        """
        raise NotImplementedError

    def is_session_bound(self, api_key_id: str, session_id: str) -> bool:
        """
        Check if a session is bound to an API key.

        Args:
            api_key_id (str): The API key ID.
            session_id (str): The session ID.

        Returns:
            bool: True if the session is bound.
        """
        raise NotImplementedError

    def log_rate_limit(self, api_key_id: str, session_id: str, action: str) -> bool:
        """
        Log a rate limit entry.

        Args:
            api_key_id (str): The API key ID.
            session_id (str): The session ID.
            action (str): The action performed.

        Returns:
            bool: True if successful.
        """
        raise NotImplementedError

    def count_rate_limit(self, api_key_id: str, action: str, since: datetime) -> int:
        """
        Count rate limit entries for an API key since a given time.

        Args:
            api_key_id (str): The API key ID.
            action (str): The action to count.
            since (datetime): The cutoff time.

        Returns:
            int: Number of entries.
        """
        raise NotImplementedError

    def clean_rate_limit_logs(self, before: datetime) -> int:
        """
        Delete rate limit logs older than the specified time.

        Args:
            before (datetime): Delete logs created before this time.

        Returns:
            int: Number of logs deleted.
        """
        raise NotImplementedError
