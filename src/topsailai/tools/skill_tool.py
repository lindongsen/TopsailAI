'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-19
  Purpose:
'''
import subprocess

import os
from topsailai.logger import logger
import shlex

from topsailai.skill_hub import skill_hook
from topsailai.skill_hub.skill_tool import (
    g_skills,
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


class SkillToolError(ValueError):
    """Raised when a skill call fails due to invalid input or environment."""
    pass


DEFAULT_CALL_SKILL_TIMEOUT = 600


def _parse_timeout_value(raw_value, key_name: str) -> int:
    """Parse a timeout value from the timeout map and validate it.

    Args:
        raw_value: The raw timeout value from the map.
        key_name: The skill key (or 'default') being parsed, used in error messages.

    Returns:
        int: A positive timeout in seconds.

    Raises:
        SkillToolError: If the value is not a positive integer.
    """
    try:
        timeout_value = int(raw_value)
    except (ValueError, TypeError) as exc:
        raise SkillToolError(
            f"Invalid timeout value for '{key_name}' in TOPSAILAI_CALL_SKILL_TIMEOUT_MAP: "
            f"{raw_value!r} is not an integer. "
            "Use a positive integer in seconds, e.g. 'ai-community=86400'."
        ) from exc

    if timeout_value <= 0:
        raise SkillToolError(
            f"Invalid timeout value for '{key_name}' in TOPSAILAI_CALL_SKILL_TIMEOUT_MAP: "
            f"{timeout_value} is not positive. "
            "Use a positive integer in seconds, e.g. 'ai-community=86400'."
        )

    return timeout_value


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
            return _parse_timeout_value(timeout, key)

    # default
    default_timeout = DEFAULT_CALL_SKILL_TIMEOUT
    if skill_timeout_map.get("default"):
        default_timeout = _parse_timeout_value(skill_timeout_map["default"], "default")

    return default_timeout


def call_skill(
        skill_folder:str,
        script_path:str,
        script_parameters:str|list="",
        no_need_stderr:int=0,
        timeout:int=120,
        output_file:str=None,
        environ:str=None,
        stdin_text:str|None=None,
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
        stdin_text (str, optional): Text data to pass to the skill script via stdin.
                           When provided, the text is encoded as UTF-8 and forwarded
                           as the subprocess input. Useful for piping data such as
                           `topsailai_data put xxx yyy --from -`.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.
    """
    # validate skill_folder first
    if not skill_folder or not os.path.isdir(skill_folder):
        raise SkillToolError(
            "Skill folder does not exist or is not a directory. "
            f"Provided: {skill_folder!r}. "
            "Check the folder path and ensure the skill is loaded."
        )

    # environ
    environ_d = environ
    if isinstance(environ, str):
        environ_d = json_tool.safe_json_load(environ)
    if not isinstance(environ_d, dict):
        environ_d = None
    if environ is not None and environ_d is None:
        raise SkillToolError(
            "A skill accepts environment variables only as a JSON object. "
            f"The provided environ {environ!r} is not a valid object. "
            "Pass a dict or a JSON object string such as '{\"KEY\": \"value\"}'."
        )

    # check parameter: output_file
    if output_file:
        if output_file[0] != '/':
            raise SkillToolError(
                f"output_file must be an absolute path, got {output_file!r}. "
                "Provide a full path such as '/tmp/output.txt'."
            )

        if not file_tool.is_tmp_dir(output_file) and os.path.exists(output_file):
            raise SkillToolError(
                f"output_file already exists and cannot be overwritten: {output_file!r}. "
                "Choose a different path or delete the existing file first."
            )

    # validate script_path before get_script_path normalizes it
    if script_path.startswith(("/", "~", "\\")):
        raise SkillToolError(
            "A skill can only run scripts that exist inside its own folder. "
            f"The provided path {script_path!r} is absolute; use a path relative to the skill folder."
        )

    # format script_path
    script_path = get_script_path(skill_folder, script_path)

    # resolved path must stay inside skill_folder
    real_skill_folder = os.path.realpath(skill_folder)
    real_script = os.path.realpath(os.path.join(skill_folder, script_path))
    if not real_script.startswith(real_skill_folder + os.sep):
        raise SkillToolError(
            "A skill can only run scripts that exist inside its own folder. "
            f"The resolved path {real_script!r} is outside the skill folder {real_skill_folder!r}."
        )

    # target must exist and be a regular file
    if not os.path.isfile(real_script):
        raise SkillToolError(
            "A skill can only run scripts that exist inside its own folder. "
            f"The requested script {script_path!r} was not found inside {skill_folder!r}."
        )

    # target must be executable
    if not os.access(real_script, os.X_OK):
        raise SkillToolError(
            f"Script {real_script!r} exists but is not executable. "
            f"Run 'chmod +x {script_path}' or invoke it with an interpreter "
            f"such as 'python {script_path}'."
        )

    # cmd
    if isinstance(script_parameters, list):
        cmd = [
            script_path.strip(),
        ] + script_parameters
    else:
        cmd = f"{script_path.strip()} {script_parameters.strip()}".strip()

    # check parameter: cmd
    raw_cmd = cmd
    if isinstance(cmd, list):
        cmd_exe_file = cmd[0]
    elif isinstance(cmd, str):
        if cmd[0] == "[":
            # json str
            cmd = json_tool.safe_json_load(cmd)
            cmd_exe_file = cmd[0] if isinstance(cmd, list) and cmd else ""
        else:
            # For string commands, extract just the executable path (first word)
            cmd_exe_file = cmd.split()[0] if cmd else cmd
    else:
        cmd_exe_file = ""

    if not cmd_exe_file:
        raise SkillToolError(
            f"Could not determine the executable from script_parameters: {raw_cmd!r}. "
            "Provide a valid script path and parameters."
        )

    # resolved executable must stay inside skill_folder
    real_cmd_exe = os.path.realpath(cmd_exe_file)
    if not real_cmd_exe.startswith(real_skill_folder + os.sep):
        raise SkillToolError(
            f"The executable {cmd_exe_file!r} resolves outside the skill folder "
            f"{real_skill_folder!r}. Use a script path relative to the skill folder."
        )

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
    exec_kwargs = {}
    if stdin_text is not None:
        if not isinstance(stdin_text, str):
            raise SkillToolError(
                f"stdin_text must be a string, got {type(stdin_text).__name__}. "
                "Pass a UTF-8 text string or omit the argument."
            )
        exec_kwargs["input"] = stdin_text.encode("utf-8")

    with ctxm_tool() as data:
        if isinstance(data, lock_tool.YieldData):
            if hook_handler.need_lock_session and data.get("session_id"):
                if not data.get("fp"):
                    msg = data.get("msg") or "unknown lock error"
                    return (
                        1,
                        "",
                        f"call_skill failed: {msg}. "
                        "Wait for the other process to release the session lock, "
                        "or remove this skill from TOPSAILAI_SESSION_LOCK_ON_SKILLS."
                    )

        try:
            result = exec_cmd(
                cmd,
                no_need_stderr=True if int(no_need_stderr) else False,
                timeout=int(timeout),
                cwd=skill_folder,
                env_info=environ_d,
                **exec_kwargs,
            )
        except subprocess.TimeoutExpired:
            logger.exception(
                "Skill script timed out: skill=%s script=%s timeout=%s",
                skill_folder, script_path, timeout,
            )
            return (
                1,
                "",
                f"Skill script timed out after {timeout}s. "
                "Increase the timeout argument or optimize the script."
            )
        except PermissionError as exc:
            logger.exception(
                "Permission denied executing skill script: %s", exc,
            )
            return (
                1,
                "",
                f"Permission denied executing {script_path!r}. "
                "Check file permissions and ownership."
            )

        hook_handler.data_agent_refresh_session.tool_result = result

        # hook after
        hook_handler.handle_after_call_skill()

        if result:
            # save stdout to the output_file
            if output_file and result[1]:
                output_dir = os.path.dirname(output_file)
                if output_dir and not os.path.exists(output_dir):
                    os.makedirs(output_dir, exist_ok=True)
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
    if not skill_folder or not os.path.isdir(skill_folder):
        raise SkillToolError(
            f"Skill folder does not exist or is not a directory: {skill_folder!r}. "
            "Provide a valid skill folder path."
        )
    return overview_skill_native(skill_folder)


def _validate_skill_file_name(file_name: str) -> None:
    """Validate that a skill file name is safe to resolve.

    Args:
        file_name: The requested file name relative to the skill folder.

    Raises:
        SkillToolError: If the file name is empty or uses an absolute/tilde/backslash prefix.
    """
    if not file_name:
        raise SkillToolError(
            "file_name cannot be empty. "
            "Provide a relative path inside the skill folder, e.g. 'scripts/run.sh'."
        )

    if file_name.startswith(("/", "~", "\\")):
        raise SkillToolError(
            f"file_name must be a relative path inside the skill folder, got {file_name!r}. "
            "Use a path such as 'scripts/run.sh' or 'README.md'."
        )


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
    if not skill_folder or not os.path.isdir(skill_folder):
        raise SkillToolError(
            f"Skill folder does not exist or is not a directory: {skill_folder!r}. "
            "Provide a valid skill folder path."
        )

    if not exists_skill(skill_folder):
        raise SkillToolError(
            f"Skill is not loaded: {skill_folder!r}. "
            "Call load_skill() or ensure the skill is listed in TOPSAILAI_PLUGIN_SKILLS."
        )

    _validate_skill_file_name(file_name)

    file_path = get_skill_file(skill_folder, file_name)
    if not file_path:
        raise SkillToolError(
            f"File {file_name!r} not found in skill folder {skill_folder!r}. "
            "Use a relative path such as 'scripts/run.sh' or 'README.md'."
        )

    real_folder = os.path.realpath(skill_folder)
    real_file = os.path.realpath(file_path)
    if not real_file.startswith(real_folder + os.sep):
        raise SkillToolError(
            f"Resolved file {real_file!r} is outside the skill folder {real_folder!r}. "
            "Use a relative path that stays inside the skill folder."
        )

    try:
        with open(file_path, encoding='utf-8') as fp:
            return fp.read()
    except PermissionError as exc:
        raise SkillToolError(
            f"Permission denied reading {file_path!r}. "
            "Check file permissions and ownership."
        ) from exc
    except UnicodeDecodeError as exc:
        raise SkillToolError(
            f"File {file_path!r} is not valid UTF-8 text: {exc}. "
            "Use a tool designed for binary files if needed."
        ) from exc

def load_skill(skill_folder:str):
    """Load a new SKILL

    Args:
        skill_folder (str):

    Raises:
        RuntimeError: when the skill folder is invalid, disabled, or a
            duplicate basename has already been loaded and no valid name
            could be resolved.
    """
    s = parse_skill_folder(skill_folder)
    if not s.name:
        raise RuntimeError(
            f"load skill failed: {skill_folder} "
            "(no valid SKILL.md, skill disabled, or duplicate basename already loaded)"
        )
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
