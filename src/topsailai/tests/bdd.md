---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---
# BDD Tests

Behavior-driven tests for user-visible capabilities. This document holds the
project conventions for writing and extending BDD scenarios; `MEMO.md` only
references it.

## BDD Tests for LLM-Related Capabilities Must Drive `llm_mock_server`

**Date:** 2026-08-27

### Rule

Any BDD scenario that exercises a capability involving an actual LLM interaction must drive it through `tests/mock/llm_mock_server.py` over the real HTTP/SSE protocol (an OpenAI-compatible endpoint pointed at the in-test server via `OPENAI_API_BASE` / `OPENAI_BASE_URL`), instead of stubbing internal functions such as `LLMModel.chat()` or `_summarize_messages()`. This covers native `tool_calls`, context summarization, streaming responses, retry / first-byte-timeout handling, and LLM-generated session names.

### Why

Function-level stubs bypass the OpenAI client's response parsing, SSE chunk assembly, connection lifecycle, and request counting, so a scenario can stay green while the real wire-protocol path is broken. Driving the mock server keeps the client, transport, and parsing layers inside the assertion boundary.

### Scope / Applies to

- Native `tool_calls` request/response handling and the resulting tool-execution loop.
- Context summarization for both layers: User2Agent (`workspace/context/ctx_runtime.py`) and Agent2LLM (`workspace/context/agent2llm.py`).
- Streaming behavior, including chunk assembly, first-byte timeout, and hard-interrupt during a stream.
- Retry paths triggered by transient provider errors, and any other capability that issues a chat-completion request.
- Out of scope: pure local logic (threshold and watermark arithmetic, formatting, path resolution, parsing of already-obtained strings). Fast in-process tests for those remain the right choice and must not be converted into HTTP tests.

### Required for a new BDD scenario

- Reuse or extend an existing harness pattern: `cli/tests/bdd/hard_interrupt_mock_server_harness.py`, `cli/tests/bdd/streaming_mock_server_harness.py`; start the server with `create_server(MockServerConfig(port=0, ...))` on a daemon thread so ports never collide.
- Assert on the server side, not only on the returned object: request count and retained request records via `GET /debug/state` (or an HTTP-layer counting handler subclass, because requests rejected with `400` never reach prompt-cache accounting), and assert on the request body the client actually sent.
- Never contact a real external LLM endpoint; the only configured base URL is the loopback mock server.
- Close the exact server and thread owned by the scenario in teardown (`shutdown()`, `server_close()`, `join(timeout=...)`) so no child process or socket leaks; write any temporary artifact under `.tmp`.
- When the canned capability is insufficient for the scenario (for example a response carrying native `tool_calls` message fields, which the current `reply`/`stream_chunks` configuration does not emit), extend `tests/mock/llm_mock_server.py` rather than falling back to an internal stub.

### Note for maintainers

The summarize BDD suite (`cli/tests/bdd/features/summarize_feasibility.feature`, `summarize_head_retention.feature`, `summarize_session_retention.feature`, `summarize_thresholds.feature`, `summarize_watermark.feature`) is still in-process: its harnesses monkeypatch `_summarize_messages` and `count_tokens`, so no summarize scenario currently crosses the HTTP boundary. Treat it as a pending migration item — whenever summarize behavior is added or changed, the new/changed coverage must land on the mock-server path instead of extending the in-process stubs.
