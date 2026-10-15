---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# LLM Mock Server

`llm_mock_server.py` provides a reusable OpenAI-compatible chat-completions service for deterministic prompt-cache and opt-in streaming tests. It uses only the Python standard library.

## Cache Model

The server canonicalizes each message and compares complete messages from the beginning of the current request with every retained historical request whose ordered `tools` schema and `tool_choice` are identical. `usage.prompt_tokens_details.cached_tokens` is the token estimate for the best exact common message prefix plus the matching tools and tool-choice components. The estimate uses `ceil(canonical_component_characters / chars_per_token)` for each message and request component.

This is an intentionally idealized KV-cache model. Its cache identity includes canonicalized `messages`, ordered `tools`, and `tool_choice`; a tools or tool-choice mismatch produces no cache hit. Fields such as `model` remain intentionally ignored. Real providers can impose token-block minimums, TTLs, routing constraints, model-specific cache policies, serialization-order requirements, and broader cache-key scopes.

## Start

From the project folder:

```text
tests/mock/llm_mock_server.py --host 127.0.0.1 --port 8000
```

Available startup arguments:

- `--host` — bind host; default `127.0.0.1`
- `--port` — bind port; default `8000`; use `0` to select an available port
- `--model` — health endpoint model name
- `--reply` — canned assistant response
- `--chars-per-token` — positive deterministic token-estimation divisor
- `--cache-capacity` — positive number of retained prompts and request records

Arguments are explicit and therefore take precedence over process configuration. No new environment variables are required by the server.

## Connect TopsailAI

Set the existing OpenAI-compatible client configuration:

```text
OPENAI_API_BASE=http://127.0.0.1:8000/v1
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=mock
OPENAI_MODEL=topsailai-mock
LLM_RESPONSE_STREAM=0
```

`ai_base/llm_base.py` reads `OPENAI_API_BASE` when it constructs the OpenAI client. `OPENAI_BASE_URL` is included because model-selection commands keep both aliases synchronized, but the direct client currently uses `OPENAI_API_BASE`.

## Endpoints

- `POST /v1/chat/completions` — OpenAI-compatible non-streaming completion, plus opt-in SSE streaming for in-process test configuration
- `GET /health` — readiness and configured model
- `GET /debug/state` — cache capacity, retained prompt count, total request count, and bounded per-request cache results
- `DELETE /debug/state` — clear retained prompts and counters

Requests with `stream=true` return an explicit `400` error by default. In-process tests may opt in by constructing `MockServerConfig(stream_chunks=(...))`; each configured string is emitted as one OpenAI-compatible SSE content chunk, followed by a terminal usage chunk and `[DONE]`. The command-line interface remains non-streaming by default.

## Deterministic Transport Timing

In-process tests may delay transport phases per request without changing default behavior:

- `response_header_delays` — per-request seconds to wait before sending the SSE response headers.
- `first_chunk_delays` — per-request seconds to wait after headers before the first SSE item.
- `lifecycle_capacity` — bounded number of per-request lifecycle records retained for `/debug/state`.

Each accepted request has a bounded `RequestHandle` available through `server.lifecycle_capture.request_handle(number)`. An already-owned handle remains observable even after bounded history eviction; number-based lookup is bounded, and acceptance waits are scoped to the current reset epoch. Tests can use `wait_for_request(number)`, `handle.wait_for_phase("headers" | "first_item")`, and `handle.release_delay()` or `server.release_delay(number)` to synchronize and release configured waits. `DELETE /debug/state` returns 409 while a completion handler is active and does not reset its ordinal. `handle.response_finished` marks response work return, `handle.connection_closed` marks server-local socket shutdown, and `handle.wait_for_thread_exit(timeout)` confirms exit only after an external join; none prove the peer observed closure. `stop_handlers(timeout)` releases delays, shuts down owned sockets, joins workers, and raises if any worker remains alive. Direct-script and package-module invocation are both supported.

`/debug/state` also exposes `lifecycle_records` (accepted, headers sent, first item sent, handler exit, disconnect) and `dropped_lifecycle_count`. Unset delay configuration keeps every existing test immediate.

## Verify Cache Reuse

Send one request, then send another request with the same leading messages and an appended suffix. The second response reports non-zero `cached_tokens`. Change or insert a message before the previously matching prefix to observe a reduced or zero hit. Query `/debug/state` to inspect `cached_messages`, `cached_tokens`, and `prompt_tokens` for every retained request.
