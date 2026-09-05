"""Compare AgentChat and summary-processor LLMChat formatting hashes."""

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


SUMMARY_CASES = (
    {
        "name": "llm_chat",
        "processor": "llm_chat",
        "expected_effective_processor": "llm_chat",
    },
    {
        "name": "agent_llm_model",
        "processor": "agent_llm_model",
        "expected_effective_processor": "agent_llm_model",
    },
    {
        "name": "agent_llm_model_unavailable_fallback",
        "processor": "agent_llm_model",
        "agent_model_available": False,
        "expected_effective_processor": "llm_chat",
    },
    {
        "name": "agent_llm_model_pending_native_fallback",
        "processor": "agent_llm_model",
        "pending_native_responses": True,
        "expected_effective_processor": "llm_chat",
    },
    {
        "name": "invalid_processor_fallback",
        "processor": "unsupported",
        "expected_effective_processor": "llm_chat",
    },
)


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


def _add_test_messages(agent_chat) -> None:
    """Populate Agent2LLM history through its public message helpers."""
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


def _run_summary_case(agent_chat, case: dict) -> bool:
    """Resolve one real summary processor path and print hash evidence."""
    runtime = agent_chat.ctx_runtime_data
    agent = agent_chat.ai_agent
    original_model = agent.llm_model
    summary_chat = None

    try:
        if not case.get("agent_model_available", True):
            agent.llm_model = None
        elif case.get("pending_native_responses"):
            original_model._pending_native_tool_call_responses = [object()]
        else:
            original_model._pending_native_tool_call_responses = []

        with patch.dict(
            os.environ,
            {"TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR": case["processor"]},
            clear=False,
        ):
            summary_chat = runtime._build_summary_chat(
                message="> SUMMARIZE MESSAGES",
                system_prompt="",
            )

        summary_chat.prompt_ctl.messages = deepcopy(agent.messages)
        model_reused = summary_chat.llm_model is original_model
        effective_processor = "agent_llm_model" if model_reused else "llm_chat"
        expected_processor = case["expected_effective_processor"]

        agent_formatted = _formatted_messages(agent.messages)
        summary_formatted = _formatted_messages(summary_chat.prompt_ctl.messages)
        agent_hash = _messages_hash(agent_formatted)
        summary_hash = _messages_hash(summary_formatted)
        hashes_match = agent_hash == summary_hash
        processor_match = effective_processor == expected_processor
        case_passed = hashes_match and processor_match

        print(f"case: {case['name']}")
        print(f"configured_processor: {case['processor']}")
        print(f"effective_processor: {effective_processor}")
        print(f"expected_effective_processor: {expected_processor}")
        print(f"model_reused: {str(model_reused).lower()}")
        print(f"agent_message_count: {len(agent.messages)}")
        print(f"llm_message_count: {len(summary_chat.prompt_ctl.messages)}")
        print(f"agent_formatted_sha256: {agent_hash}")
        print(f"llm_formatted_sha256: {summary_hash}")
        print(f"hashes_match: {str(hashes_match).lower()}")
        print(f"processor_match: {str(processor_match).lower()}")
        print(f"case_passed: {str(case_passed).lower()}")

        if not hashes_match:
            print("agent_formatted_messages:")
            print(json.dumps(agent_formatted, ensure_ascii=False, indent=2, default=str))
            print("llm_formatted_messages:")
            print(json.dumps(summary_formatted, ensure_ascii=False, indent=2, default=str))
        print("---")
        return case_passed
    finally:
        agent.llm_model = original_model
        original_model._pending_native_tool_call_responses = []
        if summary_chat is not None:
            summary_chat.close()


def main() -> int:
    """Build AgentChat, exercise summary processors, and compare messages."""
    agent_chat = None
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
            _add_test_messages(agent_chat)
            results = [
                _run_summary_case(agent_chat, case)
                for case in SUMMARY_CASES
            ]

        print(quiet_output.getvalue(), end="")
        all_cases_passed = all(results)
        print(f"all_cases_passed: {str(all_cases_passed).lower()}")
        return 0 if all_cases_passed else 1
    finally:
        if agent_chat is not None:
            agent_chat.ai_agent.close()


if __name__ == "__main__":
    raise SystemExit(main())
