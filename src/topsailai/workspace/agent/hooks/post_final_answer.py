'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose:
'''

from topsailai.utils import (
    hook_tool,
)
from topsailai.workspace.agent.agent_chat_base import AgentChatBase


ENV_KEY = "TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER"

def call_scripts(self:AgentChatBase) -> dict:
    """
    Call scripts from environ.

    Args:
        self (AgentChatBase):

    Returns:
        dict: key is script_file, value is result
    """
    return hook_tool.call_hook_scripts(ENV_KEY)


HOOKS = dict(
    call_scripts=call_scripts,
)
