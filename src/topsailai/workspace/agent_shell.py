'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-29
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.ai_base.agent_types import react
from topsailai.ai_base.agent_base import AgentRun

from topsailai.workspace.print_tool import ContentDots


def get_agent_chat(system_prompt="", to_dump_messages=False, disabled_tools:list[str]=None):
    """ return a agent object of ReAct mode. """
    env_disabled_tools = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS")
    if env_disabled_tools is None:
        # not config
        env_disabled_tools = disabled_tools
    elif not env_disabled_tools:
        # null of config
        env_disabled_tools = []

    agent = AgentRun(
        react.SYSTEM_PROMPT + "\n---\n" + system_prompt,
        tools=None,
        agent_name=react.AGENT_NAME,
        excluded_tool_kits=env_disabled_tools if isinstance(env_disabled_tools, list) else disabled_tools,
    )

    if env_tool.is_debug_mode():
        if env_tool.EnvReaderInstance.check_bool("LLM_RESPONSE_STREAM"):
            agent.llm_model.content_senders.append(ContentDots())

    # set flags
    if to_dump_messages:
        agent.flag_dump_messages = True

    return agent
