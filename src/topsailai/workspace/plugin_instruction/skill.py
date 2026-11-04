'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent
from topsailai.skill_hub import skill_tool, skill_hook


def show_skills(word: str = None) -> str | None:
    """Return cached skills, optionally filtered by name."""
    skills = skill_tool.get_skills_from_cache()
    if not skills:
        return None

    selected = [skill for skill in skills if not word or word in skill.name]
    skill_folders = [str(skill.folder) for skill in selected]
    sections = ["# SKILLS", *(str(skill) for skill in selected)]
    sections.append(
        f"---\n\n## ALL OF SKILL FOLDERS ({len(skill_folders)})\n"
        + "\n".join(skill_folders)
    )
    return "\n\n".join(sections)


def unload_skill(folder: str) -> str:
    """Unload a skill and return its completion status."""
    skill_tool.unload_skill(folder)
    agent = get_ai_agent()
    if agent:
        if not skill_tool.get_skills_from_cache():
            agent.remove_tools("skill_tool")
        agent.reload_tool_prompt()
    return "OK"


def load_skill(folder: str) -> str:
    """Load a skill and return its completion status."""
    skill_tool.load_skill(folder)
    agent = get_ai_agent()
    if agent:
        agent.add_tools_by_module("topsailai.tools.skill_tool")
        agent.reload_tool_prompt()
    return "OK" if skill_tool.exists_skill(folder) else "Failed"


def show_hooks() -> str:
    """Return the sorted skill hook names."""
    return str(sorted(skill_hook.get_hooks().keys()))

INSTRUCTIONS = dict(
    show=show_skills,
    load=load_skill,
    unload=unload_skill,
    hooks=show_hooks,
)
