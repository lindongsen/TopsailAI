"""Real subprocess scenarios for storage-metadata replay coverage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server


_CHILD = r'''
import copy
import json
import os
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from topsailai.context import ctx_manager
if os.environ.get("BDD_PREFIX") == "1":
    import topsailai.workspace.context.agent as _agent_module
    _source = Path(os.environ["BDD_PREFIX_AGENT_SOURCE"]).read_text(encoding="utf-8")
    exec(compile(_source, "<pre-fix-agent>", "exec"), _agent_module.__dict__)
from topsailai.tools.base import common as tool_registry
from topsailai.workspace import agent_shell, input_tool
from topsailai.workspace.plugin_instruction.base import cache

revision = 0
original_add = ctx_manager.add_session_message
TOOL_NAME = "metadata_safe_tool"
TOOL_CALL_ID = "call_metadata_safe"
TOOL_ARGUMENT = "BDD_METADATA_ARGUMENT"
TOOL_RESULT = "BDD_METADATA_RESULT"
tool_count = 0

def metadata_safe_tool(value: str = "") -> str:
    global tool_count
    if value != TOOL_ARGUMENT:
        raise ValueError("unexpected metadata tool argument")
    tool_count += 1
    return TOOL_RESULT

if os.environ.get("BDD_NATIVE") == "1":
    tool_registry.add_tool(TOOL_NAME, metadata_safe_tool)
    tool_registry.TOOLS_INFO[TOOL_NAME] = {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Return a fixed harmless result.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }

def decorated_add(session_id, message):
    global revision
    revision += 1
    stored = copy.deepcopy(message)
    if stored.get("role") != "system":
        stored["storage_revision"] = revision
        stored["storage_metadata"] = {"nested": [revision, {"kind": "future"}]}
    return original_add(session_id, stored)


ctx_manager.add_session_message = decorated_add


def _jsonable(value):
    """Convert provider model objects and nested containers into JSON values."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _jsonable(method())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return value


def _request_count():
    with urllib.request.urlopen(
        f"http://127.0.0.1:{os.environ['BDD_MOCK_PORT']}/debug/state"
    ) as response:
        return len(json.load(response)["request_bodies"])


def capture(chat, command):
    before = _jsonable(copy.deepcopy(chat.ai_agent.messages))
    session_before = _jsonable(copy.deepcopy(
        ctx_manager.get_messages_by_session(os.environ["SESSION_ID"])
    ))
    request_count_before = _request_count()
    output = StringIO()
    with redirect_stdout(output):
        consumed = input_tool.hook_message(command, chat.hook_instruction)
    after = _jsonable(copy.deepcopy(chat.ai_agent.messages))
    session_after = _jsonable(copy.deepcopy(
        ctx_manager.get_messages_by_session(os.environ["SESSION_ID"])
    ))
    request_count_after = _request_count()
    return {"command": command, "consumed": consumed,
            "cache_identity": cache.get_ai_agent() is chat.ai_agent,
            "stdout": output.getvalue(), "messages_before": before,
            "messages_after": after, "session_before": session_before,
            "session_after": session_after, "request_count_before": request_count_before,
            "request_count_after": request_count_after}

_real_add_runtime_messages = _agent_module.ContextRuntimeAIAgent.add_runtime_messages if "_agent_module" in globals() else __import__("topsailai.workspace.context.agent", fromlist=["ContextRuntimeAIAgent"]).ContextRuntimeAIAgent.add_runtime_messages

def _observed_add_runtime_messages(self):
    entry = copy.deepcopy(self.messages)
    report["merge_entries"].append(_jsonable(entry))
    if len(report["merge_entries"]) == 2:
        report["merge_entry"] = _jsonable(entry)
    return _real_add_runtime_messages(self)

_agent_class = __import__("topsailai.workspace.context.agent", fromlist=["ContextRuntimeAIAgent"]).ContextRuntimeAIAgent
_agent_class.add_runtime_messages = _observed_add_runtime_messages

chat = agent_shell.get_agent_chat(
    agent_type="react", agent_role="manager", session_id=os.environ["SESSION_ID"],
    message="BDD_METADATA_TURN_ONE",
    tool_map={TOOL_NAME: metadata_safe_tool} if os.environ.get("BDD_NATIVE") == "1" else None,
    need_input_message=False,
    need_print_session=False, need_set_agent_name_to_thread_local=False,
    need_project_workspace_lock=False,
)
report = {"snapshots": [], "raw_loaded": [], "merge_entries": [], "runtime_before_reload": None, "merge_entry": None, "instruction_request_counts": []}


def before(_agent):
    turn = len([item for item in report["snapshots"] if item["checkpoint"] == "A_pre"]) + 1
    report["snapshots"].append({"checkpoint": "A_pre", "turn": turn,
                                "items": [capture(chat, "/agent.messages")]})


def after(_agent):
    turn = len(report["raw_loaded"]) + 1
    report["snapshots"].append({"checkpoint": "A_post", "turn": turn,
                                "items": [capture(chat, "/agent.messages"), capture(chat, "/ctx.history")]})
    raw = ctx_manager.get_messages_by_session(os.environ["SESSION_ID"])
    report["raw_loaded"].append(_jsonable(copy.deepcopy(raw)))
    if turn == 1:
        report["runtime_before_reload"] = _jsonable(copy.deepcopy(chat.ai_agent.messages))
        restored = copy.deepcopy(raw)
        chat.ctx_runtime_data.set_messages(restored)
    report["snapshots"].append({"checkpoint": "H_post", "turn": turn,
                                "items": [capture(chat, "/ctx.history")]})

