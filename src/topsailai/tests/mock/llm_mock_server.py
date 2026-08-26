#!/usr/bin/env python3
"""OpenAI-compatible mock server with deterministic prompt-cache accounting."""

import argparse
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass(frozen=True)
class MockServerConfig:
    """Configuration for the mock LLM server."""

    host: str = "127.0.0.1"
    port: int = 0
    model: str = "topsailai-mock"
    reply: str = "Mock response"
    chars_per_token: int = 4
    cache_capacity: int = 32
    stream_chunks: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Reject invalid numeric configuration."""
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        if self.cache_capacity <= 0:
            raise ValueError("cache_capacity must be positive")


def _canonical_message(message: dict[str, Any]) -> str:
    """Serialize one message deterministically for cache comparisons."""
    return json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _message_tokens(message: str, chars_per_token: int) -> int:
    """Estimate tokens for one canonical message."""
    return max(1, (len(message) + chars_per_token - 1) // chars_per_token)


def prompt_token_count(messages: list[dict[str, Any]], chars_per_token: int) -> int:
    """Return the deterministic estimated prompt-token count."""
    return sum(
        _message_tokens(_canonical_message(message), chars_per_token)
        for message in messages
    )


def common_prefix_tokens(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    chars_per_token: int,
) -> tuple[int, int]:
    """Return token and message counts for the exact common message prefix."""
    token_count = 0
    message_count = 0
    for current_message, previous_message in zip(current, previous):
        current_text = _canonical_message(current_message)
        if current_text != _canonical_message(previous_message):
            break
        token_count += _message_tokens(current_text, chars_per_token)
        message_count += 1
    return token_count, message_count


class PromptCache:
    """Thread-safe bounded history used to simulate provider KV cache reuse."""

    def __init__(self, capacity: int, chars_per_token: int):
        """Initialize an empty prompt history."""
        self.capacity = capacity
        self.chars_per_token = chars_per_token
        self._prompts: deque[list[dict[str, Any]]] = deque(maxlen=capacity)
        self._requests: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._total_requests = 0
        self._lock = threading.Lock()

    def record(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        """Record a prompt and return its best historical prefix match."""
        with self._lock:
            best_tokens = 0
            best_messages = 0
            for previous in self._prompts:
                tokens, message_count = common_prefix_tokens(
                    messages,
                    previous,
                    self.chars_per_token,
                )
                if tokens > best_tokens:
                    best_tokens = tokens
                    best_messages = message_count

            prompt_tokens = prompt_token_count(messages, self.chars_per_token)
            self._total_requests += 1
            request = {
                "request_number": self._total_requests,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": best_tokens,
                "cached_messages": best_messages,
                "message_count": len(messages),
            }
            self._prompts.append(json.loads(json.dumps(messages)))
            self._requests.append(request)
            return dict(request)

    def state(self) -> dict[str, Any]:
        """Return a JSON-serializable cache snapshot."""
        with self._lock:
            return {
                "capacity": self.capacity,
                "cached_prompt_count": len(self._prompts),
                "total_requests": self._total_requests,
                "requests": list(self._requests),
            }

    def clear(self) -> None:
        """Clear cache entries and request counters."""
        with self._lock:
            self._prompts.clear()
            self._requests.clear()
            self._total_requests = 0


class LLMMockServer(ThreadingHTTPServer):
    """HTTP server carrying mock configuration and prompt-cache state."""

    daemon_threads = True

    def __init__(self, config: MockServerConfig):
        """Bind the server and initialize its bounded prompt cache."""
        super().__init__((config.host, config.port), LLMMockRequestHandler)
        self.config = config
        self.prompt_cache = PromptCache(config.cache_capacity, config.chars_per_token)


class LLMMockRequestHandler(BaseHTTPRequestHandler):
    """Serve the supported OpenAI and debug endpoints."""

    server: LLMMockServer

    def log_message(self, format: str, *args: Any) -> None:
        """Use quiet request handling so tests control their own output."""
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        """Write one JSON response."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        """Write an OpenAI-shaped error response."""
        self._write_json(status, {"error": {"message": message, "type": "invalid_request_error"}})

    def _write_sse(self, payload: dict[str, Any] | str) -> None:
        """Write one server-sent event and flush it immediately."""
        data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _write_stream(self, payload: dict[str, Any], cache_result: dict[str, int]) -> None:
        """Write an OpenAI-compatible scripted streaming completion."""
        completion_id = f"chatcmpl-mock-{uuid.uuid4().hex}"
        created = int(time.time())
        model = payload.get("model") or self.server.config.model
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for content in self.server.config.stream_chunks or ():
                self._write_sse({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": content},
                        "finish_reason": None,
                    }],
                })
            self._write_sse({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": cache_result["prompt_tokens"],
                    "completion_tokens": 0,
                    "total_tokens": cache_result["prompt_tokens"],
                    "prompt_tokens_details": {
                        "cached_tokens": cache_result["cached_tokens"],
                    },
                },
            })
            self._write_sse("[DONE]")
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.close_connection = True

    def do_GET(self) -> None:
        """Handle health and debug-state queries."""
        if self.path == "/health":
            self._write_json(200, {"status": "ok", "model": self.server.config.model})
            return
        if self.path == "/debug/state":
            self._write_json(200, self.server.prompt_cache.state())
            return
        self._error(404, "not found")

    def do_DELETE(self) -> None:
        """Clear debug state to support deterministic test reuse."""
        if self.path != "/debug/state":
            self._error(404, "not found")
            return
        self.server.prompt_cache.clear()
        self._write_json(200, {"status": "cleared"})

    def do_POST(self) -> None:
        """Handle non-streaming OpenAI-compatible chat completions."""
        if self.path != "/v1/chat/completions":
            self._error(404, "not found")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length))
        except (ValueError, json.JSONDecodeError):
            self._error(400, "request body must be valid JSON")
            return
        if not isinstance(payload, dict):
            self._error(400, "request body must be a JSON object")
            return

        messages = payload.get("messages")
        if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
            self._error(400, "messages must be a list of objects")
            return
        if payload.get("stream") and self.server.config.stream_chunks is None:
            self._error(400, "streaming is not supported")
            return

        cache_result = self.server.prompt_cache.record(messages)
        if payload.get("stream"):
            self._write_stream(payload, cache_result)
            return

        completion_tokens = max(
            1,
            (len(self.server.config.reply) + self.server.config.chars_per_token - 1)
            // self.server.config.chars_per_token,
        )
        prompt_tokens = cache_result["prompt_tokens"]
        response = {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model") or self.server.config.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": self.server.config.reply},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "prompt_tokens_details": {
                    "cached_tokens": cache_result["cached_tokens"],
                },
            },
        }
        self._write_json(200, response)


def create_server(config: MockServerConfig | None = None) -> LLMMockServer:
    """Create a reusable mock server without starting its serving loop."""
    return LLMMockServer(config or MockServerConfig())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line configuration; explicit arguments define all behavior."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="topsailai-mock")
    parser.add_argument("--reply", default="Mock response")
    parser.add_argument("--chars-per-token", type=int, default=4)
    parser.add_argument("--cache-capacity", type=int, default=32)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the mock server until interrupted."""
    args = parse_args(argv)
    config = MockServerConfig(
        host=args.host,
        port=args.port,
        model=args.model,
        reply=args.reply,
        chars_per_token=args.chars_per_token,
        cache_capacity=args.cache_capacity,
    )
    server = create_server(config)
    host, port = server.server_address
    print(f"LLM mock server listening at http://{host}:{port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
