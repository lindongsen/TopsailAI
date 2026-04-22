'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.utils import (
    env_tool,
    json_tool,
)
from topsailai.tools.base.common import get_tools_for_chat
from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent

def get_system_prompt() -> str:
    """
    Print system prompt
    """
    agent = get_ai_agent()
    if agent:
        print(agent.messages[0]["content"])
    return

def get_env_prompt() -> str:
    """
    Print env prompt
    """
    agent = get_ai_agent()
    if agent:
        print(agent.messages[1]["content"])
    return

def get_tool_prompt() -> str:
    """
    Print tool prompt
    """
    agent = get_ai_agent()
    if agent:
        if env_tool.is_use_tool_calls():
            content = get_tools_for_chat(agent.available_tools)
            content = json_tool.safe_json_dump(content, indent=2)
            print(content)
            print("\n---\n")
        print(agent.messages[2]["content"])

    return

def get_tools() -> list[str]:
    """
    Print tools
    """
    agent = get_ai_agent()
    if agent:
        print(sorted(list(agent.available_tools.keys())))
    return

def set_llm(llm:str) -> str:
    """
    Change LLM

    Args:
        llm (str): model name
    """
    agent = get_ai_agent()
    if not agent:
        return

    old_model_name = agent.llm_model.model_name
    agent.llm_model.model_name = llm
    result = f"old={old_model_name}, new={llm}, now={agent.llm_model.model_name}"
    return result

def get_llm() -> str:
    """
    Print LLM name
    """
    agent = get_ai_agent()
    if not agent:
        return

    llm = agent.llm_model.model_name
    return llm


INSTRUCTIONS = dict(
    system_prompt=get_system_prompt,
    env_prompt = get_env_prompt,
    tool_prompt=get_tool_prompt,
    tools=get_tools,
    set_llm=set_llm,
    llm=get_llm,
)
