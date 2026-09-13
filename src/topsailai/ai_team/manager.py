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
from topsailai.ai_team import prompt as team_prompt
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

    team_list.sort(key=lambda m: m["member_id"])
    g_members[:] = [m["member_id"] for m in team_list]

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


def generate_system_prompt(*, team_prompt_precomposed: bool = False) -> str:
    """Generate the Manager prompt and publish the team-wide plugin prompt.

    The Manager prompt follows the canonical order of base system prompt,
    runtime team prompt, shared team values, generated inventory, Manager role,
    and extra Manager prompts. ``team_prompt_precomposed`` is explicit caller
    provenance for a base prompt that already contains the two team-wide text
    segments.

    Returns:
        str: The complete Manager system prompt.
    """
    team_path = os.getenv("TOPSAILAI_TEAM_PATH")
    team_list = get_team_list()
    team_info = generate_team_prompt(team_list, g_flag_only_agent)

    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    if not os.getenv("TOPSAILAI_TEAM_PROMPT"):
        os.environ["TOPSAILAI_TEAM_PROMPT"] = PROMPT_FILE_AI_TEAM
    runtime_team_prompt = team_prompt.resolve_runtime_team_prompt(
        os.getenv("TOPSAILAI_TEAM_PROMPT")
    )
    team_values = team_prompt.load_team_values(team_path)

    team_wide_content = team_prompt.compose_team_prompt(
        team_prompt.TeamPromptSegments(
            runtime_team_prompt=runtime_team_prompt,
            team_values=team_values,
            team_inventory=team_info,
        )
    )
    os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"] = team_wide_content

    _, manager_prompt_content = file_tool.get_file_content_fuzzy(
        PROMPT_FILE_AI_TEAM_MANAGER
    )
    collaboration_prompt = prompt_tool.read_prompt("work_mode/sop/collaboration.md")
    manager_role_prompt = get_manager_prompt() + manager_prompt_content

    return team_prompt.compose_team_prompt(
        team_prompt.TeamPromptSegments(
            base_system_prompt=sys_prompt_content,
            runtime_team_prompt=runtime_team_prompt,
            team_values=team_values,
            team_inventory=team_info,
            role_prompt=manager_role_prompt,
            extra_prompts="\n---\n" + collaboration_prompt,
        ),
        team_prompt_precomposed=team_prompt_precomposed,
    ) + "\n"
