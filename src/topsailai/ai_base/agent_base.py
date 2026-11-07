'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-24
  Purpose:
'''

import json
import os

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_critical,
    print_info,
)
from topsailai.utils.thread_local_tool import (
    KEY_AGENT_DEEP,
    ctxm_give_agent_name,
    ctxm_set_agent,
    get_thread_var,
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
from topsailai.ai_base.agent_runtime import AgentRuntime
from topsailai.ai_base.agent_tool import AgentTool
from topsailai.ai_base.tool_call import StepCallBase
from topsailai.hooks.points.aibase.after_agent_run import (
    hook__aibase__after__agent_run,
)
from topsailai.hooks.points.aibase.agent_run_payloads import new_operation_id as hook__new_operation_id
from topsailai.hooks.points.aibase.before_agent_run import (
    hook__aibase__before__agent_run,
)
from topsailai.hooks.points.aibase.error_agent_run import (
    hook__aibase__error__agent_run,
)


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
        from topsailai.ai_base.llm_base import LLMModel
        from topsailai.context.llm_request_stat import LLMRequestStat
        from topsailai.context.llm_state_visualizer import LLMStateVisualizer

        self.llm_request_stat = LLMRequestStat()
        self.state_visualizer = LLMStateVisualizer(self.llm_request_stat)
        self.llm_model = LLMModel(
            llm_request_stat=self.llm_request_stat,
            state_visualizer=self.state_visualizer,
        )
        self.runtime = AgentRuntime(self)
        return

    def close(self) -> None:
        """Close runtime components owned by this agent."""
        startup_state = getattr(self, "startup_state", None)
        if startup_state is not None:
            startup_state.cancel()
        self.llm_model.close()

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
        operation_id = hook__new_operation_id()
        with (
                ctxm_give_agent_name(self.agent_name),
                ctxm_set_agent(self),
            ):
            try:
                from topsailai.hooks.points.aibase.before_agent_run.payloads import build_payload as hook__build_payload
                hook__aibase__before__agent_run(
                    **hook__build_payload(
                        operation_id=operation_id, agent_name=self.agent_name,
                        step_call=step_call, user_input=user_input,
                    ),
                )
            except Exception:
                logger.exception(
                    "Agent run Hook failed point=%s operation_id=%s",
                    "hook__aibase__before__agent_run", operation_id,
                )
            self._clear_pending_native_tool_call_responses()
            try:
                result = self._run(step_call, user_input)
            except Exception as error:
                try:
                    from topsailai.hooks.points.aibase.error_agent_run.payloads import build_payload as hook__build_payload
                    hook__aibase__error__agent_run(
                        **hook__build_payload(
                            operation_id=operation_id, agent_name=self.agent_name,
                            step_call=step_call, error=error,
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Agent run Hook failed point=%s operation_id=%s",
                        "hook__aibase__error__agent_run", operation_id,
                    )
                raise
            else:
                try:
                    from topsailai.hooks.points.aibase.after_agent_run.payloads import build_payload as hook__build_payload
                    hook__aibase__after__agent_run(
                        **hook__build_payload(
                            operation_id=operation_id, agent_name=self.agent_name,
                            step_call=step_call, result=result,
                            pending_native_tool_responses_cleared=False,
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Agent run Hook failed point=%s operation_id=%s",
                        "hook__aibase__after__agent_run", operation_id,
                    )
                return result
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

    # Per-slice wait budget used while a pause request blocks the agent loop.
    # Every slice is followed by a hard-interrupt check so a pause stays
    # interruptible even when the overall wait is unbounded.
    PAUSE_POLL_INTERVAL_SECONDS = 1.0

    # Prompt used when a pause marker does not carry its own prompt text.
    DEFAULT_PAUSE_PROMPT = "Agent paused by control request. Continue? [yes/no] "

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
        # A hard interrupt wins over a pending pause request, so any
        # unconsumed pause marker is discarded to avoid pausing the next turn.
        self._clear_pause_marker()
        raise HardInterruptError("Hard interrupt requested via control channel")

    def _get_pause_flag_path(self) -> str:
        """Return the pause-request marker path for the current process/session.

        The path follows the same session-scoped convention as the hard
        interrupt flag:
        ``{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_pause.flag``.
        """
        from topsailai.workspace.folder_constants import (
            FOLDER_WORKSPACE_TASK,
        )
        from topsailai.workspace.folder_utils import (
            get_pause_flag_path,
        )
        session_id = env_tool.get_session_id() or "topsailai"
        pid = os.getpid()
        return get_pause_flag_path(FOLDER_WORKSPACE_TASK, session_id, pid)

    def _clear_pause_marker(self) -> bool:
        """Remove an unconsumed pause marker, returning True when removed.

        Removal is best effort: a failure is logged and never interrupts the
        agent loop, because the marker is only an advisory request.
        """
        marker_path = self._get_pause_flag_path()
        if not os.path.exists(marker_path):
            return False
        try:
            os.remove(marker_path)
            logger.warning("Pause marker removed: %s", marker_path)
            return True
        except OSError as error:
            logger.warning("Failed to remove pause marker %s: %s", marker_path, error)
            return False

    def _consume_pause_marker(self) -> dict | None:
        """Read and delete the pause marker so it is consumed exactly once.

        The marker is removed before the caller starts prompting, so a repeated
        pause request can never stack a second prompt. A malformed marker is
        still consumed and reported as an empty payload, which makes the agent
        fall back to the default prompt and default answer policy.

        Returns:
            The decoded marker payload, or None when no marker exists.
        """
        marker_path = self._get_pause_flag_path()
        if not os.path.exists(marker_path):
            return None

        payload: dict = {}
        try:
            with open(marker_path, "r", encoding="utf-8") as file_obj:
                decoded = json.load(file_obj)
            if isinstance(decoded, dict):
                payload = decoded
            else:
                logger.warning(
                    "Pause marker payload is not an object, using defaults: %s",
                    marker_path,
                )
        except (OSError, ValueError) as error:
            logger.warning(
                "Failed to read pause marker %s, using defaults: %s", marker_path, error
            )

        try:
            os.remove(marker_path)
            logger.warning("Pause marker consumed: %s", marker_path)
        except OSError as error:
            logger.warning("Failed to remove pause marker %s: %s", marker_path, error)
        return payload

    def _check_pause_request(self) -> None:
        """Block on a continue prompt when a pause marker is present.

        Only the outermost agent consumes the marker. Nested subagents share the
        same session and pid path but have no usable interactive input, so they
        would degrade to the default answer and leave the parent unable to
        pause.

        The wait is sliced by ``input_yes_or_no_with_timeout`` and every slice is
        followed by a hard-interrupt check, so a pause stays interruptible.

        Raises:
            HardInterruptError: When the answer is no, or when a hard interrupt
                arrives while waiting.
        """
        if (get_thread_var(KEY_AGENT_DEEP, 0) or 0) != 1:
            return

        payload = self._consume_pause_marker()
        if payload is None:
            return

        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = self.DEFAULT_PAUSE_PROMPT
        timeout = payload.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            timeout = 0.0
        default = payload.get("default")
        default_answer = "no" if default == "interrupt" else "yes"

        from topsailai.utils.input_tool import input_yes_or_no_with_timeout
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
        )

        logger.warning(
            "Pause request consumed; waiting for a continue answer (timeout=%s, default=%s)",
            timeout,
            default_answer,
        )
        should_continue = input_yes_or_no_with_timeout(
            prompt,
            timeout=timeout,
            default=default_answer,
            input_func=get_agent_runtime_input_with_timeout(),
            poll_interval=self.PAUSE_POLL_INTERVAL_SECONDS,
            on_poll=self._check_hard_interrupt,
        )
        if not should_continue:
            logger.warning("Pause request answered no; interrupting the agent loop")
            raise HardInterruptError("Pause request answered no")
        logger.warning("Pause request answered yes; resuming the agent loop")

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
        startup_state = getattr(self, "startup_state", None)
        if startup_state is not None:
            startup_state.mark_started()

        while True:
            # Check for hard interrupt at the start of each iteration.
            self._check_hard_interrupt()
            # Honour a pause request at the start of each iteration. The hard
            # interrupt check above already ran, so an interrupt wins.
            self._check_pause_request()

            # Inject runtime messages before each LLM call
            self._inject_runtime_messages()

            # Check again right before the LLM call.
            self._check_hard_interrupt()
            # Honour a pause request right before the LLM call. The hard
            # interrupt check above already ran, so an interrupt wins.
            self._check_pause_request()

            # LLM chat retries remain inside this one call. They resend these
            # same messages and must never restart this Agent loop.
            rsp_obj, response = self.llm_model.chat(
                self.messages, for_response=True,
                for_stream=env_tool.EnvReaderInstance.check_bool("LLM_RESPONSE_STREAM"),
                tools=list(tools_for_chat.values()),
                retry_interaction_policy=getattr(step_call, "llm_retry_policy", None),
            )
            if not response:
                print_critical("No response from LLM.")
                return None
            # Response message object
            rsp_msg = self.llm_model.get_response_message(rsp_obj)
            self.add_assistant_message(response, tool_calls=rsp_msg.tool_calls)

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
            # A pause request is honoured only after the hard interrupt check,
            # so an interrupt always wins over a pending pause.
            self._check_pause_request()

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
