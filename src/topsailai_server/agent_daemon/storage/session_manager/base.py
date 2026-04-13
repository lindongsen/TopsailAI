"""
Base module for session management in AI engineering User Session.

This module defines the foundational classes and interfaces for managing
session data and storage operations within the AI engineering framework.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
"""

from __future__ import annotations
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from topsailai_server.agent_daemon.storage.message_manager import MessageData


class SessionData(object):
    """
    Data container for a single session in the AI engineering framework.

    This class holds the essential information about a session, including
    its unique identifier and associated task. Additional metadata like
    session name and creation time can be stored as attributes.
    """
    def __init__(self, session_id: str, task: str, session_name: str = None, 
                 create_time=None, update_time=None, processed_msg_id: str = None):
        """
        Initialize a SessionData instance.

        Args:
            session_id (str): Unique identifier for the session
            task (str): The task or purpose associated with this session
            session_name (str): Optional name for the session
            create_time: Creation timestamp
            update_time: Update timestamp
            processed_msg_id (str): ID of the last processed message
        """
        self.session_id = session_id
        self.task = task
        self.session_name = session_name
        self.create_time = create_time
        self.update_time = update_time
        self.processed_msg_id = processed_msg_id


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
        # message_manager
        self.message_manager = None

    def exists_session(self, session_id) -> bool:
        """ True for existing """
        raise NotImplementedError

    def create(self, session_data: SessionData) -> bool:
        """
        Create a new session.

        Args:
            session_data (SessionData): The session data to be created and stored

        Returns:
            bool: True if successful

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def update(self, session_data: SessionData) -> bool:
        """
        Update an existing session.

        Args:
            session_data (SessionData): The session data to update

        Returns:
            bool: True if successful

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def delete(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id (str): The session id to delete.

        Returns:
            bool: True if successful

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def get(self, session_id: str) -> SessionData:
        """
        Get a session by ID.

        Args:
            session_id (str): The session ID to retrieve

        Returns:
            SessionData: The session data, or None if not found
        """
        raise NotImplementedError

    def get_all(self) -> List[SessionData]:
        """
        Retrieve all stored sessions.

        Returns:
            List[SessionData]: A list of all stored SessionData instances.
                Returns an empty list if no sessions exist.
        """
        raise NotImplementedError

    def get_sessions_before(self, before_time) -> List[SessionData]:
        """
        Get sessions updated before the specified time.

        Args:
            before_time: The cutoff datetime

        Returns:
            List[SessionData]: List of sessions
        """
        raise NotImplementedError

    def get_sessions_older_than(self, cutoff_date) -> List[SessionData]:
        """
        Get sessions with update_time older than the cutoff date.

        Args:
            cutoff_date: The cutoff datetime

        Returns:
            List[SessionData]: List of old sessions
        """
        raise NotImplementedError

    def update_processed_msg_id(self, session_id: str, processed_msg_id: str) -> bool:
        """
        Update the processed_msg_id for a session.

        Args:
            session_id (str): The session ID
            processed_msg_id (str): The processed message ID

        Returns:
            bool: True if successful
        """
        raise NotImplementedError

    def get_or_create(self, session_id: str, session_name: str = None, task: str = None) -> SessionData:
        """
        Get an existing session or create a new one.

        Args:
            session_id (str): The session ID
            session_name (str): Optional session name
            task (str): Optional task

        Returns:
            SessionData: The session data
        """
        raise NotImplementedError