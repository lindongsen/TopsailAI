'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-23
  Purpose:
'''

import random

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_SYSTEM,
)
from topsailai.utils.print_tool import (
    print_step,
)
from topsailai.utils import (
    json_tool,
)
from topsailai.workspace.context.base import (
    ContextRuntimeBase,
)


class ContextRuntimeAgent2LLM(ContextRuntimeBase):
    """ Agent chats to LLM """

    # agent chats to LLM
    def del_agent_messages(self, indexes:list[int]) -> list[int]:
        """delete some messages from ai_agent.messages

        Args:
            indexes (list[int]): Sequence number starting from 0

        Returns:
            list[int]: already deleted list
        """
        if not indexes:
            return []

        new_messages = []
        deleted_list = []
        for i, msg in enumerate(self.ai_agent.messages):
            new_messages.append(msg)
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_SYSTEM:
                continue
            if i not in indexes:
                continue
            deleted_list.append(i)
            new_messages.pop()
        if not deleted_list:
            return []
        self.ai_agent.messages = new_messages

        return deleted_list

    def summarize_messages_for_processing(
            self,
            messages:list|str=None,
            head_offset_to_keep:int=None,
        ) -> str|None:
        """ Summarize messages to one text """
        index = self.ai_agent.get_work_memory_first_position()
        if index is None:
            return None

        if not messages:
            messages = self.ai_agent.messages[index:]

        if not messages:
            return None

        # print info
        print_step(f"!!! Summarizing context messages for processing: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            return None

        # head_offset_to_keep
        head_offset_to_keep = self.__get_head_offset_to_keep_in_summary(head_offset_to_keep)

        # keep last user message
        last_user_msg = self.last_user_message

        # new messages
        new_messages = messages[:head_offset_to_keep]
        new_messages.append(llm_chat.prompt_ctl.messages[-1]) # add answer(summary) to messages
        if last_user_msg:
            new_messages.append(last_user_msg)
        self.ai_agent.messages = self.ai_agent.messages[:index] + new_messages

        print_step(f"!!! New context messages for processing: msg_len=[{len(self.ai_agent.messages)}]", need_format=False, need_log=True)
        logger.info("new context messages: %s", self.ai_agent.messages)

        return answer

    def is_need_summarize_for_processing(self) -> bool:
        """ the agent is working, it is ai_agent.messages """
        quantity_threshold = self.__get_quantity_threshold()
        if not quantity_threshold:
            return False

        number_list = [23, 27, 29, 31, 37, 41, 43, 47] # min -> max
        if quantity_threshold >= number_list[0]:
            number_list.append(quantity_threshold)
        if quantity_threshold*2 <= number_list[-1]:
            number_list.append(quantity_threshold*2)

        quantity_threshold = max(random.choice(number_list), quantity_threshold)

        if len(self.ai_agent.messages) >= quantity_threshold:
            return True

        return False
