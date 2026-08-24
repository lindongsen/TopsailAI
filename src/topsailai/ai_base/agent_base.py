'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-24
  Purpose:
'''

import os

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_critical,
    print_info,
)
from topsailai.utils.thread_local_tool import (
    ctxm_give_agent_name,
    ctxm_set_agent,
)
from topsailai.utils import (
    env_tool,
)

from topsailai.ai_base.agent2llm_message_source import (
    apply_agent2llm_message_source,
)
from topsailai.ai_base.constants import (
    STEP_NAME_TASK,
    STEP_NAME_OBSERVATION,
    DEFAULT_AGENT_ROLE,
)
from topsailai.ai_base.agent_types.exception import (
    AgentNoCareResult,
    AgentNeedRefreshSession,
    DataAgentRefreshSession,
)
from topsailai.ai_base.exception import (
    HardInterruptError,
    HeavyTaskError,
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
        self.agent_role = DEFAULT_AGENT_ROLE

        # LLM
        # lazy import due to too long time to import
        from topsailai.ai_base.llm_base import (
           LLMModel,
        )
        self.llm_model = LLMModel()
        return

    def __str__(self) -> str:
        parts = {
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "threshold_ctx_history": str(self.threshold_ctx_history),
            "model_info": str(self.llm_model),
        }
        result = "\n"
        for k, v in parts.items():
            result += f"  {k}={v}\n"
        return result

    @property
    def max_tokens(self) -> int:
        """
        Get the maximum tokens allowed for the LLM model.

        Returns:
            int: Maximum tokens value
        """
        return self.llm_model.max_tokens

    def _clear_pending_native_tool_call_responses(self):
        """Clear synthetic native tool-call responses when supported."""
        clear_pending = getattr(
            self.llm_model,
            "clear_pending_native_tool_call_responses",
            None,
        )
        if callable(clear_pending):
            clear_pending()

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
            self._clear_pending_native_tool_call_responses()
            try:
                return self._run(step_call, user_input)
            finally:
                self._clear_pending_native_tool_call_responses()
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

    # Throttle interrupt checks during streaming to avoid excessive I/O.
    # A value of N means we check the flag at most once every N chunks.
    STREAM_INTERRUPT_CHECK_INTERVAL = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_chunk_counter = 0

    def _get_interrupt_flag_path(self) -> str:
        """Return the hard-interrupt flag path for the current process/session.

        The path follows the same convention used by the Agent2LLM runtime
        message source and the CLI injection helper:
        ``{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_interrupt.flag``.
        """
        from topsailai.workspace.folder_constants import (
            FOLDER_WORKSPACE_TASK,
        )
        from topsailai.workspace.folder_utils import (
            get_interrupt_flag_path,
        )
        session_id = env_tool.get_session_id() or "topsailai"
        pid = os.getpid()
        return get_interrupt_flag_path(FOLDER_WORKSPACE_TASK, session_id, pid)

    def _check_hard_interrupt(self, *, throttle_stream: bool = False):
        """Check for a hard-interrupt request and raise if present.

        This method is intentionally lightweight when the flag file does not
        exist. When the file exists, it is removed and ``HardInterruptError``
        is raised so the ReAct loop can terminate at a safe point.

        Args:
            throttle_stream: When True, only perform the check every
                ``STREAM_INTERRUPT_CHECK_INTERVAL`` chunks to avoid I/O
                overhead during streaming.

        Raises:
            HardInterruptError: If the interrupt flag file exists.
        """
        if throttle_stream:
            self._stream_chunk_counter += 1
            if self._stream_chunk_counter % self.STREAM_INTERRUPT_CHECK_INTERVAL != 0:
                return

        flag_path = self._get_interrupt_flag_path()
        if not os.path.exists(flag_path):
            return

        try:
            os.remove(flag_path)
            logger.warning("Hard interrupt flag detected and removed: %s", flag_path)
        except OSError as e:
            logger.warning("Failed to remove hard interrupt flag %s: %s", flag_path, e)
            # Even if cleanup fails, the flag exists; raise anyway so the
            # loop terminates rather than continuing under an interrupt.
        raise HardInterruptError("Hard interrupt requested via control channel")

    def _scan_memory_refs(self, response) -> None:
        """Record unique story-memory references found in one LLM response."""
        if os.environ.get("TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED", "1") == "0":
            return

        try:
            from topsailai.tools import story_memory_tool
            from topsailai.tools.memory_tool_utils import (
                memory_ref_parser,
                memory_stat,
            )

            response_text = "\n".join(
                step.get("raw_text", "")
                for step in response
                if isinstance(step, dict)
                and isinstance(step.get("raw_text", ""), str)
            )
            title_index = memory_ref_parser.build_title_index(
                story_memory_tool.list_memories()
            )
            result = memory_ref_parser.collect_canonical_ids(
                response_text, title_index
            )
            for memory_id in result.resolved_ids:
                memory_stat.record_memory_event(
                    story_memory_tool.WORKSPACE, memory_id, "cite"
                )
        except Exception:
            logger.warning(
                "Failed to record story-memory references from LLM response",
                exc_info=True,
            )

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
        print_info(f"[available_tools] [{len(all_tools)}] {list(all_tools.keys())}")

        # Tools formatted for chat API
        tools_for_chat = {}
        if env_tool.is_use_tool_calls():
            tools_for_chat = get_tools_for_chat(all_tools)
        if tools_for_chat:
            print_info(f"[effective_tools] [{len(tools_for_chat)}] {list(tools_for_chat.keys())}")

        # new session
        user_message = {"step_name":STEP_NAME_TASK,"raw_text":user_input} if user_input else None
        self.new_session(user_message)

        while True:
            # Check for hard interrupt at the start of each iteration.
            self._check_hard_interrupt()

            # Inject runtime messages before each LLM call
            self._inject_runtime_messages()

            # Check again right before the LLM call.
            self._check_hard_interrupt()

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
            self._scan_memory_refs(response)

            # Current message count
            ctx_count = len(self.messages)
            last_message = self.messages[-1]

            for i, step in enumerate(response):
                try:
                    ret = step_call(step, tools=all_tools, response=response, index=i, rsp_msg_obj=rsp_msg)
                except AgentNoCareResult:
                    break
                except AgentNeedRefreshSession as e:
                    data = e.args[0] if e.args else None
                    if data is None:
                        logger.critical("BUG: missing data of tool_call")
                        return None
                    elif isinstance(data, DataAgentRefreshSession):
                        data.ai_agent = self

                        # add last message to session
                        if data.tool_request:
                            data.ctx_runtime_data.add_session_message(
                                role=None,
                                message=data.tool_request,
                            )
                        else:
                            data.ctx_runtime_data.add_session_message_dict(last_message)

                        # add result of tool_call to session
                        self.add_tool_message(
                            {
                                "step_name": STEP_NAME_OBSERVATION,
                                "raw_text": data.tool_result,
                            }
                        )
                        data.ctx_runtime_data.add_session_message_dict(self.messages[-1])

                        # done
                        break
                    else:
                        logger.critical("BUG: illegal data of tool_call [%s]", data)
                        return None

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

            # Check for hard interrupt after tool calls have returned.
            self._check_hard_interrupt()

            if len(self.messages) == ctx_count and last_message == self.messages[-1]:
                print_critical("No progress made in this iteration, exiting.")
                return None

            # hook, pre-chat
            try:
                self.call_hooks_pre_chat()
            except HeavyTaskError as e:
                logger.warning("HeavyTaskError caught in agent run: %s", e)
                print_critical(f"Task terminated: {e}")
                return None

            # update env
            self.update_message_for_env()

        # raise RuntimeError("Unreachable code reached")

    def _inject_runtime_messages(self):
        """Inject runtime messages from the registered source before LLM chat.

        This method is called at the top of each Agent2LLM iteration. It
        delegates to ``apply_agent2llm_message_source`` which reads from the
        thread-local source (if any) and appends messages at the tail of
        ``self.messages``.
        """
        apply_agent2llm_message_source(self)
