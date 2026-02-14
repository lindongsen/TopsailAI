'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-15
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.ai_base.agent_base import (
    StepCallBase,
)

from . import (
    react,
    plan_and_execute,
    _template,
)

AGENT_TYPE_MAP = {
    "default": react,
    "react": react,
    "plan_and_execute": plan_and_execute,
}


def get_agent_type(agent_type=None) -> _template:
    if agent_type and agent_type in AGENT_TYPE_MAP:
        return AGENT_TYPE_MAP[agent_type]
    agent_type = env_tool.EnvReaderInstance.get("TOPSAILAI_AGENT_TYPE") or "default"
    return AGENT_TYPE_MAP.get(agent_type) or AGENT_TYPE_MAP["default"]

def get_agent_step_call(args:tuple=None, kwargs:dict=None) -> StepCallBase:
    """  get agent type for tool_call """
    agent_module = get_agent_type()
    if args is None:
        args = tuple()
    if not kwargs:
        kwargs = dict()
    return agent_module.AgentStepCall(*args, **kwargs)
