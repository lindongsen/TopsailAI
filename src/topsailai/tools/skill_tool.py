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
from topsailai.utils.cmd_tool import exec_cmd
from topsailai.skill_hub.skill_tool import get_skill_markdown

def call_skill(
        folder_path:str,
        cmd:str|list,
        no_need_stderr:bool=False,
        timeout:int=None,
    ):
    """Execute a shell command and return the result.

    Args:
        folder_path (str): required, skill folder.
        cmd (str|list): required, Command to execute.
        no_need_stderr (bool): If True, stderr will be returned as empty string.
                               Defaults to False.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a subprocess.TimeoutExpired
                                 exception will be raised. Defaults to None.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.

    Example:
        >>> exec_cmd(["echo", "hello"])
        (0, "hello\n", "")

        >>> exec_cmd("ls /nonexistent", no_need_stderr=True)
        (2, "", "")
    """
    return exec_cmd(
        cmd,
        no_need_stderr=no_need_stderr,
        timeout=timeout,
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
    overview_skill=overview_skill,
)

PROMPT_PLUGIN_SKILLS = get_skill_markdown()

PROMPT = """
---

# SKILLS
Every time you want to use a skill you MUST call `overview_skill` for entire details.
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
""" + PROMPT_PLUGIN_SKILLS + "\n---\n"

FLAG_TOOL_ENABLED = True if PROMPT_PLUGIN_SKILLS else False
