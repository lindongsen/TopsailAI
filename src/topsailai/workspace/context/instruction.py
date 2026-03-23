'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-23
  Purpose:
'''

from topsailai.context import ctx_manager
from topsailai.tools.agent_tool import (
    subprocess_agent_memory_as_story,
)
from topsailai.workspace.input_tool import (
    SPLIT_LINE,
)
from topsailai.workspace.print_tool import (
    print_context_messages,
    print_raw_messages,
)
from topsailai.workspace.context.agent import ContextRuntimeUtils


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
            del_msgs=self.delete_multi,
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
        """delete one message

        Args:
            index (int): Sequence number starting from 1
        """
        assert index > 0 and index <= len(self.messages), "nothing can be deleted"
        index -= 1

        self.ctx_runtime_data.del_session_message(index)

        self.history()
        return

    def delete_multi(self, *indexes:list[int]):
        """delete multiple messages

        Args:
            *indexes (list[int]): Sequence number starting from 1
        """
        new_indexes = []
        # -1
        for index in indexes:
            new_indexes.append(int(index)-1)

        result = self.ctx_runtime_data.del_session_messages(new_indexes)
        # +1
        for i, value in enumerate(result):
            result[i] = value + 1
        print(f"deleted: {result}")
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
