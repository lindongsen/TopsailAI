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
    time_tool,
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
)
from topsailai.workspace.context.agent import (
    ContextRuntimeAIAgent,
)
#from topsailai.workspace.context.agent_tool import (
#    ContextRuntimeAgentTools,
#)
from topsailai.workspace.context.instruction import (
    ContextRuntimeInstructions,
)
from topsailai.workspace.hook_instruction import HookInstruction
from topsailai.workspace.plugin_instruction.base.cache import set_ai_agent
from topsailai.workspace import lock_tool


DEFAULT_HEAD_TAIL_OFFSET = 7


class AgentChat(object):
    """AI Agent controller for managing human-agent and agent-LLM conversations.

    This class coordinates the interaction between a human user and an AI agent,
    handling message routing, context management, and session lifecycle.
    """

    def __init__(
            self,
            hook_instruction:HookInstruction,
            ctx_rt_aiagent:ContextRuntimeAIAgent,
            ctx_rt_instruction:ContextRuntimeInstructions,

            session_head_tail_offset:int=DEFAULT_HEAD_TAIL_OFFSET, # cut messages
        ):
        """Initialize the AgentChat controller.

        Args:
            hook_instruction: Hook instruction instance for input handling.
            ctx_rt_aiagent: Context runtime AI agent instance.
            ctx_rt_instruction: Context runtime instructions instance.
            session_head_tail_offset: Number of messages to keep from head and tail
                                      when truncating conversation history. Defaults to 7.
        """
        self.hook_instruction = hook_instruction
        self.ctx_rt_aiagent = ctx_rt_aiagent
        self.ctx_rt_instruction = ctx_rt_instruction
        ctx_runtime_data = ctx_rt_aiagent.ctx_runtime_data
        self.ai_agent = ctx_rt_aiagent.ai_agent

        self.first_message = None
        self.last_message = None

        set_ai_agent(self.ai_agent)

        # hook(self)
        self.hooks_pre_run = []
        self.hooks_for_final_answer = []

        if env_tool.EnvReaderInstance.get("TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION"):
            def hook_final_summarize_into_session(_) -> None:
                """ summarize messages of agent2llm, save summary content to session of user2agent """
                summary_content = ctx_runtime_data.summarize_messages_for_processing()
                if summary_content:
                    ctx_runtime_data.add_session_message(ROLE_ASSISTANT, summary_content)
                return
            self.hooks_for_final_answer.append(hook_final_summarize_into_session)

        ##########################################################################################
        # Hook Agent
        ##########################################################################################

        def hook_after_init_prompt(_ai_agent):
            """Hook function called after agent prompt initialization.

            Adds existing session messages to the agent's message history.
            Truncates messages if session_head_tail_offset is configured.

            Args:
                _ai_agent: The agent instance to operate on.
            """
            ctx_runtime_data.reset_messages()

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
            """Hook function called after a new session is created.

            Adds the initial session message to the context for tracking.

            Args:
                _ai_agent: The agent instance to operate on.
            """
            ctx_rt_aiagent.add_session_message()
            return

        def hook_summarize_messages(_ai_agent):
            """Summarize context messages to reduce token usage.

            Checks if message summarization is needed for either processed Q&A messages
            or currently processing agent messages, and performs summarization if required.

            Args:
                _ai_agent: The agent instance to operate on.
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
    def agent_name(self) -> str:
        """Get the name of the AI agent.

        Returns:
            str: The agent's name string.
        """
        return self.ai_agent.agent_name

    @property
    def messages(self) -> list:
        """Get the current conversation messages.

        Returns:
            list: List of message dictionaries in the conversation.
        """
        return self.ai_agent.messages

    @property
    def ctx_runtime_data(self) -> ContextRuntimeData:
        """Get the context runtime data instance.

        Returns:
            ContextRuntimeData: The runtime data object containing session context.
        """
        return self.ctx_rt_aiagent.ctx_runtime_data

    def call_hooks_pre_run(self):
        """Execute all pre-run hooks registered in the hooks_pre_run list.

        Iterates through each registered hook function and executes it with
        the current AgentChat instance as the argument. Any exceptions raised
        by hooks are logged but do not stop execution of remaining hooks.
        """
        for hook in self.hooks_pre_run:
            try:
                hook(self)
            except Exception as e:
                logger.exception("call hook_pre_run failed [%s]: %s", hook, e)
                # continue
        return

    def call_hook_for_final_answer(self):
        """
        Iterates through each registered hook function and executes it with
        the current AgentChat instance as the argument. Any exceptions raised
        by hooks are logged but do not stop execution of remaining hooks.
        """
        for hook in self.hooks_for_final_answer:
            try:
                hook(self)
            except Exception as e:
                logger.exception("call hook_for_final_answer failed [%s]: %s", hook, e)
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
            need_symbol_for_answer=None,
            only_save_final:bool=False,
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

        # show session messages
        if env_tool.is_interactive_mode():
            self.ctx_rt_instruction.ctx_history()

        if message is None:
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

            # run
            start_time = int(time.time())
            try:
                with ctxm_tool() as data:
                    # it need session lock but lock failed
                    if need_session_lock and data.get("session_id") and not data.get("fp"):
                        print(data.get("msg"))
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

    def hook_build_answer(self, answer:str, need_symbol:bool=False) -> str:
        """Build and format the final answer string.

        Optionally prepends a symbol to the answer based on configuration.
        The symbol is determined by environment variable TOPSAILAI_SYMBOL_STARTSWITH_ANSWER
        or defaults to "From '{agent_name}':\n".

        Args:
            answer: The raw answer string from the agent.
            need_symbol: Whether to prepend a symbol. Defaults to False.

        Returns:
            str: The formatted answer string.
        """
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
        """Perform post-processing actions on the answer.

        Currently handles saving the answer to a file if the environment variable
        TOPSAILAI_SAVE_RESULT_TO_FILE is set.

        Args:
            answer: The answer string to process.
        """
        if not answer:
            return

        # save answer to file
        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

        return


def get_ai_agent(system_prompt:str="", to_dump_messages:bool=False, disabled_tools:list[str]=None, agent_type=None):
    """Create and return an AI agent instance in ReAct mode.

    Initializes an AgentRun instance with the specified configuration.
    The agent uses ReAct (Reasoning + Acting) prompting strategy.

    Args:
        system_prompt: Additional system prompt to prepend to the agent's prompt.
        to_dump_messages: Whether to enable message dumping for debugging.
        disabled_tools: List of tool names to exclude from the agent.
        agent_type: Type of agent to create. Defaults to configuration or ReAct.

    Returns:
        AgentRun: An initialized AI agent instance.
    """
    env_disabled_tools = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS")
    if env_disabled_tools is None:
        # not config
        env_disabled_tools = disabled_tools
    elif not env_disabled_tools:
        # null of config
        env_disabled_tools = []

    agent_type_name = agent_type
    agent_type = get_agent_type(agent_type)
    agent = AgentRun(
        agent_type.SYSTEM_PROMPT + "\n---\n" + system_prompt,
        tools=None,
        agent_name=os.getenv("TOPSAILAI_AGENT_NAME") or agent_type.AGENT_NAME,
        excluded_tool_kits=env_disabled_tools if isinstance(env_disabled_tools, list) else disabled_tools,
    )
    agent.agent_type = agent_type_name or agent_type.AGENT_NAME

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

        need_print_session:bool=None,
        need_input_message:bool=True,
    ) -> AgentChat:
    """Create and return an AgentChat instance with all required components.

    This is the main factory function for creating a complete chat session.
    It initializes all necessary components including context runtime, AI agent,
    instructions, and hooks.

    Args:
        system_prompt: Additional system prompt for the agent.
        to_dump_messages: Whether to enable message dumping for debugging.
        disabled_tools: List of tool names to exclude from the agent.
        agent_type: Type of agent to create.
        agent_name: Name to assign to the agent.
        session_id: Session identifier for context tracking.
        message: Initial message to process.
        session_head_tail_offset: Number of messages to keep from head/tail.
        need_print_session: Whether to print session information.
        need_input_message: Whether to prompt for input when needed.

    Returns:
        AgentChat: A fully initialized AgentChat instance ready for conversation.
    """
    if need_print_session is None:
        if env_tool.is_debug_mode():
            need_print_session = False
        else:
            need_print_session = True

    if not env_tool.is_interactive_mode():
        need_print_session = False
        need_input_message = False

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

    # context runtime xxx
    ctx_runtime_data = ContextRuntimeData()
    ctx_rt_aiagent = ContextRuntimeAIAgent(ctx_runtime_data)
    ctx_rt_instruction = ContextRuntimeInstructions(ctx_runtime_data)

    # agent tools
    # ctx_rt_aiagent_tools = ContextRuntimeAgentTools(ctx_runtime_data)

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

        ctx_runtime_data.init(session_id, ai_agent=None)
        if not ctx_runtime_data.messages and not ctx_manager.exists_session(session_id):
            if not message:
                message = get_message(hook_instruction, need_input=need_input_message)
            ctx_manager.create_session(session_id, task=message[:100])

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

    # context runtime is ready
    ctx_runtime_data.init(session_id, ai_agent)

    ##########################################################################################
    # Hook Instruction
    ##########################################################################################
    hook_instruction.load_instructions(ctx_rt_instruction.instructions)

    # print sth.
    if need_print_session and session_id:
        ctx_rt_instruction.ctx_history()

    # agent chat
    agent_chat = AgentChat(
        hook_instruction=hook_instruction,
        ctx_rt_aiagent=ctx_rt_aiagent,
        ctx_rt_instruction=ctx_rt_instruction,

        session_head_tail_offset=session_head_tail_offset,
    )

    agent_chat.first_message = message

    return agent_chat
