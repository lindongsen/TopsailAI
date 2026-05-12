"""Base classes for API key environment variable storage."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ApiKeyEnvironData:
    """Data class representing an API key environment variable record."""
    api_key_id: str
    key: str
    value: str
    create_time: datetime = field(default_factory=datetime.now)
    update_time: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "api_key_id": self.api_key_id,
            "key": self.key,
            "value": self.value,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "update_time": self.update_time.isoformat() if self.update_time else None
        }


class ApiKeyEnvironStorageBase(ABC):
    """Abstract base class for API key environment variable storage operations."""

    @abstractmethod
    def create_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Create an environment variable for an API key. Returns True on success."""
        pass

    @abstractmethod
    def get_api_key_environs_by_api_key_id(self, api_key_id: str) -> List[ApiKeyEnvironData]:
        """Get all environment variables for an API key."""
        pass

    @abstractmethod
    def get_api_key_environ_by_api_key_id_and_key(self, api_key_id: str, key: str) -> ApiKeyEnvironData:
        """Get a specific environment variable for an API key by key name."""
        pass

    @abstractmethod
    def get_api_key_environs_by_session_id(self, session_id: str) -> List[ApiKeyEnvironData]:
        """Get all environment variables for a session via its bound API key."""
        pass

    @abstractmethod
    def update_api_key_environ(self, api_key_id: str, key: str, value: str) -> bool:
        """Update an environment variable for an API key. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def delete_api_key_environ(self, api_key_id: str, key: str) -> bool:
        """Delete a single environment variable for an API key. Returns True on success, False if not found."""
        pass

    @abstractmethod
    def delete_api_key_environs_by_api_key_id(self, api_key_id: str) -> bool:
        """Delete all environment variables for an API key. Returns True on success."""
        pass
