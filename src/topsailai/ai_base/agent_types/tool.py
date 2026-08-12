'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-23
  Purpose:
'''

from datetime import datetime
import functools
from typing import Any, Callable
import yaml

from topsailai.logger import logger
from topsailai.context import (
    tool_stat,
    tool_call_warning,
    ctx_safe,
)
from topsailai.ai_base.tool_call import (
    StepCallBase,
)
from topsailai.utils.thread_tool import (
    is_main_thread,
)
from topsailai.utils.thread_local_tool import (
    get_agent_name,
    get_agent_object,
    get_agent_runtime_input,
)
from topsailai.utils import (
    print_tool,
    env_tool,
)
from topsailai.utils.json_tool import (
    json_load,
    to_json_str,
)
from topsailai.events import record_tool_call_events
from topsailai.ai_base.constants import (
    LLM_KEYWORD_MISTAKE,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    STEP_NAME_ACTION,
    STEP_NAME_FINAL_ANSWER,
    STEP_NAME_INQUIRY,
    STEP_NAME_OBSERVATION,
    STEP_NAME_THOUGHT,
    MSG_KEY_RAW_TEXT,
    MSG_KEY_STEP_NAME,
)
from topsailai.ai_base.tool_approval import (
    with_tool_approval,
    ToolApprovalDeniedError,
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

def with_tool_response_safe(exec_tool_func: Callable) -> Callable:
    """
    A decorator for context safe to Avoid excessive context that may reach the limit!
    """

    @functools.wraps(exec_tool_func)
    def wrapper(*args, **kwargs) -> Any:
        result = exec_tool_func(*args, **kwargs)

        # safe
        result_str = str(result)
        maximum_bytes = env_tool.EnvReaderInstance.get("TOPSAILAI_TOOL_CALL_MAXIMUM_RETURN", 300000, formatter=int)
        maximum_bytes = max(maximum_bytes, agent_ctx.AgentContextInstance.max_tokens, 30000)
        if len(result_str) > maximum_bytes:
            logger.warning(
                "tool_call result exceeds maximum_bytes: [%s], args=[%s], kwargs=[%s]",
                maximum_bytes,
                args, kwargs,
            )
            return ctx_safe.truncate_text(result_str, maximum_bytes)

        return result

    return wrapper

@tool_call_warning.detect_tool_call_warning
@tool_stat.detect_duplicate_tool_call
@with_tool_response_safe
@with_tool_approval
@record_tool_call_events
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
    if not tool_name:
        tool_name = tool_func.__name__

    error = None
    result = None
    try:
        result = tool_func(**args)
    except (agent_exception.AgentToolCallException) as e:
        raise e
    except Exception as e:
        error = e
        result = str(e)
        print_tool.print_error(e, exception=True)
    finally:
        tool_stat.record_tool_call(
            tool_call=tool_name,
            tool_args=args,
            error=error,
            result=result,
        )

    if result is None:
        # Remind developers about this matter
        # tool should give a clear result
        logger.critical("tool_call result is None: [%s]", tool_name)
        return str(result)

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
            return agent_exception.ToolError("missing tool_call or arguments error")

        tool = tool_call_info.func_name
        args = tool_call_info.func_args or {}

        tool_func = get_tool_func(tools, tool)
        if tool_func is None:
            # LLM mistake, no found this tool
            return agent_exception.ToolError(f"no found such as tool: {tool}")

        try:
            return exec_tool_func(tool_func=tool_func, args=args, tool_name=tool)
        except agent_exception.AgentFinalAnswer as e:
            self.complete_final(
                {
                    "raw_text": str(e),
                }
            )
            return e
        except ToolApprovalDeniedError as e:
            return str(e)

    def execute_step_interactive(self):
        """
        Get user input in interactive mode.

        This method prompts the user for input when the agent is running in interactive mode.
        It continues to prompt until valid input is provided. If not in interactive mode
        or not running in the main thread, it returns an automatic observation message
        directing the agent to either provide input or output a final answer.

        Returns:
            str | dict: User input string, or an observation dict with frontmatter
                separating time, warning, and hint when running non-interactively.
        """
        if not self.flag_interactive or not is_main_thread():
            now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            warning = ""

            # case: no tool_call has been executed.
            if agent_ctx.get_count_of_action_for_current_agent() == 0:
                warning = "No tool_call has been executed."

            # default
            hint = "If you are sure that user information is required or task is finished, output `final_answer`. Otherwise, continue executing."

            raw_text_parts = ["---", f'time: "{now}"']
            if warning:
                raw_text_parts.append(f'warning: "{warning}"')
            raw_text_parts.extend([f'hint: "{hint}"', "---"])
            raw_text = "\n".join(raw_text_parts)

            return {
                "step_name": STEP_NAME_OBSERVATION,
                "raw_text": raw_text,
            }

        while True:
            input_func = get_agent_runtime_input()
            if input_func is None:
                input_func = input
            user_input = input_func(f"\n[{get_agent_name()}] >>> Your input: ")
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

    def _parse_message_content(self, message: dict):
        """Parse message content into a list of step dicts.

        Supports content stored as a list, a single dict, or a JSON string.
        Returns an empty list for unsupported formats.
        """
        content = message.get("content")
        if isinstance(content, list):
            return content
        if isinstance(content, dict):
            return [content]
        if isinstance(content, str):
            parsed = json_load(content)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        return []

    def _is_mergeable_thought_message(self, message: dict) -> tuple[bool, str]:
        """Check whether a message is a standalone thought/inquiry step.

        Returns (True, raw_text) when the message is an assistant message whose
        content contains exactly one step with step_name ``thought`` or
        ``inquiry``. Otherwise returns (False, "").
        """
        if not isinstance(message, dict):
            return False, ""
        if message.get("role") != ROLE_ASSISTANT:
            return False, ""
        # A message that carries tool_calls is not a pure thought/inquiry.
        if message.get("tool_calls"):
            return False, ""
        steps = self._parse_message_content(message)
        if len(steps) != 1:
            return False, ""
        step = steps[0]
        if not isinstance(step, dict):
            return False, ""
        step_name = step.get(MSG_KEY_STEP_NAME)
        if step_name not in (STEP_NAME_THOUGHT, STEP_NAME_INQUIRY):
            return False, ""
        raw_text = step.get(MSG_KEY_RAW_TEXT, "")
        return True, raw_text

    def _has_intervening_executable_messages(
        self, messages: list, start_idx: int, end_idx: int
    ) -> bool:
        """Return True if action/observation/tool messages exist between start and end.

        A user-role message whose step_name is ``observation`` is ignored, because
        such observations are human-provided context and should not block merging
        of preceding assistant reasoning into the final answer.
        """
        executable_steps = {STEP_NAME_ACTION, STEP_NAME_OBSERVATION}
        for idx in range(start_idx + 1, end_idx):
            msg = messages[idx]
            if msg.get("role") == ROLE_TOOL:
                return True
            if msg.get("role") == ROLE_USER:
                steps = self._parse_message_content(msg)
                if (
                    len(steps) == 1
                    and isinstance(steps[0], dict)
                    and steps[0].get(MSG_KEY_STEP_NAME) == STEP_NAME_OBSERVATION
                ):
                    continue
                # Any other user-role message blocks the merge.
                return True
            inner_steps = self._parse_message_content(msg)
            for step in inner_steps:
                if isinstance(step, dict) and step.get(MSG_KEY_STEP_NAME) in executable_steps:
                    return True
        return False

    def _merge_preceding_thoughts_into_final(self):
        """Merge standalone thought/inquiry messages into the final_answer thought.

        This is a fallback for LLMs that split reasoning and the final answer
        across separate assistant messages. The nearest two preceding assistant
        messages (``messages[-3]`` and ``messages[-2]``) are inspected. If they
        contain only a single ``thought`` or ``inquiry`` step and no executable
        messages intervene, their raw_text is prepended to the ``thought`` step
        of the final_answer message (``messages[-1]``). If the final_answer does
        not already contain a thought step, a new thought step is inserted at the
        front of its content.

        Original messages are preserved; only the final_answer message content
        is mutated in place.
        """
        agent = get_agent_object()
        if agent is None or not hasattr(agent, "messages"):
            return
        messages = agent.messages
        if len(messages) < 2:
            return

        final_msg = messages[-1]
        if final_msg.get("role") != ROLE_ASSISTANT:
            return

        final_steps = self._parse_message_content(final_msg)
        thought_step = None
        for step in final_steps:
            if isinstance(step, dict) and step.get(MSG_KEY_STEP_NAME) == STEP_NAME_THOUGHT:
                thought_step = step
                break

        merge_texts = []
        # Inspect messages[-3] and messages[-2] in index order.
        candidate_offsets = (-3, -2)
        for offset in candidate_offsets:
            if abs(offset) > len(messages):
                continue
            idx = len(messages) + offset
            candidate_msg = messages[idx]
            is_mergeable, raw_text = self._is_mergeable_thought_message(candidate_msg)
            if not is_mergeable:
                continue
            if self._has_intervening_executable_messages(messages, idx, len(messages) - 1):
                continue
            merge_texts.append((idx, raw_text))

        if not merge_texts:
            return

        merged_content = "\n\n".join(text for _, text in merge_texts)

        if thought_step is not None:
            original_text = thought_step.get(MSG_KEY_RAW_TEXT, "")
            thought_step[MSG_KEY_RAW_TEXT] = merged_content + "\n\n" + original_text
        else:
            new_thought = {
                MSG_KEY_STEP_NAME: STEP_NAME_THOUGHT,
                MSG_KEY_RAW_TEXT: merged_content,
            }
            final_steps.insert(0, new_thought)

        final_msg["content"] = to_json_str(final_steps)
        logger.info(
            "Merged preceding thought/inquiry from messages %s into final_answer thought",
            [idx for idx, _ in merge_texts],
        )

    def _strip_task_manifest(self, text: str) -> str:
        """Strip a task manifest frontmatter block from the start of text.

        Detects a leading '---' block, parses it as YAML, and removes it
        if it contains a 'task_id' field (indicating an unexpected manifest).
        """
        if not text:
            return text

        # Check if text starts with '---'
        if not text.startswith("---"):
            return text

        lines = text.split("\n")
        if len(lines) < 3:
            return text

        # First line is '---', find the closing '---' line
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx is None:
            return text

        # Extract YAML content between the '---' delimiters
        yaml_content = "\n".join(lines[1:end_idx])

        # Parse YAML; if parsing fails, do not process
        try:
            data = yaml.safe_load(yaml_content)
        except Exception:
            return text

        # If YAML is a dict containing 'task_id', it's unexpected content
        if isinstance(data, dict) and "task_id" in data:
            logger.warning(
                "Stripped task manifest frontmatter from final_answer: %s",
                yaml_content.strip(),
            )
            # Remove frontmatter, keep remaining content
            return "\n".join(lines[end_idx + 1:]).lstrip("\n")

        return text

    def complete_final(self, step:dict, **_):
        """
        Handle the final answer step.

        This method is called when the agent has completed its task and received
        a final answer. It extracts the raw text from the step, merges any
        standalone preceding thought/inquiry messages into the final_answer
        thought, and sets the appropriate completion code.

        Args:
            step (dict): The final step dictionary containing the raw text result.
            **_ : Additional keyword arguments (ignored).
        """
        # Handle final answer step - complete the task
        try:
            self._merge_preceding_thoughts_into_final()
        except Exception as e:
            logger.warning(
                "Failed to merge preceding thought/inquiry into final_answer: %s",
                e,
                exc_info=True,
            )
        self.result = step.get(MSG_KEY_RAW_TEXT, "")
        # Prefer the raw_text from the final_answer step in the mutated message
        # in case the step representation differs from the original response.
        agent = get_agent_object()
        if agent is not None and hasattr(agent, "messages") and agent.messages:
            final_msg = agent.messages[-1]
            final_steps = self._parse_message_content(final_msg)
            for s in final_steps:
                if isinstance(s, dict) and s.get(MSG_KEY_STEP_NAME) == STEP_NAME_FINAL_ANSWER:
                    self.result = s.get(MSG_KEY_RAW_TEXT, self.result)
                    break
        # Strip unexpected task manifest frontmatter from the final answer
        self.result = self._strip_task_manifest(self.result)
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
                    print_tool.print_error(f"{LLM_KEYWORD_MISTAKE}: give final due to duplicate to [{ori_step_name}] only")

                if step_name in keys:
                    if len(response) == 1:
                        if step.get("raw_text") and 'final_answer' in step["raw_text"]:
                            step_name = "final"
                            print_tool.print_error(f"{LLM_KEYWORD_MISTAKE}: give final due to found 'final_answer'")

        self._last_step_name = step_name
        self._last_step_count = len(response)
        return (step_name, step)
