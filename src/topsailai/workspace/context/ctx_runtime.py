'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

from topsailai.ai_base.agent_base import AgentBase
from topsailai.tools.agent_tool import (
    subprocess_agent_memory_as_story,
)
from topsailai.context import ctx_manager
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.print_tool import (
    print_context_messages,
    print_raw_messages,
)


class ContextRuntimeData(object):
    """ context manager for runtime """
    def __init__(self):
        self.session_id = ""
        self.messages = []
        self.ai_agent:AgentBase = None

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

    def set_messages(self, value:list):
        """ set new value """
        if not value:
            value = []
        self.messages.clear()
        self.messages += value
        return

    def reset_messages(self):
        """ reset messages to newest """
        if self.session_id:
            messages_from_session = ctx_manager.get_messages_by_session(self.session_id) or []
            self.set_messages(messages_from_session)
        return

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

    def add_session_message(self):
        """
        Add the latest agent message to the session context and local messages list.
        """
        if self.session_id:
            ctx_manager.add_session_message(self.session_id, self.ai_agent.messages[-1])

        self.messages.append(self.ai_agent.messages[-1])
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
