'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
    UserSession -> ctx_runtime_data.messages -> user chats to agent
    AgentSession -> ctx_runtime_aiagent.messages -> agent chats to LLM
'''

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_USER,
    ROLE_SYSTEM,
)

from topsailai.context import ctx_manager
from topsailai.utils import (
    json_tool,
)
from topsailai.utils.print_tool import print_step
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)

from topsailai.workspace.context.agent2llm import (
    ContextRuntimeAgent2LLM,
)


class ContextRuntimeData(ContextRuntimeAgent2LLM):
    """ context manager for runtime

    Variables:
        self.messages: user chats to agent
        self.ai_agent.messages: agent chats to LLM
    """

    ###############################################################
    # User chats to Agent
    ###############################################################

    def add_session_message(self, role:str, message:str):
        """ add a message to session """
        msg_dict = {"role": role, "content": message}

        self.append_message(msg_dict)

        if self.session_id:
            ctx_manager.add_session_message(
                self.session_id, msg_dict,
            )

        return

    def del_session_message(self, index:int):
        """delete a message

        Args:
            index (int): Sequence number starting from 0
        """
        session_id = self.session_id

        index = int(index)
        assert index >= 0 and index < len(self.messages), "nothing can be deleted"

        if session_id:
            raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
            index_msg = raw_msgs[index]
            index_msg_id = index_msg.msg_id
            ctx_manager.del_session_messages(session_id, [index_msg_id])

        del self.messages[index]

        return

    # user chats to agent
    def del_session_messages(self, indexes:list[int]) -> list[int]:
        """delete some messages from session messages.

        Args:
            indexes (list[int]): Sequence number starting from 0

        Returns:
            list[int]: already deleted list
        """
        if not indexes:
            return []

        deleted_list = []

        new_messages = []
        for i, msg in enumerate(self.messages):
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

        self.set_messages(new_messages)

        if self.session_id:
            raw_msgs = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)
            msg_ids = []
            for i in deleted_list:
                msg_ids.append(raw_msgs[i].msg_id)
            if msg_ids:
                ctx_manager.del_session_messages(self.session_id, msg_ids)

        return deleted_list

    def summarize_messages_for_processed(
            self,
            messages:list=None,
            head_offset_to_keep:int=None,
            need_interactive:bool=False,
        ) -> str|None:
        """ Summarize messages to one text """
        if not messages:
            # just the processed Q&A messages for current runtime
            messages = self.messages

        if not messages:
            return None

        # print info
        print_step(f"!!! Summarizing context messages for processed: msg_len=[{len(messages)}]", need_format=False, need_log=True)

        llm_chat, answer = self._summarize_messages(messages)
        if not answer:
            return None

        if need_interactive:
            try:
                print(SPLIT_LINE)
                while True:
                    yn = input(">>> Is this answer acceptable? [yes/no] ").lower().strip()
                    if not yn:
                        continue
                    if yn != "yes":
                        return answer
                    break
            except Exception:
                return answer

        # head_offset_to_keep
        head_offset_to_keep = self.__get_head_offset_to_keep_in_summary(head_offset_to_keep)

        if self.session_id:
            raw_messages_from_session = ctx_manager.get_messages_by_session(self.session_id, for_raw=True)

            # keep last user message
            last_user_raw_msg = None
            for raw_msg in reversed(raw_messages_from_session):
                msg_dict = json_tool.json_load(raw_msg.message)
                if msg_dict["role"] == ROLE_USER:
                    last_user_raw_msg = raw_msg
                    break

            # delete history messages
            if raw_messages_from_session:
                for raw_msg in raw_messages_from_session[head_offset_to_keep:]:
                    if last_user_raw_msg and raw_msg.msg_id == last_user_raw_msg.msg_id:
                        continue
                    ctx_manager.del_session_messages(self.session_id, [raw_msg.msg_id])
            else:
                logger.critical("BUG: how did it happend? null of messages from session: [%s]", self.session_id)

            # add answer to session
            ctx_manager.add_session_message(self.session_id, llm_chat.prompt_ctl.messages[-1])

            # reset messages
            self.reset_messages()
        else:
            # keep last user message
            last_user_msg = self.last_user_message

            # new messages
            new_messages = messages[:head_offset_to_keep]
            new_messages.append(llm_chat.prompt_ctl.messages[-1]) # add answer(summary) to messages
            if last_user_msg:
                new_messages.append(last_user_msg)

            self.set_messages(new_messages)

        return answer


    def is_need_summarize_for_processed(self) -> bool:
        """ the processed Q&A messages, it is ctx_runtime_data.messages """
        quantity_threshold = self.__get_quantity_threshold()
        if not quantity_threshold:
            return False

        if len(self.messages) >= quantity_threshold:
            return True

        return False
