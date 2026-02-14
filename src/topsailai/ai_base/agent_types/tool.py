'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-23
  Purpose:
'''

from topsailai.logger import logger
from topsailai.ai_base.agent_base import (
    StepCallBase,
)
from topsailai.utils.thread_tool import (
    is_main_thread,
)
from topsailai.utils.thread_local_tool import (
    get_agent_name,
)

from . import exception as agent_exception


def get_tool_func(tool_map:dict, tool_name:str):
    """get a callable func.

    Compatible connection characters to avoid mistakes made by LLM.

    Args:
        tool_map (dict): key is tool_name, value is tool_func
        tool_name (str):
    """
    if not tool_map or not tool_name:
        return None

    tool_name = tool_name.strip()
    if not tool_name:
        return None

    if tool_name in tool_map:
        return tool_map[tool_name]

    new_tool_name = tool_name.replace('.', '-')
    for _tool_name in tool_map:
        if _tool_name.replace('.', '-').strip() == new_tool_name:
            return tool_map[_tool_name]

    return None

def exec_tool_func(tool_func, args):
    try:
        result = tool_func(**args)
    except agent_exception.AgentEndProcess as e:
        raise e
    except Exception as e:
        result = str(e)
        logger.exception(e)
    return result


class StepCallTool(StepCallBase):
    """
    function startswith:
    1. "execute", get a result
    2. "complete", complete all
    """

    def execute_step_action(self, step, tools, rsp_msg_obj, **_):
        """
        Returns:
            Exception|any: Exception for error, other for tool_call return
        """
        # Handle action step - execute tool calls
        tool_call_info = self.get_tool_call_info(step, rsp_msg_obj)
        if tool_call_info is None:
            # LLM mistake, missing argv
            return agent_exception.ToolError("missing tool_call")

        tool = tool_call_info.func_name
        args = tool_call_info.func_args or {}

        tool_func = get_tool_func(tools, tool)
        if tool_func is None:
            # LLM mistake, no found this tool
            return agent_exception.ToolError(f"no found such as tool: {tool}")

        return exec_tool_func(tool_func, args)

    def execute_step_interactive(self):
        _auto_msg = "If you are sure that user information is required or task is finished, output `final_answer`. Otherwise, continue executing"
        if not self.flag_interactive or not is_main_thread():
            return _auto_msg

        while True:
            user_input = input(f"\n[{get_agent_name()}] >>> Your input: ")
            if not user_input.strip():
                continue
            return user_input

    def complete_step_thought(self, response, **_):
        # Handle thought step - process reasoning
        if len(response) == 1:
            self.user_msg = self.execute_step_interactive()
            self.code = self.CODE_STEP_FINAL
            return

    def complete_cannot_handle(self, step_name:str, step:dict, tools:dict, response:list, index:int, rsp_msg_obj=None, **_):
        if len(response) == (index+1):
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

    def complete_final(self, step:dict, **_):
        # Handle final answer step - complete the task
        self.result = step["raw_text"]
        self.code = self.CODE_TASK_FINAL
        return

    def complete_inquiry(self, **_):
        self.user_msg = self.execute_step_interactive()
        self.code = self.CODE_STEP_FINAL
        return

    def complete_action(self, step, tools, rsp_msg_obj, **_):
        result = self.execute_step_action(
            step=step,
            tools=tools,
            rsp_msg_obj=rsp_msg_obj,
        )
        if isinstance(result, Exception):
            result = str(result)
        self.tool_msg = result
        self.code = self.CODE_STEP_FINAL
        return
