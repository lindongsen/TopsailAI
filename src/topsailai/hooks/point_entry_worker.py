"""Standalone child runner for prototype Module main entries.

Author: DawsonLin
"""

import asyncio
import importlib.util
import inspect
import json
from pathlib import Path
import sys


def run():
    """Import a selected file only in the child and await any normal awaitable."""
    path = Path(sys.argv[1])
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("hook_point_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main(**json.loads(sys.argv[2]))
    if inspect.isawaitable(result):
        asyncio.run(await_result(result))


async def await_result(result):
    """Adapt arbitrary awaitables to the coroutine expected by asyncio.run."""
    return await result


if __name__ == "__main__":
    run()
