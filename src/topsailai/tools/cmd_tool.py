from topsailai.utils.text_tool import safe_decode
from topsailai.utils.cmd_tool import exec_cmd as exec_command
from topsailai.utils.json_tool import safe_json_load
from topsailai.context import ctx_safe

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

def exec_cmd(
        cmd:str|list,
        no_need_stderr:int=0,
        timeout:int=120,
        cwd:str="/tmp",
    ):
    """ execute command

    Args:
        cmd (str|list): example "echo hello" or ["echo", "hello"]
        no_need_stderr (int, optional): if 1, stderr still be null. Defaults to 0.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a exception will be raised.
                                 Defaults to 120.
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

    result = exec_command(
        cmd,
        no_need_stderr=True if int(no_need_stderr) else False,
        timeout=int(timeout),
        cwd=cwd,
    )

    cmd_string = " ".join(cmd) if isinstance(cmd, list) else cmd

    return format_return(cmd_string, result)

# name: func
TOOLS = dict(
    exec_cmd=exec_cmd,
)
