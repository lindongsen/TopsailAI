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
import html
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


class SkillHubToolError(ValueError):
    """Raised when a skill-hub operation fails due to invalid input or environment."""
    pass


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

- If a skill's `SKILL_OVERVIEW_START~SKILL_OVERVIEW_END` block is already present in the context, that skill has been pre-loaded. Do not reload the full overview.
- The `## folder content` section lists the skill's folder structure. Files not shown there may be read on demand.
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


def _normalize_overview_entry(entry: str) -> str:
    """Normalize a TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS entry.

    Strips whitespace, removes leading ``./`` or ``.\\`` components, and
    removes trailing path separators so matching is consistent regardless
    of how the value was written.
    """
    entry = entry.strip()
    for _ in range(2):
        if entry.startswith("./") or entry.startswith(".\\"):
            entry = entry[2:]
        else:
            break
    return entry.rstrip("/\\")


def _match_overview_entry(folder_path: str, entry: str) -> bool:
    """Return True when ``folder_path`` matches a single overview entry.

    Matching rules (in order):

    1. ``*`` matches every folder.
    2. Exact full-path match after normalization.
    3. ``folder_path`` starts with the normalized entry (full-path prefix).
    4. The last path segment of ``folder_path`` equals the entry (skill-name
       match). This avoids unsafe substring matches such as ``team`` matching
       ``my_team`` or ``team_x``.
    """
    if entry == "*":
        return True

    normalized_folder = folder_path.rstrip("/\\")
    normalized_entry = _normalize_overview_entry(entry)
    if not normalized_entry:
        return False

    if normalized_folder == normalized_entry:
        return True
    if normalized_folder.startswith(normalized_entry + os.sep):
        return True
    if normalized_folder.startswith(normalized_entry + "/"):
        return True

    folder_basename = os.path.basename(normalized_folder)
    entry_basename = os.path.basename(normalized_entry)
    if folder_basename and entry_basename and folder_basename == entry_basename:
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

    for skill_folder in skill_list:
        if _match_overview_entry(folder_path, skill_folder):
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


def is_disabled_skill_by_name(skill_name: str) -> bool:
    """Check whether an exact skill name is disabled."""
    if not skill_name:
        return False

    disabled_list = EnvReaderInstance.get_list_str(
        "TOPSAILAI_DISABLED_SKILLS", separator=""
    )
    if not disabled_list:
        return False
    if disabled_list == "*" or "*" in disabled_list:
        return True
    return skill_name in disabled_list


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

    if is_disabled_skill_by_name(skill_info.name):
        skill_info.name = ""
        return skill_info

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
        logger.error(
            "Conflicting skill folder name detected: basename '%s' of '%s' "
            "matches already loaded skill '%s' but SKILL.md content differs. "
            "Rejecting '%s'.",
            skill_basename, folder_path, existing_folder, folder_path
        )
        skill_info.name = ""
        return skill_info

    if skill_info.name:
        preload = bool(skill_info.all.get("preload_docs"))
        load_overview = is_need_load_overview(folder_path)
        print_tool.print_info(
            f"Skill loaded:\n  folder={folder_path}\n  name={skill_info.name}\n"
            f"  preload={preload}\n  load_overview={load_overview}"
        )
        g_skills[skill_info.folder] = skill_info

    return skill_info

def get_skill_markdown_with_subfolders(parent_folder: str, recursion_depth=0) -> str:
    if not parent_folder:
        raise SkillHubToolError(
            "parent_folder cannot be empty when scanning subfolders for skills."
        )
    if not os.path.isdir(parent_folder):
        raise SkillHubToolError(
            f"Skill search folder does not exist or is not a directory: {parent_folder!r}. "
            "Check TOPSAILAI_PLUGIN_SKILLS and ensure the folder path is correct."
        )
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


