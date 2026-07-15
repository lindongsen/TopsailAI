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

import hashlib
import logging
import os
import re

import yaml

import topsailai.logger  # configures root logger
from topsailai.utils.format_tool import to_list, to_int
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.utils import (
    file_tool,
    print_tool,
)
from topsailai.prompt_hub import prompt_tool
from topsailai.workspace.folder_constants import FOLDER_SKILL

logger = logging.getLogger(__name__)
g_skills = {}  # key is folder, value is SkillInfo

_DEFAULT_SEARCH_SKILLS_MAX_DEPTH = 5  # Default recursion depth when searching for plugin skills

PROMPT_SKILL_FORMAT = """
# Skill Registry

The following section contains the **Skill Information**.
Parse this data according to the format below:

```markdown
## {SkillName} folder={SkillFolder}
Skill Summary

(May include preliminary Overview Content)
>>> [SKILL_OVERVIEW_START:{SkillFolder}]
Overview Content
<<< [SKILL_OVERVIEW_END:{SkillFolder}]
```
"""


COMMON_SCRIPT_FOLDER_NAME_LIST = [
    "scripts",
    "script",
    "bin",
    "sbin",
    "tools",
]

def is_matched_skill(skill_folder:str, keys:list[str]) -> bool:
    """ return True for matched """
    keys = to_list(keys)

    # Filter out None values
    keys = [k for k in keys if k is not None]

    if keys:
        if '*' in keys:
            return True

    for key in keys or []:
        if skill_folder.startswith(key):
            return True
        if skill_folder.endswith(key):
            return True

    return False

def is_need_load_overview(folder_path:str) -> bool:
    """
    Check if need load overview content into prompt

    Args:
        folder_path (str): a skill folder

    Returns:
        bool:
    """
    skill_list = EnvReaderInstance.get_list_str("TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS", separator="")
    if not skill_list:
        return False

    for _ in range(2):
        if folder_path[-1] == '/':
            folder_path = folder_path[:-1]
        else:
            break

    for skill_folder in skill_list:
        if folder_path.startswith(skill_folder):
            return True
        if folder_path.endswith(
            ('' if skill_folder[0] in "./" else '/')+skill_folder
        ):
            return True
    return False


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
        self.skill_md_hash = ""

        # flags
        self.flag_overview = None

        self.all = {}

    @property
    def markdown(self):
        """Generate a markdown formatted string for this skill.

        Returns:
            str: A formatted markdown string containing the skill name,
                 folder path, and description, suitable for inclusion in prompts.
        """
        flag_able_to_overview = True
        description = self.description

        if not self.description:
            description = overview_skill_native(self.folder)
            flag_able_to_overview = False

        result = f"""
## {self.name}. folder=`{self.folder}`
{description}
"""

        if self.flag_overview is None:
            self.flag_overview = is_need_load_overview(self.folder)
        if self.flag_overview and flag_able_to_overview:
            result += overview_skill_native(self.folder)

        return result

    def __str__(self):
        return self.markdown

def get_file_skill_md(folder_path:str) -> str:
    """
    Get file of skill.md

    Args:
        folder_path (str): a skill folder

    Returns:
        str: file path of skill.md
    """
    for filename in ["SKILL.md", "skill.md"]:
        skill_file = os.path.join(folder_path, filename)
        if os.path.isfile(skill_file):
            return skill_file
    return ""

