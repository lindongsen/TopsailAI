"""Importable handlers used by the runnable Unified Hooks demos."""

from __future__ import annotations

import os


def report_worker(context):
    """Return JSON-compatible delivery details from the isolated worker."""
    return {
        "binding": context.binding_id,
        "worker_pid": os.getpid(),
        "payload": dict(context.event.payload),
    }


def report_marker(context):
    """Return a small JSON-compatible marker from the isolated worker."""
    return {"binding": context.binding_id, "marker": context.event.payload["marker"]}


def fail_intentionally(context):
    """Raise a deliberate demo failure for structured error reporting."""
    raise RuntimeError("intentional demo failure")
