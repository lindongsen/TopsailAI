'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-24
  Purpose:
'''

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
    env_tool,
)

from topsailai.ai_base.agent_types.exception import (
    AgentNoCareResult,
)
from topsailai.ai_base.llm_base import (
    LLMModel,
)

from topsailai.tools.base.common import (
    get_tools_for_chat,
)
from topsailai.ai_base.agent_tool import AgentTool
from topsailai.ai_base.tool_call import StepCallBase


class AgentBase(AgentTool):
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
        super().__init__(
            system_prompt=system_prompt,
            tool_prompt=tool_prompt,
            tools=tools,
            tool_kits=tool_kits,
            excluded_tool_kits=excluded_tool_kits,
        )

        # Name of the agent
        self.agent_name = agent_name
        self.agent_type = ""

        # LLM
        self.llm_model = LLMModel()
        return

    @property
    def max_tokens(self) -> int:
        """
        Get the maximum tokens allowed for the LLM model.

        Returns:
            int: Maximum tokens value
        """
        return self.llm_model.max_tokens

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
        user_message = {"step_name":"task","raw_text":user_input} if user_input else None
        self.new_session(user_message)

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
                try:
                    ret = step_call(step, tools=all_tools, response=response, index=i, rsp_msg_obj=rsp_msg)
                except AgentNoCareResult:
                    break

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

            # hook, pre-chat
            self.call_hooks_pre_chat()

            # update env
            self.update_message_for_env()

        # raise RuntimeError("Unreachable code reached")
