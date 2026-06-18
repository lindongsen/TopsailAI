from topsailai.utils.text_tool import safe_decode
from topsailai.utils.cmd_tool import exec_cmd as exec_command
from topsailai.utils.json_tool import safe_json_load
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.context import ctx_safe
from topsailai.prompt_hub import prompt_tool


def format_text(s, need_truncate=True):
    """ decode and truncate

    :s: str/bytes
    """
    s = safe_decode(s).strip()
    if need_truncate:
        s = ctx_safe.truncate_message(s).strip()
    return s

def _need_whole_stdout(cmd_string:str):
    """ some cases need stdout """

    # curl wikipedia.org
    if cmd_string.startswith("curl "):
        for key in [
            "wikipedia.org",
        ]:
            if key in cmd_string:
                return True

    return False

def _format_return(cmd_string: str, t:tuple):
    """ truncate text for stdout and stderr """
    need_truncate = True
    if _need_whole_stdout(cmd_string):
        need_truncate = False
    return (t[0], format_text(t[1], need_truncate=need_truncate), format_text(t[2]))

def format_return(cmd:str|list, t:tuple):
    """ hack result """
    cmd_string = " ".join(cmd) if isinstance(cmd, list) else cmd

    # no need stderr
    for tool in [
        "curl", "wget",
        "uv add", "uv sync",
        "pip install",
    ]:
        if not t[2]:
            break
        if cmd_string.startswith(tool + " "):
            t = (t[0], t[1], "")
            return _format_return(cmd_string, t)

    return _format_return(cmd_string, t)

def get_cmd_timeout(cmd:str|list, timeout:int) -> int:
    timeout = int(timeout)
    raw_timeout = timeout

    env_cmd_timeout_map = EnvReaderInstance.get("TOPSALAI_TOOL_CMD_TIMEOUT_MAP")
    if not env_cmd_timeout_map:
        return timeout

    env_cmd_timeout_map = safe_json_load(env_cmd_timeout_map)
    if not env_cmd_timeout_map:
        return timeout

    # list_dict
    # [
    # {
    #     "cmd": "pytest ",
    #     "min_timeout": 300,
    #     "max_timeout": 0
    # }
    # ]
    for item in env_cmd_timeout_map:
        item_cmd = item.get("cmd")
        if not item_cmd:
            continue

        min_timeout = int(item.get("min_timeout") or 0)
        max_timeout = int(item.get("max_timeout") or 0)

        if not min_timeout and not max_timeout:
            continue

        if min_timeout and max_timeout:
            if timeout >= min_timeout and timeout <= max_timeout:
                continue

        _matched = False
        if isinstance(cmd, str):
            if item_cmd in cmd:
                _matched = True
        else:
            if item_cmd.strip() in cmd:
                _matched = True
        if not _matched:
            continue

        if min_timeout and timeout < min_timeout:
            timeout = min_timeout
        if max_timeout and timeout > max_timeout:
            timeout = max_timeout
        if timeout != raw_timeout:
            return timeout

    return timeout


def exec_cmd(
        cmd:str|list,
        no_need_stderr:int=0,
        timeout:int=120,
        cwd:str="/tmp",
        env:dict|None=None,
    ):
    """ execute command

    Args:
        cmd (str|list): example "echo hello" or ["echo", "hello"], use str for "pipe/redirect/Logical operation" else use list
        no_need_stderr (int, optional): if 1, stderr still be null. Defaults to 0.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a exception will be raised.
                                 Defaults to 120.
        env: (dict, optional): environment variables
    Returns:
        tuple: (code, stdout, stderr)
    """
    if isinstance(cmd, str):
        if cmd[0] == '[' and cmd[-1] == ']':
            fixed_cmd = safe_json_load(cmd)
            if fixed_cmd:
                cmd = fixed_cmd

    if not isinstance(cmd, str) and not isinstance(cmd, list):
        return "illegal cmd"

    if env:
        env = safe_json_load(env)

    result = exec_command(
        cmd,
        no_need_stderr=True if int(no_need_stderr) else False,
        timeout=get_cmd_timeout(cmd, timeout),
        cwd=cwd,
        env_info=env,
    )

    cmd_string = " ".join(cmd) if isinstance(cmd, list) else cmd

    return format_return(cmd_string, result)

# name: func
TOOLS = dict(
    exec_cmd=exec_cmd,
)

PROMPT_REQUIRED = """
# Requirements For Command
1. DONOT use `killall` or `pkill -f` to terminate processes by name; you MUST specify the exact process ID with `kill {pid}`
"""

PROMPT = prompt_tool.read_prompt("search/cmd_text.md") + PROMPT_REQUIRED
