"""Real-HTTP harness for optional USER.md startup context loading."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.llm_shell import get_llm_chat
from topsailai.workspace import folder_constants

USER_MARKER = "BDD_USER_MD_MARKER"
EXPLICIT_MARKER = "BDD_EXPLICIT_CONTEXT_MARKER"


class UserMdLoadingScenario:
    """Own scenario files, environment, client, and loopback mock server."""

    def __init__(self, monkeypatch: Any, tmp_path: Path, enabled: bool):
        """Create isolated USER.md and explicit-context fixtures."""
        self.tmp_path = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        (self.home / "USER.md").write_text(USER_MARKER, encoding="utf-8")
        response = json.dumps([{"step_name": "final_answer", "raw_text": "BDD response"}])
        self.server = create_server(
            MockServerConfig(port=0, reply=response, stream_chunks=(response,))
        )
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        monkeypatch.setattr(folder_constants, "TOPSAILAI_HOME", str(self.home))
        self.client = None
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        if enabled:
            monkeypatch.delenv("TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED", raising=False)
        else:
            monkeypatch.setenv("TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED", "0")
        for key, value in {
            "TOPSAILAI_HOME": str(self.home),
            "TOPSAILAI_CONTEXT_USER_MESSAGE": EXPLICIT_MARKER,
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock-user-md",
            "OPENAI_MODEL": "topsailai-user-md",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
        }.items():
            monkeypatch.setenv(key, value)

    def send(self) -> None:
        """Send one production direct-chat request over loopback HTTP."""
        self.client = get_llm_chat(
            message="BDD user md task",
            session_id="",
            need_stdout=False,
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )
        try:
            self.client.chat(need_print=False, need_env_message=False)
        finally:
            self.client.close()

    def send_second(self) -> None:
        """Send a second request after refreshing only explicit context."""
        # The first PromptBase clears explicit startup context after consuming it.
        from os import environ
        environ["TOPSAILAI_CONTEXT_USER_MESSAGE"] = EXPLICIT_MARKER + "_SECOND"
        self.send()

    def state(self) -> dict[str, Any]:
        """Read bounded request capture from the mock server."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def close(self) -> None:
        """Stop this scenario's exact server thread and release its socket."""
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("USER.md mock-server thread did not stop")
