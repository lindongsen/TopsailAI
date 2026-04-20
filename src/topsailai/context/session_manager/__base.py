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
    its unique identifier and associated task. Additional metadata like
    session name and creation time can be stored as attributes.
    """
    def __init__(self, session_id: str, task: str):
        """
        Initialize a SessionData instance.

        Args:
            session_id (str): Unique identifier for the session
            task (str): The task or purpose associated with this session

        Note:
            Additional attributes like session_name and create_time are
            initialized to None and can be set later.
        """
        self.session_id = session_id
        self.task = task

        # other attributes that can be set later
        self.session_name = None
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

    def list_sessions(self) -> list[SessionData]:
        """
        Retrieve all stored sessions.

        This method returns a list of all sessions currently persisted in
        the storage backend, ordered by creation time (most recent first).

        Returns:
            list[SessionData]: A list of all stored SessionData instances.
                Returns an empty list if no sessions exist.

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
