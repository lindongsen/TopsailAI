#!/usr/bin/env python3
"""Check status of the agent session via topsailai_send_message."""

import os
import subprocess
import sys


def main():
    # Build environment overrides from ACS_* variables
    env = os.environ.copy()
    env.setdefault("DEBUG", "0")

    api_base = env.get("ACS_AGENT_API_BASE")
    if api_base:
        env["TOPSAILAI_AGENT_DAEMON_API_BASE"] = api_base

    api_key = env.get("ACS_AGENT_API_KEY")
    if api_key:
        env["TOPSAILAI_AGENT_DAEMON_API_KEY"] = api_key

    api_auth = env.get("ACS_AGENT_API_AUTH")
    if api_auth:
        env["TOPSAILAI_AGENT_DAEMON_AUTH_STYLE"] = api_auth

    session_id = env.get("ACS_GROUP_ID", "")
    env["TOPSAILAI_MESSAGE"] = "/status"
    env["TOPSAILAI_SESSION_ID"] = session_id

    result = subprocess.run(
        ["topsailai_send_message"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
