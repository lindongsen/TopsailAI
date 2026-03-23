"""
LLM Shell Module.

This module provides functionality for interacting with Large Language Models (LLM).
It includes the LLMChat class for managing chat sessions and a factory function
for creating chat instances with various configuration options.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-22
Purpose: Provides LLM chat interface for the TopsailAI framework.
"""

import os

from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.base_class import ContentStdout
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.ai_base.llm_control.base_class import LLMModelBase
from topsailai.utils.thread_local_tool import (
    set_thread_var,
    KEY_SESSION_ID,
    set_thread_name,
)
from topsailai.utils import (
    file_tool,
)
from topsailai.workspace.input_tool import get_message
from topsailai.context import ctx_manager


class LLMChat(object):
    """
    A class for managing chat interactions with a Large Language Model (LLM).
    
    This class handles the conversation flow between the user and the LLM,
    including message management, prompt control, and response handling.
    
    Attributes:
        prompt_ctl (PromptBase): The prompt controller managing conversation messages.
        llm_model (LLMModelBase): The LLM model instance for generating responses.
        first_message (str): The first message in the conversation.
        last_message (str): The last response received from the LLM.
    """
    
    def __init__(self, prompt_ctl: PromptBase, llm_model: LLMModelBase):
        """
        Initialize the LLMChat instance.
        
        Args:
            prompt_ctl (PromptBase): The prompt controller for managing messages.
            llm_model (LLMModelBase): The LLM model instance for generating responses.
        """
        self.prompt_ctl: PromptBase = prompt_ctl
        self.llm_model: LLMModelBase = llm_model

        self.first_message = ""
        self.last_message = ""
        return

    def chat(self, message: str = "", need_print: bool = True) -> str:
        """
        Send a message to the LLM and receive a response.
        
        This method adds the user's message to the prompt controller, updates
        the environment variables, sends the conversation to the LLM, and
        returns the assistant's response.
        
        Args:
            message (str, optional): The user's message to send to the LLM.
                Defaults to empty string.
            need_print (bool, optional): Whether to print the message before
                sending. Defaults to True.
        
        Returns:
            str: The LLM's response message, or empty string if no response.
        """
        if message:
            self.prompt_ctl.add_user_message(message, need_print=need_print)

        self.prompt_ctl.update_message_for_env()

        answer = self.llm_model.chat(self.prompt_ctl.messages, for_raw=True, for_stream=True)
        if answer:
            answer = str(answer).strip()
        self.prompt_ctl.add_assistant_message(answer)
        self.last_message = answer
        return answer


def get_llm_chat(
        message: str = None,
        session_id: str = None,
        system_prompt: str = "",
        more_prompt: str = "",
        max_tokens: int = 3000,
        temperature: float = 0.97,
        need_stdout: bool = True,
        need_input_message: bool = True,
        need_print_session: bool = True,
        need_print_message: bool = True,
        func_formatter_messages=None,
    ) -> LLMChat:
    """
    Create and return an LLMChat instance for interacting with a Large Language Model.
    
    This factory function initializes an LLM chat session with the specified parameters.
    It handles session management, prompt configuration, and model initialization.
    If no session_id is provided, it will attempt to retrieve it from environment variables.
    If no message is provided, it will prompt the user for input.
    
    Args:
        message (str, optional): The initial message to send to the LLM.
            If None and need_input_message is True, will prompt for user input.
        session_id (str, optional): The session identifier for maintaining conversation
            history. If None, will attempt to get from SESSION_ID environment variable.
            If empty string, session management is disabled.
        system_prompt (str, optional): The system prompt to use for the LLM.
            If empty, will attempt to get from SYSTEM_PROMPT environment variable.
        more_prompt (str, optional): Additional prompt content to append to the system prompt.
        max_tokens (int, optional): Maximum number of tokens in the LLM response.
            Defaults to 3000.
        temperature (float, optional): The temperature parameter for LLM generation.
            Defaults to 0.97.
        need_stdout (bool, optional): Whether to enable stdout content sending.
            Defaults to True.
        need_input_message (bool, optional): Whether to prompt for user input if
            message is not provided. Defaults to True.
        need_print_session (bool, optional): Whether to print the session_id when
            using session management. Defaults to True.
        need_print_message (bool, optional): Whether to print messages before
            sending to LLM. Defaults to True.
        func_formatter_messages (callable, optional): A function to format messages
            from session history. Defaults to None.
    
    Returns:
        LLMChat: An initialized LLMChat instance ready for conversation.
    
    Raises:
        AssertionError: If message is required but not provided.
    
    Example:
        >>> chat = get_llm_chat(message="Hello, how are you?")
        >>> response = chat.chat()
        >>> print(response)
    """
    if not message:
        message = get_message(need_input=need_input_message)

    # session
    if session_id is None:
        session_id = os.getenv("SESSION_ID")

    messages_from_session = None
    if session_id:
        if need_print_session:
            print(f"session_id: {session_id}")

        set_thread_var(KEY_SESSION_ID, session_id)
        set_thread_name(session_id)

        messages_from_session = ctx_manager.get_messages_by_session(session_id)
        if not messages_from_session:
            assert message, "message is null"
            ctx_manager.create_session(session_id, task=message)
    else:
        assert message, "message is null"

    # system prompt
    if not system_prompt:
        system_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(system_prompt)
    _, more_prompt_content = file_tool.get_file_content_fuzzy(more_prompt)
    if more_prompt_content:
        sys_prompt_content += more_prompt_content

    llm_model = LLMModel()
    if need_stdout:
        llm_model.content_senders.append(ContentStdout())
    llm_model.max_tokens = max(3000, max_tokens, llm_model.max_tokens)
    llm_model.temperature = max(0.97, temperature, llm_model.temperature)

    prompt_ctl = PromptBase(sys_prompt_content or "You are a helpful assistant.")
    if messages_from_session:
        prompt_ctl.messages = func_formatter_messages(messages_from_session) if func_formatter_messages else messages_from_session
        if message:
            prompt_ctl.add_user_message(message, need_print=need_print_message)
    else:
        prompt_ctl.new_session(message, need_print_message=need_print_message)

    llm_chat = LLMChat(
        prompt_ctl,
        llm_model,
    )
    if message:
        llm_chat.first_message = message

    return llm_chat
