'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

import os

from topsailai.ai_team import prompt as team_prompt
from topsailai.ai_team.role import (
    get_member_prompt,
)
from topsailai.utils import (
    file_tool,
)


def extend_system_prompt():
    """
    Set default SYSTEM_PROMPT_EXTRA_FILES environment variable.

    This function sets a default value for SYSTEM_PROMPT_EXTRA_FILES if it's
    not already set. The default is "work_mode/sop/work_agreement.md" which
    contains work-related agreements and SOPs.

    Returns:
        None

    Note:
        This function modifies the environment variable SYSTEM_PROMPT_EXTRA_FILES
        if it doesn't exist.
    """
    if not os.getenv("SYSTEM_PROMPT_EXTRA_FILES"):
        os.environ["SYSTEM_PROMPT_EXTRA_FILES"] = "work_mode/sop/work_agreement.md"
    return


def is_team_prompt_precomposed_launch() -> bool:
    """Return whether existing plugin launch state identifies a precomposed prompt."""
    system_prompt = os.getenv("SYSTEM_PROMPT")
    return bool(
        os.getenv("TOPSAILAI_TEAM_PROMPT_CONTENT")
        and system_prompt
        and os.getenv("TOPSAILAI_SYSTEM_PROMPT") == system_prompt
    )


def get_system_prompt(
    agent_name: str,
    *,
    team_prompt_precomposed: bool | None = None,
) -> str:
    """Build the canonical system prompt for a team Member Agent.

    Direct launches append the runtime team prompt and ``team.values`` before
    the selected Member role and values. An explicit ``team_prompt_precomposed``
    value takes precedence; when omitted, structured plugin launch state is
    used to detect whether the base prompt already contains the team-wide
    layers.

    Args:
        agent_name: Name of the selected team Member.
        team_prompt_precomposed: Explicitly state whether the base prompt
            already contains the runtime team prompt and shared team values.
            ``None`` detects the state from structured plugin launch signals.

    Returns:
        The complete Member system prompt.
    """
    if team_prompt_precomposed is None:
        team_prompt_precomposed = is_team_prompt_precomposed_launch()

    env_sys_prompt = os.getenv("SYSTEM_PROMPT")
    _, sys_prompt_content = file_tool.get_file_content_fuzzy(env_sys_prompt)

    runtime_team_prompt = ""
    team_values = ""
    if not team_prompt_precomposed:
        runtime_team_source = os.getenv("TOPSAILAI_TEAM_PROMPT")
        if runtime_team_source:
            runtime_team_prompt = team_prompt.resolve_runtime_team_prompt(
                runtime_team_source
            )
        team_values = team_prompt.load_team_values(
            os.getenv("TOPSAILAI_TEAM_PATH")
        )

    member_prompt = get_member_prompt(agent_name)
    if member_prompt in sys_prompt_content:
        member_prompt = ""

    sys_prompt_content = team_prompt.compose_team_prompt(
        team_prompt.TeamPromptSegments(
            base_system_prompt=sys_prompt_content,
            runtime_team_prompt=runtime_team_prompt,
            team_values=team_values,
            role_prompt=member_prompt,
        ),
        team_prompt_precomposed=team_prompt_precomposed,
    )

    extend_system_prompt()
    return sys_prompt_content
