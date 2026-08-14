'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-05
  Purpose: ReAct (Reasoning and Acting) framework implementation for AI agents
'''

from topsailai.utils import (
    env_tool,
    print_tool,
)
from topsailai.prompt_hub.prompt_tool import PromptHubExtractor
from .tool import (
    StepCallTool,
    ExceptionStepCallEnd,
)
from topsailai.ai_base.constants import STEP_NAME_THOUGHT
from topsailai.context import thought_line_pattern

# define prompt of ReAct framework
SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolPrompt
if env_tool.is_use_tool_calls():
    SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolCall

AGENT_NAME = "AgentReAct"


class Step4ReAct(StepCallTool):
    """Implementation of the ReAct (Reasoning and Acting) framework for AI agents"""

    def __format_action_result(self, result):
        return {
            "step_name": "observation",
            "raw_text": result,
        }

    def _execute(self, step: dict, tools: dict, response: list, index: int, rsp_msg_obj=None, **_):
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
            self.complete_action(
                func_formatter_result=self.__format_action_result,
                step=step,
                tools=tools,
                rsp_msg_obj=rsp_msg_obj,
                **_
            )
        elif step_name == "thought":
            try:
                thought_line_pattern.evaluate_and_maybe_inject(
                    raw_text=str(step.get("raw_text", "")),
                    step_type="thought",
                )
            except Exception:
                pass
            self.complete_step_thought(response=response)
        elif step_name.startswith('final'):
            # Malformed final/final_answer -> convert back to thought, do not terminate.
            converted = False
            try:
                if thought_line_pattern.is_enabled():
                    converted = thought_line_pattern.evaluate_and_maybe_inject(
                        raw_text=str(step.get("raw_text", "")),
                        step_type="final_answer",
                        on_warning=print_tool.print_warning,
                    )
            except Exception:
                converted = False
            if converted:
                # Actually change the step type to thought per requirement.
                step["step_name"] = STEP_NAME_THOUGHT
                return  # Do NOT call complete_final; no CODE_TASK_FINAL -> next round.
            self.complete_final(step=step)
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
