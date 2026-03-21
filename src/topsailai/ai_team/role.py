'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)


MANAGER_STARTSWITH = "AIManager."
MEMBER_STARTSWITH = "AIMember."


def get_manager_name(manager_name:str=None) -> str:
    """Get the manager name.
    If the manager name is not provided, it will be read from the environment variable "TOPSAIL_TEAM_MANAGER_NAME".
    If the environment variable is not set, it will default to "Manager".
    The manager name will be prefixed with "AIManager." if it does not already start with it.
    """
    if not manager_name:
        manager_name = env_tool.EnvReaderInstance.get("TOPSAIL_TEAM_MANAGER_NAME") \
            or env_tool.EnvReaderInstance.get("TOPSAILAI_AGENT_NAME")

    if not manager_name:
        manager_name = "Manager"

    if not manager_name.startswith(MANAGER_STARTSWITH):
        manager_name = MANAGER_STARTSWITH + manager_name

    return manager_name

def get_member_name(member_name:str=None) -> str:
    """Get the member name.
    If the member name is not provided, it will be read from the environment variable "TOPSAIL_TEAM_MEMBER_NAME".
    If the environment variable is not set, it will default to "Member".
    The member name will be prefixed with "AIMember." if it does not already start with it.
    """
    if not member_name:
        member_name = env_tool.EnvReaderInstance.get("TOPSAIL_TEAM_MEMBER_NAME") \
            or env_tool.EnvReaderInstance.get("TOPSAILAI_AGENT_NAME")

    if not member_name:
        member_name = "Member"

    if not member_name.startswith(MEMBER_STARTSWITH):
        member_name = MEMBER_STARTSWITH + member_name

    return member_name

def get_manager_prompt(agent_name:str=None) -> str:
    """ get prompt for role info """
    agent_name = get_manager_name(agent_name)
    return f"""

---
YOUR ROLE IS Manager, YOUR NAME IS ({agent_name})
---

"""

def get_member_prompt(agent_name:str=None) -> str:
    """ get prompt for role info """
    agent_name = get_member_name(agent_name)
    return f"""

---
YOUR ROLE IS Member, YOUR NAME IS ({agent_name})
---

"""
