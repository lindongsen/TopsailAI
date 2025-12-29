'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-05
  Purpose: ReAct (Reasoning and Acting) framework implementation for AI agents
'''

from topsailai.logger import logger

from topsailai.utils.thread_tool import (
    is_main_thread,
)
from topsailai.utils import (
    env_tool,
)
from topsailai.prompt_hub.prompt_tool import PromptHubExtractor
from topsailai.ai_base.agent_base import (
    StepCallBase,
)


# define prompt of ReAct framework
SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolPrompt
if env_tool.is_use_tool_calls():
    SYSTEM_PROMPT = PromptHubExtractor.prompt_mode_ReAct_toolCall

AGENT_NAME = "AgentReAct"


class Step4ReAct(StepCallBase):
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
            step_name = step["step_name"]
        except Exception:
            self.user_msg = "no found step_name"
            self.code = self.CODE_STEP_FINAL
            return

        if step_name == 'action':
            # Handle action step - execute tool calls
            tool_call_info = self.get_tool_call_info(step, rsp_msg_obj)
            if tool_call_info is None:
                # LLM mistake, missing argv
                obs_json = {
                    "step_name": "observation",
                    "raw_text": "missing tool_call"
                }
                self.tool_msg = obs_json
                self.code = self.CODE_STEP_FINAL
                return

            tool = tool_call_info.func_name
            args = tool_call_info.func_args or {}

            tool_func = tools.get(tool)
            if tool_func is None:
                # LLM mistake, no found this tool
                obs_json = {
                    "step_name": "observation",
                    "raw_text": f"no found such as tool: {tool}"
                }
                self.tool_msg = obs_json
                self.code = self.CODE_STEP_FINAL
                return
            else:
                try:
                    obs = tool_func(**args)
                except Exception as e:
                    obs = str(e)
                    logger.exception(e)
                obs_json = {
                    "step_name": "observation",
                    "raw_text": obs
                }
                self.tool_msg = obs_json
                self.code = self.CODE_STEP_FINAL
                return
        elif step_name == "thought":
            # Handle thought step - process reasoning
            if len(response) == 1:
                if not self.flag_interactive:
                    # for retry
                    self.code = self.CODE_STEP_FINAL
                    self.user_msg = "no found action"
                    # for failed
                    # self.code = self.CODE_TASK_FAILED
                    # self.result = ("only thought step without action or final_answer in non-interactive mode, exiting.")
                    return
                # interactive mode, ask user for more input
                # only thought, no action or final_answer, ask user for more input
                user_input = "continue"
                while True:
                    if not is_main_thread():
                        break
                    user_input = input("\n>>> Your input: ")
                    if not user_input.strip():
                        continue
                    break
                self.user_msg = user_input
                self.code = self.CODE_STEP_FINAL
                return
        elif step_name.startswith('final'):
            # Handle final answer step - complete the task
            self.result = step["raw_text"]
            self.code = self.CODE_TASK_FINAL
            return
        elif len(response) == (index+1):
            # the last element, LLM has a mistake
            logger.error(
                "LLM has a mistake: agent can not handle it [%s] [%s]",
                step_name,
                rsp_msg_obj.content if rsp_msg_obj else None,
            )
            self.code = self.CODE_STEP_FINAL
            self.user_msg = "I can not handle it"
            return

        return
