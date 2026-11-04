"""Isolated explicit-plugin registration probe; author: DawsonLin."""

import json
import os
from pathlib import Path
import subprocess
from topsailai.utils.env_tool import resolve_python_interpreter


def inspect_plugin(storage, configured, enabled="*", disabled=""):
    """Inspect the real registry and prompts in a fresh process without LLM I/O."""
    root = Path(__file__).resolve().parents[2]
    storage = Path(storage)
    storage.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("TOPSAILAI_", "PLUGIN_", "ENABLED_", "DISABLED_"))}
    env.update(PYTHONPATH=os.pathsep.join((str(root), str(root.parent))),
               PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(storage),
               TOPSAILAI_HOME=str(storage / "home"),
               TOPSAILAI_EVENTS_ENABLED="0",
               TOPSAILAI_DISABLED_TOOLS=disabled,
               TOPSAILAI_ENABLED_TOOLS=enabled,
               TOPSAILAI_PLUGIN_TOOLS=str(root / "plugins" / "tools") if configured else "")
    code = """
import json
from topsailai.tools.base.init import TOOLS
from topsailai.tools.base.init import TOOL_MODULES
from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
from topsailai.tools.agent_tool_utils.story import agent_memory_as_story
names = sorted(name for name in TOOLS if name.startswith('agent_tool-'))
print('RESULT:' + json.dumps(dict(names=names,
    source=TOOL_MODULES.get('agent_tool'),
    bigfile_present='bigfile_tool-read_file' in TOOLS,
    prompt=get_prompt_by_tools(names), story_callable=callable(agent_memory_as_story))))
"""
    result = subprocess.run([resolve_python_interpreter(), "-B", "-c", code],
                            cwd=storage, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(next(line[7:] for line in result.stdout.splitlines()
                           if line.startswith("RESULT:")))
