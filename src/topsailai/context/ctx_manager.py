'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose: Context management module for handling chat history and session management
'''

import os
import threading

from topsailai.logger import logger
from topsailai.utils.format_tool import to_list
from topsailai.utils import (
    env_tool,
)

from .chat_history_manager import ALL_MANAGERS
from .chat_history_manager.__base import (
    ChatHistoryBase,
    ChatHistoryMessageData,
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


def get_messages_by_session(
        session_id:str="",
        session_mgr:SessionStorageBase=None,
        for_raw=False,
    ) -> list[dict] | list[ChatHistoryMessageData]:
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
        list[dict]: for_raw=False, List of message dictionaries for the session,
                   or empty list if session doesn't exist or no session_id provided.
        list[ChatHistoryMessageData]: for_raw=True,
    """
    # Try to get session_id from environment if not provided
    if not session_id:
        session_id = env_tool.get_session_id()

    # Return empty list if no session_id is available
    if not session_id:
        return []

    # Create session manager if not provided
    if session_mgr is None:
        session_mgr = get_session_manager()

    # Retrieve messages if session exists
    if session_mgr.exists_session(session_id):
        if for_raw:
            messages_from_session = session_mgr.get_messages_by_session(session_id)
        else:
            messages_from_session = session_mgr.retrieve_messages(session_id)
        logger.info(f"retrieve messages: session_id={session_id}, count={len(messages_from_session)}")
        return messages_from_session

    return []

def update_session_name(session_id:str, session_name:str, session_mgr:SessionStorageBase=None) -> bool:
    """
    Update the name of an existing session.

    Args:
        session_id (str): The session identifier to update.
        session_name (str): The new session name.
        session_mgr (SessionStorageBase, optional): Session manager instance.
                                                   If None, a new one is created.

    Returns:
        bool: True if the session name was updated successfully, False otherwise.
    """
    if not session_id:
        return False
    if session_name is None:
        return False

    if session_mgr is None:
        session_mgr = get_session_manager()

    return session_mgr.update_session_name(session_id, session_name)


def exists_session(session_id:str, session_mgr:SessionStorageBase=None) -> bool:
    """ check if exists session """
    if not session_id:
        return False

    if session_mgr is None:
        session_mgr = get_session_manager()

    return session_mgr.exists_session(session_id)


def _get_auto_session_name_max_length() -> int:
    """Parse TOPSAILAI_AUTO_SESSION_NAME_MAX_LENGTH with fallback."""
    max_length_str = os.getenv("TOPSAILAI_AUTO_SESSION_NAME_MAX_LENGTH", "30")
    try:
        max_length = int(max_length_str)
    except ValueError:
        max_length = 30
    if max_length <= 0:
        max_length = 30
    return max_length


def generate_session_name(session_id: str, message: str) -> str:
    """
    Generate a concise session name from the given message using the LLM.

    This is a synchronous helper. Callers that need non-blocking behavior
    should run it in a background thread.

    Args:
        session_id (str): The session identifier, passed to the LLM chat.
        message (str): The message or task content to summarize from.

    Returns:
        str: The generated session name, or an empty string if generation failed.
    """
    # Import here to avoid a circular import: workspace.llm_shell depends on
    # context.ctx_manager via the agent/chat history stack.
    from topsailai.workspace.llm_shell import get_llm_chat

    if not session_id or not message:
        return ""

    max_length = _get_auto_session_name_max_length()

    system_prompt = (
        "You are a naming assistant. Generate a concise session name based on "
        "the user's content. Return only the session name, without quotes, "
        "without markdown, and without explanation."
    )
    user_message = (
        f"Generate a concise session name (maximum {max_length} characters) "
        f"for the following content:\n\n{message}"
    )

    try:
        llm_chat = get_llm_chat(
            session_id="",
            system_prompt=system_prompt,
            message=user_message,
            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        summary = llm_chat.chat(need_print=False, need_env_message=False)
        if not summary:
            return ""

        session_name = summary.strip().strip("\"'").strip()
        if not session_name:
            return ""

        return session_name[:max_length].strip()
    except Exception as e:
        logger.debug(f"generate_session_name failed for session_id={session_id}: {e}")
        return ""

def _async_update_session_name(session_id: str, message: str, session_mgr: SessionStorageBase):
    """
    Background worker: generate a session name and update storage.

    Failures are swallowed and logged at debug level. The session manager
    instance is reused; SQLAlchemy is configured to be thread-safe for SQLite.

    Args:
        session_id (str): The session id to rename.
        message (str): The message or task content to summarize from.
        session_mgr (SessionStorageBase): Session manager used to update the name.
    """
    try:
        session_name = generate_session_name(session_id, message)
        if not session_name:
            return

        # Do not overwrite an existing name that may have been set meanwhile.
        session_data = session_mgr.get_session(session_id)
        if session_data is None or session_data.session_name:
            return

        session_mgr.update_session_name(session_id, session_name)
        logger.info(f"auto_rename: session_id={session_id}, session_name={session_name}")
    except Exception as e:
        logger.debug(f"auto_rename failed for session_id={session_id}: {e}")

def create_session(session_id:str, task:str, session_name:str=None, session_mgr:SessionStorageBase=None) -> bool:
    """
    Create a new session for a specific task.

    Args:
        session_id (str): Unique identifier for the session.
        task (str): Description or name of the task for this session.
        session_name (str, optional): Display name for the session. If empty
            or None, an asynchronous LLM-based rename may be triggered.
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
        SessionData(session_id=session_id, task=task, session_name=session_name)
    )

    # Trigger asynchronous session name generation if no explicit name was given.
    if not session_name and task:
        if env_tool.EnvReaderInstance.check_bool("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", default=True):
            try:
                threading.Thread(
                    target=_async_update_session_name,
                    args=(session_id, task, session_mgr),
                    daemon=True,
                ).start()
            except Exception as e:
                logger.debug(f"create_session: failed to start auto_rename thread: {e}")

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

def del_session_messages(session_id:str, message_ids:list[str]) -> bool:
    # Get all configured chat history managers
    history_mgrs = get_managers_by_env()
    if not history_mgrs:
        return False

    if not message_ids:
        return False

    message_ids = to_list(message_ids)
    # Add message to all managers
    for mgr in history_mgrs:
        for msg_id in message_ids:
            mgr.del_messages(msg_id, session_id)

    return True

def cut_messages(messages:list, head_tail_offset:int=7) -> list:
    if not messages:
        return messages

    head_tail_offset = int(head_tail_offset)

    if head_tail_offset > 0:
        if len(messages) > (head_tail_offset*2):
            logger.info("cut messages: msg_len=[%s], head_tail_offset=[%s]", len(messages), head_tail_offset)
            return messages[:head_tail_offset] + messages[-head_tail_offset:]

    return messages
