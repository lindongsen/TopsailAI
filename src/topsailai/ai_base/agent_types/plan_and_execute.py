'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-06
  Purpose:
'''

from topsailai.utils.thread_tool import (
    is_main_thread,
)
from topsailai.prompt_hub.prompt_tool import PromptHubExtractor
from topsailai.ai_base.agent_base import (
    StepCallBase,
)

# define prompt of Plan-And-Execute framework
SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_PlanAndExecute

AGENT_NAME = "AgentPlanAndExecute"


class StepCall4PlanAndExecute(StepCallBase):
    """ running on Plan-And-Execute mode """
    def _execute(self, step:dict, tools:dict, response:list, index:int, **_):
        """ acting steps """
        step_name = step.get("step_name", "")
        raw_text = step.get("raw_text", "")
        tool_call = step.get("tool_call", "")
        tool_args = step.get("tool_args", {})

        if step_name.startswith("final"):
            self.result = raw_text
            self.code = self.CODE_TASK_FINAL
            return

        elif step_name == "task-ask":
            assert is_main_thread()
            # Ask user for more information
            user_reply = input(f">>> LLM: {raw_text}\n>>> Your input: ")
            self.user_msg = {"step_name":"task","raw_text":user_reply}
            self.code = self.CODE_STEP_FINAL
            return

        elif step_name in ["execute-subtask", "action"]:
            if tool_call in tools:
                tool_func = tools[tool_call]
                result = tool_func(**tool_args)
                self.tool_msg = result
                self.code = self.CODE_STEP_FINAL
                return
            else:
                self.result = (f"Unknown tool call {tool_call}.")
                self.code = self.CODE_TASK_FAILED
                return

        return
