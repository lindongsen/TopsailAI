'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-06
  Purpose:
'''

from topsailai.utils import (
    env_tool,
)
from topsailai.prompt_hub.prompt_tool import PromptHubExtractor, read_prompt
from .tool import (
    StepCallTool,
    ExceptionStepCallEnd,
)

# define prompt of Plan-And-Execute framework

# work-mode PlanAndExecute
prompt_mode_PlanAndExecute_base = (
    read_prompt("work_mode/PlanAndExecute.md")
    + PromptHubExtractor.prompt_common
    + PromptHubExtractor.prompt_task
    + PromptHubExtractor.prompt_extra
)

prompt_mode_PlanAndExecute_toolPrompt = (
    prompt_mode_PlanAndExecute_base

    # place them to tail
    #+ prompt_interactive_json
    #+ read_prompt("work_mode/format/json_ReAct.md")
    + PromptHubExtractor.prompt_interactive_topsailai
    + read_prompt("work_mode/format/topsailai_action.md")
)

prompt_mode_PlanAndExecute_toolCall = (
    prompt_mode_PlanAndExecute_base
    + read_prompt("work_mode/format/topsailai2.md")
    + PromptHubExtractor.prompt_use_tool_calls
)

SYSTEM_PROMPT = prompt_mode_PlanAndExecute_toolPrompt
if env_tool.is_use_tool_calls():
    SYSTEM_PROMPT = prompt_mode_PlanAndExecute_toolCall

AGENT_NAME = "AgentPlanAndExecute"


class StepCall4PlanAndExecute(StepCallTool):
    """ running on Plan-And-Execute mode """
    def _execute(self, step:dict, tools:dict, response:list, index:int, rsp_msg_obj=None, **_):
        """ acting steps """
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

        if step_name.startswith("final"):
            self.complete_final(
                step=step,
            )
        elif step_name in ["inquiry"]:
            self.complete_inquiry()
        elif step_name in ["action"]:
            self.complete_action(
                step=step,
                tools=tools,
                rsp_msg_obj=rsp_msg_obj,
            )
        elif step_name == "thought":
            self.complete_step_thought(
                response=response
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

AgentStepCall = StepCall4PlanAndExecute

__all__ = [
    "SYSTEM_PROMPT",
    "AGENT_NAME",
    "AgentStepCall",
]
