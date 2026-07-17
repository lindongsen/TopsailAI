"""
Base module for session management in AI engineering context.

This module defines the foundational classes and interfaces for managing
session data and storage operations within the AI engineering framework.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
"""

from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
)

class SessionData(object):
    """
    Data container for a single session in the AI engineering framework.

    This class holds the essential information about a session, including
    its unique identifier, associated task, and runtime environment paths.
    Additional metadata like session name and creation time can be stored
    as attributes.
    """
    def __init__(
        self,
        session_id: str,
        task: str = "",
        session_name: str = None,
        project_workspace: str = None,
        pwd: str = None,
        topsailai_home: str = None,
    ):
        """
        Initialize a SessionData instance.

        Args:
            session_id (str): Unique identifier for the session
            task (str, optional): The task or purpose associated with this session.
                Defaults to an empty string.
            session_name (str, optional): Display name for the session
            project_workspace (str, optional): Project workspace path at session creation
            pwd (str, optional): Working directory at session creation
            topsailai_home (str, optional): TopsailAI home directory at session creation

        Note:
            Additional attributes like session_name and create_time are
            initialized to None and can be set later.
        """
        self.session_id = session_id
        self.task = task

        # other attributes that can be set later
        self.session_name = session_name
        self.project_workspace = project_workspace
        self.pwd = pwd
        self.topsailai_home = topsailai_home
        self.create_time = None

    def __str__(self):
        """Return string representation of SessionData."""
        return f"SessionData(session_id={self.session_id}, task={self.task})"

class SessionStorageBase(object):
    """
    Abstract base class for session storage implementations.

    This class defines the interface that all session storage backends
    must implement. It provides methods for creating new sessions and
    listing existing sessions. Concrete implementations should handle
    persistence, such as database or file-based storage.

    Attributes:
        tb_session (str): Name of the session table/collection in storage.
    """
    tb_session = "session"

    def __init__(self):

        # chat_history_manager
        self.chat_history = None

    def exists_session(self, session_id) -> bool:
        """ True for existing """
        raise NotImplementedError

    def create_session(self, session_data: SessionData):
        """
        Create a new session and maintain historical limit.

        This method persists a new session to the storage backend and ensures
        that only the most recent 100 sessions are retained. Older sessions
        beyond this limit should be automatically removed.

        Args:
            session_data (SessionData): The session data to be created and stored

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def list_sessions(
        self,
        sessions: list[str] = None,
        order_by: str = None,
        offset: int = 0,
        limit: int = None,
    ) -> list[SessionData]:
        """
        Retrieve stored sessions, optionally filtered, sorted, and paginated.

        Args:
            sessions (list[str], optional): A list of session IDs to include.
                When provided, only sessions whose ID is in this list are returned.
                When empty or None, all sessions are returned.
            order_by (str, optional): Field name to sort by. Supported fields include
                ``session_id``, ``session_name``, ``task``, and ``create_time``.
                Prefix the field name with ``-`` for descending order
                (e.g., ``-created_at``). When not provided, the default order is
                implementation-defined (typically ``create_time`` descending).
            offset (int, optional): Number of sessions to skip. Defaults to ``0``.
            limit (int, optional): Maximum number of sessions to return.
                If ``None``, all matching sessions are returned.

        Returns:
            list[SessionData]: A list of SessionData instances matching the query.
                Returns an empty list if no sessions match.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def delete_session(self, session_id: str):
        """
        Delete a session and its associated chat history.

        Args:
            session_id (str): The session id to delete.

        Raises:
            Exception: If the session does not exist or deletion fails.
        """
        raise NotImplementedError

    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """
        Update the name of an existing session.

        Args:
            session_id (str): The session id to update.
            session_name (str): The new session name.

        Returns:
            bool: True if the session name was updated successfully,
                  False if the session does not exist or the update failed.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError
    def accumulate_session_tokens(
        self,
        session_id: str,
        current_tokens: int,
        current_cached_tokens: int,
    ) -> bool:
        """
        Atomically add per-agent token deltas to the session totals.

        A single session may be processed by multiple agents, each owning its own
        TokenStat instance. Callers must therefore pass the *current-agent delta*
        (``current_tokens`` / ``current_cached_tokens``) rather than an agent-level
        total. Overwriting the session row with ``TokenStat.total_*`` would lose the
        contributions of other agents that share the same session.

        Args:
            session_id (str): The session identifier whose totals should be updated.
            current_tokens (int): Number of tokens produced by the current agent
                invocation to add to ``total_tokens``.
            current_cached_tokens (int): Number of cached tokens produced by the
                current agent invocation to add to ``total_cached_tokens``.

        Returns:
            bool: True if the session existed and was updated, False otherwise.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def get_session_token_totals(self, session_id: str) -> tuple[int, int] | None:
        """
        Retrieve the accumulated token totals for a session.

        Returns the ``total_tokens`` and ``total_cached_tokens`` values stored in
        session storage. These totals are accumulated from per-agent deltas via
        ``accumulate_session_tokens()`` and therefore reflect the combined token
        usage of all agents that have processed the session.

        Args:
            session_id (str): The session identifier whose totals should be read.

        Returns:
            tuple[int, int] | None: A tuple of ``(total_tokens, total_cached_tokens)``
                if the session exists, otherwise ``None``.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError



    def retrieve_messages(self, session_id:str) -> list[dict]:
        """ retrieve messages by chat_history_manager """
        raise NotImplementedError

    def clean_sessions(self, before_seconds: int):
        """
        Delete sessions that were created before the specified number of seconds ago.

        Args:
            before_seconds (int): Delete sessions older than this many seconds from current time.

        Returns:
            int: Number of sessions deleted.
        """
        raise NotImplementedError

    def get_messages_by_session(self, session_id:str) -> list[ChatHistoryMessageData]:
        """ get messages by chat_history_manager """
        raise NotImplementedError
