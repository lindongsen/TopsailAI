'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-30
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.prompt_hub.prompt_tool import (
    PromptHubExtractor,
    read_prompt,
)
from .react import AgentStepCall

BASE_PROMPT = read_prompt("work_mode/ReAct.Community.md") + PromptHubExtractor.prompt_extra

# define prompt of ReAct framework
SYSTEM_PROMPT = (
    BASE_PROMPT +

    PromptHubExtractor.prompt_interactive_topsailai +
    read_prompt("work_mode/format/topsailai_ReAct.md")
)

if env_tool.is_use_tool_calls():
    SYSTEM_PROMPT = (
        BASE_PROMPT +
        read_prompt("work_mode/format/topsailai2.md") +
        PromptHubExtractor.prompt_use_tool_calls
    )

AGENT_NAME = "AgentReActCommunity"

__all__ = [
    SYSTEM_PROMPT,
    AGENT_NAME,
    AgentStepCall,
]
