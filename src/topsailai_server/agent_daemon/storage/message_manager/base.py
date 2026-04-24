'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose:
'''

from datetime import datetime
from typing import Optional
from topsailai.utils import (
    time_tool,
)


class MessageData(object):
    """
    Data structure for a chat history message.

    This class represents a single message in the chat history with all its metadata.

    Attributes:
        msg_id (str): Unique identifier for the message.
        session_id (str): Identifier for the session.
        message (str): The content of the message.
        role (str): Role of the message sender (user/assistant), default is user.
        create_time (datetime or None): Timestamp when the message was created.
        update_time (datetime or None): Timestamp when the message was last updated.
        task_id (str or None): Task ID generated at this message point.
        task_result (str or None): Result of the task.
        processed_msg_id (str or None): The row of data comes from processed_msg_id processing results.

    primary_keys: (msg_id, session_id)
    """

    def __init__(
        self,
        message: str,
        msg_id: str = None,
        session_id: str = None,
        role: str = "user",
        create_time: Optional[datetime] = None,
        update_time: Optional[datetime] = None,
        task_id: Optional[str] = None,
        task_result: Optional[str] = None,
        processed_msg_id: Optional[str] = None
    ):
        """
        Initialize a MessageData instance.

        Args:
            message (str): The content of the message.
            msg_id (str): Unique identifier for the message. If None, will be generated from message content.
            session_id (str): Identifier for the session.
            role (str): Role of the message sender (user/assistant), default is user.
            create_time (datetime or None): Timestamp when the message was created.
            update_time (datetime or None): Timestamp when the message was last updated.
            task_id (str or None): Task ID generated at this message point.
            task_result (str or None): Result of the task.
            processed_msg_id (str or None): The row of data comes from processed_msg_id processing results.
        """
        self.msg_id = msg_id or time_tool.get_now_hex_str()
        self.session_id = session_id
        self.message = message
        self.role = role
        self.create_time = create_time
        self.update_time = update_time
        self.task_id = task_id
        self.task_result = task_result
        self.processed_msg_id = processed_msg_id


class MessageStorageBase(object):
    """
    Abstract base class for chat history message storage implementations.

    This class defines the interface that all concrete storage implementations
    must follow. Subclasses should implement all abstract methods.
    """

    # Name of the message table in storage
    tb_message = "message"

    def create(self, message_data: MessageData) -> bool:
        """
        Create a new message in storage.

        Args:
            message_data (MessageData): The message data to create.

        Returns:
            bool: True if successful, False otherwise.
        """
        raise NotImplementedError

    def get(self, msg_id: str, session_id: str) -> Optional[MessageData]:
        """
        Retrieve a message by its msg_id and session_id.

        Args:
            msg_id (str): The unique identifier of the message.
            session_id (str): The session identifier.

        Returns:
            MessageData: The message data object, or None if not found.
        """
        raise NotImplementedError

    def get_by_session(self, session_id: str) -> list[MessageData]:
        """
        Retrieve all messages associated with a specific session.

        Args:
            session_id (str): The session identifier to filter messages.

        Returns:
            list[MessageData]: List of message data objects for the session.
        """
        raise NotImplementedError

    def get_by_session_sorted(
        self,
        session_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        sort_key: str = "create_time",
        order_by: str = "desc",
        offset: int = 0,
        limit: int = 1000
    ) -> list[MessageData]:
        """
        Retrieve messages for a session with sorting and filtering.

        Args:
            session_id (str): The session identifier.
            start_time (datetime, optional): Filter messages created after this time.
            end_time (datetime, optional): Filter messages created before this time.
            sort_key (str): Field to sort by, default is create_time.
            order_by (str): Sort order, 'asc' or 'desc', default is desc.
            offset (int): Number of records to skip.
            limit (int): Maximum number of records to return.

        Returns:
            list[MessageData]: List of message data objects.
        """
        raise NotImplementedError

    def get_latest_message(self, session_id: str) -> Optional[MessageData]:
        """
        Get the latest message for a session.

        Args:
            session_id (str): The session identifier.

        Returns:
            MessageData: The latest message, or None if not found.
        """
        raise NotImplementedError

    def get_unprocessed_messages(self, session_id: str, processed_msg_id: str) -> list[MessageData]:
        """
        Get unprocessed messages after the processed_msg_id.

        Args:
            session_id (str): The session identifier.
            processed_msg_id (str): The last processed message ID.

        Returns:
            list[MessageData]: List of unprocessed messages.
        """
        raise NotImplementedError

    def get_messages_since(self, since: datetime) -> list[MessageData]:
        """
        Get all messages created since the specified time.

        Args:
            since (datetime): Get messages created after this time.

        Returns:
            list[MessageData]: List of messages.
        """
        raise NotImplementedError

    def update_task_info(
        self,
        msg_id: str,
        session_id: str,
        task_id: Optional[str],
        task_result: Optional[str],
        processed_msg_id: Optional[str] = None
    ) -> Optional[MessageData]:
        """
        Update task_id, task_result, and processed_msg_id for a message.

        Args:
            msg_id (str): The message ID.
            session_id (str): The session ID.
            task_id (str or None): The task ID.
            task_result (str or None): The task result.
            processed_msg_id (str or None): The processed message ID.

        Returns:
            MessageData: The updated message, or None if not found.
        """
        raise NotImplementedError

    def delete_messages_by_session(self, session_id: str) -> int:
        """
        Delete all messages for a session.

        Args:
            session_id (str): The session identifier.

        Returns:
            int: Number of messages deleted.
        """
        raise NotImplementedError

    def add_message(self, msg: MessageData):
        """
        Add a message to the storage if it doesn't exist, and create a session mapping.

        If the message with the given msg_id already exists, it won't be re-added.
        Always adds a mapping between the message and the session, if not already present.

        Args:
            msg (MessageData): The message data to add, including msg_id, message, and session_id.
        """
        raise NotImplementedError

    def get_message(self, msg_id: str) -> MessageData:
        """
        Retrieve a single message by its msg_id and update access metadata.

        Updates the access_time to current time and increments access_count.

        Args:
            msg_id (str): The unique identifier of the message to retrieve.

        Returns:
            MessageData: The message data object, or None if not found.
        """
        raise NotImplementedError

    def get_messages_by_session(self, session_id: str) -> list[MessageData]:
        """
        Retrieve all messages associated with a specific session, ordered by creation time (descending).

        Args:
            session_id (str): The session identifier to filter messages.

        Returns:
            list[MessageData]: List of message data objects for the session.
        """
        raise NotImplementedError

    def del_messages(self, msg_id: str = None, session_id: str = None):
        """
        Delete messages from storage based on msg_id or session_id.

        If session_id is provided, deletes all mappings for that session and any orphaned messages
        (messages no longer mapped to any session). If msg_id is provided, deletes all mappings
        for that message and the message itself. At least one of msg_id or session_id must be provided.

        Args:
            msg_id (str, optional): The message ID to delete all instances of.
            session_id (str, optional): The session ID to delete all messages for.

        Raises:
            AssertionError: If neither msg_id nor session_id is provided.
        """
        raise NotImplementedError

    def clean_messages(self, before_seconds: int, session_id: str = None) -> int:
        """
        Delete messages that created within the specified time period.

        Args:
            before_seconds (int): Number of seconds before current time.
                                Messages with create_time less than (current time - before_seconds) will be deleted.
            session_id (str): The session identifier to filter messages.

        Returns:
            int: Number of messages deleted.
        """
        raise NotImplementedError
