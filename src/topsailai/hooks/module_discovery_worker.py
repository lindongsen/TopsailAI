"""Worker-only import probing for configured hook modules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def main(context: Any) -> dict[str, object]:
    """Load one exact candidate in the isolated worker and validate callable main."""
    payload = context.event.payload
    source_path = Path(payload["source_path"])
    logical_name = payload["logical_name"]
    try:
        spec = importlib.util.spec_from_file_location(logical_name, source_path)
        if spec is None or spec.loader is None:
            return {"load_status": "load_error", "entry_valid": False}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException:
        return {"load_status": "load_error", "entry_valid": False}
    entry_valid = callable(getattr(module, "main", None))
    return {
        "load_status": "ready" if entry_valid else "invalid_entry",
        "entry_valid": entry_valid,
    }
