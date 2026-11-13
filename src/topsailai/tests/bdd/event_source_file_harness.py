"""Real-HTTP harness that inspects the events file written by production paths.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Drive real production event sources and assert on the on-disk JSONL file
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.events import reset_event_collector
from topsailai.events.collector import get_event_collector


class EventSourceFileHarness:
    """Own one mock provider, one events file, and the real production paths.

    The harness never stubs an event producer. It drives the real
    ``LLMModel.chat()``, the real ``exec_tool_func()`` and the real
    ``with_tool_approval()`` ASK branch, then reads the JSONL file that the
    production file backend actually wrote.
    """

    def __init__(
        self,
        monkeypatch: Any,
        directory: Path,
        session_id: str = "bdd-event-file",
        enabled: bool = True,
    ):
        """Start the provider, point the collector at a scenario-owned file."""
        self.monkeypatch = monkeypatch
        self.directory = directory
        self.session_id = session_id
        self.enabled = enabled
        self.events_path = directory / "bdd.events"
        self.prompt_text = "bdd private prompt text"
        self.tool_argument = "/tmp/bdd-private-argument"
        self.original_interrupt = None
        self.observed_interrupt = None
        self.tool_result = None
        self.approval_result = None
        self.approval_instance_id = None
        self.model = None

        self.server = create_server(MockServerConfig(port=0, reply="bdd reply"))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-event-source-file-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "TOPSAILAI_EVENTS_ENABLED": "1" if enabled else "0",
            "TOPSAILAI_EVENTS_FILE_PATH": str(self.events_path),
            "TOPSAILAI_SESSION_ID": session_id,
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "bdd-event-file",
            "OPENAI_MODEL": "bdd-event-model",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_MODEL_SETTINGS": "",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        reset_event_collector()

    def send_llm_request(self) -> None:
        """Run one real LLM request through the real OpenAI-compatible client."""
        from topsailai.ai_base.llm_base import LLMModel

        self.model = LLMModel()
        self.model.chat([{"role": "user", "content": self.prompt_text}])

    def interrupt_llm_request(self, exception_type: str) -> None:
        """Run the real chat lifecycle until its interrupt checkpoint raises."""
        from topsailai.ai_base import llm_base
        from topsailai.ai_base.exception import HardInterruptError

        if exception_type == "HardInterruptError":
            interrupt = HardInterruptError("bdd hard interrupt")
        elif exception_type == "KeyboardInterrupt":
            interrupt = KeyboardInterrupt()
        else:
            raise AssertionError(f"unsupported interrupt type: {exception_type}")

        class _InterruptingAgent:
            """Raise the exact interruption supplied by the scenario."""

            def _check_hard_interrupt(self):
                raise interrupt

        model = object.__new__(llm_base.LLMModel)
        model.model_name = "bdd-event-model"
        original = llm_base.get_agent_object
        llm_base.get_agent_object = lambda: _InterruptingAgent()
        try:
            model.chat([{"role": "user", "content": self.prompt_text}])
        except BaseException as error:  # noqa: BLE001 - the scenario expects the interrupt
            self.original_interrupt = interrupt
            self.observed_interrupt = error
        else:
            raise AssertionError(f"{exception_type} did not reach the caller")
        finally:
            llm_base.get_agent_object = original

    def execute_tool(self) -> None:
        """Run one real tool call through the decorated production entry."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func

        def _bdd_tool(path: str = "") -> str:
            """Return a marker so the recorded result is predictable."""
            return f"read {path}"

        self.tool_result = exec_tool_func(
            _bdd_tool, {"path": self.tool_argument}, tool_name="bdd_tool"
        )

    def approve_tool(self) -> None:
        """Run the real approval ASK branch and approve it from another thread."""
        from topsailai.ai_base.tool_approval import decorator as approval_decorator
        from topsailai.ai_base.tool_approval.instance import ApprovalDecision
        from topsailai.ai_base.tool_approval.transport import ApprovalTransport

        class _RecordingTransport(ApprovalTransport):
            """Transport that records requests and resolves them on demand."""

            def __init__(self):
                self.instances = []
                self.request_ready = threading.Event()
                self._lock = threading.Lock()
                self._events = {}

            def send_request(self, instance):
                """Record the request and signal that it is ready to resolve."""
                self.instances.append(instance)
                with self._lock:
                    self._events[instance.id] = threading.Event()
                self.request_ready.set()

            def wait_response(self, instance, timeout=None):
                """Block until the decision is resolved or the timeout expires."""
                with self._lock:
                    event = self._events.get(instance.id)
                if event is None:
                    return instance.status
                effective = timeout if timeout is not None else instance.timeout
                if event.wait(timeout=effective):
                    return instance.status
                return instance.STATUS_TIMEOUT

            def on_resolved(self, instance):
                """Wake the waiter for a resolved instance."""
                with self._lock:
                    event = self._events.pop(instance.id, None)
                if event is not None:
                    event.set()

            def supports_external_resolution(self):
                """Allow another thread to approve while the caller waits."""
                return True

        transport = _RecordingTransport()
        self.monkeypatch.setattr(
            approval_decorator, "_get_default_transport", lambda: transport, raising=True
        )
        self.monkeypatch.setattr(
            approval_decorator.ToolApprovalInstance,
            "decide",
            lambda self: ApprovalDecision(
                action=ApprovalDecision.ASK,
                rule=SimpleNamespace(name="bdd-rule"),
                timeout=5.0,
                policy="deny",
            ),
            raising=True,
        )

        from topsailai.ai_base.tool_approval.decorator import with_tool_approval

        def _danger_tool(tool_func, args, tool_name=None, **kwargs):
            """Stand-in tool body that records its own execution."""
            return "approved-run"

        decorated = with_tool_approval(_danger_tool)

        def _approve_later():
            """Approve the pending request once the transport has it."""
            if transport.request_ready.wait(timeout=5.0):
                transport.instances[0].approve()

        thread = threading.Thread(target=_approve_later, daemon=True)
        thread.start()
        self.approval_result = decorated(
            tool_func=_danger_tool,
            args={"path": self.tool_argument},
            tool_name="bdd_danger_tool",
        )
        thread.join(timeout=5.0)
        self.approval_instance_id = transport.instances[0].id

    def flush(self) -> None:
        """Flush the production collector so the file holds every record."""
        get_event_collector().flush()

    def events(self) -> list[dict]:
        """Read the real JSONL file and return every parsed record."""
        self.flush()
        if not self.events_path.exists():
            return []
        records = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def of_type(self, event_type: str) -> list[dict]:
        """Return every record of one event type."""
        return [record for record in self.events() if record["event_type"] == event_type]

    def close(self) -> None:
        """Stop only this scenario's provider and collector."""
        if self.model is not None:
            self.model.close()
        reset_event_collector()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("event-source-file mock-server thread did not stop")
