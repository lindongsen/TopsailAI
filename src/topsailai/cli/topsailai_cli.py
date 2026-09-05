#!/usr/bin/env python3
"""TopsailAI CLI entry point.

The interactive task watcher implementation has been moved into the
``cli_topsailai`` package.  This file remains a thin shim so that existing
invocations (``python topsailai.py``) continue to work.
"""

import os
import sys

from dotenv import load_dotenv


def _load_cli_environment() -> None:
    """Load CLI-specific environment files without overriding existing values."""
    startup_cwd = os.getcwd()
    candidates = [os.path.join(startup_cwd, ".topsailai_cli.env")]
    topsailai_home = os.environ.get("TOPSAILAI_HOME")
    if topsailai_home:
        topsailai_home = os.path.abspath(os.path.expanduser(topsailai_home))
    else:
        home = os.environ.get("HOME")
        topsailai_home = os.path.join(home, ".topsailai") if home else "/topsailai"
    candidates.append(os.path.join(topsailai_home, ".topsailai_cli.env"))

    loaded_paths = set()
    for env_path in candidates:
        normalized_path = os.path.abspath(env_path)
        if normalized_path in loaded_paths:
            continue
        loaded_paths.add(normalized_path)
        if os.path.isfile(normalized_path):
            load_dotenv(normalized_path, override=False)


_load_cli_environment()

import _import_topsailai  # noqa: E402,F401  (adds core project root to sys.path)
os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)

from cli_topsailai.core import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1:])
