"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
Purpose: Context runtime base module for managing chat sessions and message handling.
"""

import random

from topsailai.ai_base.constants import (
    ROLE_USER,
)
from topsailai.ai_base.agent_base import (
    AgentBase,
)
from topsailai.context import ctx_manager
from topsailai.context.token import count_tokens
from topsailai.tools import (
    story_tool,
)
from topsailai.utils import (
    json_tool,
    env_tool,
    file_tool,
    print_tool,
)
from topsailai.workspace.llm_shell import get_llm_chat
from topsailai.workspace.context import summary_tool


class ContextRuntimeBase(object):
    """
    Context manager for runtime (session).

    Manages user chat sessions and maintains message history between users and agents.

    Variables:
        self.messages: User chats to agent in the current session.
        self.ai_agent.messages: Agent chats to LLM.
    """

    def __init__(self):
        """
        Initialize the ContextRuntimeBase instance.

        Sets up default values for session ID, messages list, and AI agent reference.
        """
        self.session_id = ""
        self.messages = []
        self.ai_agent: AgentBase = None

    @property
    def last_user_message(self):
        """
        Get the last user message from self.messages of current session.

        Returns:
            dict or None: The last message from ROLE_USER, or None if not found.
        """
        last_user_msg = None
        for msg in reversed(self.messages):
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_USER:
                last_user_msg = msg
                break
        return last_user_msg

    def init(self, session_id: str, ai_agent: AgentBase):
        """
        Initialize the context runtime with session ID and AI agent.

        Args:
            session_id (str): Unique identifier for the session.
            ai_agent (AgentBase): The AI agent instance to use for processing.

        Returns:
            None
        """
        self.session_id = session_id
        self.ai_agent = ai_agent
        self.reset_messages()
        return

    def append_message(self, message: dict):
        """
        Append a message to the messages list.

        Args:
            message (dict): The message dictionary to append.

        Returns:
            None
        """
        if not message:
            return

        self.messages.append(message)

    def set_messages(self, value: list):
        """
        Set a new value for the messages list.

        Replaces all existing messages with the provided list.

        Args:
            value (list): New list of messages to set.

        Returns:
            None
        """
        if not value:
            value = []
        if value is self.messages:
            return
        self.messages.clear()
        self.messages += value
        return

    def reset_messages(self):
        """
        Reset messages to the newest from session storage.

        Retrieves messages from the session storage and updates the internal messages list.

        Returns:
            None
        """
        if self.session_id:
            messages_from_session = ctx_manager.get_messages_by_session(self.session_id) or []
            self.set_messages(messages_from_session)
        return

    ###############################################################
    # Env
    ###############################################################

    def _get_quantity_threshold(
            self,
            env_key: str = "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
        ) -> int:
        """
        Get the quantity threshold for message summarization.

        The layer-specific env variable (env_key) takes precedence.
        If it is unset or empty, fall back to the legacy shared variable
        TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD for backward compatibility.
        If the final value is 0, null, or negative, summarization is disabled.

        Args:
            env_key (str): Primary environment variable name to read.
                Defaults to TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD.

        Returns:
            int: The quantity threshold value. Returns 0 if disabled.
        """
        # Read the layer-specific threshold first.
        env_quantity_threshold = env_tool.EnvReaderInstance.get(
            env_key,
            formatter=int,
        )

        # Fall back to the legacy shared threshold for backward compatibility.
        if not env_quantity_threshold or env_quantity_threshold < 0:
            env_quantity_threshold = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
                formatter=int,
            )

        # disabled
        if not env_quantity_threshold or env_quantity_threshold < 0:
            return 0

        number_list = [13, 17, 19, 23]
        quantity_threshold = max(random.choice(number_list), env_quantity_threshold)
        return quantity_threshold

    def _get_head_offset_to_keep_in_summary(
            self,
            head_offset_to_keep: int = None,
        ) -> int:
        """
        Get the head offset to keep in summary.

        Args:
            head_offset_to_keep (int, optional): If provided, use this value directly.
                If None, retrieve from environment variable.

        Returns:
            int: The head offset value to keep in summary. Always returns non-negative value.
        """
        if head_offset_to_keep is None:
            head_offset_to_keep = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP",
                default=0,
                formatter=int
            ) or 0

        if head_offset_to_keep < 0:
            head_offset_to_keep = 0

        return head_offset_to_keep

    def _get_token_calculation_messages(self):
        """
        Get the messages used for real-time token calculation.

        Subclasses may override this to return the message source appropriate
        for their layer (e.g. User2Agent session messages or Agent2LLM messages).

        Returns:
            list | None: The messages to count, or None if not available.
        """
        if self.ai_agent:
            return self.ai_agent.messages
        return self.messages

    def _get_current_tokens(self, messages=None, realtime=False) -> int | None:
        """
        Get the current token count.

        When TOPSAILAI_REALTIME_TOKEN_CALCULATION is enabled, tokens are
        calculated from the provided messages (or the layer-appropriate
        message source). Otherwise, the cached tokenStat.current_tokens value
        is returned for backward compatibility.

        Args:
            messages (list | str, optional): Messages to count. If None, the
                layer-appropriate message source is used.

        Returns:
            int | None: The current token count, or None if not available.
        """
        if not realtime:
            realtime = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_REALTIME_TOKEN_CALCULATION", False
            )
        if realtime:
            if messages is None:
                messages = self._get_token_calculation_messages()
            if messages is None:
                return None
            try:
                return int(count_tokens(str(messages)))
            except Exception:
                return None

        try:
            if self.ai_agent and self.ai_agent.llm_model and self.ai_agent.llm_model.tokenStat:
                return int(self.ai_agent.llm_model.tokenStat.current_tokens)
        except Exception:
            pass
        return None

    ###############################################################
    # Summary
    ###############################################################

    def _get_summary_prompt(
            self,
            prompt: str = None,
            extra_prompt: str=None,
        ) -> str:
        # prompt
        prompt_content = ""
        if prompt is None:
            prompt = env_tool.EnvReaderInstance.get("TOPSAILAI_SUMMARY_PROMPT")
        _, prompt_content = file_tool.get_file_content_fuzzy(prompt)
        if not prompt_content:
            prompt_content = ""

        # extra prompt
        extra_prompt_content = ""
        if extra_prompt is None:
            extra_prompt = summary_tool.get_summary_prompt(self.ai_agent.agent_type)
            if not extra_prompt:
                if self.ai_agent.agent_type.lower().endswith("community"):
                    extra_prompt = story_tool.PROMPT_SUMMARY_MEMORY
                else:
                    extra_prompt = story_tool.PROMPT_SUMMARY_TASK
            extra_prompt_content = extra_prompt
        else:
            _, extra_prompt_content = file_tool.get_file_content_fuzzy(extra_prompt)
            if not extra_prompt_content:
                extra_prompt_content = ""

        return extra_prompt_content + prompt_content


    def _summarize_messages(
            self,
            messages,
            prompt: str = None,
            extra_prompt: str=None,
        ):
        """
        Summarize messages into a single text using LLM.

        Args:
            messages: The messages to summarize. Can be a string or list/dict.
            prompt (str, optional): Custom prompt for summarization. If None, uses
                default from environment variable.

        Returns:
            tuple: A tuple containing (llm_chat, answer) where:
                - llm_chat: The LLM chat instance used for summarization
                - answer (str): The summarized text response from LLM

        Raises:
            AssertionError: If messages is null/empty.
        """
        # switch to summary-runtime mode
        if env_tool.EnvReaderInstance.get("TOPSAILAI_CONTEXT_SUMMARY_MODE") == "runtime":
            return self._summarize_runtime_messages(
                messages, prompt=prompt, extra_prompt=extra_prompt,
            )

        # message
        assert messages, "null of messages"
        message_title = """
