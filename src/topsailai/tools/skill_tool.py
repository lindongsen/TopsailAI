'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''

import os
import shlex

from topsailai.skill_hub.skill_tool import (
    get_skill_markdown,
    get_skills_from_cache,
    overview_skill_native,
    is_matched_skill,
)
from topsailai.tools.cmd_tool import exec_cmd
from topsailai.utils import (
    json_tool,
    env_tool,
    thread_local_tool,
)
from topsailai.workspace import lock_tool


def call_skill(
        folder_path:str,
        cmd:str|list,
        no_need_stderr:int=0,
        timeout:int=120,
    ):
    """Execute a skill script

    Args:
        folder_path (str): required, skill folder.
        cmd (str|list): required, The executable file must be an absolute path from skill folder.
        no_need_stderr (int): If 1, stderr will be returned as empty string.
                               Defaults to 0.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a exception will be raised.
                                 Defaults to 120.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.
    """
    raw_cmd = cmd
    if isinstance(cmd, str):
        if cmd[0] == "[":
            # json str
            cmd = json_tool.safe_json_load(cmd)
    if not cmd:
        raise Exception("illegal cmd: [%s]" % raw_cmd)

    cmd_exe_file = cmd
    if isinstance(cmd, list):
        cmd_exe_file = cmd[0]

    if not cmd_exe_file:
        raise Exception("illegal cmd: [%s]" % raw_cmd)

    if not cmd_exe_file.startswith(folder_path):
        # case: /xxx or .xxx
        for _ in range(2):
            if cmd_exe_file[0] in ['/', '.']:
                cmd_exe_file = cmd_exe_file[1:]
            else:
                break

        cmd_exe_file = os.path.join(folder_path, cmd_exe_file)
        if isinstance(cmd, list):
            cmd[0] = cmd_exe_file
        else:
            cmd = folder_path + "/" + cmd

    flag_cmd_matched = False
    for skill in get_skills_from_cache():
        if cmd_exe_file.startswith(skill.folder):
            flag_cmd_matched = True
            break
    assert flag_cmd_matched, "Illegal cmd, The executable file must be an absolute path from skill folder"

    # enhance security
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)

    # lock session
    need_lock_session = False

    _skills_need_lock_session = env_tool.EnvReaderInstance.get_list_str(
        "TOPSAILAI_SESSION_LOCK_ON_SKILLS", separator=None,
    ) or []
    if is_matched_skill(folder_path, _skills_need_lock_session):
        need_lock_session = True

    ctxm_tool = lock_tool.ctxm_void
    if need_lock_session:
        ctxm_tool = lock_tool.ctxm_try_session_lock

    # refresh session
    need_refresh_session = False
    _skills_need_refresh_session = env_tool.EnvReaderInstance.get_list_str(
        "TOPSAILAI_SESSION_REFRESH_ON_SKILLS", separator=None,
    ) or []
    if is_matched_skill(folder_path, _skills_need_refresh_session):
        need_refresh_session = True

    with ctxm_tool() as data:
        if isinstance(data, lock_tool.YieldData):
            if need_lock_session and data.get("session_id"):
                if not data.get("fp"):
                    return f"call_skill failed: {data.get("msg")}"

        if need_refresh_session:
            ai_agent = thread_local_tool.get_agent_object()
            if ai_agent:
                ai_agent.init_prompt()

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
    return overview_skill_native(folder_path)


TOOLS = dict(
    call_skill=call_skill,
    overview_skill=overview_skill,
)

PROMPT_SKILL = """
---

# SKILLS

When your task is related to a skill, you MUST call `overview_skill` for detail.
The following skill information is merely a summary, Every time you want to use a skill you MUST call `overview_skill` for entire details.
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

PROMPT_PLUGIN_SKILLS = ""
PROMPT = ""
FLAG_TOOL_ENABLED = False

def reload():
    """ reload prompt """
    global PROMPT_PLUGIN_SKILLS
    PROMPT_PLUGIN_SKILLS = get_skill_markdown()

    global PROMPT
    PROMPT = PROMPT_SKILL + PROMPT_PLUGIN_SKILLS + "\n---\n"

    global FLAG_TOOL_ENABLED
    FLAG_TOOL_ENABLED = True if PROMPT_PLUGIN_SKILLS else False

    return

reload()
