#!/usr/bin/env python3
"""Send chat message to agent via topsailai_send_message or topsailai_llm_chat."""

import os
import subprocess
import sys


def build_api_env(env: dict) -> dict:
    """Map ACS_AGENT_API_* to TOPSAILAI_AGENT_DAEMON_* variables."""
    api_base = env.get("ACS_AGENT_API_BASE")
    if api_base:
        env["TOPSAILAI_AGENT_DAEMON_API_BASE"] = api_base

    api_key = env.get("ACS_AGENT_API_KEY")
    if api_key:
        env["TOPSAILAI_AGENT_DAEMON_API_KEY"] = api_key

    api_auth = env.get("ACS_AGENT_API_AUTH")
    if api_auth:
        env["TOPSAILAI_AGENT_DAEMON_AUTH_STYLE"] = api_auth

    timeout = env.get("ACS_AGENT_TIMEOUT")
    if timeout:
        env["MAX_WAIT_TIME"] = timeout

    return env


def run_command(cmd: list, env: dict):
    """Run a command and pass through stdout, stderr, and exit code."""
    result = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)


def main():
    env = os.environ.copy()
    session_id = env.get("ACS_GROUP_ID", "")
    agent_mode = env.get("ACS_AGENT_MODE", "")
    agent_type = env.get("ACS_AGENT_TYPE", "")
    agent_message = env.get("ACS_AGENT_MESSAGE", "")
    group_context = env.get("ACS_GROUP_CONTEXT", "")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    check_status_script = os.path.join(script_dir, "topsailai_agent_cmd_check_status.py")

    # If ACS_GROUP_CONTEXT exists and is non-empty, try to initialize session
    if group_context:
        status_result = subprocess.run(
            [sys.executable, check_status_script],
            env=env.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if status_result.returncode != 0 and b"Session not found" in status_result.stdout:
            init_env = build_api_env(env.copy())
            init_env["TOPSAILAI_MESSAGE_ROLE"] = "assistant"
            init_env["TOPSAILAI_MESSAGE"] = group_context
            init_env["TOPSAILAI_SESSION_ID"] = session_id
            subprocess.run(
                ["topsailai_send_message"],
                env=init_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    # Determine how to send the actual message
    if agent_mode == "chat" and agent_type == "manager-agent":
        # Use topsailai_llm_chat for manager-agent in chat mode
        llm_env = env.copy()
        llm_env["SESSION_ID"] = session_id
        agent_prompt = env.get("ACS_AGENT_PROMPT", "")
        if agent_prompt:
            llm_env["SYSTEM_PROMPT"] = agent_prompt
        llm_env["TOPSAILAI_USER_MESSAGE"] = agent_message
        run_command(["topsailai_llm_chat"], llm_env)

    elif agent_mode == "chat" and agent_type != "manager-agent":
        # Append direct-answer instruction for non-manager agents in chat mode
        send_env = build_api_env(env.copy())
        send_env["TOPSAILAI_MESSAGE"] = (
            agent_message + "\n! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !"
        )
        send_env["TOPSAILAI_SESSION_ID"] = session_id
        run_command(["topsailai_send_message"], send_env)

    else:
        # Default agent mode
        send_env = build_api_env(env.copy())
        send_env["TOPSAILAI_MESSAGE"] = agent_message
        send_env["TOPSAILAI_SESSION_ID"] = session_id
        run_command(["topsailai_send_message"], send_env)


if __name__ == "__main__":
    main()
