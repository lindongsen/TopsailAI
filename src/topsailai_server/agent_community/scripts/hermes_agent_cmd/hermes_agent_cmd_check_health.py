#!/usr/bin/env python3
"""Check health of Hermes agent via cli/hermes_health.

Maps ACS_* environment variables to HERMES_* variables and invokes
the native Hermes health check CLI. Parses JSON response and validates
status == "ok".

Exit codes:
    0 - Agent is healthy (status == "ok")
    1 - Agent is unhealthy, network error, or invalid response
"""

import json
import os
import subprocess
import sys


def find_cli_executable(name: str) -> str:
    """Find the cli executable for the given name.

    Looks for compiled binary first (no extension), then .py script.
    e.g., name='hermes_health' -> tries 'cli/hermes_health', then 'cli/hermes_health.sh'
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(script_dir, "cli")

    # Try compiled binary first (no extension)
    binary_path = os.path.join(cli_dir, name)
    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

    # Fallback to shell script
    sh_path = os.path.join(cli_dir, f"{name}.sh")
    if os.path.isfile(sh_path):
        return sh_path

    raise FileNotFoundError(f"Neither {name} nor {name}.sh found in {cli_dir}")


def main():
    env = os.environ.copy()

    # Map ACS_* to HERMES_*
    if env.get("ACS_AGENT_API_BASE"):
        env["HERMES_API_BASE"] = env["ACS_AGENT_API_BASE"]
    if env.get("ACS_AGENT_API_KEY"):
        env["HERMES_API_KEY"] = env["ACS_AGENT_API_KEY"]

    try:
        cmd_path = find_cli_executable("hermes_health")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [cmd_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()

    # If the underlying script failed, propagate failure
    if result.returncode != 0:
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        sys.exit(1)

    # Parse JSON and validate status == "ok"
    if not stdout_text:
        print("ERROR: Empty response from health check", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON response: {e}", file=sys.stderr)
        sys.exit(1)

    status = data.get("status")
    if status != "ok":
        print(f"ERROR: Health check failed, status='{status}'", file=sys.stderr)
        sys.stdout.buffer.write(result.stdout)
        sys.exit(1)

    # Healthy: print raw response and exit 0
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