def is_disabled_skill(folder_path:str) -> bool:
    """
    Check if the skill is disabled

    Args:
        folder_path (str): a skill folder

    Returns:
        bool: True is disabled
    """
    if not folder_path:
        return True

    disabled_list = EnvReaderInstance.get_list_str("TOPSAILAI_DISABLED_SKILLS", separator="")
    if not disabled_list:
        return False
    if disabled_list == "*":
        return True
    if folder_path in disabled_list:
        return True
    for f in disabled_list:
        if folder_path.startswith(f):
            return True
        if folder_path.endswith(f):
            return True
    return False

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

    # if disabled
    if is_disabled_skill(folder_path):
        return skill_info

    # Look for SKILL.md or skill.md
    skill_file = get_file_skill_md(folder_path)

    if not skill_file:
        return skill_info

    # Read and parse the skill file
    try:
        with open(skill_file, encoding="utf-8") as fd:
            content = fd.read()
    except Exception:
        return skill_info

    skill_info.skill_md_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Block duplicate skill folder basenames. A skill whose folder basename
    # matches an already-loaded skill from a different path is handled based on
    # the content of its SKILL.md: identical content is treated as a harmless
    # duplicate and the cached SkillInfo is returned; differing content is a
    # conflict and is rejected.
    normalized_folder = os.path.normpath(folder_path)
    skill_basename = os.path.basename(normalized_folder)
    for existing_folder, existing_info in list(g_skills.items()):
        if os.path.normpath(existing_folder) == normalized_folder:
            continue
        if os.path.basename(os.path.normpath(existing_folder)) != skill_basename:
            continue
        if existing_info.skill_md_hash == skill_info.skill_md_hash:
            logger.info(
                "Duplicate skill folder name detected with identical SKILL.md: "
                "basename '%s' of '%s' matches already loaded skill '%s'. "
                "Returning cached skill info.",
                skill_basename, folder_path, existing_folder
            )
            return existing_info
        else:
            logger.error(
                "Conflicting skill folder name detected: basename '%s' of '%s' "
                "matches already loaded skill '%s' but SKILL.md content differs. "
                "Rejecting '%s'.",
                skill_basename, folder_path, existing_folder, folder_path
            )
        return skill_info

    # Parse YAML frontmatter (--- delimited)
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        yaml_content = match.group(1)
        try:
            data = yaml.safe_load(yaml_content)
            if data:
                skill_info.all = data
                skill_info.name = data.get("name", "")
                skill_info.description = data.get("description", "")
                if "flag_overview" in data and data["flag_overview"] != "":
                    skill_info.flag_overview = True if to_int(data.get("flag_overview", 0)) else False
        except yaml.YAMLError as e:
            logger.exception(e)

    if skill_info.name:
        g_skills[skill_info.folder] = skill_info

    return skill_info

def get_skill_markdown_with_subfolders(parent_folder:str, recursion_depth=0) -> str:
    assert parent_folder
    result = ""
    for item in os.listdir(parent_folder):
        subfolder = os.path.join(parent_folder, item)
        if os.path.isdir(subfolder):
            sub_skill_info = parse_skill_folder(subfolder)
            if sub_skill_info.name:
                result += sub_skill_info.markdown
            elif recursion_depth > 0:
                recursion_depth -= 1
                result += get_skill_markdown_with_subfolders(subfolder, recursion_depth)
    return result

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
        for env_key in [
            "TOPSAILAI_PROJECT_WORKSPACE",
            "TOPSAILAI_PWD",
        ]:
            env_dir = EnvReaderInstance.get(env_key)
            if not env_dir:
                continue
            env_dir_skill = os.path.join(env_dir, ".topsailai/skills")
            if os.path.exists(env_dir_skill) and env_dir_skill not in skill_folders:
                skill_folders.append(env_dir_skill)

    max_recursion_depth = EnvReaderInstance.get(
        "TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH",
        default=_DEFAULT_SEARCH_SKILLS_MAX_DEPTH,
        formatter=int,
    ) or _DEFAULT_SEARCH_SKILLS_MAX_DEPTH
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
                result += get_skill_markdown_with_subfolders(skill_folder, recursion_depth=max_recursion_depth)

    if result:
        content_all_skill_folders = "\n".join(
            ("- " + key) for key in g_skills.keys()
        )
        return PROMPT_SKILL_FORMAT + result + f"""
## ALL OF SKILL FOLDERS
{content_all_skill_folders}
"""
    return ""


def get_skills_from_cache() -> list[SkillInfo]:
    """ get all of skills """
    return g_skills.values()

def get_skill_info_from_cache(folder_path:str) -> SkillInfo|None:
    return g_skills.get(folder_path)

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

def _expand_preload_doc_entry(skill_folder: str, doc_entry: str) -> list[tuple[str, str]]:
    """Expand a preload_docs entry into a list of (relative_path, absolute_path) tuples.

    If ``doc_entry`` points to a directory, all files ending with ``.md`` or
    ``.MD`` are collected recursively and returned in sorted order. If it
    points to a file, the single file is returned.

    Args:
        skill_folder: Root folder of the skill.
        doc_entry: A preload_docs entry from SKILL.md.

    Returns:
        List of tuples ``(relative_path, absolute_path)`` for each document.
    """
    relative_entry = doc_entry
    for _ in range(2):
        if relative_entry and relative_entry[0] in "./":
            relative_entry = relative_entry[1:]
        else:
            break

    abs_path = os.path.join(skill_folder, relative_entry)
    if os.path.isdir(abs_path):
        md_files = []
        for root, _dirs, files in os.walk(abs_path):
            for filename in files:
                if filename.lower().endswith(".md"):
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, skill_folder)
                    md_files.append((rel_path, full_path))
        md_files.sort(key=lambda item: item[0])
        return md_files

    return [(relative_entry, abs_path)]


