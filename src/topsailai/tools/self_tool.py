"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-10
  Purpose: Let the agent know itself by reading its own session metadata file.
"""

import json
import os

from topsailai.logger import logger
from topsailai.workspace import session_meta


def _resolve_related_files(meta_file: str, files) -> dict:
    """Resolve stored related-file names into absolute paths.

    The metadata file stores bare basenames because every related file lives in
    the same task folder. The agent needs absolute paths so it can read them
    directly, so resolution happens here instead of at every call site.

    Args:
        meta_file: Absolute path of the metadata file.
        files: Stored mapping of file type to basename.

    Returns:
        dict: Mapping of file type to absolute path. Non-mapping input yields {}.
    """
    if not isinstance(files, dict):
        return {}
    base_folder = os.path.dirname(meta_file)
    resolved = {}
    for file_type, name in files.items():
        if not isinstance(name, str) or not name:
            continue
        resolved[file_type] = (
            name if os.path.isabs(name) else os.path.join(base_folder, name)
        )
    return resolved


def get_self_info() -> dict:
    """Return this agent's own runtime identity and work details.

    The information comes from the session metadata file of the current process,
    so it reflects the live session state, including a session name that is
    generated asynchronously after startup.

    Returns:
        dict: status is "ok", "not_found", or "invalid_meta".
            On "ok": meta_file holds the metadata file path, self holds every
            stored field, and files holds absolute paths of related session
            files such as the events log and the stdout log.
            On "not_found": meta_file holds the expected path.
            On "invalid_meta": meta_file and reason explain the failure.
    """
    meta_file = session_meta.get_session_meta_path()
    if not os.path.isfile(meta_file):
        logger.debug("[self_tool] Session meta file not found: %s", meta_file)
        return {
            "status": "not_found",
            "meta_file": meta_file,
            "reason": "session metadata file does not exist yet",
        }

    try:
        with open(meta_file, "r", encoding="utf-8") as fd:
            meta = json.load(fd)
    except (OSError, ValueError) as error:
        logger.warning("[self_tool] Failed to read session meta %s: %s", meta_file, error)
        return {
            "status": "invalid_meta",
            "meta_file": meta_file,
            "reason": f"cannot read session metadata: {error}",
        }

    if not isinstance(meta, dict):
        logger.warning("[self_tool] Session meta is not an object: %s", meta_file)
        return {
            "status": "invalid_meta",
            "meta_file": meta_file,
            "reason": "session metadata is not a JSON object",
        }

    return {
        "status": "ok",
        "meta_file": meta_file,
        "self": meta,
        "files": _resolve_related_files(meta_file, meta.get("files")),
    }


PROMPT = """
## self_tool (get_self_info)

Call `get_self_info` with no arguments to learn this agent's own identity and
runtime configuration.

The `files` paths it returns are absolute; read them with `file_tool`. Historical
details such as past messages and recorded events are recoverable from those
files, so read them before claiming that earlier context is unavailable.
"""

TOOLS = dict(
    get_self_info=get_self_info,
)
