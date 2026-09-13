"""Resolve and compose ordered prompts for AI teams.

Author: DawsonLin
"""

import os
from dataclasses import dataclass

from topsailai.utils import file_tool


TEAM_VALUES_FILE = "team.values"


@dataclass(frozen=True)
class TeamPromptSegments:
    """Represent the fixed prompt layers used by team entry points."""

    base_system_prompt: str = ""
    runtime_team_prompt: str = ""
    team_values: str = ""
    team_inventory: str = ""
    role_prompt: str = ""
    member_values: str = ""
    extra_prompts: str = ""


def resolve_runtime_team_prompt(prompt_source: str | None) -> str:
    """Resolve the existing runtime team prompt from file content or direct text."""
    _, prompt_content = file_tool.get_file_content_fuzzy(prompt_source)
    return prompt_content or ""


def load_team_values(team_path: str | None) -> str:
    """Load optional non-structured ``team.values`` text from a team directory.

    A missing team path, missing file, or empty file contributes no prompt segment.
    Read errors from an existing path are intentionally propagated so configured
    team constraints cannot be omitted silently.
    """
    if not team_path:
        return ""

    values_path = os.path.join(team_path, TEAM_VALUES_FILE)
    if not os.path.exists(values_path):
        return ""

    with open(values_path, encoding="utf-8") as values_file:
        return values_file.read().strip()


def compose_team_prompt(
    segments: TeamPromptSegments,
    *,
    team_prompt_precomposed: bool = False,
) -> str:
    """Compose prompt segments in canonical broad-to-specific order.

    ``team_prompt_precomposed`` is explicit provenance supplied by the caller.
    When true, the base prompt already contains the runtime team prompt and shared
    team values, so those two segments are not appended again. No content-based
    duplicate detection is performed.
    """
    ordered_segments = [segments.base_system_prompt]
    if not team_prompt_precomposed:
        ordered_segments.extend([
            segments.runtime_team_prompt,
            segments.team_values,
        ])
    ordered_segments.extend([
        segments.team_inventory,
        segments.role_prompt,
        segments.member_values,
        segments.extra_prompts,
    ])
    return _join_prompt_segments(ordered_segments)


def _join_prompt_segments(segments: list[str]) -> str:
    """Join non-empty prompt segments with one deterministic newline boundary."""
    result = ""
    for segment in segments:
        if not segment:
            continue
        if not result:
            result = segment
            continue
        result = result.rstrip() + "\n" + segment.strip()
    return result
