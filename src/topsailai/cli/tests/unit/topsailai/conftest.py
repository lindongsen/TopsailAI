#!/usr/bin/env python3
"""Pytest bootstrap: expose the core project root for imports."""

import sys
from pathlib import Path

# Add <repo-root>/src to sys.path so ``import topsailai`` resolves to the
# core package rather than the sibling CLI script ``topsailai.py``.
SRC_ROOT = str(Path(__file__).resolve().parents[5])
sys.path = [SRC_ROOT] + [p for p in sys.path if p != SRC_ROOT]
