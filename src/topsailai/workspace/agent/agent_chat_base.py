'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-02
  Purpose:
'''

import os

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
)
from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
)
from topsailai.context import ctx_manager
from topsailai.workspace.context.ctx_runtime import (
    ContextRuntimeData,
)
from topsailai.workspace.context.agent import (
    ContextRuntimeAIAgent,
)
from topsailai.workspace.context.instruction import (
    ContextRuntimeInstructions,
)
from topsailai.workspace.hook_instruction import HookInstruction
from topsailai.workspace.plugin_instruction.base.cache import set_ai_agent
from topsailai.workspace.agent.agent_constants import (
    DEFAULT_HEAD_TAIL_OFFSET,
)


class AgentChatBase(object):
    """AI Agent controller for managing human-agent and agent-LLM conversations.

    This class coordinates the interaction between a human user and an AI agent,
    handling message routing, context management, and session lifecycle.
    """

    def __init__(
            self,
            hook_instruction:HookInstruction,
            ctx_rt_aiagent:ContextRuntimeAIAgent,
            ctx_rt_instruction:ContextRuntimeInstructions,

            session_head_tail_offset:int=DEFAULT_HEAD_TAIL_OFFSET, # cut messages
        ):
        """Initialize the AgentChat controller.

        Args:
            hook_instruction: Hook instruction instance for input handling.
            ctx_rt_aiagent: Context runtime AI agent instance.
            ctx_rt_instruction: Context runtime instructions instance.
            session_head_tail_offset: Number of messages to keep from head and tail
                                      when truncating conversation history. Defaults to 7.
        """
        self.hook_instruction = hook_instruction
        self.ctx_rt_aiagent = ctx_rt_aiagent
        self.ctx_rt_instruction = ctx_rt_instruction
        ctx_runtime_data = ctx_rt_aiagent.ctx_runtime_data
        self.ai_agent = ctx_rt_aiagent.ai_agent

        self.first_message = None
        self.last_message = None

        if session_head_tail_offset is None:
            session_head_tail_offset = DEFAULT_HEAD_TAIL_OFFSET
        self.session_head_tail_offset = session_head_tail_offset

        set_ai_agent(self.ai_agent)

        ##########################################################################################
        # Agent HOOKS
        ##########################################################################################
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        # hook(self)
        self.hooks_pre_run = get_hooks("pre_run")
        self.hooks_for_final_answer = get_hooks("post_final_answer")

        if env_tool.EnvReaderInstance.get("TOPSAILAI_HOOK_FINAL_SUMMARIZE_INTO_SESSION"):
            def hook_final_summarize_into_session(_) -> None:
                """ summarize messages of agent2llm, save summary content to session of user2agent """
                summary_content = ctx_runtime_data.summarize_messages_for_processing()
                if summary_content:
                    ctx_runtime_data.add_session_message(ROLE_ASSISTANT, summary_content)
                return
            self.hooks_for_final_answer.append(hook_final_summarize_into_session)

        ##########################################################################################
        # Hook Agent
        ##########################################################################################

        def hook_after_init_prompt(_ai_agent):
            """Hook function called after agent prompt initialization.

            Adds existing session messages to the agent's message history.
            Truncates messages if session_head_tail_offset is configured.

            Args:
                _ai_agent: The agent instance to operate on.
            """
            ctx_runtime_data.reset_messages()

            # cut messages
            if session_head_tail_offset and ctx_runtime_data.messages:
                new_messages = ctx_manager.cut_messages(
                    ctx_runtime_data.messages,
                    session_head_tail_offset,
                )
                if new_messages is not ctx_runtime_data.messages or \
                    len(new_messages) != len(ctx_runtime_data.messages) or \
                    new_messages[-1] != ctx_runtime_data.messages[-1] or \
                        new_messages[0] != ctx_runtime_data.messages[0]:
                    ctx_runtime_data.set_messages(new_messages)

            # add messages to agent
            ctx_rt_aiagent.add_runtime_messages()

            return

        def hook_after_new_session(_ai_agent):
            """Hook function called after a new session is created.

            Adds the initial session message to the context for tracking.

            Args:
                _ai_agent: The agent instance to operate on.
            """
            ctx_rt_aiagent.add_session_message()
            return

        def hook_summarize_messages(_ai_agent):
            """Summarize context messages to reduce token usage.

            Checks if message summarization is needed for either processed Q&A messages
            or currently processing agent messages, and performs summarization if required.

            Args:
                _ai_agent: The agent instance to operate on.
            """

            # the processed Q&A messages
            if ctx_runtime_data.is_need_summarize_for_processed():
                ctx_runtime_data.summarize_messages_for_processed()

            # the processing agent messages
            if ctx_runtime_data.is_need_summarize_for_processing():
                ctx_runtime_data.summarize_messages_for_processing()

            return

        # add hooks
        self.ai_agent.hooks_after_init_prompt.append(hook_after_init_prompt)
        self.ai_agent.hooks_after_new_session.append(hook_after_new_session)
        self.ai_agent.hooks_pre_chat.append(hook_summarize_messages)

        return

    @property
    def agent_name(self) -> str:
        """Get the name of the AI agent.

        Returns:
            str: The agent's name string.
        """
        return self.ai_agent.agent_name

    @property
    def messages(self) -> list:
        """Get the current conversation messages.

        Returns:
            list: List of message dictionaries in the conversation.
        """
        return self.ai_agent.messages

    @property
    def ctx_runtime_data(self) -> ContextRuntimeData:
        """Get the context runtime data instance.

        Returns:
            ContextRuntimeData: The runtime data object containing session context.
        """
        return self.ctx_rt_aiagent.ctx_runtime_data

    def call_hooks_pre_run(self):
        """Execute all pre-run hooks registered in the hooks_pre_run list.

        Iterates through each registered hook function and executes it with
        the current AgentChat instance as the argument. Any exceptions raised
        by hooks are logged but do not stop execution of remaining hooks.
        """
        for hook in self.hooks_pre_run:
            try:
                hook(self)
            except Exception as e:
                logger.exception("call hook_pre_run failed [%s]: %s", hook, e)
                # continue
        return

    def call_hook_for_final_answer(self):
        """
        Iterates through each registered hook function and executes it with
        the current AgentChat instance as the argument. Any exceptions raised
        by hooks are logged but do not stop execution of remaining hooks.
        """
        for hook in self.hooks_for_final_answer:
            try:
                hook(self)
            except Exception as e:
                logger.exception("call hook_for_final_answer failed [%s]: %s", hook, e)
                # continue
        return

    def hook_build_answer(self, answer:str, need_symbol:bool=False) -> str:
        """Build and format the final answer string.

        Optionally prepends a symbol to the answer based on configuration.
        The symbol is determined by environment variable TOPSAILAI_SYMBOL_STARTSWITH_ANSWER
        or defaults to "From '{agent_name}':\n".

        Args:
            answer: The raw answer string from the agent.
            need_symbol: Whether to prepend a symbol. Defaults to False.

        Returns:
            str: The formatted answer string.
        """
        if not answer:
            return answer

        if need_symbol:
            # symbol
            symbol_start = os.getenv("TOPSAILAI_SYMBOL_STARTSWITH_ANSWER")
            if not symbol_start and self.agent_name:
                symbol_start = f"From '{self.agent_name}':\n"
            if symbol_start and symbol_start not in answer[:len(symbol_start)+17]:
                answer = symbol_start + answer

        return answer

    def hook_for_answer(self, answer:str):
        """Perform post-processing actions on the answer.

        Currently handles saving the answer to a file if the environment variable
        TOPSAILAI_SAVE_RESULT_TO_FILE is set.

        Args:
            answer: The answer string to process.
        """
        if not answer:
            return

        # save answer to file
        file_path_result = os.getenv("TOPSAILAI_SAVE_RESULT_TO_FILE")
        if file_path_result:
            with open(file_path_result, encoding='utf-8', mode='w') as fd:
                fd.write(answer)

        return
