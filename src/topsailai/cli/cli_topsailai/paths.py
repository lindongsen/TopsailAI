"""Path resolution helpers for the TopsailAI CLI."""

import os


def get_topsailai_home() -> str:
    """
    Resolve TOPSAILAI_HOME with the following priority:
    1. Environment variable TOPSAILAI_HOME (supports ~ expansion and absolute path)
    2. Default: ~/.topsailai
    3. Fallback: /topsailai
    """
    env_home = os.environ.get("TOPSAILAI_HOME")
    if env_home:
        if env_home.startswith("~"):
            home = os.environ.get("HOME")
            if home:
                env_home = home + env_home[1:]
        env_home = os.path.abspath(env_home)
        os.environ["TOPSAILAI_HOME"] = env_home
        return env_home

    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".topsailai")

    return "/topsailai"


def expand_path(path: str) -> str:
    """Expand ``~`` and environment variables in *path*."""
    return os.path.expandvars(os.path.expanduser(path))


def get_workspace_root(path: str = "") -> str:
    """Return the workspace root used by the CLI.

    The CLI historically used ``/TopsailAI`` as the fixed workspace root.
    This helper preserves that default while allowing override via the
    ``TOPSAILAI_WORKSPACE_ROOT`` environment variable.

    Args:
        path: Optional path to resolve relative to the workspace root.

    Returns:
        The workspace root, or the joined path if *path* is provided.
    """
    root = os.environ.get("TOPSAILAI_WORKSPACE_ROOT", "/TopsailAI")
    if path:
        return os.path.join(root, path)
    return root
