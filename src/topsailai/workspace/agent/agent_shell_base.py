'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-29
  Purpose:
  Context:
    1. ai_agent.messages: Save the context message that is currently being processed
    2. ctx_runtime_data.messages: Save the processed Q&A messages
'''

import os
import sys
import time

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    time_tool,
)
from topsailai.utils.print_tool import (
    print_info,
)
from topsailai.context import tool_stat
from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
)
from topsailai.ai_base.agent_types.init import (
    get_agent_step_call,
)
from topsailai.workspace.session_meta import update_session_meta_status
from topsailai.ai_base.agent_types import (
    exception as agent_exception,
)
from topsailai.ai_base.exception import (
    HardInterruptError,
    HeavyTaskError,
)
from topsailai.workspace.control_channel import ControlServer
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
    SPLIT_LINE,
)
from topsailai.workspace import lock_tool
from topsailai.workspace.agent.agent_chat_base import AgentChatBase
from topsailai.workspace.task import task_tool
from topsailai.workspace.print_tool import (
    decorator_tee_output_by_session,
)
from topsailai.workspace import terminal_title


def _get_session_token_totals(session_id: str, ai_agent) -> tuple[int, int]:
    """
    Resolve total token counts for the end-of-run summary.

    When a session id is available, read the accumulated totals from session
    storage. The session row aggregates per-agent deltas contributed by every
    agent that processed the session, so it is the authoritative source.

    When no session id is available, or when reading from storage fails, fall
    back to the current agent's TokenStat totals.

    Args:
        session_id (str): The current session id, if any.
        ai_agent: The AI agent instance whose TokenStat should be used as fallback.

    Returns:
        tuple[int, int]: ``(total_tokens, total_cached_tokens)``.
    """
    if session_id:
        try:
            # Lazy import to avoid circular imports between workspace and context.
            from topsailai.context import ctx_manager
            session_mgr = ctx_manager.get_session_manager()
            totals = session_mgr.get_session_token_totals(session_id)
            if totals is not None:
                return totals
        except Exception as e:
            logger.debug(f"_get_session_token_totals: failed to read from session storage: {e}")

    # Fallback: use the current agent's TokenStat totals.
    token_stat = getattr(ai_agent, "llm_model", None)
    if token_stat:
        token_stat = getattr(token_stat, "tokenStat", None)
    if token_stat:
        return (
            getattr(token_stat, "total_tokens", 0) or 0,
            getattr(token_stat, "total_cached_tokens", 0) or 0,
        )
    return 0, 0


# Warning appended to the final answer when a task completes with tool-stat
# enabled but zero recorded tool calls. This is a strong, obvious system alert
# so that users and callers notice potential lazy execution.
LAZY_EXECUTION_WARNING = (
    "\n\n---\n\n"
    "!!! CRITICAL SYSTEM WARNING !!!\n"
    "The task completed with ZERO tool calls. "
    "This may indicate lazy execution: the agent produced a final answer without "
    "verifying facts, reading files, or invoking any tools. "
    "Please review the result carefully before trusting it."
)

class AgentChat(AgentChatBase):
    @decorator_tee_output_by_session(need_delete_log_files=True)
    def run(self, *args, **kwargs):
        """Run the agent chat session.

        Executes the main conversation loop between human and AI agent.
        Handles message input, agent execution, response processing, and
        session management.

        Args:
            message: Initial message to send to the agent. If None, prompts for input.
            times: Maximum number of conversation turns. 0 means unlimited.
            func_build_message: Optional callback to transform message before sending.
            func_print_pre_input_message: Optional callback to execute before prompting for input.
            need_save_answer: Whether to save answers to context. Defaults to True.
            need_confirm_abort: Whether to confirm before aborting on keyboard interrupt.
            need_interactive: Whether to use interactive mode. Defaults to True.
            need_symbol_for_answer: Whether to prepend symbol to answer. Defaults to False.
            only_save_final: If True, only save the final answer to session history.

        Returns:
            str: The final answer from the AI agent.
        """
        completed = False
        try:
            result = self._run(*args, **kwargs)
            completed = True
            return result
        except Exception:
            update_session_meta_status(
                "error",
                getattr(self.ctx_runtime_data, "session_id", None),
            )
            raise
        finally:
            if completed:
                update_session_meta_status(
                    "completed",
                    getattr(self.ctx_runtime_data, "session_id", None),
                )
            self._stop_control_server()

    def _clear_interrupt_state(self):
        """Clear the interrupted state and any current-process flag file."""
        self.interrupted = False
        session_id = self.ctx_runtime_data.session_id or env_tool.get_session_id()
        if not session_id:
            return

        from topsailai.workspace.folder_constants import (
            FOLDER_WORKSPACE_TASK,
        )
        from topsailai.workspace.folder_utils import (
            get_interrupt_flag_path,
        )

        flag_path = get_interrupt_flag_path(
            FOLDER_WORKSPACE_TASK,
            session_id,
            os.getpid(),
        )
        try:
            os.remove(flag_path)
            logger.info("Cleared hard interrupt flag after receiving new input: %s", flag_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to clear hard interrupt flag %s: %s", flag_path, e)
    def _start_control_server(self):
        """Start the per-process control channel server if not already running."""
        if self.control_server is not None:
            return

        try:
            registry = ControlHandlerRegistry()
            register_control_handlers(registry)

            session_id = self.ctx_runtime_data.session_id or env_tool.get_session_id() or "topsailai"
            context = ControlContext(
                session_id=session_id,
                pid=os.getpid(),
                agent_chat=self,
            )

            server = ControlServer(
                registry=registry,
                context=context,
            )
            server.start()
            self.control_server = server
            logger.info("Started control channel server at %s", server.socket_path)
        except Exception as e:
            logger.warning("Failed to start control channel server: %s", e)
            self.control_server = None

    def _stop_control_server(self):
        """Stop the per-process control channel server if running."""
        if self.control_server is None:
            return

        try:
            self.control_server.stop()
            logger.info("Stopped control channel server")
        except Exception as e:
            logger.warning("Failed to stop control channel server: %s", e)
        finally:
            self.control_server = None

    def _run(
            self,
            message:str=None,
            times:int=0,

            func_build_message=None,
            func_print_pre_input_message=None,

            need_save_answer:bool=True,
            need_confirm_abort:bool=True,
            need_interactive:bool=None,
            need_symbol_for_answer=None,
            need_session_lock:bool=None,
            only_save_final:bool=False,
            task_id=None,
        ) -> str:
        """Run the agent chat session.

        Executes the main conversation loop between human and AI agent.
        Handles message input, agent execution, response processing, and
        session management.

        Args:
            message: Initial message to send to the agent. If None, prompts for input.
            times: Maximum number of conversation turns. 0 means unlimited.
            func_build_message: Optional callback to transform message before sending.
            func_print_pre_input_message: Optional callback to execute before prompting for input.
            need_save_answer: Whether to save answers to context. Defaults to True.
            need_confirm_abort: Whether to confirm before aborting on keyboard interrupt.
            need_interactive: Whether to use interactive mode. Defaults to True.
            need_symbol_for_answer: Whether to prepend symbol to answer. Defaults to False.
            only_save_final: If True, only save the final answer to session history.

        Returns:
            str: The final answer from the AI agent.
        """
        self.call_hooks_pre_run()
        self._start_control_server()

        if not func_print_pre_input_message or not env_tool.is_interactive_mode():
            # noop
            func_print_pre_input_message = lambda *args, **kwargs: None

        # first message
        if not message:
            if self.first_message:
                message = self.first_message

        if message is None:
            # show session messages
            if env_tool.is_interactive_mode():
                self.ctx_rt_instruction.ctx_history()

            func_print_pre_input_message()
            message = get_message(self.hook_instruction, need_input=env_tool.is_interactive_mode())

        if not self.first_message:
            self.first_message = message

        # env
        if need_interactive is None:
            need_interactive = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_INTERACTIVE_MODE", True)

        if need_symbol_for_answer is None:
            need_symbol_for_answer = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_NEED_SYMBOL_FOR_ANSWER", False)

        if need_session_lock is None:
            need_session_lock = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_ENABLE_SESSION_LOCK", False,
            )
        ctxm_lock_tool = lock_tool.ctxm_void
        if need_session_lock:
            ctxm_lock_tool = lock_tool.ctxm_try_session_lock

        # task
        task = None
        if times == 1:
            if not task_id:
                task_id = env_tool.EnvReaderInstance.get("TOPSAILAI_TASK_ID")
            if task_id:
                task = task_tool.TaskUtil(task_id)
                task.session_messages = self.ctx_runtime_data.messages

        # variables
        # up_time = int(time.time())
        answer = ""
        curr_count = 0


        if message:
            message = self.format_message(message)

        # set terminal title once at session start
        try:
            terminal_title.refresh_terminal_title(
                session_id=self.ctx_runtime_data.session_id,
            )
        except Exception as e:
            logger.debug("Failed to refresh terminal title at session start: %s", e)

        # start
        while True:
            if self.interrupted:
                func_print_pre_input_message()
                while True:
                    message = input_message(hook=self.hook_instruction).strip()
                    if message:
                        message = self.format_message(message)
                        self._clear_interrupt_state()
                        break
                continue
            flag_abort = False
            # reset answer to null string
            answer = ""

            curr_count += 1
            # build message
            if message and func_build_message:
                message = func_build_message(
                    message=message,
                    curr_count=curr_count,
                )

            # task
            if task:
                if message:
                    task.task_content = message
                    message = task.manifest + message

            # run
            start_time = int(time.time())
            try:
                with (
                    task_tool.ctxm_process_task(task),
                    ctxm_lock_tool(timeout=0) as data
                    ):
                    # it need session lock but lock failed
                    if need_session_lock and data.get("session_id") and not data.get("fp"):
                        print_info(data.get("msg"))
                        return data.get("msg")

                    # lock session ok, refresh session messages in hook_after_init_prompt
                    #if fp:
                        # refresh session messages
                        #self.ctx_runtime_data.reset_messages()

                    answer = self.ai_agent.run(
                        get_agent_step_call(
                            args=(need_interactive,),
                            agent_type=self.ai_agent.agent_type,
                        ),
                        message,
                    )

                    # task
                    if task:
                        task.result = answer
                        try:
                            if env_tool.EnvReaderInstance.check_bool(
                                "TOPSAILAI_ENABLE_TOOL_STAT", True
                            ):
                                task.tool_call_count = tool_stat.get_agent_tool_stat(
                                    self.ai_agent
                                ).total_calls
                            else:
                                task.tool_call_count = 0
                        except Exception as e:
                            logger.debug("Failed to read task tool call count: %s", e)
                            task.tool_call_count = 0

            except HardInterruptError as e:
                self.interrupted = True
                answer = ""
                logger.warning("Hard interrupt caught in agent chat loop: %s", e)
                continue
            except agent_exception.AgentEndProcess:
                self.last_message = self.messages[-1]
                self.call_hooks_post_fail_run(agent_exception.AgentEndProcess())
            except HeavyTaskError as e:
                logger.warning("HeavyTaskError caught in agent chat loop: %s", e)
                answer = f"Task terminated: {e}"
                self.last_message = answer
                self.call_hooks_post_fail_run(e)
                break
            except (KeyboardInterrupt, EOFError):
                flag_abort = True
                answer = "failed due to abort by Human"
                if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                    self.call_hooks_post_fail_run(KeyboardInterrupt())
                    break

            if answer:
                answer = self.hook_build_answer(
                    answer,
                    need_symbol=need_symbol_for_answer,
                )

                # task
                if task:
                    answer = task.manifest + answer
                    if (
                        env_tool.EnvReaderInstance.check_bool(
                            "TOPSAILAI_ENABLE_TOOL_STAT", True
                        )
                        and task.tool_call_count == 0
                    ):
                        answer += LAZY_EXECUTION_WARNING
                    need_save_answer = True
                    only_save_final = True

                if need_save_answer:
                    if only_save_final:
                        self.ctx_runtime_data.add_session_message(ROLE_ASSISTANT, answer)
                    else:
                        if not flag_abort:
                            self.ctx_rt_aiagent.add_session_message()
                self.last_message = answer

            self.call_hook_for_final_answer()
            self.call_hooks_post_succ_run()

            # it is not interactive mode
            if not env_tool.is_debug_mode() or not env_tool.is_interactive_mode():
                print(answer)

            # check times
            if times > 0 and curr_count >= times:
                break

            self.ctx_runtime_data.reset_messages()
            if env_tool.is_interactive_mode():
                self.ctx_rt_instruction.ctx_history()

            # end time
            end_time = int(time.time())

            if env_tool.is_need_print():
                total_tokens, total_cached_tokens = _get_session_token_totals(
                    self.ctx_runtime_data.session_id, self.ai_agent
                )
                # Cache hit rate: cached tokens / total tokens. Guard against
                # zero or missing totals so we never divide by zero.
                if total_tokens:
                    cache_hit_rate = f"{total_cached_tokens / total_tokens * 100:.3f}%"
                else:
                    cache_hit_rate = "N/A"

                session_id = self.ctx_runtime_data.session_id or ""
                session_name = ""
                session_data = self.ctx_runtime_data.session_data
                if session_data is not None:
                    session_name = session_data.session_name or ""

                print()
                print(SPLIT_LINE)
                print(f"[{self.agent_name}] have scheduled tasks [{curr_count}] times")
                print(f"session_id          : {session_id}")
                print(f"session_name        : {session_name}")
                print(f"start_time          : {time_tool.parse_time_seconds(start_time)}")
                print(f"end_time(now)       : {time_tool.parse_time_seconds(end_time)}")
                print(f"elapsed_time        : {end_time-start_time}")
                print(f"total_tokens        : {total_tokens}")
                print(f"total_cached_tokens : {total_cached_tokens}")
                print(f"cache_hit_rate      : {cache_hit_rate}")
                sys.stdout.flush()

            if env_tool.is_debug_mode() or env_tool.EnvReaderInstance.check_bool("TOPSAILAI_PRINT_TOOL_STAT", True):
                tool_call_stat = tool_stat.get_agent_tool_stat(self.ai_agent)
                __content = tool_call_stat.export_json()
                logger.info("ToolStat of tool_calls:\n [%s]", __content)

            # next time
            try:
                terminal_title.refresh_terminal_title(
                    session_id=self.ctx_runtime_data.session_id,
                )
            except Exception as e:
                logger.debug("Failed to refresh terminal title: %s", e)

            func_print_pre_input_message()
            while True:
                message = input_message(hook=self.hook_instruction)
                message = message.strip()
                if message:
                    message = self.format_message(message)
                    break

        # hook answer
        self.hook_for_answer(answer)

        # no limit times
        if times == 0:
            logger.info("agent loop run is exiting: current_count=[%s]", curr_count)

        return answer
