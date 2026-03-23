'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-23
  Purpose:
'''

import random

from topsailai.ai_base.constants import (
    ROLE_USER,
)
from topsailai.ai_base.agent_base import (
    AgentBase,
)
from topsailai.context import ctx_manager
from topsailai.tools import (
    story_tool,
)
from topsailai.utils import (
    json_tool,
    env_tool,
    file_tool,
)
from topsailai.workspace.llm_shell import get_llm_chat


class ContextRuntimeBase(object):
    """ context manager for runtime (session)

    Variables:
        self.messages: user chats to agent
        self.ai_agent.messages: agent chats to LLM
    """
    def __init__(self):
        self.session_id = ""
        self.messages = []
        self.ai_agent:AgentBase = None

    @property
    def last_user_message(self):
        """ get last of user message from self.messages of current session """
        last_user_msg = None
        for msg in reversed(self.messages):
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_USER:
                last_user_msg = msg
                break
        return last_user_msg

    def init(
            self,
            session_id:str,
            ai_agent:AgentBase,
        ):
        """ init data """
        self.session_id = session_id
        self.ai_agent = ai_agent
        self.reset_messages()
        return

    def append_message(self, message:dict):
        """ append a message """
        if not message:
            return

        self.messages.append(message)

    def set_messages(self, value:list):
        """ set new value """
        if not value:
            value = []
        if value is self.messages:
            return
        self.messages.clear()
        self.messages += value
        return

    def reset_messages(self):
        """ reset messages to newest """
        if self.session_id:
            messages_from_session = ctx_manager.get_messages_by_session(self.session_id) or []
            self.set_messages(messages_from_session)
        return


    ###############################################################
    # Env
    ###############################################################
    def __get_quantity_threshold(self) -> int:
        """ if 0 or null, it is disabled. """
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

    def __get_head_offset_to_keep_in_summary(
            self,
            head_offset_to_keep:int=None,
        ) -> int:
        """
        Args:
            head_offset_to_keep: if None, get it from env.
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

    ###############################################################
    # Summary
    ###############################################################
    def _summarize_messages(self, messages, prompt:str=None):
        """ summarize messages to one text.

        return (llm_chat, answer)
        """
        assert messages, "null of messages"
        one_msg = messages if isinstance(messages, str) else json_tool.json_dump(messages)
        enhanced_prompt = "\n---\nYou MUST focus on the Human's intention\n---\n\n"

        # prompt
        if prompt is None:
            prompt = env_tool.EnvReaderInstance.get("TOPSAILAI_SUMMARY_PROMPT")
        _, prompt_content = file_tool.get_file_content_fuzzy(prompt)
        if not prompt_content:
            prompt_content = ""

        llm_chat = get_llm_chat(
            message=enhanced_prompt+one_msg,
            session_id="",
            system_prompt=story_tool.PROMPT_SUMMARY + prompt_content,

            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        answer = llm_chat.chat(need_print=False)

        return (llm_chat, answer)
