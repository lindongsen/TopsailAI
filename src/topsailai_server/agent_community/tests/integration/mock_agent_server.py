#!/usr/bin/env python3
"""Simple HTTP mock agent server for integration tests.

This server implements the endpoints expected by the `topsailai_send_message`
client (used by the `topsailai_agent_cmd_*` scripts) so that ACS can invoke
agent members during integration tests.

Endpoints:
  GET  /health                       -> health check
  GET  /api/v1/session/<session_id>  -> session status (used by /status command)
  POST /api/v1/message               -> send a message (used by chat command)
  GET  /api/v1/message               -> list messages by processed_msg_id
"""

import argparse
import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class MockAgentHandler(BaseHTTPRequestHandler):
    """Handler for mock agent daemon API requests."""

    # Shared state across all handler instances
    state_lock = threading.Lock()
    messages = {}  # session_id -> list of message dicts
    config = {
        "delay": 1.5,
        "error_rate": 0.0,
    }

    def log_message(self, fmt, *args):
        print(f"[MockAgent] {self.address_string()} - {fmt % args}")

    def _send_json(self, status_code, body):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def _api_response(self, data, message="", code=0):
        return {"code": code, "data": data, "message": message}

    def _should_error(self):
        return random.random() < self.config["error_rate"]

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(200, self._api_response({"status": "healthy"}))
            return

        if path.startswith("/api/v1/session/"):
            session_id = path[len("/api/v1/session/"):]
            if not session_id:
                self._send_json(400, self._api_response(None, "Session ID required", 1))
                return
            self._send_json(200, self._api_response({"status": "idle"}))
            return

        if path == "/api/v1/message":
            session_id = self._first(query.get("session_id"))
            processed_msg_id = self._first(query.get("processed_msg_id"))

            if not session_id or not processed_msg_id:
                self._send_json(
                    400,
                    self._api_response(None, "session_id and processed_msg_id required", 1),
                )
                return

            # Simulate the agent processing time before the response is available.
            delay = self.config["delay"]
            if delay > 0:
                time.sleep(delay)

            if self._should_error():
                # Use 422 Unprocessable Entity so the client treats this as a
                # non-retryable application error and returns immediately.
                self._send_json(422, self._api_response(None, "mock agent error", 1))
                return

            with self.state_lock:
                session_messages = self.messages.setdefault(session_id, [])
                response_msg = {
                    "msg_id": f"msg-{uuid.uuid4().hex[:12]}",
                    "session_id": session_id,
                    "processed_msg_id": processed_msg_id,
                    "role": "assistant",
                    "message": "Mock agent response",
                    "task_id": "",
                    "task_result": "",
                    "create_time": self._now(),
                }
                session_messages.append(response_msg)

            self._send_json(200, self._api_response([response_msg]))
            return

        self._send_json(404, self._api_response(None, "not found", 1))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/v1/message":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json(400, self._api_response(None, "invalid JSON", 1))
                return

            session_id = payload.get("session_id", "")
            if not session_id:
                self._send_json(400, self._api_response(None, "session_id required", 1))
                return

            # Simulate a chat failure when the mock is configured to error.
            # Failing the POST causes topsailai_send_message to exit immediately
            # with a non-zero status, which lets the ACS consumer reset the
            # agent member_status back to idle within the test timeout.
            if self._should_error():
                self._send_json(500, self._api_response(None, "mock agent chat error", 1))
                return

            new_msg_id = f"msg-{uuid.uuid4().hex[:12]}"
            request_msg = {
                "msg_id": new_msg_id,
                "session_id": session_id,
                "processed_msg_id": payload.get("processed_msg_id", ""),
                "role": payload.get("role", "user"),
                "message": payload.get("message", ""),
                "task_id": "",
                "task_result": "",
                "create_time": self._now(),
            }
            with self.state_lock:
                self.messages.setdefault(session_id, []).append(request_msg)

            self._send_json(200, self._api_response({"msg_id": new_msg_id}))
            return

        self._send_json(404, self._api_response(None, "not found", 1))

    @staticmethod
    def _first(values):
        if values:
            return values[0]
        return None


class MockAgentServer:
    """Wrapper around the mock agent HTTP server.

    Supports both explicit ``start()``/``stop()`` calls and the context-manager
    protocol (``with MockAgentServer(...) as server:``).
    """

    def __init__(
        self,
        host="127.0.0.1",
        port=7371,
        delay=1.5,
        error_rate=0.0,
        # Backward-compatible parameters kept for existing tests.
        agent_id=None,
        agent_name=None,
        auth_token=None,
    ):
        self.host = host
        self.port = port
        self.delay = delay
        self.error_rate = error_rate
        # agent_id, agent_name and auth_token are accepted for backward
        # compatibility but are not required by the new agent-daemon API.
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.auth_token = auth_token
        self.server = None
        self.thread = None

    def start(self):
        MockAgentHandler.config["delay"] = self.delay
        MockAgentHandler.config["error_rate"] = self.error_rate
        MockAgentHandler.messages.clear()

        self.server = HTTPServer((self.host, self.port), MockAgentHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[MockAgent] Server started on http://{self.host}:{self.port}")
        return self

    def stop(self):
        print("[MockAgent] Server stopping")
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def main():
    parser = argparse.ArgumentParser(description="Mock agent daemon server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7371)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--error-rate", type=float, default=0.0)
    args = parser.parse_args()

    server = MockAgentServer(
        host=args.host, port=args.port, delay=args.delay, error_rate=args.error_rate
    )
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
