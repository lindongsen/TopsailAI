#!/usr/bin/env python3
"""Record every skill execution into a compliance ledger.

Scenario: a platform team lets the agent run release-check skills against
production. Compliance requires an auditable record of which skill ran, with
which arguments, and whether it succeeded, because the ledger is reviewed after
an incident and the agent's own terminal output is gone by then. The ledger is
an external system with its own retention, so the skill tool must not embed a
writer for it. This Hook module observes the skill lifecycle and appends one
bounded record per execution.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LEDGER_ENV = "TOPSAILAI_COOKBOOK_SKILL_LEDGER_FILE"
MAX_RECORDS = 500


def _ledger_path() -> Path:
    """Return the absolute ledger path selected by the operator.

    Returns:
        The ledger file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(LEDGER_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{LEDGER_ENV} must name an absolute file path")
    return Path(raw)


def _read_records(path: Path) -> list[dict]:
    """Load existing ledger records, tolerating a missing or broken file.

    Args:
        path: The ledger file path.

    Returns:
        The stored records, or an empty list when the file cannot be used.
    """
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _append(record: dict) -> None:
    """Append one record to the bounded ledger, replacing it atomically.

    Args:
        record: The ledger entry to store.
    """
    path = _ledger_path()
    records = _read_records(path)
    records.append(record)
    records = records[-MAX_RECORDS:]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    temporary.replace(path)


def _now() -> str:
    """Return the current local time as an ISO-8601 string.

    Returns:
        The timestamp with a timezone offset.
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def handle_before_call_skill(handler) -> None:
    """Record the intent to run a skill before the script starts.

    Args:
        handler: The skill hook handler exposing the folder and command list.
    """
    _append(
        {
            "phase": "before",
            "at": _now(),
            "skill_folder": handler.skill_folder,
            "cmd": list(handler.cmd_list),
            "lock_session": bool(handler.need_lock_session),
            "refresh_session": bool(handler.need_refresh_session),
        }
    )


def handle_after_call_skill(handler) -> None:
    """Record the outcome of a skill run after the script finished.

    Args:
        handler: The skill hook handler exposing the tool result.
    """
    result = handler.data_agent_refresh_session.tool_result
    code = None
    if isinstance(result, tuple) and result:
        code = result[0]
    _append(
        {
            "phase": "after",
            "at": _now(),
            "skill_folder": handler.skill_folder,
            "cmd": list(handler.cmd_list),
            "exit_code": code,
        }
    )


HOOKS = {
    "handle_before_call_skill": handle_before_call_skill,
    "handle_after_call_skill": handle_after_call_skill,
}
