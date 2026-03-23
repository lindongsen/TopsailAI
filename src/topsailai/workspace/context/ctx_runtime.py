'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
    UserSession -> ctx_runtime_data.messages -> user chats to agent
    AgentSession -> ctx_runtime_aiagent.messages -> agent chats to LLM
'''

import random

from topsailai.logger import logger
from topsailai.ai_base.constants import ROLE_USER
from topsailai.ai_base.agent_base import AgentBase
from topsailai.tools.agent_tool import (
    subprocess_agent_memory_as_story,
)
from topsailai.tools import (
    story_tool,
    env_tool,
)
from topsailai.context import ctx_manager
from topsailai.utils import (
    json_tool,
)
from topsailai.utils.print_tool import print_step
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.print_tool import (
    print_context_messages,
    print_raw_messages,
)
from topsailai.workspace.llm_shell import get_llm_chat


class ContextRuntimeData(object):
    """ context manager for runtime """
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

    def add_session_message(self, role:str, message:str):
        """ add a message to session """
        msg_dict = {"role": role, "content": message}

        self.append_message(msg_dict)

        if self.session_id:
            ctx_manager.add_session_message(
                self.session_id, msg_dict,
            )

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

    def _summarize_messages(self, messages):
        """ summarize messages to one text.

        return (llm_chat, answer)
        """
        assert messages, "null of messages"
        one_msg = messages if isinstance(messages, str) else json_tool.json_dump(messages)
        enhanced_prompt = "\n---\nYou MUST focus on the Human's intention\n---\n\n"

        llm_chat = get_llm_chat(
            message=enhanced_prompt+one_msg,
            session_id="",
            system_prompt=story_tool.PROMPT_SUMMARY,

            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        answer = llm_chat.chat(need_print=False)

        return (llm_chat, answer)

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

    def is_need_summarize_for_processed(self) -> bool:
        """ the processed Q&A messages, it is ctx_runtime_data.messages """
        quantity_threshold = self.__get_quantity_threshold()
        if not quantity_threshold:
            return False

        if len(self.messages) >= quantity_threshold:
            return True

        return False

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


class ContextRuntimeUtils(object):
    """ common utils """
    def __init__(self, ctx_runtime_data:ContextRuntimeData):
        self.ctx_runtime_data = ctx_runtime_data
        return

    @property
    def session_id(self) -> str:
        return self.ctx_runtime_data.session_id

    @property
    def messages(self) -> list:
        return self.ctx_runtime_data.messages

    @property
    def ai_agent(self) -> AgentBase:
        return self.ctx_runtime_data.ai_agent

class ContextRuntimeAIAgent(ContextRuntimeUtils):
    """ reference to AIAgent """

    def add_session_message(self, message:dict=None):
        """
        Add the latest agent message to the session context and local messages list.
        """
        if not message:
            if self.ai_agent.messages:
                message = self.ai_agent.messages[-1]

        assert message

        if self.session_id:
            ctx_manager.add_session_message(self.session_id, message)

        self.ctx_runtime_data.append_message(message)

        return

    def add_runtime_messages(self):
        """ add runtime_data.messages to ai_agent.messages """
        if self.messages:
            self.ai_agent.messages += self.messages
        return

class ContextRuntimeInstructions(ContextRuntimeUtils):
    """ instrunctions for human """

    @property
    def instructions(self) -> dict:
        """ get instructions """
        return dict(
            clear=self.clear,
            story=self.story,
            history=self.history,
            history2=self.history2,
            delete=self.delete,
            summarize=self.summarize,
        )

    def clear(self):
        """
        Clear context messages if no session ID exists.
        Shows message if session ID prevents clearing.
        """
        session_id = self.session_id

        if session_id:
            print(f"Context cannot be clear due to exist session_id({session_id})")
        else:
            # clear context messages
            self.messages.clear()
            print("Context already is clear")
        return

    def story(self):
        """
        Save context messages to a new story using subprocess.
        Only works if there are existing messages in the session.
        """
        if not self.messages:
            return
        pid = subprocess_agent_memory_as_story(self.messages)
        print(f"The history messages will be save to a new story, pid=[{pid}], msg_len=[{len(self.messages)}]")
        return

    def history(self, offset:str=""):
        """
        Display the history of messages for the current session.
        Shows separator line and all context messages if available.

        Args:
            offset:
              - usage1: number, e.g. 7 is 7:-7;
              - usage2: 'head_num:tail_num', e.g 5:-3
        """
        session_id = self.session_id

        print(f"\n\n{SPLIT_LINE}")
        print(f"Show history messages {session_id}")
        if self.messages:
            head_offset = None
            tail_offset = None
            if offset:
                try:
                    if ':' in offset:
                        head_offset, tail_offset = offset.split(':', 1)
                        head_offset = int(head_offset)
                        tail_offset = int(tail_offset)
                    else:
                        head_offset = tail_offset = int(offset)
                        tail_offset = -tail_offset
                except Exception:
                    pass

            _msgs = self.messages if head_offset is None else self.messages[head_offset:tail_offset]
            print_context_messages(_msgs)

        return

    def history2(self):
        """ print raw history messages """
        session_id = self.session_id

        print(f"\n\n{SPLIT_LINE}")
        print(f"Show raw history messages {session_id}")
        raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
        if raw_msgs:
            print_raw_messages(raw_msgs)
        return

    def delete(self, index:int):
        """
        delete one message

        Args:
          index: int
        """
        session_id = self.session_id

        index = int(index)
        assert index > 0 and index <= len(self.messages), "nothing can be deleted"
        index -= 1
        raw_msgs = ctx_manager.get_messages_by_session(session_id, for_raw=True)
        index_msg = raw_msgs[index]
        index_msg_id = index_msg.msg_id
        ctx_manager.del_session_messages(session_id, [index_msg_id])
        self.ctx_runtime_data.reset_messages()
        self.history()
        return

    def summarize(self, head_offset_to_keep:int=1):
        """Summarize context messages for current session.

        Args:
            head_offset_to_keep (int): default is 1
        """
        self.ctx_runtime_data.summarize_messages_for_processed(
            head_offset_to_keep=head_offset_to_keep,
            need_interactive=True,
        )
        self.history()
        return