def overview_skill_native(folder_path:str) -> str:
    """ Every time you want to use a skill you MUST call `overview_skill` for entire details.
    Args:
        folder_path (str): required, skill folder.
    """
    file_skill_md = ""
    for skill_md in ["SKILL.md", "skill.md"]:
        file_skill_md = os.path.join(folder_path, skill_md)
        if os.path.exists(file_skill_md):
            break

        file_skill_md = ""

    assert file_skill_md, f"no found skill.md in this folder: {folder_path}"

    content_skill_md = ""
    with open(file_skill_md, encoding="utf-8") as fd:
        content_skill_md = fd.read()

    folder_list = file_tool.list_files(
        folder_path,
        to_exclude_dot_start=True,
        excluded_starts=(
            '__pycache__',
        ),
    )
    folder_content = "\n".join(
        [
            ('- ' + _folder.replace(f"{folder_path}/", ""))
            for _folder in folder_list
        ]
    )

    result = f"""
# skill overview: folder={folder_path}

## file content

### {file_skill_md}
{content_skill_md}

## folder content
{folder_content}
"""

    # preload_docs
    skill_info = get_skill_info_from_cache(folder_path)
    if skill_info:
        preload_docs = skill_info.all.get("preload_docs")
        if preload_docs:
            preload_docs = to_list(preload_docs)
        else:
            preload_docs = []
        for doc_entry in preload_docs:
            try:
                for doc_file, _ in _expand_preload_doc_entry(folder_path, doc_entry):
                    doc_content = get_skill_file_content(folder_path, doc_file)
                    if doc_content:
                        result += f"""
### file:{doc_file}
{doc_content}

"""
            except Exception as e:
                print_tool.print_critical(f"failed to load doc: [{doc_entry}] [{e}]")

    return f"\n>>> [SKILL_OVERVIEW_START:{folder_path}]\n" + result + f"\n<<< [SKILL_OVERVIEW_END:{folder_path}]\n"

def get_skill_file(folder_path:str, file_name:str) -> str:
    """ Return a skill file """
    # format file_name
    for _ in range(2):
        if file_name[0] in "./":
            file_name = file_name[1:]
        else:
            break

    # check file path
    fpath = os.path.join(folder_path, file_name)
    if os.path.exists(fpath):
        return fpath

    # real file_name
    for _ in range(2):
        if file_name[-1] == '/':
            file_name = file_name[:-1]
        else:
            break
    file_name = file_name.rsplit('/', 1)[-1]
    if not file_name:
        return ""

    # list folder
    file_list = file_tool.list_files(
        folder_path,
        to_exclude_dot_start=True,
        included_filename_keywords=[file_name],
    )
    if file_list and len(file_list) == 1:
        return file_list[0]

    return ""

def get_skill_file_content(folder_path:str, file_name:str) -> str:
    """
    Get file content from skill folder

    Args:
        folder_path (str): skill folder
        file_name (str): relative file name

    Returns:
        str: file content
    """
    file_path = get_skill_file(folder_path, file_name)
    assert file_path, f"no found this skill file: {file_name}"

    file_content = ""
    with open(file_path, encoding='utf-8') as fp:
        file_content = fp.read()

    return file_content

def get_script_path(skill_folder:str, script_path:str) -> str:
    """ return absolute path """
    if not script_path.startswith(skill_folder):
        # case: /xxx or .xxx
        for _ in range(2):
            if script_path[0] in ['/', '.']:
                script_path = script_path[1:]
            else:
                break

        if not os.path.exists(f"{skill_folder}/{script_path}"):
            for _script_dirname in COMMON_SCRIPT_FOLDER_NAME_LIST:
                _real_script_path = f"{skill_folder}/{_script_dirname}/{script_path}"
                if os.path.exists(_real_script_path):
                    script_path = _real_script_path
                    return script_path

    script_base_name = os.path.basename(script_path)
    if not os.path.exists(script_path):
        for _script_dirname in COMMON_SCRIPT_FOLDER_NAME_LIST:
            _real_script_path = f"{skill_folder}/{_script_dirname}/{script_base_name}"
            if os.path.exists(_real_script_path):
                script_path = _real_script_path
                return script_path

    _real_script_path = get_skill_file(skill_folder, script_base_name)
    if _real_script_path:
        return _real_script_path

    return script_path
