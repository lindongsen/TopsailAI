'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose: Base prompt management class for AI context handling and message management
'''

import os

from topsailai.logger.log_chat import logger
from topsailai.ai_base.constants import (
    ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL,
    NON_SYSTEM_PROMPT_MESSAGE_INDEX,
    STEP_NAME_OBSERVATION,
)
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
    cmd_tool,
    thread_local_tool,
)
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.utils.thread_local_tool import (
    get_agent_name,
)
from topsailai.utils.thread_local_tool import get_session_id
from topsailai.context.token import count_tokens
from topsailai.context.ctx_manager import get_managers_by_env
from topsailai.context.prompt_env import generate_prompt_for_env


class MessageData(object):
    """
    {"role": ROLE_USER, "content": content, "tool_call_id": None}
    """
    ROLE_USER = ROLE_USER
    ROLE_ASSISTANT = ROLE_ASSISTANT
    ROLE_SYSTEM = ROLE_SYSTEM
    ROLE_TOOL = ROLE_TOOL

    def __init__(self, role:str, content:str, tool_call_id:str=None):
        self.role = str(role)
        self.content = content if isinstance(content, str) else to_json_str(content, indent=0)
        self.tool_call_id = str(tool_call_id) if tool_call_id is not None else tool_call_id

    def to_dict(self):
        result = dict(
            role=self.role,
            content=self.content,
        )
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        return result

    def __str__(self):
        return to_json_str(self.to_dict())


def get_prompt_by_cmd(cmd:str) -> str:
    """ Execute a command to get stdout """
    assert cmd, "missing command"
    ret = cmd_tool.exec_cmd(cmd, timeout=60)
    if ret and ret[0] == 0 and ret[1]:
        content = ret[1].strip()
        if content:
            return content
    return ""

def get_prompt_by_script(env_key:str) -> str:
    """ Execute a script from env to get prompt

    Args:
        env_key (str): TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT, TOPSAILAI_OBTAIN_TOOL_PROMPT_SCRIPT
    """
    script_file = os.getenv(env_key)
    if not script_file:
        return ""
    return get_prompt_by_cmd(script_file)

class ThresholdContextHistory(object):
    """
    Manages context history thresholds for token count and message length

    This class handles the logic for determining when context history exceeds
    configured thresholds and needs to be slimmed down or managed.
    """

    # variables, set default value
    token_max = 128000
    token_ratio = 0.8
    slim_len = 43
    uncached_token_max = 27000

    # constants
    SLIM_MIN_LEN = 27

    def __init__(self):
        """
        Initialize threshold context history with environment variable overrides

        Reads CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS, CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH,
        and CONTEXT_MESSAGES_SLIM_THRESHOLD_UNCACHED_TOKENS from environment to override
        default values if present.
        """
        self.token_max = int(os.getenv("CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS", self.token_max))
        self.slim_len = int(os.getenv("CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH", self.slim_len))
        self.uncached_token_max = int(os.getenv("CONTEXT_MESSAGES_SLIM_THRESHOLD_UNCACHED_TOKENS", self.uncached_token_max))

    def __str__(self):
        return f"ThresholdContextHistory=(token_max: {self.token_max}, token_ratio: {self.token_ratio}, slim_len: {self.slim_len}, uncached_token_max: {self.uncached_token_max})"

    def exceed_ratio(self, token_count, max_ratio=None, max_count=None):
        """
        Check if token count exceeds the configured ratio.

        The ratio is computed as ``token_count / max_count``. If the ratio is
        greater than or equal to ``max_ratio``, the threshold is considered
        exceeded.

        Args:
            token_count (int): Current token count to check.
            max_ratio (float, optional): Ratio threshold to use. Must be
                less than 1. Values below 0.5 are clamped to 0.5. Defaults to
                ``self.token_ratio``.
            max_count (int, optional): Token budget used as the denominator for
                the ratio check. Values below 3000 are clamped to 3000. Defaults
                to ``self.token_max``.

        Returns:
            bool: True if token count exceeds the threshold, False otherwise.
        """
        max_ratio = max_ratio if max_ratio is not None else self.token_ratio
        if max_count is None:
            max_count = self.token_max
        assert isinstance(max_ratio, float) and max_ratio < 1
        max_count = max(3000, max_count)
        max_ratio = max(0.5, max_ratio)

        curr_ratio = float(token_count) / max_count
        if curr_ratio >= max_ratio:
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

        # check cached_tokens first
        agent = thread_local_tool.get_agent_object()

        # debug
        #from topsailai.ai_base.agent_base import AgentBase
        # assert isinstance(agent, AgentBase)

        if agent:
            try:
                current_tokens = agent.llm_model.tokenStat.current_tokens
                uncached_tokens = agent.llm_model.tokenStat.uncached_tokens

                if current_tokens and uncached_tokens:
                    _v_exceed_uncached_tokens = self.exceed_ratio(uncached_tokens, max_count=self.uncached_token_max)
                    if _v_exceed_uncached_tokens:
                        return True

                    # no exceed on uncached_tokens.
                    # tips for current_tokens is exceeded.
                    _v_exceed_current_tokens = self.exceed_ratio(current_tokens)
                    if _v_exceed_current_tokens:
                        logger.warning(
                            "context messages not exceed threshold: current_tokens=%s, uncached_tokens=%s, %s",
                            current_tokens, uncached_tokens, str(self),
                        )
                    return False
            except Exception as e:
                logger.exception(e)

        # check current_tokens
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

    NON_SYSTEM_PROMPT_MESSAGE_INDEX = NON_SYSTEM_PROMPT_MESSAGE_INDEX

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
        prompt_from_script = get_prompt_by_script("TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT")
        if prompt_from_script:
            self.system_prompt += "\n---\n" + prompt_from_script

        # Only write it in AI Agent
        self.tool_prompt = tool_prompt or ""
        prompt_from_script = get_prompt_by_script("TOPSAILAI_OBTAIN_TOOL_PROMPT_SCRIPT")
        if prompt_from_script:
            self.tool_prompt += "\n---\n" + prompt_from_script

        # context history messages
        self.threshold_ctx_history = ThresholdContextHistory()
        self.hooks_ctx_history = get_managers_by_env() # list[ChatHistoryBase]
        # context messages
        self.messages = []
        self.reset_messages(to_suppress_log=True)

        # set flags
        if os.getenv("TOPSAILAI_FLAG_DUMP_MESSAGES") == "1":
            self.flag_dump_messages = True

        # hooks, func(self)
        self.hooks_after_init_prompt = []
        self.hooks_after_new_session = []
        self.hooks_pre_chat = []

    def call_hooks_pre_chat(self):
        """ call hooks before chatting """
        for hook in self.hooks_pre_chat:
            try:
                hook(self)
            except Exception as e:
                logger.exception("failed to call hook [%s]: %s", hook, e)
        return

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
                # last message is not system role
                if self.messages[-1]["role"] == ROLE_SYSTEM:
                    break

                try:
                    hook.add_session_message(self.messages[-1])
                except Exception as e:
                    logger.exception("failed to call hook add_session_message: %s", e)

        # check threshold, link messages to reduce content
        if self.threshold_ctx_history.is_exceeded(self.messages):
            for hook in self.hooks_ctx_history:
                try:
                    hook.link_messages(self.messages)
                except Exception as e:
                    logger.exception("failed to call hook link_messages: %s", e)
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
        logger.info("initializing prompt")
        self.reset_messages()
        for hook in self.hooks_after_init_prompt:
            try:
                hook(self)
            except Exception as e:
                logger.exception("failed to call hook [%s]: %s", hook, e)
        return

    def new_session(self, user_message, need_print_message=True):
        """
        Start a new session with a user message

        Args:
            user_message: The initial user message for the new session
        """
        self.init_prompt()
        context_message = self._build_context_message()
        if context_message:
            context_message = {
                "step_name": STEP_NAME_OBSERVATION,
                "raw_text": context_message,
            }
            self.add_user_message(context_message, need_print=need_print_message)
        if user_message:
            self.add_user_message(user_message, need_print=need_print_message)
        for hook in self.hooks_after_new_session:
            try:
                hook(self)
            except Exception as e:
                logger.exception("failed to call hook [%s]: %s", hook, e)
        return

    def _build_context_message(self) -> str | None:
        """Build a single combined context message from a list of fragments.

        **ONLY ONCE**, The context messages will be store to session.

        Returns:
            str | None: Combined message with separator format, or None if empty.
        """
        # agent-dimension context user messages
        message_list: list[str] = []
        context_user_message = EnvReaderInstance.context_user_message_content
        if context_user_message:
            message_list.append(context_user_message)

        # ONLY ONCE: clean context xxx messages in env
        EnvReaderInstance.clean_context_x_message()

        if not message_list:
            return None

        parts = []
        for item in message_list:
            item = item.strip()
            if not item:
                continue
            parts.append(item)
        if not parts:
            return None

        return "".join(f"---\n{item}\n" for item in parts) + "---\n"

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
        # 0, system
        self.append_message({"role": ROLE_SYSTEM, "content": self.system_prompt}, to_suppress_log)
        # 1, env
        self.append_message({"role": ROLE_SYSTEM, "content": generate_prompt_for_env()}, to_suppress_log)
        # 2, tool
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

    def update_message_for_tool(self):
        """
        Update the tool prompt message
        """
        self.messages[2] = {"role": ROLE_SYSTEM, "content": self.tool_prompt}
        return

    def add_user_message(self, content, need_print=True):
        """
        Add a user message to the context

        Args:
            content: The user message content to add
        """
        if content is None:
            return

        need_format = False
        if isinstance(content, (dict, list)):
            need_format = True

        content = self.hook_format_content(content)
        if need_print:
            print_step(content, need_format=need_format)
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
            print_step(tool_calls, need_format=False)
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
            print_step(f"dump messages: [{file_path}]", need_format=False)
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

    def get_work_memory_first_position(self) -> int|None:
        """ get the first position in the conversation """
        for index, msg in enumerate(self.messages):
            msg_dict = json_load(msg)
            if msg_dict["role"] != ROLE_SYSTEM:
                return index
        return None
