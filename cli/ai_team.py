#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-20
  Purpose: I am AI Manager who is a "Router and Coordinator"
  MD:
    "ai_team.md" is shared across the entire team;
    "ai_team_manager.md" is only used by the manager;
  Env:
    @SESSION_ID: required, string;
    @SYSTEM_PROMPT: file or content;
    @TOPSAILAI_TEAM_PROMPT: required, file or content;
    @TOPSAILAI_TEAM_PATH: required, the team folder;
    @TOPSAILAI_TEAM_AGENT_SESSION_NEED_SAVE_MESSAGE: team_agent can store the first message (task) and the last message (final_answer)
'''

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.ai_base.agent_types import (
    get_agent_step_call,
    exception as agent_exception,
)
from topsailai.ai_team.manager import (
    get_team_list,
    g_members,
    generate_team_prompt,
    build_manager_message,
)
from topsailai.ai_team.role import (
    get_manager_name,
    get_manager_prompt,
)
from topsailai.human.role import (
    get_human_name,
)
from topsailai.context import ctx_manager
from topsailai.utils import (
    env_tool,
    time_tool,
    file_tool,
)
from topsailai.workspace.input_tool import (
    get_message,
    input_message,
    input_yes,
    SPLIT_LINE,
)
from topsailai.workspace.hook_instruction import HookInstruction
from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.workspace.context.ctx_runtime import (
    ContextRuntimeInstructions,
    ContextRuntimeAIAgent,
    ContextRuntimeData,
)


DEFAULT_HEAD_TAIL_OFFSET = 7
PROMPT_FILE_AI_TEAM = f"{project_root}/cli/ai_team.md"
PROMPT_FILE_AI_TEAM_MANAGER = f"{project_root}/cli/ai_team_manager.md"

g_flag_only_agent = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_MANAGER_ONLY_AGENT")
if g_flag_only_agent:
    PROMPT_FILE_AI_TEAM_MANAGER = f"{project_root}/cli/ai_team_manager_only_agent.md"


def generate_system_prompt():
    """
    Generate the complete system prompt by combining multiple sources.

    Combines:
    - Team information from get_team_list() and generate_team_prompt()
    - System prompt from environment variable or file
    - Team prompt from environment variable or default file

    Returns:
        str: The complete system prompt content

    Environment Variables Used:
        SYSTEM_PROMPT: File path or content for system prompt
        TOPSAILAI_TEAM_PROMPT: File path for team prompt (defaults to PROMPT_FILE_AI_TEAM)
        TOPSAILAI_TEAM_PATH: Path to team member directory (used by get_team_list())
    """
    # team info
    team_list = get_team_list()
    team_info = generate_team_prompt(team_list, g_flag_only_agent)

    # system prompt
    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    # team prompt
    if not os.getenv("TOPSAILAI_TEAM_PROMPT"):
        os.environ["TOPSAILAI_TEAM_PROMPT"] = PROMPT_FILE_AI_TEAM
    env_team_prompt = os.getenv("TOPSAILAI_TEAM_PROMPT")
    _, team_prompt_content = file_tool.get_file_content_fuzzy(env_team_prompt)
    if team_prompt_content:
        sys_prompt_content += "\n" + team_prompt_content.strip()

    team_prompt_content += team_info

    # team info
    sys_prompt_content += team_info

    # agent will use this
    os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"] = team_prompt_content

    # print(team_prompt_content)

    # manager prompt
    _, manager_prompt_content = file_tool.get_file_content_fuzzy(PROMPT_FILE_AI_TEAM_MANAGER)

    # team role info
    sys_prompt_content += (
        get_manager_prompt() +
        manager_prompt_content +
        "\n\n---"
    )

    print(sys_prompt_content)

    return sys_prompt_content

def main():
    """ main entry """
    message = None

    # context runtime data
    ctx_runtime_data = ContextRuntimeData()

    # agent name
    manager_name = get_manager_name()

    # prompt
    sys_prompt_content = generate_system_prompt()

    # agent
    agent = get_agent_chat(sys_prompt_content, disabled_tools=["agent_tool"])
    agent.agent_name = manager_name

    # llm
    llm_model = agent.llm_model
    llm_model.max_tokens = max(1600, llm_model.max_tokens)
    llm_model.temperature = max(0.97, llm_model.temperature)

    # session
    session_id = os.getenv("SESSION_ID") or time_tool.get_current_date(with_t=True)
    if session_id:
        os.environ["SESSION_ID"] = session_id

        # basic info
        print(f"session_id: {session_id}")
        print(f"members: {g_members}")

        ctx_runtime_data.init(session_id, ai_agent=agent)
        if not ctx_runtime_data.messages:
            message = get_message()
            ctx_manager.create_session(session_id, task=message[:100])

    # context runtime xxx
    ctx_rt_aiagent = ContextRuntimeAIAgent(ctx_runtime_data)
    ctx_rt_instruction = ContextRuntimeInstructions(ctx_runtime_data)

    ##########################################################################################
    # Hook Agent
    ##########################################################################################

    def hook_after_init_prompt(ai_agent):
        """
        Hook function called after agent prompt initialization.
        Adds existing session messages to the agent's message history.

        Args:
            ai_agent: The agent instance
        """
        # offset
        if ctx_runtime_data.messages:
            head_tail_offset = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET",
                formatter=int,
            ) or DEFAULT_HEAD_TAIL_OFFSET

            new_messages = ctx_manager.cut_messages(
                ctx_runtime_data.messages,
                head_tail_offset
            )
            ctx_runtime_data.set_messages(new_messages)

        # add messages to agent
        ctx_rt_aiagent.add_runtime_messages()

        return

    def hook_after_new_session(ai_agent):
        """
        Hook function called after a new session is created.
        Adds the initial session message to the context.

        Args:
            ai_agent: The agent instance
        """
        ctx_rt_aiagent.add_session_message()

    agent.hooks_after_init_prompt.append(hook_after_init_prompt)
    agent.hooks_after_new_session.append(hook_after_new_session)

    ##########################################################################################
    # Hook Instruction
    ##########################################################################################

    hook_instruction = HookInstruction()
    hook_instruction.load_instructions(ctx_rt_instruction.instructions)

    def _member():
        """
        Display the list of team members.
        Shows separator line and all available team members.
        """
        print(f"\n\n{SPLIT_LINE}")
        print("/member: Show members")
        print(g_members)
        return

    hook_instruction.add_hook("/member", _member, "show members")

    ##########################################################################################
    # main
    ##########################################################################################
    if session_id:
        ctx_rt_instruction.history()
        _member()
        print(SPLIT_LINE + "\n\n")

    if not message:
        message = get_message(hook_instruction)

    # env
    human_name = get_human_name()

    curr_count = 0
    while True:
        answer = ""
        curr_count += 1

        try:
            if curr_count != 1:
                message = build_manager_message(message)
            answer = agent.run(get_agent_step_call(args=(True,)), f"{human_name} Say:\n" + message)
        except agent_exception.AgentEndProcess:
            pass
        except (KeyboardInterrupt, EOFError):
            if not input_yes("Agent Session Continue [yes/no] "):
                break

        if answer:
            ctx_rt_aiagent.add_session_message()

        ctx_runtime_data.reset_messages()
        ctx_rt_instruction.history()
        _member()

        if answer and not env_tool.is_debug_mode():
            print()
            print(">>> answer:")
            print(answer)

        print()
        print(f"The manager have scheduled tasks [{curr_count}] times")
        print()

        while True:
            message = input_message(hook=hook_instruction)
            message = message.strip()
            if message:
                break

    return


if __name__ == "__main__":
    main()
