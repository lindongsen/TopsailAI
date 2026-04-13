'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-05
  Purpose: ReAct (Reasoning and Acting) framework implementation for AI agents
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.prompt_hub.prompt_tool import PromptHubExtractor
from .tool import (
    StepCallTool,
    ExceptionStepCallEnd,
)

# define prompt of ReAct framework
SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolPrompt
if env_tool.is_use_tool_calls():
    SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolCall

AGENT_NAME = "AgentReAct"


class Step4ReAct(StepCallTool):
    """Implementation of the ReAct (Reasoning and Acting) framework for AI agents"""

    def _execute(self, step:dict, tools:dict, response:list, index:int, rsp_msg_obj=None, **_):
        """
        Execute a single step in the ReAct framework

        This method processes different step types (thought, action, final_answer) and handles
        tool execution, user interaction, and step transitions.

        Args:
            step (dict): Current step information containing 'step_name' and other metadata
            tools (dict): Dictionary of available tools that can be called by the agent
            response (list): List of all steps in the current response
            index (int): Current index in the response list
            rsp_msg_obj: Response message object (optional)
            **_: Additional keyword arguments (ignored)

        Returns:
            None: The method sets internal state variables (self.code, self.user_msg, etc.)
            to control the agent's behavior rather than returning values directly
        """
        try:
            step_name, step = self.pre_execute(
                step=step,
                tools=tools,
                response=response,
                index=index,
                rsp_msg_obj=rsp_msg_obj,
                **_
            )
        except ExceptionStepCallEnd:
            return

        if step_name == 'action':
            result = self.execute_step_action(
                step=step,
                tools=tools,
                rsp_msg_obj=rsp_msg_obj,
            )
            if isinstance(result, Exception):
                result = str(result)
            self.tool_msg = {
                "step_name": "observation",
                "raw_text": result,
            }
            self.code = self.CODE_STEP_FINAL
        elif step_name == "thought":
            self.complete_step_thought(
                response=response
            )
        elif step_name.startswith('final'):
            self.complete_final(
                step=step,
            )
        else:
            self.complete_cannot_handle(
                step_name=step_name,
                step=step,
                tools=tools,
                response=response,
                index=index,
                rsp_msg_obj=rsp_msg_obj,
            )

        return

# set common name
AgentStepCall = Step4ReAct


__all__ = [
    "SYSTEM_PROMPT",
    "AGENT_NAME",
    "AgentStepCall",
]
