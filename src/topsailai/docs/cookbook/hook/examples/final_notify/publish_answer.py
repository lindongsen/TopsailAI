#!/usr/bin/env python3
"""Publish one agent final answer to an on-call ticket queue.

Scenario: an on-call engineer asks the agent to triage an alert. The answer is
useful only if it reaches the ticket queue that the rest of the rotation reads,
because the engineer may close the terminal before reading it. The queue is an
external system with its own credentials and its own retention, so the agent
must not embed a client for it. This consumer receives the answer through the
environment and appends one bounded record to a queue file.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

QUEUE_ENV = "TOPSAILAI_COOKBOOK_TICKET_QUEUE_FILE"
ANSWER_ENV = "TOPSAILAI_FINAL_ANSWER"
MAX_RECORDS = 200
MAX_ANSWER_CHARS = 4000


def _queue_path() -> Path:
    """Return the absolute queue path selected by the operator.

    Returns:
        The queue file path.

    Raises:
        ValueError: When the variable is unset or not absolute.
    """
    raw = os.getenv(QUEUE_ENV, "").strip()
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{QUEUE_ENV} must name an absolute file path")
    return Path(raw)


def _read_records(path: Path) -> list[dict]:
    """Load existing queue records, tolerating a missing or broken file.

    Args:
        path: The queue file path.

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


def main() -> int:
    """Append the current final answer to the bounded ticket queue.

    Returns:
        0 on success, 2 when the answer or configuration is unusable.
    """
    answer = os.getenv(ANSWER_ENV, "")
    if not answer.strip():
        print(f"error: {ANSWER_ENV} is empty; nothing to publish", file=sys.stderr)
        return 2

    try:
        path = _queue_path()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    truncated = len(answer) > MAX_ANSWER_CHARS
    record = {
        "published_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "answer": answer[:MAX_ANSWER_CHARS],
        "truncated": truncated,
        "session_id": os.getenv("TOPSAILAI_SESSION_ID") or os.getenv("SESSION_ID") or "",
        "task_id": os.getenv("TOPSAILAI_TASK_ID", ""),
    }

    records = _read_records(path)
    records.append(record)
    records = records[-MAX_RECORDS:]

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    temporary.replace(path)
    print(f"published answer_chars={len(record['answer'])} truncated={truncated} records={len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
