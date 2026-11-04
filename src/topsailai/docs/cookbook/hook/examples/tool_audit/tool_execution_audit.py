"""Write bounded tool-execution audit snapshots for an operations review.

During an incident review an operator must decide whether the agent really called
the tools it claims it called, and must not retain argument values, results, or
exception messages while collecting that evidence. Each Hook phase overwrites one
small JSON file, so the example cannot create an unbounded audit log.
"""

import json
import os
from pathlib import Path

AUDIT_FOLDER_ENV = "TOPSAILAI_COOKBOOK_HOOK_AUDIT_DIR"
ALLOWED_COMMON_FIELDS = ("tool_name", "argument_count", "argument_keys")


def _phase(payload: dict) -> str:
    """Identify the tool lifecycle phase from its point-specific metadata."""
    if "error_category" in payload:
        return "error"
    if "duration_sec" in payload:
        return "after"
    return "before"


def _audit_folder() -> Path:
    """Return the existing absolute folder selected by the operator."""
    raw_path = os.getenv(AUDIT_FOLDER_ENV, "")
    path = Path(raw_path)
    if not raw_path or not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{AUDIT_FOLDER_ENV} must name an existing absolute directory")
    return path


def _safe_record(payload: dict) -> dict:
    """Project the Hook payload onto the documented metadata allowlist."""
    phase = _phase(payload)
    record = {"phase": phase}
    for field in ALLOWED_COMMON_FIELDS:
        value = payload.get(field)
        record[field] = list(value) if field == "argument_keys" else value
    if phase == "after":
        record["duration_sec"] = payload["duration_sec"]
    elif phase == "error":
        record["error_category"] = payload["error_category"]
    return record


def main(**payload):
    """Atomically replace the bounded audit snapshot for this lifecycle phase."""
    record = _safe_record(payload)
    destination = _audit_folder() / f"tool-{record['phase']}.json"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return record
