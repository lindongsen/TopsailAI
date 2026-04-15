'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-23
  Purpose:
'''

from topsailai.logger import logger
from topsailai.context import tool_stat
from topsailai.ai_base.tool_call import (
    StepCallBase,
)
from topsailai.utils.thread_tool import (
    is_main_thread,
)
from topsailai.utils.thread_local_tool import (
    get_agent_name,
)
from topsailai.utils import (
    print_tool,
)

from . import context as agent_ctx
from . import exception as agent_exception


def get_tool_func(tool_map: dict, tool_name: str):
    """
    Retrieve a callable tool function from a tool map by name.

    This function looks up a tool function in the provided dictionary using the tool name.
    It handles compatibility with different connection characters (dots and hyphens) to avoid
    mistakes made by LLM when generating tool calls.

    Args:
        tool_map (dict): A dictionary where keys are tool names (strings) and values are
            the corresponding callable tool functions.
        tool_name (str): The name of the tool to retrieve. Can use either '.' or '-' as
            connection characters.

    Returns:
        callable|None: The tool function if found, None otherwise. Returns None if either
            the tool_map or tool_name is empty/None after processing.
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

def exec_tool_func(tool_func, args, tool_name:str=None):
    """
    Execute a tool function with the given arguments.

    This function calls the provided tool function with the given arguments and handles
    any exceptions that may occur during execution. Special exceptions like
    AgentEndProcess are re-raised, while other exceptions are converted to string
    representations.

    Args:
        tool_func (callable): The tool function to execute.
        args (dict): A dictionary of arguments to pass to the tool function.

    Returns:
        any: The result of the tool function execution, or a string representation
            of the error if an exception occurred (except for AgentEndProcess).
    """
    error = None
    try:
        result = tool_func(**args)
    except (agent_exception.AgentToolCallException) as e:
        raise e
    except Exception as e:
        error = e
        result = str(e)
        logger.exception(e)
    finally:
        tool_stat.record_tool_call(
            tool_call=tool_name or tool_func.__name__,
            tool_args=args,
            error=error,
            result=result,
        )
    return result


class ExceptionStepCallEnd(Exception):
    """
    the step is end
    """
    pass

class StepCallTool(StepCallBase):
    """
    function startswith:
    1. "execute", get a result
    2. "complete", complete all
    """

    def is_action_finish_task(self, action:str) -> bool:
        """ The action will end task """
        return False
        #from topsailai.tools.collaboration_tool import ACTION_FINISH_TASK
        #return action.endswith(ACTION_FINISH_TASK)

    def build_step_for_finish_task(self, step, rsp_msg_obj) -> dict|None:
        """ return new step """
        tool_call_info = self.get_tool_call_info(step, rsp_msg_obj)
        if not tool_call_info:
            return None
        if not self.is_action_finish_task(tool_call_info.func_name):
            return None
        content = ""
        if len(tool_call_info.func_args) == 1:
            content = list(tool_call_info.func_args.values())[0]
        else:
            content = str(tool_call_info.func_args)
        return {
            "step_name": "final_answer",
            "raw_text": content
        }

    def hook_pre_step(self, step, rsp_msg_obj) -> dict|None:
        """ return new step """
        # case: action is finish_task
        return self.build_step_for_finish_task(step, rsp_msg_obj)

    def execute_step_action(self, step, tools, rsp_msg_obj, **_):
        """
        Execute a tool action step.

        This method handles the execution of tool calls during the action step of the agent.
        It retrieves the tool call information from the step, looks up the tool function,
        and executes it with the provided arguments.

        Args:
            step: The current step containing tool call information.
            tools (dict): A dictionary mapping tool names to their callable functions.
            rsp_msg_obj: The response message object that may contain additional context.
            **_ : Additional keyword arguments (ignored).

        Returns:
            Exception|any: A ToolError exception if there's an issue (missing tool call or
                tool not found), otherwise the result of the tool function execution.
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

        try:
            return exec_tool_func(tool_func, args, tool_name=tool)
        except agent_exception.AgentFinalAnswer as e:
            self.complete_final(
                {
                    "raw_text": str(e),
                }
            )
            return e

    def execute_step_interactive(self):
        """
        Get user input in interactive mode.

        This method prompts the user for input when the agent is running in interactive mode.
        It continues to prompt until valid input is provided. If not in interactive mode
        or not running in the main thread, it returns an automatic message directing
        the user to either provide input or output a final answer.

        Returns:
            str: User input string or an automatic guidance message.
        """
        if not self.flag_interactive or not is_main_thread():
            _auto_msg = ""

            # case: no tool_call has been executed.
            if agent_ctx.get_count_of_action_for_current_agent() == 0:
                _auto_msg += "No tool_call has been executed. "

            # default
            _auto_msg += "If you are sure that user information is required or task is finished, output `final_answer`. Otherwise, continue executing"

            return _auto_msg

        while True:
            user_input = input(f"\n[{get_agent_name()}] >>> Your input: ")
            if not user_input.strip():
                continue
            return user_input

    def complete_step_thought(self, response, **_):
        """
        Handle the completion of a thought step.

        This method is called when a thought step is completed. If the response contains
        only one element, it indicates that the agent needs user input or confirmation.

        Args:
            response (list): The response from the thought step processing.
            **_ : Additional keyword arguments (ignored).
        """
        # Handle thought step - process reasoning
        if len(response) == 1:
            self.user_msg = self.execute_step_interactive()
            self.code = self.CODE_STEP_FINAL
            return

    def complete_cannot_handle(self, step_name:str, step:dict, tools:dict, response:list, index:int, rsp_msg_obj=None, **_):
        """
        Handle cases where the agent cannot process a step.

        This method is called when the agent encounters a step it cannot handle.
        If this is the last element in the response, it logs an error indicating
        an LLM mistake and sets the final state with an error message.

        Args:
            step_name (str): The name of the step that cannot be handled.
            step (dict): The step dictionary containing step information.
            tools (dict): A dictionary of available tools.
            response (list): The response list being processed.
            index (int): The current index in the response list.
            rsp_msg_obj: The response message object (optional).
            **_ : Additional keyword arguments (ignored).
        """
        if len(response) == (index+1):
            # the last element, LLM has a mistake
            logger.error(
                "LLM has a mistake: agent can not handle it [%s] [%s]",
                step_name,
                rsp_msg_obj.content if rsp_msg_obj else None,
            )
            self.code = self.CODE_STEP_FINAL
            self.user_msg = "I can not handle it: missing action?"
            return
        return

    def complete_final(self, step:dict, **_):
        """
        Handle the final answer step.

        This method is called when the agent has completed its task and received
        a final answer. It extracts the raw text from the step and sets the
        appropriate completion code.

        Args:
            step (dict): The final step dictionary containing the raw text result.
            **_ : Additional keyword arguments (ignored).
        """
        # Handle final answer step - complete the task
        self.result = step["raw_text"]
        self.code = self.CODE_TASK_FINAL
        return

    def complete_inquiry(self, **_):
        """
        Handle an inquiry step.

        This method is called when the agent needs to make an inquiry to the user.
        It prompts for interactive user input and sets the appropriate completion code.

        Args:
            **_ : Additional keyword arguments (ignored).
        """
        self.user_msg = self.execute_step_interactive()
        self.code = self.CODE_STEP_FINAL
        return

    def complete_action(self, step, tools, rsp_msg_obj, func_formatter_result=None, **_):
        """
        Handle the completion of an action step.

        This method is called after an action step is executed. It retrieves the result
        from the tool execution, converts any exceptions to strings, stores the result
        in tool_msg, and sets the appropriate completion code.

        Args:
            step: The action step that was executed.
            tools (dict): A dictionary of available tools.
            rsp_msg_obj: The response message object.
            **_ : Additional keyword arguments (ignored).
        """
        result = self.execute_step_action(
            step=step,
            tools=tools,
            rsp_msg_obj=rsp_msg_obj,
        )
        if isinstance(result, agent_exception.AgentFinalAnswer):
            return
        if isinstance(result, Exception):
            result = str(result)
        if func_formatter_result:
            result = func_formatter_result(result)
        self.tool_msg = result
        self.code = self.CODE_STEP_FINAL
        return

    def pre_execute(self, step:dict, tools:dict, response:list, index:int, rsp_msg_obj=None, **_):
        """

        Returns:
            tuple(step_name, step)
        Exception:
            ExceptionStepCallEnd, current step is end
        """
        step_name = None
        try:
            # hook
            new_step = self.hook_pre_step(step, rsp_msg_obj)
            if new_step:
                step = new_step

            step_name = step["step_name"]
        except KeyboardInterrupt as e:
            raise e
        except Exception as e:
            self.user_msg = "missing step_name"
            self.code = self.CODE_STEP_FINAL
            raise ExceptionStepCallEnd(e)
        finally:
            ori_step_name = step_name
            keys = ["thought", "inquiry"]
            if self._last_step_name and step_name:
                if self._last_step_name in keys \
                    and step_name == self._last_step_name \
                    and len(response) == 1 \
                    and self._last_step_count == 1:
                    # only thought, duplicate found
                    step_name = "final"
                    print_tool.print_error(f"LLM mistake: give final due to duplicate to [{ori_step_name}] only")

                if step_name in keys:
                    if len(response) == 1:
                        if step.get("raw_text") and 'final_answer' in step["raw_text"]:
                            step_name = "final"
                            print_tool.print_error("LLM mistake: give final due to found 'final_answer'")

        self._last_step_name = step_name
        self._last_step_count = len(response)
        return (step_name, step)
