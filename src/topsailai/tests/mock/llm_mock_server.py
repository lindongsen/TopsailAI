#!/usr/bin/env python3
"""OpenAI-compatible mock server with deterministic prompt-cache accounting."""

import argparse
import json
import math
import numbers
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

if __package__:
    from .llm_mock_lifecycle import LifecycleCapture, RequestHandle
else:
    from llm_mock_lifecycle import LifecycleCapture, RequestHandle


@dataclass(frozen=True)
class MockServerConfig:
    """Configuration for the mock LLM server."""

    host: str = "127.0.0.1"
    port: int = 0
    model: str = "topsailai-mock"
    reply: str = "Mock response"
    chars_per_token: int = 4
    cache_capacity: int = 32
    request_body_capacity: int = 32
    stream_chunks: tuple[str, ...] | None = None
    stream_response_chunks: tuple[tuple[str, ...], ...] | None = None
    stream_error_messages: tuple[str | None, ...] | None = None
    stream_http_error_responses: tuple[tuple[int, str], ...] | None = None
    report_cache_usage: bool = True
    report_usage: bool = True
    tool_call_responses: tuple[tuple[dict[str, Any], ...], ...] | None = None
    tool_call_response_content: str | None = None
    response_header_delays: tuple[float, ...] | None = None
    first_chunk_delays: tuple[float, ...] | None = None
    after_first_chunk_delays: tuple[float, ...] | None = None
    complete_response_delays: tuple[float, ...] | None = None
    complete_response_replies: tuple[str, ...] | None = None
    lifecycle_capacity: int = 32

    def __post_init__(self) -> None:
        """Reject invalid numeric configuration."""
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        if self.cache_capacity <= 0:
            raise ValueError("cache_capacity must be positive")
        if self.request_body_capacity <= 0:
            raise ValueError("request_body_capacity must be positive")
        if isinstance(self.lifecycle_capacity, bool) or not isinstance(self.lifecycle_capacity, int) or self.lifecycle_capacity <= 0:
            raise ValueError("lifecycle_capacity must be a positive integer")
        for name, delays in (
            ("response_header_delays", self.response_header_delays),
            ("first_chunk_delays", self.first_chunk_delays),
            ("after_first_chunk_delays", self.after_first_chunk_delays),
            ("complete_response_delays", self.complete_response_delays),
        ):
            if delays is None:
                continue
            if not isinstance(delays, tuple):
                raise ValueError(f"{name} must be a tuple of finite non-negative numbers")
            for delay in delays:
                try:
                    valid = (not isinstance(delay, bool) and isinstance(delay, numbers.Real)
                             and math.isfinite(delay) and delay >= 0)
                except (OverflowError, TypeError, ValueError):
                    valid = False
                if not valid:
                    raise ValueError(f"{name} must contain finite non-negative numbers")

