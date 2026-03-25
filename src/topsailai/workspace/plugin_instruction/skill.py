'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent
from topsailai.skill_hub import skill_tool


def show_skills(word:str=None):
    """Print skills

    Args:
        word (str, optional): Simple fuzzy matching
    """
    print()
    print("# SKILLS")
    for skill in skill_tool.get_skills_from_cache():
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
        agent.reload_tool_prompt()
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
        agent.reload_tool_prompt()
    if skill_tool.exists_skill(folder):
        print("Load skill into map ok")
    else:
        print("Failed")
    return


INSTRUCTIONS = dict(
    show=show_skills,
    load=load_skill,
    unload=unload_skill,
)
