'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

import os
import yaml

from topsailai.utils import (
    env_tool,
    file_tool,
)
from topsailai.prompt_hub import prompt_tool
from topsailai.ai_team.role import (
    get_manager_prompt,
)

CWD = os.path.abspath(os.path.dirname(__file__))

PROMPT_FILE_AI_TEAM = f"{CWD}/ai_team.md"
PROMPT_FILE_AI_TEAM_MANAGER = f"{CWD}/ai_team_manager.md"

g_flag_only_agent = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_MANAGER_ONLY_AGENT")
if g_flag_only_agent:
    PROMPT_FILE_AI_TEAM_MANAGER = f"{CWD}/ai_team_manager_only_agent.md"


g_members = []

def get_members_cache() -> list:
    """ return members """
    return g_members

def get_team_list() -> list[dict]:
    """
    Get a list of team members from the TOPSAILAI_TEAM_PATH directory.

    Returns:
        list[dict]: A list of dictionaries containing member information, where each dict has:
            - member_id: The base name of the member file without extension
            - member_info: The content of the member file
            - is_able_to_call_chat: Boolean indicating if chat capability exists
            - is_able_to_call_agent: Boolean indicating if agent capability exists

    Raises:
        AssertionError: If TOPSAILAI_TEAM_PATH is not set or is not a valid directory
    """
    team_path = os.getenv("TOPSAILAI_TEAM_PATH")
    assert team_path and os.path.isdir(team_path), f"invalid team path: {team_path}"

    team_list = []
    for f in os.listdir(team_path):
        if not f.endswith(".member"):
            continue

        member = {
            "member_id": "",
            "member_info": "",
            "is_able_to_call_chat": False,
            "is_able_to_call_agent": False,
        }
        team_list.append(member)
        f_path = os.path.join(team_path, f)
        with open(f_path, encoding="utf-8") as fd:
            f_content = fd.read().strip()

        member["member_id"] = os.path.basename(f_path).rsplit('.', 1)[0]
        member["member_info"] = f_content

        # global vars
        g_members.append(member["member_id"])

        # ability
        for ext in ["chat", "agent"]:
            f_ext = f_path.rsplit('.', 1)[0] + "." + ext
            member[f"is_able_to_call_{ext}"] = os.path.exists(f_ext)
            if member[f"is_able_to_call_{ext}"]:
                os.system(f"chmod +x {f_ext}")

    return team_list


def generate_team_prompt(team_list: list[dict], only_agent: bool = True) -> str:
    """
    Generate a YAML-formatted prompt section for the team members.

    Args:
        team_list (list[dict]): List of team member dictionaries from get_team_list()
        only_agent (bool): If True, removes ability flags from the output. Defaults to True.

    Returns:
        str: A formatted string containing team details in YAML format

    Raises:
        AssertionError: If team_list is empty
    """
    assert team_list

    if only_agent:
        # remove is_able_to_call...
        new_team_list = []
        for team_info in team_list:
            new_team_info = team_info.copy()
            new_team_list.append(new_team_info)

            for key in list(new_team_info.keys()):
                if key.startswith("is_able_to_call_"):
                    del new_team_info[key]

        team_list = new_team_list

    content = f"""

## Team Detail
```yaml
{yaml.safe_dump(team_list)}
```
"""
    return content


def build_manager_message(message: str) -> str:
    """
    Build and return a modified message for the manager.

    This function checks if any team member is mentioned in the message (using @mention format).
    If a member is mentioned, it appends a note for the manager to use tool call.

    Args:
        message (str): The original message to be checked for member mentions.

    Returns:
        str: The modified message with additional instructions if a member is mentioned.
    """
    # case: @member
    for member_name in g_members:
        member_name = member_name.strip()
        if not member_name:
            continue
        if member_name in message or f'@{member_name}' in message:
            message += "\nManager to use tool call"
            break

    return message


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

    # collaboration prompt
    collaboration_prompt = prompt_tool.read_prompt("work_mode/sop/collaboration.md")

    # team role info
    sys_prompt_content += (
        get_manager_prompt() +
        manager_prompt_content +
        "\n\n---" +
        collaboration_prompt
    ) + "\n"

    return sys_prompt_content
