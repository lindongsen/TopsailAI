#!/usr/bin/env python3
"""TopsailAI model registry CLI entry point.

This script is dispatched through ``../bin/topsailai_models`` (a symlink to
``topsailai.cli``).  The basename ``topsailai_models`` is resolved by the
wrapper and mapped to ``cli/topsailai_models.py``.
"""

from cli_topsailai.core import main

if __name__ == "__main__":
    import sys

    main(["models"] + sys.argv[1:])
