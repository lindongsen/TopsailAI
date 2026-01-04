'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-10
  Purpose: Sandbox tool for executing commands in different environments (SSH, Docker, etc.)
'''

import os

from topsailai.utils.cmd_tool import (
    exec_cmd_in_remote,
    exec_cmd,
)


class Sandbox(object):
    """Represents a sandbox configuration for command execution environments.

    Attributes:
        protocol (str): The protocol used for sandbox communication (e.g., 'ssh', 'docker')
        node (str): The target node or host for the sandbox
        tags (set): Set of tags associated with the sandbox
        port (int): Port number for SSH connections (default: 22)
        name (str): Name for Docker container or other named resources
    """
    def __init__(self):
        self.protocol = ""
        self.node = ""
        self.tags = set()

        # ssh
        self.port = 22

        # docker
        self.name = ""


def _parse_sandbox_config(sandbox:str) -> Sandbox:
    """Parse a sandbox configuration string into a Sandbox object.

    The configuration string uses comma-separated key=value pairs.
    Example: "protocol=ssh,node=example.com,tag=ai,port=2222"

    Args:
        sandbox (str): Configuration string with key=value pairs

    Returns:
        Sandbox: Configured Sandbox object with parsed attributes
    """
    sandbox_obj = Sandbox()
    # k1=v1,k2=v2
    for kv in sandbox.split(','):
        kv = kv.strip()
        if not kv:
            continue
        k, v = kv.split('=', 1)
        if k == "tag":
            sandbox_obj.tags.add(v)
        else:
            setattr(sandbox_obj, k, v)

    return sandbox_obj

def call_sandbox(sandbox:str, cmd:str, timeout:int=30):
    """ execute command in sandbox

    Args:
        sandbox (str): sandbox info, get it by `list_sandbox`, format like 'tag=x,protocol=y,node=z'
        cmd (str): command
        timeout (int): default 30 seconds
    """
    sandbox_obj = _parse_sandbox_config(sandbox)

    result = None
    if sandbox_obj.protocol == "ssh":
        result = exec_cmd_in_remote(
            cmd,
            remote=sandbox_obj.node,
            port=sandbox_obj.port,
            timeout=timeout or 30,
        )
    if result:
        from .cmd_tool import format_return
        return format_return(cmd, result)

    return "unknown sandbox"

def copy2sandbox(sandbox:str, local_fpath:str, sandbox_fpath:str, timeout:int=60) -> bool:
    """copy file/folder to sandbox

    Args:
        sandbox (str): get it by `list_sandbox`
        local_fpath (str): local path
        sandbox_fpath (str): a path of sandbox
        timeout (int, optional): _description_. Defaults to 60.

    Returns:
        bool: True for ok, False for failed.
    """
    sandbox_obj = _parse_sandbox_config(sandbox)

    if sandbox_obj.protocol == "ssh":
        if os.path.isdir(local_fpath):
            local_fname = os.path.basename(local_fpath)
            sandbox_fname = os.path.basename(sandbox_fpath)
            if local_fname == sandbox_fname:
                sandbox_fpath = os.path.dirname(sandbox_fpath)

        cmd = f"scp -r '{local_fpath}' '{sandbox_obj.name or "root"}@{sandbox_obj.node}:{sandbox_fpath}'"
        ret = exec_cmd(cmd, timeout=timeout, need_error_log=True)
        return ret[0] == 0
    return False

def list_sandbox(tag:str) -> str:
    """ list all of sandbox by tag

    Args:
      tag (str): a tag name.

    Return:
      str, One sandbox configuration per line
    """
    # split sandbox by ';', split key=value by ','.
    # example: tag=ai,protocol=ssh,node={hostname};tag=ai,protocol=docker,node={hostname},name={container_name}

    result = ""
    env_sandbox_settings = os.getenv("SANDBOX_SETTINGS")
    for sandbox_conf in env_sandbox_settings.split(';'):
        sandbox_conf = sandbox_conf.strip()
        if not sandbox_conf:
            continue
        if f"tag={tag}" not in sandbox_conf:
            continue
        result += sandbox_conf + "\n"
    return result.strip()

# Dictionary mapping tool names to their corresponding functions
TOOLS = dict(
    call_sandbox=call_sandbox,
    list_sandbox=list_sandbox,
    copy2sandbox=copy2sandbox,
)

PROMPT = """
## sandbox_tool
When the user mentions accessing the sandbox, you need to first use the `list_sandbox` to decide one target, and then use `call_sandbox` to execute command in it.
"""
