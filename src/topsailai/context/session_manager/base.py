"""Public session management contract (author: DawsonLin)."""

from abc import ABC, abstractmethod

from topsailai.context.session_manager.__base import SessionData
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData
from topsailai.context.session_cleanup import HistoryCleanupManager


class SessionManager(ABC):
    """Separate session management capabilities from database storage."""

    @property
    @abstractmethod
    def chat_history(self) -> HistoryCleanupManager:
        """Expose history operations with protected age-based cleanup."""
        ...

    @abstractmethod
    def exists_session(self, session_id: str) -> bool:
        """Check whether the session exists."""
        ...

    @abstractmethod
    def get_session(self, session_id: str) -> SessionData | None:
        """Retrieve one session."""
        ...

    @abstractmethod
    def create_session(self, session_data: SessionData) -> bool:
        """Create a session and apply protected soft retention."""
        ...

    @abstractmethod
    def list_sessions(self, sessions: list[str] | None = None, order_by: str | None = None,
                      offset: int = 0, limit: int | None = None) -> list[SessionData]:
        """List sessions with existing filters and ordering."""
        ...

    @abstractmethod
    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """Update the stored session name."""
        ...

    @abstractmethod
    def retrieve_messages(self, session_id: str) -> list[dict]:
        """Retrieve session message dictionaries."""
        ...

    @abstractmethod
    def get_messages_by_session(self, session_id: str) -> list[ChatHistoryMessageData]:
        """Retrieve stored session message records."""
        ...

    @abstractmethod
    def accumulate_session_tokens(self, session_id: str, current_tokens: int, current_cached_tokens: int,
                                  current_completion_tokens: int = 0) -> bool:
        """Accumulate request token deltas."""
        ...

    @abstractmethod
    def get_session_token_totals(self, session_id: str) -> tuple[int, int] | None:
        """Retrieve legacy prompt and cache totals."""
        ...

    @abstractmethod
    def get_session_token_usage(self, session_id: str) -> dict[str, int] | None:
        """Retrieve explicit token usage totals."""
        ...

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """Delete only after stopped ownership is reverified."""
        ...

    @abstractmethod
    def clean_sessions(self, before_seconds: int) -> int:
        """Clean old sessions while preserving protected owners."""
        ...