---
Summarize Messages
---
"""
        one_msg = messages if isinstance(messages, str) else json_tool.json_dump(messages)

        llm_chat = get_llm_chat(
            message=message_title + one_msg,
            session_id="",
            system_prompt=self._get_summary_prompt(prompt=prompt, extra_prompt=extra_prompt),

            need_stdout=env_tool.is_interactive_mode(),
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        answer = llm_chat.chat(
            need_print=env_tool.is_interactive_mode(),
            need_env_message=False,
        )

        return (llm_chat, answer)


    def _summarize_runtime_messages(
            self,
            messages,
            prompt: str = None,
            extra_prompt: str=None,
        ):
        all_messages = self.ai_agent.messages[:] if self.ai_agent else None
        if not all_messages or len(all_messages) < 7:
            all_messages = messages
        assert all_messages, "null of messages"
        print_tool.print_debug(f"All of messages: length=[{len(all_messages)}]")

        llm_chat = get_llm_chat(
            message="NA",
            session_id="",
            system_prompt="",

            need_stdout=env_tool.is_interactive_mode(),
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        llm_chat.prompt_ctl.messages = all_messages
        TIPS = "\nDONOT CALL ANY TOOLS, DIRECTLY OUTPUT FINAL_ANSWER!"
        answer = llm_chat.chat(
            self._get_summary_prompt(prompt=prompt, extra_prompt=extra_prompt) + TIPS,
            need_print=env_tool.is_interactive_mode(),
            need_env_message=False,
        )

        return (llm_chat, answer)
