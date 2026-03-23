'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-29
  Purpose:
  Context:
    1. ai_agent.messages: Save the context message that is currently being processed
    2. ctx_runtime_data.messages: Save the processed Q&A messages
'''

import os
import time

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    file_tool,
    thread_local_tool,
)
from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
)
from topsailai.ai_base.agent_types import (
    get_agent_type,
    get_agent_step_call,
    exception as agent_exception,
)
from topsailai.ai_base.agent_base import AgentRun
from topsailai.context import ctx_manager
from topsailai.workspace.print_tool import ContentDots
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
    SPLIT_LINE,
)
from topsailai.workspace.context.ctx_runtime import (
    ContextRuntimeData,
    ContextRuntimeAIAgent,
    ContextRuntimeInstructions,
)
from topsailai.workspace.hook_instruction import HookInstruction


DEFAULT_HEAD_TAIL_OFFSET = 7


class AgentChat(object):
    """ AI Agent controller, Human chats with Agent, Agent chats with LLM """
    def __init__(
            self,
            hook_instruction:HookInstruction,
            ctx_rt_aiagent:ContextRuntimeAIAgent,
            ctx_rt_instruction:ContextRuntimeInstructions,

            session_head_tail_offset:int=DEFAULT_HEAD_TAIL_OFFSET, # cut messages
        ):
        self.hook_instruction = hook_instruction
        self.ctx_rt_aiagent = ctx_rt_aiagent
        self.ctx_rt_instruction = ctx_rt_instruction

        self.ai_agent = ctx_rt_aiagent.ai_agent

        self.first_message = None
        self.last_message = None

        # hook(self)
        self.hooks_pre_run = []

        ctx_runtime_data = ctx_rt_aiagent.ctx_runtime_data

        ##########################################################################################
        # Hook Agent
        ##########################################################################################

        def hook_after_init_prompt(_ai_agent):
            """
            Hook function called after agent prompt initialization.
            Adds existing session messages to the agent's message history.

            Args:
                _ai_agent: The agent instance
            """
            # cut messages
            if session_head_tail_offset and ctx_runtime_data.messages:
                new_messages = ctx_manager.cut_messages(
                    ctx_runtime_data.messages,
                    session_head_tail_offset,
                )
                if new_messages is not ctx_runtime_data.messages or \
                    len(new_messages) != len(ctx_runtime_data.messages) or \
                    new_messages[-1] != ctx_runtime_data.messages[-1] or \
                        new_messages[0] != ctx_runtime_data.messages[0]:
                    ctx_runtime_data.set_messages(new_messages)

            # add messages to agent
            ctx_rt_aiagent.add_runtime_messages()

            return

        def hook_after_new_session(_ai_agent):
            """
            Hook function called after a new session is created.
            Adds the initial session message to the context.

            Args:
                _ai_agent: The agent instance
            """
            ctx_rt_aiagent.add_session_message()
            return

        def hook_summarize_messages(_ai_agent):
            """Summarize context messages

            Args:
                _ai_agent: agent instance
            """

            # the processed Q&A messages
            if ctx_runtime_data.is_need_summarize_for_processed():
                ctx_runtime_data.summarize_messages_for_processed()

            # the processing agent messages
            if ctx_runtime_data.is_need_summarize_for_processing():
                ctx_runtime_data.summarize_messages_for_processing()

            return

        # add hooks
        self.ai_agent.hooks_after_init_prompt.append(hook_after_init_prompt)
        self.ai_agent.hooks_after_new_session.append(hook_after_new_session)
        self.ai_agent.hooks_pre_chat.append(hook_summarize_messages)

        return

    @property
    def agent_name(self):
        return self.ai_agent.agent_name

    @property
    def messages(self):
        return self.ai_agent.messages

    @property
    def ctx_runtime_data(self):
        return self.ctx_rt_aiagent.ctx_runtime_data

    def call_hooks_pre_run(self):
        """ call hooks for pre-run """
        for hook in self.hooks_pre_run:
            try:
                hook(self)
            except Exception as e:
                logger.exception("call hook_pre_run failed [%s]: %s", hook, e)
                # continue
        return

    def run(
            self,
            message:str=None,
            times:int=0,

            func_build_message=None,
            func_print_pre_input_message=None,

            need_save_answer:bool=True,
            need_confirm_abort:bool=True,
            need_interactive:bool=True,
            need_symbol_for_answer=False,
            only_save_final:bool=False,
        ) -> str:
        """ run agent.
        :message: if it is none, get message; if it is null string, continue.
        """

        self.call_hooks_pre_run()

        if not func_print_pre_input_message:
            # noop
            func_print_pre_input_message = lambda *args, **kwargs: None

        # first message
        if not message:
            if self.first_message:
                message = self.first_message

        if message is None:
            func_print_pre_input_message()
            message = get_message(self.hook_instruction)

        if not self.first_message:
            self.first_message = message

        # variables
        # up_time = int(time.time())
        answer = ""
        curr_count = 0

        # start
        while True:
            # reset answer to null string
            answer = ""

            curr_count += 1

            # build message
            if message and func_build_message:
                message = func_build_message(
                    message=message,
                    curr_count=curr_count,
                )

            # run
            start_time = int(time.time())
            try:
                answer = self.ai_agent.run(
                    get_agent_step_call(
                        args=(need_interactive,),
                        agent_type=self.ai_agent.agent_type,
                    ),
                    message,
                )
            except agent_exception.AgentEndProcess:
                self.last_message = self.messages[-1]
            except (KeyboardInterrupt, EOFError):
                answer = "failed due to abort by Human"
                if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                    break

            if answer:
                answer = self.hook_build_answer(
                    answer,
                    need_symbol=need_symbol_for_answer,
                )
                if need_save_answer:
                    if only_save_final:
                        self.ctx_runtime_data.add_session_message(ROLE_ASSISTANT, answer)
                    else:
                        self.ctx_rt_aiagent.add_session_message()
                self.last_message = answer

            # check times
            if times > 0 and curr_count >= times:
                break

            self.ctx_runtime_data.reset_messages()
            self.ctx_rt_instruction.history()

            # end time
            end_time = int(time.time())

            if not env_tool.is_debug_mode():
                print()
                print(">>> answer:")
                print(answer)

            print()
            print(SPLIT_LINE)
            print(f"The manager have scheduled tasks [{curr_count}] times")
            print(f"session: {self.ctx_runtime_data.session_id}")
            print(f"elapsed_time: {end_time-start_time}")

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

    def hook_build_answer(self, answer:str, need_symbol:bool=False) -> str:
        """ build new answer """
        if not answer:
            return answer

        if need_symbol:
            # symbol
            symbol_start = os.getenv("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER")
            if not symbol_start and self.agent_name:
                symbol_start = f"From '{self.agent_name}':\n"
            if symbol_start and symbol_start not in answer[:len(symbol_start)+17]:
                answer = symbol_start + answer

        return answer

    def hook_for_answer(self, answer:str):
        """ do sth. for answer """
        if not answer:
            return

        # save answer to file
        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

        return


def get_ai_agent(system_prompt="", to_dump_messages=False, disabled_tools:list[str]=None, agent_type=None):
    """ return a agent object of ReAct mode. """
    env_disabled_tools = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS")
    if env_disabled_tools is None:
        # not config
        env_disabled_tools = disabled_tools
    elif not env_disabled_tools:
        # null of config
        env_disabled_tools = []

    agent_type = get_agent_type(agent_type)
    agent = AgentRun(
        agent_type.SYSTEM_PROMPT + "\n---\n" + system_prompt,
        tools=None,
        agent_name=os.getenv("TOPSAILAI_AGENT_NAME") or agent_type.AGENT_NAME,
        excluded_tool_kits=env_disabled_tools if isinstance(env_disabled_tools, list) else disabled_tools,
    )
    agent.agent_type = agent_type

    if env_tool.is_debug_mode():
        if env_tool.EnvReaderInstance.check_bool("LLM_RESPONSE_STREAM"):
            agent.llm_model.content_senders.append(ContentDots())

    # set flags
    if to_dump_messages:
        agent.flag_dump_messages = True

    return agent

def get_agent_chat(
        system_prompt:str="",
        to_dump_messages:bool=False,
        disabled_tools:list[str]=None,
        agent_type:str=None,

        agent_name:str=None,
        session_id:str=None,
        message:str=None,

        session_head_tail_offset:int=DEFAULT_HEAD_TAIL_OFFSET, # cut messages

        need_print_session:bool=True,
        need_input_message:bool=True,
    ) -> AgentChat:
    """ get an instance of AgentChat """
    # set agent name to thread local
    if agent_name:
        thread_local_tool.set_thread_var(thread_local_tool.KEY_AGENT_NAME, agent_name)
    if session_id:
        thread_local_tool.set_thread_name(session_id)

    # system prompt
    if not system_prompt:
        env_sys_prompt = os.getenv("SYSTEM_PROMPT")
        _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)
        if sys_prompt_content:
            system_prompt = sys_prompt_content

    # ai agent
    ai_agent = get_ai_agent(
        system_prompt=system_prompt,
        to_dump_messages=to_dump_messages,
        disabled_tools=disabled_tools,
        agent_type=agent_type,
    )

    if agent_name:
        ai_agent.agent_name = agent_name


    # llm model
    llm_model = ai_agent.llm_model
    llm_model.max_tokens = max(3000, llm_model.max_tokens)
    llm_model.temperature = min(0.97, llm_model.temperature)

    # context runtime data
    ctx_runtime_data = ContextRuntimeData()
    ctx_runtime_data.init(session_id, ai_agent)

    # instructions
    hook_instruction = HookInstruction()

    # message
    if not message:
        # from env
        message = os.getenv("TOPSAILAI_TASK")
        os.environ["TOPSAILAI_TASK"] = "" # only once
        _, message_content = file_tool.get_file_content_fuzzy(message)
        if message_content:
            message = message_content

    if not message:
        message = ""

    message_from_args = ""
    if not need_input_message:
        message_from_args = get_message(need_input=need_input_message)

    if message_from_args:
        message = message_from_args + "\n" + message

    # session
    if session_id is None:
        session_id = os.getenv("SESSION_ID")

    if session_id:
        thread_local_tool.set_thread_name(session_id)
        os.environ["SESSION_ID"] = session_id

        # basic info
        if need_print_session:
            print(f"session_id: {session_id}")

        ctx_runtime_data.init(session_id, ai_agent=ai_agent)
        if not ctx_runtime_data.messages:
            if not message:
                message = get_message(hook_instruction, need_input=need_input_message)
            ctx_manager.create_session(session_id, task=message[:100])

    # context runtime xxx
    ctx_rt_aiagent = ContextRuntimeAIAgent(ctx_runtime_data)
    ctx_rt_instruction = ContextRuntimeInstructions(ctx_runtime_data)

    ##########################################################################################
    # Hook Instruction
    ##########################################################################################
    hook_instruction.load_instructions(ctx_rt_instruction.instructions)

    # print sth.
    if need_print_session and session_id:
        ctx_rt_instruction.history()

    # agent chat
    agent_chat = AgentChat(
        hook_instruction=hook_instruction,
        ctx_rt_aiagent=ctx_rt_aiagent,
        ctx_rt_instruction=ctx_rt_instruction,

        session_head_tail_offset=session_head_tail_offset,
    )

    agent_chat.first_message = message

    return agent_chat
