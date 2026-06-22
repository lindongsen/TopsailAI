#!/usr/bin/env python3
"""Mock agent command-line adaptor for ACS integration tests.

ACS invokes this script via the agent interface cmd_chat / cmd_check_health /
cmd_check_status fields. The script reads the runtime environment variables
injected by ACS and prints a simple response to stdout. Stdout is captured by
ACS and stored as the agent's response message.

Subcommands:
  health  -> print "healthy" and exit 0
  status  -> print "idle" and exit 0
  chat    -> read ACS_* env vars, optionally sleep, print response, exit 0

Optional env vars used for test control:
  MOCK_AGENT_SLEEP          -> seconds to sleep before responding (default 0.5)
  MOCK_AGENT_RECORD_PATH    -> append a JSON record of each chat invocation
  MOCK_AGENT_RESPONSE_PREFIX -> prefix for the chat response text
"""

import json
import os
import sys
import time
import uuid


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_invocation(record_dir: str) -> None:
    """Write a JSON file describing this chat invocation.

    Using one file per invocation avoids races when the test harness clears
    the record directory between tests.
    """
    record = {
        "invocation_id": uuid.uuid4().hex[:12],
        "timestamp_ms": _now_ms(),
        "pid": os.getpid(),
        "agent_id": os.environ.get("ACS_AGENT_ID", ""),
        "agent_name": os.environ.get("ACS_AGENT_NAME", ""),
        "agent_type": os.environ.get("ACS_AGENT_TYPE", ""),
        "group_id": os.environ.get("ACS_GROUP_ID", ""),
        "group_name": os.environ.get("ACS_GROUP_NAME", ""),
        "message_id": os.environ.get("ACS_MESSAGE_ID", ""),
        "sender_id": os.environ.get("ACS_SENDER_ID", ""),
        "sender_name": os.environ.get("ACS_SENDER_NAME", ""),
        "mode": os.environ.get("ACS_AGENT_MODE", ""),
        "trigger_type": os.environ.get("ACS_MESSAGE_TRIGGER_TYPE", ""),
        "timeout": os.environ.get("ACS_AGENT_TIMEOUT", ""),
    }
    try:
        os.makedirs(record_dir, exist_ok=True)
        file_path = os.path.join(record_dir, f"{uuid.uuid4().hex}.jsonl")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as exc:
        print(f"[mock-agent] failed to write record: {exc}", file=sys.stderr)


def do_health() -> int:
    print("healthy")
    return 0


def do_status() -> int:
    print("idle")
    return 0


def do_chat() -> int:
    sleep_seconds = float(os.environ.get("MOCK_AGENT_SLEEP", "0.5"))
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    record_dir = os.environ.get("MOCK_AGENT_RECORD_PATH")
    if record_dir:
        _record_invocation(record_dir)

    agent_id = os.environ.get("ACS_AGENT_ID", "unknown")
    agent_name = os.environ.get("ACS_AGENT_NAME", "unknown")
    message_id = os.environ.get("ACS_MESSAGE_ID", "unknown")
    mode = os.environ.get("ACS_AGENT_MODE", "unknown")
    trigger_type = os.environ.get("ACS_MESSAGE_TRIGGER_TYPE", "unknown")
    prefix = os.environ.get("MOCK_AGENT_RESPONSE_PREFIX", "Mock response")

    response = (
        f"{prefix} from {agent_name}({agent_id}) for message {message_id} "
        f"[mode={mode}, trigger={trigger_type}]"
    )
    print(response)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: mock_agent_cmd.py <health|status|chat>", file=sys.stderr)
        return 1

    mode = sys.argv[1].lower()
    if mode == "health":
        return do_health()
    if mode == "status":
        return do_status()
    if mode == "chat":
        return do_chat()

    print(f"[mock-agent] unknown mode: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
