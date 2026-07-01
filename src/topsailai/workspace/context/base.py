"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-23
Purpose: Context runtime base module for managing chat sessions and message handling.
"""

import random

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_USER,
    STEP_NAME_TASK,
)
from topsailai.ai_base.agent_base import (
    AgentBase,
)
from topsailai.context import ctx_manager
from topsailai.context.token import count_tokens
from topsailai.tools import (
    story_tool,
)
from topsailai.utils import (
    json_tool,
    env_tool,
    file_tool,
    print_tool,
)
from topsailai.workspace.llm_shell import get_llm_chat
from topsailai.workspace.context import summary_tool


class ContextRuntimeBase(object):
    """
    Context manager for runtime (session).

    Manages user chat sessions and maintains message history between users and agents.

    Variables:
        self.messages: User chats to agent in the current session.
        self.ai_agent.messages: Agent chats to LLM.
    """

    def __init__(self):
        """
        Initialize the ContextRuntimeBase instance.

        Sets up default values for session ID, messages list, and AI agent reference.
        """
        self.session_id = ""
        self.messages = []
        self.ai_agent: AgentBase = None

    @property
    def last_user_message(self):
        """
        Get the last user message from self.messages of current session.

        IMPORTANT DESIGN NOTE:
        This property intentionally scans self.messages (the User2Agent persisted
        session layer), NOT self.ai_agent.messages (the Agent2LLM ephemeral ReAct
        context). The "last user message" is defined as the most recent real human
        input to the agent. The Agent2LLM layer contains internal user-role messages
        such as tool observations and task injections, which must NOT be treated as
        the last user message. When Agent2LLM summarization needs to preserve the
        last user message, it relies on this property to obtain the correct human
        message from the User2Agent session.

        Returns:
            dict or None: The last message from ROLE_USER, or None if not found.
        """
        last_user_msg = None
        for msg in reversed(self.messages):
            msg_dict = json_tool.json_load(msg)
            if msg_dict["role"] == ROLE_USER:
                last_user_msg = msg
                break
        return last_user_msg

    def init(self, session_id: str, ai_agent: AgentBase):
        """
        Initialize the context runtime with session ID and AI agent.

        Args:
            session_id (str): Unique identifier for the session.
            ai_agent (AgentBase): The AI agent instance to use for processing.

        Returns:
            None
        """
        self.session_id = session_id
        self.ai_agent = ai_agent
        self.reset_messages()
        return

    def append_message(self, message: dict):
        """
        Append a message to the in-memory messages list.

        The generic name is intentional: this method operates on the in-memory
        ``self.messages`` list, not on persistent session storage. Names like
        ``append_session_message`` would incorrectly imply a storage operation.

        Args:
            message (dict): The message dictionary to append.

        Returns:
            None
        """
        if not message:
            return

        self.messages.append(message)

    def set_messages(self, value: list):
        """
        Set a new value for the in-memory messages list.

        Replaces all existing messages with the provided list. The replacement
        is performed in-place (clear + extend) so that the ``self.messages``
        object reference is preserved and any external references to the same
        list remain valid.

        The generic name is intentional: this method operates on the in-memory
        ``self.messages`` list, not on persistent session storage. Names like
        ``set_session_messages`` would incorrectly imply a storage operation.

        Args:
            value (list): New list of messages to set.

        Returns:
            None
        """
        if not value:
            value = []
        if value is self.messages:
            return
        self.messages.clear()
        self.messages += value
        return

    def reset_messages(self):
        """
        Reset the in-memory messages list from session storage.

        Retrieves messages from the session storage and updates the in-memory
        ``self.messages`` list via ``set_messages``.

        The generic name is intentional: this method operates on the in-memory
        ``self.messages`` list, not on persistent session storage. Names like
        ``reset_session_messages`` would incorrectly imply a storage operation.

        Returns:
            None
        """
        if self.session_id:
            messages_from_session = ctx_manager.get_messages_by_session(self.session_id) or []
            self.set_messages(messages_from_session)
        return

    def delete_message(self, index: int):
        """
        Delete a single message from the in-memory messages list by index.

        This mutates the list in-place, which is safe because it does not
        replace the ``self.messages`` reference. The method is kept as a
        controlled mutator entry point so that all deletions go through the
        same API.

        Args:
            index (int): Zero-based index of the message to remove.

        Raises:
            AssertionError: If index is out of the valid range.

        Returns:
            None
        """
        assert 0 <= index < len(self.messages), "index out of range"

        del self.messages[index]
        return

    def clear_messages(self):
        """
        Clear all messages from the in-memory messages list.

        This mutates the list in-place, which is safe because it does not
        replace the ``self.messages`` reference. The method is kept as a
        controlled mutator entry point so that all clear operations go through
        the same API.

        Returns:
            None
        """
        self.messages.clear()
        return

    ###############################################################
    # Summarization message-structure helpers
    ###############################################################
    #
    # Clarified design for context summarization (both User2Agent and Agent2LLM):
    #
    #   final new_messages = head_portion + [summary_answer] + [last_user_message]
    #
    # - head_portion: messages from the beginning of the list up to and
    #   including the first message whose role == "user" and step_name == "task".
    #   The variable `keeping_messages` (formerly `task_messages`) represents
    #   this head_portion, NOT the set of all task messages.
    # - summary_answer: exactly one assistant message produced by _summarize_messages.
    # - last_user_message: exactly one final user message kept at the tail.
    #
    # The summarizer still receives the current runtime messages. In the default
    # "runtime" summary mode the LLM is fed from the layer's full runtime message
    # store (self.messages for User2Agent, self.ai_agent.messages for Agent2LLM),
    # so the wrapper argument is the runtime messages while the actual summary
    # context is the full runtime history.
    ###############################################################

    @staticmethod
    def _is_task_message(msg) -> bool:
        """
        Check whether a message is a user task message that must be preserved.

        A task message is identified by:
        - role == "user"
        - content is a dict (or JSON object) with step_name == "task"

        Args:
            msg: A message dict or JSON-serialized message string.

        Returns:
            bool: True if the message is a task message, False otherwise.
        """
        msg_dict = json_tool.safe_json_load(msg)
        if not isinstance(msg_dict, dict):
            return False
        if msg_dict.get("role") != ROLE_USER:
            return False
        content = msg_dict.get("content")
        if isinstance(content, dict):
            return content.get("step_name") == STEP_NAME_TASK
        if isinstance(content, str):
            try:
                parsed = json_tool.json_load(content)
                if isinstance(parsed, dict):
                    return parsed.get("step_name") == STEP_NAME_TASK
            except Exception:
                pass
        return False

    def _split_task_messages(self, messages: list) -> tuple[list, list]:
        """
        Split messages into task messages and non-task messages.

        Args:
            messages (list): The original message list.

        Returns:
            tuple[list, list]: (task_messages, non_task_messages) in original order.
        """
        task_messages = []
        non_task_messages = []
        for msg in messages:
            if self._is_task_message(msg):
                task_messages.append(msg)
            else:
                non_task_messages.append(msg)
        return task_messages, non_task_messages

    def _get_messages_before_first_user_task_message(self, messages: list, max_count:int=7) -> list:
        """
        Build the head_portion used by context summarization.

        The head_portion contains messages from the beginning of `messages`
        up to and including the first message whose role == "user" and
        step_name == "task". It is stored in the `keeping_messages` variable
        in the summarizers. Messages after this head_portion (except the
        last user message) are summarized.

        Args:
            messages (list): The message list to scan.
            max_count (int): Safety cap on how far to scan when no task
                message is found. Defaults to 7.

        Returns:
            list: The head_portion messages in original order.
        """
        head_messages = []
        for i, msg in enumerate(messages):
            head_messages.append(msg)
            if self._is_task_message(msg):
                break
            if i > max_count:
                break
        return head_messages

    def _get_first_and_last_task_messages(self, messages: list) -> list:
        task_messages, _ = self._split_task_messages(messages)
        if not task_messages:
            return []
        first_and_last_task_messages = []
        if task_messages:
            first_and_last_task_messages = [
                task_messages[0],
                task_messages[-1],
            ]
            if task_messages[0] is task_messages[-1]:
                first_and_last_task_messages = [task_messages[0]]
        return first_and_last_task_messages

    def _merge_task_messages(
            self,
            original_messages: list,
            new_messages: list,
            task_messages: list,
        ) -> list:
        """
        Merge the head_portion back into the summarized message list.

        `task_messages` here is actually the head_portion: messages from the
        beginning of the original list up to and including the first user task
        message. They are re-inserted into new_messages so the final structure
        remains:

            head_portion + [summary_answer] + [last_user_message]

        Each head_portion message is placed immediately after its original
        predecessor if that predecessor survived summarization. If the
        predecessor was summarized away, the message is inserted right before
        the summary message, keeping chronological order relative to the
        summary and any surviving tail messages.

        Args:
            original_messages (list): The full original message list, including
                the head_portion messages that were split out.
            new_messages (list): The post-summary message list without the
                head_portion (typically head_offset + session + summary +
                last user message).
            task_messages (list): The head_portion messages to preserve.

        Returns:
            list: The merged message list with the head_portion in place.
        """
        if not task_messages:
            return new_messages
        task_ids = {id(m) for m in task_messages}
        original_ids = {id(m) for m in original_messages}
        new_ids = {id(m) for m in new_messages}

        # Find each task message's predecessor in the original list.
        task_predecessors = {}
        for i, msg in enumerate(original_messages):
            if id(msg) in task_ids:
                task_predecessors[id(msg)] = original_messages[i - 1] if i > 0 else None

        # Locate the summary message: the first message in new_messages that did
        # not exist in original_messages (e.g. the LLM-generated summary).
        summary_index = None
        for i, msg in enumerate(new_messages):
            _id = id(msg)
            if _id not in original_ids:
                summary_index = i
                break

        # Track current positions in the result list for predecessor lookup.
        result = list(new_messages)
        positions = {id(m): i for i, m in enumerate(result)}

        for task_msg in task_messages:
            _id_task = id(task_msg)
            if _id_task in new_ids:
                continue
            predecessor = task_predecessors.get(_id_task)

            if predecessor is None:
                insert_pos = 0
            elif id(predecessor) in positions:
                insert_pos = positions[id(predecessor)] + 1
            else:
                # Predecessor was summarized; place task before the summary.
                insert_pos = summary_index if summary_index is not None else len(result)

            result.insert(insert_pos, task_msg)

            # Update positions for messages shifted by this insertion.
            for msg_id in list(positions.keys()):
                if positions[msg_id] >= insert_pos:
                    positions[msg_id] += 1
            positions[_id_task] = insert_pos

            # Summary index shifts if we inserted before it.
            if summary_index is not None and insert_pos <= summary_index:
                summary_index += 1

        return result

    ###############################################################
    # Env
    ###############################################################

    def _get_quantity_threshold(
            self,
            env_key: str = "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
        ) -> int:
        """
        Get the quantity threshold for message summarization.

        The layer-specific env variable (env_key) takes precedence.
        If it is unset or empty, fall back to the legacy shared variable
        TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD for backward compatibility.
        If the final value is 0, null, or negative, summarization is disabled.

        Args:
            env_key (str): Primary environment variable name to read.
                Defaults to TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD.

        Returns:
            int: The quantity threshold value. Returns 0 if disabled.
        """
        # Read the layer-specific threshold first.
        env_quantity_threshold = env_tool.EnvReaderInstance.get(
            env_key,
            formatter=int,
        )

        # Fall back to the legacy shared threshold for backward compatibility.
        if not env_quantity_threshold or env_quantity_threshold < 0:
            env_quantity_threshold = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD",
                formatter=int,
            )

        # disabled
        if not env_quantity_threshold or env_quantity_threshold < 0:
            return 0

        number_list = [13, 17, 19, 23]
        quantity_threshold = max(random.choice(number_list), env_quantity_threshold)
        return quantity_threshold

    def _get_head_offset_to_keep_in_summary(
            self,
            head_offset_to_keep: int = None,
        ) -> int:
        """
        Get the head offset to keep in summary.

        Args:
            head_offset_to_keep (int, optional): If provided, use this value directly.
                If None, retrieve from environment variable.

        Returns:
            int: The head offset value to keep in summary. Always returns non-negative value.
        """
        if head_offset_to_keep is None:
            head_offset_to_keep = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP",
                default=0,
                formatter=int
            ) or 0

        if head_offset_to_keep < 0:
            head_offset_to_keep = 0

        return head_offset_to_keep

    def _get_token_calculation_messages(self):
        """
        Get the messages used for real-time token calculation.

        IMPORTANT DESIGN NOTE:
        This method intentionally returns self.ai_agent.messages when an agent is
        present, even for User2Agent-layer callers. self.messages (User2Agent session)
        is loaded as the starting prefix of self.ai_agent.messages via
        ContextRuntimeAIAgent.add_runtime_messages(), so self.ai_agent.messages
        already contains self.messages and represents the complete runtime context
        seen by the LLM. Both User2Agent and Agent2LLM summarization/token checks
        therefore use the same full context source.

        Subclasses should NOT override this method to return a different layer
        unless the layer semantics genuinely change. If a layer needs a different
        message source, add a new layer-specific helper instead.

        Returns:
            list | None: The messages to count, or None if not available.
        """
        if self.ai_agent:
            if self.ai_agent.messages is None:
                return None
            return self.ai_agent.messages[:]
        if self.messages is None:
            return None
        return self.messages[:]
    def _get_current_tokens(self, messages=None, realtime=False) -> int | None:
        """
        Get the current token count.

        When TOPSAILAI_REALTIME_TOKEN_CALCULATION is enabled, tokens are
        calculated from the provided messages (or the layer-appropriate
        message source). Otherwise, the cached tokenStat.current_tokens value
        is returned for backward compatibility.

        Args:
            messages (list | str, optional): Messages to count. If None, the
                layer-appropriate message source is used.

        Returns:
            int | None: The current token count, or None if not available.
        """
        if messages:
            realtime = True
        if not realtime:
            realtime = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_REALTIME_TOKEN_CALCULATION", False
            )
        if realtime:
            if messages is None:
                messages = self._get_token_calculation_messages()
            if messages is None:
                return None
            try:
                return int(count_tokens(str(messages)))
            except Exception:
                return None

        try:
            if self.ai_agent and self.ai_agent.llm_model and self.ai_agent.llm_model.tokenStat:
                return int(self.ai_agent.llm_model.tokenStat.current_tokens)
        except Exception:
            pass
        return None

    def _check_summarize_token_reduction(
            self,
            method_name: str,
            before_tokens: int | None,
            after_tokens: int | None,
        ) -> None:
        """
        Emit a critical log if summarization did not reduce token count.

        This helper is called immediately after a summarization method rebuilds
        the runtime message list. If the post-summarization token count is not
        strictly lower than the pre-summarization count, something went wrong
        (e.g. the summary was longer than the original context or token
        accounting is inconsistent) and operators should be alerted.

        Args:
            method_name (str): Name of the summarization method being checked.
            before_tokens (int | None): Token count before summarization.
            after_tokens (int | None): Token count after summarization.

        Returns:
            None
        """
        if before_tokens is None or after_tokens is None:
            return
        if after_tokens >= before_tokens:
            logger.critical(
                f"[{method_name}] token count did not decrease after summarization: "
                f"before_tokens={before_tokens}, after_tokens={after_tokens}, "
                f"session_id={self.session_id or ''}"
            )
        return

    ###############################################################
    # Summary
    ###############################################################

    def _get_summary_prompt(
            self,
            prompt: str = None,
            extra_prompt: str=None,
        ) -> str:
        # prompt
        prompt_content = ""
        if prompt is None:
            prompt = env_tool.EnvReaderInstance.get("TOPSAILAI_SUMMARY_PROMPT")
        _, prompt_content = file_tool.get_file_content_fuzzy(prompt)
        if not prompt_content:
            prompt_content = ""

        # extra prompt
        extra_prompt_content = ""
        if extra_prompt is None:
            extra_prompt = summary_tool.get_summary_prompt(self.ai_agent.agent_type)
            if not extra_prompt:
                if self.ai_agent.agent_type.lower().endswith("community"):
                    extra_prompt = story_tool.PROMPT_SUMMARY_MEMORY
                else:
                    extra_prompt = story_tool.PROMPT_SUMMARY_TASK
            extra_prompt_content = extra_prompt
        else:
            _, extra_prompt_content = file_tool.get_file_content_fuzzy(extra_prompt)
            if not extra_prompt_content:
                extra_prompt_content = ""

        return extra_prompt_content + prompt_content


    def _summarize_messages(
            self,
            messages,
            prompt: str = None,
            extra_prompt: str=None,
        ):
        """
        Summarize messages into a single text using LLM.

        The caller passes the current runtime messages, which is the expected
        input. In the default "runtime" summary mode the actual messages fed
        to the LLM are taken from the layer's full runtime message store
        (self.messages for User2Agent, self.ai_agent.messages for Agent2LLM),
        so the wrapper receives runtime messages while the summary itself is
        built from the full runtime context.

        Args:
            messages: The runtime messages passed by the caller. Can be a
                string or list/dict.
            prompt (str, optional): Custom prompt for summarization. If None, uses
                default from environment variable.

        Returns:
            tuple: A tuple containing (llm_chat, answer) where:
                - llm_chat: The LLM chat instance used for summarization
                - answer (str): The summarized text response from LLM

        Raises:
            AssertionError: If messages is null/empty.
        """
        # switch to summary-runtime mode
        if env_tool.EnvReaderInstance.get("TOPSAILAI_CONTEXT_SUMMARY_MODE") == "runtime":
            return self._summarize_runtime_messages(
                messages, prompt=prompt, extra_prompt=extra_prompt,
            )

        # message
        assert messages, "null of messages"
        message_title = """
