'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

import os

from topsailai.utils import (
    env_tool,
    time_tool,
    file_tool,
)
from topsailai.ai_team.manager import (
    get_team_list,
    generate_team_prompt,
)
from topsailai.ai_team.role import (
    get_manager_prompt,
)


CWD = os.path.abspath(os.path.dirname(__file__))

DEFAULT_HEAD_TAIL_OFFSET = 7
PROMPT_FILE_AI_TEAM = f"{CWD}/ai_team.md"
PROMPT_FILE_AI_TEAM_MANAGER = f"{CWD}/ai_team_manager.md"

g_flag_only_agent = env_tool.EnvReaderInstance.check_bool("TOPSAILAI_TEAM_MANAGER_ONLY_AGENT")
if g_flag_only_agent:
    PROMPT_FILE_AI_TEAM_MANAGER = f"{CWD}/ai_team_manager_only_agent.md"


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

def get_session_id() -> str:
    """
    Generate or retrieve a session ID for the current session.

    Uses SESSION_ID environment variable if set, otherwise generates
    one based on current date and time.

    Returns:
        str: A unique session identifier string.

    Example:
        >>> get_session_id()
        '20260120123456'
    """
    session_id = os.getenv("SESSION_ID") or time_tool.get_current_date(with_t=True).replace('-', '')
    session_id = session_id.replace(':', '')
    return session_id
