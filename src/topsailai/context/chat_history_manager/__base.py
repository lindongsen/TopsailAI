'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose:
'''

from typing import Optional

from topsailai.logger import logger
from topsailai.utils.hash_tool import md5sum
from topsailai.utils import json_tool
from topsailai.utils import format_tool
from topsailai.utils.thread_local_tool import get_session_id
from topsailai.utils.time_tool import get_current_date
from topsailai.context.token import count_tokens
from topsailai.ai_base.constants import ROLE_SYSTEM, ROLE_USER


class ChatHistoryMessageData(object):
    """
    Data structure for a chat history message.

    Attributes:
        msg_id (str): Unique identifier for the message (primary key).
        session_id (str): Identifier for the session.
        message (str): The content of the message.
        msg_size (int): Length of the message.
        create_time (datetime or None): Timestamp when the message was created.
        access_time (datetime or None): Last access time, updated when queried by msg_id.
        access_count (int or None): Number of times the message has been retrieved.
    """

    def __init__(self, message:str, msg_id:str, session_id:str):
        self.msg_id = msg_id
        self.session_id = session_id
        self.message = message
        if not self.msg_id and message:
            self.msg_id = md5sum(message)

        self.msg_size = len(message) if message else 0
        self.create_time = None
        self.access_time = None
        self.access_count = None


class MessageStorageBase(object):
    """ Base class for chat history messages manager. """

    conn = None

    def add_session_message(self, last_message:dict):
        """ add message for session """
        raise NotImplementedError

    def add_message(self, msg: ChatHistoryMessageData):
        """
        Add a message to the storage if it doesn't exist, and create a session mapping.

        If the message with the given msg_id already exists, it won't be re-added.
        Always adds a mapping between the message and the session, if not already present.

        Args:
            msg (ChatHistoryMessageData): The message data to add, including msg_id, message, and session_id.
        """
        raise NotImplementedError

    def get_message(self, msg_id: str) -> ChatHistoryMessageData:
        """
        Retrieve a single message by its msg_id and update access metadata.

        Updates the access_time to current time and increments access_count.

        Args:
            msg_id (str): The unique identifier of the message to retrieve.

        Returns:
            ChatHistoryMessageData: The message data object, or None if not found.
        """
        raise NotImplementedError

    def get_messages_by_session(self, session_id: str) -> list[ChatHistoryMessageData]:
        """
        Retrieve all messages associated with a specific session, ordered by creation time (descending).

        Args:
            session_id (str): The session identifier to filter messages.

        Returns:
            list[ChatHistoryMessageData]: List of message data objects for the session.
        """
        raise NotImplementedError

    def del_messages(self, msg_id: Optional[str] = None, session_id: Optional[str] = None):
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

    def update_message_access(self, msg_id: str):
        """
        Update the access metadata for a message: set access_time to current time and increment access_count.

        Args:
            msg_id (str): The unique identifier of the message to update.
        """
        raise NotImplementedError

    def clean_messages(self, before_seconds:int) -> int:
        """
        Delete messages that have not been accessed within the specified time period.

        Args:
            before_seconds (int): Number of seconds before current time.
                                Messages with access_time less than (current time - before_seconds) will be deleted.

        Returns:
            int: Number of messages deleted.
        """
        raise NotImplementedError


class ContextManager(MessageStorageBase):
    """ context messages manager """
    ignored_roles = set([ROLE_SYSTEM, ROLE_USER])
    attention_step_names = set(["action", "observation"])
    prefix_raw_text_retrieve_msg = "retrieve_msg by msg_id="

    def _link_msg_id(self, content_dict:dict):
        """ link content to msg_id """
        message = None
        if len(content_dict) == 2 and "raw_text" in content_dict:
            message = content_dict["raw_text"]
            if not isinstance(message, str):
                message = json_tool.json_dump(message, indent=0)
        else:
            message = json_tool.json_dump(content_dict, indent=0)
        msg_obj = ChatHistoryMessageData(
            message=message,
            session_id=get_session_id(),
            msg_id=None,
        )
        self.add_message(msg_obj)
        content_dict.clear()
        content_dict.update(
            dict(
                step_name="archive",
                raw_text=f"{self.prefix_raw_text_retrieve_msg}{msg_obj.msg_id}"
            )
        )
        logger.info(
            f"message is archived: "
            f"msg_id={msg_obj.msg_id}, "
            f"length={msg_obj.msg_size}, "
            f"save_tokens={count_tokens(msg_obj.message)}"
        )
        return

    def link_messages(self, messages, index_start=3, index_end=-11, max_size=1024):
        """ link a message to msg_id """
        for msg in messages[index_start:index_end]:
            if msg["role"] in self.ignored_roles:
                if msg["role"] == ROLE_USER and "tool_call_id" in msg:
                    # need link
                    pass
                else:
                    continue
            content = msg["content"]
            if content[0] not in ["{", "["]:
                continue
            content_obj = None
            try:
                content_obj = json_tool.json_load(content)
            except Exception as _:
                continue

            if not content_obj:
                continue

            new_content_obj = []
            flag_changed = False
            for content_dict in format_tool.to_list(content_obj):
                new_content_obj.append(content_dict)
                if "step_name" not in content_dict:
                    continue
                if content_dict["step_name"] not in self.attention_step_names:
                    continue
                if len(str(content_dict)) <= max_size:
                    continue

                self._link_msg_id(content_dict)
                flag_changed = True

            if flag_changed:
                msg["content"] = json_tool.json_dump(new_content_obj)

        # end for
        return

    def retrieve_message(self, msg_id: str) -> str:
        """ retrieve a message """
        return self.get_message(msg_id).message

    def retrieve_messages(self, session_id:str) -> list[dict]:
        """ retrieve messages for session continue """
        msg_set = self.get_messages_by_session(session_id)
        return [
            json_tool.json_load(msg.message) for msg in msg_set
        ]

    def __call__(self, messages:list):
        """ callable """
        # reduce the content of context messages.
        self.link_messages(messages)
        return

    def add_session_message(self, last_message:dict, session_id:str=None):
        """ add message for session """
        # add last message to storage
        if not session_id:
            session_id = get_session_id()
        if not session_id or session_id == "None":
            return

        if last_message["role"] != ROLE_SYSTEM:
            new_last_message = {"create_time": get_current_date(include_ms=True)}
            new_last_message.update(last_message)
            last_message = new_last_message

        # save last message
        last_message = json_tool.json_dump(last_message)
        msg_data = ChatHistoryMessageData(
            message=last_message,
            session_id=session_id,
            msg_id=None,
        )
        self.add_message(msg_data)
        logger.info(f"add message for session: session_id={session_id}, msg_id={msg_data.msg_id}")

        return


class ChatHistoryBase(ContextManager):
    """
    Base class for chat history messages manager.

    This abstract base class defines the interface for managing chat history messages
    and sessions. Subclasses must implement all abstract methods to provide specific
    storage implementations.

    Class Attributes:
        tb_chat_history_messages (str): Table name for chat history messages.
        tb_map_session_message (str): Table name for session-message mapping.
    """
    tb_chat_history_messages = "chat_history_messages"
    tb_map_session_message = "map_session_message"
