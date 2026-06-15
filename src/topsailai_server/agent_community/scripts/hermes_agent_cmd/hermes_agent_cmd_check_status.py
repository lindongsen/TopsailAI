#!/usr/bin/env python3
"""Check status of Hermes agent session via cli/hermes_status.

Maps ACS_* environment variables to HERMES_* variables and invokes
the native Hermes status check CLI. Parses JSON response and prints
only the plain status string to stdout.

Exit codes:
    0 - Status check executed successfully (stdout contains status string)
    1 - Missing required env var, cli not found, or underlying script crashed
"""

import json
import os
import subprocess
import sys


def find_cli_executable(name: str) -> str:
    """Find the cli executable for the given name.

    Looks for compiled binary first (no extension), then .py script.
    e.g., name='hermes_status' -> tries 'cli/hermes_status', then 'cli/hermes_status.py'
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(script_dir, "cli")

    # Try compiled binary first (no extension)
    binary_path = os.path.join(cli_dir, name)
    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

    # Fallback to Python script
    py_path = os.path.join(cli_dir, f"{name}.py")
    if os.path.isfile(py_path):
        return py_path

    raise FileNotFoundError(f"Neither {name} nor {name}.py found in {cli_dir}")


def main():
    env = os.environ.copy()

    session_id = env.get("ACS_GROUP_ID", "").strip()
    if not session_id:
        print("ERROR: ACS_GROUP_ID is required", file=sys.stderr)
        sys.exit(1)

    # Map ACS_* to HERMES_*
    if env.get("ACS_AGENT_API_BASE"):
        env["HERMES_API_BASE"] = env["ACS_AGENT_API_BASE"]
    if env.get("ACS_AGENT_API_KEY"):
        env["HERMES_API_KEY"] = env["ACS_AGENT_API_KEY"]
    env["HERMES_SESSION_ID"] = session_id

    try:
        cmd_path = find_cli_executable("hermes_status")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [cmd_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # If the underlying script failed, propagate failure
    if result.returncode != 0:
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        sys.exit(1)

    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()

    if not stdout_text:
        print("ERROR: Empty response from status check", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON response: {e}", file=sys.stderr)
        sys.exit(1)

    status = data.get("status")
    if status is None:
        print("ERROR: Missing 'status' field in response", file=sys.stderr)
        sys.exit(1)

    # Print only the plain status string to stdout
    print(status)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
