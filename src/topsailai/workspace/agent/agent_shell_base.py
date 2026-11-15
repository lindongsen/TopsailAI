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
    db_io_tool,
    env_tool,
    thread_tool,
    time_tool,
)
from topsailai.utils.print_tool import (
    print_info,
    print_warning,
)
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
    ContextWindowLimitError,
    HardInterruptError,
    HeavyTaskError,
    LLMBackToChatError,
    LLMRetryExhaustedError,
)
from topsailai.ai_base.llm_control.exception import (
    LLMProviderConnectionError,
    LLMProviderInternalServerError,
    LLMProviderReadError,
    LLMProviderTimeoutError,
)
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from topsailai.hooks.points.workspace.after_attempt_settle_user2agent import (
    hook__workspace__after__attempt_settle_user2agent,
)
from topsailai.workspace.session_stats_service import process_service
from topsailai.utils.thread_local_tool import get_agent_runtime_input
from topsailai.workspace.control_channel import ControlServer
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.folder_utils import resolve_session_id_for_files
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
    SPLIT_LINE,
)
from topsailai.workspace import lock_tool
from topsailai.workspace.agent.agent_chat_base import AgentChatBase
from topsailai.workspace.plugin_instruction.base.cache import bind_instruction_agent
from topsailai.workspace.task import task_tool
from topsailai.workspace.print_tool import (
    decorator_tee_output_by_session,
)
from topsailai.workspace import terminal_title


# Provider failures that leave the conversation intact: the request failed, but
# the session, the messages and the user's intent are all still valid. In
# interactive mode these abandon the current turn and wait for the next user
# message instead of terminating the process. Bad-request and permission-denied
# errors are deliberately excluded because continuing cannot fix them.
RECOVERABLE_PROVIDER_ERRORS = (
    LLMProviderInternalServerError,
    LLMProviderConnectionError,
    LLMProviderTimeoutError,
    LLMProviderReadError,
)


def _resolve_recoverable_provider_error(error):
    """Return the provider error that makes a turn recoverable, else ``None``.

    A provider failure can reach the User2Agent loop in two shapes. When the
    failure is raised outside the bounded retry loop it arrives directly. When
    the bounded retry loop consumes it, the loop raises
    ``LLMRetryExhaustedError`` and keeps the provider failure in ``last_error``
    (also chained as ``__cause__``). Both shapes describe the same recoverable
    condition, so resolve the underlying provider error before deciding whether
    the turn can be abandoned instead of terminating the process.

    An explicit Exit choice in the retry-exhaustion menu raises the same
    ``LLMRetryExhaustedError`` with the same ``last_error``, but it is a human
    decision to stop rather than a recoverable provider failure, so it must
    stay fatal.

    Args:
        error (BaseException): The exception caught by the turn loop.

    Returns:
        BaseException | None: The recoverable provider error, or ``None`` when
        the failure must stay fatal.
    """
    if isinstance(error, RECOVERABLE_PROVIDER_ERRORS):
        return error
    if not isinstance(error, LLMRetryExhaustedError):
        return None
    if getattr(error, "explicit_exit", False):
        return None
    candidates = [getattr(error, "last_error", None), error.__cause__]
    for candidate in candidates:
        if isinstance(candidate, RECOVERABLE_PROVIDER_ERRORS):
            return candidate
    return None


def _resolve_db_io_failure(error):
    """Return the database I/O failure carried by an exception chain, else ``None``.

    A committed write failure can reach the User2Agent loop directly or wrapped
    by an intermediate layer that re-raises it. Both shapes describe the same
    condition, so walk the chain before deciding how to recover.

    Args:
        error (BaseException): The exception caught by the turn loop.

    Returns:
        BaseException | None: The database I/O failure, or ``None`` when the
        failure is unrelated and must keep its original contract.
    """
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if db_io_tool.is_db_io_failure(current):
            return current
        current = current.__cause__ or current.__context__
    return None


# Exit code used when a non-interactive run cannot persist its result. A
# non-zero code is required because a lost write must never look like success
# to a script, a CI job or the launcher that started this process.
DB_IO_FALLBACK_EXIT_CODE = 1


