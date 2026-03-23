'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-22
  Purpose:
'''

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
    """ chatting with LLM """
    def __init__(self, prompt_ctl:PromptBase, llm_model:LLMModelBase):
        self.prompt_ctl:PromptBase = prompt_ctl
        self.llm_model:LLMModelBase = llm_model

        self.first_message = ""
        self.last_message = ""
        return

    def chat(self, message:str="", need_print=True) -> str:
        """ chatting to LLM, return answer """
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
        message:str=None,
        session_id:str=None,
        system_prompt:str="",
        more_prompt:str="",

        # llm parameters
        max_tokens:int=3000,
        temperature:float=0.97,

        need_stdout:bool=True,
        need_input_message:bool=True,
        need_print_session:bool=True,
        need_print_message:bool=True,
        func_formatter_messages=None,
    ) -> LLMChat:
    """ get a object for chatting.

    Args:
        session_id, set an empty string to indicate non-use, set None to get it by environ
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
