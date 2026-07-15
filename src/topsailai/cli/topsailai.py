#!/usr/bin/env python3
"""TopsailAI CLI entry point.

The interactive task watcher implementation has been moved into the
``cli_topsailai`` package.  This file remains a thin shim so that existing
invocations (``python topsailai.py``) continue to work.
"""

from cli_topsailai.core import main

if __name__ == "__main__":
    main()
