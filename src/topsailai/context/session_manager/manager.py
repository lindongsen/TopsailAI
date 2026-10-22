"""Session management through explicit composition (author: DawsonLin)."""

from topsailai.context.session_manager.__base import SessionStorageBase, SessionData
from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData
from topsailai.context.session_cleanup import HistoryCleanupManager, SessionCleanupManager
from topsailai.context.session_manager.base import SessionManager


class DefaultSessionManager(SessionManager):
    """Compose pure storage and conservative cleanup without dynamic forwarding."""

    def __init__(self, storage: SessionStorageBase, activity_probe):
        """Bind storage and the boundary-resolved activity probe."""
        self.storage = storage
        self.cleanup = SessionCleanupManager(storage, activity_probe)
        self._chat_history = HistoryCleanupManager(storage.chat_history, activity_probe)

    @property
    def chat_history(self) -> HistoryCleanupManager:
        """Expose ordinary history operations and protected retention."""
        return self._chat_history

    def exists_session(self, session_id: str) -> bool:
        """Check whether the session exists."""
        return self.storage.exists_session(session_id)

    def get_session(self, session_id: str) -> SessionData | None:
        """Retrieve one session."""
        return self.storage.get_session(session_id)

    def create_session(self, session_data: SessionData) -> bool:
        """Create a session and apply protected soft retention."""
        created = self.storage.create_session(session_data)
        if created:
            self.cleanup.evict_sessions(session_data.session_id)
        return created

    def list_sessions(self, sessions: list[str] | None = None, order_by: str | None = None,
                      offset: int = 0, limit: int | None = None) -> list[SessionData]:
        """List sessions with existing filters and ordering."""
        return self.storage.list_sessions(sessions=sessions, order_by=order_by,
                                          offset=offset, limit=limit)

    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """Update the stored session name."""
        return self.storage.update_session_name(session_id, session_name)

    def retrieve_messages(self, session_id: str) -> list[dict]:
        """Retrieve session message dictionaries."""
        return self.storage.retrieve_messages(session_id)

    def get_messages_by_session(self, session_id: str) -> list[ChatHistoryMessageData]:
        """Retrieve stored session message records."""
        return self.storage.get_messages_by_session(session_id)

    def accumulate_session_tokens(self, session_id: str, current_tokens: int, current_cached_tokens: int,
                                  current_completion_tokens: int = 0) -> bool:
        """Accumulate request token deltas."""
        return self.storage.accumulate_session_tokens(
            session_id, current_tokens, current_cached_tokens, current_completion_tokens)

    def get_session_token_totals(self, session_id: str) -> tuple[int, int] | None:
        """Retrieve legacy prompt and cache totals."""
        return self.storage.get_session_token_totals(session_id)

    def get_session_token_usage(self, session_id: str) -> dict[str, int] | None:
        """Retrieve explicit token usage totals."""
        return self.storage.get_session_token_usage(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete only after stopped ownership is reverified."""
        return self.cleanup.delete_session(session_id)

    def clean_sessions(self, before_seconds: int) -> int:
        """Clean old sessions while preserving protected owners."""
        return self.cleanup.clean_sessions(before_seconds)
