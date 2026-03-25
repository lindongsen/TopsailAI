'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose: Parsing Skills.

  Folder Structure:
skill-folder-name/
- SKILL.md    # [core] document
- scripts/    # [tool] executable scripts
- references/ # [knowledge] domain expertise
- assets/     # [resource] static files
- config/     # [variable] config file

  About of SKILL.md:
---
name: aaa        -> yaml format
description: bbb
---
'''

import os
import re

import yaml

from topsailai.utils.format_tool import to_list
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.prompt_hub import prompt_tool
from topsailai.workspace.folder_constants import FOLDER_SKILL


g_skills = {} # key is folder, value is SkillInfo

PROMPT_SKILL = prompt_tool.read_prompt("skills/skill.md")


class SkillInfo(object):
    """Container for skill metadata extracted from a skill folder.

    This class holds information about a skill including its folder path,
    name, and description. It also provides a formatted markdown representation
    for use in prompts.
    """

    def __init__(self):
        """Initialize a new SkillInfo instance with empty fields."""
        self.folder = ""
        self.name = ""
        self.description = ""

    @property
    def markdown(self):
        """Generate a markdown formatted string for this skill.

        Returns:
            str: A formatted markdown string containing the skill name,
                 folder path, and description, suitable for inclusion in prompts.
        """
        return f"""
## {self.name}. folder=`{self.folder}`
{self.description}
"""

    def __str__(self):
        return self.markdown


def parse_skill_folder(folder_path: str) -> SkillInfo:
    """Parse a skill folder to extract skill information.

    Looks for SKILL.md or skill.md in the folder and parses the YAML frontmatter
    to extract name and description.

    Args:
        folder_path: Path to the skill folder

    Returns:
        SkillInfo object with folder, name, and description populated
    """
    skill_info = SkillInfo()
    skill_info.folder = folder_path

    if not os.path.isdir(folder_path):
        return skill_info

    # Look for SKILL.md or skill.md
    skill_file = None
    for filename in ["SKILL.md", "skill.md"]:
        candidate = os.path.join(folder_path, filename)
        if os.path.isfile(candidate):
            skill_file = candidate
            break

    if not skill_file:
        return skill_info

    # Read and parse the skill file
    try:
        with open(skill_file, encoding="utf-8") as fd:
            content = fd.read()
    except Exception:
        return skill_info

    # Parse YAML frontmatter (--- delimited)
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        yaml_content = match.group(1)
        try:
            data = yaml.safe_load(yaml_content)
            if data:
                skill_info.name = data.get("name", "")
                skill_info.description = data.get("description", "")
        except yaml.YAMLError:
            pass

    if skill_info.name:
        g_skills[skill_info.folder] = skill_info

    return skill_info


def get_skill_markdown(skill_folders=None) -> str:
    """Get the markdown prompt for all available skills.

    Scans the skill folder and any plugin skill folders specified in
    the TOPSAILAI_PLUGIN_SKILLS environment variable.

    Returns:
        A formatted string containing skill information, or empty string if no skills found
    """
    result = ""

    # Get skill folders to scan
    if not skill_folders:
        skill_folders = [
            FOLDER_SKILL,
        ] + (
            EnvReaderInstance.get_list_str("TOPSAILAI_PLUGIN_SKILLS", separator="") or []
        )

    for skill_folder in to_list(skill_folders):
        if not os.path.exists(skill_folder):
            continue

        if os.path.isfile(skill_folder):
            continue
        elif os.path.isdir(skill_folder):
            # Check if skill.md/SKILL.md exists directly in the folder
            skill_info = parse_skill_folder(skill_folder)
            if skill_info.name:
                result += skill_info.markdown
            else:
                # If no skill.md/SKILL.md found, process subfolders
                for item in os.listdir(skill_folder):
                    subfolder = os.path.join(skill_folder, item)
                    if os.path.isdir(subfolder):
                        sub_skill_info = parse_skill_folder(subfolder)
                        if sub_skill_info.name:
                            result += sub_skill_info.markdown

    if result:
        return PROMPT_SKILL + result
    return ""


def get_skills_from_cache() -> list[SkillInfo]:
    """ get all of skills """
    return g_skills.values()

def unload_skill(folder_path:str):
    """ unload a skill """
    # remove env
    skill_folders = EnvReaderInstance.get_list_str("TOPSAILAI_PLUGIN_SKILLS", separator="")
    if skill_folders:
        skill_folders = set(skill_folders)
        if folder_path in skill_folders:
            skill_folders.remove(folder_path)
    os.environ["TOPSAILAI_PLUGIN_SKILLS"] = ";".join(list(skill_folders)) if skill_folders else ""

    # remove cache
    if folder_path in g_skills:
        del g_skills[folder_path]
    return

def load_skill(folder_path:str) -> SkillInfo:
    """
    Load a skill

    Args:
        folder_path (str): skill folder

    Returns:
        SkillInfo: a instance
    """
    # add env
    skill_folders = EnvReaderInstance.get_list_str("TOPSAILAI_PLUGIN_SKILLS", separator="")
    if not skill_folders:
        skill_folders = []
    if folder_path not in skill_folders:
        skill_folders.append(folder_path)
    if skill_folders:
        os.environ["TOPSAILAI_PLUGIN_SKILLS"] = ";".join(skill_folders)

    # add skill
    return parse_skill_folder(folder_path)

def exists_skill(folder_path:str) -> bool:
    """
    Check if the skill exists

    Args:
        folder_path (str): skill folder

    Returns:
        bool: True for ok
    """
    return folder_path in g_skills
