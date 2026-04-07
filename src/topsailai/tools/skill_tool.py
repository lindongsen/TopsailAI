'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''

import os
import shlex

from topsailai.skill_hub import skill_hook
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
    format_tool,
)
from topsailai.ai_base.agent_types.exception import (
    AgentNeedRefreshSession,
)
from topsailai.workspace import lock_tool


DEFAULT_CALL_SKILL_TIMEOUT = 600

def get_call_skill_timeout(folder_path:str) -> int:
    """ get timeout from environ """

    timeout_map_s = env_tool.EnvReaderInstance.get("TOPSAILAI_CALL_SKILL_TIMEOUT_MAP")
    if not timeout_map_s:
        return DEFAULT_CALL_SKILL_TIMEOUT

    skill_timeout_map = format_tool.parse_str_to_dict(timeout_map_s, kv_strip=True)
    if not skill_timeout_map:
        return DEFAULT_CALL_SKILL_TIMEOUT

    # matched?
    for key, timeout in skill_timeout_map.items():
        if is_matched_skill(folder_path, [key]):
            return int(timeout)

    # default
    default_timeout = DEFAULT_CALL_SKILL_TIMEOUT
    if skill_timeout_map.get("default"):
        default_timeout = int(skill_timeout_map["default"])

    return default_timeout

def call_skill(
        folder_path:str,
        cmd:str|list,
        no_need_stderr:int=0,
        timeout:int=120,
    ):
    """Execute a skill script

    Args:
        folder_path (str): required, a skill folder.
        cmd (str|list): required, The executable file must be in folder_path, otherwise it cannot be called.
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
            for _ in range(2):
                if cmd[0] in '/.':
                    cmd = cmd[1:]
            cmd = folder_path + "/" + cmd

    flag_cmd_matched = False
    for skill in get_skills_from_cache():
        if cmd_exe_file.startswith(skill.folder):
            flag_cmd_matched = True
            break
    assert flag_cmd_matched, \
        "Illegal cmd, The executable file must be an absolute path from skill folder OR no found this skill: error_exe_file=[%s]" % cmd_exe_file

    # enhance security
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)

    # hook
    hook_handler = skill_hook.SkillHookHandler(
        folder_path, cmd,
    )

    # ctxm
    ctxm_tool = lock_tool.ctxm_void
    if hook_handler.need_lock_session:
        ctxm_tool = lock_tool.ctxm_try_session_lock

    # timeout
    timeout = max(
        int(timeout),
        get_call_skill_timeout(folder_path),
    )

    # hook before
    hook_handler.handle_before_call_skill()

    result = None
    with ctxm_tool() as data:
        if isinstance(data, lock_tool.YieldData):
            if hook_handler.need_lock_session and data.get("session_id"):
                if not data.get("fp"):
                    return f"call_skill failed: {data.get("msg")}"

        result = exec_cmd(
            cmd,
            no_need_stderr=True if int(no_need_stderr) else False,
            timeout=int(timeout),
            cwd=folder_path,
        )
        hook_handler.data_agent_refresh_session.tool_result = result

        # hook after
        hook_handler.handle_after_call_skill()

        if result:
            if hook_handler.need_refresh_session and data.get("session_id"):
                hook_handler.data_agent_refresh_session.session_id = data.get("session_id")
                if not hook_handler.data_agent_refresh_session.tool_result:
                    hook_handler.data_agent_refresh_session.tool_result = result
                raise AgentNeedRefreshSession(hook_handler.data_agent_refresh_session)

        return result

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