def _exit_after_db_io_failure(error) -> None:
    """Terminate a non-interactive run after a database I/O failure.

    This is the last-resort fallback for a caller that cannot wait for a human.
    ``os._exit`` is an abnormal termination, so the on-disk scene is preserved
    exactly as the failure left it: the session metadata keeps its ``running``
    state instead of being rewritten, and both output streams are flushed so
    the stdout artifact keeps the evidence already produced. Flushing only
    delivers buffered bytes; it never fabricates state. No artifact is removed.

    Args:
        error: The database I/O failure that ended the run.
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        logger.critical(
            "Failed to flush output before fallback exit: [%s] %s",
            type(error).__name__, error, exc_info=True,
        )
    logger.critical(
        "Non-interactive run terminated after a database I/O failure: [%s] %s",
        type(error).__name__, error,
    )
    os._exit(DB_IO_FALLBACK_EXIT_CODE)


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


def _summary_count(runtime) -> int:
    """Read a non-negative runtime count without interpreting mock-like values."""
    value = getattr(runtime, "summary_count", 0)
    return value if type(value) is int and value >= 0 else 0


def _get_session_summary_count(session_id: str, runtime) -> int:
    """Prefer the persisted session total, falling back to this runtime's count."""
    if session_id:
        try:
            from topsailai.context import ctx_manager

            manager = ctx_manager.get_session_manager()
            session = manager.get_session(session_id) if manager is not None else None
            value = getattr(session, "summary_count", None)
            if type(value) is int and value >= 0:
                return value
        except Exception:
            logger.warning("Cannot read session summary count: session_id=%s", session_id,
                           exc_info=True)
    return _summary_count(runtime)


