#!/usr/bin/env python3
"""Send chat message to Hermes agent via cli/hermes_chat.

Maps ACS_* environment variables to HERMES_* variables and invokes
the native Hermes chat CLI. Handles session initialization with
group context, mode-based message modification, and passes through
all output from the underlying CLI.

Exit codes:
    0 - Message sent and response received successfully
    1 - Missing required env var, cli not found, or underlying script failed
"""

import os
import subprocess
import sys


def find_cli_executable(name: str) -> str:
    """Find the cli executable for the given name.

    Looks for compiled binary first (no extension), then .py script.
    e.g., name='hermes_chat' -> tries 'cli/hermes_chat', then 'cli/hermes_chat.py'
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


def run_command(cmd: list, env: dict):
    """Run a command and pass through stdout, stderr, and exit code."""
    result = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)


def main():
    env = os.environ.copy()

    session_id = env.get("ACS_GROUP_ID", "").strip()
    if not session_id:
        print("ERROR: ACS_GROUP_ID is required", file=sys.stderr)
        sys.exit(1)

    agent_message = env.get("ACS_AGENT_MESSAGE", "").strip()
    if not agent_message:
        print("ERROR: ACS_AGENT_MESSAGE is required", file=sys.stderr)
        sys.exit(1)

    agent_mode = env.get("ACS_AGENT_MODE", "").strip()
    agent_type = env.get("ACS_AGENT_TYPE", "").strip()
    group_context = env.get("ACS_GROUP_CONTEXT", "").strip()
    agent_prompt = env.get("ACS_AGENT_PROMPT", "").strip()

    # Map ACS_* to HERMES_*
    if env.get("ACS_AGENT_API_BASE"):
        env["HERMES_API_BASE"] = env["ACS_AGENT_API_BASE"]
    if env.get("ACS_AGENT_API_KEY"):
        env["HERMES_API_KEY"] = env["ACS_AGENT_API_KEY"]
    if env.get("ACS_AGENT_TIMEOUT"):
        env["HERMES_AGENT_TIMEOUT"] = env["ACS_AGENT_TIMEOUT"]

    env["HERMES_SESSION_ID"] = session_id
    env["HERMES_USER_MESSAGE"] = agent_message
    if agent_prompt:
        env["HERMES_SYSTEM_PROMPT"] = agent_prompt

    # If ACS_GROUP_CONTEXT is non-empty, check if session exists
    if group_context:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        check_status_script = os.path.join(script_dir, "hermes_agent_cmd_check_status.py")

        status_result = subprocess.run(
            [sys.executable, check_status_script],
            env=os.environ.copy(),  # Use original env for the check script
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        status_stdout = status_result.stdout.decode("utf-8", errors="replace").strip()

        if status_result.returncode == 0 and status_stdout == "not_found":
            # Session does not exist, initialize with group_context as user message
            try:
                init_cmd_path = find_cli_executable("hermes_chat")
            except FileNotFoundError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                sys.exit(1)

            init_env = env.copy()
            init_env["HERMES_USER_MESSAGE"] = group_context
            # Clear system prompt for init message
            init_env.pop("HERMES_SYSTEM_PROMPT", None)

            init_result = subprocess.run(
                [init_cmd_path],
                env=init_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if init_result.returncode != 0:
                print(
                    "[WARN] Failed to initialize session with group context",
                    file=sys.stderr,
                )
                sys.stderr.buffer.write(init_result.stderr)
            else:
                print(
                    f"[INFO] Session initialized with group context: {session_id}",
                    file=sys.stderr,
                )

    # Handle mode-based message modification
    if agent_mode == "chat" and agent_type != "manager-agent":
        env["HERMES_USER_MESSAGE"] = (
            agent_message
            + "\n! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !"
        )

    try:
        cmd_path = find_cli_executable("hermes_chat")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    run_command([cmd_path], env)


if __name__ == "__main__":
    main()
