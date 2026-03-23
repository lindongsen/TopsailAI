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
    """
    Get the agent type module based on the specified type or environment variable.

    This function resolves the agent type to use for the AI agent. It first checks
    if an explicit agent_type is provided. If not, it falls back to the environment
    variable 'TOPSAILAI_AGENT_TYPE'. If neither is set, it defaults to 'default'.

    Args:
        agent_type (str, optional): The agent type to use. Supported values:
            - "default" or "react": Uses the ReAct agent implementation
            - "plan_and_execute": Uses the Plan-and-Execute agent implementation

    Returns:
        _template: The agent module corresponding to the resolved agent type.

    Raises:
        KeyError: If the agent_type is not found in AGENT_TYPE_MAP, defaults to "default".
    """
    if agent_type and agent_type in AGENT_TYPE_MAP:
        return AGENT_TYPE_MAP[agent_type]
    agent_type = env_tool.EnvReaderInstance.get("TOPSAILAI_AGENT_TYPE") or "default"
    return AGENT_TYPE_MAP.get(agent_type) or AGENT_TYPE_MAP["default"]


def get_agent_step_call(args:tuple=None, kwargs:dict=None, agent_type:str=None) -> StepCallBase:
    """
    Create and return an agent step call instance.

    This function instantiates the appropriate agent step call handler based on
    the specified agent type. It retrieves the agent module and creates an
    instance of its AgentStepCall class with the provided arguments.

    Args:
        args (tuple, optional): Positional arguments to pass to the AgentStepCall
            constructor. Defaults to an empty tuple if not provided.

        kwargs (dict, optional): Keyword arguments to pass to the AgentStepCall
            constructor. Defaults to an empty dictionary if not provided.

        agent_type (str, optional): The type of agent to use. If not provided,
            defaults to the value from environment variable or "default".
            Supported values: "react", "plan_and_execute", "default".

    Returns:
        StepCallBase: An instance of the AgentStepCall class from the
            corresponding agent module.
    """
    agent_module = get_agent_type(agent_type)
    if args is None:
        args = tuple()
    if not kwargs:
        kwargs = dict()
    return agent_module.AgentStepCall(*args, **kwargs)
