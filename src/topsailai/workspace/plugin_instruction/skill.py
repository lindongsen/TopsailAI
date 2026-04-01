'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent
from topsailai.skill_hub import skill_tool, skill_hook


def show_skills(word:str=None):
    """Print skills

    Args:
        word (str, optional): Simple fuzzy matching
    """
    skills = skill_tool.get_skills_from_cache()
    if not skills:
        return
    print()
    print("# SKILLS")
    for skill in skills:
        if word:
            if word in skill.name:
                print(str(skill))
        else:
            print(str(skill))
    return

def unload_skill(folder:str):
    """
    unload a skill

    Args:
        folder (str): folder path
    """
    skill_tool.unload_skill(folder)
    agent = get_ai_agent()
    if agent:
        if not skill_tool.get_skills_from_cache():
            agent.remove_tools("skill_tool")
        agent.reload_tool_prompt()
    print("OK")
    return

def load_skill(folder:str):
    """
    Load a skill

    Args:
        folder (str): folder path
    """
    skill_tool.load_skill(folder)
    agent = get_ai_agent()
    if agent:
        agent.add_tools_by_module("topsailai.tools.skill_tool")
        agent.reload_tool_prompt()
    if skill_tool.exists_skill(folder):
        print("OK")
    else:
        print("Failed")
    return

def show_hooks():
    """
    Show skill hooks
    """
    print(sorted(skill_hook.get_hooks().keys()))
    return

INSTRUCTIONS = dict(
    show=show_skills,
    load=load_skill,
    unload=unload_skill,
    hooks=show_hooks,
)