def _get_agent_model_name(ai_agent) -> str:
    """
    Resolve the model name currently used by the agent for the turn summary.

    Args:
        ai_agent: The AI agent instance whose LLM model name should be read.

    Returns:
        str: The model name, or an empty string when it is unavailable.
    """
    llm_model = getattr(ai_agent, "llm_model", None)
    if llm_model is None:
        return ""
    return getattr(llm_model, "model_name", "") or ""


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
    @decorator_tee_output_by_session(need_delete_log_files=False)
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
        self._terminal_failure = False
        self._stats_binding = None
        self._stats_prepare_failed = False
        try:
            try:
                service = process_service(
                    diagnostic=lambda category, name: logger.warning(
                        "Session statistics %s: %s", category, name,
                    ),
                )
                self._stats_binding = service.bind(
                    self.ai_agent, self.ctx_runtime_data.session_id,
                )
            except Exception:
                logger.warning("Session statistics binding unavailable", exc_info=True)
            result = self._run(*args, **kwargs)
            completed = True
            return result
        except SystemExit:
            # A deliberate exit command (`q`, `exit`, `quit`) raises
            # SystemExit, which is a BaseException and therefore never reaches
            # the `except Exception` handler below. Without this branch the
            # completion write in `finally` is skipped, the metadata keeps
            # `running`, and the atexit fallback rewrites it to `interrupted`,
            # misreporting a normal end of session as an abnormal termination.
            # Mark the session complete and re-raise so the requested exit code
            # still propagates. KeyboardInterrupt is deliberately not handled
            # here: an interrupted run must keep reporting `interrupted`.
            completed = True
            raise
        except Exception as e:
            db_error = _resolve_db_io_failure(e)
            update_session_meta_status(
                "error",
                getattr(self.ctx_runtime_data, "session_id", None),
            )
            if db_error is None:
                raise
            # Last-resort net: a database I/O failure must never escape as an
            # uncaught exception, because that would terminate the process and
            # lose the session. The metadata records the failure, the diagnostic
            # artifacts are retained, and the caller receives an explicit
            # failure answer instead of a traceback.
            logger.critical(
                "Database I/O failure ended the session: [%s] %s",
                type(db_error).__name__, db_error,
            )
            self._terminal_failure = True
            failure_answer = (
                "Task terminated: a database write failed and the session could "
                f"not continue: [{type(db_error).__name__}] {db_error}"
            )
            self.last_message = failure_answer
            print(failure_answer)
            return failure_answer
        finally:
            if completed:
                update_session_meta_status(
                    "error" if self._terminal_failure else "completed",
                    getattr(self.ctx_runtime_data, "session_id", None),
                )
            try:
                if self._stats_binding is not None:
                    self._stats_binding.close()
            except Exception:
                logger.warning("Session statistics binding close failed", exc_info=True)
            finally:
                self._stop_control_server()
                self.ai_agent.close()

    def _clear_interrupt_state(self):
        """Clear the interrupted state and any current-process flag file."""
        self.interrupted = False
        session_id = resolve_session_id_for_files(self.ctx_runtime_data)

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

    def _read_next_user_message(self, func_print_pre_input_message):
        """Read a fresh non-empty message after an abandoned User2Agent turn."""
        func_print_pre_input_message()
        while True:
            message = input_message(hook=self.hook_instruction).strip()
            message = self.format_message(message)
            if message:
                return message

    def _start_control_server(self):
        """Acquire the shared per-process control channel server if available.

        Only one control server is started per (session_id, pid) combination
        inside a single process. Subsequent AgentChat instances (e.g. subagents)
        reuse the existing server instead of creating a new one.
        """
        if self.control_server is not None:
            return

        try:
            registry = ControlHandlerRegistry()
            register_control_handlers(registry)

            session_id = resolve_session_id_for_files(self.ctx_runtime_data)
            pid = os.getpid()
            context = ControlContext(
                session_id=session_id,
                pid=pid,
                agent_chat=self,
            )

            from topsailai.workspace.control_channel.server import (
                get_or_start_control_server,
            )

            server = get_or_start_control_server(
                session_id=session_id,
                pid=pid,
                registry=registry,
                context=context,
            )
            self.control_server = server
            logger.info("Acquired control channel server at %s", server.socket_path)
        except Exception as e:
            logger.warning("Failed to acquire control channel server: %s", e)
            self.control_server = None
    def _stop_control_server(self):
        """Release the shared per-process control channel server reference.

        The underlying server is only stopped when the last AgentChat that
        acquired it releases its reference.
        """
        if self.control_server is None:
            return

        try:
            session_id = resolve_session_id_for_files(self.ctx_runtime_data)
            pid = os.getpid()
            from topsailai.workspace.control_channel.server import (
                release_control_server,
            )

            release_control_server(
                session_id=session_id,
                pid=pid,
                server=self.control_server,
            )
            logger.info("Released control channel server reference")
        except Exception as e:
            logger.warning("Failed to release control channel server: %s", e)
        finally:
            self.control_server = None

    @bind_instruction_agent
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

        # Resolve interactivity once for this User2Agent run. An explicit False
        # must override the process environment for every input decision,
        # including prompts used by LLM chat request retries.
        if need_interactive is None:
            need_interactive = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_INTERACTIVE_MODE", True
            )
        interactive_enabled = bool(need_interactive)

        if not func_print_pre_input_message or not interactive_enabled:
            func_print_pre_input_message = lambda *args, **kwargs: None

        # first message
        if not message and self.first_message:
            message = self.first_message

        if message is None:
            if interactive_enabled:
                print(self.ctx_rt_instruction.ctx_history())

            func_print_pre_input_message()
            try:
                message = get_message(
                    self.hook_instruction,
                    need_input=interactive_enabled,
                )
            except EOFError:
                # The input channel is closed before the first message, so the
                # session has nothing to run. End it cleanly instead of
                # reprinting the prompt without bound or raising a traceback.
                logger.info("agent loop run is exiting: input channel closed")
                return ""

        if not self.first_message:
            self.first_message = message

        retry_policy = LLMRetryInteractionPolicy(
            interactive_enabled=interactive_enabled,
            allow_back_to_chat=interactive_enabled and times == 0,
            input_func=get_agent_runtime_input() if interactive_enabled else None,
        )

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
        # the session name is generated asynchronously after the first turn
        # starts, so the cache is reset here to make sure the later refresh
        # is not suppressed by a title written before the name existed
        try:
            terminal_title.reset_terminal_title_cache()
            terminal_title.refresh_terminal_title(
                session_id=self.ctx_runtime_data.session_id,
                force=True,
            )
        except Exception as e:
            logger.debug("Failed to refresh terminal title at session start: %s", e)

        # start
        while True:
            if self.interrupted:
                func_print_pre_input_message()
                try:
                    while True:
                        message = input_message(hook=self.hook_instruction).strip()
                        if message:
                            message = self.format_message(message)
                            self._clear_interrupt_state()
                            break
                except EOFError:
                    # The input channel is closed, so no resume message can
                    # arrive. End the session instead of reprinting the prompt
                    # without bound.
                    self._clear_interrupt_state()
                    break
                continue
            flag_abort = False
            back_to_chat_requested = False
            summary_count_before = _summary_count(self.ctx_runtime_data)
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
                    # Assign executor as soon as the task is taken over so that
                    # pre-run manifests (status=initializing) carry the real
                    # executing agent instead of an empty value.
                    task.executor = (
                        getattr(self.ai_agent, "agent_name", "")
                        or env_tool.EnvReaderInstance.get("TOPSAILAI_TEAM_MEMBER_NAME")
                        or ""
                    )
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

                    # LLM request retries remain inside LLMModel.chat and reuse
                    # the same messages; this never retries ai_agent.run().
                    step_call = get_agent_step_call(
                        kwargs={
                            "flag_interactive": need_interactive,
                            "llm_retry_policy": retry_policy,
                        },
                        agent_type=self.ai_agent.agent_type,
                    )
                    stats_binding = (None if getattr(self, "_stats_prepare_failed", False)
                                     else getattr(self, "_stats_binding", None))
                    attempt = None
                    try:
                        if stats_binding is not None and stats_binding.prepare():
                            attempt = stats_binding.begin()
                    except Exception:
                        self._stats_prepare_failed = True
                    outcome = "failure"
                    try:
                        answer = self.ai_agent.run(step_call, message)
                        outcome = "success"
                    except LLMBackToChatError:
                        outcome = "back"
                        raise
                    except (HardInterruptError, KeyboardInterrupt, EOFError):
                        outcome = "interrupt"
                        raise
                    finally:
                        if attempt is not None:
                            attempt.determine(outcome)
                        hook__workspace__after__attempt_settle_user2agent(
                            agent_chat=self, outcome=outcome, attempt=attempt,
                        )

                    # task
                    if task:
                        task.result = answer
                        try:
                            if env_tool.EnvReaderInstance.check_bool(
                                "TOPSAILAI_ENABLE_TOOL_STAT", True
                            ):
                                task.tool_call_count = (
                                    self.ai_agent.runtime.tool_stat.total_calls
                                )
                            else:
                                task.tool_call_count = 0
                        except Exception as e:
                            logger.debug("Failed to read task tool call count: %s", e)
                            task.tool_call_count = 0
                        task.executor = getattr(self.ai_agent, "agent_name", "") or ""

            except (LLMBackToChatError, LLMRetryExhaustedError) + RECOVERABLE_PROVIDER_ERRORS as e:
                # Back and a recoverable provider failure both abandon this
                # User2Agent turn: the session, the messages and the user's
                # intent stay intact, so the turn simply ends and the loop
                # waits for the next user message instead of terminating the
                # process. Retry stays inside LLMModel.chat and resends the
                # same request, so it never reaches this branch.
                if not isinstance(e, LLMBackToChatError):
                    # The bounded retry loop may already have consumed the
                    # provider failure and raised LLMRetryExhaustedError, so
                    # resolve the underlying provider error before deciding.
                    provider_error = _resolve_recoverable_provider_error(e)
                    if (
                        provider_error is None
                        or not interactive_enabled
                        or not thread_tool.is_main_thread()
                    ):
                        # Non-interactive callers keep the original fail-fast
                        # contract, and unrelated exhaustion causes stay fatal.
                        # A worker thread (e.g. a subagent) must never read the
                        # main conversation's input, so it also stays fatal.
                        raise
                    print_warning(
                        "LLM provider failure aborted this turn: "
                        f"[{type(provider_error).__name__}] {provider_error}"
                    )
                back_to_chat_requested = True
                answer = ""
                self.call_hooks_post_fail_run(e)
                try:
                    message = self._read_next_user_message(
                        func_print_pre_input_message
                    )
                except (KeyboardInterrupt, EOFError):
                    back_to_chat_requested = False
                    flag_abort = True
                    answer = "failed due to abort by Human"
                    if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                        self.call_hooks_post_fail_run(KeyboardInterrupt())
                        break
                # An abandoned turn is not a completed scheduled turn. The loop
                # naturally starts again with the fresh message; do not use a
                # continue that could accidentally replay the old request.
                curr_count -= 1
            except HardInterruptError as e:
                self.interrupted = True
                answer = ""
                print_warning(f"Hard interrupt requested: {e}")
                if times > 0 and curr_count >= times:
                    self.interrupted = False
                    break
                continue
            except agent_exception.AgentEndProcess:
                self.last_message = self.messages[-1]
                self.call_hooks_post_fail_run(agent_exception.AgentEndProcess())
            except (ContextWindowLimitError, HeavyTaskError) as e:
                logger.warning("%s caught in agent chat loop: %s", type(e).__name__, e)
                self._terminal_failure = True
                answer = f"Task terminated: {e}"
                self.last_message = answer
                print(answer)
                if need_save_answer:
                    self.ctx_runtime_data.add_session_message(ROLE_ASSISTANT, answer)
                self.call_hooks_post_fail_run(e)
                break
            except (KeyboardInterrupt, EOFError):
                flag_abort = True
                answer = "failed due to abort by Human"
                if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                    self.call_hooks_post_fail_run(KeyboardInterrupt())
                    break
            except Exception as e:
                db_error = _resolve_db_io_failure(e)
                if db_error is None:
                    # Only a database I/O failure is recoverable here. Every
                    # other unexpected exception keeps its original contract.
                    raise
                # A database I/O failure must never terminate the process. The
                # conversation, the session metadata and the diagnostic
                # artifacts all survive, so the turn is abandoned instead.
                logger.critical(
                    "Database I/O failure aborted this turn: [%s] %s",
                    type(db_error).__name__, db_error,
                )
                self.call_hooks_post_fail_run(e)
                if not interactive_enabled or not thread_tool.is_main_thread():
                    # A caller that cannot wait for a human ends the run with an
                    # explicit failure answer instead of an uncaught traceback.
                    self._terminal_failure = True
                    answer = (
                        "Task terminated: a database write failed and this turn "
                        f"could not be persisted: [{type(db_error).__name__}] {db_error}"
                    )
                    self.last_message = answer
                    print(answer)
                    if not interactive_enabled and thread_tool.is_main_thread():
                        # Last-resort fallback: a lost write must never look
                        # like success to a script, a CI job or the launcher, so
                        # the process exits non-zero. The on-disk scene is left
                        # untouched: ``os._exit`` is an abnormal termination, so
                        # the metadata keeps its ``running`` state and the
                        # artifacts stay exactly as the failure left them. A
                        # worker thread never reaches this call: it must not
                        # terminate the interpreter that owns a possibly usable
                        # interactive session.
                        _exit_after_db_io_failure(db_error)
                    break
                print_warning(
                    "Database write failed; this turn was not persisted: "
                    f"[{type(db_error).__name__}] {db_error}"
                )
                if answer:
                    # The answer was already produced, so show it before the
                    # turn is abandoned: a lost write must not lose the result.
                    print(answer)
                back_to_chat_requested = True
                answer = ""
                try:
                    message = self._read_next_user_message(
                        func_print_pre_input_message
                    )
                except (KeyboardInterrupt, EOFError):
                    back_to_chat_requested = False
                    flag_abort = True
                    answer = "failed due to abort by Human"
                    if need_confirm_abort and not input_yes("Agent Session Continue [yes/no] "):
                        self.call_hooks_post_fail_run(KeyboardInterrupt())
                        break
                # An abandoned turn is not a completed scheduled turn, so the
                # finite-turn budget is restored before the loop continues.
                curr_count -= 1

            if not back_to_chat_requested:
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

                answer_printed = False
                try:
                    if need_save_answer:
                        if only_save_final:
                            self.ctx_runtime_data.add_session_message(ROLE_ASSISTANT, answer)
                        else:
                            if not flag_abort:
                                self.ctx_rt_aiagent.add_session_message()
                    if answer:
                        # An empty answer must not overwrite the last message
                        # recorded by an earlier branch such as AgentEndProcess.
                        self.last_message = answer

                    self.call_hook_for_final_answer()
                    self.call_hooks_post_succ_run()

                    # Use the interactivity resolved once for this run. An explicit
                    # need_interactive=False must not be overridden by process state.
                    if not env_tool.is_debug_mode() or not interactive_enabled:
                        print(answer)
                        answer_printed = True

                    reached_times_limit = times > 0 and curr_count >= times
                    if not reached_times_limit:
                        self.ctx_runtime_data.reset_messages()
                        if interactive_enabled:
                            print(self.ctx_rt_instruction.ctx_history())
                except Exception as e:
                    db_error = _resolve_db_io_failure(e)
                    if db_error is None:
                        raise
                    # The answer already exists, so a failed persistence must not
                    # discard it or end the process. Report the loss, skip the
                    # session reload that would fail the same way, and let the
                    # loop continue from the prompt.
                    logger.critical(
                        "Database I/O failure while persisting the answer: [%s] %s",
                        type(db_error).__name__, db_error,
                    )
                    print_warning(
                        "The answer could not be persisted to the database: "
                        f"[{type(db_error).__name__}] {db_error}"
                    )
                    if answer and not answer_printed:
                        print(answer)
                    if answer:
                        # The answer is the turn's result even though it could
                        # not be stored, so it must remain the last message.
                        self.last_message = answer
                    reached_times_limit = times > 0 and curr_count >= times

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
                    model_name = _get_agent_model_name(self.ai_agent)

                    print()
                    print(SPLIT_LINE)
                    print(f" {self.agent_name} Turn Summary ".center(len(SPLIT_LINE)))
                    print(SPLIT_LINE)
                    print(f"[{self.agent_name}] have scheduled tasks [{curr_count}] times")
                    print(f"session_id          : {session_id}")
                    print(f"session_name        : {session_name}")
                    print(f"model_name          : {model_name}")
                    print(f"project_workspace   : {os.environ.get('TOPSAILAI_PROJECT_WORKSPACE', '')}")
                    print(f"pwd                 : {os.environ.get('TOPSAILAI_PWD', '')}")
                    print(f"start_time          : {time_tool.parse_time_seconds(start_time)}")
                    print(f"end_time(now)       : {time_tool.parse_time_seconds(end_time)}")
                    print(f"elapsed_time        : {end_time-start_time}")
                    print(f"total_prompt_tokens : {total_tokens}")
                    print(f"total_cached_tokens : {total_cached_tokens}")
                    print(f"cache_hit_rate      : {cache_hit_rate}")
                    turn_summary_count = max(
                        0, _summary_count(self.ctx_runtime_data) - summary_count_before
                    )
                    total_summary_count = _get_session_summary_count(
                        session_id, self.ctx_runtime_data
                    )
                    print(f"summary_count       : +{turn_summary_count}(total {total_summary_count})")
                    sys.stdout.flush()

                if env_tool.is_debug_mode() or env_tool.EnvReaderInstance.check_bool("TOPSAILAI_PRINT_TOOL_STAT", True):
                    tool_call_stat = self.ai_agent.runtime.tool_stat
                    __content = tool_call_stat.export_json()
                    logger.info("ToolStat of tool_calls:\n [%s]", __content)

                # refresh the terminal title before the times check, because
                # the session name is generated during the first turn and a
                # single-turn run would otherwise exit without ever showing it
                try:
                    terminal_title.refresh_terminal_title(
                        session_id=self.ctx_runtime_data.session_id,
                        force=True,
                    )
                except Exception as e:
                    logger.debug("Failed to refresh terminal title: %s", e)

                # check times after the completed-turn summary is emitted
                if reached_times_limit:
                    break

                # next time
                func_print_pre_input_message()
                try:
                    while True:
                        message = input_message(hook=self.hook_instruction)
                        message = message.strip()
                        if message:
                            message = self.format_message(message)
                            break
                except EOFError:
                    # The input channel is closed, so no next message can
                    # arrive. End the session instead of reprinting the prompt
                    # without bound.
                    break

        # hook answer
        self.hook_for_answer(answer)

        # no limit times
        if times == 0:
            logger.info("agent loop run is exiting: current_count=[%s]", curr_count)

        return answer
