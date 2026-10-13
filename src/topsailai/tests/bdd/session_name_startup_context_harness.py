"""Subprocess BDD harness for startup-context isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from typing import Any
from tests.mock.llm_mock_server import MockServerConfig, create_server

USER_MARKER = "BDD_PLAN_USER_MD_MARKER"
EXPLICIT_MARKER = "BDD_PLAN_EXPLICIT_CONTEXT_MARKER"



_CHILD_SCRIPT = r'''
import json
import os
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from topsailai.context.agent_startup import AgentStartupState
from topsailai.context import ctx_manager
from topsailai.workspace import agent_shell, folder_constants, llm_shell

worker_threads = []
worker_results = []
original_thread = ctx_manager.threading.Thread
class TrackedThread(original_thread):
    def start(self):
        worker_threads.append(self)
        return super().start()

    def run(self):
        try:
            super().run()
        except BaseException as exc:
            worker_results.append((self, exc))
            raise
        else:
            worker_results.append((self, None))
ctx_manager.threading.Thread = TrackedThread
naming_chats = []
_original_get_llm_chat = llm_shell.get_llm_chat
def tracked_get_llm_chat(*args, **kwargs):
    chat = _original_get_llm_chat(*args, **kwargs)
    naming_chats.append(chat)
    return chat
llm_shell.get_llm_chat = tracked_get_llm_chat

folder_constants.TOPSAILAI_HOME = os.environ["BDD_HOME"]
opened_user_md = Path(os.environ["BDD_USER_OPEN_COUNT"])
_original_open = open


def tracked_open(file, *args, **kwargs):
    if str(file).endswith("USER.md"):
        current = int(opened_user_md.read_text(encoding="utf-8")) if opened_user_md.exists() else 0
        opened_user_md.write_text(str(current + 1), encoding="utf-8")
    return _original_open(file, *args, **kwargs)


import builtins
builtins.open = tracked_open

barrier = Path(os.environ["BDD_WAIT_ENTERED"])
started = Path(os.environ["BDD_STARTED"])
original_wait = AgentStartupState.wait
original_mark_started = AgentStartupState.mark_started

def wait(state, timeout=300.0):
    if os.environ.get("BDD_INTEGRITY_SCENARIO") == "1":
        return original_wait(state, timeout)
    barrier.write_text("entered", encoding="utf-8")
    result = original_wait(state, timeout)
    if result:
        Path(os.environ["BDD_WAIT_RELEASED"]).write_text("released", encoding="utf-8")
    return result


def mark_started(state):
    if os.environ.get("BDD_INTEGRITY_SCENARIO") == "1":
        return original_mark_started(state)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not barrier.exists():
        time.sleep(0.01)
    if not barrier.exists():
        raise AssertionError("naming worker did not enter startup wait")
    started.write_text("started", encoding="utf-8")
    return original_mark_started(state)

AgentStartupState.wait = wait
AgentStartupState.mark_started = mark_started


def wait_for_barrier():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not barrier.exists():
        time.sleep(0.01)
    if not barrier.exists():
        raise AssertionError("naming worker did not enter startup wait")


def capture_instruction(chat, command):
    """Dispatch one registered slash instruction and capture operator output."""
    from topsailai.workspace import input_tool
    from topsailai.workspace.plugin_instruction.base import cache

    if cache.get_ai_agent() is not chat.ai_agent:
        raise AssertionError("instruction cache does not reference the active agent")
    output = StringIO()
    with redirect_stdout(output):
        consumed = input_tool.hook_message(command, chat.hook_instruction)
    return {
        "command": command,
        "consumed": consumed,
        "stdout": output.getvalue(),
        "cache_identity": cache.get_ai_agent() is chat.ai_agent,
    }


def capture_group(chat):
    """Capture the two real instruction views without changing agent state."""
    return [capture_instruction(chat, command) for command in ("/agent.messages", "/ctx.history")]


def run_integrity_scenario():
    """Run one completed turn and export instruction and transport observations."""
    chat = agent_shell.get_agent_chat(
        agent_type="react",
        agent_role="manager",
        session_id=os.environ["BDD_SESSION_ID"],
        message="BDD_PLAN_TURN_ONE_TOKEN",
        need_input_message=False,
        need_print_session=False,
        need_set_agent_name_to_thread_local=False,
        need_project_workspace_lock=False,
    )
    snapshots = []
    pre_inspection_runtime = None
    pre_inspection_session = None

    def observe_after_new_session(_agent):
        """Capture the initialized runtime immediately before the first request."""
        snapshots.append({"checkpoint": "A_pre", "items": [capture_instruction(chat, "/agent.messages")]})

    try:
        chat.ai_agent.hooks_after_new_session.append(observe_after_new_session)
        chat.run(message=chat.first_message, times=1, need_interactive=False)
        pre_inspection_runtime = json.loads(json.dumps(chat.ai_agent.messages))
        pre_inspection_session = json.loads(json.dumps(chat.ctx_runtime_data.messages))
        before_runtime = json.loads(json.dumps(chat.ai_agent.messages))
        before_session = json.loads(json.dumps(chat.ctx_runtime_data.messages))
        snapshots.append({"checkpoint": "A_post", "items": capture_group(chat)})
        snapshots.append({"checkpoint": "H_post", "items": [capture_instruction(chat, "/ctx.history")]})
        snapshots.append({"checkpoint": "purity_before", "items": capture_group(chat)})
        snapshots.append({"checkpoint": "purity_after", "items": capture_group(chat)})
        report = {
            "snapshots": snapshots,
            "pre_inspection_runtime": pre_inspection_runtime,
            "pre_inspection_session": pre_inspection_session,
            "before_runtime": before_runtime,
            "before_session": before_session,
            "after_runtime": json.loads(json.dumps(chat.ai_agent.messages)),
            "after_session": json.loads(json.dumps(chat.ctx_runtime_data.messages)),
            "agent_message_count": len(chat.ai_agent.messages),
            "session_messages": list(chat.ctx_runtime_data.messages),
            "handler_counts": {
                command: len(chat.hook_instruction.hook_map.get(command, []))
                for command in ("/agent.messages", "/ctx.history")
            },
        }
        report_path = Path(os.environ["BDD_INTEGRITY_REPORT"])
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        temporary.replace(report_path)
    finally:
        chat.ai_agent.close()


def run_turn(message, agent_type):
    chat = agent_shell.get_agent_chat(
        agent_type=agent_type,
        agent_role="manager",
        session_id=os.environ["BDD_SESSION_ID"],
        message=message,
        need_input_message=False,
        need_print_session=False,
        need_set_agent_name_to_thread_local=False,
        need_project_workspace_lock=False,
    )
    try:
        chat.run(message=chat.first_message, times=1, need_interactive=False)
    finally:
        chat.ai_agent.close()

try:
    if os.environ.get("BDD_INTEGRITY_SCENARIO") == "1":
        run_integrity_scenario()
    else:
        run_turn("Create a plan for the startup-context regression.", os.environ.get("BDD_AGENT_TYPE", "plan_and_execute"))
    if os.environ.get("BDD_INTEGRITY_SCENARIO") != "1":
        wait_for_barrier()
        run_turn("Continue the existing plan in a later turn.", os.environ.get("BDD_AGENT_TYPE", "plan_and_execute"))
finally:
    cleanup_errors = []
    for worker in worker_threads:
        worker.join(timeout=10)
        if worker.is_alive():
            cleanup_errors.append(AssertionError("naming worker did not exit"))
    for worker, error in worker_results:
        if error is not None:
            cleanup_errors.append(error)
    for naming_chat in naming_chats:
        try:
            naming_chat.close()
        except BaseException as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise AssertionError("naming worker cleanup failed: " + "; ".join(map(str, cleanup_errors)))
'''


class SessionNameStartupScenario:
    """Own the loopback server and execute the real factory in a child process."""

    def __init__(self, monkeypatch: Any, tmp_path: Path, agent_type: str = "plan_and_execute", integrity: bool = False) -> None:
        """Create isolated startup files, database, and provider."""
        self.agent_type = agent_type
        self.integrity = integrity
        self.tmp_path = None
        self.server = None
        self.server_thread = None
        self.server_thread_started = False
        self.server_loop_started = threading.Event()
        self.server_loop_failed = None
        self.server_stop_requested = threading.Event()
        self.server_start_lock = threading.Lock()
        self.process = None
        try:
            self.tmp_path = Path(tempfile.mkdtemp(prefix="startup-scenario-", dir=str(tmp_path)))
            tmp_path = self.tmp_path
            self.home = tmp_path / "home"
            self.home.mkdir(parents=True, exist_ok=True)
            (self.home / "USER.md").write_text(USER_MARKER, encoding="utf-8")
            self.database = tmp_path / "sessions.sqlite"
            response_text = "BDD_PLAN_ANSWER_ONE_TOKEN" if integrity else "Plan complete"
            response = json.dumps([{"step_name": "final_answer", "raw_text": response_text}])
            self.server = create_server(MockServerConfig(port=0, reply=response, stream_chunks=(response,)))
            self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
            def serve_forever() -> None:
                with self.server_start_lock:
                    if self.server_stop_requested.is_set():
                        return
                    self.server_loop_started.set()
                try:
                    self.server.serve_forever()
                except BaseException as error:
                    self.server_loop_failed = error
                    raise

            self.server_thread = threading.Thread(
                target=serve_forever, daemon=True
            )
            self.server_thread.start()
            self.server_thread_started = True
            self.session_id = "bdd-plan-startup"
            self.events_dir = tmp_path / "events"
            self.events_dir.mkdir()
            self.wait_entered = self.events_dir / "wait-entered"
            self.started = self.events_dir / "started"
            self.wait_released = self.events_dir / "wait-released"
            self.user_open_count = self.events_dir / "user-md-open-count"
            self.user_open_count.write_text("0", encoding="utf-8")
            for key, value in {
                "TOPSAILAI_HOME": str(self.home),
                "TOPSAILAI_CONTEXT_USER_MESSAGE": EXPLICIT_MARKER,
                "TOPSAILAI_PROJECT_WORKSPACE": str(tmp_path),
                "TOPSAILAI_PWD": str(tmp_path),
                "CONTEXT_HISTORY_MANAGERS": f"sql.ChatHistorySQLAlchemy conn=sqlite:///{self.database}",
                "OPENAI_API_BASE": self.base_url,
                "OPENAI_BASE_URL": self.base_url,
                "OPENAI_API_KEY": "bdd-plan-startup",
                "OPENAI_MODEL": "topsailai-plan-startup",
                "LLM_RESPONSE_STREAM": "1",
                "TOPSAILAI_INTERACTIVE_MODE": "0",
                "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0" if integrity else "1",
                "TOPSAILAI_USE_TOOL_CALLS": "0",
                "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
                "TOPSAILAI_DISABLED_TOOLS": "*",
                "TOPSAILAI_DISABLED_SKILLS": "*",
                "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "0",
                "TOPSAILAI_TERMINAL_TITLE_ENABLED": "0",
                "TOPSAILAI_EVENTS_ENABLED": "0",
                "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
                "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "0",
                "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "0",
            }.items():
                monkeypatch.setenv(key, value)
        except BaseException:
            self.close()
            raise

    def run(self) -> None:
        """Run both a new-session turn and a later turn in a fresh subprocess."""
        env = os.environ.copy()
        env.update({
            "BDD_HOME": str(self.home),
            "BDD_WAIT_ENTERED": str(self.wait_entered),
            "BDD_STARTED": str(self.started),
            "BDD_WAIT_RELEASED": str(self.wait_released),
            "BDD_USER_OPEN_COUNT": str(self.user_open_count),
            "BDD_SESSION_ID": self.session_id,
            "BDD_AGENT_TYPE": self.agent_type,
            "BDD_INTEGRITY_SCENARIO": "1" if self.integrity else "0",
            "BDD_INTEGRITY_REPORT": str(self.events_dir / "integrity-report.json"),
        })
        self.process = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            cwd=str(Path(__file__).parents[2]),
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if self.process.returncode != 0:
            raise AssertionError(self.process.stderr or self.process.stdout)
        (self.events_dir / "child-stdout").write_text(self.process.stdout, encoding="utf-8")
        (self.events_dir / "child-stderr").write_text(self.process.stderr, encoding="utf-8")
        if not self.integrity:
            assert self.wait_entered.exists()
            assert self.started.exists()
            assert self.wait_released.exists()

    def state(self) -> dict[str, Any]:
        """Return captured provider requests."""
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/debug/state", timeout=3
        ) as response:
            return json.load(response)

    def request_texts(self) -> list[str]:
        """Return captured request bodies as serialized text."""
        return [json.dumps(item["body"], ensure_ascii=False) for item in self.state()["request_bodies"]]

    def integrity_report(self) -> dict[str, Any]:
        """Load the bounded child instruction observation report."""
        return json.loads((self.events_dir / "integrity-report.json").read_text(encoding="utf-8"))

    def close(self) -> None:
        """Terminate the owned provider and exact child process if needed."""
        if self.process is not None and self.process.returncode is None:
            raise AssertionError("startup subprocess did not terminate")
        errors = []
        if self.server is not None:
            if self.server_thread is not None and self.server_thread_started:
                self.server_stop_requested.set()
                deadline = time.monotonic() + 5
                while not self.server_loop_started.is_set() and self.server_thread.is_alive():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        errors.append(AssertionError("session naming mock-server thread did not enter"))
                        break
                    self.server_loop_started.wait(min(remaining, 0.05))
                if self.server_loop_started.is_set():
                    try:
                        self.server.shutdown()
                    except BaseException as error:
                        errors.append(error)
            try:
                self.server.server_close()
            except BaseException as error:
                errors.append(error)
        if self.server_thread is not None and self.server_thread_started:
            self.server_thread.join(timeout=5)
            if self.server_thread.is_alive():
                errors.append(AssertionError("session naming mock-server thread did not stop"))
        if self.server_loop_failed is not None:
            errors.append(self.server_loop_failed)
        if errors:
            raise AssertionError("scenario cleanup failed: " + "; ".join(map(str, errors)))
