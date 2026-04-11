'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-29
  Purpose:
  Context:
    1. ai_agent.messages: Save the context message that is currently being processed
    2. ctx_runtime_data.messages: Save the processed Q&A messages
'''

import time

from topsailai.utils import (
    env_tool,
    time_tool,
)
from topsailai.utils.print_tool import (
    print_step,
)
from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
)
from topsailai.ai_base.agent_types import (
    get_agent_step_call,
    exception as agent_exception,
)
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
    SPLIT_LINE,
)
from topsailai.workspace import lock_tool
from topsailai.workspace.agent.agent_chat_base import AgentChatBase
from topsailai.workspace.task import task_tool


class AgentChat(AgentChatBase):
    def run(
            self,
            message:str=None,
            times:int=0,

            func_build_message=None,
            func_print_pre_input_message=None,

            need_save_answer:bool=True,
            need_confirm_abort:bool=True,
            need_interactive:bool=True,
            need_symbol_for_answer=None,
            only_save_final:bool=False,
            task_id=None,
        ) -> str:
        """Run the agent chat session.

        Executes the main conversation loop between human and AI agent.
        Handles message input, agent execution, response processing, and
        session management.

        Args:
            message: Initial message to send to the agent. If None, prompts for input.
            times: Maximum number of conversation turns. 0 means unlimited.
            func_build_message: Optional callback to transform message before sending.
            func_print_pre_input_message: Optional callback to execute before prompting for input.
            need_save_answer: Whether to save answers to context. Defaults to True.
            need_confirm_abort: Whether to confirm before aborting on keyboard interrupt.
            need_interactive: Whether to use interactive mode. Defaults to True.
            need_symbol_for_answer: Whether to prepend symbol to answer. Defaults to False.
            only_save_final: If True, only save the final answer to session history.

        Returns:
            str: The final answer from the AI agent.
        """
        self.call_hooks_pre_run()

        if not func_print_pre_input_message or not env_tool.is_interactive_mode():
            # noop
            func_print_pre_input_message = lambda *args, **kwargs: None

        # first message
        if not message:
            if self.first_message:
                message = self.first_message

        if message is None:
            # show session messages
            if env_tool.is_interactive_mode():
                self.ctx_rt_instruction.ctx_history()

            func_print_pre_input_message()
            message = get_message(self.hook_instruction, need_input=env_tool.is_interactive_mode())

        if not self.first_message:
            self.first_message = message

        # env
        if need_symbol_for_answer is None:
            need_symbol_for_answer = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", False)

        need_session_lock = env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_ENABLE_SESSION_LOCK", False,
        )
        ctxm_tool = lock_tool.ctxm_void
        if need_session_lock:
            ctxm_tool = lock_tool.ctxm_try_session_lock

        # task
        task = None
        if times == 1:
            if not task_id:
                task_id = env_tool.EnvReaderInstance.get("TOPSAILAI_TASK_ID")
            if task_id:
                task = task_tool.TaskUtil(task_id)
                task.session_messages = self.ctx_runtime_data.messages

        # variables
        # up_time = int(time.time())
        answer = ""
        curr_count = 0

        # start
        while True:
            flag_abort = False
            # reset answer to null string
            answer = ""

            curr_count += 1

            # build message
            if message and func_build_message:
                message = func_build_message(
                    message=message,
                    curr_count=curr_count,
                )

            # task
            if task:
                if message:
                    task.task_content = message
                    message = task.manifest + message

            # run
            start_time = int(time.time())
            try:
                with (
                    task_tool.ctxm_process_task(task),
                    ctxm_tool() as data
                    ):
                    # it need session lock but lock failed
                    if need_session_lock and data.get("session_id") and not data.get("fp"):
                        print_step(data.get("msg"), need_format=False, need_log=True)
                        return data.get("msg")

                    # lock session ok, refresh session messages in hook_after_init_prompt
                    #if fp:
                        # refresh session messages
                        #self.ctx_runtime_data.reset_messages()

                    answer = self.ai_agent.run(
                        get_agent_step_call(
                            args=(need_interactive,),
                            agent_type=self.ai_agent.agent_type,
                        ),
                        message,
                    )

                    # task
                    if task:
                        task.result = answer

            except agent_exception.AgentEndProcess:
                self.last_message = self.messages[-1]
            except (KeyboardInterrupt, EOFError):
                flag_abort = True
                answer = "failed due to abort by Human"
                if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                    break

            if answer:
                answer = self.hook_build_answer(
                    answer,
                    need_symbol=need_symbol_for_answer,
                )

                # task
                if task:
                    answer = task.manifest + answer
                    need_save_answer = True
                    only_save_final = True

                if need_save_answer:
                    if only_save_final:
                        self.ctx_runtime_data.add_session_message(ROLE_ASSISTANT, answer)
                    else:
                        if not flag_abort:
                            self.ctx_rt_aiagent.add_session_message()
                self.last_message = answer

            self.call_hook_for_final_answer()

            # it is not interactive mode
            if not env_tool.is_debug_mode() or not env_tool.is_interactive_mode():
                print(answer)

            # check times
            if times > 0 and curr_count >= times:
                break

            self.ctx_runtime_data.reset_messages()
            if env_tool.is_interactive_mode():
                self.ctx_rt_instruction.ctx_history()

            # end time
            end_time = int(time.time())

            if env_tool.is_interactive_mode() or env_tool.is_debug_mode():
                print()
                print(SPLIT_LINE)
                print(f"[{self.agent_name}] have scheduled tasks [{curr_count}] times")
                print(f"session         : {self.ctx_runtime_data.session_id}")
                print(f"start_time      : {time_tool.parse_time_seconds(start_time)}")
                print(f"end_time(now)   : {time_tool.parse_time_seconds(end_time)}")
                print(f"elapsed_time    : {end_time-start_time}")

            # next time
            func_print_pre_input_message()
            while True:
                message = input_message(hook=self.hook_instruction)
                message = message.strip()
                if message:
                    break

        # hook answer
        self.hook_for_answer(answer)

        return answer
