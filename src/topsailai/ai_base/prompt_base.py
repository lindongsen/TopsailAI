'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose: Base prompt management class for AI context handling and message management
'''

import os
import traceback

from topsailai.logger.log_chat import logger
from topsailai.tools import (
    get_tool_prompt,
)
from topsailai.ai_base.constants import (
    ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL,
)
from topsailai.prompt_hub import prompt_tool
from topsailai.utils.print_tool import (
    print_step,
    print_error,
)
from topsailai.utils.json_tool import (
    to_json_str,
    json_load,
)
from topsailai.utils import (
    time_tool,
    env_tool,
)
from topsailai.utils.thread_local_tool import (
    get_agent_name,
)
from topsailai.utils.thread_local_tool import get_session_id
from topsailai.context.token import count_tokens
from topsailai.context.ctx_manager import get_managers_by_env
from topsailai.context.prompt_env import generate_prompt_for_env


class ThresholdContextHistory(object):
    """
    Manages context history thresholds for token count and message length

    This class handles the logic for determining when context history exceeds
    configured thresholds and needs to be slimmed down or managed.
    """

    # variables
    token_max = 1280000
    token_ratio = 0.8
    slim_len = 43

    # constants
    SLIM_MIN_LEN = 27

    def __init__(self):
        """
        Initialize threshold context history with environment variable overrides

        Reads MAX_TOKENS and CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH from environment
        to override default values if present.
        """
        self.token_max = int(os.getenv("MAX_TOKENS", self.token_max))
        self.slim_len = int(os.getenv("CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH", self.slim_len))

    def exceed_ratio(self, token_count):
        """
        Check if token count exceeds the configured ratio threshold

        Args:
            token_count (int): Current token count to check

        Returns:
            bool: True if token count exceeds the ratio threshold, False otherwise
        """
        curr_ratio = float(token_count) / self.token_max
        if curr_ratio >= self.token_ratio:
            return True
        return False

    def exceed_msg_len(self, msg_len):
        """
        Check if message list length exceeds the configured threshold

        Args:
            msg_len (int): Current message list length to check

        Returns:
            bool: True if message length exceeds the threshold, False otherwise
        """
        if msg_len >= max(self.SLIM_MIN_LEN, self.slim_len):
            return True
        return False

    def is_exceeded(self, messages:list):
        """
        Check if context history exceeds any configured thresholds

        Args:
            messages (list): List of messages to check against thresholds

        Returns:
            bool: True if either message length or token ratio is exceeded, False otherwise
        """
        if self.exceed_msg_len(len(messages)):
            return True
        token_count_now = count_tokens(str(messages))
        if self.exceed_ratio(token_count_now):
            return True
        return False


class PromptBase(object):
    """
    Base prompt manager for AI context handling

    This class manages the conversation context, message history, and provides
    hooks for context management and message processing.
    """

    # define flags
    flag_dump_messages = False

    def __init__(self, system_prompt:str, tool_prompt:str=""):
        """
        Initialize the prompt base manager

        Args:
            system_prompt (str): The system prompt to use for the AI
            tool_prompt (str, optional): Tool prompt provided by user. Defaults to "".
        """
        assert system_prompt, "missing system_prompt"
        self.system_prompt = system_prompt

        # Only write it in AI Agent
        self.tool_prompt = tool_prompt or ""

        # context history messages
        self.threshold_ctx_history = ThresholdContextHistory()
        self.hooks_ctx_history = get_managers_by_env() # list[ChatHistoryBase]

        # context messages
        self.messages = []
        self.reset_messages(to_suppress_log=True)

        # set flags
        if os.getenv("FLAG_DUMP_MESSAGES") == "1":
            self.flag_dump_messages = True

        # hooks, func(self)
        self.hooks_after_init_prompt = []
        self.hooks_after_new_session = []

    def call_hooks_ctx_history(self):
        """
        Call context history hooks to manage message history

        This method handles:
        - Recording session messages if session ID exists
        - Linking messages when thresholds are exceeded
        - Error handling for hook execution
        """
        if not self.hooks_ctx_history:
            return

        # record session
        if get_session_id():
            for hook in self.hooks_ctx_history:
                try:
                    hook.add_session_message(self.messages[-1])
                except Exception:
                    logger.error(f"failed to call hook add_session_message: {traceback.format_exc()}")

        # check threshold, link messages to reduce content
        if self.threshold_ctx_history.is_exceeded(self.messages):
            for hook in self.hooks_ctx_history:
                try:
                    hook.link_messages(self.messages)
                except Exception:
                    logger.error(f"failed to call hook link_messages: {traceback.format_exc()}")
        return

    def append_message(self, msg:dict, to_suppress_log=False):
        """
        Append a message to the context and call history hooks

        Args:
            msg (dict): Message dictionary to append
            to_suppress_log (bool, optional): Whether to suppress logging. Defaults to False.
        """
        if not to_suppress_log:
            logger.info(msg)

        # debug
        #if self.messages and msg == self.messages[-1]:
        #    logger.warning("duplicate message")

        self.messages.append(msg)
        self.call_hooks_ctx_history()

    def init_prompt(self):
        """
        Initialize the prompt system

        Resets messages and calls after-init-prompt hooks
        """
        self.reset_messages()
        for hook in self.hooks_after_init_prompt:
            try:
                hook(self)
            except Exception:
                logger.error(f"failed to call hook: {traceback.format_exc()}")
        return

    def new_session(self, user_message):
        """
        Start a new session with a user message

        Args:
            user_message: The initial user message for the new session
        """
        self.init_prompt()
        self.add_user_message(user_message)
        for hook in self.hooks_after_new_session:
            try:
                hook(self)
            except Exception:
                logger.error(f"failed to call hook: {traceback.format_exc()}")
        return

    def hook_format_content(self, content):
        """
        Hook to format content for LLM consumption

        Args:
            content: Content to format

        Returns:
            str: Formatted content as JSON string
        """
        return to_json_str(content)

    def reset_messages(self, to_suppress_log=False):
        """
        Reset context messages to initial state

        Clears all messages and re-initializes with:
        - System prompt
        - Environment prompt
        - Tool prompt (if available)

        Args:
            to_suppress_log (bool, optional): Whether to suppress logging. Defaults to False.
        """
        self.messages = []
        # 1
        self.append_message({"role": ROLE_SYSTEM, "content": self.system_prompt}, to_suppress_log)
        # 2
        self.append_message({"role": ROLE_SYSTEM, "content": generate_prompt_for_env()}, to_suppress_log)
        if self.tool_prompt:
            # last
            self.append_message({"role": ROLE_SYSTEM, "content": self.tool_prompt}, to_suppress_log)

    def update_message_for_env(self):
        """
        Update the environment information message

        Replaces the environment prompt message with current environment data
        """
        self.messages[1] = {"role": ROLE_SYSTEM, "content": generate_prompt_for_env()}
        return

    def add_user_message(self, content):
        """
        Add a user message to the context

        Args:
            content: The user message content to add
        """
        if content is None:
            return
        content = self.hook_format_content(content)
        print_step(content)
        self.append_message({"role": ROLE_USER, "content": content})

    def add_assistant_message(self, content, tool_calls=None):
        """
        Add an assistant message to the context

        Args:
            content: The assistant message content to add
            tool_calls: Optional tool calls associated with the message
        """
        if content is None:
            return
        content = self.hook_format_content(content)
        print_step(content)
        if tool_calls:
            print_step(tool_calls)
        self.append_message({"role": ROLE_ASSISTANT, "content": content, "tool_calls": tool_calls})

    def add_tool_message(self, content):
        """
        Add a tool message to the context

        Args:
            content: The tool message content to add
        """
        if content is None:
            return
        content = self.hook_format_content(content)
        print_step(content)
        tool_call_id = self.get_tool_call_id()
        if tool_call_id:
            self.append_message({"role": ROLE_TOOL, "content": content, "tool_call_id": tool_call_id})
        else:
            self.append_message({"role": ROLE_USER, "content": content, "tool_call_id": None})
        return

    def get_tool_call_id(self):
        """
        Get the tool call ID from the last message

        Returns:
            str or None: The tool call ID if available, None otherwise
        """
        last_message = self.messages[-1]
        tool_calls = last_message.get("tool_calls")
        if tool_calls:
            return tool_calls[0].id
        return None

    def dump_messages(self):
        """
        Dump current messages to a file for debugging

        Returns:
            str or None: File path if successful, None if failed
        """
        try:
            now_date = time_tool.get_current_date(True)
            file_name = f"dump.{get_agent_name()}.{now_date}.msg"
            file_path = file_name
            with open(file_path, 'w', encoding='utf-8') as fd:
                fd.write(to_json_str(self.messages))
            print_step(f"dump messages: [{file_path}]")
            return file_path
        except Exception as e:
            print_error(f"dump messages failed: {e}")
        return None

    def load_messages(self, file_path:str):
        """
        Load messages from a file

        Args:
            file_path (str): Path to the file containing messages
        """
        with open(file_path, encoding='utf-8') as fd:
            content = fd.read()
            self.messages = json_load(content)
            assert isinstance(self.messages, list)
        return
