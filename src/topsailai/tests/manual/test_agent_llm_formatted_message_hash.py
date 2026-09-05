"""Compare AgentChat and summarize-style LLMChat message formatting hashes."""

import contextlib
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SRC_DIR))

from topsailai.ai_base.llm_control.message import format_messages
from topsailai.workspace.agent_shell import get_agent_chat
from topsailai.workspace.llm_shell import get_llm_chat


def _formatted_messages(messages: list[dict]) -> list[dict]:
    """Return a copy immediately after production message formatting."""
    return format_messages(
        deepcopy(messages),
        key_name="step_name",
        value_name="raw_text",
    )


def _messages_hash(messages: list[dict]) -> str:
    """Return a deterministic SHA-256 hash for a formatted message list."""
    payload = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    """Build both chat paths, compare formatted messages, and print evidence."""
    agent_chat = None
    llm_chat = None
    quiet_output = io.StringIO()
    test_environment = {
        "DEBUG": "0",
        "LLM_RESPONSE_STREAM": "0",
        "OPENAI_API_BASE": "http://127.0.0.1:1/v1",
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "formatted-message-hash-test",
        "TOPSAILAI_INTERACTIVE_MODE": "0",
    }

    try:
        with (
            patch.dict(os.environ, test_environment, clear=False),
            patch("topsailai.workspace.agent_shell.record_project_history"),
            patch("topsailai.workspace.agent_shell.create_session_meta"),
            patch("topsailai.workspace.agent_shell.cleanup_session_meta_files"),
            patch("topsailai.workspace.llm_shell.record_project_history"),
            contextlib.redirect_stdout(quiet_output),
        ):
            agent_chat = get_agent_chat(
                message="formatted message hash verification",
                session_id="",
                need_input_message=False,
                need_print_session=False,
                need_project_workspace_lock=False,
            )
            agent_chat.ai_agent.add_user_message(
                {
                    "step_name": "task",
                    "raw_text": "Compare AgentChat and LLMChat formatting.",
                },
                need_print=False,
            )
            agent_chat.ai_agent.add_assistant_message(
                {
                    "step_name": "thought",
                    "raw_text": "Prepare deterministic message content.",
                }
            )
            agent_chat.ai_agent.add_user_message(
                {
                    "step_name": "observation",
                    "raw_text": "The same messages will be copied into LLMChat.",
                },
                need_print=False,
            )

            llm_chat = get_llm_chat(
                message="> SUMMARIZE MESSAGES",
                session_id="",
                system_prompt="You are a helpful assistant.",
                need_stdout=False,
                need_input_message=False,
                need_print_session=False,
                need_print_message=False,
            )
            llm_chat.prompt_ctl.messages = agent_chat.ai_agent.messages[:]

            agent_formatted = _formatted_messages(
                agent_chat.ai_agent.messages,
            )
            llm_formatted = _formatted_messages(
                llm_chat.prompt_ctl.messages,
            )

        agent_hash = _messages_hash(agent_formatted)
        llm_hash = _messages_hash(llm_formatted)
        hashes_match = agent_hash == llm_hash

        print(f"agent_message_count: {len(agent_chat.ai_agent.messages)}")
        print(f"llm_message_count: {len(llm_chat.prompt_ctl.messages)}")
        print(f"agent_formatted_sha256: {agent_hash}")
        print(f"llm_formatted_sha256: {llm_hash}")
        print(f"hashes_match: {str(hashes_match).lower()}")

        if not hashes_match:
            print("agent_formatted_messages:")
            print(json.dumps(agent_formatted, ensure_ascii=False, indent=2, default=str))
            print("llm_formatted_messages:")
            print(json.dumps(llm_formatted, ensure_ascii=False, indent=2, default=str))
            return 1
        return 0
    finally:
        if llm_chat is not None:
            llm_chat.close()
        if agent_chat is not None:
            agent_chat.ai_agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
