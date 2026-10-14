'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from contextvars import ContextVar
from functools import wraps

from topsailai.ai_base.agent_base import AgentBase

# ai agent object
g_ai_agent = None
_active_ai_agent = ContextVar("instruction_ai_agent", default=None)

def set_ai_agent(agent):
    """ set agent object to global variable """
    if agent and _active_ai_agent.get() is None:
        global g_ai_agent
        g_ai_agent = agent
    return

def get_ai_agent() -> AgentBase:
    """ return a agent object """
    active = _active_ai_agent.get()
    return active if active is not None else g_ai_agent


def bind_instruction_agent(method):
    """Bind inspection to this chat during execution and restore its parent."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        """Reset the exact context token even on nested execution failure."""
        token = _active_ai_agent.set(self.ai_agent)
        try:
            return method(self, *args, **kwargs)
        finally:
            _active_ai_agent.reset(token)
    return wrapped
