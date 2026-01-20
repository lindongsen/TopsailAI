#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-20
  Purpose:
  Env:
    @SESSION_ID: required, string;
    @SYSTEM_PROMPT: file or content;
    @TEAM_PROMPT: required, file or content;
    @TEAM_PATH: required, the team folder;
'''

import os
import sys
import yaml
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.ai_base.agent_types import (
    react,
    exception as agent_exception,
)
from topsailai.context import ctx_manager
from topsailai.utils import (
    env_tool,
    time_tool,
    file_tool,
    json_tool,
)
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
)
from topsailai.workspace.hook_instruction import HookInstruction
from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.workspace.print_tool import (
    print_context_messages,
)

from topsailai.tools.agent_tool import subprocess_agent_memory_as_story


PROMPT_FILE_AI_TEAM = f"{project_root}/cli/ai_team.md"

def get_team_list() -> list[dict]:
    team_path = os.getenv("TEAM_PATH")
    assert team_path and os.path.isdir(team_path), f"invalid team path: {team_path}"

    team_list = []
    for f in os.listdir(team_path):
        if not f.endswith(".member"):
            continue

        member = {
            "member_id": "",
            "member_name": "",
            "member_info": "",
            "is_able_to_call_chat": False,
            "is_able_to_call_agent": False,
        }
        team_list.append(member)
        f_path = os.path.join(team_path, f)
        with open(f_path, encoding="utf-8") as fd:
            f_content = fd.read().strip()

        member["member_id"] = f_path
        member["member_name"] = os.path.basename(f_path).rsplit('.', 1)[0]
        member["member_info"] = f_content

        # ability
        for ext in ["chat", "agent"]:
            f_ext = f_path.rsplit('.', 1)[0] + "." + ext
            member[f"is_able_to_call_{ext}"] = os.path.exists(f_ext)
            if member[f"is_able_to_call_{ext}"]:
                os.system(f"chmod +x {f_ext}")

    return team_list

def generate_team_prompt(team_list:list[dict]):
    """generate prompt for team
    """
    assert team_list
    content = f"""

## Team Detail
```yaml
{yaml.safe_dump(team_list)}
```
"""
    return content

def generate_system_prompt():
    # team info
    team_list = get_team_list()
    team_info = generate_team_prompt(team_list)

    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    sys_prompt_file = ""
    sys_prompt_content = ""
    if env_sys_prompt:
        if os.path.exists(env_sys_prompt):
            sys_prompt_file = env_sys_prompt
        else:
            sys_prompt_content = env_sys_prompt

    if sys_prompt_file:
        with open(sys_prompt_file, encoding="utf-8") as fd:
            sys_prompt_content = fd.read().strip()

    # team prompt
    if not os.getenv("TEAM_PROMPT"):
        os.environ["TEAM_PROMPT"] = PROMPT_FILE_AI_TEAM
    env_team_prompt = os.getenv("TEAM_PROMPT")
    _, team_prompt_content = file_tool.get_file_content_fuzzy(env_team_prompt)
    if team_prompt_content:
        sys_prompt_content += team_prompt_content.strip()

    # team info
    sys_prompt_content += team_info

    os.environ["SYSTEM_PROMPT_CONTENT"] = sys_prompt_content

    print(sys_prompt_content)

    return sys_prompt_content

def main():
    """ main entry """
    load_dotenv()
    message = None

    # prompt
    sys_prompt_content = generate_system_prompt()

    # agent
    agent = get_agent_chat(sys_prompt_content, disabled_tools=["agent_tool"])
    agent.agent_name = "AITeam"

    # llm
    llm_model = agent.llm_model
    llm_model.max_tokens = max(1600, llm_model.max_tokens)
    llm_model.temperature = max(0.97, llm_model.temperature)

    # session
    session_id = os.getenv("SESSION_ID") or time_tool.get_current_date(with_t=True)
    messages_from_session = None
    if session_id:
        os.environ["SESSION_ID"] = session_id
        print(f"session_id: {session_id}")

        messages_from_session = ctx_manager.get_messages_by_session(session_id)
        if not messages_from_session:
            message = get_message()
            ctx_manager.create_session(session_id, task=message[:100])

    if not messages_from_session:
        messages_from_session = []

    ##########################################################################################
    # Hook Agent
    ##########################################################################################

    def add_session_message():
        if session_id:
            ctx_manager.add_session_message(session_id, agent.messages[-1])
        messages_from_session.append(agent.messages[-1])

    def hook_after_init_prompt(self):
        if messages_from_session:
            self.messages += messages_from_session

    def hook_after_new_session(self):
        add_session_message()

    agent.hooks_after_init_prompt.append(hook_after_init_prompt)
    agent.hooks_after_new_session.append(hook_after_new_session)

    ##########################################################################################
    # Hook Instruction
    ##########################################################################################

    hook_instruction = HookInstruction()
    def _clear():
        if session_id:
            print(f"{message}: Context cannot be clear due to exist session_id({session_id})")
        else:
            # clear context messages
            messages_from_session.clear()
            print("/clear: Context already is clear")
        return
    def _story():
        if not messages_from_session:
            return
        pid = subprocess_agent_memory_as_story(messages_from_session)
        print(f"/story: The history messages will be save to a new story, pid=[{pid}]")
        return
    def _history():
        print(f"/history: Show history messages {session_id}")
        if messages_from_session:
            print_context_messages(messages_from_session)
        return
    hook_instruction.add_hook("/clear", _clear, "clear context messages")
    hook_instruction.add_hook("/story", _story, "save context messages to a story")
    hook_instruction.add_hook("/history", _history, "show context messages")

    ##########################################################################################
    # main
    ##########################################################################################
    if session_id:
        _history()

    if not message:
        message = get_message(hook_instruction)

    max_count = 100
    while True:
        answer = ""
        max_count -= 1

        try:
            answer = agent.run(react.Step4ReAct(True), message)
        except agent_exception.AgentEndProcess:
            pass
        except KeyboardInterrupt:
            if not input_yes("Agent Session Continue [yes/no] "):
                break

        if answer:
            add_session_message()

        print("\n\n--------------------------------------------------------------------------------\n\n")
        messages_from_session = ctx_manager.get_messages_by_session(session_id)
        _history()

        if answer and not env_tool.is_debug_mode():
            print()
            print(">>> answer:")
            print(answer)

        print()
        if max_count == 0:
            break

        while True:
            message = input_message(hook=hook_instruction)
            message = message.strip()
            if message:
                break

    return


if __name__ == "__main__":
    main()
