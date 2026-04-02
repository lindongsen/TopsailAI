'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-02
  Purpose:
'''

import os

from topsailai.utils import (
    env_tool,
    file_tool,
    thread_local_tool,
)
from topsailai.ai_base.agent_types import (
    get_agent_type,
)
from topsailai.ai_base.agent_base import AgentRun
from topsailai.context import ctx_manager
from topsailai.workspace.input_tool import (
    get_message,
)
from topsailai.workspace.context.ctx_runtime import (
    ContextRuntimeData,
)
from topsailai.workspace.context.agent import (
    ContextRuntimeAIAgent,
)
from topsailai.workspace.context.instruction import (
    ContextRuntimeInstructions,
)
from topsailai.workspace.hook_instruction import HookInstruction
from topsailai.workspace.print_tool import ContentDots
#from topsailai.workspace.context.agent_tool import (
#    ContextRuntimeAgentTools,
#)
from topsailai.workspace.agent.agent_shell_base import (
    AgentChat,
)


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

        session_head_tail_offset:int=None, # cut messages

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
