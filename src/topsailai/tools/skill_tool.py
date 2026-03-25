'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''

import os

from topsailai.utils import (
    file_tool,
)
from topsailai.skill_hub.skill_tool import (
    get_skill_markdown,
    get_skills_from_cache,
)
from topsailai.tools.cmd_tool import exec_cmd


def call_skill(
        folder_path:str,
        cmd:str|list,
        no_need_stderr:int=0,
        timeout:int=120,
    ):
    """Execute a skill script

    Args:
        folder_path (str): required, skill folder.
        cmd (str|list): required, Command to execute, The executable file must be an absolute path.
        no_need_stderr (int): If 1, stderr will be returned as empty string.
                               Defaults to 0.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a exception will be raised.
                                 Defaults to 120.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.
    """
    flag_cmd_matched = False
    for skill in get_skills_from_cache():
        if cmd.startswith(skill.folder):
            flag_cmd_matched = True
            break
    assert flag_cmd_matched, "Illegal cmd, The executable file must be an absolute path"

    return exec_cmd(
        cmd,
        no_need_stderr=True if int(no_need_stderr) else False,
        timeout=int(timeout),
        cwd=folder_path,
    )

def overview_skill(folder_path:str):
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

    folder_content = "\n".join(file_tool.list_files(folder_path, to_exclude_dot_start=True))

    result = f"""
# skill overview: folder={folder_path}

## file content

### {file_skill_md}
{content_skill_md}

## folder content
{folder_content}
"""
    return result


TOOLS = dict(
    call_skill=call_skill,
    overview_skill=overview_skill,
)

PROMPT_PLUGIN_SKILLS = get_skill_markdown()

PROMPT_SKILL = """
---

# SKILLS

[Attention] Every time you want to use a skill you MUST call `overview_skill` for entire details.
When skill refers to a file with a relative_path, you should use `{folder}/{relative_path}` to construct an absolute_path to access it.

common folder structure:
```
folder-name/
- SKILL.md    # [core] document
- scripts/    # [tool] executable scripts
- references/ # [knowledge] domain expertise
- assets/     # [resource] static files
- config/     # [variable] config file can be updated
```
"""

PROMPT = PROMPT_SKILL + PROMPT_PLUGIN_SKILLS + "\n---\n"

FLAG_TOOL_ENABLED = True if PROMPT_PLUGIN_SKILLS else False

def reload():
    """ reload prompt """
    global PROMPT_PLUGIN_SKILLS
    PROMPT_PLUGIN_SKILLS = get_skill_markdown()

    global PROMPT
    PROMPT = PROMPT_SKILL + PROMPT_PLUGIN_SKILLS + "\n---\n"

    global FLAG_TOOL_ENABLED
    FLAG_TOOL_ENABLED = True if PROMPT_PLUGIN_SKILLS else False

    return
