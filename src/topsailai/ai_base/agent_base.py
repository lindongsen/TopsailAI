from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_critical,
    print_step,
)
from topsailai.utils.thread_local_tool import (
    ctxm_give_agent_name,
    ctxm_set_agent,
)
from topsailai.utils import (
    json_tool,
    env_tool,
)

from topsailai.ai_base.prompt_base import (
    PromptBase,
)
from topsailai.ai_base.llm_base import (
    LLMModel,
)
from topsailai.prompt_hub import prompt_tool

from topsailai.tools import (
    get_tool_prompt,
    TOOLS as INTERNAL_TOOLS,
    get_tools_for_chat,
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
        # for result
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
        self.__init__()
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

class AgentBase(PromptBase):
    """
    Base class for AI agents.

    This class provides the foundation for creating AI agents with tool
    capabilities and prompt management.
    """
    def __init__(
            self,
            system_prompt:str,
            tools:dict,
            agent_name:str,
            tool_prompt:str="",
            tool_kits:list=None,
            excluded_tool_kits:list=None,
        ):
        """
        Initialize AgentBase instance.

        Args:
            system_prompt (str): System prompt for the agent
            tools (dict): Specific tools for this agent (tool_name: function)
            agent_name (str): Name of the agent
            tool_prompt (str): Additional tool prompt text
            tool_kits (list): List of internal tool kits to use
            excluded_tool_kits (list): List of tool kits to exclude

        Raises:
            AssertionError: If system_prompt is empty
        """
        # System prompt for the agent
        self.system_prompt = system_prompt
        # Specific tools for this agent
        self.tools = tools
        # Name of the agent
        self.agent_name = agent_name
        assert self.system_prompt, "system_prompt is required"

        self.llm_model = LLMModel()  # LLM model instance for the agent

        ######################################################################
        # tool_kits, internal tools
        ######################################################################
        if not self.tools and not tool_kits:
            # using all of internal tools.
            tool_kits = list(INTERNAL_TOOLS.keys())

        if tool_kits and excluded_tool_kits:
            for tool_name in excluded_tool_kits:
                if tool_name in tool_kits:
                    tool_kits.remove(tool_name)
                    continue
                for _tool in tool_kits[:]:
                    if _tool.startswith(tool_name):
                        if _tool in tool_kits:
                            tool_kits.remove(_tool)

        if tool_kits:
            tool_kits = prompt_tool.get_tools_by_env(tool_kits)

        ######################################################################
        # all of available tools
        ######################################################################
        # Dictionary of all available tools for this agent
        self.available_tools = dict()
        for tool_name in tool_kits or []:
            self.available_tools[tool_name] = INTERNAL_TOOLS[tool_name]
        for tool_name in self.tools or {}:
            self.available_tools[tool_name] = self.tools[tool_name]

        ######################################################################
        # tool prompts
        ######################################################################
        if not tool_prompt:
            tool_prompt = ""

        if self.available_tools:
            if not env_tool.is_use_tool_calls():
                # get tool docs as prompt
                tool_prompt += get_tool_prompt(None, self.available_tools)

            # extend prompt with tool
            tool_prompt += prompt_tool.get_prompt_by_tools(self.available_tools)

            # extra tools
            tool_prompt += prompt_tool.get_extra_tools()

        # prepare tool_prompt ok
        # Tool prompt text for the agent
        self.tool_prompt = tool_prompt

        # debug
        if self.tool_prompt and env_tool.EnvReaderInstance.check_bool("TOPSAILAI_PRINT_TOOL_PROMPT"):
            print_step(f"[tool_prompt]:\n{self.tool_prompt}\n", need_format=False)

        super(AgentBase, self).__init__(self.system_prompt, self.tool_prompt)
        return

    @property
    def max_tokens(self) -> int:
        """
        Get the maximum tokens allowed for the LLM model.

        Returns:
            int: Maximum tokens value
        """
        return self.llm_model.max_tokens

    @property
    def all_tools(self):
        """
        Get all available tools including internal tools.

        Returns:
            dict: Dictionary containing all available tools
        """
        # Dictionary to store all tools
        all_tools = {}
        # first, internal tools
        all_tools.update(INTERNAL_TOOLS)

        # second, specific tools for this agent.
        if self.tools:
            all_tools.update(self.tools)

        return all_tools

    def run(self, step_call:StepCallBase, user_input:str):
        """
        Run the agent with the given step call and user input.

        This method sets up the agent context and executes the run process.

        Args:
            step_call (StepCallBase): Step call instance to use
            user_input (str): User input to process

        Returns:
            The result of the agent execution
        """
        with (
                ctxm_give_agent_name(self.agent_name),
                ctxm_set_agent(self),
            ):
            try:
                return self._run(step_call, user_input)
            finally:
                if self.flag_dump_messages:
                    self.dump_messages()

    def _run(self, step_call:StepCallBase, user_input:str):
        """
        Internal run method to be implemented by subclasses.

        Args:
            step_call (StepCallBase): Step call instance to use
            user_input (str): User input to process

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError("Subclasses must implement this method")

class AgentRun(AgentBase):
    """
    Common agent implementation for running steps.

    This class provides a standard implementation for agent execution
    with step-by-step processing.
    """
    def _run(self, step_call:StepCallBase, user_input:str):
        """
        Execute the agent run process with step-by-step processing.

        This method handles the main execution loop for the agent,
        processing user input and managing tool calls.

        Args:
            step_call (StepCallBase): Step call instance to use
            user_input (str): User input to process

        Returns:
            The final result of the task or None if failed
        """
        # tools
        # Available tools for the agent
        all_tools = self.available_tools
        print_step(f"[available_tools] [{len(all_tools)}] {list(all_tools.keys())}", need_format=False)

        # Tools formatted for chat API
        tools_for_chat = {}
        if env_tool.is_use_tool_calls():
            tools_for_chat = get_tools_for_chat(all_tools)
        if tools_for_chat:
            print_step(f"[effective_tools] [{len(tools_for_chat)}] {list(tools_for_chat.keys())}", need_format=False)

        # new session
        if user_input:
            self.new_session({"step_name":"task","raw_text":user_input})

        while True:
            rsp_obj, response = self.llm_model.chat(
                self.messages, for_response=True,
                for_stream=env_tool.EnvReaderInstance.check_bool("LLM_RESPONSE_STREAM"),
                tools=list(tools_for_chat.values()),
            )
            if not response:
                print_critical("No response from LLM.")
                return None
            # Response message object
            rsp_msg = self.llm_model.get_response_message(rsp_obj)
            self.add_assistant_message(response, tool_calls=rsp_msg.tool_calls)

            # Current message count
            ctx_count = len(self.messages)

            for i, step in enumerate(response):
                ret = step_call(step, tools=all_tools, response=response, index=i, rsp_msg_obj=rsp_msg)
                assert isinstance(ret, StepCallBase), "step_call must return StepCallBase instance"
                if ret.code == ret.CODE_TASK_FINAL:
                    logger.info(f"final: {ret.result}")
                    return ret.result
                elif ret.code == ret.CODE_TASK_FAILED:
                    print_critical(f"Task failed: {ret.result}")
                    return None
                elif ret.code == ret.CODE_STEP_FINAL:
                    self.add_user_message(ret.user_msg)
                    self.add_tool_message(ret.tool_msg)
                    break

            # end for step in response

            if len(self.messages) == ctx_count:
                print_critical("No progress made in this iteration, exiting.")
                return None

            # update env
            self.update_message_for_env()

        # raise RuntimeError("Unreachable code reached")