def _strip_skill_frontmatter(content: str) -> str:
    """Remove complete YAML frontmatter from the start of SKILL.md."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return content

    try:
        metadata = yaml.safe_load("".join(lines[1:closing_index]))
    except yaml.YAMLError:
        return content
    if metadata is not None and not isinstance(metadata, dict):
        return content

    return "".join(lines[closing_index + 1:])


def _render_overview_file(relative_path: str, content: str) -> str:
    """Render one skill document inside an XML file boundary."""
    escaped_path = html.escape(relative_path, quote=True)
    return f'<file path="{escaped_path}">\n{content}\n</file>'


def overview_skill_native(folder_path: str) -> str:
    """Return the complete, compact overview for a skill folder."""
    if not folder_path:
        raise SkillHubToolError(
            "skill folder cannot be empty. Provide a valid skill folder path."
        )
    if not os.path.isdir(folder_path):
        raise SkillHubToolError(
            f"Skill folder does not exist or is not a directory: {folder_path!r}. "
            "Check the folder path and ensure the skill is loaded."
        )

    file_skill_md = ""
    for skill_md in ["SKILL.md", "skill.md"]:
        candidate = os.path.join(folder_path, skill_md)
        if os.path.exists(candidate):
            file_skill_md = candidate
            break

    if not file_skill_md:
        raise SkillHubToolError(
            f"No SKILL.md found in skill folder {folder_path!r}. "
            "Ensure the folder contains a SKILL.md file and the skill is not disabled."
        )

    try:
        with open(file_skill_md, encoding="utf-8") as fd:
            content_skill_md = _strip_skill_frontmatter(fd.read())
    except PermissionError as exc:
        raise SkillHubToolError(
            f"Permission denied reading {file_skill_md!r}: {exc}. "
            "Check file permissions and ownership."
        )
    except UnicodeDecodeError as exc:
        raise SkillHubToolError(
            f"{file_skill_md!r} is not valid UTF-8 text: {exc}. "
            "SKILL.md must be a UTF-8 encoded text file."
        )

    folder_list = file_tool.list_files(
        folder_path,
        to_exclude_dot_start=True,
        excluded_starts=("__pycache__",),
    )
    folder_content = "\n".join(
        "- " + os.path.relpath(item, folder_path)
        for item in folder_list
    )
    skill_relative_path = os.path.relpath(file_skill_md, folder_path)
    result = (
        "\n"
        + _render_overview_file(skill_relative_path, content_skill_md)
        + f"\n\n## folder content\n{folder_content}\n"
    )

    skill_info = get_skill_info_from_cache(folder_path)
    seen_paths = {
        os.path.normcase(os.path.normpath(os.path.abspath(file_skill_md)))
    }
    if skill_info:
        preload_docs = to_list(skill_info.all.get("preload_docs") or [])
        for doc_entry in preload_docs:
            try:
                expanded_docs = _expand_preload_doc_entry(folder_path, doc_entry)
            except Exception as exc:
                print_tool.print_critical(
                    f"failed to load doc: [{doc_entry}] [{exc}]"
                )
                continue
            for _doc_file, doc_path in expanded_docs:
                normalized_path = os.path.normcase(
                    os.path.normpath(os.path.abspath(doc_path))
                )
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)
                relative_path = os.path.relpath(doc_path, folder_path)
                try:
                    doc_content = get_skill_file_content(folder_path, relative_path)
                except Exception as exc:
                    print_tool.print_critical(
                        f"failed to load doc: [{relative_path}] [{exc}]"
                    )
                    continue
                if doc_content:
                    result += (
                        "\n"
                        + _render_overview_file(relative_path, doc_content)
                        + "\n"
                    )

    return (
        f"\n>>> [SKILL_OVERVIEW_START:{folder_path}]\n"
        + result
        + f"\n<<< [SKILL_OVERVIEW_END:{folder_path}]\n"
    )

def _is_path_inside_skill_folder(skill_folder: str, target_path: str) -> bool:
    """Return True if ``target_path`` resolves to a path inside ``skill_folder``.

    Symlinks inside the skill folder are intentionally preserved so a skill
    can expose files through symlinks. Only ``.`` and ``..`` components are
    normalized.
    """
    try:
        real_skill = os.path.normpath(os.path.abspath(skill_folder))
        real_target = os.path.normpath(os.path.abspath(target_path))
        if real_target == real_skill:
            return True
        common = os.path.commonpath([real_skill, real_target])
        return common == real_skill
    except (ValueError, OSError):
        return False

def get_skill_file(folder_path: str, file_name: str) -> str:
    """Return a skill file path if it resolves inside the skill folder.

    ``file_name`` may be a relative path inside ``folder_path`` or an
    absolute path that resolves to a file inside ``folder_path``.
    Relative path traversal outside the skill folder is rejected.
    Symlinks inside the skill folder are preserved.
    """
    if not file_name:
        return ""

    if os.path.isabs(file_name):
        candidate = os.path.normpath(os.path.abspath(file_name))
        if _is_path_inside_skill_folder(folder_path, candidate) and os.path.isfile(candidate):
            return candidate
        return ""

    normalized = os.path.normpath(file_name)
    if normalized.startswith(".."):
        return ""

    candidate = os.path.normpath(os.path.abspath(os.path.join(folder_path, normalized)))
    if _is_path_inside_skill_folder(folder_path, candidate) and os.path.isfile(candidate):
        return candidate

    # Fallback: search by basename, keeping results inside the skill folder.
    base_name = os.path.basename(normalized)
    if not base_name:
        return ""

    file_list = file_tool.list_files(
        folder_path,
        to_exclude_dot_start=True,
        included_filename_keywords=[base_name],
    )
    for found_path in file_list or []:
        real_found = os.path.normpath(os.path.abspath(found_path))
        if _is_path_inside_skill_folder(folder_path, real_found) and os.path.isfile(real_found):
            return real_found

    return ""

def get_skill_file_content(folder_path:str, file_name:str) -> str:
    """
    Get file content from skill folder

    Args:
        folder_path (str): skill folder
        file_name (str): relative file name or absolute file path

    Returns:
        str: file content

    Raises:
        SkillHubToolError: If the file cannot be found or read.
    """
    # Reject traversal and outside absolute paths before attempting resolution.
    if file_name:
        if os.path.isabs(file_name):
            candidate = os.path.normpath(os.path.abspath(file_name))
        else:
            candidate = os.path.normpath(os.path.abspath(os.path.join(folder_path, file_name)))
        if not _is_path_inside_skill_folder(folder_path, candidate):
            raise SkillHubToolError(
                f"File {file_name!r} is outside the skill folder {folder_path!r}. "
                "Use a relative path that stays inside the skill folder."
            )

    file_path = get_skill_file(folder_path, file_name)
    if not file_path:
        raise SkillHubToolError(
            f"File {file_name!r} not found in skill folder {folder_path!r}. "
            "Use a relative path such as 'scripts/run.sh' or 'README.md'."
        )

    try:
        with open(file_path, encoding='utf-8') as fp:
            return fp.read()
    except PermissionError as exc:
        raise SkillHubToolError(
            f"Permission denied reading {file_path!r}: {exc}. "
            "Check file permissions and ownership."
        ) from exc
    except UnicodeDecodeError as exc:
        raise SkillHubToolError(
            f"File {file_path!r} is not valid UTF-8 text: {exc}. "
            "Use a tool designed for binary files if needed."
        ) from exc

def get_script_path(skill_folder:str, script_path:str) -> str:
    """Return absolute path to a skill script.

    ``script_path`` may be a relative path inside ``skill_folder`` or an
    absolute path that resolves to a script inside ``skill_folder``.
    Relative path traversal outside the skill folder is rejected.
    Symlinks inside the skill folder are preserved.
    """
    if not script_path:
        return script_path

    normalized = os.path.normpath(script_path)

    # Reject traversal before checking existence.
    if normalized.startswith(".."):
        return ""

    # Absolute paths are accepted only when contained in the skill folder.
    if os.path.isabs(normalized):
        candidate = os.path.normpath(os.path.abspath(normalized))
        if _is_path_inside_skill_folder(skill_folder, candidate) and os.path.isfile(candidate):
            return candidate
        return ""

    candidate = os.path.normpath(os.path.abspath(os.path.join(skill_folder, normalized)))
    if _is_path_inside_skill_folder(skill_folder, candidate) and os.path.isfile(candidate):
        return candidate

    for _script_dirname in COMMON_SCRIPT_FOLDER_NAME_LIST:
        candidate = os.path.normpath(os.path.abspath(os.path.join(skill_folder, _script_dirname, normalized)))
        if _is_path_inside_skill_folder(skill_folder, candidate) and os.path.isfile(candidate):
            return candidate

    script_base_name = os.path.basename(normalized)
    for _script_dirname in COMMON_SCRIPT_FOLDER_NAME_LIST:
        candidate = os.path.normpath(os.path.abspath(os.path.join(skill_folder, _script_dirname, script_base_name)))
        if _is_path_inside_skill_folder(skill_folder, candidate) and os.path.isfile(candidate):
            return candidate

    _real_script_path = get_skill_file(skill_folder, script_base_name)
    if _real_script_path:
        return _real_script_path

    return ""
