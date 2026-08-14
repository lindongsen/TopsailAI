#!/usr/bin/env python3
"""TopsailAI CLI entry point.

The interactive task watcher implementation has been moved into the
``cli_topsailai`` package.  This file remains a thin shim so that existing
invocations (``python topsailai.py``) continue to work.
"""

import os
import sys

import _import_topsailai  # noqa: F401  (adds core project root to sys.path)
os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)

from cli_topsailai.core import main

if __name__ == "__main__":
    main(sys.argv[1:])
