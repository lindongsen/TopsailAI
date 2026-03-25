'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

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
        print(agent.messages[2]["content"])
    return


INSTRUCTIONS = dict(
    system_prompt=get_system_prompt,
    env_prompt = get_env_prompt,
    tool_prompt=get_tool_prompt,
)
