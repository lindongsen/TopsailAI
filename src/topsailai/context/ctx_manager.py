'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose: Context management module for handling chat history and session management
'''

import os

from topsailai.logger import logger

from .chat_history_manager import ALL_MANAGERS
from .chat_history_manager.__base import (
    ChatHistoryBase,
)
from .session_manager.__base import (
    SessionStorageBase,
    SessionData,
)
from .session_manager.sql import SessionSQLAlchemy, DEFAULT_CONN


def get_managers_by_env(count=10) -> list[ChatHistoryBase]:
    """
    Get instances of chat history managers based on environment configuration.

    This function reads the CONTEXT_HISTORY_MANAGERS environment variable to
    instantiate chat history managers. The environment variable should contain
    manager specifications separated by semicolons.

    Args:
        count (int, optional): Maximum number of managers to instantiate.
                              Defaults to 10.

    Returns:
        list[ChatHistoryBase]: List of instantiated chat history manager objects,
                              or None if no valid configuration is found.

    Example environment variable format:
        "sql.ChatHistorySQLAlchemy conn=sqlite://memory.db;"
    """
    # Get manager configuration from environment variable
    env_ctx_history_managers = os.getenv("CONTEXT_HISTORY_MANAGERS")
    if not env_ctx_history_managers:
        return

    mgrs = []

    # Parse manager specifications from environment variable
    # Format: "manager_name param1=value1 param2=value2;"
    for mgr in env_ctx_history_managers.split(';'):
        mgr = mgr.strip()
        if not mgr:
            continue

        # Split manager name from parameters
        mgr_list = mgr.split(' ')
        mgr_name = mgr_list[0]

        # Validate manager name
        if mgr_name not in ALL_MANAGERS:
            logger.warning(f"invalid context history manager: [{mgr}]")
            continue

        # Parse parameters
        args = []
        kwargs = {}
        for param in mgr_list[1:]:
            param_kv = param.split('=', 1)
            if len(param_kv) == 2:
                # Key-value parameter
                kwargs[param_kv[0]] = param_kv[1]
            else:
                # Positional parameter
                args.append(param)

        # Validate that parameters are provided
        if not args and not kwargs:
            logger.warning(f"missing parameters for this manager: [{mgr}]")
            continue

        # Instantiate the manager
        mgrs.append(
            ALL_MANAGERS[mgr_name](*args, **kwargs)
        )

        # Stop if we've reached the maximum count
        count -= 1
        if count <= 0:
            break

    # Log successful instantiation
    if mgrs:
        logger.info(f"got CONTEXT_HISTORY_MANAGERS: count={len(mgrs)}")

    return mgrs


def get_session_manager(conn=None, default_conn=DEFAULT_CONN) -> SessionStorageBase:
    """
    Get a session manager instance with fallback logic.

    The function tries to get a session manager in the following order:
    1. Using the provided connection string
    2. Using the first manager from environment configuration
    3. Using the default connection string

    Args:
        conn (str, optional): Database connection string. If provided,
                             this takes highest priority.
        default_conn (str, optional): Default connection string to use
                                     if no other options are available.

    Returns:
        SessionStorageBase: An instance of session manager.

    Raises:
        Exception: If no valid session manager can be instantiated.
    """
    # Priority 1: Use provided connection string
    if conn:
        return SessionSQLAlchemy(conn)

    # Priority 2: Get manager from environment configuration
    mgrs = get_managers_by_env(1)
    if mgrs:
        msg_mgr = mgrs[0]
        return SessionSQLAlchemy(msg_mgr.conn)

    # Priority 3: Use default connection string
    if default_conn:
        return SessionSQLAlchemy(default_conn)

    # If all options fail, raise exception
    raise Exception("fail to get session manager")


def get_messages_by_session(session_id:str="", session_mgr:SessionStorageBase=None) -> list[dict]:
    """
    Retrieve messages for a specific session.

    If no session_id is provided, the function attempts to get it from
    the SESSION_ID environment variable.

    Args:
        session_id (str, optional): The session identifier. If empty,
                                   tries to get from environment.
        session_mgr (SessionStorageBase, optional): Session manager instance.
                                                   If None, a new one is created.

    Returns:
        list[dict]: List of message dictionaries for the session,
                   or empty list if session doesn't exist or no session_id provided.
    """
    # Try to get session_id from environment if not provided
    if not session_id:
        session_id = os.getenv("SESSION_ID")

    # Return empty list if no session_id is available
    if not session_id:
        return []

    # Create session manager if not provided
    if session_mgr is None:
        session_mgr = get_session_manager()

    # Retrieve messages if session exists
    if session_mgr.exists_session(session_id):
        messages_from_session = session_mgr.retrieve_messages(session_id)
        logger.info(f"retrieve messages: session_id={session_id}, count={len(messages_from_session)}")
        return messages_from_session

    return []


def create_session(session_id:str, task:str, session_mgr:SessionStorageBase=None) -> bool:
    """
    Create a new session for a specific task.

    Args:
        session_id (str): Unique identifier for the session.
        task (str): Description or name of the task for this session.
        session_mgr (SessionStorageBase, optional): Session manager instance.
                                                   If None, a new one is created.

    Returns:
        bool: True if session was created successfully, False otherwise.
    """
    # Validate required parameters
    if not session_id:
        return False
    if not task:
        return False

    # Create session manager if not provided
    if session_mgr is None:
        session_mgr = get_session_manager()

    # Create the session
    session_mgr.create_session(
        SessionData(session_id=session_id, task=task)
    )

    return True


def add_session_message(session_id:str, message:dict) -> bool:
    """
    Add a message to a session across all configured chat history managers.

    Args:
        session_id (str): The session identifier to add the message to.
        message (dict): The message content to add.

    Returns:
        bool: True if message was added to at least one manager, False otherwise.
    """
    # Get all configured chat history managers
    history_mgrs = get_managers_by_env()
    if not history_mgrs:
        return False

    # Add message to all managers
    for mgr in history_mgrs:
        mgr.add_session_message(message, session_id=session_id)

    return True