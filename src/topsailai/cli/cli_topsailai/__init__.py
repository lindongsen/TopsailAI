"""TopsailAI CLI package.

This package contains the refactored modules originally living in the
monolithic ``topsailai.py`` script.  The top-level ``topsailai.py`` file
is now a thin entry-point shim; callers should import the specific
submodule they need instead of importing this package.
"""
