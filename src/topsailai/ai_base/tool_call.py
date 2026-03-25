'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-26
  Purpose:
'''

from topsailai.logger import logger
from topsailai.utils import (
    json_tool,
    env_tool,
)


class ToolCallInfo(object):
    """
    Data structure to store tool call information.

    This class encapsulates the function name and arguments for a tool call.
    """
    def __init__(self):
        """Initialize ToolCallInfo with empty function name and arguments."""
        # Function name to be called
        self.func_name = ""
        # Arguments for the function call
        self.func_args = {}


class StepCallBase(object):
    """
    Base class for step call return values.

    This class defines the data structure for return values of step_call(...) method.
    It provides status codes and result handling for agent execution steps.
    """
    CODE_TASK_FINAL = 0  # Task completed successfully with final result
    CODE_STEP_FINAL = 1  # Step completed, ready for next step
    CODE_TASK_FAILED = -1  # Task failed with error

    def __init__(self, flag_interactive:bool=False):
        """
        Initialize StepCallBase instance.

        Args:
            flag_interactive (bool): Whether this step call is interactive
        """
        # for result, refer to self.__reset
        # Status code indicating the execution result
        self.code = None
        # User message for the next step
        self.user_msg = None
        # Tool message containing tool execution results
        self.tool_msg = None
        # Final result of the task
        self.result = None

        # flags
        # Flag indicating if this is an interactive step
        self.flag_interactive = True if flag_interactive else False

        if env_tool.EnvReaderInstance.get("TOPSAILAI_FLAG_INTERACTIVE_MODE") is not None:
            self.flag_interactive = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_FLAG_INTERACTIVE_MODE")
        logger.info("interactive mode: [%s]", self.flag_interactive)

        # print_step(f"interactive mode: [{self.flag_interactive}]", need_format=False)

        # internal variables, self._xxx
        # last step name, string
        self._last_step_name = None
        # last count, int
        self._last_step_count = None

        return

    def __reset(self):
        # Status code indicating the execution result
        self.code = None
        # User message for the next step
        self.user_msg = None
        # Tool message containing tool execution results
        self.tool_msg = None
        # Final result of the task
        self.result = None

        return

    def __call__(self, *args, **kwds):
        """
        Make the instance callable.

        This method allows the instance to be called like a function.
        It resets the instance and executes the step.

        Returns:
            StepCallBase: The instance itself after execution
        """
        # it must init all of result for each call
        self.__reset()

        self._execute(*args, **kwds)
        return self

    def get_tool_call_info(self, step:dict, rsp_msg_obj) -> ToolCallInfo|None:
        """
        Extract tool call information from step and response message.

        This method attempts to extract tool call information from multiple sources:
        1. Response message object's tool_calls
        2. Direct step dictionary
        3. Raw text in step dictionary

        Args:
            step (dict): Step information from message
            rsp_msg_obj: ChatMessage response object

        Returns:
            ToolCallInfo|None: Tool call information if found, None otherwise
        """
        if rsp_msg_obj is not None:
            # list_dict
            tool_calls = rsp_msg_obj.tool_calls
            if tool_calls:
                tool_call = tool_calls[0]

                # Function name from tool call
                func_name = tool_call.function.name
                # Function arguments
                func_args = None
                if tool_call.function.arguments:
                    try:
                        func_args = json_tool.json_load(tool_call.function.arguments)
                    except Exception as e:
                        logger.exception(e)
                        return None

                if func_name:
                    result = ToolCallInfo()
                    result.func_name = func_name
                    result.func_args = func_args or {}
                    return result

        if 'tool_call' in step:
            # Function name from step
            func_name = step["tool_call"]
            # Function arguments from step
            func_args = step.get('tool_args')

            if func_name:
                result = ToolCallInfo()
                result.func_name = func_name
                result.func_args = func_args or {}
                return result

        if 'raw_text' in step:
            try:
                # Raw text content
                raw_text = json_tool.convert_code_block_to_json_str(step["raw_text"]) or step["raw_text"]
                raw_text = json_tool.to_json_str(raw_text)
                # Parsed dictionary from raw text
                raw_dict = None
                if raw_text:
                    raw_dict = json_tool.json_load(raw_text)
                    if isinstance(raw_dict, list):
                        raw_dict = raw_dict[0]
                if raw_dict and 'tool_call' in raw_dict:
                    # Function name from raw text
                    func_name = raw_dict['tool_call']
                    # Function arguments from raw text
                    func_args = raw_dict.get('tool_args')
                    if func_name:
                        result = ToolCallInfo()
                        result.func_name = func_name
                        result.func_args = func_args or {}
                        return result
            except Exception:
                pass

        return None

    def _execute(
            self,
            step:dict,
            tools:dict,
            response:list,
            index:int,
            rsp_msg_obj=None,
        ):
        """
        Execute the step call.

        This method must be implemented by subclasses to define specific
        step execution logic.

        Args:
            step (dict): Current step information
            tools (dict): Available tools dictionary
            response (list): Full response list
            index (int): Current step index in response
            rsp_msg_obj: Response message object

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError("Subclasses must implement this method")
