'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose:
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
    """ define threshold  """

    # variables
    token_max = 1280000
    token_ratio = 0.8
    slim_len = 43

    # constants
    SLIM_MIN_LEN = 27

    def __init__(self):
        self.token_max = int(os.getenv("MAX_TOKENS", self.token_max))
        self.slim_len = int(os.getenv("CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH", self.slim_len))

    def exceed_ratio(self, token_count):
        """ token count is exceeded ratio """
        curr_ratio = float(token_count) / self.token_max
        if curr_ratio >= self.token_ratio:
            return True
        return False

    def exceed_msg_len(self, msg_len):
        """ message list length is exceeded """
        if msg_len >= max(self.SLIM_MIN_LEN, self.slim_len):
            return True
        return False

    def is_exceeded(self, messages:list):
        """ return bool. True for exceeded """
        if self.exceed_msg_len(len(messages)):
            return True
        token_count_now = count_tokens(str(messages))
        if self.exceed_ratio(token_count_now):
            return True
        return False


class PromptBase(object):
    """ prompt base manager """

    # define flags
    flag_dump_messages = False

    def __init__(self, system_prompt:str, tool_prompt:str=""):
        """
        Args:
            system_prompt (str):
            tool_prompt (str, optional): User give it. Defaults to "".
            tools_name (list, optional): Internal tools. Defaults to None (no need any tools).
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
        """ let context messages become to history messages. remember these messages. """
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
        """ append a message to context """
        if not to_suppress_log:
            logger.info(msg)

        # debug
        #if self.messages and msg == self.messages[-1]:
        #    logger.warning("duplicate message")

        self.messages.append(msg)
        self.call_hooks_ctx_history()

    def init_prompt(self):
        """ init sth. """
        self.reset_messages()
        for hook in self.hooks_after_init_prompt:
            try:
                hook(self)
            except Exception:
                logger.error(f"failed to call hook: {traceback.format_exc()}")
        return

    def new_session(self, user_message):
        """ start a new session """
        self.init_prompt()
        self.add_user_message(user_message)
        for hook in self.hooks_after_new_session:
            try:
                hook(self)
            except Exception:
                logger.error(f"failed to call hook: {traceback.format_exc()}")
        return

    def hook_format_content(self, content):
        """ set a hook to format content to text for LLM can to read """
        return to_json_str(content)

    def reset_messages(self, to_suppress_log=False):
        """ reset context message. clear all of messages.

        index:
        - system
        - env, dynamic
        - tool
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
        """ update env info """
        self.messages[1] = {"role": ROLE_SYSTEM, "content": generate_prompt_for_env()}
        return

    def add_user_message(self, content):
        """ the message from human """
        if content is None:
            return
        content = self.hook_format_content(content)
        print_step(content)
        self.append_message({"role": ROLE_USER, "content": content})

    def add_assistant_message(self, content, tool_calls=None):
        """ the message from LLM """
        if content is None:
            return
        content = self.hook_format_content(content)
        print_step(content)
        if tool_calls:
            print_step(tool_calls)
        self.append_message({"role": ROLE_ASSISTANT, "content": content, "tool_calls": tool_calls})

    def add_tool_message(self, content):
        """ the message from tool call """
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
        """ get id from the last message """
        last_message = self.messages[-1]
        tool_calls = last_message.get("tool_calls")
        if tool_calls:
            return tool_calls[0].id
        return None

    def dump_messages(self):
        """ dump messages to a file.

        return file path. None for failed.
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
        """ read file content as messages """
        with open(file_path, encoding='utf-8') as fd:
            content = fd.read()
            self.messages = json_load(content)
            assert isinstance(self.messages, list)
        return