def write_second_message(pipe_path):
    """Provide the second real user turn through the public input pipe."""
    import time
    deadline = time.monotonic() + 60
    while not os.path.exists(pipe_path) and time.monotonic() < deadline:
        time.sleep(0.01)
    if not os.path.exists(pipe_path):
        raise AssertionError("input pipe was not created")
    with open(pipe_path, "w", encoding="utf-8") as pipe:
        pipe.write("BDD_METADATA_TURN_TWO_TOKEN\\n")
        pipe.flush()


chat.ai_agent.hooks_after_new_session.append(before)
chat.hooks_post_succ_run.append(after)
writer = None
try:
    from topsailai.workspace import input_tool as _input_tool
    writer = __import__("threading").Thread(
        target=write_second_message,
        args=(_input_tool._build_pipe_path(os.environ["SESSION_ID"]),), daemon=True,
    )
    writer.start()
    chat.run(message=chat.first_message, times=2, need_interactive=False,
             only_save_final=True if os.environ.get("BDD_NATIVE") == "1" else False)
    report["session_messages"] = _jsonable(copy.deepcopy(ctx_manager.get_messages_by_session(os.environ["SESSION_ID"])))
    report["tool_count"] = tool_count
    report["tool_call_id"] = TOOL_CALL_ID
    report["tool_name"] = TOOL_NAME
    report["tool_argument"] = TOOL_ARGUMENT
    report["tool_result"] = "topsailai.observation\n" + TOOL_RESULT
    Path(os.environ["REPORT"]).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
finally:
    if writer is not None:
        writer.join(timeout=5)
    chat.ai_agent.close()


'''
class MetadataScenario:
    """Own one loopback provider and one isolated child process."""

    def __init__(self, tmp_path: Path, monkeypatch: Any, native: bool = False):
        """Create the scenario-local database, server, and environment."""
        self.tmp_path = tmp_path
        self.native = native
        self.report_path = tmp_path / ("native-report.json" if native else "report.json")
        self.database = tmp_path / ("native.sqlite" if native else "ordinary.sqlite")
        final = json.dumps([{"step_name": "final_answer", "raw_text": "BDD_METADATA_ANSWER"}])
        if native:
            call = {
                "id": "call_metadata_safe",
                "type": "function",
                "function": {
                    "name": "metadata_safe_tool",
                    "arguments": json.dumps({"value": "BDD_METADATA_ARGUMENT"}),
                },
            }
            config = MockServerConfig(
                port=0,
                reply=final,
                request_body_capacity=16,
                tool_call_responses=((call,), None, None),
                tool_call_response_content=json.dumps([{"step_name": "action", "raw_text": "BDD_METADATA_ACTION"}]),
            )
        else:
            config = MockServerConfig(port=0, reply=final, stream_chunks=(final,), request_body_capacity=16)
        self.server = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.session_id = "bdd-history-metadata"
        values = {
            "TOPSAILAI_PROJECT_WORKSPACE": str(tmp_path),
            "TOPSAILAI_HOME": str(tmp_path / "home"),
            "CONTEXT_HISTORY_MANAGERS": f"sql.ChatHistorySQLAlchemy conn=sqlite:///{self.database}",
            "OPENAI_API_BASE": f"http://127.0.0.1:{self.server.server_port}/v1",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
            "OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "metadata-model",
            "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0", "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "0", "TOPSAILAI_TERMINAL_TITLE_ENABLED": "0",
            "TOPSAILAI_INPUT_PIPE_ENABLED": "1", "TOPSAILAI_INPUT_PIPE_TIMEOUT": "10", "TOPSAILAI_USE_TOOL_CALLS": "1" if native else "0",
            "TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS": "1",
            "TOPSAILAI_EVENTS_ENABLED": "0", "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_DISABLED_SKILLS": "*", "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "0",
            "SYSTEM_PROMPT": "BDD_METADATA_SYSTEM", "TOPSAILAI_CONTEXT_USER_MESSAGE": "",
            "LLM_RESPONSE_STREAM": "0" if native else "1",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    def run(self, pre_fix=False):
        """Execute the real AgentChat child and load its report."""
        env = os.environ.copy()
        if pre_fix:
            source_path = self.tmp_path / "pre_fix_agent.py"
            source = subprocess.check_output(["git", "-C", "/TopsailAI/src/topsailai", "show", "HEAD:src/topsailai/workspace/context/agent.py"], text=True)
            source_path.write_text(source, encoding="utf-8")
            env.update({"BDD_PREFIX": "1", "BDD_PREFIX_AGENT_SOURCE": str(source_path)})
        env.update({"SESSION_ID": self.session_id, "REPORT": str(self.report_path), "REQUEST_COUNT": "3" if self.native else "2", "BDD_NATIVE": "1" if self.native else "0", "BDD_MOCK_PORT": str(self.server.server_port)})
        try:
            result = subprocess.run([sys.executable, "-c", _CHILD], cwd=str(Path(__file__).parents[2]), env=env, text=True, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise AssertionError(f"child timeout state={self.state()!r} stdout={error.stdout!r} stderr={error.stderr!r}") from error
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)
        return json.loads(self.report_path.read_text(encoding="utf-8"))

    def state(self):
        """Return real loopback provider request state."""
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}/debug/state") as response:
            return json.load(response)

    def close(self):
        """Stop the exact scenario-owned provider thread."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AssertionError("metadata mock server did not stop")
