"""Fresh-child real AgentChat driver for native tool-call integrity BDD coverage."""
from __future__ import annotations

import json
import os
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from topsailai.context import ctx_manager
from topsailai.tools.base import common as tool_registry
from topsailai.workspace import agent_shell, input_tool
from topsailai.workspace.plugin_instruction.base import cache

TASK = "BDD_NATIVE_TASK_TOKEN"
CALL_ID = "call_bdd_integrity_native"
ARGUMENT = "BDD_NATIVE_ARGUMENT_TOKEN"
RESULT = "BDD_NATIVE_RESULT_TOKEN"
ANSWER = "BDD_NATIVE_ANSWER_TOKEN"
TOOL_NAME = "safe_native_tool"


def safe_native_tool(value: str = "") -> str:
    """Return the fixed harmless native-tool result."""
    if value != ARGUMENT:
        raise ValueError("unexpected native argument")
    state = Path(os.environ["BDD_NATIVE_TOOL_STATE"])
    data = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {"count": 0, "arguments": []}
    data["count"] += 1
    data["arguments"].append({"value": value})
    state.write_text(json.dumps(data), encoding="utf-8")
    return RESULT


def capture(chat, command: str) -> dict:
    """Dispatch one real instruction and capture its output."""
    if cache.get_ai_agent() is not chat.ai_agent:
        raise AssertionError("instruction cache mismatch")
    output = StringIO()
    with redirect_stdout(output):
        consumed = input_tool.hook_message(command, chat.hook_instruction)
    return {"command": command, "consumed": consumed, "cache_identity": cache.get_ai_agent() is chat.ai_agent, "stdout": output.getvalue()}


def state_count() -> int:
    """Read accepted request count from the real mock server."""
    with urllib.request.urlopen(os.environ["BDD_SERVER_STATE_URL"], timeout=3) as response:
        return int(json.load(response)["total_requests"])


def detach(value):
    """Convert SDK model objects into owned JSON-compatible structures."""
    if hasattr(value, "model_dump"):
        return detach(value.model_dump())
    if isinstance(value, dict):
        return {key: detach(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [detach(item) for item in value]
    return value


def main() -> None:
    """Run one real native tool loop and atomically export observations."""
    tool_registry.add_tool(TOOL_NAME, safe_native_tool)
    tool_registry.TOOLS_INFO[TOOL_NAME] = {"type": "function", "function": {"name": TOOL_NAME, "description": "Return the fixed native result.", "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}}}
    chat = agent_shell.get_agent_chat(
        agent_type="react", agent_role="manager", session_id=os.environ["BDD_SESSION_ID"],
        message=TASK, tool_map={TOOL_NAME: safe_native_tool}, need_input_message=False,
        need_print_session=False, need_set_agent_name_to_thread_local=False,
        need_project_workspace_lock=False,
    )
    snapshots = []
    before_runtime = None
    before_session = None
    before_request_count = None
    def before(_agent):
        snapshots.append({"checkpoint": "A_pre", "items": [capture(chat, "/agent.messages")]})
    def after(_agent):
        nonlocal before_runtime, before_session, before_request_count
        before_runtime = detach(chat.ai_agent.messages)
        before_session = detach(ctx_manager.get_messages_by_session(os.environ["BDD_SESSION_ID"]))
        before_request_count = state_count()
        snapshots.append({"checkpoint": "A_post", "items": [capture(chat, "/agent.messages")]})
        snapshots.append({"checkpoint": "H_post", "items": [capture(chat, "/ctx.history")]})
    chat.ai_agent.hooks_after_new_session.append(before)
    chat.hooks_post_succ_run.append(after)
    try:
        chat.run(message=chat.first_message, times=1, need_interactive=False, only_save_final=True)
        snapshots.append({"checkpoint": "purity_before", "items": [capture(chat, "/agent.messages"), capture(chat, "/ctx.history")]})
        snapshots.append({"checkpoint": "purity_after", "items": [capture(chat, "/agent.messages"), capture(chat, "/ctx.history")]})
        persisted = ctx_manager.get_messages_by_session(os.environ["BDD_SESSION_ID"])
        after_runtime = detach(chat.ai_agent.messages)
        after_session = detach(ctx_manager.get_messages_by_session(os.environ["BDD_SESSION_ID"]))
        after_request_count = state_count()
        report = {"snapshots": snapshots, "runtime": after_runtime, "session_messages": detach(persisted), "before_runtime": before_runtime, "after_runtime": after_runtime, "before_session": before_session, "after_session": after_session, "before_request_count": before_request_count, "after_request_count": after_request_count, "request_count": after_request_count, "tool_state": json.loads(Path(os.environ["BDD_NATIVE_TOOL_STATE"]).read_text(encoding="utf-8")), "handler_counts": {command: len(chat.hook_instruction.hook_map.get(command, [])) for command in ("/agent.messages", "/ctx.history")}, "user_open_count": int(Path(os.environ["BDD_USER_OPEN_COUNT"]).read_text(encoding="utf-8"))}
        destination = Path(os.environ["BDD_INTEGRITY_REPORT"])
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
    finally:
        chat.ai_agent.close()


if __name__ == "__main__":
    main()
