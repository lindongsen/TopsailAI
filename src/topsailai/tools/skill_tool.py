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
    exists_skill,
    get_skill_file,
    get_script_path,
    parse_skill_folder,
)
from topsailai.tools.cmd_tool import format_return
from topsailai.utils import (
    json_tool,
    env_tool,
    format_tool,
    file_tool,
)
from topsailai.utils.cmd_tool import exec_cmd
from topsailai.prompt_hub import prompt_tool
from topsailai.ai_base.agent_types.exception import (
    AgentNeedRefreshSession,
)
from topsailai.workspace import lock_tool


DEFAULT_CALL_SKILL_TIMEOUT = 600

def get_call_skill_timeout(skill_folder:str) -> int:
    """ get timeout from environ """

    timeout_map_s = env_tool.EnvReaderInstance.get("TOPSAILAI_CALL_SKILL_TIMEOUT_MAP")
    if not timeout_map_s:
        return DEFAULT_CALL_SKILL_TIMEOUT

    skill_timeout_map = format_tool.parse_str_to_dict(timeout_map_s, kv_strip=True)
    if not skill_timeout_map:
        return DEFAULT_CALL_SKILL_TIMEOUT

    # matched?
    for key, timeout in skill_timeout_map.items():
        if is_matched_skill(skill_folder, [key]):
            return int(timeout)

    # default
    default_timeout = DEFAULT_CALL_SKILL_TIMEOUT
    if skill_timeout_map.get("default"):
        default_timeout = int(skill_timeout_map["default"])

    return default_timeout

def call_skill(
        skill_folder:str,
        script_path:str,
        script_parameters:str|list="",
        no_need_stderr:int=0,
        timeout:int=120,
        output_file:str=None,
        environ:str=None,
    ):
    """Can only execute scripts that exist in the skill-folder, cannot execute other command lines!

    Args:
        skill_folder (str): required, a skill folder.
        script_path (str): required, The executable file (MUST EXIST) in skill_folder, otherwise it cannot be called.
        script_parameters (str|list): optional

        no_need_stderr (int, optional): If 1, stderr will be returned as empty string.
                               Defaults to 0.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a exception will be raised.
                                 Defaults to 120.
        output_file (str, optional): Save stdout to a file path.
                           The result may be truncated due to the content being too long.
                           You can output it to a file and then process the large text.
        environ (str, optional): JSON str, dict, environment variables.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.
    """

    # environ
    environ_d = environ
    if isinstance(environ, str):
        environ_d = json_tool.safe_json_load(environ)
    if not isinstance(environ_d, dict):
        environ_d = None
    if environ and not environ_d:
        raise Exception("error parameter 'environ': it should be JSON and MAP format")

    # check parameter: output_file
    if output_file:
        assert output_file[0] == '/', "The output_file MUST be a absolute path"

        if not file_tool.is_tmp_dir(output_file):
            assert not os.path.exists(output_file), "The output_file already exists and cannot be overwritten"

    # format script_path
    script_path = get_script_path(skill_folder, script_path)

    # cmd
    if isinstance(script_parameters, list):
        cmd = [
            script_path.strip(),
        ] + script_parameters
    else:
        cmd = f"{script_path.strip()} {script_parameters.strip()}".strip()

    # check parameter: cmd
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
    else:
        # For string commands, extract just the executable path (first word)
        cmd_exe_file = cmd.split()[0] if cmd else cmd

    if not cmd_exe_file:
        raise Exception("illegal cmd: [%s]" % raw_cmd)

    if not cmd_exe_file.startswith(skill_folder):
        # case: /xxx or .xxx
        for _ in range(2):
            if cmd_exe_file[0] in ['/', '.']:
                cmd_exe_file = cmd_exe_file[1:]
            else:
                break

        cmd_exe_file = os.path.join(skill_folder, cmd_exe_file)
        if isinstance(cmd, list):
            cmd[0] = cmd_exe_file
        else:
            for _ in range(2):
                if cmd[0] in '/.':
                    cmd = cmd[1:]
            cmd = skill_folder + "/" + cmd

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
        skill_folder, cmd,
    )

    # ctxm
    ctxm_tool = lock_tool.ctxm_void
    if hook_handler.need_lock_session:
        ctxm_tool = lock_tool.ctxm_try_session_lock

    # timeout
    timeout = max(
        int(timeout),
        get_call_skill_timeout(skill_folder),
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
            cwd=skill_folder,
            env_info=environ_d,
        )
        hook_handler.data_agent_refresh_session.tool_result = result

        # hook after
        hook_handler.handle_after_call_skill()

        if result:
            # save stdout to the output_file
            if output_file and result[1]:
                with open(output_file, mode='w', encoding='utf-8') as fp:
                    fp.write(result[1])

            if hook_handler.need_refresh_session and data.get("session_id"):
                hook_handler.data_agent_refresh_session.session_id = data.get("session_id")
                if not hook_handler.data_agent_refresh_session.tool_result:
                    hook_handler.data_agent_refresh_session.tool_result = result
                raise AgentNeedRefreshSession(hook_handler.data_agent_refresh_session)

        return format_return(cmd, result)

def overview_skill(skill_folder:str):
    """ Retrieve entire details of skill.
    Args:
        skill_folder (str): required, skill folder.
    """
    return overview_skill_native(skill_folder)

def read_skill_file(
        skill_folder:str,
        file_name:str,
    ):
    """
    Can only Read A File from skill folder.

    Args:
        skill_folder (str): a skill folder
        file_name (str): a file with relative path
    """
    assert exists_skill(skill_folder), f"no found this skill folder: {skill_folder}"

    file_path = get_skill_file(skill_folder, file_name)
    assert file_path, f"no found this skill file: {file_name}"

    file_content = ""
    with open(file_path, encoding='utf-8') as fp:
        file_content = fp.read()

    return file_content

def load_skill(skill_folder:str):
    """Load a new SKILL

    Args:
        skill_folder (str):
    """
    s = parse_skill_folder(skill_folder)
    assert s.name, f"load skill failed: {skill_folder}"
    return s.markdown


TOOLS = dict(
    call_skill=call_skill,
    overview_skill=overview_skill,
    read_skill_file=read_skill_file,
    load_skill=load_skill,
)

PROMPT_SKILL_TOOL_RULE = """
## Mandatory Skill Inspection
- **Trigger:** Whenever a task is related to a skill, you **MUST** call the `overview_skill` tool immediately.
- **Purpose:** To retrieve the **full, up-to-date details** (parameters, constraints, dependencies) required for execution.
- **Constraint:** The skill information provided in the system prompt is **only a summary** for identification purposes. It is **strictly forbidden** to execute a skill based solely on this summary. You must rely on the output from `overview_skill` for all execution logic.
---

"""

PROMPT_SKILL = prompt_tool.read_prompt("skills/skill.md") + PROMPT_SKILL_TOOL_RULE

PROMPT_PLUGIN_SKILLS = ""
PROMPT = ""
FLAG_TOOL_ENABLED = False

def reload():
    """ reload prompt """
    global PROMPT_PLUGIN_SKILLS
    PROMPT_PLUGIN_SKILLS = get_skill_markdown()

    global PROMPT
    PROMPT = PROMPT_SKILL + PROMPT_PLUGIN_SKILLS

    global FLAG_TOOL_ENABLED
    FLAG_TOOL_ENABLED = True if PROMPT_PLUGIN_SKILLS else False

    return

reload()