---
Summarize Messages
---
"""
        one_msg = messages if isinstance(messages, str) else json_tool.json_dump(messages)

        llm_chat = get_llm_chat(
            message=message_title + one_msg,
            session_id="",
            system_prompt=self._get_summary_prompt(prompt=prompt, extra_prompt=extra_prompt),

            need_stdout=env_tool.is_interactive_mode(),
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        answer = llm_chat.chat(
            need_print=env_tool.is_interactive_mode(),
            need_env_message=False,
        )

        return (llm_chat, answer)


    def _summarize_runtime_messages(
            self,
            messages,
            prompt: str = None,
            extra_prompt: str=None,
        ):
        """
        Runtime-mode summarization.

        The LLM summary is built from the layer's full runtime message store
        (self.messages for User2Agent, self.ai_agent.messages for Agent2LLM).
        The `messages` argument is retained for API compatibility and is used
        only as a fallback when the layer-specific runtime store is unavailable.

        Args:
            messages: Fallback messages passed by the caller.
            prompt (str, optional): Custom prompt for summarization.
            extra_prompt (str, optional): Extra prompt appended to the summary
                instructions.

        Returns:
            tuple: (llm_chat, answer) from the summarization chat.
        """
        all_messages = self._get_token_calculation_messages()
        if not all_messages:
            print_tool.print_error("[summarize_runtime_messages] no found runtime-messages, fallback to passed-messages")
            all_messages = messages
        # Defensive fallback: if the runtime-derived message list is unexpectedly
        # shorter than the caller-supplied messages, prefer the passed-in messages.
        # This protects against cases where the runtime store has been partially
        # pruned or desynchronized, ensuring we do not summarize an incomplete or
        # stale context. The passed-in messages are the authoritative view from
        # the layer that triggered summarization.
        if all_messages and messages and len(all_messages) < len(messages):
            print_tool.print_step("[summarize_runtime_messages] use passed-messages due to larger length", need_format=False, need_log=True)
            all_messages = messages
        assert all_messages, "null of messages"
        print_tool.print_step(f"[summarize_runtime_messages] All of messages: length=[{len(all_messages)}]", need_format=False, need_log=True)

        llm_chat = get_llm_chat(
            message="> SUMMARIZE MESSAGES",
            session_id="",
            system_prompt="",

            need_stdout=env_tool.is_interactive_mode(),
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        llm_chat.prompt_ctl.messages = all_messages[:]
        TIPS = "\n> DONOT INVOKE ANY TOOLS, DIRECTLY OUTPUT FINAL_ANSWER!"
        answer = llm_chat.chat(
            self._get_summary_prompt(prompt=prompt, extra_prompt=extra_prompt) + TIPS,
            need_print=env_tool.is_interactive_mode(),
            need_env_message=False,
        )

        return (llm_chat, answer)
