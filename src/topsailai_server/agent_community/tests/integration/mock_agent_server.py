#!/usr/bin/env python3
"""Mock AI-Agent Server for testing ACS integration.

This server simulates an AI agent that responds to chat requests.
It supports configurable delay, error rate, and Bearer Token authentication.
"""

import argparse
import json
import logging
import random
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mock_agent")


class MockAgentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock agent server."""

    def __init__(self, config, *args, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info(format % args)

    def _send_json(self, status_code, data):
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _check_auth(self):
        """Check Bearer Token authentication if configured."""
        if not self.config.get("auth_token"):
            return True

        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.config['auth_token']}"
        if auth_header != expected:
            logger.warning("Authentication failed: %s", auth_header)
            return False
        return True

    def _simulate_delay(self):
        """Simulate processing delay."""
        delay = self.config.get("delay", 0)
        if delay > 0:
            time.sleep(delay)

    def _should_error(self):
        """Determine if this request should simulate an error."""
        error_rate = self.config.get("error_rate", 0)
        return random.random() < error_rate

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._handle_health()
        elif path == "/status":
            self._handle_status()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/chat":
            self._handle_chat()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_health(self):
        """Handle health check endpoint."""
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        self._send_json(200, {
            "status": "healthy",
            "agent_id": self.config.get("agent_id", "mock-agent"),
            "timestamp": int(time.time() * 1000)
        })

    def _handle_status(self):
        """Handle status check endpoint."""
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        # Randomly return idle or processing
        statuses = ["idle", "processing"]
        status = random.choice(statuses)

        self._send_json(200, {
            "status": status,
            "agent_id": self.config.get("agent_id", "mock-agent"),
            "timestamp": int(time.time() * 1000)
        })

    def _handle_chat(self):
        """Handle chat endpoint."""
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            request_data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            request_data = {}

        # Simulate delay
        self._simulate_delay()

        # Simulate error
        if self._should_error():
            self._send_json(500, {
                "error": "simulated agent error",
                "agent_id": self.config.get("agent_id", "mock-agent")
            })
            return

        # Generate response based on input
        message = request_data.get("message", "")
        agent_mode = request_data.get("mode", "agent")
        agent_id = self.config.get("agent_id", "mock-agent")
        agent_name = self.config.get("agent_name", "Mock Agent")

        # Generate a contextual response
        if "@all" in message:
            response_text = f"Hello everyone! This is {agent_name} ({agent_id}). I received a message addressed to all members."
        elif "@" in message:
            mentioned = [w for w in message.split() if w.startswith("@")]
            response_text = f"Hi! {agent_name} here. I see mentions: {', '.join(mentioned)}. How can I help?"
        elif "help" in message.lower():
            response_text = f"I'm {agent_name} ({agent_id}), ready to assist you. What do you need help with?"
        elif agent_mode == "chat":
            response_text = f"[{agent_name}] Chat mode response: {message}"
        else:
            if len(message) > 50:
                response_text = f"[{agent_name}] Agent mode response to: '{message[:50]}...'"
            else:
                response_text = f"[{agent_name}] Agent mode response to: '{message}'"

        response_data = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "mode": agent_mode,
            "response": response_text,
            "timestamp": int(time.time() * 1000),
            "processed": True
        }

        logger.info("Chat response: %s", response_data["response"][:100])
        self._send_json(200, response_data)


def create_handler(config):
    """Create a request handler class with config."""
    def handler(*args, **kwargs):
        return MockAgentHandler(config, *args, **kwargs)
    return handler


class MockAgentServer:
    """Mock agent server wrapper for testing."""

    def __init__(self, host="127.0.0.1", port=18080, agent_id="mock-agent",
                 agent_name="Mock Agent", auth_token="", delay=0.1, error_rate=0.0):
        self.host = host
        self.port = port
        self.config = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "auth_token": auth_token,
            "delay": delay,
            "error_rate": error_rate,
        }
        self.server = None
        self.thread = None

    def start(self):
        """Start the mock agent server in a background thread."""
        handler_class = create_handler(self.config)
        self.server = HTTPServer((self.host, self.port), handler_class)

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(
            "Mock agent server started on %s:%d (agent_id=%s)",
            self.host, self.port, self.config["agent_id"]
        )

    def stop(self):
        """Stop the mock agent server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Mock agent server stopped")

    def is_running(self):
        """Check if the server is running."""
        return self.thread is not None and self.thread.is_alive()


def main():
    """Run the mock agent server."""
    parser = argparse.ArgumentParser(description="Mock AI-Agent Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=18080, help="Port to listen on")
    parser.add_argument("--agent-id", default="mock-agent", help="Agent ID")
    parser.add_argument("--agent-name", default="Mock Agent", help="Agent name")
    parser.add_argument("--auth-token", default="", help="Bearer token for auth")
    parser.add_argument("--delay", type=float, default=0.1, help="Response delay in seconds")
    parser.add_argument("--error-rate", type=float, default=0.0, help="Error rate (0.0-1.0)")

    args = parser.parse_args()

    server = MockAgentServer(
        host=args.host,
        port=args.port,
        agent_id=args.agent_id,
        agent_name=args.agent_name,
        auth_token=args.auth_token,
        delay=args.delay,
        error_rate=args.error_rate,
    )
    server.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down mock agent server...")
        server.stop()


if __name__ == "__main__":
    main()