def _canonical_value(value: Any) -> str:
    """Serialize one request value deterministically for cache comparisons."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_message(message: dict[str, Any]) -> str:
    """Serialize one message deterministically for cache comparisons."""
    return _canonical_value(message)


def _message_tokens(message: str, chars_per_token: int) -> int:
    """Estimate tokens for one canonical request component."""
    return max(1, (len(message) + chars_per_token - 1) // chars_per_token)


def prompt_token_count(
    messages: list[dict[str, Any]],
    chars_per_token: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
) -> int:
    """Return the deterministic estimated complete prompt-token count."""
    token_count = sum(
        _message_tokens(_canonical_message(message), chars_per_token)
        for message in messages
    )
    if tools:
        token_count += _message_tokens(_canonical_value(tools), chars_per_token)
        token_count += _message_tokens(_canonical_value(tool_choice), chars_per_token)
    return token_count


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
        self._prompts: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._requests: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._total_requests = 0
        self._lock = threading.Lock()

    def record(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> dict[str, int]:
        """Record a complete prompt and return its best historical prefix match."""
        with self._lock:
            best_tokens = 0
            best_messages = 0
            for previous in self._prompts:
                if _canonical_value(tools) != _canonical_value(previous["tools"]):
                    continue
                if _canonical_value(tool_choice) != _canonical_value(previous["tool_choice"]):
                    continue
                tokens, message_count = common_prefix_tokens(
                    messages,
                    previous["messages"],
                    self.chars_per_token,
                )
                if tools:
                    tokens += _message_tokens(_canonical_value(tools), self.chars_per_token)
                    tokens += _message_tokens(_canonical_value(tool_choice), self.chars_per_token)
                if tokens > best_tokens:
                    best_tokens = tokens
                    best_messages = message_count

            prompt_tokens = prompt_token_count(
                messages,
                self.chars_per_token,
                tools=tools,
                tool_choice=tool_choice,
            )
            self._total_requests += 1
            request = {
                "request_number": self._total_requests,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": best_tokens,
                "cached_messages": best_messages,
                "message_count": len(messages),
            }
            self._prompts.append(json.loads(json.dumps({
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            })))
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


class RequestBodyCapture:
    """Thread-safe bounded storage for HTTP request bodies."""

    def __init__(self, capacity: int):
        """Initialize bounded request-body storage."""
        self.capacity = capacity
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._total_records = 0
        self._dropped_records = 0
        self._lock = threading.Lock()

    def record(self, raw_body: bytes, parsed_body: Any = None, parse_error: str | None = None) -> None:
        """Record one parsed or malformed request body without raising."""
        with self._lock:
            self._total_records += 1
            if len(self._records) == self.capacity:
                self._dropped_records += 1
            record = {
                "request_number": self._total_records,
                "parsed": parse_error is None,
                "body": parsed_body if parse_error is None else None,
            }
            if parse_error is not None:
                record["raw_body"] = raw_body.decode("utf-8", errors="replace")
                record["parse_error"] = parse_error
            self._records.append(record)

    def state(self) -> dict[str, Any]:
        """Return a JSON-serializable request-body snapshot."""
        with self._lock:
            return {
                "request_body_capacity": self.capacity,
                "request_bodies": list(self._records),
                "dropped_request_body_count": self._dropped_records,
            }

    def clear(self) -> None:
        """Clear captured bodies and counters."""
        with self._lock:
            self._records.clear()
            self._total_records = 0
            self._dropped_records = 0


class LLMMockServer(ThreadingHTTPServer):
    """HTTP server carrying mock configuration and owned request resources."""

    daemon_threads = True

    def __init__(self, config: MockServerConfig):
        """Bind the server and initialize bounded state and worker ownership."""
        super().__init__((config.host, config.port), LLMMockRequestHandler)
        self.config = config
        self.prompt_cache = PromptCache(config.cache_capacity, config.chars_per_token)
        self.request_body_capture = RequestBodyCapture(config.request_body_capacity)
        self.lifecycle_capture = LifecycleCapture(config.lifecycle_capacity)
        self._ownership_lock = threading.RLock()
        self._workers: dict[threading.Thread, dict[str, Any]] = {}
        self._stopping = False

    def process_request(self, request, client_address) -> None:
        """Register exact socket/thread ownership before starting each daemon worker."""
        with self._ownership_lock:
            for completed in [item for item in self._workers if not item.is_alive()]:
                self._workers.pop(completed, None)
            if self._stopping:
                self.shutdown_request(request)
                return
            thread = threading.Thread(target=self.process_request_thread,
                                      args=(request, client_address), daemon=True)
            self._workers[thread] = {"socket": request, "handle": None}
            try:
                thread.start()
            except BaseException:
                self._workers.pop(thread, None)
                self.shutdown_request(request)
                raise

    def capture_body(self, *args: Any, **kwargs: Any) -> None:
        """Record a body atomically with debug-state reset."""
        with self._ownership_lock:
            self.request_body_capture.record(*args, **kwargs)

    def admit_completion(self, payload: dict[str, Any], raw_body: bytes) -> tuple[dict[str, Any], RequestHandle]:
        """Atomically capture, allocate the completion ordinal, and publish its handle."""
        with self._ownership_lock:
            self.request_body_capture.record(raw_body, parsed_body=payload)
            result = self.prompt_cache.record(payload["messages"], tools=payload.get("tools"),
                                              tool_choice=payload.get("tool_choice"))
            return result, self.bind_handle(result["request_number"])

    def reset_debug_state(self) -> bool:
        """Reset only when no completion handler can own an active identity."""
        with self._ownership_lock:
            if any(context["handle"] is not None and thread.is_alive()
                   for thread, context in self._workers.items()):
                return False
            self.prompt_cache.clear()
            self.request_body_capture.clear()
            self.lifecycle_capture.clear()
            return True

    def bind_handle(self, request_number: int) -> RequestHandle:
        """Bind lifecycle authority to this handler's exact worker and socket."""
        thread = threading.current_thread()
        with self._ownership_lock:
            context = self._workers.get(thread)
            if context is None:
                raise RuntimeError("request handler has no owned worker context")
            handle = self.lifecycle_capture.start(request_number, thread, context["socket"])
            context["handle"] = handle
            if self._stopping:
                handle.release_delay()
            return handle

    def mark_connection_closed(self, request) -> None:
        """Record successful local socket shutdown for its exact worker."""
        with self._ownership_lock:
            for context in self._workers.values():
                if context["socket"] is request:
                    handle = context["handle"]
                    if handle is not None:
                        self.lifecycle_capture.mark(handle, "connection_closed")
                    return

    def shutdown_request(self, request) -> None:
        """Close one owned socket and observe local close only on success."""
        super().shutdown_request(request)
        self.mark_connection_closed(request)

    def _delay_seconds(self, delays: tuple[float, ...] | None, index: int) -> float:
        """Return zero for an unspecified request index, including unequal arrays."""
        return delays[index] if delays is not None and index < len(delays) else 0.0

    def release_delay(self, request_number: int) -> None:
        """Release both configured delays for one retained request."""
        self.lifecycle_capture.request_handle(request_number).release_delay()

    def stop_handlers(self, timeout: float = 5.0) -> None:
        """Release and join all exact owned workers or report a cleanup failure."""
        deadline = time.monotonic() + timeout
        with self._ownership_lock:
            self._stopping = True
            contexts = list(self._workers.items())
            for _, context in contexts:
                handle = context["handle"]
                if handle is not None:
                    handle.release_delay()
                try:
                    context["socket"].shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        alive = []
        for thread, _ in contexts:
            thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                alive.append(thread.name)
        with self._ownership_lock:
            for thread, _ in contexts:
                if not thread.is_alive():
                    self._workers.pop(thread, None)
        if alive:
            raise RuntimeError(f"mock handler threads did not exit: {alive}")

    def server_close(self) -> None:
        """Join owned handlers, always close listener, and preserve cleanup errors."""
        error = None
        try:
            self.stop_handlers()
        except BaseException as caught:
            error = caught
        try:
            super().server_close()
        finally:
            if error is not None:
                raise error

    def process_request_thread(self, request, client_address) -> None:
        """Run the standard handler and finalize response work on every path."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._ownership_lock:
                context = self._workers.get(threading.current_thread())
                handle = context["handle"] if context else None



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

    def _wait_delay(self, seconds: float, handle: RequestHandle, phase: str) -> None:
        """Wait in a named phase until timeout or scenario-owned release."""
        self.server.lifecycle_capture.mark(handle, "waiting_phase", phase)
        handle.release.wait(seconds)
        self.server.lifecycle_capture.mark(handle, "waiting_phase", None)

    def _write_stream(self, payload: dict[str, Any], cache_result: dict[str, int],
                      lifecycle: RequestHandle) -> None:
        """Write an OpenAI-compatible request-indexed streaming completion."""
        try:
            completion_id = f"chatcmpl-mock-{uuid.uuid4().hex}"
            created = int(time.time())
            model = payload.get("model") or self.server.config.model
            scripted_responses = self.server.config.stream_response_chunks or ()
            scripted_errors = self.server.config.stream_error_messages or ()
            response_index = cache_result["request_number"] - 1
            stream_chunks = scripted_responses[response_index] if response_index < len(scripted_responses) else self.server.config.stream_chunks or ()
            stream_error = scripted_errors[response_index] if response_index < len(scripted_errors) else None
            completion_tokens = max(1, (sum(len(content) for content in stream_chunks) + self.server.config.chars_per_token - 1) // self.server.config.chars_per_token)
            total_tokens = cache_result["prompt_tokens"] + completion_tokens
            header_delay = self.server._delay_seconds(self.server.config.response_header_delays, response_index)
            if header_delay > 0:
                self._wait_delay(header_delay, lifecycle, "headers")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            self.server.lifecycle_capture.mark(lifecycle, "headers_sent")
            first_item_delay = self.server._delay_seconds(self.server.config.first_chunk_delays, response_index)
            if first_item_delay > 0:
                self._wait_delay(first_item_delay, lifecycle, "first_item")
            if stream_error is not None:
                self._write_sse({"error": {"message": stream_error}})
                self.server.lifecycle_capture.mark(lifecycle, "first_item_sent")
                return
            first_item_sent = False
            for content_index, content in enumerate(stream_chunks):
                self._write_sse({"id": completion_id, "object": "chat.completion.chunk", "created": created,
                    "model": model, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]})
                if not first_item_sent:
                    self.server.lifecycle_capture.mark(lifecycle, "first_item_sent")
                    first_item_sent = True
                delay = self.server._delay_seconds(self.server.config.after_first_chunk_delays, response_index)
                if content_index == 0 and delay > 0:
                    self._wait_delay(delay, lifecycle, "after_first_chunk")
            final_chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            if self.server.config.report_usage:
                final_chunk["usage"] = {"prompt_tokens": cache_result["prompt_tokens"], "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens, **({"prompt_tokens_details": {"cached_tokens": cache_result["cached_tokens"]}} if self.server.config.report_cache_usage else {})}
            self._write_sse(final_chunk)
            if not first_item_sent:
                self.server.lifecycle_capture.mark(lifecycle, "first_item_sent")
            self._write_sse("[DONE]")
        except OSError:
            self.server.lifecycle_capture.mark(lifecycle, "disconnected")
            raise
        finally:
            self.close_connection = True

    def do_GET(self) -> None:
        """Handle health and debug-state queries."""
        if self.path == "/health":
            self._write_json(200, {"status": "ok", "model": self.server.config.model})
            return
        if self.path == "/debug/state":
            state = self.server.prompt_cache.state()
            state.update(self.server.request_body_capture.state())
            state.update(self.server.lifecycle_capture.state())
            self._write_json(200, state)
            return
        self._error(404, "not found")

    def do_DELETE(self) -> None:
        """Clear debug state to support deterministic test reuse."""
        if self.path != "/debug/state":
            self._error(404, "not found")
            return
        if not self.server.reset_debug_state():
            self._error(409, "cannot reset debug state while completion handlers are active")
            return
        self._write_json(200, {"status": "cleared"})

    def do_POST(self) -> None:
        """Handle non-streaming OpenAI-compatible chat completions."""
        if self.path != "/v1/chat/completions":
            self._error(404, "not found")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.server.capture_body(b"", parse_error="invalid Content-Length")
            self._error(400, "request body must be valid JSON")
            return
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.server.capture_body(raw_body, parse_error=type(error).__name__)
            self._error(400, "request body must be valid JSON")
            return
        if not isinstance(payload, dict):
            self.server.capture_body(raw_body, parsed_body=payload)
            self._error(400, "request body must be a JSON object")
            return

        messages = payload.get("messages")
        if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
            self.server.capture_body(raw_body, parsed_body=payload)
            self._error(400, "messages must be a list of objects")
            return
        if (
            payload.get("stream")
            and self.server.config.stream_chunks is None
            and self.server.config.stream_response_chunks is None
        ):
            self.server.capture_body(raw_body, parsed_body=payload)
            self._error(400, "streaming is not supported")
            return

        cache_result, lifecycle = self.server.admit_completion(payload, raw_body)
        try:
            self._respond_completion(payload, cache_result, lifecycle)
        finally:
            capture = self.server.lifecycle_capture
            capture.mark(lifecycle, "waiting_phase", None)
            capture.mark(lifecycle, "handler_exit")
            capture.mark(lifecycle, "response_finished")

    def _respond_completion(self, payload: dict[str, Any], cache_result: dict[str, int], lifecycle: RequestHandle) -> None:
        """Write one admitted response without changing completion semantics."""
        if payload.get("stream"):
            scripted_errors = self.server.config.stream_http_error_responses or ()
            response_index = cache_result["request_number"] - 1
            if response_index < len(scripted_errors):
                status, message = scripted_errors[response_index]
                try:
                    self._error(status, message)
                except OSError:
                    self.server.lifecycle_capture.mark(lifecycle, "disconnected")
                    raise
                return
            self._write_stream(payload, cache_result, lifecycle)
            return

        response_index = cache_result["request_number"] - 1
        scripted_responses = self.server.config.tool_call_responses or ()
        tool_calls = scripted_responses[response_index] if response_index < len(scripted_responses) else None
        complete_replies = self.server.config.complete_response_replies or ()
        reply = complete_replies[response_index] if response_index < len(complete_replies) else self.server.config.reply
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": self.server.config.tool_call_response_content if tool_calls is not None else reply,
        }
        finish_reason = "stop"
        completion_text = reply
        if tool_calls is not None:
            assistant_message["tool_calls"] = list(tool_calls)
            finish_reason = "tool_calls"
            completion_text = json.dumps(assistant_message, ensure_ascii=False)
        completion_tokens = max(1, (len(completion_text) + self.server.config.chars_per_token - 1) // self.server.config.chars_per_token)
        prompt_tokens = cache_result["prompt_tokens"]
        response = {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()),
            "model": payload.get("model") or self.server.config.model,
            "choices": [{"index": 0, "message": assistant_message, "finish_reason": finish_reason}],
        }
        if self.server.config.report_usage:
            response["usage"] = {
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                **({"prompt_tokens_details": {"cached_tokens": cache_result["cached_tokens"]}} if self.server.config.report_cache_usage else {}),
            }
        delay = self.server._delay_seconds(self.server.config.complete_response_delays, response_index)
        if delay > 0:
            self._wait_delay(delay, lifecycle, "complete_response")
        try:
            self._write_json(200, response)
        except OSError:
            self.server.lifecycle_capture.mark(lifecycle, "disconnected")
            raise


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
    parser.add_argument("--request-body-capacity", type=int, default=32)
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
        request_body_capacity=args.request_body_capacity,
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
